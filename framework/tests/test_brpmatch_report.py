from utilities.brpmatch_report import format_bucket_stats

STATS = {
    "n_buckets": 412, "min": 3, "q": [25, 180, 900, 4000, 9100], "max": 9800, "mean": 1043.7,
    "sum_patients": 429_400, "sum_treated": 204_500, "max_treated": 610, "max_control": 9500,
    "sec_total": 812.4, "sec_mean": 1.97, "sec_q": [0.4, 7.9], "sec_max": 31.2,
}


def lines(**totals):
    return "\n".join(format_bucket_stats(STATS, min_cell=20, **totals))


def test_bucket_stats_are_aggregate_and_small_cell_safe():
    text = lines(n_total=430_094, n_treated=204_840)
    assert "412 buckets" in text
    assert "min <20" in text                  # 3 patients in a bucket is a small cell
    assert "median 900" in text and "max 9,800" in text
    assert "total 812.4" in text and "max 31.20" in text


def test_max_group_sizes_are_not_labelled_as_one_bucket():
    # max(num_treated) and max(num_control) can come from different buckets.
    text = lines(n_total=430_094, n_treated=204_840)
    assert "largest exposed group in any bucket 610" in text
    assert "largest control group in any bucket 9,500" in text
    assert "largest bucket:" not in text


def test_reports_people_outside_matched_buckets():
    # bucket_stats only holds buckets that produced a match, so coverage must
    # come from totals, not from counting one-sided buckets (always 0 there).
    text = lines(n_total=430_094, n_treated=204_840)
    assert "patients in matched buckets: 429,400 of 430,094 (694 outside)" in text
    assert "exposed: 204,500 of 204,840 (340 outside)" in text
    assert "one-sided" not in text


def test_small_outside_count_is_not_derivable():
    text = lines(n_total=429_410, n_treated=204_505)
    assert "all but <20 of 429,410" in text and "429,400" not in text
    assert "exposed: all but <20 of 204,505" in text


def test_every_line_is_tagged():
    assert all(l.startswith("[buckets] ") for l in format_bucket_stats(STATS, min_cell=20))


def test_inclusive_suppression_hides_min_cell_itself():
    s = dict(STATS, min=20, max_treated=20)
    text = "\n".join(format_bucket_stats(s, min_cell=20, inclusive=True,
                                         n_total=430_094, n_treated=430_074 - 100))
    assert "min ≤20" in text
    assert "largest exposed group in any bucket ≤20" in text
    assert " 20," not in text and "<20" not in text


from utilities.brpmatch_report import format_match_gap  # noqa: E402


def _numbers(text):
    import re
    return [int(x.replace(",", "")) for x in re.findall(r"(?<![≤<\d])\d[\d,]*(?![\d.%])", text)]


def test_match_gap_hides_best_when_it_is_almost_everyone():
    # best = 798 of 802 (4 unmatchable): neither best nor the gap may be shown,
    # else 802 - (569 + 229) recovers the 4.
    text = format_match_gap(best=798, actual=569, n_t=802, min_cell=20, inclusive=True)
    assert "all but ≤20" in text
    assert 798 not in _numbers(text) and 229 not in _numbers(text)
    assert "569" in text


def test_match_gap_hides_small_loss():
    text = format_match_gap(best=1000, actual=990, n_t=1500, min_cell=20, inclusive=True)
    assert "within ≤20 of best possible" in text
    assert 1000 not in _numbers(text) and 10 not in _numbers(text)


def test_match_gap_shows_everything_when_safe():
    text = format_match_gap(best=200_000, actual=108_000, n_t=204_840, min_cell=20, inclusive=True)
    assert "200,000 of 204,840" in text and "108,000 of 204,840" in text
    assert "candidate-limit loss 92,000" in text
