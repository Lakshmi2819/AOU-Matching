"""Aggregate, small-cell-safe summaries of BRPMatch's per-bucket diagnostics.

match() returns a bucket_stats table (one row per LSH bucket: num_patients,
num_treated, num_control, num_matches, seconds). Printing it directly would
show small groups of participants, so these helpers reduce it to a few
distribution statistics and suppress any participant count from 1 to
min_cell-1. Bucket counts and seconds are not participant counts.

Caveat on coverage: match() drops buckets that lack either cohort before
matching, and bucket_stats is built from the matches, so it only contains
buckets that produced at least one match. Counting one-sided buckets in it is
always zero. Coverage is therefore reported as people in the matched buckets
versus the cohort totals passed in by the caller.
"""
from __future__ import annotations

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]


def collect_bucket_stats(bucket_stats) -> dict:
    """One small aggregate row from match()'s bucket_stats Spark DataFrame."""
    import pyspark.sql.functions as F

    row = bucket_stats.agg(
        F.count("*").alias("n_buckets"),
        F.min("num_patients").alias("min"),
        F.percentile_approx("num_patients", QUANTILES).alias("q"),
        F.max("num_patients").alias("max"),
        F.avg("num_patients").alias("mean"),
        F.sum("num_patients").alias("sum_patients"),
        F.sum("num_treated").alias("sum_treated"),
        F.max("num_treated").alias("max_treated"),
        F.max("num_control").alias("max_control"),
        F.sum("seconds").alias("sec_total"),
        F.avg("seconds").alias("sec_mean"),
        F.percentile_approx("seconds", [0.5, 0.95]).alias("sec_q"),
        F.max("seconds").alias("sec_max"),
    ).collect()[0]
    return row.asDict()


def format_bucket_stats(s: dict, min_cell: int = 20,
                        n_total: int | None = None, n_treated: int | None = None) -> list[str]:
    """n_total / n_treated: the cohort that went into match(), for coverage."""
    def n(x) -> str:  # a participant count
        x = int(round(x or 0))
        return f"<{min_cell}" if 0 < x < min_cell else f"{x:,}"

    def covered(inside, total) -> str:
        # Never print inside and total together when their difference is small.
        outside = total - inside
        if 0 < outside < min_cell:
            return f"all but <{min_cell} of {n(total)}"
        return f"{n(inside)} of {n(total)} ({n(outside)} outside)"

    p5, p25, p50, p75, p95 = s["q"]
    out = [
        f"[buckets] {s['n_buckets']:,} buckets with matches; patients per bucket: min {n(s['min'])}, "
        f"p5 {n(p5)}, p25 {n(p25)}, median {n(p50)}, p75 {n(p75)}, p95 {n(p95)}, "
        f"max {n(s['max'])}, mean {n(s['mean'])}",
        f"[buckets] largest exposed group in any bucket {n(s['max_treated'])}; "
        f"largest control group in any bucket {n(s['max_control'])} (may be different buckets)",
    ]
    if n_total is not None and n_treated is not None:
        out.append(
            f"[buckets] patients in matched buckets: {covered(s['sum_patients'], n_total)}; "
            f"exposed: {covered(s['sum_treated'], n_treated)} "
            f"(outside = in buckets dropped for lacking a cohort or with no match)")
    out.append(
        f"[buckets] seconds per bucket: total {s['sec_total']:.1f}, mean {s['sec_mean']:.2f}, "
        f"median {s['sec_q'][0]:.2f}, p95 {s['sec_q'][1]:.2f}, max {s['sec_max']:.2f}")
    return out
