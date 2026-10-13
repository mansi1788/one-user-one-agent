"""Independent exported-artifact checks; does not execute the outcome simulator."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from .ingestion import records
from .schemas import timestamp, IST
from .interventions import available


def validate_outputs(pack,out):
    pack,out=Path(pack),Path(out)
    actions=list(records(out/'actions.jsonl'));decisions=list(records(out/'decisions.jsonl'))
    arms={r['user_id']:r['arm'] for r in records(pack/'replay/arms.csv')}
    catalogue={r['title_id']:r for r in records(pack/'data/catalogue.csv')}
    config=json.loads((pack/'config/interventions.json').read_text())
    controls=list(records(pack/'replay/control_events.jsonl'))
    errors=[]; ids=set();triggers=set();caps=Counter()
    by_id={d['decision_id']:d for d in decisions if d.get('decision_id') and d.get('status')!='DUPLICATE'}
    for d in decisions:
        counts=d.get('budget',{}).get('counts',{})
        if counts.get('model',0)>8 or counts.get('tool',0)>20:
            errors.append({'reason':'Decision exceeded hard call budget','decision_id':d.get('decision_id')})
    for a in actions:
        ref=a.get('action_id','missing')
        def require(condition,reason):
            if not condition: errors.append({'action_id':ref,'reason':reason})
        require(all(k in a for k in ('action_id','decision_id','user_id','trigger_event_id','type','published_at')),'Required simulator fields')
        require(a['action_id'] not in ids and a['trigger_event_id'] not in triggers,'Duplicate action/trigger')
        ids.add(a['action_id']);triggers.add(a['trigger_event_id'])
        require(arms.get(a['user_id'])=='agent','Holdout or missing arm')
        at=timestamp(a['published_at']);kind=a['type']
        d=by_id.get(a['decision_id'])
        require(bool(d and d['user_id']==a['user_id'] and d['trigger_event_id']==a['trigger_event_id']),'Action must link to its audited decision')
        if d:require(0<=(at-timestamp(d['deliver_at'])).total_seconds()<=60,'Publication latency bound')
        require(kind in ('home_page','push','whatsapp','in_app_message'),'Supported action type')
        if kind=='home_page':
            titles=([a['hero_title_id']] if a.get('hero_title_id') else [])+[t for r in a['rows'] for t in r['title_ids']]
            require(len(a['rows'])<=config['home_page']['rows']['max_rows'],'Row count')
            for r in a['rows']:
                require(config['home_page']['rows']['min_titles_per_row']<=len(r['title_ids'])<=config['home_page']['rows']['max_titles_per_row'],'Row title count')
        else:
            titles=[a['title_id']];send=timestamp(a['send_at'])
            require(send>=at,'Backdated send')
            scope='outbound' if kind in ('push','whatsapp') else 'in_app'
            key=(a['user_id'],send.astimezone(IST).date().isoformat(),scope);caps[key]+=1
            require(caps[key]<=(1 if scope=='outbound' else config['in_app_message']['max_per_day']),'Exported message cap')
            if scope=='outbound':require(8<=send.astimezone(IST).hour<22,'Quiet hours')
            at=send
        rows=[catalogue[t] for t in titles if t in catalogue]
        require(len(rows)==len(titles),'Unknown catalogue title')
        require(len({t['content_slug'] for t in rows})==len(titles),'Duplicate content slug')
        for title in rows:
            require(available(title,at.isoformat()),'Unavailable title')
            require(not any(c['type']=='title_withdrawn' and c['title_id']==title['title_id'] and timestamp(c['at'])<=at for c in controls),'Withdrawn title')
            if kind=='home_page':require(title['dialect']==a['dialect'],'Page dialect mismatch')
    old=pack/'sample_run/phase1_audit_before.json'
    unchanged=None
    if old.exists():
        original=json.loads(old.read_text())['files']
        unchanged=all(hashlib.sha256((pack/name).read_bytes()).hexdigest()==row['sha256'] for name,row in original.items())
        if not unchanged:errors.append({'reason':'Supplied pack file hash changed'})
    return {'valid':not errors,'actions':len(actions),'decisions':len(decisions),'pack_unchanged':unchanged,'errors':errors}
