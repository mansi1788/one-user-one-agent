# Randomized impact evaluation

Triggered-cohort ITT uses a fixed supplied trigger roster that is generated independently of actions; includes all assigned agent users in that roster, including NO_ACTION. A causal interpretation is conditional on this exogenous-cohort assumption, valid randomization, comparable observation and no interference. It describes this synthetic simulator and seed, not real product impact.

Untriggered randomized users lack complete simulator follow-up: supplied live-event positives are retained, while other outcomes remain unknown, not zero. Full-population ITT rates, relative lift and confidence intervals are not estimable without assumptions. Reported population bounds are worst-case identification bounds, not confidence intervals.

Two exploratory endpoints are reported without multiple-testing adjustment; neither supports a pre-registered confirmatory claim.

## non_trial_purchase_7d

Any observed non-trial purchase_completed in the same fixed seven-day receipt-time window; no selected-goal or served restriction

Window: 2026-09-30T18:30:00+00:00 to 2026-10-07T18:30:00+00:00 (end excluded).

### All randomized users (ITT)

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| agent | 2513 | 864 | 24 | 1649 | not estimable | not estimable |
| holdout | 2487 | 884 | 32 | 1603 | not estimable | not estimable |

Absolute difference: not estimable percentage points. 95% CI: not estimable.
Relative lift: not estimable. 95% CI: not estimable.
Full randomized population point estimate is not estimable with missing outcomes or an empty arm; bounds make no missing-at-random assumption
Worst-case population difference bounds: -64.787 to 65.287 pp; not a confidence interval.

### Scripted triggered cohort (ITT)

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| agent | 863 | 863 | 23 | 0 | 2.665% | 1.782% to 3.967% |
| holdout | 883 | 883 | 31 | 0 | 3.511% | 2.484% to 4.940% |

Absolute difference: -0.846 percentage points. 95% CI: -2.526 to 0.813 pp.
Relative lift: -24.087%. 95% CI: -55.369% to 29.121%.
Comparison follows randomized assignment, including treatment viewers receiving NO_ACTION; inference assumes valid randomization, common ascertainment and no interference
The difference interval includes zero; this run does not demonstrate a difference.

## any_play_7d

Any observed play_started in the same fixed seven-day receipt-time window; no selected-goal or served restriction

Window: 2026-09-30T18:30:00+00:00 to 2026-10-07T18:30:00+00:00 (end excluded).

### All randomized users (ITT)

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| agent | 2513 | 869 | 573 | 1644 | not estimable | not estimable |
| holdout | 2487 | 893 | 573 | 1594 | not estimable | not estimable |

Absolute difference: not estimable percentage points. 95% CI: not estimable.
Relative lift: not estimable. 95% CI: not estimable.
Full randomized population point estimate is not estimable with missing outcomes or an empty arm; bounds make no missing-at-random assumption
Worst-case population difference bounds: -64.332 to 65.181 pp; not a confidence interval.

### Scripted triggered cohort (ITT)

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| agent | 863 | 863 | 567 | 0 | 65.701% | 62.471% to 68.792% |
| holdout | 883 | 883 | 563 | 0 | 63.760% | 60.536% to 66.865% |

Absolute difference: 1.941 percentage points. 95% CI: -2.539 to 6.408 pp.
Relative lift: 3.044%. 95% CI: -3.851% to 10.434%.
Comparison follows randomized assignment, including treatment viewers receiving NO_ACTION; inference assumes valid randomization, common ascertainment and no interference
The difference interval includes zero; this run does not demonstrate a difference.

## Selected-goal impact

No holdout selected-goal assignments, goal commitment times or success definitions are supplied. Agent goal attainment cannot be compared to an invented holdout goal.

## Earlier pilot audit

Serving is a post-assignment choice that can select for activity, eligibility and opportunity to expose. Served versus everyone else mixes unserved treatment and holdout users and breaks randomization; its uplift is not causal.

### Original served comparison (descriptive, biased)

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| served | 217 | 217 | 87 | 0 | 40.092% | 33.799% to 46.730% |
| other | 3674 | 3674 | 649 | 0 | 17.665% | 16.465% to 18.931% |

Absolute difference: 22.427 percentage points. 95% CI: 16.008 to 29.173 pp.
Relative lift: 126.962%. 95% CI: 90.146% to 170.907%.
Descriptive association only: served versus everyone else is not a randomized contrast and cannot identify causal uplift
The interval excludes zero under the stated inference assumptions; this is not evidence beyond that population and observation process.

### Randomized pilot label comparison

| Arm | Assigned/cohort N | Observed N | Successes | Missing | Conversion | 95% Wilson CI |
|---|---:|---:|---:|---:|---:|---|
| treatment | 1912 | 1912 | 349 | 0 | 18.253% | 16.586% to 20.048% |
| holdout | 1979 | 1979 | 387 | 0 | 19.555% | 17.868% to 21.361% |

Absolute difference: -1.302 percentage points. 95% CI: -3.760 to 1.161 pp.
Relative lift: -6.659%. 95% CI: -18.064% to 6.333%.
Comparison follows randomized assignment, including treatment viewers receiving NO_ACTION; inference assumes valid randomization, common ascertainment and no interference
The difference interval includes zero; this run does not demonstrate a difference.

Pilot succeeded fields are supplied labels, not independently verified events. G06 eligibility is underspecified; goal-specific observation coverage and censoring are unavailable. The randomized comparison estimates differences in supplied labels only, conditional on consistent measurement.

Sources: replay/arms.csv, actual simulator outcome_events.jsonl/report/source, actual goal rules and controls, and the three supplied pilot files. Numerical estimates use no model claims or action publication as success evidence.
