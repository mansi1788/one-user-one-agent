"""One-command local decide/act/measure pipeline using the unchanged supplied simulator."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from .evaluation import evaluate, write_reports
from .outcomes import atomic_write, measure
from .output_validation import validate_outputs
from .replay import run_replay
from .store import Store


def input_hashes(pack):
    pack=Path(pack)
    return {str(p.relative_to(pack)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('data','config','pilot','replay','simulator') for p in sorted((pack/folder).glob('*')) if p.is_file() and p.suffix in ('.json','.jsonl','.csv','.md','.py')}


def run_measurement(pack,db,out,sim=None,as_of=None):
    sim=Path(sim) if sim else Path(out)/'sim'
    with Store(db) as store:
        summary,events=measure(store,pack,sim,out,as_of=as_of)
        impact=evaluate(pack,events,summary['manifest'])
        write_reports(pack,out,impact,summary)
        integrity=store.connection.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys=len(store.connection.execute('PRAGMA foreign_key_check').fetchall())
    validation={'valid':integrity=='ok' and not foreign_keys,'sqlite_integrity':integrity,'foreign_key_errors':foreign_keys,
        'simulator_events':summary['manifest']['events'],'outcomes':summary['counts'],'outcome_run_id':summary['outcome_run_id']}
    if not validation['valid']:raise ValueError('Measurement SQLite integrity check failed')
    return summary,impact,validation


def pipeline(pack,db,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);Path(db).parent.mkdir(parents=True,exist_ok=True)
    before=input_hashes(pack)
    replay=run_replay(pack,db,out)
    action_check=validate_outputs(pack,out)
    if not action_check['valid']:raise ValueError('Action export failed independent validation')
    command=[sys.executable,'-B',str(Path(pack)/'simulator/simulate_outcomes.py'),'--pack',str(pack),'--actions',str(out/'actions.jsonl'),'--out',str(out/'sim')]
    subprocess.run(command,check=True)
    summary,impact,validation=run_measurement(pack,db,out)
    after=input_hashes(pack)
    validation.update(inputs_unchanged=before==after,input_hashes=after,action_validation=action_check,
        replay=replay,simulator=summary['manifest']['simulator_report'],randomized_users=impact['randomized_users'],triggered_users=impact['triggered_users'])
    if before!=after:raise ValueError('A supplied input changed during the pipeline')
    expected=('decisions.jsonl','viewer_state','actions.jsonl','outcomes.jsonl','latency_report.json','impact_report.md','final_report.md')
    validation['required_artifacts_present']=all((out/name).exists() for name in expected)
    state_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((out/'viewer_state').glob('*.json'))}
    validation['viewer_state_count']=len(state_hashes)
    validation['viewer_state_sha256']=hashlib.sha256(json.dumps(state_hashes,sort_keys=True).encode()).hexdigest()
    validation['artifact_sha256']={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in expected if (out/name).is_file()}
    validation['valid'] &= validation['required_artifacts_present'] and validation['inputs_unchanged']
    atomic_write(out/'phase5_pipeline_validation.json',json.dumps(validation,indent=2))
    return validation
