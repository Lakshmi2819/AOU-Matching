#!/usr/bin/env python
"""Real-data BRPMatch scaling benchmark on the AoU cluster (no outcome).

  1. Cohort: Spark SQL over the CDR tables (cohort.sql); built once and cached
     on the executors. Nothing is collected to pandas.
  2. Features: generate_features() once, so one-hot categories are identical
     across runs.
  3. Runs: for each entry in config `runs`, keep a deterministic hash-based
     share of treated and of controls (person_id mod 100; sets size and ratio),
     match with the given rebucket threshold and n_neighbors, and report match
     rate, covariate balance (SMD computed in Spark, not via match_summary(),
     which collects the whole cohort to the driver), bucket stats, wall time,
     and diagnostics on the unmatched:
       - best possible matches inside buckets (sum of min(treated, controls))
         vs actual: how much the k-NN candidate limit costs;
       - SMD of unmatched treated vs unused controls: do the unmatched look
         like the leftover controls (avoidable losses) or not (hard to match);
       - unmatched treated sharing a coarse cell (exact group x birth band x
         condition-count quantile) with at least one unused control;
       - capacity across the whole cohort (ignoring buckets): sum over cells of
         min(unmatched treated, unused controls), at each configured
         granularity, next to the unmatched total and the in-bucket loss.

Aggregate output only; participant counts from 1 to min_cell (inclusive) are
suppressed and shown as "≤min_cell".
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

import brpmatch
import pyspark.sql.functions as F
import yaml
from brpmatch import generate_features, match

from utilities.brpmatch_report import (collect_bucket_stats, format_bucket_stats, format_cell_capacity,
                                       format_match_gap)
from utilities.spark import get_spark, load_cohort, ship_package

sys.stdout.reconfigure(line_buffering=True)

ap = argparse.ArgumentParser()
ap.add_argument("--config", required=True)
cfg = yaml.safe_load(Path(ap.parse_args().config).read_text())
min_cell = cfg.get("min_cell", 20)
exact_cols = cfg.get("exact_match_cols", [])
num_cols = cfg.get("numeric_cols", [])
cat_cols = cfg.get("categorical_cols", [])
FEATURE_SUFFIXES = ("__num", "__cat", "__exact", "__date")


HIDDEN = f"≤{min_cell}"


def small(n) -> bool:
    """Counts from 1 to min_cell inclusive are never shown."""
    return 0 < n <= min_cell


def fmt_n(n) -> str:
    return HIDDEN if small(n) else f"{int(n):,}"


def share(k, total) -> str:
    """'k of total (pct)', without ever making a small count derivable."""
    if small(total - k):
        return f"all but {HIDDEN} of {fmt_n(total)}"
    if small(k):
        return f"{HIDDEN} of {fmt_n(total)}"
    return f"{fmt_n(k)} of {fmt_n(total)} ({100 * k / max(total, 1):.1f}%)"


def keep_share(id_col: str, pct: float):
    """Deterministic subsample: person_id mod 100 < pct (about pct% of ids).

    Plain arithmetic rather than a hash so the R/MatchIt comparison
    (experiments/2026-10-22-matchit-realdata) selects exactly the same people.
    """
    return F.pmod(F.col(id_col).cast("long"), F.lit(100)) < F.lit(pct)


def smd_between(df, flag, cols):
    """Per-covariate SMD between rows with flag == 1 and flag == 0 (unweighted,
    brpmatch's compute_smd() definition)."""
    aggs = []
    for i, c in enumerate(cols):
        for g, m in (("a", F.col(flag) == 1), ("b", F.col(flag) == 0)):
            aggs += [F.avg(F.when(m, F.col(c))).alias(f"m{g}{i}"),
                     F.var_samp(F.when(m, F.col(c))).alias(f"v{g}{i}")]
    r = df.agg(*aggs).collect()[0]
    out = {}
    for i, c in enumerate(cols):
        sd = (((r[f"va{i}"] or 0) + (r[f"vb{i}"] or 0)) / 2) ** 0.5
        ok = sd >= 1e-10 and r[f"ma{i}"] is not None and r[f"mb{i}"] is not None
        out[c.rsplit("__", 1)[0]] = (r[f"ma{i}"] - r[f"mb{i}"]) / sd if ok else 0.0
    return out


def cell_key(sub, band, q):
    """Coarse cell: exact-match group x band-year birth band x q quantile bins of
    condition count; quantile cut points come from the whole run cohort."""
    dcfg = cfg.get("diagnostics", {})
    yob = f"{dcfg.get('birth_col', 'year_of_birth')}__num"
    cond = f"{dcfg.get('conditions_col', 'log_conditions')}__num"
    cuts = sub.approxQuantile(cond, [i / q for i in range(1, q)], 0.001)
    qbin = sum((F.when(F.col(cond) > cut, 1).otherwise(0) for cut in cuts), F.lit(0))
    return F.concat_ws("|", F.col("exact_match__group").cast("string"),
                       F.floor(F.col(yob) / band).cast("string"), qbin.cast("string"))


def guarded(name, label, fn):
    """Run one diagnostic; on failure print which one and the traceback (code
    lines, no data) and carry on, so one diagnostic can't end the session."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - report and continue
        print(f"{label} [diag] {name} FAILED: {type(e).__name__}; run continues", flush=True)
        traceback.print_exc(file=sys.stdout)
        return None


def diagnose(sub, units, bstats, cols, n_t, n_matched, label):
    """Is the unmatched loss avoidable? Each diagnostic prints as soon as it is
    ready and is guarded separately, so a failure loses only that line."""
    dcfg = cfg.get("diagnostics", {})
    q = dcfg.get("condition_quantiles", 5)
    band = dcfg.get("birth_band_years", 5)

    # 1. Best possible 1:1 within the buckets match() formed vs actual.
    # format_match_gap hides any of best / gap / unmatchable that could reveal a
    # small count through the others.
    def match_gap():
        b = bstats.agg(F.sum(F.least("num_treated", "num_control")).alias("b")).collect()[0]["b"] or 0
        print(f"{label} " + format_match_gap(b, n_matched, n_t, min_cell, inclusive=True), flush=True)
        return b

    best = guarded("best possible within buckets", label, match_gap)

    lab = sub.join(units.select(F.col("id").alias("person_id__id"), "weight"), "person_id__id")
    left = lab.filter(F.col("weight") == 0).cache()
    try:
        c = left.agg(F.sum("treat__treat").alias("t"), F.count("*").alias("n")).collect()[0]
        n_ut, n_uc = c["t"] or 0, (c["n"] or 0) - (c["t"] or 0)
        if n_ut <= min_cell or n_uc <= min_cell:
            print(f"{label} [diag] unmatched treated {fmt_n(n_ut)}, unused controls {fmt_n(n_uc)}: "
                  f"too few to compare (diagnostics 2-4 suppressed)", flush=True)
            return

        # 2. Unmatched treated vs unused controls.
        def unmatched_smd():
            left_smd = smd_between(left, "treat__treat", cols)
            all_smd = smd_between(sub, "treat__treat", cols)
            worst = max(left_smd, key=lambda k: abs(left_smd[k]))
            nums = ", ".join(f"{k} {left_smd[k]:.3f}" for k in num_cols if k in left_smd)
            print(f"{label} [diag] unmatched treated {fmt_n(n_ut)} vs unused controls {fmt_n(n_uc)}: "
                  f"max |SMD| {abs(left_smd[worst]):.3f} ({worst}); {nums} "
                  f"(all treated vs all controls: max |SMD| {max(map(abs, all_smd.values())):.3f})",
                  flush=True)

        guarded("unmatched vs unused SMD", label, unmatched_smd)

        # 3. Unmatched treated sharing a coarse cell with >= 1 unused control.
        def cell_share():
            cells = left.withColumn("_cell", cell_key(sub, band, q))
            unused_cells = cells.filter(F.col("treat__treat") == 0).select("_cell").distinct()
            n_share = (cells.filter(F.col("treat__treat") == 1)
                       .join(unused_cells, "_cell", "left_semi").count())
            print(f"{label} [diag] unmatched treated sharing a cell (exact group x {band}-yr birth band "
                  f"x {q} condition-count quantiles) with >=1 unused control: {share(n_share, n_ut)}",
                  flush=True)

        guarded("cell share", label, cell_share)

        # 4. Capacity across the whole cohort (ignoring buckets): sum over cells
        # of min(unmatched treated, unused controls), at each granularity.
        if best is None:
            print(f"{label} [diag] capacity skipped: needs diagnostic 1", flush=True)
            return
        for g in dcfg.get("capacity_cells", [{"birth_band_years": band, "condition_quantiles": q}]):
            gb, gq = g["birth_band_years"], g["condition_quantiles"]

            def capacity_line(gb=gb, gq=gq):
                per_cell = (left.withColumn("_cell", cell_key(sub, gb, gq)).groupBy("_cell")
                            .agg(F.sum("treat__treat").alias("t"),
                                 F.sum(1 - F.col("treat__treat")).alias("c")))
                capacity = per_cell.agg(F.sum(F.least("t", "c")).alias("k")).collect()[0]["k"] or 0
                print(f"{label} " + format_cell_capacity(
                    f"exact group x {gb}-yr birth band x {gq} condition-count quantiles",
                    capacity, best, n_matched, n_t, min_cell, inclusive=True), flush=True)

            guarded(f"capacity {gb}-yr x {gq}q", label, capacity_line)
    finally:
        left.unpersist()


def balance(feats, units, cols):
    """Max |SMD| before/after matching, computed with Spark aggregations.

    SMD = (mean_treated - mean_control) / sqrt((var_t + var_c) / 2), with the
    variances of the sample being described: all people before matching, the
    matched people (weighted by match() weights) after. This is brpmatch's own
    compute_smd() definition, so numbers line up with match_summary().
    """
    t = F.col("treat__treat") == 1
    before = []
    for i, c in enumerate(cols):
        for g, m in (("t", t), ("c", ~t)):
            before += [F.avg(F.when(m, F.col(c))).alias(f"m{g}{i}"),
                       F.var_samp(F.when(m, F.col(c))).alias(f"v{g}{i}")]
    b = feats.agg(*before).collect()[0]

    id_col = next(c for c in feats.columns if c.endswith("__id"))
    matched = feats.join(
        units.filter(F.col("weight") > 0).select(F.col("id").alias(id_col), "weight"), id_col)
    after = []
    for i, c in enumerate(cols):
        for g, m in (("t", t), ("c", ~t)):
            after += [F.sum(F.when(m, F.col("weight") * F.col(c))).alias(f"s{g}{i}"),
                      F.sum(F.when(m, F.col("weight") * F.col(c) * F.col(c))).alias(f"q{g}{i}"),
                      F.sum(F.when(m, F.col("weight"))).alias(f"w{g}{i}")]
    a = matched.agg(*after).collect()[0]

    def smd(mt, mc, vt, vc):
        sd = (((vt or 0) + (vc or 0)) / 2) ** 0.5
        return 0.0 if sd < 1e-10 else (mt - mc) / sd

    smd_b, smd_a = {}, {}
    for i, c in enumerate(cols):
        name = c.rsplit("__", 1)[0]
        smd_b[name] = smd(b[f"mt{i}"], b[f"mc{i}"], b[f"vt{i}"], b[f"vc{i}"])
        if a[f"wt{i}"] and a[f"wc{i}"]:
            mean = {g: a[f"s{g}{i}"] / a[f"w{g}{i}"] for g in "tc"}
            var = {g: a[f"q{g}{i}"] / a[f"w{g}{i}"] - mean[g] ** 2 for g in "tc"}
            smd_a[name] = smd(mean["t"], mean["c"], var["t"], var["c"])
    worst = max(smd_a, key=lambda k: abs(smd_a[k])) if smd_a else None
    return (max(map(abs, smd_b.values()), default=float("nan")),
            abs(smd_a[worst]) if worst else float("nan"), worst)


# --- 1. cohort (Spark SQL over the CDR; cached on executors) ----------------------
spark = get_spark("brpmatch-realdata-scaling")
ship_package(spark, brpmatch)
sc = spark.sparkContext
print(f"[bench] spark master: {sc.master}; default parallelism: {sc.defaultParallelism}; "
      f"executor instances: {sc.getConf().get('spark.executor.instances', 'n/a')}; "
      f"executor cores: {sc.getConf().get('spark.executor.cores', 'n/a')}; "
      f"executor memory: {sc.getConf().get('spark.executor.memory', 'n/a')}")

t0 = time.perf_counter()
df = load_cohort(spark, Path(cfg["sql_file"]).read_text(), cfg["cdr_tables"],
                 params=cfg.get("sql_params"))
df = df.select(
    F.col("person_id").cast("long"), F.col("treat").cast("int"),
    *[F.col(c).cast("double") for c in num_cols],
    *[F.col(c).cast("string") for c in exact_cols + cat_cols],
)
# Merge categories too small to show safely (in either group) into "other".
for c in exact_cols + cat_cols:
    counts = df.groupBy(c).agg(F.sum("treat").alias("t"), F.sum(1 - F.col("treat")).alias("u")).collect()
    rare = [r[c] for r in counts if min(r["t"], r["u"]) <= min_cell and r[c] is not None]
    if rare:
        df = df.withColumn(c, F.when(F.col(c).isin(rare), F.lit("other")).otherwise(F.col(c)))
df = df.orderBy("person_id").cache()
tot = df.agg(F.count("*").alias("n"), F.sum("treat").alias("t")).collect()[0]
print(f"[cohort] treatment concept {cfg['sql_params']['treatment_concept_id']}: "
      f"{fmt_n(tot['t'])} treated, {fmt_n(tot['n'] - tot['t'])} controls "
      f"(population share {cfg['sql_params'].get('population_pct', 100)}%); "
      f"built in {time.perf_counter() - t0:.0f}s")

# --- 2. features (once) -------------------------------------------------------------
feats = generate_features(
    spark, df, id_col="person_id", treatment_col="treat", treatment_value="1",
    categorical_cols=cat_cols or None, numeric_cols=num_cols or None,
    exact_match_cols=exact_cols or None,
).cache()
feat_cols = [c for c in feats.columns if c.endswith(FEATURE_SUFFIXES)]
print(f"[cohort] {len(feat_cols)} feature columns; exact on {', '.join(exact_cols) or 'nothing'}; "
      f"{cfg.get('feature_space', 'mahalanobis')}, 1:{cfg.get('ratio_k', 1)}, "
      f"{'with' if cfg.get('with_replacement') else 'without'} replacement, "
      f"n_neighbors {cfg.get('n_neighbors', 5)} (default; per-run overrides in labels)")

# --- 3. runs ------------------------------------------------------------------------
for r in cfg["runs"]:
    tp, cp, thr = r["treated_pct"], r["control_pct"], r["threshold"]
    k_nn = r.get("n_neighbors", cfg.get("n_neighbors", 5))
    label = f"[run t{tp}% c{cp}% thr{thr} k{k_nn}]"
    sub = feats.filter(
        ((F.col("treat__treat") == 1) & keep_share("person_id__id", tp))
        | ((F.col("treat__treat") == 0) & keep_share("person_id__id", cp))
    ).cache()
    n = sub.agg(F.count("*").alias("n"), F.sum("treat__treat").alias("t")).collect()[0]
    n_t, n_c = n["t"], n["n"] - n["t"]

    t0 = time.perf_counter()
    units, _, bstats = match(
        sub,
        feature_space=cfg.get("feature_space", "mahalanobis"),
        ratio_k=cfg.get("ratio_k", 1),
        with_replacement=cfg.get("with_replacement", False),
        n_neighbors=k_nn,
        num_patients_trigger_rebucket=thr,
        seed=cfg.get("seed", 42),
        verbose=False,  # its per-bucket printout can include small counts
    )
    units = units.cache()
    n_matched = units.filter(F.col("is_treated") & (F.col("weight") > 0)).count()
    secs = time.perf_counter() - t0

    unmatched = n_t - n_matched
    rate = (f"all but {HIDDEN}" if small(unmatched)
            else f"{100 * n_matched / n_t:.1f}% ({fmt_n(unmatched)} unmatched)")
    smd_before, smd_after, worst = balance(sub, units, feat_cols)
    print(f"{label} treated {fmt_n(n_t)}, controls {fmt_n(n_c)} (1:{n_c / max(n_t, 1):.1f}); "
          f"matched {rate}; max |SMD| {smd_before:.3f} -> {smd_after:.3f} ({worst}); "
          f"match wall time {secs:.0f}s")
    for line in format_bucket_stats(collect_bucket_stats(bstats), min_cell, n_total=n_t + n_c,
                                    n_treated=n_t, inclusive=True):
        print(line.replace("[buckets]", f"{label} [buckets]", 1))
    if r.get("diagnostics", cfg.get("diagnostics", {}).get("enabled", True)):
        guarded("diagnostics", label,
                lambda: diagnose(sub, units, bstats, feat_cols, n_t, n_matched, label))
    units.unpersist()
    sub.unpersist()

spark.stop()
print("[bench] DONE")
