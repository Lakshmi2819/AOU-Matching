---
status: done
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

AoU CDR, 2026-10-22 (R 4.3.3, MatchIt 4.8.1, master node with 2 cores), next
to the BRPMatch ladder on the same subsets (`2026-10-22-brpmatch-realdata-scaling`;
the 100% BRPMatch row is its earlier full-cohort run):

| Subset | Treated / controls | MatchIt time | BRPMatch time | MatchIt matched | BRPMatch matched | MatchIt max \|SMD\| after | BRPMatch max \|SMD\| after |
|---|---|---|---|---|---|---|---|
| 1% | 2,006 / 2,302 | 0 s | 442 s | 96.6% | 56.4% | 0.947 | 0.718 |
| 5% | 10,255 / 11,326 | 5 s | 397 s | 94.2% | 56.6% | 0.886 | 0.576 |
| 10% | 20,568 / 22,670 | 30 s | 419 s | 94.0% | 56.3% | 0.877 | 0.517 |
| 25% | 51,368 / 56,362 | 288 s | 456 s | 93.4% | 55.1% | 0.875 | 0.409 |
| 50% | 102,226 / 112,639 | 1,084 s | 493 s | 93.4% | 54.2% | 0.869 | 0.323 |
| 100% | 204,840 / 225,254 | 4,371 s | 653 s | 93.2% | 52.8% | 0.867 | 0.232 |

## Interpretation
- Same data on both sides: identical treated/control counts at every size
  (person_id mod 100 subsets), same covariates, same settings.
- **Time.** MatchIt is far faster on small cohorts, where BRPMatch's wall
  time is mostly fixed Spark overhead (~400 s floor on this 2-worker cluster).
  MatchIt grows roughly with size squared (about 4x per doubling: 288 ->
  1,084 -> 4,371 s); BRPMatch barely grows (456 -> 493 -> 653 s). They cross
  between 25% and 50% (~50-100k treated); on the full cohort BRPMatch is
  ~6.7x faster.
- **Match rate.** MatchIt matches ~93-97% (its unmatched are treated in exact
  gender strata with fewer controls than treated); BRPMatch ~53-57% at every
  size. The full-cohort diagnostics (brpmatch-realdata-scaling README) show
  this is mostly a common-support limit: ~71.5k of the 96.8k unmatched are
  excess treated in buckets with more treated than controls, the 5-candidate
  limit costs at most ~25k, and only ~13% of the unmatched could be paired 1:1
  with a leftover control in the same coarse cell.
- **Balance.** BRPMatch's matched sample is much better balanced (max |SMD|
  0.72 -> 0.23, improving with size); MatchIt's stays ~0.87-0.95, worst on
  log_conditions: matching almost everyone at ~1:1 forces poor matches.
- Caveats: compute differs (MatchIt is single-threaded R on the 2-vCPU master;
  BRPMatch uses 2 Spark workers), the two may estimate the Mahalanobis
  covariance differently, and the match rates differ so much that balance is
  compared on different samples.
