from utilities.brpmatch_report import format_bucket_stats

STATS = {
    "n_buckets": 412, "min": 3, "q": [25, 180, 900, 4000, 9100], "max": 9800, "mean": 1043.7,
    "one_sided": 7, "treated_no_controls": 12, "max_treated": 610, "max_control": 9500,
    "sec_total": 812.4, "sec_mean": 1.97, "sec_q": [0.4, 7.9], "sec_max": 31.2,
}


def test_bucket_stats_are_aggregate_and_small_cell_safe():
    text = "\n".join(format_bucket_stats(STATS, min_cell=20))
    assert "412 buckets" in text
    assert "min <20" in text                  # 3 patients in a bucket is a small cell
    assert "median 900" in text and "max 9,800" in text
    assert "exposed in buckets with no controls: <20" in text
    assert "one-sided buckets (no exposed or no controls): 7" in text  # a bucket count, not people
    assert "total 812.4" in text and "max 31.20" in text


def test_every_line_is_tagged():
    assert all(line.startswith("[buckets] ") for line in format_bucket_stats(STATS, min_cell=20))
