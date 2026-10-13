"""Randomized intent-to-treat comparisons with explicit missingness and identifiability."""
import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path
from .ingestion import records
from .outcomes import atomic_write
from .schemas import timestamp

Z=1.959963984540054

def wilson(successes,n):
    if not n:return None
    p=successes/n;denom=1+Z*Z/n
    center=(p+Z*Z/(2*n))/denom
    half=Z*math.sqrt(p*(1-p)/n+Z*Z/(4*n*n))/denom
    return [max(0,center-half),min(1,center+half)]


def compare(assignments,outcomes,treatment='agent',control='holdout'):
    """outcomes[user] is bool or None. Missing users remain in randomized denominators."""
    groups={}
    for arm in (treatment,control):
        users=[u for u,a in assignments.items() if a==arm];known=[outcomes.get(u) for u in users if isinstance(outcomes.get(u),bool)]
        n=len(users);s=sum(known);missing=n-len(known)
        groups[arm]={'randomized_n':n,'observed_n':len(known),'successes':s,'failures':len(known)-s,'missing':missing,
            'conversion_rate':s/n if n and not missing else None,'conversion_rate_ci95':wilson(s,n) if n and not missing else None,
            'observed_only_rate':s/len(known) if known else None,
            'population_rate_bounds':[s/n,(s+missing)/n] if n else None}
    a,b=groups[treatment],groups[control]
    result={'groups':groups,'absolute_difference_pp':None,'difference_ci95_pp':None,'relative_lift':None,'relative_lift_ci95':None,
        'confidence_method':'95% Wilson arm intervals; Newcombe independent risk-difference interval; log-risk-ratio interval where both arms have successes',
        'estimable':False}
    if a['population_rate_bounds'] and b['population_rate_bounds']:
        result['population_difference_bounds_pp']=[100*(a['population_rate_bounds'][0]-b['population_rate_bounds'][1]),100*(a['population_rate_bounds'][1]-b['population_rate_bounds'][0])]
    if a['conversion_rate'] is None or b['conversion_rate'] is None:
        result['reason']='Full randomized population point estimate is not estimable with missing outcomes or an empty arm; bounds make no missing-at-random assumption'
        return result
    p,q=a['conversion_rate'],b['conversion_rate'];delta=p-q;la,ua=a['conversion_rate_ci95'];lb,ub=b['conversion_rate_ci95']
    result.update(estimable=True,absolute_difference_pp=100*delta,
        difference_ci95_pp=[100*max(-1,delta-math.sqrt((p-la)**2+(ub-q)**2)),100*min(1,delta+math.sqrt((ua-p)**2+(q-lb)**2))])
    if q>0:
        result['relative_lift']=p/q-1
        if a['successes']>0:
            se=math.sqrt(1/a['successes']-1/a['randomized_n']+1/b['successes']-1/b['randomized_n'])
            log_rr=math.log(p/q);result['relative_lift_ci95']=[math.exp(log_rr-Z*se)-1,math.exp(log_rr+Z*se)-1]
    result['reason']='Comparison follows randomized assignment, including treatment viewers receiving NO_ACTION; inference assumes valid randomization, common ascertainment and no interference'
    return result


def pilot_audit(pack):
    assignment=list(records(Path(pack)/'pilot/pilot_assignment.csv'));labels=list(records(Path(pack)/'pilot/pilot_outcomes.csv'))
    mapping={r['user_id']:r for r in assignment};rows={r['user_id']:r for r in labels}
    if len(mapping)!=len(assignment) or len(rows)!=len(labels) or set(rows)-set(mapping):raise ValueError('Pilot duplicate/unknown identity')
    values={}
    for u,a in mapping.items():
        r=rows.get(u)
        if r and (r['arm']!=a['arm'] or r['served']!=a['served']):raise ValueError('Pilot arms/served labels disagree across supplied files')
        if a['arm'] not in ('treatment','holdout') or a['served'] not in ('true','false'):raise ValueError('Invalid pilot assignment')
        values[u]=r['succeeded']=='true' if r and r['succeeded'] in ('true','false') else None
    arms={u:r['arm'] for u,r in mapping.items()}
    served={u:'served' if r['served']=='true' else 'other' for u,r in mapping.items()}
    biased=compare(served,values,'served','other')
    biased['reason']='Descriptive association only: served versus everyone else is not a randomized contrast and cannot identify causal uplift'
    return {'randomized_label_itt':compare(arms,values,'treatment','holdout'),
        'biased_served_comparison':biased,
        'goal_mix':{arm:dict(Counter(r['goal_id'] for r in labels if r['arm']==arm)) for arm in ('treatment','holdout')},
        'selection_bias':'Serving is a post-assignment choice that can select for activity, eligibility and opportunity to expose. Served versus everyone else mixes unserved treatment and holdout users and breaks randomization; its uplift is not causal.',
        'limitations':'Pilot succeeded fields are supplied labels, not independently verified events. G06 eligibility is underspecified; goal-specific observation coverage and censoring are unavailable. The randomized comparison estimates differences in supplied labels only, conditional on consistent measurement.',
        'source':['pilot/pilot_assignment.csv','pilot/pilot_outcomes.csv','pilot/pilot_summary_report.md']}


