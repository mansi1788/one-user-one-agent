"""Synthetic cases test measurement logic; no fixture results enter submitted reports."""
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import pytest
from test_memory import PACK,event
from test_planning import setup,AT
from one_agent.ingestion import load_goals
from one_agent.schemas import timestamp
from one_agent.outcomes import judge_goal,measure,validate_simulator
from one_agent.evaluation import compare,evaluate,pilot_audit,wilson

RULES=load_goals(PACK)
COVER={'coverage_start':'2026-10-01T00:00:00Z','coverage_end_exclusive':'2026-10-20T00:00:00Z','observed_users':['U1']}

def goal(gid='G05',**changes):
    r=next(g for g in RULES['goals'] if g['goal_id']==gid)
    g={'id':1,'user_id':'U1','goal_id':gid,'rule_version':RULES['version'],'started_at':AT,
       'deadline':(timestamp(AT)+timedelta(hours=r['success']['window_hours'])).isoformat(),'status':'open','payload':json.dumps({'success':r['success']})}
    g.update(changes);return g

def observed(kind='purchase_completed',at='2026-10-01T07:00:00Z',**props):
    r=event(event_id='OBS',event=kind,received_at=at,occurred_at=at,sent_at=at,properties=props)
    r['_source_ref']='fixture:OBS';return r

def judge(g=None,rows=(),coverage=None,controls=(),catalogue=None,**kw):
    return judge_goal(g or goal(),rows,RULES,controls,catalogue or {},coverage or COVER,**kw)

@pytest.mark.parametrize('trial,status',[(False,'SUCCEEDED'),(True,'FAILED')])
def test_paid_purchase_requires_non_trial(trial,status):
    result=judge(rows=[observed(is_trial=trial)])
    assert result['verdict']==status
    if not trial:assert result['evidence']==['fixture:OBS']

def test_failure_needs_complete_window():
    assert judge()['verdict']=='FAILED'
    assert judge(as_of='2026-10-02T00:00:00Z')['verdict']=='INCONCLUSIVE'
    c={**COVER,'observed_users':[]}
    assert judge(coverage=c)['verdict']=='INCONCLUSIVE'

def test_early_success_and_wrong_viewer():
    row=observed(is_trial=False)
    assert judge(rows=[row],as_of='2026-10-01T08:00:00Z')['verdict']=='SUCCEEDED'
    row['user_id']='OTHER'
    assert judge(rows=[row])['verdict']=='FAILED'

@pytest.mark.parametrize('offset,status',[(-1,'SUCCEEDED'),(0,'SUCCEEDED'),(1,'FAILED')])
def test_deadline_boundary(offset,status):
    g=goal();at=(timestamp(g['deadline'])+timedelta(microseconds=offset)).isoformat()
    assert judge(g,[observed(at=at,is_trial=False)])['verdict']==status

def test_events_before_commit_not_success():
    assert judge(rows=[observed(at='2026-10-01T05:59:59Z',is_trial=False)])['verdict']=='FAILED'

@pytest.mark.parametrize('change',[{'rule_version':'missing'},{'deadline':'2026-10-03T00:00:00Z'}])
def test_invalid_rule_version_or_deadline_is_inconclusive(change):
    assert judge(goal(**change),[observed(is_trial=False)])['verdict']=='INCONCLUSIVE'

@pytest.mark.parametrize('gid',['G06','G07','G10','G11'])
def test_unsupported_goals(gid):
    assert judge(goal(gid),[observed(is_trial=False)])['verdict']=='INCONCLUSIVE'

def test_g03_correction_rejects_app_open_accepts_later_day_play():
    control={'at':'2026-10-01T08:30:00Z','type':'goal_rule_corrected','goal_id':'G03','new_success':{'event':'play_started','condition':'on a later IST calendar day within the window'}}
    later=observed('app_open','2026-10-02T06:00:00Z')
    assert judge(goal('G03'),[later],controls=[control])['verdict']=='FAILED'
    later['event']='play_started'
    result=judge(goal('G03'),[later],controls=[control])
    assert result['verdict']=='SUCCEEDED' and 'replay/control_events.jsonl:1' in result['rule_evidence']
    later['received_at']='2026-10-01T08:00:00Z'
    assert judge(goal('G03'),[later],controls=[control])['verdict']=='FAILED'

def test_g09_uses_distinct_ist_days():
    rows=[observed('play_started',f'2026-10-0{n}T06:00:00Z') for n in (2,3,4)]
    assert judge(goal('G09'),rows)['verdict']=='SUCCEEDED'
    for row in rows:row['received_at']='2026-10-02T06:00:00Z'
    assert judge(goal('G09'),rows)['verdict']=='FAILED'

def test_g08_release_window_and_missing_metadata():
    row=observed('play_started',title_id='T')
    assert judge(goal('G08'),[row],catalogue={'T':{'release_date':'2026-09-15'}})['verdict']=='SUCCEEDED'
    assert judge(goal('G08'),[row],catalogue={'T':{'release_date':'2026-01-01'}})['verdict']=='FAILED'
    assert judge(goal('G08'),[row])['verdict']=='INCONCLUSIVE'

