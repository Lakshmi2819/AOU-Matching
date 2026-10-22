#!/usr/bin/env python
"""New-user design: 1-year GI bleed risk after a new peptic ulcer diagnosis,
BRPMatch-matched against people with no ulcer (see cohort.sql for the design).

  1. Cohort: Spark SQL over the CDR tables (BigQuery connector in AoU,
     Eunomia copied from DuckDB locally).
  2. Matching: BRPMatch nearest-neighbour matching (LSH buckets + k-NN) on the
     covariates in config.yaml, exact on gender.
  3. Balance: SMD / variance ratio before and after, plus a love plot.
  4. Outcome: 1-year GI bleed risk in each matched group, paired risk difference,
     risk ratio, McNemar test (1:1 only); crude risks for comparison.

Row-level data stays in Spark; only aggregates are printed. Any count
from 1 to min_cell-1 is shown as "<min_cell" (AoU small-cell rule).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: write the love plot to a file

import brpmatch  # noqa: E402
import numpy as np  # noqa: E402
import pyspark.sql.functions as F  # noqa: E402
import yaml  # noqa: E402
from brpmatch import generate_features, match, match_summary  # noqa: E402
from scipy.stats import chi2  # noqa: E402

from utilities.brpmatch_report import collect_bucket_stats, format_bucket_stats  # noqa: E402
from utilities.spark import get_spark, load_cohort, ship_package  # noqa: E402

# Line-buffer so output order matches what happened (stdout is a pipe under the runner).
sys.stdout.reconfigure(line_buffering=True)

ap = argparse.ArgumentParser()
ap.add_argument("--config", required=True)
cfg = yaml.safe_load(Path(ap.parse_args().config).read_text())
min_cell = cfg.get("min_cell", 20)
exact_cols = cfg.get("exact_match_cols", [])
num_cols = cfg.get("numeric_cols", [])
cat_cols = cfg.get("categorical_cols", [])
ratio_k = cfg.get("ratio_k", 1)
sql_params = cfg.get("sql_params", {})
win = f"{sql_params.get('outcome_days', 365)}-day"
out_dir = Path(cfg.get("out_dir", "experiments/2026-10-14-pud-gibleed-incident/runs"))
out_dir.mkdir(parents=True, exist_ok=True)


def small(n) -> bool:
    return 0 < n < min_cell


def fmt_n(n) -> str:
    return f"<{min_cell}" if small(n) else f"{int(n):,}"


def fmt_pct(k, n) -> str:
    """A proportion is shown only if both its numerator and complement are safe."""
    if small(k) or small(n - k):
        return "suppressed"
    return f"{100 * k / n:.1f}%"


# --- 1. cohort -----------------------------------------------------------------
# Spark only: in AoU the executors read the CDR tables from BigQuery, so no
# row-level data passes through the small master node (7 GB, mostly used by
# cluster services).
spark = get_spark("pud-gibleed-incident")
ship_package(spark, brpmatch)  # executors run brpmatch code in applyInPandas
df = load_cohort(spark, Path(cfg["sql_file"]).read_text(), cfg["cdr_tables"],
                 params=sql_params)
df = df.select(
    F.col("person_id").cast("long"),
    F.col("exposed").cast("int"),
    F.col("outcome").cast("int"),
    *[F.col(c).cast("double") for c in num_cols],
    *[F.col(c).cast("string") for c in exact_cols + cat_cols],
)

# Merge categories too small to show safely (in either group) into "other".
for c in exact_cols + cat_cols:
    counts = df.groupBy(c).agg(F.sum("exposed").alias("e"),
                               F.sum(1 - F.col("exposed")).alias("u")).collect()
    rare = [r[c] for r in counts if min(r["e"], r["u"]) < min_cell and r[c] is not None]
    if rare:
        df = df.withColumn(c, F.when(F.col(c).isin(rare), F.lit("other")).otherwise(F.col(c)))
    print(f"[cohort] {c}: {len(counts) - len(rare)} categories kept, "
          f"{len(rare)} merged into 'other'")

# Sort so seeded matching is reproducible; cache on the executors.
df = df.orderBy("person_id").cache()
tot = df.agg(
    F.count("*").alias("n"),
    F.sum("exposed").alias("n_exp"),
    F.sum(F.col("exposed") * F.col("outcome")).alias("crude_e"),
    F.sum((1 - F.col("exposed")) * F.col("outcome")).alias("crude_u"),
).collect()[0]
n_exp, n_unexp = tot["n_exp"], tot["n"] - tot["n_exp"]
crude_e, crude_u = tot["crude_e"], tot["crude_u"]
print(f"[cohort] eligible people ({sql_params.get('washout_days', 365)}d observed before index, "
      f"{sql_params.get('outcome_days', 365)}d after, no prior bleed): {fmt_n(tot['n'])}")
print(f"[cohort] new peptic ulcer (exposed): {fmt_n(n_exp)}; never-ulcer controls: {fmt_n(n_unexp)}")

# --- 2. matching ---------------------------------------------------------------
features_df = generate_features(
    spark, df,
    id_col="person_id", treatment_col="exposed", treatment_value="1",
    categorical_cols=cat_cols or None, numeric_cols=num_cols or None,
    exact_match_cols=exact_cols or None,
).cache()
rebucket = cfg.get("rebucket_threshold", 10000)
t0 = time.perf_counter()
units, pairs, bucket_stats = match(
    features_df,
    feature_space=cfg.get("feature_space", "mahalanobis"),
    ratio_k=ratio_k,
    with_replacement=cfg.get("with_replacement", False),
    num_patients_trigger_rebucket=rebucket,
    seed=cfg.get("seed", 42),
    verbose=False,  # its per-bucket printout can include small counts
)
units = units.cache()

u = units.groupBy("is_treated").agg(
    F.count("*").alias("n"), F.sum(F.when(F.col("weight") > 0, 1).otherwise(0)).alias("matched"),
).collect()
match_secs = time.perf_counter() - t0
u = {r["is_treated"]: r for r in u}
n_t_matched, n_c_matched = u[True]["matched"], u[False]["matched"]
print(f"[match] BRPMatch {cfg.get('feature_space', 'mahalanobis')}, 1:{ratio_k}, "
      f"{'with' if cfg.get('with_replacement') else 'without'} replacement; "
      f"exact on {', '.join(exact_cols) or 'nothing'}; rebucket threshold {rebucket:,}")
print(f"[match] wall time (bucketing + matching): {match_secs:.0f}s")
# Don't print a total alongside a matched count whose difference is a small cell:
# "N - k of N (<20 unmatched)" lets anyone subtract and recover k.
n_unmatched = u[True]["n"] - n_t_matched
if small(n_unmatched):
    print(f"[match] exposed matched: all but <{min_cell} of {fmt_n(u[True]['n'])}")
else:
    print(f"[match] exposed matched: {fmt_n(n_t_matched)} of {fmt_n(u[True]['n'])} "
          f"({fmt_n(n_unmatched)} unmatched)")
# For 1:1 without replacement, controls used ~= exposed matched, so printing it
# would leak the same difference; it is only informative for k:1 / replacement.
if ratio_k > 1 or cfg.get("with_replacement"):
    print(f"[match] controls used: {fmt_n(n_c_matched)}")
for line in format_bucket_stats(collect_bucket_stats(bucket_stats), min_cell,
                                n_total=u[True]["n"] + u[False]["n"], n_treated=u[True]["n"]):
    print(line)

# --- 3. balance ----------------------------------------------------------------
balance, _, fig = match_summary(features_df, units,
                                sample_frac=cfg.get("balance_sample_frac", 1.0))
for _, r in balance.iterrows():
    vr = ""
    if not np.isnan(r.get("vr_unadjusted", np.nan)):
        vr = f"; VR before {r['vr_unadjusted']:.2f}, after {r['vr_adjusted']:.2f}"
    print(f"[balance] {r['display_name']}: SMD before {r['smd_unadjusted']:.3f}, "
          f"after {r['smd_adjusted']:.3f}{vr}")
max_smd = balance["smd_adjusted"].abs().max()
print(f"[balance] max |SMD| after matching: {max_smd:.3f} "
      f"({'OK' if max_smd < 0.1 else 'above 0.1 - check balance'})")
fig.savefig(out_dir / "love_plot.png", dpi=120, bbox_inches="tight")
print(f"[balance] wrote aggregate love plot to {out_dir / 'love_plot.png'}")

# --- 4. outcome ----------------------------------------------------------------
print(f"[crude] {win} GI bleed risk: exposed {fmt_pct(crude_e, n_exp)}, "
      f"unexposed {fmt_pct(crude_u, n_unexp)}")

y = df.select(F.col("person_id").cast("string").alias("id"), "outcome")
arms = (units.filter(F.col("weight") > 0).join(y, "id")
        .groupBy("is_treated")
        .agg(F.count("*").alias("n"), F.sum("outcome").alias("events"),
             F.sum("weight").alias("w"), F.sum(F.col("weight") * F.col("outcome")).alias("wy"))
        .collect())
arms = {r["is_treated"]: r for r in arms}
risk_t = arms[True]["wy"] / arms[True]["w"]
risk_c = arms[False]["wy"] / arms[False]["w"]
print(f"[matched] {win} GI bleed risk: exposed {fmt_pct(arms[True]['events'], arms[True]['n'])}, "
      f"matched unexposed {fmt_pct(arms[False]['events'], arms[False]['n'])}"
      + (" (unweighted counts; weighted risks below)" if ratio_k > 1 else ""))

# Per exposed person: own outcome minus the mean outcome of their matched controls.
yt = y.withColumnRenamed("id", "person_id").withColumnRenamed("outcome", "y_t")
yc = y.withColumnRenamed("id", "match_person_id").withColumnRenamed("outcome", "y_c")
per_t = (pairs.join(yt, "person_id").join(yc, "match_person_id")
         .groupBy("person_id").agg(F.first("y_t").alias("y_t"), F.avg("y_c").alias("y_c"))
         .withColumn("d", F.col("y_t") - F.col("y_c")))
s = per_t.agg(
    F.count("*").alias("n"), F.avg("d").alias("rd"), F.stddev("d").alias("sd"),
    F.sum(F.when((F.col("y_t") == 1) & (F.col("y_c") == 0), 1).otherwise(0)).alias("b"),
    F.sum(F.when((F.col("y_t") == 0) & (F.col("y_c") == 1), 1).otherwise(0)).alias("c"),
).collect()[0]

counts = [arms[True]["events"], arms[False]["events"],
          arms[True]["n"] - arms[True]["events"], arms[False]["n"] - arms[False]["events"]]
if ratio_k == 1:
    counts += [s["b"], s["c"]]
if any(small(k) for k in counts):
    print("[matched] effect estimates suppressed: a contributing count is below min_cell")
else:
    se = s["sd"] / np.sqrt(s["n"])
    print(f"[matched] risk difference = {100 * s['rd']:.2f} pp "
          f"(95% CI {100 * (s['rd'] - 1.96 * se):.2f} to {100 * (s['rd'] + 1.96 * se):.2f}); "
          f"risk ratio = {f'{risk_t / risk_c:.2f}' if risk_c > 0 else 'undefined (no control events)'}")
    if ratio_k == 1:
        b, c = s["b"], s["c"]
        print(f"[matched] discordant pairs: exposed-only {fmt_n(b)}, control-only {fmt_n(c)}")
        if b + c > 0:
            stat = (abs(b - c) - 1) ** 2 / (b + c)  # continuity-corrected, as R's mcnemar.test
            print(f"[matched] McNemar chi-sq = {stat:.2f}, p = {chi2.sf(stat, 1):.4g}")
    if cfg.get("with_replacement"):
        print("[matched] note: CI ignores reuse of controls (with replacement), so it is too narrow")

spark.stop()
