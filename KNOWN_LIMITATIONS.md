# Known limitations

* G06's recent-lapse eligibility and G10's meaningful-engagement definition are incomplete; G11's TV signal
  is absent. They remain disabled and their outcomes unsupported. G07 requires an authoritative unfinished
  series identity/lifetime completion context not established by this pack; no success is inferred.
* Only triggered users receive complete simulator follow-up. All randomized users remain in ITT denominators,
  but full-population point impact, relative lift and confidence intervals are not estimable without missingness
  assumptions. Selected-goal causal impact is not identifiable because holdout goal assignments/windows are absent.
* Triggered-cohort estimates depend on the supplied fixed trigger roster being independent of treatment, valid
  randomization, common ascertainment and no interference. They are exploratory, use one synthetic seed, have no
  multiplicity adjustment, and do not establish real product benefit. Individual attainment does not establish
  individual causal attribution. Pilot supplied success labels cannot be independently revalidated from raw pilot
  outcome evidence; G06 and goal-specific follow-up limitations apply to that audit.
* Negative judgments assume the supplied simulator completely represents its declared bounded generated-user
  horizon; event-file minimum/maximum timestamps alone would not prove coverage. No coverage is imputed to other
  users. Unknown rules, incomplete windows, cancellations without full ownership and missing condition fields
  produce INCONCLUSIVE. Historical rule versions beyond the supplied version plus recorded corrections are unsupported.
* The default planner prefers home pages and can propose a language-mismatching catalogue variant; the independent
  verifier rejects it. Stale-positive consent conservatism blocks many outbound proposals. WhatsApp supports the
  substantiated recommendation template; unsupported episode/trial copy is blocked. In-app body conventions are
  internal because the source does not give an exact message-body schema.
* Model timeouts are emulated immediately rather than sleeping 45 seconds. Degraded store reads fail at a bounded
  client deadline; they do not reproduce an exact stochastic 20% server-timeout/8-second p95 distribution. Reported
  times are actual local measurements. Single-worker local SQLite replay is not a production multi-worker service.
* Only local simulated publication is implemented. Future schedules represent simulator intent, not a real durable
  notification delivery service. Reservations are conservative. No external notifications or real user actions occur.
* Learning records observed attainment, source evidence and uncertainty. It does not automatically retrain policy or
  claim intervention efficacy. Outcome events remain separate from replay settings/facts; automatically reconciling
  them into a future live decision stream is unfinished. Closure of measured goals is durable, but automatic next-goal
  execution after outcome arrival is outside this submission's offline measurement pipeline.
* Fresh replays measure new elapsed times and therefore need not have identical action timestamps/hashes. Reruns of
  the same completed database and fixed simulator seed are reproducible and idempotent. Run IDs preserve distinct
  simulator/action inputs; old judgments are retained rather than overwritten. Re-measurement at an earlier as-of
  point does not roll back already observed terminal viewer state.
* Earlier phase notes and development replay databases are historical artifacts. The final submission uses
  sample_run/replay.sqlite3 and the current sample_run reports. DATA_PACK_README.md preserves the original README;
  supplied data/config/replay/pilot files and simulator are unchanged.
