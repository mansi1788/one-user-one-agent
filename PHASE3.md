# Phase 3: independent local verification

New modules: verifier.py, provider.py and budget.py. Existing SQLite databases gain approvals, message_reservations, verifications and call_audits through additive CREATE TABLE/INDEX statements. Phase 1/2 tables, APIs and behavior remain intact.

## CLI

With PYTHONPATH=src:
```powershell
.venv\Scripts\python.exe -B -m one_agent.cli verify --pack . --db sample_run/viewer_memory.sqlite3 --decision <persisted-decision-id> --as-of 2026-10-01T00:00:00Z
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Optional --max-model-calls (8), --max-tool-calls (20), and --max-seconds (60) bound each verification attempt. CLI lookup is counted. Verdicts are APPROVED, REJECTED or ABSTAINED, with individual check results, reasons, evidence and a call audit. No publisher or action-export path is implemented. APPROVED means a local safety approval, not a published or delivery-confirmed action. publishable remains false and re-verification is required before any future publication.

## Trust and policy

The verifier imports no planner code. It rereads actual configuration, policy, arms, effective controls, and SQLite viewer history, profile versions, catalogue, goal rules and active goal/plan state. Planner facts, eligibility flags, generated text and confidence do not establish evidence. Shared pure evidence/rule functions are invoked with freshly loaded authoritative records.

Checks cover goal identity/version/window/success definition, eligibility, holdout, latest settings, catalogue identity and language/dialect, availability and known withdrawal, content_slug uniqueness, page dimensions, consent/opt-outs, quiet hours, channel rules, copy, deeplinks, scheduling and expiration. A known goal correction makes the old success definition fail closed; this phase does not replay controls or migrate open goals.

Consent is independently checked against the latest available profile consent field and observed opt-outs. Conflicting equally current versions cannot authorize consent. This does not modify Phase 1's conservative unknown positive-consent facts or Phase 2's blocked outgoing options.

The pack's one combined outbound message per IST day and configured in-app limit use separate scopes. Observed deliveries plus reserved slots consume caps. BEGIN IMMEDIATE protects reads, duplicate checks, approval insertion and reservation insertion. A partial unique index prevents concurrent use of the same viewer/day/scope/slot. Decision, trigger, semantic action and optional external action IDs also have durable uniqueness constraints. Identical verification reuses one approval and reservation. Failed re-verification revokes a previous approval and releases its reservation.

Inspection proposals without triggers are identified as inspections, not as timed replay decisions. When a SQLite decision has a trigger, its identity, owner, delivery time and 60-second latency bound are verified. Nothing claims to have published within the replay latency budget.

## Mock model and budgets

MockProvider returns the exact supplied model_output for matching triggers and raises ModelTimeout with the supplied seconds for timeout faults. Timeout faults are emulated immediately without sleeping; declared duration is not reported as measured runtime. Normal responses are deterministic. consult always treats advice as untrusted and uses deterministic fallback; budget exhaustion abstains without invoking the fallback. No model output is written to viewer facts or used as eligibility evidence.

Budgets count admitted logical provider calls and repository/config bundle operations, not individual SQL statements within one repository operation. Denied calls do not execute. Failed calls still count. Audit-only recovery logging is excluded from action/tool retries. Verification stores its call log durably; provider calls using the same Budget appear in that verification's audit. Limits are per attempt; the future replay orchestrator must share one Budget across its full decision pipeline.

## Deliberate limits

No publishing, replay engine or simulator runs exist. Future schedules reserve the relevant IST day but remain conditional on re-verification. Reservations are conservative: elapsed time alone does not release them. Re-verification can revoke an unsafe approval.

Arbitrary generated copy is rejected rather than accepted through a shallow phrase scan. Push and in-app currently support only independently substantiated fixed copy. WhatsApp recommendation variables are checked against catalogue records; new-episode and ending-trial claims remain blocked because this implementation cannot substantiate their freshness from supplied metadata. No invented prices or discounts are accepted. Language matching is conservative for title variants.

Phase 1 lifetime-history uncertainty and disabled G06/G10/G11 remain. No new outcomes, exposure or uplift claims are made. Test fixtures are isolated synthetic cases, not actual viewer evidence.

## Validation

The full suite passed: 85 tests (including the original 45). Actual demonstration verdicts and source-integrity checks are recorded under sample_run/phase3.
