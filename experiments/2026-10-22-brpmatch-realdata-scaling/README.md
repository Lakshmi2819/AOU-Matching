---
status: pending
created: 2026-10-22
---

# Experiment 2026-10-22 — brpmatch-realdata-scaling

## Intent
A larger, harder BRPMatch matching task built from **real** AoU data, entirely
in Spark SQL / Spark (no collecting to pandas), as suggested by Shawn O'Neil in
place of building synthetic data on the cluster. No outcome: this measures
matching itself.

- **Cohort** (`cohort.sql`): everyone with an EHR condition record. Treated =
  any hypertension diagnosis (316866 and descendants), a common condition, so
  the treated group is large (the ulcer cohort was ~1:22, which barely
  exercises bucketing). Real covariates: gender (exact), race, ethnicity,
  year of birth, log(1 + visits), log(1 + distinct condition concepts).
- **Scaling knobs**, all deterministic filters `person_id mod 100 < pct`
  (plain arithmetic, so `2026-10-22-matchit-realdata` selects identical
  people): `population_pct` (SQL) shrinks the whole cohort;
  `treated_pct` / `control_pct` per run set size and treated:control ratio;
  `threshold` per run is the rebucket threshold.
- **Per run** (aggregate only): treated/control N and ratio, match rate,
  max |SMD| before -> after with the worst covariate (computed with Spark
  aggregations using brpmatch's own SMD definition; checked against
  `match_summary()` locally), bucket stats (count, patients-per-bucket
  distribution, largest bucket, one-sided buckets, seconds per bucket), and
  match wall time. Participant counts from 1 to 19 are suppressed.

## Run
AoU (after the usual cluster setup and `make install-brpmatch`):
```sh
source .workspace_env
make run-exp SLUG=brpmatch-realdata-scaling
```
The default runs are the size ladder (1-50%) for the MatchIt comparison; the
full-cohort run is already done, and the threshold and ratio sweeps are
commented out in config.yaml. Each full-cohort run matches
every hypertension patient, so it may take much longer than the ulcer
experiments; to start small, keep only the first run or set
`population_pct: 25`.

## Next step: are the unmatched avoidable?
Before deciding on the rematch / caliper work in brpmatch (branch
`rematch-unmatched-treated`, kept as an experiment, no PR), one full-cohort run
at n_neighbors 5 reports, per run, three aggregate diagnostics (participant
counts from 1 to 20 suppressed as "≤20", and hidden whenever another printed
count would reveal them):

1. Best possible 1:1 within the buckets match() formed (sum of
   min(treated, controls)) vs actual matched: how much the k-NN candidate limit
   costs. An upper bound that ignores distance.
2. SMD of unmatched treated vs unused controls, next to the original
   treated-vs-control SMD: do the unmatched resemble the leftover controls?
3. Unmatched treated sharing a coarse cell (gender x 5-year birth band x
   condition-count quintile) with at least one unused control.

Avoidable losses look like: best possible well above actual, small SMD in (2),
and most unmatched sharing a cell in (3). Only then run the commented
n_neighbors 20 / 50 sweep in config.yaml. Local Eunomia check (peptic ulcer as
treatment): at n_neighbors 5, best possible is all but ≤20 of 802 vs 569
matched, but the unmatched differ sharply from the unused controls
(log_conditions SMD 2.70 vs 1.25 overall) and 46.8% share a cell, so locally
the losses look mostly hard to match rather than avoidable.

## Results
### AoU diagnostics, 2026-10-29 (same cohort: 204,840 treated / 225,254 controls)
n_neighbors 5, threshold 10,000 (match wall time 669 s):
```
[run t100% c100% thr10000 k5] treated 204,840, controls 225,254 (1:1.1); matched 52.8% (96,769 unmatched); max |SMD| 1.006 -> 0.231 (year_of_birth); match wall time 669s
[buckets] patients in matched buckets: 429,269 of 430,094 (825 outside); exposed: 204,408 of 204,840 (432 outside)
[diag] best possible within buckets: 133,333 of 204,840 (65.1%); actual matched 108,071 of 204,840 (52.8%); candidate-limit loss 25,262
[diag] unmatched treated 96,769 vs unused controls 117,173: max |SMD| 2.360 (log_conditions); year_of_birth -1.737, log_visits 1.240, log_conditions 2.360 (all treated vs all controls: max |SMD| 1.006)
[diag] unmatched treated sharing a cell (exact group x 5-yr birth band x 5 condition-count quantiles) with >=1 unused control: 78,232 of 96,769 (80.8%)
```
- Exact coverage confirms the earlier estimate: 825 people (432 treated)
  outside the matched buckets.