def test_cancellation_censors_negative_outcome():
    assert judge(cancelled_at='2026-10-02T00:00:00Z')['verdict']=='INCONCLUSIVE'
    assert judge(rows=[observed(is_trial=False)],cancelled_at='2026-10-02T00:00:00Z')['verdict']=='SUCCEEDED'

def test_missing_trial_field_is_uncertain():
    assert judge(rows=[observed()])['verdict']=='INCONCLUSIVE'

def test_unknown_success_condition_is_not_invented():
    rules=deepcopy(RULES);next(r for r in rules['goals'] if r['goal_id']=='G05')['success']['condition']='model claims it succeeded'
    assert judge_goal(goal(),[observed(is_trial=False)],rules,[],{},COVER)['verdict']=='INCONCLUSIVE'

def test_itt_keeps_no_action_users_and_missingness():
    r=compare({'a':'agent','b':'agent','h':'holdout','m':'holdout'},{'a':True,'b':False,'h':False})
    assert r['groups']['agent']['randomized_n']==2 and r['groups']['agent']['conversion_rate']==.5
    assert r['groups']['holdout']['missing']==1 and r['groups']['holdout']['conversion_rate'] is None
    assert not r['estimable'] and r['population_difference_bounds_pp']==[0,50]

def test_ci_and_undefined_relative_lift():
    r=compare({'a':'agent','h':'holdout'},{'a':False,'h':False})
    assert r['estimable'] and r['relative_lift'] is None
    assert r['difference_ci95_pp'][0]<0<r['difference_ci95_pp'][1]
    assert wilson(0,0) is None

def test_full_population_and_triggered_denominators(tmp_path):
    (tmp_path/'replay').mkdir();(tmp_path/'replay/arms.csv').write_text('user_id,arm\na,agent\nb,agent\nh,holdout\nm,holdout\n')
    (tmp_path/'replay/live_events.jsonl').write_text('')
    # Pilot audit is independently tested using supplied files; copy source fixtures.
    (tmp_path/'pilot').mkdir()
    for name in ('pilot_assignment.csv','pilot_outcomes.csv'): (tmp_path/'pilot'/name).write_bytes((PACK/'pilot'/name).read_bytes())
    manifest={**COVER,'observed_users':['a','b','h']}
    rows={'a':[{**observed(is_trial=False),'user_id':'a'}]}
    report=evaluate(tmp_path,rows,manifest);m=report['metrics']['non_trial_purchase_7d']
    assert m['full_randomized_population_itt']['groups']['holdout']['randomized_n']==2
    assert m['scripted_triggered_cohort_itt']['groups']['agent']['randomized_n']==2
    assert m['scripted_triggered_cohort_itt']['groups']['agent']['successes']==1
    assert not report['selected_goal_success_impact']['estimable']

def test_untriggered_live_positive_is_retained(tmp_path):
    (tmp_path/'replay').mkdir();(tmp_path/'replay/arms.csv').write_text('user_id,arm\nU1,agent\nh,holdout\n')
    e=observed(is_trial=False);e.pop('_source_ref');(tmp_path/'replay/live_events.jsonl').write_text(json.dumps(e)+'\n')
    (tmp_path/'pilot').mkdir()
    for name in ('pilot_assignment.csv','pilot_outcomes.csv'):(tmp_path/'pilot'/name).write_bytes((PACK/'pilot'/name).read_bytes())
    report=evaluate(tmp_path,{},dict(COVER,observed_users=[]))
    m=report['metrics']['non_trial_purchase_7d']['full_randomized_population_itt']
    assert m['groups']['agent']['successes']==1 and m['groups']['holdout']['missing']==1

def test_pilot_bias_uses_randomized_rows():
    report=pilot_audit(PACK)
    assert report['randomized_label_itt']['groups']['treatment']['randomized_n']==1912
    assert report['randomized_label_itt']['groups']['holdout']['randomized_n']==1979
    assert report['biased_served_comparison']['groups']['served']['randomized_n']==217
    assert 'not a randomized' in report['biased_served_comparison']['reason']
    assert 'not independently verified' in report['limitations']

def test_measure_persists_learning_and_is_idempotent(setup,tmp_path,monkeypatch):
    from one_agent.planner import plan
    import one_agent.outcomes as module
    s,p=setup;plan(s,p,'U1',AT)
    row=observed(is_trial=False);row['_deliveries']=[{'source_ref':row['_source_ref'],'payload':{k:v for k,v in row.items() if not k.startswith('_')}}]
    manifest={**COVER,'events':1,'simulator_report':{},'hashes':{}}
    monkeypatch.setattr(module,'validate_simulator',lambda *a:(manifest,{'U1':[row]},{}))
    out=tmp_path/'out';first,_=measure(s,p,tmp_path,out);before=(out/'outcomes.jsonl').read_bytes()
    second,_=measure(s,p,tmp_path,out)
    assert first==second and before==(out/'outcomes.jsonl').read_bytes()
    assert s.connection.execute('SELECT COUNT(*) FROM viewer_learning').fetchone()[0]==1
    assert s.connection.execute('SELECT COUNT(*) FROM goal_outcomes').fetchone()[0]==1
    assert s.active_goal_plan('U1') is None
    state=json.loads(next((out/'viewer_state').glob('*.json')).read_text())
    assert state['outcomes'][0]['verdict']=='SUCCEEDED' and state['learning'][0]['evidence']==['fixture:OBS']

