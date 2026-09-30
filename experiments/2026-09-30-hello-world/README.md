---
status: pending
created: 2026-09-30
---

# Experiment 2026-09-30 — hello-world

## Intent
Confirm that the experiment runner can launch an analysis script in local or
Verily Workbench without a dataset, CDR, or workspace environment file.

## Run
From the repository root, run:

```sh
make run-exp SLUG=hello-world
```

The entrypoint prints a greeting into `runs/summary.md`. It does not connect to
BigQuery or open any local data.

## Results
<after running, note the result from `runs/summary.md`>

## Interpretation
<confirm that the runner launched the entrypoint successfully>
