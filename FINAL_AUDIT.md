# Final independent verification audit

**Verdict: ready for submission as the documented offline assignment, with the PARTIAL items below.**
There are no unresolved critical safety, setup, execution or commit-hygiene blockers. This does not mean every
production behavior or every presentation detail is complete. No commit or external publication was performed.

This is a separate verification pass by the same Codex assistant that helped implement the project, not a
third-party certification. Independent checks reconstructed settings and success evidence from supplied records
and recomputed statistics separately from `one_agent.evaluation`. The full PDF was read from the user's supplied
`assignment_one_user_one_agent.pdf`; the original pack README is `DATA_PACK_README.md`.

## Actual execution

* Original environment: **140 passed in 19.11 s**.
* New editable-install environment: **140 passed in 45.10 s**, after the only runtime change (compact decision
  JSON formatting). Python **3.13.3**, pytest **9.1.1**. All source/tests also parse with Python 3.11 syntax rules;
  other interpreter versions were not executed.
* Fresh setup succeeded: `python -m venv .audit/venv` then
  `.audit\venv\Scripts\python.exe -m pip install -e ".[test]"`. The installed `one-agent --help` worked.
  `PYTHONPATH` was explicitly unset for the installed-package tests/pipeline.
* A pipeline started with **no generated database or output directory**:
  `.audit\venv\Scripts\python.exe -B -m one_agent.cli pipeline --pack . --db .audit/clean/replay.sqlite3 --out .audit/clean`.
  It completed and was snapshotted in **450.16 s**, including import, replay, simulation, validation, measurement, reports and initial hash verification.
* Repeating that completed clean pipeline produced **identical file hashes, viewer-state hash and SQLite counts**.
  Its database contains one outcome run and **759 judgments / 759 learning records**, without rerun duplicates.
* The submitted `sample_run` pipeline was also refreshed and repeated after compacting JSON. Its current artifact
  manifest matches every required file. Historical measurement versions remain separate in its SQLite database;
  they are not pooled in reports and the databases are excluded from Git.
* SQLite integrity: **ok**; foreign-key errors: **0**. All 17 supplied data/config/pilot/replay/simulator hashes
  match the original baseline. No supplied data or simulator code was modified.

The first clean attempt failed during outcome persistence with `sqlite3.OperationalError: database or disk is full`.
It was not counted as successful. Two redundant historical replay databases and the failed scratch run were removed
only after validating their resolved workspace paths. The successful run above then started from an empty directory.
The initial sandbox venv creation also failed during ensurepip; approved local execution completed setup successfully.
These environment failures are disclosed rather than presented as passes.

## Confirmed blockers fixed

1. Git originally resolved to **C:/Users/Raghav**, outside this project, and no project ignore file existed.
   A project-local repository was initialized; `.gitignore` now excludes environments, caches, credentials,
   all generated SQLite databases, build output and non-submission scratch/development logs. Nothing was staged.
2. `sample_run/decisions.jsonl` was **108,207,852 bytes**. Its JSON values are now exported with compact separators;
   no evidence fields or records were removed. The final file is **102,241,958 bytes**, below a conservative
   100 MiB hosting threshold. Git itself has no universal 100 MiB file limit. The formatting-only change is in
   `src/one_agent/replay.py`; all 140 tests and sample/clean pipeline reruns passed after it.
3. `.gitattributes` preserves exact source/evidence checkout bytes (`* -text`), preventing line-ending normalization
   from invalidating the supplied-pack and evidence hashes. `git check-attr` confirmed the setting.
4. Redundant generated databases exhausted local space during the first audit attempt. Cleanup retained the current
   sample database, the current audit database, original supplied inputs and historical JSON reports.

## Required submission inventory