- Of the 96,769 unmatched, ~25,300 (26%) were lost to the 5-candidate limit
  (an unused control remained in their bucket); ~71,500 (74%) could not be
  matched 1:1 within their buckets at all (more treated than controls there).
- The unmatched treated differ far more from the unused controls (max |SMD|
  2.36: older, more visits, many more conditions) than treated do from controls
  overall (1.006): the leftover controls are mostly younger and healthier.
- 80.8% share a coarse cell with at least one unused control, but that test
  ignores capacity (one control serves one treated) and the cells are wide.
- Reading: mostly legitimately hard to match (lack of common support), with
  at most ~25k potentially recoverable, an upper bound that ignores distance.

### AoU capacity diagnostic, 2026-11-01 (same cohort, n_neighbors 5, threshold 10,000)
Match wall time 545 s; cohort built in 223 s.
```
[run t100% c100% thr10000 k5] treated 204,840, controls 225,254 (1:1.1); matched 52.8% (96,773 unmatched); max |SMD| 1.006 -> 0.231 (year_of_birth); match wall time 545s
[diag] best possible within buckets: 133,333 of 204,840 (65.1%); actual matched 108,067 of 204,840 (52.8%); candidate-limit loss 25,266
[diag] unmatched treated 96,773 vs unused controls 117,194: max |SMD| 2.360 (log_conditions); year_of_birth -1.737, log_visits 1.240, log_conditions 2.360 (all treated vs all controls: max |SMD| 1.006)
[diag] unmatched treated sharing a cell (exact group x 5-yr birth band x 5 condition-count quantiles) with >=1 unused control: 78,236 of 96,773 (80.8%)
[diag] capacity within cells (exact group x 5-yr birth band x 5 condition-count quantiles, whole cohort): 12,884 of the 96,773 unmatched (13.3%); in-bucket candidate-limit loss 25,266
[diag] capacity within cells (exact group x 2-yr birth band x 10 condition-count quantiles, whole cohort): 12,297 of the 96,773 unmatched (12.7%); in-bucket candidate-limit loss 25,266
```
- The k5 results reproduce 2026-10-29 to within a few matches (greedy
  order is not fully deterministic across runs).
- Capacity is far below the 80.8% who share a cell: the unused controls sit
  in different cells (younger, fewer conditions) from the unmatched treated,
  so most cells have many unmatched treated and few leftover controls.
- Only ~12.3-12.9k of the 96.8k unmatched (~13%) could still be paired 1:1
  with a similar leftover control, about half the 25.3k in-bucket
  candidate-limit loss. Finer cells barely lower it (12,884 -> 12,297), so
  this is not an artifact of wide cells.
- Ceiling for any rematch / caliper fix: roughly +6 points of treated
  (52.8% -> ~59%) with reasonably similar controls; the remaining ~84k
  unmatched lack common support with the leftover controls.

Pending: the n_neighbors 20 run. In the 2026-11-01 session `make run-exp`
ended with an error after the k5 diagnostics, before any k20 line printed
(cause not yet known). The first attempt (2026-10-29, second session) crashed
after the k5 summary line, before any diagnostic printed; diagnostics now
print as they are computed and failures are reported without ending the run
(commit 2b56434).

