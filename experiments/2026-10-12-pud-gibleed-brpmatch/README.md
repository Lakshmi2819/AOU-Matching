---
status: done
created: 2026-10-12
---

# Experiment 2026-10-12 — pud-gibleed-brpmatch

## Intent
Repeat the peptic ulcer -> GI bleed comparison from
`2026-10-07-pud-gibleed-matched` with **BRPMatch** (nearest-neighbour matching
on Spark via bucketed random projection) instead of exact matching, and with a
richer covariate set:

- exact: gender
- distance (Mahalanobis): year of birth, log(1 + visit count), race, ethnicity

Visit count is new and matters: people who are seen more often get more
diagnoses recorded, so without it the comparison mixes "has an ulcer" with
"uses more healthcare". Exposure and outcome definitions are unchanged (same
concept overlap caveat as the earlier experiment), so the difference between
the two results comes from the matching method and covariates.

Output (aggregate only): cohort sizes, match rate, per-covariate SMD and
variance ratio before/after, a love plot (`runs/love_plot.png`, one point per
covariate), crude and matched GI bleed risk, paired risk difference with 95%
CI, risk ratio, McNemar test. Counts from 1 to 19 are suppressed and
categories with fewer than 20 people in either group are merged into "other".

## Run
Laptop (once: `brew install openjdk@17` and `make install-spark`):
```sh
source .venv/bin/activate
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
make run-exp SLUG=pud-gibleed-brpmatch
```

AoU Workbench (Dataproc cluster; once per new cluster, after the usual setup):
```sh
make install-brpmatch
python -c "import pyspark, sklearn, scipy, pyarrow; print(pyspark.__version__)"
source .workspace_env
make run-exp SLUG=pud-gibleed-brpmatch
```
The check line must print a pyspark version >= 3.5 with no import error.

The cohort is built in Spark SQL: in AoU the executors read the CDR tables
(`cdr_tables` in config.yaml) through the Spark BigQuery connector, so no
row-level data passes through the master node, which is small (7 GB, most of
it used by cluster services) and ran out of memory when the cohort was
loaded through pandas. Reading `condition_occurrence` takes a few minutes.

## Results
Local Eunomia (synthetic) run, 2026-10-12:
```
[match] exposed matched: 745 of 802 (57 unmatched)
[balance] log_visits: SMD before 0.330, after 0.000; VR before 1.22, after 1.00
[balance] max |SMD| after matching: 0.004 (OK)
[crude] GI bleed risk: exposed 33.2%, unexposed 11.3%
[matched] GI bleed risk: exposed 30.3%, matched unexposed 17.2%
[matched] risk difference = 13.15 pp (95% CI 10.09 to 16.21); risk ratio = 1.77
```
AoU CDR `R2025Q4R6`, run 2026-10-14 (exit 0). The `[match] exposed matched`
line is shown in its corrected form: the original run printed the matched
count next to the total, from which the small unmatched count could be
derived; the script was fixed the same day.
```
[cohort] gender_concept_id: 3 categories kept, 1 merged into 'other'
[cohort] race_concept_id: 9 categories kept, 0 merged into 'other'
[cohort] ethnicity_concept_id: 5 categories kept, 1 merged into 'other'
[cohort] people with EHR conditions: 430,094
[cohort] peptic ulcer (exposed): 18,169; unexposed: 411,925
[match] BRPMatch mahalanobis, 1:1, without replacement; exact on gender_concept_id
[match] exposed matched: all but <20 of 18,169
[balance] race_concept_id_8515: SMD before -0.103, after -0.000
[balance] gender_concept_id_45878463: SMD before -0.046, after 0.000
[balance] gender_concept_id_45880669: SMD before 0.052, after -0.000
[balance] year_of_birth: SMD before -0.496, after -0.005; VR before 0.70, after 1.02
[balance] log_visits: SMD before 0.690, after 0.000; VR before 0.98, after 1.00
[balance] max |SMD| after matching: 0.005 (OK)
[crude] GI bleed risk: exposed 44.8%, unexposed 8.8%
[matched] GI bleed risk: exposed 44.8%, matched unexposed 15.0%
[matched] risk difference = 29.69 pp (95% CI 28.82 to 30.56); risk ratio = 2.99
[matched] discordant pairs: exposed-only 6,739, control-only 1,349
[matched] McNemar chi-sq = 3590.67, p = 0
```
(All other race/ethnicity/gender categories: |SMD| <= 0.031 before, 0.000 after.)

## Interpretation
Comparison with exact matching on the same cohort (`2026-10-07-pud-gibleed-matched`):

| | Exact (gender + 5-yr birth band) | BRPMatch (+ race, ethnicity, visits) |
|---|---|---|
| Matched control GI bleed risk | 9.6% | 15.0% |
| Risk difference | 35.3 pp (34.4 to 36.1) | 29.7 pp (28.8 to 30.6) |
| Risk ratio | 4.69 | 2.99 |

- BRPMatch scales to the full AoU cohort on the Workbench Dataproc cluster
  (cohort build ~3 min via the BigQuery connector) and matched almost every
  exposed person while balancing every covariate (max |SMD| 0.005).
- Healthcare utilization is the main confounder found. People with a peptic
  ulcer had far more visits (log-visits SMD 0.69, the largest imbalance;
  larger than age at 0.50). Matching on it raised the control GI bleed risk
  from 9.6% to 15.0% and cut the risk ratio from 4.7 to 3.0: people who are
  seen more often get more diagnoses recorded, GI bleeds included.
- The association remains strong after matching, as expected clinically.
- Still overstated: the exposure/outcome concept overlap (e.g. "gastric ulcer
  with hemorrhage" counts as both) is unchanged, and flags are ever/never
  with no time ordering. Fixing those is the next step before reading the
  size of the effect.
- "p = 0" is floating-point underflow; read it as p < 1e-300.
