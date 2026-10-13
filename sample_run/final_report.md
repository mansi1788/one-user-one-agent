# Final submission run

Simulator seed: oua-practice. 31433 actual simulator events for 1746 triggered users.
719 accepted home pages; 501 personalised page-show events (not unique viewers); 0 simulator policy problems.
Replay: 2769 trigger deliveries, 2679 unique, 90 duplicates; 719 local actions; 0 holdout actions.
Goal judgments: 759 instances for 756 viewers. Counts: {"FAILED": 639, "SUCCEEDED": 120}.
Goal attainment is observed within viewer-specific committed windows. Success does not establish that a page caused the event. Holdout users without a goal have no fabricated outcome judgments.

## Measurement by goal

| Goal | SUCCEEDED | FAILED | INCONCLUSIVE |
|---|---:|---:|---:|
| G03 | 2 | 48 | 0 |
| G05 | 17 | 365 | 0 |
| G08 | 101 | 226 | 0 |

## Impact

No holdout selected-goal assignments, goal commitment times or success definitions are supplied. Agent goal attainment cannot be compared to an invented holdout goal.

Untriggered randomized users lack complete simulator follow-up: supplied live-event positives are retained, while other outcomes remain unknown, not zero. Full-population ITT rates, relative lift and confidence intervals are not estimable without assumptions. Reported population bounds are worst-case identification bounds, not confidence intervals.

### non_trial_purchase_7d: randomized triggered cohort

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| agent | 863 | 863 | 23 | 0 | 2.665% | 1.782% to 3.967% |
| holdout | 883 | 883 | 31 | 0 | 3.511% | 2.484% to 4.940% |

Absolute difference: -0.846 percentage points. 95% CI: -2.526 to 0.813 pp.
Relative lift: -24.087%. 95% CI: -55.369% to 29.121%.
Comparison follows randomized assignment, including treatment viewers receiving NO_ACTION; inference assumes valid randomization, common ascertainment and no interference
The difference interval includes zero; this run does not demonstrate a difference.

### any_play_7d: randomized triggered cohort

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| agent | 863 | 863 | 567 | 0 | 65.701% | 62.471% to 68.792% |
| holdout | 883 | 883 | 563 | 0 | 63.760% | 60.536% to 66.865% |

Absolute difference: 1.941 percentage points. 95% CI: -2.539 to 6.408 pp.
Relative lift: 3.044%. 95% CI: -3.851% to 10.434%.
Comparison follows randomized assignment, including treatment viewers receiving NO_ACTION; inference assumes valid randomization, common ascertainment and no interference
The difference interval includes zero; this run does not demonstrate a difference.

## Reliability and limits

Publication latency seconds: {"max": 44.861499, "p50": 0.188227, "p95": 0.367315, "p99": 0.560551}. Decisions >60 s: 0; >5 min: 0. Recorded replay failures: {"TimeoutError": 16}.
G06/G10/G11 remain disabled; G07 outcome needs an authoritative unfinished-series identity and is unsupported. Unknown historical rule versions and incomplete windows are inconclusive. G03 uses the supplied correction for affected open goals. Source events are stored separately so nullable simulator app settings cannot overwrite replay facts.
Mock timeouts are emulated without a 45-second sleep; store degradation uses conservative bounded reads. Local simulator results do not establish real-world product lift. See KNOWN_LIMITATIONS.md and impact_report.md.

## Reproduction

`python -m one_agent.cli pipeline --pack . --db sample_run/replay.sqlite3 --out sample_run` runs replay recovery, the supplied simulator, validation, outcomes and reports locally. `pytest -q` runs automated verification. The stored source manifest and phase5_pipeline_validation.json provide content hashes and invariants.
