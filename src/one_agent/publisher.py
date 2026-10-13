"""Durable, local-only publication. JSONL is a rebuildable ledger export."""
import hashlib
from .store import encode
from .schemas import timestamp, IST
from .verifier import _authorities, _context, _validate

DDL = '''
CREATE TABLE IF NOT EXISTS replay_arrivals(item_key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS replay_items(item_key TEXT PRIMARY KEY,kind TEXT,delivery_at TEXT,payload TEXT,result TEXT);
CREATE TABLE IF NOT EXISTS replay_controls(item_key TEXT PRIMARY KEY,payload TEXT);
CREATE TABLE IF NOT EXISTS replay_results(trigger_id TEXT PRIMARY KEY,payload TEXT);
CREATE TABLE IF NOT EXISTS outbox(action_id TEXT PRIMARY KEY,decision_id TEXT UNIQUE,approval_id TEXT,status TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS published_actions(action_id TEXT PRIMARY KEY,decision_id TEXT UNIQUE,trigger_id TEXT UNIQUE,approval_id TEXT,published_at TEXT,payload TEXT);
'''

def action_for(decision, at):
    raw=decision['proposal']['payload']; kind=decision['proposal']['type']
    result={k:decision[k] for k in ('decision_id','user_id','trigger_event_id')}
    result.update(action_id='PUB-'+hashlib.sha256(decision['decision_id'].encode()).hexdigest(),type=kind,published_at=at)
    if kind=='home_page':
        result.update(dialect=raw['dialect'],hero_title_id=raw.get('hero_title_id'),
            rows=[{'row_type':r['row_type'],'title_ids':r['title_ids']} for r in raw['rows']])
    else:
        for key in ('title_id','text','deeplink','template_id','variables'):
            if key in raw: result[key]=raw[key]
        result['send_at']=max(timestamp(at),timestamp(raw.get('send_at',at))).isoformat()
    return result

def publish(store, pack, decision, approval, now, budget, drain):
    """Recheck authoritative state at the ledger's publication linearization point."""
    aid=action_for(decision,now())['action_id']
    with store.connection:
        store.connection.execute('INSERT OR IGNORE INTO outbox VALUES (?,?,?,?,?)',
            (aid,decision['decision_id'],approval,'pending',encode(decision)))
    while True:
        drain(now())
        at=now()
        def read():
            return _authorities(pack,at,store),_context(store,decision['user_id'],at,decision['decision_id'])
        authority,context=budget.call('tool','publication_authoritative_reads',read)
        point=now()
        if not drain(point): break
    checks=[]
    def check(name, passed, reason, evidence=(), unknown=False):
        checks.append({'name':name,'status':'PASSED' if passed else 'FAILED','reason':reason,'evidence':list(evidence)})
        return passed
    _validate(context,authority,decision,decision['proposal']['type'],decision['proposal']['payload'],point,check)
    arms=[r['arm'] for r in authority['arms'] if r['user_id']==decision['user_id']]
    check('publication_holdout',arms==['agent'],'Authoritative arm must be agent')
    check('publication_budget',budget.clock()-budget.started<budget.max_seconds,'Publication must meet decision deadline')
    kind=decision['proposal']['type']
    if kind in ('push','whatsapp','in_app_message'):
        scope='outbound' if kind in ('push','whatsapp') else 'in_app'
        day=timestamp(point).astimezone(IST).date().isoformat()
        rows=store.connection.execute("SELECT approval_id FROM message_reservations WHERE user_id=? AND ist_day=? AND scope=? AND status='reserved'",(decision['user_id'],day,scope)).fetchall()
        channels=('push','whatsapp') if scope=='outbound' else ('in_app_message',)
        delivered=[e for e in context['events'] if e['event']=='message_delivered' and e['properties'].get('channel') in channels and timestamp(e['received_at']).astimezone(IST).date().isoformat()==day]
        limit=1 if scope=='outbound' else authority['interventions']['in_app_message']['max_per_day']
        check('publication_reservation',any(r[0]==approval for r in rows) and len(rows)+len(delivered)<=limit,
              'Current IST-day reservation and observed deliveries must still satisfy the cap')
    if any(c['status']!='PASSED' for c in checks):
        with store.connection:
            store.connection.execute("UPDATE outbox SET status='cancelled' WHERE action_id=?",(aid,))
            store.connection.execute("UPDATE approvals SET status='revoked' WHERE approval_id=?",(approval,))
            store.connection.execute("UPDATE message_reservations SET status='released' WHERE approval_id=?",(approval,))
        return None,checks
    budget.charge('tool','commit_simulated_publication')
    action=action_for(decision,point)
    with store.connection:
        store.connection.execute('BEGIN IMMEDIATE')
        row=store.connection.execute("SELECT status FROM approvals WHERE approval_id=?",(approval,)).fetchone()
        if not row or row[0]!='approved': raise ValueError('Approval revoked before publication')
        store.connection.execute('INSERT OR IGNORE INTO published_actions VALUES (?,?,?,?,?,?)',
            (aid,decision['decision_id'],decision['trigger_event_id'],approval,point,encode(action)))
        store.connection.execute("UPDATE outbox SET status='published',payload=? WHERE action_id=?",(encode(action),aid))
    return action,checks
