"""Observed goal attainment; source events never imply individual causal attribution."""
import hashlib
import json
import os
import runpy
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from .ingestion import load_goals, records
from .schemas import IST, timestamp
from .store import encode

DDL='''
CREATE TABLE IF NOT EXISTS outcome_runs(run_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observed_outcomes(run_id TEXT,event_id TEXT,user_id TEXT,received_at TEXT,payload TEXT,source_ref TEXT,PRIMARY KEY(run_id,event_id));
CREATE TABLE IF NOT EXISTS outcome_deliveries(run_id TEXT,source_ref TEXT,payload TEXT,PRIMARY KEY(run_id,source_ref));
CREATE TABLE IF NOT EXISTS goal_outcomes(run_id TEXT,goal_instance_id INTEGER REFERENCES goals(id),user_id TEXT,verdict TEXT,payload TEXT,PRIMARY KEY(run_id,goal_instance_id));
CREATE TABLE IF NOT EXISTS viewer_learning(run_id TEXT,goal_instance_id INTEGER,user_id TEXT,payload TEXT,PRIMARY KEY(run_id,goal_instance_id));
'''


def atomic_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(text,encoding='utf-8');os.replace(temp,path)


def validate_simulator(pack,sim,actions):
    pack,sim=Path(pack),Path(sim)
    contract=runpy.run_path(str(pack/'simulator/simulate_outcomes.py'),run_name='one_agent_simulator_contract')
    start=contract['REPLAY_START'];end=start+timedelta(days=contract['HORIZON_DAYS']+1)
    report=json.loads((sim/'simulator_report.json').read_text(encoding='utf-8'))
    triggers=list(records(pack/'replay/triggers.jsonl'));users={r['user_id'] for r in triggers}
    arms=list(records(pack/'replay/arms.csv'));arm_map={r['user_id']:r['arm'] for r in arms}
    if len(arm_map)!=len(arms) or set(arm_map.values())-{'agent','holdout'}:raise ValueError('Invalid randomized arm identities')
    source=list(records(sim/'outcome_events.jsonl'));ids=set();events=defaultdict(list);previous=None;canonical={}
    catalogue={r['title_id']:r for r in records(pack/'data/catalogue.csv')}
    episodes={r['episode_id']:r['content_slug'] for r in records(pack/'data/episodes.csv')}
    live=defaultdict(list)
    for r in records(pack/'replay/live_events.jsonl'):live[r['event_id']].append(r)
    plans={r['plan_id']:r['price_inr'] for r in json.loads((pack/'config/pricing.json').read_text())['plans']}
    allowed={'app_open','home_page_shown','play_started','episode_completed','purchase_completed','message_failed','message_delivered','message_clicked','notification_opt_out'}
    published=list(records(actions));action_map={r['action_id']:r for r in published}
    if len(action_map)!=len(published):raise ValueError('Duplicate published action ID')
    for n,row in enumerate(source,1):
        required={'event_id','user_id','event','received_at','occurred_at','sent_at','session_id','properties'}
        if not required<=row.keys() or not isinstance(row['properties'],dict):raise ValueError(f'Invalid simulator event line {n}')
        at=timestamp(row['received_at'])
        if (row['event_id'] in ids and row['event_id'] not in live) or row['user_id'] not in users or row['user_id'] not in arm_map:raise ValueError('Duplicate/unknown outcome identity')
        if previous and at<previous:raise ValueError('Unsorted outcome receipt timestamps')
        if not timestamp(start.isoformat())<=at<timestamp(end.isoformat()):raise ValueError('Outcome outside simulator horizon')
        previous=at;ids.add(row['event_id'])
        if row['event_id'] in live:
            if row not in live[row['event_id']]:raise ValueError('Scripted event differs from supplied live event')
        elif row['event'] not in allowed:raise ValueError('Unsupported generated event')
        props=row['properties'];tid=props.get('title_id');ep=props.get('episode_id')
        if tid and tid not in catalogue:raise ValueError('Unknown outcome title')
        if row['event'] in ('play_started','episode_completed') and (not tid or not ep or episodes.get(ep)!=catalogue[tid]['content_slug']):raise ValueError('Unknown or mismatched outcome episode')
        if row['event']=='purchase_completed' and (props.get('plan_id') not in plans or props.get('price_inr')!=plans[props['plan_id']] or not isinstance(props.get('is_trial'),bool)):
            raise ValueError('Unsupported outcome purchase')
        if row['event']=='home_page_shown' and props.get('personalised'):
            action=action_map.get(props.get('page_action_id'))
            if not action or action['user_id']!=row['user_id'] or arm_map[row['user_id']]!='agent':raise ValueError('Unattributable personalised exposure')
        ref=f'{sim.name}/outcome_events.jsonl:{n}:event:{row["event_id"]}'
        if row['event_id'] in canonical:
            canonical[row['event_id']]['_deliveries'].append({'source_ref':ref,'payload':row})
        else:
            event=dict(row);event['_source_ref']=ref;event['_deliveries']=[{'source_ref':ref,'payload':row}]
            canonical[row['event_id']]=event;events[row['user_id']].append(event)
    expected_live={eid for eid,versions in live.items() if versions[0]['user_id'] in users}
    if not expected_live<=ids:raise ValueError('Scripted outcome events missing')
    if report['events_written']!=len(source) or report['triggered_users']!=len(users):raise ValueError('Simulator report/file count mismatch')
    if report['counts'].get('actions_total',0)!=len(published):raise ValueError('Simulator did not consume these actions')
    if report['policy_problem_count'] or report['policy_problems']:raise ValueError('Simulator reports policy violations')
    if report['counts'].get('home_page_accepted',0)!=sum(a['type']=='home_page' for a in published):raise ValueError('Simulator rejected a published page')
    manifest={'coverage_start':start.isoformat(),'coverage_end_exclusive':end.isoformat(),'observed_users':sorted(users),
        'events':len(source),'unique_events':len(ids),'duplicate_deliveries':len(source)-len(ids),'simulator_report':report,'coverage_basis':'Supplied simulator runs replay sessions plus days 1..HORIZON_DAYS for each scripted triggered user; no coverage for other randomized users',
        'hashes':{str(p.relative_to(pack)) if p.is_relative_to(pack) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (pack/'simulator/simulate_outcomes.py',sim/'outcome_events.jsonl',sim/'simulator_report.json',Path(actions))}}
    return manifest,events,catalogue


