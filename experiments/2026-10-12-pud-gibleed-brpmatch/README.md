---
status: pending
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
python -c "import pyspark, sklearn, scipy, pyarrow, google.cloud.bigquery, db_dtypes; print(pyspark.__version__)"
source .workspace_env
make run-exp SLUG=pud-gibleed-brpmatch
```
The check line must print a pyspark version >= 3.5 with no import error.

## Results
Local Eunomia (synthetic) run, 2026-10-12:
```
[match] exposed matched: 745 of 802 (57 unmatched); controls used: 745
[balance] log_visits: SMD before 0.330, after 0.000; VR before 1.22, after 1.00
[balance] max |SMD| after matching: 0.004 (OK)
[crude] GI bleed risk: exposed 33.2%, unexposed 11.3%
[matched] GI bleed risk: exposed 30.3%, matched unexposed 17.2%
[matched] risk difference = 13.15 pp (95% CI 10.09 to 16.21); risk ratio = 1.77
```
AoU: <paste the scrubbed runs/summary.md here>

## Interpretation
<what you concluded; safe aggregate numbers only>
