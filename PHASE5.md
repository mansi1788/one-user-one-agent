# Phase 5 executed results

Implemented `src/one_agent/outcomes.py`, `evaluation.py` and `pipeline.py`; extended the existing CLI with
`measure` and `pipeline`; added `tests/test_outcomes.py`. Added submission README, ARCHITECTURE.md,
AI_COLLABORATION.md and KNOWN_LIMITATIONS.md. DATA_PACK_README.md preserves the original supplied README.
Protected data/config/pilot/replay/simulator inputs retain their original hashes.

## Actual commands and checks

```powershell
.venv\Scripts\python.exe -B simulator/simulate_outcomes.py --pack . --actions sample_run/actions.jsonl --out sample_run/sim
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -B -m one_agent.cli measure --pack . --db sample_run/replay.sqlite3 --out sample_run
.venv\Scripts\python.exe -B -m one_agent.cli pipeline --pack . --db sample_run/replay.sqlite3 --out sample_run
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Full suite: **140 passed in 19.90 seconds**, including the previous 110 tests. New tests cover observation
windows, exact deadlines, historical rule versions, unsupported signals, corrected G03, cancellation,
missing data, randomized denominators, live positives outside the simulator cohort, pilot selection bias,
simulator validation/tampering, and complete pipeline/report rerun idempotency.

The first actual simulator validator run rejected repeated live event IDs; it was corrected to preserve raw
deliveries and deduplicate counting without changing simulator output. Integration fixtures also initially
omitted required session/delivery fields; those fixtures were corrected, while strict schema checks and
assertions remained in place. These failed development runs are not presented as passing tests.

## Simulator and judgments

Seed `oua-practice`: **31,433 raw events**, **31,429 unique event IDs**, **four duplicate deliveries**, for
**1,746 triggered viewers**. All **719 home pages** were accepted. There were **501 personalised page-show
events**, **11 published-but-not-shown events**, **36 scripted organic purchases**, and **zero policy problems**.
Show counts are events, not unique users. Publication reached 467 viewers; all 863 triggered agent-arm
viewers, including the other 396 without a published action, remain in triggered-cohort ITT.

Current measurement: **759 selected goal instances for 756 viewers**; **120 SUCCEEDED, 639 FAILED,
zero INCONCLUSIVE**. Only G03, G05 and G08 were selected. Zero inconclusive here does not imply that
unsupported goals or incomplete follow-up are measurable; isolated tests exercise those abstentions.

| Goal | Succeeded | Failed |
|---|---:|---:|
| G03, corrected play on a later IST day | 2 | 48 |
| G05, observed non-trial purchase | 17 | 365 |
| G08, observed play of qualifying recent release | 101 | 226 |

Three G05 instances were cancelled during replay after paid evidence arrived and nevertheless have qualifying
observed purchases before ownership ended. Their historical lifecycle remains cancelled; their outcome
judgment is succeeded. Other terminal measured goals/plans close durably. Historical development measurement
versions remain in SQLite: three runs, 2,277 historical judgments/learning records, but **759 current-run
judgments**. Reports identify the current content/engine-derived outcome_run_id and do not pool versions.

## Randomized estimates

Full randomized population: **2,513 agent / 2,487 holdout**. Simulator follow-up covers **863 / 883**.
Known positive live events from untriggered users are retained. Paid-endpoint missingness is **1,649 / 1,603**;
play-endpoint missingness is **1,644 / 1,594**. Full-population point impact and selected-goal impact are
**not estimable**. The full report includes worst-case identification bounds, not invented confidence intervals.

Triggered-cohort ITT, same fixed seven-day receipt-time window:

| Endpoint | Agent | Holdout | Difference (pp) | 95% difference CI (pp) | Relative lift | 95% relative-lift CI |
|---|---|---|---:|---|---:|---|
| Non-trial purchase | 23/863 = 2.665% | 31/883 = 3.511% | -0.846 | -2.526 to 0.813 | -24.087% | -55.369% to 29.121% |
| Any play | 567/863 = 65.701% | 563/883 = 63.760% | 1.941 | -2.539 to 6.408 | 3.044% | -3.851% to 10.434% |

Both difference intervals include zero. This seed/run does not demonstrate a treatment benefit. Cohort
causal interpretation is conditional on the fixed trigger roster being exogenous, valid randomization,
common observation and no interference; these are not real-product impact estimates.

Pilot headline replication: served **87/217 = 40.092%** versus other **649/3,674 = 17.665%**, a descriptive
**22.427 pp** difference. This selects on post-assignment serving and is not causal. Correct randomized
label comparison is treatment **349/1,912 = 18.253%** versus holdout **387/1,979 = 19.555%**, difference
**-1.302 pp**, 95% CI **-3.760 to 1.161 pp**. Pilot labels lack independently verifiable raw success events
and complete goal-specific observation windows, so even that comparison has a narrower interpretation.

## Final validation and restart

The final complete pipeline ran twice. `sample_run/phase5_restart_check.json` reports **unchanged = true**:
all required report/action/decision/outcome hashes, raw simulator output/report hashes, aggregate viewer-state
hash and SQLite row counts match. No extra actions, reservations or outcome rows were created on rerun.
SQLite integrity is **ok**, foreign-key errors **zero**, required artifacts present, and protected inputs
unchanged, as recorded in `sample_run/phase5_pipeline_validation.json`.

All generated judgments and endpoint observations cite supplied records or actual simulator events.
`impact_report.json` retains per-user binary/unknown endpoint observations and source references, including
all randomized users. Raw events are never invented or edited. No external notification or API call occurred.
Unfinished behavior and inference limits are documented in KNOWN_LIMITATIONS.md.
