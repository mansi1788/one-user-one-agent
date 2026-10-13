# Phase 4: local replay and safe simulated publication

Implemented modules: `replay.py`, `publisher.py`, `runtime.py`, and `output_validation.py`.
Extended the CLI, planner trigger binding, budget instrumentation, verifier publication checks,
and immutable episode caching. Existing ingestion, uncertainty and disabled-goal behavior is retained.

## Running locally

```powershell
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -B -m one_agent.cli replay --pack . --db sample_run/replay.sqlite3 --out sample_run
```

The replay merges controls by `at`, live events by `deliver_at`, and triggers by `deliver_at`.
Ties use controls, then live events, then triggers, with original file line order within a stream.
It runs a single worker, measures service time with a monotonic clock, accounts for queue time,
and drains reached live/control/queued-trigger arrivals during decisions. Device timestamps remain untrusted.
A request whose device occurrence is more than the configurable 24-hour threshold behind delivery
is conservatively suppressed as potentially buffered or clock-skewed; this is not a lifetime fact
or an assertion that the device clock is correct.

Each unique trigger consults the existing local mock, invokes deterministic planning, verifies,
then verifies again before a final authoritative publication check. Model advice is never eligibility
evidence. Eight model calls, twenty logical repository/provider tool operations, and sixty seconds
are upper bounds; they can be configured downward. SQLite statements within one repository
operation and transport/control checkpoint bookkeeping are not separate tool calls.

Publication is exclusively an INSERT into a local SQLite simulated-action ledger. JSONL exports
are atomically replaced from that ledger. No message is sent and no outcome simulator is invoked.
Home-page, push, WhatsApp and in-app fields follow the supplied channel contracts. Explicit
NO_ACTION is stored in decisions and never emitted as an action. The default planner prefers pages;
`--channel` supports inspection/replay of other existing proposal paths without overriding consent.

Approvals, messaging reservations, pending/cancelled/published outbox records, action identities,
unique trigger results, per-delivery checkpoints and processing budgets are durable. Publication
checks title availability, reached withdrawal controls, app settings, consent, quiet hours, deadlines,
and the current IST-day reservation. Published reservations remain consumed even if a subsequent
verification revokes an approval. Actions have uniqueness constraints on action, decision and trigger.
Reruns recover the persisted proposal/publication and recreate exports without publishing again.
Changed pack contents or settings require a new replay database.

G03 corrections update only still-open G03 goals/plans and their persisted effective rule. The base
pack version remains unchanged; the control's durable identity/payload records the amendment.
Old decision audits remain immutable. Withdrawals are checked against reached controls rather than
rewriting catalogue evidence. Dependencies expire at their supplied `until` timestamps.

## Reliability boundaries

* This is a deterministic single-worker local replay, not a production multi-worker dispatcher.
  SQLite reservation transactions and uniqueness constraints protect message caps; concurrent
  replay drivers against the same database are not a supported deployment topology.
* The existing mock emulates its 45-second model timeout without sleeping. Measured latency therefore
  describes the local mock, not real model-service performance. Malformed and unsupported outputs
  use deterministic fallback; budget exhaustion abstains.
* During the supplied store-degradation interval, a conservative client read deadline (default
  250 ms) fails closed. This does not reproduce a calibrated distribution with exactly 20% server
  timeouts and 8-second p95. The source contains aggregate descriptions, not per-call outcomes.
  Actual local wait time is measured and recorded; no fabricated backend timings are reported.
* Goals still require proven eligibility. G06/G10/G11 remain disabled. Snapshot consent uncertainty
  can block planner message proposals. The preserved planner can propose dialect-matching titles
  with a different language; the independent verifier rejects those proposals rather than relaxing
  its check. No missing facts, titles, outcomes or eligibility rules are invented.
* A crash during a decision can leave a conservative pending reservation. Recovery revalidates it;
  it does not automatically free an unpublished reservation without checking the approval.
* Future scheduled message proposals represent local simulator scheduling intent, with policy and
  availability checked at the proposed send time. No real future-delivery service is implemented.
* Publication timestamps identify the final checked ledger linearization point. Export/file-write
  time is excluded from publication latency; processing time includes the subsequent ledger commit.
* An interrupted initial run remains in `sample_run/replay_interrupted.sqlite3`. A long pause was correctly
  measured and caused deadline abstentions. The final database `sample_run/replay.sqlite3` is the reported
  demonstration run. A pre-fix development run remains in `replay_uninterrupted.sqlite3`. These databases are local generated artifacts, not changes to the pack.

