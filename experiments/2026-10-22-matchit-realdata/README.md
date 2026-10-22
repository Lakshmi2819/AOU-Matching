---
status: pending
created: 2026-10-22
---

# Experiment 2026-10-22 — matchit-realdata

## Intent
Shawn asked whether the BRPMatch real-data test can be repeated with MatchIt on
the same data. This runs R's MatchIt on exactly the cohort of
`2026-10-22-brpmatch-realdata-scaling`:

- Same people and covariates: the same cohort SQL logic (here in plain SQL for
  BigQuery/DuckDB via `pick_connection()`), the same rare-category merging,
  and the same subsets, `person_id mod 100 < pct` in each group. The BRPMatch
  side was switched from a hash to this rule so both select identical people
  (checked locally: identical treated/control counts at every size).
- Same settings: nearest-neighbour, Mahalanobis, 1:1 without replacement,
  exact on gender; covariates race, ethnicity, birth year, log visits, log
  distinct conditions.
- Same balance metric: max |SMD| with brpmatch's `compute_smd()` definition.

MatchIt is single-machine (in AoU, the master node) and its greedy
nearest-neighbour search compares each treated person with every remaining
control in the same exact-match group, so time grows with treated x controls.
The runs climb a size ladder (1%, 5%, 10%, 25%, 50%, 100%); before each run
the time is projected from the previous one, and runs projected over
`max_minutes_per_run` (120) are skipped rather than started.

Known differences to note when comparing:
- MatchIt matches every treated person it can against all remaining controls;
  BRPMatch only considers `n_neighbors` (5) candidates within an LSH bucket and
  leaves the rest unmatched. Expect MatchIt: higher match rate, worse balance.
- MatchIt's Mahalanobis distance and BRPMatch's whitening may use different
  covariance estimates.

## Run
AoU (MatchIt is installed by the R setup step):
```sh
Rscript framework/scripts/ensure_r_packages.R   # once per cluster; or make setup-workspace
source .workspace_env
make run-exp SLUG=matchit-realdata
```
Then the matching BRPMatch ladder:
```sh
make run-exp SLUG=brpmatch-realdata-scaling
```

## Results
Local Eunomia (synthetic) smoke test, 2026-10-22, treatment swapped to peptic
ulcer (4027663):
```
[run t25% c25%]  treated 194, controls 460 (1:2.4); matched 100.0%; max |SMD| 1.274 -> 0.675 (log_conditions); 0s
[run t50% c50%]  treated 409, controls 943 (1:2.3); matched 100.0%; max |SMD| 1.228 -> 0.613 (log_conditions); 0s
[run t100% c100%] treated 802, controls 1,892 (1:2.4); matched 100.0%; max |SMD| 1.254 -> 0.599 (log_conditions); 0s
```
BRPMatch on the same subsets: 25% matched 81.4% (max |SMD| 0.492), 50% matched
77.0% (0.476).

AoU: <paste the scrubbed runs/summary.md here>

## Interpretation
<what you concluded; safe aggregate numbers only>
