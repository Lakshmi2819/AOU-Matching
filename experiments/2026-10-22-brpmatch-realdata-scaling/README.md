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

## Results
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

## Interpretation
<what you concluded; safe aggregate numbers only>
