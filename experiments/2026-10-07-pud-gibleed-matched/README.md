---
status: pending
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
<after running, paste the scrubbed contents of runs/summary.md here>

## Interpretation
<what you concluded; safe aggregate numbers only>