| Required path | Status | Actual evidence |
|---|---|---|
| `README.md` | PASS | Setup, one-command replay, full pipeline, measurement and tests documented; installed commands executed. |
| `ARCHITECTURE.md` | PASS | Ownership, planning, evidence, memory, independent verification, latency, recovery and trust boundaries. |
| `AI_COLLABORATION.md` | PASS | Checked against the available conversation and executions; no invented user-rejected suggestion. |
| `KNOWN_LIMITATIONS.md` | PASS | Missing definitions, measurement identification, mocked timing and offline learning scope disclosed. |
| `src/` | PASS | Nineteen Python modules, including CLI, store, planner, verifier, replay, outcomes and evaluation. |
| `tests/` | PASS | Five test modules; 140 tests passed, including required late/duplicate, conflict, failure and correction cases. |
| `sample_run/decisions.jsonl` | PASS | 2,769 valid JSON delivery records; 2,679 unique-trigger decisions and 90 duplicate references. |
| `sample_run/viewer_state/` | PASS | 1,746 per-viewer JSON files with facts/provenance/uncertainty, active state, outcomes and learning. |
| `sample_run/actions.jsonl` | PASS | 719 simulator-compatible home-page actions with unique action/decision/trigger identity and publication time. |
| `sample_run/outcomes.jsonl` | PASS | 759 current-run goal-instance judgments with windows, rule/signal, evidence and reasons. |
| `sample_run/latency_report.json` | PASS | Measured processing/queue/publication distributions, failures and deadline-exceedance counts. |
| `sample_run/impact_report.md` | PASS | Randomized denominators, missingness, confidence intervals, non-estimable metrics and pilot bias audit. |
| `sample_run/final_report.md` | PASS | Actual simulator, replay, goal, impact and limitation summary. |
| `pyproject.toml` | PASS | Editable install and CLI entry point worked in a new environment. |
| Supplied pack / simulator | PASS | All 17 protected inputs exist, are commit candidates, and retain original byte hashes. |

## PDF requirements, behavior and surprises

PASS means executed evidence supports the implemented requirement; PARTIAL identifies a disclosed limitation,
not an invented pass. No unresolved FAIL remains in the required runnable submission or safety path.