Local Eunomia (synthetic) smoke test, 2026-10-22, with treatment swapped to
peptic ulcer (4027663; Eunomia has no hypertension codes), ~30% treated:
```
[run t100% c100% thr10000] treated 802, controls 1,892 (1:2.4); matched 70.9% (233 unmatched); max |SMD| 1.254 -> 0.361 (year_of_birth)
[run t100% c100% thr1000]  ... 29 buckets; matched 70.4%
[run t100% c100% thr300]   ... 58 buckets; matched 69.2%
[run t25% c100% thr10000]  treated 161 (1:11.8); matched all but <20
[run t5% c100% thr10000]   treated 22 (1:86.0); matched 100.0%
```
(Max |SMD| above is from the first version of the SMD code; with brpmatch's
definition year_of_birth after matching is 0.341, identical to
`match_summary()`.)

Local Eunomia n_neighbors comparison (same peptic ulcer cohort, 802 treated /
1,892 controls, threshold 10,000, Mahalanobis, 1:1 without replacement;
synthetic data). More candidates per treated raise the match rate and worsen
balance:

| n_neighbors | Matched | Max \|SMD\| after (year_of_birth) |
|---|---|---|
| 1 | 51.2% | 0.213 |
| 5 | 70.9% | 0.342 |
| 20 | 85.0% | 0.426 |

Already visible locally: with ~30% treated, about 30% of treated go unmatched
and balance degrades (log_conditions SMD 1.25 before, so the matcher trades
year-of-birth balance for it), while at 1:12 and 1:86 nearly everyone
matches. Lowering the rebucket threshold multiplies buckets (5 -> 29 -> 58)
with little change in match rate.

AoU CDR, 2026-10-22, full cohort, threshold 10,000, n_neighbors 5:
```
[run t100% c100% thr10000] treated 204,840, controls 225,254 (1:1.1); matched 52.8% (96,766 unmatched); max |SMD| 1.006 -> 0.232 (year_of_birth); match wall time 653s
[buckets] 589 buckets; patients per bucket: min <20, p5 <20, p25 50, median 223, p75 705, p95 3,636, max 9,875, mean 729
[buckets] max exposed in any bucket 5,546; max controls in any bucket 8,015 (not necessarily the same bucket)
[buckets] seconds per bucket: total 211.5, mean 0.36, median 0.06, p95 1.60, max 19.30
```
The run printed two lines that are corrected here: the max-group line was
labelled "largest bucket: exposed 5,546, controls 8,015", but the two maxima
can come from different buckets (5,546 + 8,015 > 9,875); and "one-sided
buckets: 0" is always 0, because match() drops one-sided buckets and
bucket_stats only holds buckets with matches. 589 x 729 ~ 429k of 430,094, so
a few hundred to ~1k people were outside the matched buckets. Both are fixed
in brpmatch_report.py; later runs report exact coverage.

AoU size ladder, 2026-10-22 (threshold 10,000, n_neighbors 5), next to
MatchIt on the identical subsets (`2026-10-22-matchit-realdata`):

| Subset | Treated / controls | MatchIt time | BRPMatch time | MatchIt matched | BRPMatch matched | MatchIt max \|SMD\| after | BRPMatch max \|SMD\| after |
|---|---|---|---|---|---|---|---|
| 1% | 2,006 / 2,302 | 0 s | 442 s | 96.6% | 56.4% | 0.947 | 0.718 |
| 5% | 10,255 / 11,326 | 5 s | 397 s | 94.2% | 56.6% | 0.886 | 0.576 |
| 10% | 20,568 / 22,670 | 30 s | 419 s | 94.0% | 56.3% | 0.877 | 0.517 |
| 25% | 51,368 / 56,362 | 288 s | 456 s | 93.4% | 55.1% | 0.875 | 0.409 |
| 50% | 102,226 / 112,639 | 1,084 s | 493 s | 93.4% | 54.2% | 0.869 | 0.323 |
| 100% | 204,840 / 225,254 | 4,371 s | 653 s | 93.2% | 52.8% | 0.867 | 0.232 |

Bucket coverage on the ladder (exact, from the fixed report): people outside
the matched buckets were <20 at 1% and 5%, then 138, 177 and 178 at 10%, 25%
and 50% (under 0.2%). Per-bucket k-NN time summed over buckets: 1.0, 7.6,
16.7, 53.3, 108.9, 211.5 s. One worker was killed for memory (exit 137) during
the ladder run; Spark recovered.

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
