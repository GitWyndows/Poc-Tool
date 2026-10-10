"""Tests for advisories.py: the advisory format, the weekly figures, and the writer."""
import pytest

import config
from advisories import AdvisoryWriter, advisory_text, format_period, make_advisory, weekly_figures

GAUGES = ["A", "B", "C", "D", "E"]


def week(start_day=1, flow=20.0, step=1.0):
    """Seven days where every gauge carries the same flow, moving by `step` ML/day each day."""
    return {f"2026-07-{start_day + i:02d}": {sid: flow + step * i for sid in GAUGES} for i in range(7)}


# The advisory itself

def test_figures_are_rounded_to_what_a_notice_would_quote():
    advisory = make_advisory("ADV-01", "2026-07-07", "2026-07-01", "2026-07-07", "Water Corporation", 245.349, -0.1249)
    assert advisory["avg_flow_ml"] == 245.3
    assert advisory["change_pct"] == -12


def test_period_ending_before_it_starts_is_rejected():
    with pytest.raises(ValueError, match="ADV-09"):
        make_advisory("ADV-09", "2026-07-07", "2026-07-07", "2026-07-01", "Water Corporation", 100.0, 0.0)


def test_period_within_one_month():
    assert format_period("2026-07-13", "2026-07-19") == "13-19 Jul"


def test_period_across_two_months():
    assert format_period("2026-06-29", "2026-07-05") == "29 Jun - 5 Jul"


def test_text_reads_naturally_for_rising_falling_and_steady_flow():
    base = ("ADV-01", "2026-07-07", "2026-07-01", "2026-07-07", "Water Corporation", 245.0)
    assert advisory_text(make_advisory(*base, 0.31)).endswith("up 31% over the week.")
    assert advisory_text(make_advisory(*base, -0.24)).endswith("down 24% over the week.")
    assert advisory_text(make_advisory(*base, 0.0)).endswith("unchanged over the week.")


def test_text_includes_source_period_and_flow():
    advisory = make_advisory("ADV-01", "2026-07-07", "2026-07-01", "2026-07-07", "Water Corporation", 245.0, 0.1)
    assert advisory_text(advisory).startswith(
        "Water Corporation weekly update (1-7 Jul): combined streamflow averaged 245.0 ML/day")


# Weekly figures

def test_flow_is_the_combined_flow_of_every_gauge_averaged_over_the_week():
    # Five gauges at 20, 21 ... 26 ML/day combine to 100, 105 ... 130, which averages 115.
    figures = weekly_figures(week(), "2026-07-01", "2026-07-07")
    assert figures is not None
    assert figures[0] == pytest.approx(115.0)


def test_change_runs_from_the_first_day_to_the_last():
    # Combined flow goes from 100 to 130 ML/day, which is up 30%.
    figures = weekly_figures(week(), "2026-07-01", "2026-07-07")
    assert figures is not None
    assert figures[1] == pytest.approx(0.30)


def test_only_days_inside_the_period_count():
    readings = {**week(start_day=1), **week(start_day=8, flow=500.0)}
    figures = weekly_figures(readings, "2026-07-01", "2026-07-07")
    assert figures is not None
    assert figures[0] == pytest.approx(115.0)


def test_dry_start_gives_no_change_rather_than_an_error():
    # Every stream at zero on day one has no sensible percentage change.
    figures = weekly_figures(week(flow=0.0), "2026-07-01", "2026-07-07")
    assert figures is not None
    assert figures[1] == 0.0


def test_period_the_readings_dont_cover_gives_none():
    assert weekly_figures(week(), "2026-07-05", "2026-07-11") is None


# The writer

def test_writer_publishes_on_the_seventh_day_only():
    writer = AdvisoryWriter()
    published = [writer.record(d, flows) for d, flows in week().items()]

    assert published[:6] == [None] * 6

    advisory = published[6]
    assert advisory is not None
    assert (advisory["period_start"], advisory["period_end"], advisory["published"]) == \
        ("2026-07-01", "2026-07-07", "2026-07-07")


def test_writer_uses_an_approved_source_and_numbers_its_advisories():
    writer = AdvisoryWriter()
    readings = {**week(start_day=1), **week(start_day=8)}
    published = [a for a in (writer.record(d, flows) for d, flows in readings.items()) if a]

    assert [a["id"] for a in published] == ["ADV-01", "ADV-02"]
    assert all(a["source"] in config.APPROVED_SOURCES for a in published)


def test_writer_quotes_the_readings_it_is_given():
    # A fake 500 ML/day on one gauge is passed straight into the advisory, as a real agency's system would.
    readings = week()
    readings["2026-07-04"]["C"] = 500.0
    writer = AdvisoryWriter()
    advisory = [writer.record(d, flows) for d, flows in readings.items()][-1]

    assert advisory is not None
    assert advisory["avg_flow_ml"] == round((7 * 115.0 + 500.0 - 23.0) / 7, 1)


def test_writer_keeps_every_advisory_it_publishes():
    writer = AdvisoryWriter()
    for d, flows in {**week(start_day=1), **week(start_day=8)}.items():
        writer.record(d, flows)
    assert [a["id"] for a in writer.published] == ["ADV-01", "ADV-02"]