## Actual validation

The final test result, uninterrupted replay counts, latency percentiles, output validation and
rerun identity checks are recorded below after execution. Full machine-readable metrics are in
`sample_run/latency_report.json`; source/evidence and per-call records are in `decisions.jsonl`
and SQLite. Viewer exports retain provenance, uncertainty and the single active goal/plan.

The final replay was seeded from the already imported Phase 1 baseline in a separate derived
SQLite database (140,730 historical events and 29,976 baseline facts). Replay events, decisions,
controls, reservations and checkpoints were cleared only in that new derived database before
execution, and goal rules restored from the actual config. Source CSV/JSONL/config files were
never edited. This reused the completed ingestion without repeating its materialization cost.
The completed database was renamed from `replay_final.sqlite3` to the default `replay.sqlite3`.

### Executed results

* Full suite: **110 passed in 27.58 s**. This includes the original 85 tests and 25 Phase 4 tests.
  Sandbox-only attempts could not access pytest temporary directories; the suite was run with
  the tool's approved local execution permission. An initial direct module invocation needed
  `PYTHONPATH=src`; the successful commands above include that setting.
* Complete final replay: **3,380 merged items**: 2,769 trigger deliveries (2,679 unique and 90
  duplicates), 607 live deliveries, and four controls.
* **719 published simulated home pages**, **zero holdout actions**, and **1,960 unique-trigger
  no-action outcomes**. No outbound or in-app messages were published by the default auto planner.
* **16 safe TimeoutError abstentions** during the supplied store-degradation interval. No other
  final-run decision exceptions occurred. Zero decisions exceeded 60 seconds or five minutes.
* Observed maximum: **one model call and eleven tool calls** per decision.
* All five supplied model-fault triggers invoked the mock once, and used untrusted-output handling
  with deterministic fallback. Two unsupported-claim triggers and the malformed-output trigger
  published independently verified pages; the other unsupported claim and timeout trigger
  abstained. No model claim was adopted as eligibility evidence.
* All **50 still-open G03 goals** use the corrected `play_started` success signal.
* Export validation: **valid**, no errors, SQLite integrity **ok**, **zero foreign-key errors**,
  and all original supplied-pack file hashes unchanged. **1,746 viewer-state files** exported.

Measured seconds (rounded):

| Metric | p50 | p95 | p99 | Maximum |
|---|---:|---:|---:|---:|
| Processing | 0.124 | 0.306 | 0.474 | 44.892 |
| Queue | 0 | 0 | 0.177 | 37.163 |
| Total decision | 0.124 | 0.328 | 0.526 | 44.892 |
| Publication latency | 0.188 | 0.367 | 0.561 | 44.861 |

No-action reasons (unique triggers):

| Reason | Count |
|---|---:|
| Randomized holdout | 1,180 |
| Current app language mismatch | 323 |
| Potential offline buffering or untrusted device-clock skew | 239 |
| No measurable goal with proven eligibility | 130 |
| No available matching content | 51 |
| Unknown current app dialect | 20 |
| Bounded store-read timeout | 16 |
| Existing goal retained with unknown eligibility | 1 |

Validation commands actually executed after replay:

```powershell
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -B sample_run/validate_phase4.py
.venv\Scripts\python.exe -B -m one_agent.cli replay --pack . --db sample_run/replay.sqlite3 --out sample_run
```

`sample_run/phase4_validation.json` records schema/evidence checks, integrity, fault coverage,
G03 state, budget maxima and the action SHA-256. A separate subprocess rerun compares the
SHA-256 of actions, decisions and latency report and the SQLite action/approval/reservation/goal/
plan/trigger counts; its actual result is saved in `sample_run/phase4_restart_check.json`.
The outcome simulator has not been run.

Final restart check: **unchanged = true**. Actions, decisions and latency-report hashes are identical
before and after the subprocess rerun. SQLite counts are unchanged: 719 published actions,
719 approvals, zero messaging reservations, 759 goal/plan records and 2,679 unique trigger results.
One active goal/plan per viewer is still enforced by the existing partial unique indexes.

Added tests are in `tests/test_replay.py`. Modified existing modules are `cli.py`, `planner.py`,
`store.py`, `verifier.py`, `goals.py`, and `budget.py`; the mock provider implementation was reused.
Created outputs include `decisions.jsonl`, `actions.jsonl`, `latency_report.json`, `viewer_state/`,
`phase4_validation.json`, `phase4_restart_check.json`, `phase4_rerun_stdout.json` and the local
validation script, all under `sample_run/`.
