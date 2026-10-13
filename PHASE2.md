# Phase 2: deterministic planning

Existing Phase 1 ingestion, evidence resolution and eligibility are reused. New planner and intervention modules build proposals without model calls, message delivery, home-page publication, replay execution or simulator execution.

## Commands

From the workspace:
```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -B -m one_agent.cli plan --pack . --db sample_run/viewer_memory.sqlite3 --user U-00042 --as-of 2026-10-01T00:00:00Z
.venv\Scripts\python.exe -B -m one_agent.cli plan --pack . --db sample_run/viewer_memory.sqlite3 --user U-00001 --as-of 2026-10-01T00:00:00Z
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Use --channel auto, home_page, push, whatsapp, in_app_message or no_action. Alternatives are mutually exclusive options, not a batch to send. Every proposal has publishable=false; Phase 3 must verify it independently. No published_at is invented.

## Selection and memory

The planner resolves and persists facts as of the requested server time, reads back that snapshot, and retrieves history and persisted conflicts. Future replay triggers are not consumed. It evaluates all twelve configured goals through Phase 1. G06/G10/G11 remain explicitly disabled; unknown eligibility cannot create a goal.

Implementation priority is G01, G02, G03, G04, G05, G07, G12, G09, G08. This is a documented engineering choice, not evidence of uplift. Only eligible goals with measurable success events can be selected. A selected goal starts its configured window at commitment.

An existing goal retains its deadline and plan identity while supported. Unknown current eligibility pauses proposals rather than replacing the goal. New ineligibility cancels the old goal/plan before selecting another supported goal. Signup acquisition windows are evaluated at commitment for an existing G03 goal; ageing alone does not cancel it. Deadline expiry is recorded as inconclusive, not an observed failure or success.

Atomic SQLite persistence uses the existing tables, unique active-state constraints, a write transaction and an optimistic active-state check. An evidence/input digest identifies a decision; repeated identical requests return the persisted JSON and create no additional goals, plans or decisions. New relevant evidence generates a new audit. Historical requests cannot move an active plan backwards in time.

## Intervention proposals

Available catalogue records are filtered by known app dialect and deduplicated by content_slug. G08 content must be a release in the goal's configured 30-day interval. Ranking uses observed viewer plays then title ID, not catalogue descriptions. Home pages use at most one hero and valid genre rows within configured limits. Empty rows are omitted. Descriptions are never interpreted or executed.

Known withdrawals effective by the inspection time are read from the supplied control file as catalogue exclusions. Future controls are not consulted as current evidence. No control stream is replayed.

Push and WhatsApp require proven true consent and valid IST time; observed deliveries consume their shared daily cap. WhatsApp uses only the approved recommendation template in the known app language, with catalogue-derived variables. In-app content uses fixed honest copy and its separate daily cap. Missing/ambiguous arm assignments and holdout always produce NO_ACTION, without content alternatives. Holdout can never obtain an active publishable plan.

## Limitations

Phase 1's conservative lifetime-history and G07 uncertainty remain. Its stale-positive consent behavior blocks actual-pack push and WhatsApp proposals; explicit known-consent builder fixtures test those code paths without inventing viewer consent. Freshness is reported in seconds; no undocumented freshness cutoff is invented.

The supplied config is checked against persisted goal rules. G03's mid-replay correction is not applied by this inspection-only phase; rule-correction processing belongs to the later replay lifecycle. Preview availability and consent can change before action time. Final frequency reservations, policy checks and publication require Phase 3. In-app message body structure is an internal proposal convention because the supplied catalogue specifies no exact body schema.

No outcomes or causal claims are inferred from these plans. Test fixtures are synthetic and never used as evidence for actual viewers.
