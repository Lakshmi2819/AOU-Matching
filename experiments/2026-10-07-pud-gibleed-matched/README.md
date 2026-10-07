---
status: done
created: 2026-10-07
---

# Experiment 2026-10-07 — pud-gibleed-matched

## Intent
A practice matched comparison to exercise the full workflow before a real
question. Among people with any recorded condition, is a GI bleed (192671 and
descendants) more common in people with a peptic ulcer (4027663 and
descendants) than in people without one, after 1:1 exact matching on gender and
5-year birth-year band?

Basic questions the output answers:
1. How many people are in the cohort, and how many are exposed?
2. How different are the groups in birth year and gender before matching (SMD)?
3. How many matched pairs were formed, and is balance good after matching?
4. What is the GI bleed risk in each group, crude and matched, and the paired
   risk difference, risk ratio and McNemar p-value?

Limitations: ever/never flags with no time ordering, and gender identity
rather than sex at birth. This is an association, not a causal estimate. Counts
from 1 to 19 are suppressed (`min_cell` in config.yaml).

## Run
```sh
make run-exp SLUG=pud-gibleed-matched
```

## Results
AoU CDR `R2025Q4R6`, run 2026-10-07 21:34 UTC (exit 0), scrubbed summary.md:

```
[cohort] people with EHR conditions: 430,094
[cohort] peptic ulcer (exposed): 18,169; unexposed: 411,925
[cohort] mean year_of_birth: exposed 1960.6, unexposed 1968.2
[match] before matching balance: SMD(year_of_birth) = -0.496, SMD(most-common gender) = -0.046
[match] 1:1 exact on gender + 5-year birth band: 18,169 pairs; 0 exposed unmatched
[match] after matching balance: SMD(year_of_birth) = -0.004, SMD(most-common gender) = 0.000
[crude] GI bleed risk: exposed 44.8%, unexposed 8.8%
[matched] GI bleed risk: exposed 44.8%, matched unexposed 9.6%
[matched] discordant pairs: exposed-only 7,335, control-only 926
[matched] risk difference = 35.27 pp (95% CI 34.44 to 36.11); risk ratio = 4.69
[matched] McNemar chi-sq = 4970.64, p = 0
```

For comparison, the local Eunomia (synthetic) run: 802 pairs, risk 33.2% vs
11.6%, risk difference 21.57 pp (95% CI 17.53 to 25.61), risk ratio 2.86.

## Interpretation
- The pipeline works end to end on the real CDR: query, matching, aggregate
  output, scrubbing.
- Matching did its job. People with a peptic ulcer were about 8 years older
  (birth-year SMD -0.50, well above the usual 0.1 threshold); after exact
  matching both SMDs are below 0.01. Every exposed person found a match.
- Matching on age moved control risk from 8.8% to 9.6% (older people bleed
  more), so the crude estimate was slightly inflated by age.
- The effect (risk ratio 4.7) is almost certainly overstated. In the full OMOP
  vocabulary, codes such as "gastric ulcer with hemorrhage" are descendants of
  both peptic ulcer (4027663) and GI hemorrhage (192671), so one diagnosis can
  make a person both exposed and an outcome. Eunomia's pruned vocabulary has no
  such overlap, which is why it did not show up locally. A follow-up should
  exclude shared concepts from the outcome and add time ordering.
- "p = 0" is floating-point underflow; read it as p < 1e-300.