| PDF / README requirement | Status | Supporting paths and actual evidence |
|---|---|---|
| Understand viewers using known evidence, sources, time and freshness | PASS | `src/one_agent/evidence.py`, `store.py`, decisions and viewer-state facts; independent reconstruction of action-time settings passed. |
| Fact-specific source precedence and explicit disagreement | PASS | `evidence.py`, `tests/test_memory.py`, `test_planning.py`; current app settings, profile/deeplink disagreement and missing-profile cases. |
| Treat receipt time as trustworthy; preserve device timestamps | PASS | `store.py`, `schemas.py`, `outcomes.py`; independent attribution checks use receipt time. True device occurrence chronology is not asserted. |
| Deduplicate events and content variants | PASS | `store.py`, `interventions.py`; event_id deduplication, all 719 pages checked for content_slug uniqueness; four simulated redeliveries retained raw and counted once. |
| Choose one measurable eligible goal, or abstain | PASS | `goals.py`, `planner.py`; all 12 eligibility outcomes retained, G06/G10/G11 disabled, finite-history uncertainty respected; only G03/G05/G08 selected here. |
| Preserve commitment, goal version, deadline and success signal | PASS | Goal/plan SQLite APIs, `planner.py`, `outcomes.py`; every measured deadline matches its configured window and supplied version. |
| One agent / active goal / active plan per viewer | PASS | `store.py` unique indexes `one_open_goal`, `one_active_plan`; zero ownership violations in the clean database. |
| Plan/revise on new evidence, including a purchase after a never-paid snapshot | PASS | Replay ingests current evidence; three historical G05 goals were cancelled before G08 selection; their observed qualifying purchases are separately judged. |
| Home-page hero/rows, content existence, dialect, language and availability | PASS | `interventions.py`, `verifier.py`, `publisher.py`; all 719 actions independently checked against action-time feed, catalogue, row bounds and withdrawals. |
| Push / WhatsApp / in-app / NO_ACTION options | PASS | Proposal/publisher code plus `tests/test_verification.py` and `test_replay.py`; default actual run safely publishes pages only, without inventing consent to demonstrate other channels. |
| Consent, later opt-out, quiet hours, daily caps and templates | PASS | Independent verifier and transactional reservations; concurrent shared-cap, later-opt-out, forged quiet-hour push and publication-time cap tests passed. Actual simulator policy problems: zero. |
| Independent pre-action and publication-time verification | PASS | `verifier.py` imports no planner; independent raw-record audit confirms all published titles/settings/availability. Approvals are separate from actions. |
| Data/generated text must not be instructions or eligibility evidence | PASS | Catalogue-injection and unsupported-model-claim tests; local provider advice is untrusted and cannot update eligibility facts. |
| Explicit NO_ACTION / insufficient evidence | PASS | 1,960 unique-trigger no-actions and 90 separate duplicate-delivery audits; reasons and actual errors retained. |
| Complete common audit envelope for every failure decision | PARTIAL | Sixteen store-timeout abstentions retain trigger, error/reason, budget and NO_ACTION, but omit the ordinary planner confidence/fact/assumption block. They publish nothing; richer explicit UNKNOWN fields are an optional presentation improvement. |
| Confidence explanation, assumptions, conflicts and checks on ordinary decisions | PASS | `planner.py`, `verifier.py`, decisions; explained qualitative confidence, not a fabricated calibrated probability. Failed-before-read cases are the PARTIAL row above. |
| Publish within 60 s; report >5 min failures | PASS | Clean replay: maximum publication 0.869 s, total-decision maximum 0.902 s; zero >60 s / >5 min. Stored sample has its own measured maximum 44.861 s, also under 60 s. |
| Configurable maximum 8 model / 20 tool calls | PASS | `budget.py`, replay hard-limit tests; observed maximum one model and eleven logical tool operations per decision. Failed admitted operations count. |
| Read/call models only when reducing meaningful uncertainty | PARTIAL | The mock is called for each unique trigger and its advice is then discarded in favor of deterministic planning; calls fit budget but many are unnecessary. No hosted-model cost is claimed. |
| Durable facts, conflicts, profile versions, decisions, actions, outcomes and learning | PASS | `store.py`, `publisher.py`, `outcomes.py`; fresh SQLite integrity passed; JSON evidence plus source pack can reconstruct the ignored runtime database. |
| Buffered/late/duplicate trigger surprise | PASS | `replay.py`, late/duplicate tests; 239 potential-buffer/clock-skew abstentions. The 24-hour device-age heuristic is conservative engineering policy, not proof of true offline age. |
| Conflicting app/profile/deeplink surprise | PASS | Tested explicitly; independent current settings reconstruction found zero publication mismatches. |
| Goal correction during replay, including open G03 goals | PASS | `runtime.py`, replay control migration, verifier and outcome tests; all 50 G03 judgments use play_started on a later IST day with control references. |
| Unsupported eligibility claims / malformed output / timeout surprise | PASS | All five supplied fault triggers invoked the mock in the sample; deterministic fallback or abstention, never claim-based eligibility. |
| Accurate outage-delay distribution / production timing demonstration | PARTIAL | Declared 45-second model timeout is emulated immediately; degraded store uses bounded 250 ms reads, not a calibrated 20% timeout / 8 s p95 backend. These limits are explicit in `KNOWN_LIMITATIONS.md`. |
| Catalogue-description prompt injection surprise | PASS | Descriptions are not executed; independent safety checks and injection tests passed. |
| Traffic burst / queues / stale requests | PASS | Source replay completed; burst, queue timing, duplicates and queued-settings tests passed; clean queue maximum 0.242 s. |
| Recover safely after failure/restart; no duplicate actions/reservations | PASS | Durable outbox/checkpoints, uniqueness constraints, crash tests and two actual complete repeats; hashes and row counts unchanged. |
| Judge success/failure/inconclusive using attributable events | PASS | `outcomes.py`; 120 positive judgments have qualifying observed viewer events; 639 failed windows are complete; zero attribution errors. No action or model claim is a success signal. |
| Incomplete observations cannot become failure | PASS | Independent coverage check found zero incomplete failures; partial-window, missing-user, unsupported-rule/signal and cancellation tests passed. |
| Individual causal attribution / true device event time | PARTIAL | Results are explicitly receipt-window attainment. Individual intervention causation and unreliable device occurrence time are not identified by this pack. No such claim is made. |
| Record viewer learning and close measured goals | PASS | 759 current-run judgments/lessons in the clean database, matching viewer-state exports; terminal plans closed without changing historical cancelled lifecycle. |
| Automatic future live outcome-to-replanning loop | PARTIAL | Outcomes/learning remain separate from replay facts; automatic reconciliation and execution of a next goal after future follow-up is not implemented. Offline measurement is complete. |
| Compare randomized arms and include NO_ACTION users | PASS | `evaluation.py`; 2,513/2,487 full-population denominators and 863/883 scripted-triggered-cohort denominators, including 396 triggered agent viewers with no publication. |
| Honest missingness and unmeasurable goal-specific impact | PASS | All randomized users remain represented; untriggered live positives are retained and other follow-up unknown. Full-population point impact and selected-goal impact are explicitly not estimable. |
| Conversion rates, pp difference, relative lift and confidence intervals | PASS | Independently recomputed success sets and score/Newcombe/log-RR intervals match both endpoints to numerical tolerance; both difference intervals include zero. |
| Audit earlier pilot served-versus-unserved bias | PASS | `pilot_audit`, supplied pilot files and report; 217 served treatment users versus 1,695 unserved treatment + 1,979 holdout is not randomized. Independent randomized label comparison matches report. |
| Only supplied evidence, no invented titles, history, outcomes or consent | PASS | Protected hashes unchanged; simulator output validated; success/evaluation source references checked; unsupported definitions remain unsupported. |
| Local privacy / no API keys required / mock provider | PASS | Standard-library runtime, local simulator/provider, no runtime external API. Commit candidate scan found no recognized secret patterns; public dependency installation is setup, not a data upload. |
| Reproducible setup and one-command replay/pipeline | PASS | New editable install and installed CLI worked with PYTHONPATH unset; empty-state full pipeline and complete repeat succeeded. |
| Architecture / AI collaboration / limitations documents | PASS | Required files reviewed; collaboration log accurately describes checks and self-corrections and explicitly invents no user-rejected suggestions. |
| Suggested effort / four-day human submission window | PARTIAL | Human effort/deadline compliance cannot be established from workspace artifacts; no time-spent claim is fabricated. |
| Technical discussion / production-scale questions | PARTIAL | Design and limits are documented for discussion; 10-million-user/40-dialect deployment and a human technical interview were not demonstrated. They are not prerequisites for this local working submission. |

