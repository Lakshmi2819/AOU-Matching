---
status: pending
created: 2026-10-14
---

# Experiment 2026-10-14 — pud-gibleed-incident

## Intent
Does a **new** peptic ulcer diagnosis raise the **1-year** risk of a GI bleed,
compared with BRPMatch-matched people who never had an ulcer?

This fixes the two problems that inflated the earlier estimates
(`2026-10-07-pud-gibleed-matched`, RR 4.69; `2026-10-12-pud-gibleed-brpmatch`,
RR ~3.0):

1. **Concept overlap.** Exposure uses only ulcer codes that do not also mean a
   bleed ("gastric ulcer with hemorrhage" and similar are excluded); controls
   have no ulcer code of any kind.
2. **Time order.** Everyone has an index date: the first ulcer-only diagnosis
   for exposed people, and one visit chosen by a fixed hash (deterministic
   pseudo-random) for controls. Outcome = any GI hemorrhage code (192671 and
   descendants) in the 365 days **after** index. Anyone with a GI bleed on or
   before index is excluded.

Everyone needs 365 days of observation before index (so the ulcer is new and
prior visits are measured over the same window) and 365 days after (so a bleed
would be recorded). Windows are `sql_params` in config.yaml.

Matching (BRPMatch, Mahalanobis, 1:1 without replacement): exact on gender;
distance on age at index, index year, log(1 + visits in the prior 365 days),
race, ethnicity. All covariates are measured at index.

Output is aggregate only, with the same small-cell rules as the earlier
BRPMatch experiment.

## Run
Laptop: `source .venv/bin/activate; export JAVA_HOME=/opt/homebrew/opt/openjdk@17;
make run-exp SLUG=pud-gibleed-incident`

AoU (after the usual cluster setup and `make install-brpmatch`):
```sh
source .workspace_env
make run-exp SLUG=pud-gibleed-incident
```
This reads `observation_period` and builds index dates over all visits, so the
cohort step takes longer than the earlier experiments.

## Results
Local Eunomia (synthetic), 2026-10-14: the pipeline runs end to end, but the
synthetic data cannot test the outcome. Every GI bleed after an ulcer in
Eunomia happens more than a year later, so the 365-day risk is 0% in both
groups; only 302 controls qualify (few visits), so 93 of 802 exposed matched.
With a 10-year outcome window as a local test, events appear and the
small-cell suppression engages as expected.

AoU: <paste the scrubbed runs/summary.md here>

## Interpretation
<what you concluded; safe aggregate numbers only>