@pytest.fixture
def simulator_fixture(setup,tmp_path):
    import csv,subprocess,sys
    s,p=setup;(p/'data').mkdir();(p/'simulator').mkdir()
    (p/'simulator/simulate_outcomes.py').write_bytes((PACK/'simulator/simulate_outcomes.py').read_bytes())
    (p/'config/pricing.json').write_bytes((PACK/'config/pricing.json').read_bytes())
    titles=[json.loads(r[0]) for r in s.connection.execute('SELECT payload FROM catalogue')]
    def csv_write(name,rows):
        with (p/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    csv_write('data/catalogue.csv',titles)
    eps=[{'episode_id':'ep'+str(n),'content_slug':t['content_slug'],'season':'1','episode':'1','minutes':'10'} for n,t in enumerate(titles)]
    csv_write('data/episodes.csv',eps)
    profile=json.loads(s.connection.execute('SELECT payload FROM profiles').fetchone()[0]);csv_write('data/profiles_snapshot.csv',[profile])
    historical=event(event_id='history',received_at='2026-09-30T10:00:00Z',session_id='old')
    (p/'data/events.jsonl').write_text(json.dumps(historical)+'\n')
    trigger=event(event_id='trigger',received_at=AT,occurred_at=AT,sent_at=AT,deliver_at=AT,session_id='session',app_language='hin')
    (p/'replay/triggers.jsonl').write_text(json.dumps(trigger)+'\n');(p/'replay/model_faults.jsonl').write_text('')
    live=observed(at='2026-10-01T07:00:00Z',is_trial=False,plan_id='P_MONTH',price_inr=149);live.pop('_source_ref');live['session_id']='organic';live['deliver_at']=live['received_at']
    duplicate={**live,'received_at':'2026-10-01T07:00:01Z','deliver_at':'2026-10-01T07:00:01Z'}
    (p/'replay/live_events.jsonl').write_text(json.dumps(live)+'\n'+json.dumps(duplicate)+'\n')
    with s.connection:
        s.connection.execute('INSERT INTO triggers VALUES (?,?,?,?,?)',('fixture',trigger['event_id'],'U1',AT,json.dumps(trigger)))
    out=tmp_path/'generated';out.mkdir();(out/'actions.jsonl').write_text('')
    subprocess.run([sys.executable,'-B',str(p/'simulator/simulate_outcomes.py'),'--pack',str(p),'--actions',str(out/'actions.jsonl'),'--out',str(out/'sim')],check=True,capture_output=True)
    return s,p,out

def test_simulator_validation_preserves_duplicate_deliveries(simulator_fixture):
    s,p,out=simulator_fixture
    raw=(out/'sim/outcome_events.jsonl').read_bytes()
    manifest,events,cat=validate_simulator(p,out/'sim',out/'actions.jsonl')
    assert manifest['duplicate_deliveries']==1
    assert sum(e['event_id']=='OBS' for e in events['U1'])==1
    assert len(next(e for e in events['U1'] if e['event_id']=='OBS')['_deliveries'])==2
    assert raw==(out/'sim/outcome_events.jsonl').read_bytes()

@pytest.mark.parametrize('failure',['count','event'])
def test_simulator_validation_rejects_modified_output(simulator_fixture,failure):
    s,p,out=simulator_fixture
    if failure=='count':
        path=out/'sim/simulator_report.json';report=json.loads(path.read_text());report['events_written']+=1;path.write_text(json.dumps(report))
    else:
        path=out/'sim/outcome_events.jsonl';rows=[json.loads(line) for line in path.read_text().splitlines()];rows[0]['user_id']='UNKNOWN';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    with pytest.raises(ValueError):validate_simulator(p,out/'sim',out/'actions.jsonl')

def test_complete_fixture_pipeline_and_reports_idempotent(simulator_fixture):
    from one_agent.pipeline import pipeline
    s,p,out=simulator_fixture
    (p/'pilot').mkdir()
    for name in ('pilot_assignment.csv','pilot_outcomes.csv','pilot_summary_report.md'):(p/'pilot'/name).write_bytes((PACK/'pilot'/name).read_bytes())
    db=s.connection.execute('PRAGMA database_list').fetchone()[2]
    first=pipeline(p,db,out)
    hashes=first['artifact_sha256']
    with s.connection:counts=s.connection.execute('SELECT COUNT(*) FROM goal_outcomes').fetchone()[0]
    second=pipeline(p,db,out)
    assert first==second and hashes==second['artifact_sha256']
    assert counts==s.connection.execute('SELECT COUNT(*) FROM goal_outcomes').fetchone()[0]
    assert second['valid'] and second['required_artifacts_present']