def evaluate(pack,events,manifest):
    assignments_list=list(records(Path(pack)/'replay/arms.csv'));assignments={r['user_id']:r['arm'] for r in assignments_list}
    if len(assignments)!=len(assignments_list) or set(assignments.values())-{'agent','holdout'}:raise ValueError('Ambiguous randomized arms')
    triggered=set(manifest['observed_users']);start=timestamp(manifest['coverage_start']);end=start+timedelta(days=7)
    observed_through=timestamp(manifest.get('evaluated_through',manifest['coverage_end_exclusive']))
    coverage_ok=timestamp(manifest['coverage_end_exclusive'])>=end and observed_through>=end
    observed={u:list(rows) for u,rows in events.items()}
    seen={r['event_id'] for rows in observed.values() for r in rows}
    for n,row in enumerate(records(Path(pack)/'replay/live_events.jsonl'),1):
        if row['event_id'] not in seen:
            row=dict(row);row['_source_ref']=f'replay/live_events.jsonl:{n}:event:{row["event_id"]}'
            observed.setdefault(row['user_id'],[]).append(row);seen.add(row['event_id'])
    metrics={}
    for metric,event in (('non_trial_purchase_7d','purchase_completed'),('any_play_7d','play_started')):
        values={};evidence={}
        for user in assignments:
            rows=[e for e in observed.get(user,[]) if e['event']==event and start<=timestamp(e['received_at'])<end and timestamp(e['received_at'])<=observed_through]
            qualified=[e for e in rows if event!='purchase_completed' or e['properties'].get('is_trial') is False]
            ambiguous=any(not isinstance(e['properties'].get('is_trial'),bool) for e in rows) if event=='purchase_completed' else False
            values[user]=True if qualified else None if ambiguous or user not in triggered or not coverage_ok else False
            evidence[user]=[e.get('_source_ref','event:'+e['event_id']) for e in qualified]
        metrics[metric]={'definition':'Any observed '+('non-trial purchase_completed' if event=='purchase_completed' else 'play_started')+' in the same fixed seven-day receipt-time window; no selected-goal or served restriction',
            'window':{'start_inclusive':start.isoformat(),'end_exclusive':end.isoformat()},
            'observations':{u:{'arm':assignments[u],'outcome':values[u],'evidence':evidence[u]} for u in assignments},
            'full_randomized_population_itt':compare(assignments,values),
            'scripted_triggered_cohort_itt':compare({u:a for u,a in assignments.items() if u in triggered},values)}
    return {'randomized_users':len(assignments),'triggered_users':len(triggered),'unobserved_users':len(assignments)-len(triggered),'metrics':metrics,
        'selected_goal_success_impact':{'estimable':False,'reason':'No holdout selected-goal assignments, goal commitment times or success definitions are supplied. Agent goal attainment cannot be compared to an invented holdout goal.'},
        'causal_scope':'Triggered-cohort ITT uses a fixed supplied trigger roster that is generated independently of actions; includes all assigned agent users in that roster, including NO_ACTION. A causal interpretation is conditional on this exogenous-cohort assumption, valid randomization, comparable observation and no interference. It describes this synthetic simulator and seed, not real product impact.',
        'missingness':'Untriggered randomized users lack complete simulator follow-up: supplied live-event positives are retained, while other outcomes remain unknown, not zero. Full-population ITT rates, relative lift and confidence intervals are not estimable without assumptions. Reported population bounds are worst-case identification bounds, not confidence intervals.',
        'multiplicity':'Two exploratory endpoints are reported without multiple-testing adjustment; neither supports a pre-registered confirmatory claim.',
        'pilot':pilot_audit(pack)}


def fmt(value,digits=3):return 'not estimable' if value is None else f'{value:.{digits}f}'

def comparison_table(result,treatment='agent',control='holdout'):
    lines=['| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |','|---|---:|---:|---:|---:|---:|---|']
    for arm in (treatment,control):
        r=result['groups'][arm];ci=r['conversion_rate_ci95'];rate=r['conversion_rate']
        lines.append(f"| {arm} | {r['randomized_n']} | {r['observed_n']} | {r['successes']} | {r['missing']} | {f'{100*rate:.3f}%' if rate is not None else 'not estimable'} | "+(f'{100*ci[0]:.3f}% to {100*ci[1]:.3f}%' if ci else 'not estimable')+' |')
    ci=result['difference_ci95_pp'];lift=result['relative_lift'];lci=result['relative_lift_ci95']
    lines+=['',f"Absolute difference: {fmt(result['absolute_difference_pp'])} percentage points. 95% CI: "+(f'{ci[0]:.3f} to {ci[1]:.3f} pp.' if ci else 'not estimable.'),
        'Relative lift: '+(f'{100*lift:.3f}%' if lift is not None else 'not estimable')+'. 95% CI: '+(f'{100*lci[0]:.3f}% to {100*lci[1]:.3f}%.' if lci else 'not estimable.'),result['reason']]
    if not result['estimable'] and result.get('population_difference_bounds_pp'):
        lo,hi=result['population_difference_bounds_pp'];lines.append(f'Worst-case population difference bounds: {lo:.3f} to {hi:.3f} pp; not a confidence interval.')
    if ci is not None:
        lines.append('The difference interval includes zero; this run does not demonstrate a difference.' if ci[0]<=0<=ci[1] else 'The interval excludes zero under the stated inference assumptions; this is not evidence beyond that population and observation process.')
    return '\n'.join(lines)