The PDF's evaluation weights are human grading criteria, not scores this audit can award. The evidence above
covers goal/decision quality, provenance/state, reliability, verification, measurement, engineering and AI use.
No numerical grade or real-product uplift is invented.

## README / simulator contract cross-check

| Contract item | Status | Evidence |
|---|---|---|
| All listed pack files and formats | PASS | Seventeen original protected inputs; loaders and original hash manifest. |
| UTC timestamps / IST policies / untrusted device times | PASS | Typed parsing, receipt-order state, IST day/quiet-hour checks and independent event-window reconstruction. |
| Merge triggers/live/control delivery timestamps | PASS | `replay.py`: deliver_at/deliver_at/at, deterministic stream/line ties, queued-trigger memory ingestion. |
| Unique action/decision/viewer/trigger/type/publication fields | PASS | Independent JSON/action checks and simulator acceptance of all 719 actions. |
| Actual schema constraints / content_slug / availability | PASS | All page rows and titles independently validated against catalogue and controls. Other channel policies are unit-tested. |
| Supplied unchanged simulator invocation and output | PASS | Executed from new environment; 31,433 events, 719 accepted pages, zero policy problems. |
| Same completed run + same seed reproducibility | PASS | Actual full repeats preserve raw simulator outputs, reports, viewer-state hash and database counts. Fresh measured runs can legitimately have different timestamps and exposure counts. |

## What the counts mean

* **5,000 randomized users**: 2,513 agent / 2,487 holdout. Randomization is not an outcome observation.
* **2,769 trigger deliveries** include **90 duplicates**, leaving **2,679 unique-trigger decisions** for
  **1,746 viewers**. A viewer can trigger more than once.
* **719 actions** were published across **467 viewers**; 1,960 unique-trigger decisions published nothing.
  All 863 triggered agent viewers, including 396 without a published action, remain in cohort ITT.
* **759 goal-instance judgments** belong to **756 viewers**. Three viewers changed goal, creating a second
  historical goal instance. No holdout goal assignment or success judgment was fabricated.
* **31,433 raw simulator behavioral events**, with four redeliveries, become **31,429 canonical event IDs**
  for counting. These events are not the 759 goal-level outcome judgments.
* **1,746 viewer-state files** contain latest facts with source/time/status/conflicts, current active state,
  judgments and lessons. Null active state after terminal measurement is expected. Full profile/event/plan
  history resides in regenerated SQLite and supplied/global evidence rather than being duplicated in every JSON.

