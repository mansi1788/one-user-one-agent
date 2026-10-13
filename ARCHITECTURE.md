# Architecture

## Ownership and memory

SQLite is the authority for one agent per viewer. A partial unique index enforces one open goal and one
active plan. Events deduplicate by event_id; profiles retain all source versions. Receipt time orders
knowledge; device occurrence/sent timestamps remain untrusted. Facts retain source references, timestamps,
freshness and conflicts. App settings take precedence for current dialect; profile/deeplink disagreements
remain visible. Missing lifetime history and stale consent are not converted into certainty.

```mermaid
flowchart LR
  Pack[Local pack and delivery streams] --> Memory[SQLite viewer memory]
  Memory --> Planner[Deterministic goals and proposals]
  Mock[Untrusted local model advice] --> Planner
  Planner --> Verify[Independent authoritative verifier]
  Verify --> Outbox[Transactional approval and outbox]
  Outbox --> Publish[Publication-time checks and local action ledger]
  Publish --> Sim[Unchanged supplied simulator]
  Sim --> Measure[Observed outcomes and randomized evaluation]
  Measure --> Learning[Durable judgments and viewer learning]
```

## Evidence and planning

`ingestion`, `schemas`, `evidence` and `goals` validate source records and implement fact-specific
resolution and three-valued eligibility. `planner` owns goal choice and respects an active plan unless new
evidence invalidates it. Goals reference the pack version, original commitment/deadline and success signal.
G06/G10/G11 stay disabled; G07 cannot be proven from finite history. `interventions` uses catalogue identity,
app dialect, availability and content_slug deduplication. Catalogue descriptions and device data are content,
never executable instructions. Confidence is explained evidence sufficiency, not a calibrated uplift estimate.

## Independent verification and trust boundaries

`verifier` imports no planner implementation. It reloads actual config/policy, arms and authoritative SQLite
records; model claims and planner checks cannot authorize anything. It checks goal/rule/window, dialect and
language, content, consent, quiet hours, shared outbound/in-app caps, templates, copy, deeplinks and duplicates.
Transactions and partial unique reservation indexes protect simultaneous cap claims. Approval remains distinct
from publication and observed delivery. Fixed copy and approved recommendation templates avoid unsupported
prices, deadlines and generated eligibility claims.

The local provider returns the supplied faults for the relevant trigger. A shared per-decision `Budget` bounds
model and logical repository/config operations; failures count. Advice always falls back to deterministic
reasoning or abstention. No hosted model is invoked.

## Real-time replay and recovery

`replay` merges delivery timestamps with deterministic control/live/trigger/line tie breaks. Transport ingests
queued-trigger evidence before publication even while decisions wait for the single worker. Controls apply
only when reached: withdrawal is rechecked at publication, G03 corrections update affected open goals, and
outages/degradation expire at supplied timestamps. Context is read again at publication, including current
settings, consent, availability and the IST-day reservation.

`publisher` writes only simulated actions. Action/decision/trigger uniqueness, durable outbox/checkpoints and
atomic completed-trigger transactions support crash recovery. Exports atomically replace JSONL from SQLite.
Processing and queue time use monotonic elapsed measurements mapped onto replay delivery time; no nominal
fault duration is substituted for measured time. The maximum decision budget is 8 model calls, 20 tool calls,
60 seconds; >60-second and >5-minute decisions are separately reported. Deployment is one replay worker;
multi-worker dispatch/backpressure is not implemented.

## Measurement and learning

`outcomes` validates actual simulator files, identities, counts, purchases, episodes, source-scripted event
versions and personalised exposure links. Duplicate deliveries remain raw, with a canonical first-received
event used for counting. A manifest binds outcomes to source/simulator/action hashes and the actual simulator
coverage contract: replay day plus follow-up days 1 through HORIZON_DAYS, for scripted triggered users only.
The absence of a generated event is bounded non-occurrence only for covered users/windows, never lifetime absence.

Goal judgments use each persisted commitment, configured window, actual rule version and applicable G03
amendment. Viewer identity, receipt time and condition fields must match; publication and model output are
not success signals. A positive signal can succeed before the deadline. Failure requires complete coverage;
censoring, missing rules/conditions and unsupported signals are INCONCLUSIVE. Cancelled goal ownership ends
at the next recorded goal commitment. Goal instance, version, observation window and event references are
stored in `goal_outcomes`; `viewer_learning` records the result without asserting individual causal efficacy.
Terminal judgments close open goals/plans; the original replay lifecycle is retained for idempotent remeasurement.
Simulator events live in separate outcome tables so simulated null app settings do not overwrite replay facts.

`evaluation` keeps all 5,000 randomized users in full-population ITT denominators. Known live-event positives
remain observed; missing follow-up is unknown. It reports identification bounds when point impact is not
identified. Scripted-triggered-cohort ITT compares identical seven-day binary endpoints by assigned arm,
including NO_ACTION viewers. Wilson intervals, Newcombe risk-difference intervals and log-risk-ratio intervals
are standard-library deterministic calculations. Holdout selected-goal assignments are unavailable and are not
invented. The earlier pilot is audited using assignment rather than served status; supplied success labels
are distinguished from independently validated event evidence.

`pipeline` coordinates replay, the unchanged simulator, measurement, integrity checks, input hashes and
reproducible reports. Repeated measurement has a content-derived run identity and durable uniqueness keys.
No outcome simulator file or supplied data/config/pilot file is edited.