def write_reports(pack,out,evaluation,outcome_summary):
    out=Path(out);lines=['# Randomized impact evaluation','',evaluation['causal_scope'],'',evaluation['missingness'],'',evaluation['multiplicity']]
    for name,metric in evaluation['metrics'].items():
        lines+=['',f'## {name}','',metric['definition'],'',f"Window: {metric['window']['start_inclusive']} to {metric['window']['end_exclusive']} (end excluded).",'',
            '### All randomized users (ITT)','',comparison_table(metric['full_randomized_population_itt']),'','### Scripted triggered cohort (ITT)','',comparison_table(metric['scripted_triggered_cohort_itt'])]
    lines+=['','## Selected-goal impact','',evaluation['selected_goal_success_impact']['reason'],'','## Earlier pilot audit','',evaluation['pilot']['selection_bias'],'',
        '### Original served comparison (descriptive, biased)','',comparison_table(evaluation['pilot']['biased_served_comparison'],'served','other'),'',
        '### Randomized pilot label comparison','',comparison_table(evaluation['pilot']['randomized_label_itt'],'treatment','holdout'),'',evaluation['pilot']['limitations'],'',
        'Sources: replay/arms.csv, actual simulator outcome_events.jsonl/report/source, actual goal rules and controls, and the three supplied pilot files. Numerical estimates use no model claims or action publication as success evidence.']
    atomic_write(out/'impact_report.md','\n'.join(lines)+'\n');atomic_write(out/'impact_report.json',json.dumps(evaluation,indent=2))
    latency=json.loads((out/'latency_report.json').read_text());sim=outcome_summary['manifest']['simulator_report']
    final=['# Final submission run','',f"Simulator seed: {sim['seed']}. {sim['events_written']} actual simulator events for {sim['triggered_users']} triggered users.",
        f"{sim['counts'].get('home_page_accepted',0)} accepted home pages; {sim['counts'].get('home_page_shown_personalised',0)} personalised page-show events (not unique viewers); {sim['policy_problem_count']} simulator policy problems.",
        f"Replay: {latency['trigger_deliveries']} trigger deliveries, {latency['unique_triggers']} unique, {latency['duplicates']} duplicates; {latency['actions']} local actions; {latency['holdout_actions']} holdout actions.",
        f"Goal judgments: {outcome_summary['goal_instances']} instances for {outcome_summary['viewers_with_goals']} viewers. Counts: {json.dumps(outcome_summary['counts'],sort_keys=True)}.",
        'Goal attainment is observed within viewer-specific committed windows. Success does not establish that a page caused the event. Holdout users without a goal have no fabricated outcome judgments.',
        '', '## Measurement by goal','', '| Goal | SUCCEEDED | FAILED | INCONCLUSIVE |','|---|---:|---:|---:|']
    for gid,c in outcome_summary['by_goal'].items():final.append(f"| {gid} | {c.get('SUCCEEDED',0)} | {c.get('FAILED',0)} | {c.get('INCONCLUSIVE',0)} |")
    final+=['','## Impact','',evaluation['selected_goal_success_impact']['reason'],'',evaluation['missingness']]
    for name,m in evaluation['metrics'].items():final+=['',f'### {name}: randomized triggered cohort','',comparison_table(m['scripted_triggered_cohort_itt'])]
    final+=['','## Reliability and limits','',f"Publication latency seconds: {json.dumps(latency['publication_latency_seconds'],sort_keys=True)}. Decisions >60 s: {latency['exceeding_60_seconds']}; >5 min: {latency['exceeding_5_minutes']}. Recorded replay failures: {json.dumps(latency['failures'],sort_keys=True)}.",
        'G06/G10/G11 remain disabled; G07 outcome needs an authoritative unfinished-series identity and is unsupported. Unknown historical rule versions and incomplete windows are inconclusive. G03 uses the supplied correction for affected open goals. Source events are stored separately so nullable simulator app settings cannot overwrite replay facts.',
        'Mock timeouts are emulated without a 45-second sleep; store degradation uses conservative bounded reads. Local simulator results do not establish real-world product lift. See KNOWN_LIMITATIONS.md and impact_report.md.',
        '', '## Reproduction','', '`python -m one_agent.cli pipeline --pack . --db sample_run/replay.sqlite3 --out sample_run` runs replay recovery, the supplied simulator, validation, outcomes and reports locally. `pytest -q` runs automated verification. The stored source manifest and phase5_pipeline_validation.json provide content hashes and invariants.']
    atomic_write(out/'final_report.md','\n'.join(final)+'\n')