def judge_goal(goal,events,rules,controls,catalogue,coverage,*,as_of=None,cancelled_at=None):
    """Known positive signals can succeed early; negative judgments require complete follow-up."""
    payload=json.loads(goal['payload']) if isinstance(goal.get('payload'),str) else goal.get('payload',{})
    at=timestamp(as_of or coverage['coverage_end_exclusive']);start=timestamp(goal['started_at']);deadline=timestamp(goal['deadline'])
    rule=next((g for g in rules['goals'] if g['goal_id']==goal['goal_id']),None)
    result={'goal_instance_id':goal['id'],'user_id':goal['user_id'],'goal_id':goal['goal_id'],'rule_version':goal['rule_version'],
        'started_at':start.isoformat(),'deadline':deadline.isoformat(),'evaluated_through':at.isoformat(),
        'observation_window':{'start_inclusive':start.isoformat(),'deadline_inclusive':deadline.isoformat(),'coverage_start':coverage['coverage_start'],'coverage_end_exclusive':coverage['coverage_end_exclusive']},
        'verdict':'INCONCLUSIVE','evidence':[],'rule_evidence':['config/goals.json:'+goal['goal_id']],
        'attribution':'Viewer-specific observed goal attainment; individual causal effect of the agent is not identified',
        'prior_lifecycle_status':goal['status']}
    def finish(verdict,reason,evidence=()):
        result.update(verdict=verdict,reason=reason,evidence=list(evidence));return result
    if not rule or goal['rule_version']!=rules['version']:return finish('INCONCLUSIVE','Missing historical goal-rule version; no rule is invented')
    if deadline!=start+timedelta(hours=rule['success']['window_hours']):return finish('INCONCLUSIVE','Stored deadline differs from the committed rule window')
    success=dict(rule['success']);stop=min(deadline,at)
    if cancelled_at:stop=min(stop,timestamp(cancelled_at))
    for n,control in enumerate(controls,1):
        if control['type']=='goal_rule_corrected' and control['goal_id']==goal['goal_id'] and timestamp(control['at'])<=min(deadline,at) and (not cancelled_at or timestamp(control['at'])<timestamp(cancelled_at)):
            success.update(control['new_success']);result['rule_evidence'].append(f'replay/control_events.jsonl:{n}')
    result['success_signal']=success
    result['recorded_success_signal']=payload.get('success')
    gid=goal['goal_id'];condition=success.get('condition');event_name=success.get('event')
    expected={'G01':('play_started',{'any title'}),'G02':('episode_completed',{'any episode'}),
        'G03':(event_name,{'on a later IST calendar day than the goal start','on a later IST calendar day within the window'}),
        'G04':('purchase_completed',{'is_trial = false'}),'G05':('purchase_completed',{'is_trial = false'}),
        'G08':('play_started',{'a title released in the 30 days before the goal start'}),
        'G09':('play_started',{'on 3 distinct IST days'}),'G12':('play_started',{'any title'})}
    if gid not in expected or event_name!=expected[gid][0] or condition not in expected[gid][1] or (gid=='G03' and event_name not in ('app_open','play_started')):
        return finish('INCONCLUSIVE','Unsupported or disabled success definition; G06/G07/G10/G11 are not judged by invented signals')
    matched=[];ambiguous=[]
    for e in events:
        if e['user_id']!=goal['user_id'] or e['event']!=event_name:continue
        when=timestamp(e['received_at'])
        if not start<=when<=stop:continue
        ok=True
        if gid in ('G04','G05'):
            if not isinstance(e['properties'].get('is_trial'),bool):ambiguous.append(e);continue
            ok=e['properties']['is_trial'] is False
        elif gid=='G03':ok=when.astimezone(IST).date()>start.astimezone(IST).date()
        elif gid=='G08':
            title=catalogue.get(e['properties'].get('title_id'))
            if not title or not title.get('release_date'):ambiguous.append(e);continue
            days=(start.date()-timestamp(title['release_date']+'T00:00:00Z').date()).days;ok=0<=days<=30
        if ok:matched.append(e)
    enough=len({timestamp(e['received_at']).astimezone(IST).date() for e in matched})>=3 if gid=='G09' else bool(matched)
    refs=lambda rows:[e.get('_source_ref','event:'+e['event_id']) for e in rows]
    if enough:return finish('SUCCEEDED','Required observed success signal occurred within the committed goal window',refs(matched))
    if ambiguous:return finish('INCONCLUSIVE','Candidate success events have missing condition fields',refs(ambiguous))
    covered=goal['user_id'] in coverage['observed_users'] and timestamp(coverage['coverage_start'])<=start and deadline<timestamp(coverage['coverage_end_exclusive']) and at>=deadline
    if cancelled_at and timestamp(cancelled_at)<deadline:return finish('INCONCLUSIVE','Goal ownership was cancelled before its complete deadline; follow-up censored',refs(matched))
    if not covered:return finish('INCONCLUSIVE','Observation window or viewer coverage is incomplete; absence is not failure',refs(matched))
    return finish('FAILED','Complete bounded observation window contains insufficient qualifying success signals',refs(matched))


