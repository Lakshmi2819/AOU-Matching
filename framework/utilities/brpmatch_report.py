"""Aggregate, small-cell-safe summaries of BRPMatch's per-bucket diagnostics.

match() returns a bucket_stats table (one row per LSH bucket: num_patients,
num_treated, num_control, num_matches, seconds). Printing it directly would
show small groups of participants, so these helpers reduce it to a few
distribution statistics and suppress any participant count from 1 to
min_cell-1. Bucket counts and seconds are not participant counts.
"""
from __future__ import annotations

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]


def collect_bucket_stats(bucket_stats) -> dict:
    """One small aggregate row from match()'s bucket_stats Spark DataFrame."""
    import pyspark.sql.functions as F

    one_sided = (F.col("num_treated") == 0) | (F.col("num_control") == 0)
    row = bucket_stats.agg(
        F.count("*").alias("n_buckets"),
        F.min("num_patients").alias("min"),
        F.percentile_approx("num_patients", QUANTILES).alias("q"),
        F.max("num_patients").alias("max"),
        F.avg("num_patients").alias("mean"),
        F.sum(F.when(one_sided, 1).otherwise(0)).alias("one_sided"),
        F.sum(F.when(F.col("num_control") == 0, F.col("num_treated")).otherwise(0)).alias("treated_no_controls"),
        F.max("num_treated").alias("max_treated"),
        F.max("num_control").alias("max_control"),
        F.sum("seconds").alias("sec_total"),
        F.avg("seconds").alias("sec_mean"),
        F.percentile_approx("seconds", [0.5, 0.95]).alias("sec_q"),
        F.max("seconds").alias("sec_max"),
    ).collect()[0]
    return row.asDict()


def format_bucket_stats(s: dict, min_cell: int = 20) -> list[str]:
    def n(x) -> str:  # a participant count
        x = int(round(x or 0))
        return f"<{min_cell}" if 0 < x < min_cell else f"{x:,}"

    p5, p25, p50, p75, p95 = s["q"]
    return [
        f"[buckets] {s['n_buckets']:,} buckets; patients per bucket: min {n(s['min'])}, "
        f"p5 {n(p5)}, p25 {n(p25)}, median {n(p50)}, p75 {n(p75)}, p95 {n(p95)}, "
        f"max {n(s['max'])}, mean {n(s['mean'])}",
        f"[buckets] largest bucket: exposed {n(s['max_treated'])}, controls {n(s['max_control'])}",
        f"[buckets] one-sided buckets (no exposed or no controls): {s['one_sided']:,}; "
        f"exposed in buckets with no controls: {n(s['treated_no_controls'])}",
        f"[buckets] seconds per bucket: total {s['sec_total']:.1f}, mean {s['sec_mean']:.2f}, "
        f"median {s['sec_q'][0]:.2f}, p95 {s['sec_q'][1]:.2f}, max {s['sec_max']:.2f}",
    ]
