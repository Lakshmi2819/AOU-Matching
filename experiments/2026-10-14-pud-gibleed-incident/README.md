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

AoU CDR `R2025Q4R6`, run 2026-10-15 01:58 UTC (cohort step ~6 min):
```
[cohort] eligible people (365d observed before index, 365d after, no prior bleed): 369,419
[cohort] new peptic ulcer (exposed): 10,051; never-ulcer controls: 359,368
[match] BRPMatch mahalanobis, 1:1, without replacement; exact on gender_concept_id
[match] exposed matched: 10,051 of 10,051 (0 unmatched)
[balance] race_concept_id_8515: SMD before -0.121, after 0.000
[balance] age_at_index: SMD before 0.284, after -0.000; VR before 0.73, after 1.00
[balance] index_year: SMD before -0.485, after -0.205; VR before 2.08, after 1.51
[balance] log_prior_visits: SMD before 0.361, after -0.000; VR before 1.02, after 1.00
[balance] max |SMD| after matching: 0.205 (above 0.1 - check balance)
[crude] 365-day GI bleed risk: exposed 5.8%, unexposed 1.0%
[matched] 365-day GI bleed risk: exposed 5.8%, matched unexposed 1.1%
[matched] risk difference = 4.75 pp (95% CI 4.25 to 5.24); risk ratio = 5.07
[matched] discordant pairs: exposed-only 576, control-only 99
[matched] McNemar chi-sq = 335.67, p = 5.601e-75
```
(All race/ethnicity/gender categories: |SMD| <= 0.042 before, 0.000 after.)

## Interpretation
- Removing the overlapping codes and requiring the bleed to come after the
  ulcer cut absolute risks sharply (exposed 44.8% ever -> 5.8% within a year).
- The risk ratio rose (5.07) rather than fell. Two likely reasons, to fix
  before trusting the estimate:
  1. **Calendar time is not balanced** (index_year SMD -0.205 after matching).
     New ulcer diagnoses spread across the whole EHR history, while control
     index dates are random visits, mostly recent, so early-year ulcer
     patients have few close controls. Fix: exact matching on calendar period.
  2. **Same-episode coding.** Ulcers are often diagnosed at an endoscopy done
     because of bleeding, so a bleed coded a day or two after the ulcer may be
     the cause of the diagnosis, not a consequence. Fix: a lag, counting bleeds
     from day 31, as a sensitivity analysis.
- Matching itself worked for every other covariate (|SMD| 0.000 after),
  including prior-year visits (SMD 0.36 before).