def measure(store,pack,sim,out,*,as_of=None):
    manifest,events,catalogue=validate_simulator(pack,sim,Path(out)/'actions.jsonl')
    manifest['evaluated_through']=as_of or manifest['coverage_end_exclusive']
    rules=load_goals(pack);controls=list(records(Path(pack)/'replay/control_events.jsonl'))
    goals=[dict(r) for r in store.connection.execute('SELECT * FROM goals ORDER BY id')]
    # Preserve replay lifecycle separately: outcome closure must not change repeat judgments.
    for g in goals:
        p=json.loads(g['payload']);g['status']=p.get('_replay_lifecycle_status',g['status'])
    inputs={'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'manifest':manifest,'rules':rules,'controls':controls,'as_of':as_of or manifest['coverage_end_exclusive'],
        'goals':[{k:g[k] for k in ('id','user_id','goal_id','rule_version','started_at','deadline','status')} for g in goals]}
    run_id='O-'+hashlib.sha256(encode(inputs).encode()).hexdigest()
    store.connection.executescript(DDL)
    by_user=defaultdict(list)
    for g in goals:by_user[g['user_id']].append(g)
    judgments=[]
    for g in goals:
        later=[x['started_at'] for x in by_user[g['user_id']] if timestamp(x['started_at'])>timestamp(g['started_at'])]
        cancel=min(later,key=timestamp) if g['status']=='cancelled' and later else None
        if g['status']=='cancelled' and cancel is None:cancel=g['started_at']
        result=judge_goal(g,events[g['user_id']],rules,controls,catalogue,manifest,as_of=as_of,cancelled_at=cancel)
        result['outcome_run_id']=run_id;judgments.append(result)
    with store.connection:
        store.connection.execute('INSERT OR IGNORE INTO outcome_runs VALUES (?,?)',(run_id,encode(inputs)))
        for user,rows in events.items():
            for e in rows:
                store.connection.execute('INSERT OR IGNORE INTO observed_outcomes VALUES (?,?,?,?,?,?)',(run_id,e['event_id'],user,e['received_at'],encode({k:v for k,v in e.items() if not k.startswith('_')}),e['_source_ref']))
                for delivery in e['_deliveries']:
                    store.connection.execute('INSERT OR IGNORE INTO outcome_deliveries VALUES (?,?,?)',(run_id,delivery['source_ref'],encode(delivery['payload'])))
        for g,result in zip(goals,judgments):
            store.connection.execute('INSERT OR IGNORE INTO goal_outcomes VALUES (?,?,?,?,?)',(run_id,g['id'],g['user_id'],result['verdict'],encode(result)))
            learning={'goal_instance_id':g['id'],'goal_id':g['goal_id'],'outcome_run_id':run_id,'verdict':result['verdict'],'evidence':result['evidence'],
                'lesson':'Observed goal attainment is not proof the intervention caused it; preserve the evidence and bounded window',
                'reason':result['reason'],'success_signal':result.get('success_signal'),
                'next_step':'Re-evaluate eligibility before choosing another goal; do not repeat a completed goal without new evidence' if result['verdict']=='SUCCEEDED' else 'Revisit the plan using new evidence; failure does not prove disinterest or harm' if result['verdict']=='FAILED' else 'Wait for missing observations or rule clarification; do not count this as failure'}
            store.connection.execute('INSERT OR IGNORE INTO viewer_learning VALUES (?,?,?,?)',(run_id,g['id'],g['user_id'],encode(learning)))
            payload=json.loads(g['payload']);payload['_replay_lifecycle_status']=g['status']
            store.connection.execute('UPDATE goals SET payload=? WHERE id=?',(encode(payload),g['id']))
            if result['verdict'] in ('SUCCEEDED','FAILED') and g['status']=='open':
                store.connection.execute('UPDATE goals SET status=? WHERE id=?',(result['verdict'].lower(),g['id']))
                store.connection.execute("UPDATE plans SET status='closed' WHERE goal_instance_id=?",(g['id'],))
    atomic_write(Path(out)/'outcomes.jsonl',''.join(encode(r)+'\n' for r in judgments))
    # Augment rather than replace the replay's provenance/fact exports.
    for user in manifest['observed_users']:
        path=Path(out)/'viewer_state'/(hashlib.sha256(user.encode()).hexdigest()+'.json')
        state=json.loads(path.read_text()) if path.exists() else {'user_id':user,'facts':[]}
        state['active_goal_plan']=store.active_goal_plan(user)
        state['outcomes']=[r for r in judgments if r['user_id']==user]
        state['learning']=[json.loads(r[0]) for r in store.connection.execute('SELECT payload FROM viewer_learning WHERE run_id=? AND user_id=? ORDER BY goal_instance_id',(run_id,user))]
        atomic_write(path,encode(state))
    summary={'outcome_run_id':run_id,'goal_instances':len(judgments),'viewers_with_goals':len(by_user),'counts':dict(Counter(r['verdict'] for r in judgments)),
        'by_goal':{gid:dict(Counter(r['verdict'] for r in judgments if r['goal_id']==gid)) for gid in sorted({r['goal_id'] for r in judgments})},'manifest':manifest}
    atomic_write(Path(out)/'outcome_validation.json',json.dumps(summary,indent=2))
    return summary,events
