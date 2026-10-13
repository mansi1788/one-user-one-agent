"""Replay fixtures are synthetic tests, never pack evidence."""
import json
import pytest
from test_planning import setup, AT
from test_memory import event, PACK
from one_agent.replay import Replay
from one_agent.schemas import timestamp

@pytest.fixture
def replay_setup(setup):
    s,p=setup
    (p/'config/pricing.json').write_bytes((PACK/'config/pricing.json').read_bytes())
    for name in ('triggers.jsonl','live_events.jsonl','model_faults.jsonl'):
        (p/'replay'/name).write_text('')
    def build(events=None,controls=None,faults=None,**kwargs):
        events=events if events is not None else [event(event_id='trigger',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin')]
        for name,rows in [('triggers',events),('control_events',controls or []),('model_faults',faults or [])]:
            (p/'replay'/f'{name}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with s.connection:
            for n,e in enumerate(events):
                s.connection.execute('INSERT OR IGNORE INTO triggers VALUES (?,?,?,?,?)',(f'test:{n}',e['event_id'],e['user_id'],e['deliver_at'],json.dumps(e)))
        return Replay(s,p,**kwargs)
    return s,p,build

def test_replay_publication_schema_timing_and_restart(replay_setup,tmp_path):
    s,p,build=replay_setup;r=build();report=r.run(tmp_path/'out',False)
    assert report['actions']==1
    a=json.loads((tmp_path/'out/actions.jsonl').read_text())
    assert set(('action_id','decision_id','user_id','trigger_event_id','type','published_at','dialect','rows'))<=a.keys()
    d=json.loads((tmp_path/'out/decisions.jsonl').read_text())
    assert (timestamp(a['published_at'])-timestamp(AT)).total_seconds()==pytest.approx(d['publication_latency_seconds'])
    assert d['budget']['counts']['tool']<=20
    assert Replay(s,p).run(tmp_path/'again',False)['actions']==1
    assert (tmp_path/'out/actions.jsonl').read_bytes()==(tmp_path/'again/actions.jsonl').read_bytes()

def test_duplicate_trigger(replay_setup,tmp_path):
    s,p,build=replay_setup
    e=event(event_id='same',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin')
    report=build([e,e]).run(tmp_path/'out',False)
    assert report['actions']==1 and report['duplicates']==1

def test_holdout(replay_setup,tmp_path):
    s,p,build=replay_setup;(p/'replay/arms.csv').write_text('user_id,arm\nU1,holdout\n')
    report=build().run(tmp_path/'out',False)
    assert report['actions']==report['holdout_actions']==0

@pytest.mark.parametrize('kind',['old','model','store','budget'])
def test_failures_and_late_requests(replay_setup,tmp_path,kind):
    s,p,build=replay_setup;controls=[];kwargs={}
    e=event(event_id='trigger',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin')
    if kind=='old': e['occurred_at']='2026-09-01T00:00:00Z'
    if kind in ('model','store'):
        controls=[{'at':AT,'until':'2026-10-01T07:00:00Z','type':'dependency_unavailable' if kind=='model' else 'dependency_degraded','dependency':'model_provider' if kind=='model' else 'user_data_store'}]
    if kind=='budget': kwargs['max_tool_calls']=0
    report=build([e],controls,**kwargs).run(tmp_path/'out',False)
    assert report['actions']==(1 if kind=='model' else 0)
    if kind=='model': assert '503' in json.loads((tmp_path/'out/decisions.jsonl').read_text())['model']['reason']

def test_withdrawal_applies_only_when_delivered(replay_setup,tmp_path):
    s,p,build=replay_setup
    controls=[{'at':AT,'type':'title_withdrawn','title_id':'T000'}]
    report=build(controls=controls).run(tmp_path/'out',False)
    assert report['actions']==1
    action=json.loads((tmp_path/'out/actions.jsonl').read_text())
    assert action['hero_title_id']!='T000'
    assert all('T000' not in row['title_ids'] for row in action['rows'])

def test_g03_correction_updates_open_goal(replay_setup,tmp_path):
    s,p,build=replay_setup
    from one_agent.planner import plan
    with s.connection:
        for row in s.connection.execute('SELECT source_ref,payload FROM profiles').fetchall():
            value=json.loads(row['payload']);value['signup_at']='2026-10-01T00:00:00Z'
            s.connection.execute('UPDATE profiles SET payload=? WHERE source_ref=?',(json.dumps(value),row['source_ref']))
    d=plan(s,p,'U1',AT)
    assert d['goal']['goal_id']=='G03'
    control={'at':AT,'type':'goal_rule_corrected','goal_id':'G03','new_success':{'event':'play_started','condition':'on a later IST calendar day within the window'}}
    r=build(controls=[control]);r.drain(AT)
    active=s.active_goal_plan('U1')
    assert json.loads(active['payload'])['success']['event']=='play_started'
    assert active['deadline']==d['goal']['deadline']

def test_model_timeout_and_malformed_safe_fallback(replay_setup,tmp_path):
    s,p,build=replay_setup
    report=build(faults=[{'trigger_event_id':'trigger','fault':'timeout','seconds':45}]).run(tmp_path/'out',False)
    assert report['actions']==1
    assert 'timeout' in json.loads((tmp_path/'out/decisions.jsonl').read_text())['model']['reason'].lower()

def test_traffic_burst_is_bounded(replay_setup,tmp_path):
    s,p,build=replay_setup
    events=[event(event_id=f't{i}',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin') for i in range(12)]
    report=build(events).run(tmp_path/'out',False)
    assert report['unique_triggers']==12 and report['holdout_actions']==0
    assert report['total_seconds']['max']<60

def test_export_crash_recovery(replay_setup,tmp_path,monkeypatch):
    s,p,build=replay_setup;r=build()
    def crash(_): raise RuntimeError('Crash before filesystem export')
    monkeypatch.setattr(r,'export',crash)
    with pytest.raises(RuntimeError): r.run(tmp_path/'out',False)
    assert Replay(s,p).run(tmp_path/'out',False)['actions']==1
    assert s.connection.execute('SELECT COUNT(*) FROM published_actions').fetchone()[0]==1

def test_actual_store_exception_fails_closed(replay_setup,tmp_path,monkeypatch):
    import sqlite3
    import one_agent.replay as module
    s,p,build=replay_setup;r=build()
    def fail(*args,**kwargs): raise sqlite3.OperationalError('Synthetic unavailable SQLite read')
    monkeypatch.setattr(module,'plan',fail)
    report=r.run(tmp_path/'out',False)
    assert report['actions']==0 and report['failures']=={'OperationalError':1}

def test_in_app_cap_survives_replay(replay_setup,tmp_path):
    s,p,build=replay_setup
    events=[event(event_id=f'm{i}',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin') for i in range(2)]
    report=build(events,channel='in_app_message').run(tmp_path/'out',False)
    assert report['actions']==1
    assert s.connection.execute("SELECT COUNT(*) FROM message_reservations WHERE status='reserved'").fetchone()[0]==1

def test_push_quiet_hours_no_publication(replay_setup,tmp_path):
    s,p,build=replay_setup
    night='2026-10-01T17:00:00Z'
    e=event(event_id='night',received_at=night,occurred_at=night,sent_at=night,deliver_at=night,app_language='hin')
    report=build([e],channel='push').run(tmp_path/'out',False)
    assert report['actions']==0

def test_artifact_validator_detects_tampering(replay_setup,tmp_path):
    s,p,build=replay_setup
    (p/'data').mkdir()
    import csv
    titles=[json.loads(r[0]) for r in s.connection.execute('SELECT payload FROM catalogue')]
    with (p/'data/catalogue.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(titles[0]));w.writeheader();w.writerows(titles)
    build().run(tmp_path/'out',False)
    from one_agent.output_validation import validate_outputs
    assert validate_outputs(p,tmp_path/'out')['valid']
    path=tmp_path/'out/actions.jsonl';a=json.loads(path.read_text());a['hero_title_id']='FAKE'
    path.write_text(json.dumps(a)+'\n')
    assert not validate_outputs(p,tmp_path/'out')['valid']

def test_budget_failure_has_durable_decision_identity(replay_setup,tmp_path):
    s,p,build=replay_setup
    build(max_tool_calls=0).run(tmp_path/'out',False)
    result=json.loads((tmp_path/'out/decisions.jsonl').read_text())
    row=s.connection.execute('SELECT payload FROM decisions WHERE decision_id=?',(result['decision_id'],)).fetchone()
    assert row and json.loads(row[0])['proposal']['type']=='NO_ACTION'
    assert result['error']=='BudgetExceeded'

@pytest.mark.parametrize('limit,kwargs',[('model',{'max_model_calls':9}),('tool',{'max_tool_calls':21}),('time',{'max_seconds':61})])
def test_hard_replay_limits(replay_setup,limit,kwargs):
    s,p,build=replay_setup
    with pytest.raises(ValueError,match='limits'):build(**kwargs)

def test_crash_between_result_and_driver_checkpoint(replay_setup,tmp_path,monkeypatch):
    s,p,build=replay_setup;r=build();original=r.trigger
    def crash_after_commit(item):
        original(item)
        raise RuntimeError('Crash after completed decision transaction')
    monkeypatch.setattr(r,'trigger',crash_after_commit)
    with pytest.raises(RuntimeError):r.run(tmp_path/'out',False)
    from one_agent.store import Store
    db=s.connection.execute('PRAGMA database_list').fetchone()[2]
    with Store(db) as restarted:
        report=Replay(restarted,p).run(tmp_path/'out',False)
    assert report['actions']==1 and report['unique_triggers']==1 and report['duplicates']==0

def test_independent_quiet_hours_against_forged_push(replay_setup,tmp_path,monkeypatch):
    import one_agent.replay as module
    from one_agent.verifier import FIXED_COPY
    s,p,build=replay_setup;original=module.plan
    def forged(*args,**kwargs):
        d=original(*args,**kwargs);at=d['as_of'];title=d['proposal']['payload']['hero_title_id']
        d['proposal']={'type':'push','status':'PROPOSED','payload':{'type':'push','proposed_at':at,'send_at':at,'title_id':title,'text':FIXED_COPY['push'],'deeplink':'ott://title/'+title}}
        with s.connection:s.connection.execute('UPDATE decisions SET payload=? WHERE decision_id=?',(json.dumps(d),d['decision_id']))
        return d
    monkeypatch.setattr(module,'plan',forged)
    night='2026-10-01T17:00:00Z';e=event(event_id='quiet',received_at=night,occurred_at=night,sent_at=night,deliver_at=night,app_language='hin')
    report=build([e]).run(tmp_path/'out',False)
    assert report['actions']==0
    checks=json.loads((tmp_path/'out/decisions.jsonl').read_text())['verification']['checks']
    assert any(c['name']=='quiet_hours' and c['status']=='FAILED' for c in checks)
    assert any(c['name']=='consent' and c['status']=='PASSED' for c in checks)

def test_delivery_between_approval_and_publication_consumes_cap(replay_setup,tmp_path,monkeypatch):
    import one_agent.publisher as publisher
    s,p,build=replay_setup;original=publisher._context
    def delivery(store,user,at,did):
        with store.connection:
            store.add_event(event(event_id='new-delivery',event='message_delivered',received_at=at,occurred_at=at,sent_at=at,properties={'channel':'in_app_message'}),'synthetic-test')
        return original(store,user,at,did)
    monkeypatch.setattr(publisher,'_context',delivery)
    report=build(channel='in_app_message').run(tmp_path/'out',False)
    assert report['actions']==0
    d=json.loads((tmp_path/'out/decisions.jsonl').read_text())
    assert any(c['name']=='publication_reservation' and c['status']=='FAILED' for c in d['publication_checks'])

def test_queued_trigger_settings_are_visible_at_publication(replay_setup,tmp_path):
    s,p,build=replay_setup
    first=event(event_id='a',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin')
    later=event(event_id='z',dialect='d9',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin')
    report=build([first,later]).run(tmp_path/'out',False)
    assert report['actions']==0
    assert len(s.user_events('U1','2026-10-02T00:00:00Z'))==3
    assert s.connection.execute('SELECT COUNT(*) FROM replay_arrivals').fetchone()[0]==2

def test_duplicate_budget_failure_links_original_audit(replay_setup,tmp_path):
    s,p,build=replay_setup
    e=event(event_id='budget-duplicate',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,app_language='hin')
    build([e,e],max_tool_calls=0).run(tmp_path/'out',False)
    rows=[json.loads(line) for line in (tmp_path/'out/decisions.jsonl').read_text().splitlines()]
    assert rows[1]['original_decision_id']==rows[0]['decision_id']
