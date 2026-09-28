"""Tests for advisories.py: the advisory format, the weekly figures, and the writer."""
from typing import Dict, Optional, Tuple

import pytest

import config
from advisories import AdvisoryWriter, advisory_text, format_period, make_advisory, weekly_figures

SENSORS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]

# A day's readings by sensor, where None means that sensor sent nothing.
DayReadings = Dict[str, Optional[Tuple[float, float]]]


def week(start_day=1, rain=2.0, level=1.0, step=-0.01) -> Dict[str, DayReadings]:
    """Seven days of readings where every sensor gets the same rain and the rivers move by `step` a day."""
    return {f"2026-06-{start_day + i:02d}": {sid: (rain, round(level + step * i, 2)) for sid in SENSORS}
            for i in range(7)}


# The advisory itself

def test_figures_are_rounded_to_what_a_notice_would_quote():
    advisory = make_advisory("ADV-01", "2026-06-07", "2026-06-01", "2026-06-07", "Water Corporation", 24.6349, -0.1249)
    assert advisory["avg_rain_mm"] == 24.6
    assert advisory["avg_level_change_m"] == -0.12


def test_period_ending_before_it_starts_is_rejected():
    with pytest.raises(ValueError, match="ADV-09"):
        make_advisory("ADV-09", "2026-06-07", "2026-06-07", "2026-06-01", "Water Corporation", 1.0, 0.0)


def test_period_within_one_month():
    assert format_period("2026-06-22", "2026-06-28") == "22-28 Jun"


def test_period_across_two_months():
    assert format_period("2026-06-29", "2026-07-05") == "29 Jun - 5 Jul"


def test_text_reads_naturally_for_rising_falling_and_flat_rivers():
    base = ("ADV-01", "2026-06-07", "2026-06-01", "2026-06-07", "Water Corporation", 12.0)
    assert advisory_text(make_advisory(*base, 0.35)).endswith("river levels up 0.35 m.")
    assert advisory_text(make_advisory(*base, -0.2)).endswith("river levels down 0.20 m.")
    assert advisory_text(make_advisory(*base, 0.0)).endswith("river levels unchanged.")


def test_text_includes_source_period_and_rainfall():
    advisory = make_advisory("ADV-01", "2026-06-07", "2026-06-01", "2026-06-07", "Water Corporation", 12.0, 0.1)
    assert advisory_text(advisory).startswith("Water Corporation weekly update (1-7 Jun): average rainfall 12.0 mm")


# Weekly figures

def test_rain_is_each_sensors_weekly_total_averaged_across_sensors():
    # Every sensor gets 2 mm a day for 7 days, so each weekly total, and the average, is 14 mm.
    figures = weekly_figures(week(rain=2.0), "2026-06-01", "2026-06-07")
    assert figures is not None
    rain, _ = figures
    assert rain == pytest.approx(14.0)


def test_level_change_runs_from_the_first_day_to_the_last():
    # Rivers fall 1 cm a day, so from day 1 to day 7 they drop 6 cm.
    figures = weekly_figures(week(step=-0.01), "2026-06-01", "2026-06-07")
    assert figures is not None
    _, change = figures
    assert change == pytest.approx(-0.06)


def test_only_days_inside_the_period_count():
    readings = {**week(start_day=1, rain=2.0), **week(start_day=8, rain=50.0)}
    figures = weekly_figures(readings, "2026-06-01", "2026-06-07")
    assert figures is not None
    rain, _ = figures
    assert rain == pytest.approx(14.0)


def test_missing_readings_are_skipped():
    readings = week(rain=2.0)
    readings["2026-06-03"]["S1"] = None
    figures = weekly_figures(readings, "2026-06-01", "2026-06-07")
    assert figures is not None
    rain, change = figures

    # S1 missed one day, so its total is 12 mm while the other seven have 14 mm.
    assert rain == pytest.approx((12.0 + 7 * 14.0) / 8)
    assert change == pytest.approx(-0.06)


def test_period_with_no_readings_gives_none():
    assert weekly_figures(week(), "2026-07-01", "2026-07-07") is None


# The writer

def test_writer_publishes_on_the_seventh_day_only():
    writer = AdvisoryWriter()
    published = [writer.record(d, r) for d, r in week().items()]

    assert published[:6] == [None] * 6

    advisory = published[6]
    assert advisory is not None
    assert advisory["period_start"] == "2026-06-01"
    assert advisory["period_end"] == "2026-06-07"
    assert advisory["published"] == "2026-06-07"


def test_writer_uses_an_approved_source_and_numbers_its_advisories():
    writer = AdvisoryWriter()
    readings = {**week(start_day=1), **week(start_day=8)}
    published = [a for a in (writer.record(d, r) for d, r in readings.items()) if a]

    assert [a["id"] for a in published] == ["ADV-01", "ADV-02"]
    assert all(a["source"] in config.APPROVED_SOURCES for a in published)


def test_writer_quotes_the_readings_it_is_given():
    # A 70 mm fake reading on one day is passed straight into the advisory, as a real agency's system would.
    readings = week(rain=2.0)
    readings["2026-06-04"]["S3"] = (70.0, 0.97)
    writer = AdvisoryWriter()
    advisory = [writer.record(d, r) for d, r in readings.items()][-1]

    assert advisory is not None
    assert advisory["avg_rain_mm"] == round((7 * 14.0 + (14.0 - 2.0 + 70.0)) / 8, 1)
