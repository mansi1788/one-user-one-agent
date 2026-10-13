# One User, One Agent

Local Python implementation of the supplied hiring assignment: durable viewer memory, deterministic
planning, independent policy verification, safe simulated publication, outcome judgments and randomized
measurement. All viewer/title evidence comes from the supplied pack or its unchanged outcome simulator.
No API keys, network calls, UI or actual notifications are required.

The original pack README and exact data/action formats are preserved in [DATA_PACK_README.md](DATA_PACK_README.md).

## Setup

Python 3.11+ and pytest for tests; runtime uses only the standard library. From this directory:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
```

An editable install provides `one-agent`. Alternatively use `$env:PYTHONPATH='src'` and
`.venv\Scripts\python.exe -B -m one_agent.cli` without installing the project. On POSIX use
`.venv/bin/python` and `PYTHONPATH=src`. No model credentials are needed; the provider is local and mocked.

## One-command replay

```powershell
.venv\Scripts\python.exe -B -m one_agent.cli replay --pack . --db sample_run/replay.sqlite3 --out sample_run
```

A fresh database imports the pack; a completed database recovers its durable checkpoints and exports
without publishing again. Use a new database and output directory for a new independent measured replay.
Do not compare fresh-run latency hashes: elapsed times are measured and naturally vary.

## One-command end-to-end submission pipeline

```powershell
.venv\Scripts\python.exe -B -m one_agent.cli pipeline --pack . --db sample_run/replay.sqlite3 --out sample_run
```

This runs replay/recovery, independent action validation, the supplied simulator, simulator-output
validation, goal outcome measurement, randomized/pilot evaluation and submission reports. All files stay
local. The simulator command used internally is exactly:

```powershell
.venv\Scripts\python.exe -B simulator/simulate_outcomes.py --pack . --actions sample_run/actions.jsonl --out sample_run/sim
```

To judge existing simulator output without running it again:

```powershell
.venv\Scripts\python.exe -B -m one_agent.cli measure --pack . --db sample_run/replay.sqlite3 --out sample_run
```

`measure --as-of <UTC timestamp>` censors observations at that point; incomplete follow-up cannot become
failure. Existing `validate`, `ingest`, `viewer`, `plan` and `verify` commands remain available. `plan` and
`verify` never publish; replay publishes exclusively to SQLite and simulator-compatible JSONL.

## Tests and artifacts

```powershell
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

The sample run includes `decisions.jsonl`, `actions.jsonl`, `outcomes.jsonl`, `latency_report.json`,
`viewer_state/`, `impact_report.md`, `final_report.md`, simulator output under `sim/`, and validation
manifests/hashes. SQLite stores facts/conflicts, goal/plan history, approvals/reservations, the outbox,
checkpoints, raw outcome deliveries, deduplicated outcome events, judgments and viewer learning.

## Reading the results

Goal attainment is not individual causal attribution. All randomized users remain in full-population ITT
analysis; untriggered users lack complete simulator follow-up. Their known positive live signals are kept,
and other outcomes remain unknown. Full-population point impact and selected-goal impact are not estimable.
A separate randomized scripted-triggered-cohort analysis uses common seven-day event definitions and
includes agent viewers receiving NO_ACTION. Its interpretation is conditional on an exogenous trigger
roster, valid randomization and comparable observation. Served-versus-unserved differences are descriptive.

See [ARCHITECTURE.md](ARCHITECTURE.md), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md),
[AI_COLLABORATION.md](AI_COLLABORATION.md), and the actual results in
[sample_run/final_report.md](sample_run/final_report.md) and
[sample_run/impact_report.md](sample_run/impact_report.md). PHASE1.md through PHASE4.md document earlier
milestones; statements about unimplemented later phases in those historical notes describe their original scope.