## Actual measurements and inference

| Run | Publication p50 | p95 | p99 | Maximum | >60 s / >5 min |
|---|---:|---:|---:|---:|---:|
| Submitted sample | 0.188 s | 0.367 s | 0.561 s | 44.861 s | 0 / 0 |
| Clean audit | 0.150 s | 0.252 s | 0.423 s | 0.869 s | 0 / 0 |

Both runs contain 719 accepted pages and 120 succeeded / 639 failed / zero inconclusive selected-goal
judgments. The clean run has 502 personalised-show events versus the stored sample's 501 because measured
publication times differ. This is a legitimate simulator timing effect, not a fabricated or rewritten observation.
Fixed completed-run repeats are identical; fresh-run hashes need not match the historical sample.

| Seven-day endpoint, triggered-cohort ITT | Agent | Holdout | Difference (pp) | 95% difference CI (pp) | Relative lift | 95% relative-lift CI |
|---|---|---|---:|---|---:|---|
| Non-trial purchase | 23/863 (2.665%) | 31/883 (3.511%) | -0.846 | -2.526 to 0.813 | -24.087% | -55.369% to 29.121% |
| Any play | 567/863 (65.701%) | 563/883 (63.760%) | 1.941 | -2.539 to 6.408 | 3.044% | -3.851% to 10.434% |

Both intervals include zero; this seed/run does not demonstrate a benefit. These are common event endpoints,
not an invented shared selected-goal metric. Full-population purchase outcomes have 1,649 agent / 1,603 holdout
missing; play has 1,644 / 1,594 missing. Full-population and selected-goal point impact remain not estimable.
The reports correctly distinguish worst-case population identification bounds from confidence intervals.

Pilot labels: treatment 349/1,912 versus holdout 387/1,979; difference **-1.302 pp**, 95% CI **-3.760 to 1.161**.
The served-versus-other **+22.427 pp** association is not causal. Raw pilot success signals and comparable
complete goal-specific windows are unavailable, so the randomized pilot comparison is limited to supplied labels.

## Commit hygiene and exact commands

The project-local repository has no tracked/staged files yet. All required files and protected inputs are normal
Git candidates. No recognized private-key, AWS/OpenAI/GitHub token or assigned-secret patterns were found in those
candidates. This is a heuristic content scan, not mathematical proof against arbitrary unknown secret formats.
Virtual environments, audit scratch state, egg-info, caches, all SQLite databases and development logs are ignored.
The source/data/simulator and final JSON evidence are included. The current sample database stays local and can be
regenerated from the included pack; its omission does not remove the submitted per-viewer JSON evidence.

Run these from PowerShell to make a local commit after reviewing the staged summary:

```powershell
Set-Location -LiteralPath 'C:\Users\Raghav\Downloads\one_user_one_agent_data_pack\one_user_one_agent_pack'
git rev-parse --show-toplevel
git add -- .gitignore .gitattributes pyproject.toml *.md AUDIT_EVIDENCE.json src tests config data pilot replay simulator sample_run
git diff --cached --stat --stat-count=30
git diff --cached --name-only -- .venv .audit '*.sqlite*' '*.db' '*.tmp' '.env*'
git commit -m "Complete One User One Agent assignment"
git status --short
```

The root command must print this project directory. The excluded-path check should print nothing.
No remote or push command is included. `AUDIT_EVIDENCE.json` records actual execution, independent calculations,
source hashes, restart proofs and commit-scope checks. `.audit/` contains local detailed scratch results and is excluded.

## Optional improvements, not unresolved critical blockers

1. Enrich the 16 safe-failure audit envelopes with explicit UNKNOWN confidence/fact/check fields.
2. Avoid mock consultation for deterministic/holdout abstentions except fault-injection exercise where appropriate.
3. Filter language variants earlier in planning rather than relying on safe verifier rejection.
4. Add realistic backend timing simulation and asynchronous post-outcome reconciliation if expanding beyond this offline assignment.
5. Test additional Python/runtime platforms; only Python 3.13 was executed here.

These are disclosed PARTIAL items. No unsafe action, missing required submission file, failing test, unverifiable
FAILED window, fabricated causal result, or unresolved execution/commit blocker was found in the final verified state.
