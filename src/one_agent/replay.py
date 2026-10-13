"""Delivery-ordered local replay; durable checkpoints and simulated publication only."""
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from .budget import Budget, BudgetExceeded
from .ingestion import records
from .planner import plan
from .provider import MockProvider, consult
from .publisher import DDL, publish
from .runtime import effective_goals
from .schemas import timestamp
from .store import Store, encode
from .verifier import verify

class Replay:
    def __init__(self,store,pack,*,max_model_calls=8,max_tool_calls=20,max_seconds=60,
                 stale_seconds=86400,store_read_timeout=.25,clock=time.monotonic,sleep=time.sleep,channel="auto"):
        if not 0<=max_model_calls<=8 or not 0<=max_tool_calls<=20 or not 0<max_seconds<=60:
            raise ValueError("Replay limits must fit 8 model calls, 20 tool calls and 60 seconds")
        if stale_seconds<0 or store_read_timeout<0:
            raise ValueError("Replay time thresholds must be nonnegative")
        self.store,self.pack=store,Path(pack)
        self.clock,self.sleep=clock,sleep
        self.settings=dict(max_model_calls=max_model_calls,max_tool_calls=max_tool_calls,max_seconds=max_seconds,
                           stale_seconds=stale_seconds,store_read_timeout=store_read_timeout)
        if channel!="auto": self.settings["channel"]=channel
        store.connection.executescript(DDL)
        store.replay_mode=True
        store.applied_controls=[json.loads(r[0]) for r in store.connection.execute('SELECT payload FROM replay_controls ORDER BY rowid')]
        store.is_published=lambda approval: bool(store.connection.execute('SELECT 1 FROM published_actions WHERE approval_id=?',(approval,)).fetchone())
        store.episode_cache=[json.loads(r[0]) for r in store.connection.execute('SELECT payload FROM episodes')]
        self.provider=MockProvider(pack)
        self.items=[]
        for priority,(kind,name,field) in enumerate((('control','control_events.jsonl','at'),('live','live_events.jsonl','deliver_at'),('trigger','triggers.jsonl','deliver_at'))):
            for n,row in enumerate(records(self.pack/'replay'/name),1):
                self.items.append((timestamp(row[field]),priority,n,kind,f'{kind}:{n}',row))
        self.items.sort(key=lambda x:x[:3])
        fingerprint=hashlib.sha256(encode({'settings':self.settings,'items':self.items_serialized(),
            'files':{str(p.relative_to(self.pack)):hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ('data','config','replay') for p in sorted((self.pack/folder).glob('*')) if p.is_file()}}).encode()).hexdigest()
        old=store.connection.execute("SELECT value FROM metadata WHERE key='replay_fingerprint'").fetchone()
        if old and old[0]!=fingerprint: raise ValueError('Replay inputs/settings changed; use a fresh database')
        with store.connection:
            store.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('replay_fingerprint',?)",(fingerprint,))
        self.done={r[0] for r in store.connection.execute('SELECT item_key FROM replay_items')}
        self.arrivals={r[0] for r in store.connection.execute('SELECT item_key FROM replay_arrivals')}
        self.available=None
        saved=store.connection.execute("SELECT value FROM metadata WHERE key='replay_available'").fetchone()
        if saved: self.available=timestamp(saved[0])

    def items_serialized(self):
        return [[a.isoformat(),b,c,d,e,f] for a,b,c,d,e,f in self.items]

    def arrived(self,item):
        delivery,_,_,kind,key,row=item
        if key in self.done: return False
        if kind=='trigger':
            if key in self.arrivals:return False
            with self.store.connection:
                self.store.add_event(row,'replay/triggers.jsonl')
                self.store.connection.execute('INSERT INTO replay_arrivals VALUES (?)',(key,))
            self.arrivals.add(key)
            return True
        with self.store.connection:
            if kind=='live': self.store.add_event(row,'replay/live_events.jsonl')
            else: self.control(key,row)
            self.store.connection.execute('INSERT INTO replay_items VALUES (?,?,?,?,NULL)',(key,kind,delivery.isoformat(),encode(row)))
        self.done.add(key)
        return True

    def drain(self,at):
        changed=False
        for item in self.items:
            if item[0]>timestamp(at): break
            changed=self.arrived(item) or changed
        return changed

    def control(self,key,row):
        s=self.store
        s.connection.execute('INSERT INTO replay_controls VALUES (?,?)',(key,encode(row)))
        s.applied_controls.append(row)
        if row['type']=='goal_rule_corrected':
            config=effective_goals(s,self.pack)
            rule=next(g for g in config['goals'] if g['goal_id']==row['goal_id'])
            s.connection.execute('UPDATE goal_rules SET payload=? WHERE version=? AND goal_id=?',(encode(rule),config['version'],row['goal_id']))
            for goal in s.connection.execute("SELECT id,payload FROM goals WHERE goal_id=? AND status='open'",(row['goal_id'],)).fetchall():
                payload=json.loads(goal['payload']); payload['success']=rule['success']; payload['rule_revision']=key
                s.connection.execute('UPDATE goals SET payload=? WHERE id=?',(encode(payload),goal['id']))
                for p in s.connection.execute("SELECT id,payload FROM plans WHERE goal_instance_id=? AND status='active'",(goal['id'],)).fetchall():
                    value=json.loads(p['payload']); value['goal']['success']=rule['success'];value['goal']['rule_revision']=key
                    s.connection.execute('UPDATE plans SET payload=? WHERE id=?',(encode(value),p['id']))
        # Withdrawal is authoritative through reached controls, checked on every publication.

    def trigger(self,item):
        delivery,_,_,_,key,event=item
        prior=self.store.connection.execute('SELECT payload FROM replay_results WHERE trigger_id=?',(event['event_id'],)).fetchone()
        if prior:
            with self.store.connection:
                self.store.add_event(event,'replay/triggers.jsonl')
            return {'status':'DUPLICATE','trigger_event_id':event['event_id'],'original_decision_id':json.loads(prior[0]).get('decision_id'),'deliver_at':delivery.isoformat(),'user_id':event['user_id']}
        start=self.clock(); queue=max(0,(self.available-delivery).total_seconds()) if self.available else 0
        def now(): return (delivery+timedelta(seconds=queue+self.clock()-start)).isoformat()
        budget=Budget(self.settings['max_model_calls'],self.settings['max_tool_calls'],self.settings['max_seconds'],clock=self.clock)
        budget.started-=queue
        result={'trigger_event_id':event['event_id'],'user_id':event['user_id'],'deliver_at':delivery.isoformat(),'queue_seconds':queue,'published':False,'status':'NO_ACTION'}
        def hook(kind,name,entry):
            for control in self.store.applied_controls:
                if 'dependency' not in control or not(timestamp(control['at'])<=timestamp(now())<timestamp(control['until'])): continue
                if kind=='model' and control['dependency']=='model_provider': raise TimeoutError('Reached model_provider HTTP 503 control')
                if name in ('plan_viewer','read_authoritative_viewer_and_catalogue','publication_authoritative_reads') and control['dependency']=='user_data_store':
                    entry['dependency_control']=control; entry['client_read_timeout_seconds']=self.settings['store_read_timeout']
                    self.sleep(self.settings['store_read_timeout'])
                    raise TimeoutError('Store read exceeded bounded client deadline; no publication')
        budget.before_call=hook
        try:
            self.drain(now())
            with self.store.connection:
                budget.call('tool','ingest_trigger',self.store.add_event,event,'replay/triggers.jsonl')
            # Device times cannot prove offline status. Conservatively suppress potentially old requests.
            uncertain=(delivery-timestamp(event['occurred_at'])).total_seconds()>self.settings['stale_seconds']
            channel='no_action' if uncertain else self.settings.get('channel','auto')
            existing=self.store.connection.execute('SELECT payload FROM decisions WHERE trigger_event_id=? ORDER BY decided_at LIMIT 1',(event['event_id'],)).fetchone()
            def fallback():
                return json.loads(existing[0]) if existing else budget.call('tool','plan_viewer',plan,self.store,self.pack,event['user_id'],now(),
                    channel=channel,request_id=event['event_id'],trigger_event_id=event['event_id'])
            advice=consult(self.provider,event['event_id'],{'user_id':event['user_id'],'untrusted':True},budget,fallback)
            decision=advice['proposal']; result['model']={k:v for k,v in advice.items() if k not in ('proposal','budget')}
            if 'decision_id' not in decision: raise BudgetExceeded('No deterministic decision within budget')
            result.update(decision_id=decision['decision_id'],decision=decision)
            if uncertain: result['stale_reason']='Potential offline buffering or device clock skew; device time untrusted, request conservatively suppressed'
            recovered=self.store.connection.execute('SELECT payload FROM published_actions WHERE decision_id=?',(decision['decision_id'],)).fetchone()
            if recovered:
                action=json.loads(recovered[0]);result.update(status='PUBLISHED',published=True,action=action,recovered=True)
            else:
                self.drain(now())
                verdict=verify(self.store,self.pack,decision,now(),budget=budget);result['verification']=verdict
                if verdict['verdict']=='APPROVED':
                    self.drain(now())
                    second=verify(self.store,self.pack,decision,now(),budget=budget);result['publication_verification']=second
                    if second['verdict']=='APPROVED':
                        action,checks=publish(self.store,self.pack,decision,second['approval_id'],now,budget,self.drain)
                        result['publication_checks']=checks
                        if action: result.update(status='PUBLISHED',published=True,action=action)
                if not result['published']:
                    result['reason']=decision.get('no_action_reason') or '; '.join(verdict['reasons']) or 'Publication revalidation failed'
        except (TimeoutError,BudgetExceeded,ValueError,RuntimeError,sqlite3.Error) as exc:
            result.update(reason=str(exc),error=type(exc).__name__)
        result['processing_seconds']=max(0,self.clock()-start)
        result['total_seconds']=queue+result['processing_seconds']
        result['budget']=budget.snapshot()
        if result.get('action'):
            result['publication_latency_seconds']=(timestamp(result['action']['published_at'])-delivery).total_seconds()
        self.available=delivery+timedelta(seconds=result['total_seconds'])
        with self.store.connection:
            self.store.connection.execute('INSERT INTO replay_results VALUES (?,?)',(event['event_id'],encode(result)))
            self.store.connection.execute('INSERT OR IGNORE INTO replay_items VALUES (?,?,?,?,?)',(key,'trigger',delivery.isoformat(),encode(event),encode(result)))
            self.store.connection.execute("INSERT OR REPLACE INTO metadata VALUES ('replay_available',?)",(self.available.isoformat(),))
        return result

    def run(self,out,progress=True):
        for index,item in enumerate(self.items):
            if item[4] in self.done: continue
            if item[3]!='trigger': self.arrived(item);continue
            result=self.trigger(item)
            with self.store.connection:
                self.store.connection.execute('INSERT OR IGNORE INTO replay_items VALUES (?,?,?,?,?)',(item[4],item[3],item[0].isoformat(),encode(item[5]),encode(result)))
            self.done.add(item[4])
            if progress and index%100==0: print(f'Replay {index}/{len(self.items)}',file=sys.stderr,flush=True)
        return self.export(out)

    def export(self,out):
        out=Path(out);out.mkdir(parents=True,exist_ok=True)
        decisions=[]
        # Complete failure audits even when execution stopped before the planner could persist one.
        with self.store.connection:
            for row in self.store.connection.execute("SELECT item_key,result FROM replay_items WHERE kind='trigger' ORDER BY delivery_at,item_key").fetchall():
                d=json.loads(row['result'])
                if d['status']=='DUPLICATE' and not d.get('original_decision_id'):
                    d['original_decision_id']='R-'+hashlib.sha256(d['trigger_event_id'].encode()).hexdigest()
                    self.store.connection.execute('UPDATE replay_items SET result=? WHERE item_key=?',(encode(d),row['item_key']))
                if d.get('stale_reason') and not d.get('published'):
                    d['reason']=d['stale_reason']
                    self.store.connection.execute('UPDATE replay_items SET result=? WHERE item_key=?',(encode(d),row['item_key']))
                    self.store.connection.execute('UPDATE replay_results SET payload=? WHERE trigger_id=?',(encode(d),d['trigger_event_id']))
                if d['status']!='DUPLICATE' and not d.get('decision_id'):
                    d['decision_id']='R-'+hashlib.sha256(d['trigger_event_id'].encode()).hexdigest()
                    at=(timestamp(d['deliver_at'])+timedelta(seconds=d['total_seconds'])).isoformat()
                    audit={'decision_id':d['decision_id'],'user_id':d['user_id'],'trigger_event_id':d['trigger_event_id'],
                        'as_of':at,'status':'NO_ACTION','published':False,'goal':None,
                        'proposal':{'type':'NO_ACTION','payload':None,'reason':d.get('reason')},
                        'no_action_reason':d.get('reason'),'evidence':['replay/triggers.jsonl:'+d['trigger_event_id']],
                        'error':d.get('error'),'budget':d['budget']}
                    self.store.viewer(d['user_id'])
                    self.store.connection.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?)',
                        (d['decision_id'],d['user_id'],d['trigger_event_id'],at,encode(audit)))
                    d['decision']=audit
                    self.store.connection.execute('UPDATE replay_items SET result=? WHERE item_key=?',(encode(d),row['item_key']))
                    self.store.connection.execute('UPDATE replay_results SET payload=? WHERE trigger_id=?',(encode(d),d['trigger_event_id']))
                decisions.append(d)
        actions=[json.loads(r[0]) for r in self.store.connection.execute('SELECT payload FROM published_actions ORDER BY published_at,action_id')]
        def write(path,value):
            temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(value,encoding='utf-8');os.replace(temp,path)
        write(out/'decisions.jsonl',''.join(json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n' for d in decisions))
        write(out/'actions.jsonl',''.join(encode(a)+'\n' for a in actions))
        unique=[d for d in decisions if d['status']!='DUPLICATE']
        def distribution(values):
            values=sorted(values)
            return {**{f'p{p}':values[min(len(values)-1,int((len(values)-1)*p/100))] if values else 0 for p in (50,95,99)},'max':max(values,default=0)}
        report={'trigger_deliveries':len(decisions),'unique_triggers':len(unique),'duplicates':len(decisions)-len(unique),
            'actions':len(actions),'action_types':dict(Counter(a['type'] for a in actions)),
            'no_action_reasons':dict(Counter('; '.join(dict.fromkeys(d.get('reason','Unspecified').split('; '))) for d in unique if not d['published'])),
            'failures':dict(Counter(d['error'] for d in unique if d.get('error'))),
            'processing_seconds':distribution([d['processing_seconds'] for d in unique]),
            'queue_seconds':distribution([d['queue_seconds'] for d in unique]),
            'total_seconds':distribution([d['total_seconds'] for d in unique]),
            'publication_latency_seconds':distribution([d['publication_latency_seconds'] for d in unique if 'publication_latency_seconds' in d]),
            'exceeding_60_seconds':sum(d['total_seconds']>60 for d in unique),'exceeding_5_minutes':sum(d['total_seconds']>300 for d in unique),
            'live_events':sum(i[3]=='live' for i in self.items),'controls':len(self.store.applied_controls),'settings':self.settings}
        arms={r['user_id']:r['arm'] for r in records(self.pack/'replay/arms.csv')}
        report['holdout_actions']=sum(arms.get(a['user_id'])!='agent' for a in actions)
        write(out/'latency_report.json',json.dumps(report,indent=2))
        states=out/'viewer_state';states.mkdir(exist_ok=True)
        for user in sorted({d['user_id'] for d in decisions}):
            facts=[json.loads(r[0]) for r in self.store.connection.execute('SELECT payload FROM facts WHERE user_id=? AND as_of=(SELECT MAX(as_of) FROM facts WHERE user_id=?)',(user,user))]
            write(states/(hashlib.sha256(user.encode()).hexdigest()+'.json'),encode({'user_id':user,'facts':facts,'active_goal_plan':self.store.active_goal_plan(user)}))
        return report

def run_replay(pack,db,out,**settings):
    with Store(db) as store:
        if not store.connection.execute('SELECT 1 FROM goal_rules LIMIT 1').fetchone(): store.import_pack(pack)
        return Replay(store,pack,**settings).run(out)
