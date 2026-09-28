"""Tests for attacks.py: the right value is changed, and every change is logged."""
import pytest

import config
from attacks import Attacker, attack_dates, day_after, describe

PLAN = [
    {"type": "spike", "sensor": "S3", "date": "2026-06-13", "field": "rainfall_mm", "value": 80.0},
    {"type": "spike", "sensor": "S5", "date": "2026-08-10", "field": "river_level_m", "value": 3.20},
]

FLATLINE = {"type": "flatline", "sensor": "S7", "start": "2026-06-26", "days": 3, "field": "river_level_m"}

DRIFT = {"type": "drift", "sensor": "S2", "start": "2026-07-18", "days": 3, "field": "river_level_m", "rate": 0.06}

FAKE_FIGURES = {"type": "fake_figures", "date": "2026-06-07", "period_start": "2026-06-01", "period_end": "2026-06-07",
                "source": "Water Corporation", "avg_rain_mm": 1.5, "avg_level_change_m": -0.8}

FAKE_SOURCE = {"type": "fake_source", "date": "2026-06-07", "period_start": "2026-06-01", "period_end": "2026-06-07",
               "source": "WA Water Watch"}


def week_of_readings():
    """Seven days where all 8 sensors get 2 mm a day and the rivers fall 1 cm a day."""
    return {f"2026-06-{i + 1:02d}": {f"S{s}": (2.0, round(1.0 - 0.01 * i, 2)) for s in range(1, 9)} for i in range(7)}


def test_rainfall_attack_changes_only_rainfall():
    attacker = Attacker(PLAN)
    assert attacker.apply("S3", "2026-06-13", (0.0, 2.04)) == (80.0, 2.04)


def test_river_attack_changes_only_river_level():
    attacker = Attacker(PLAN)
    assert attacker.apply("S5", "2026-08-10", (0.0, 1.76)) == (0.0, 3.20)


def test_untargeted_readings_pass_through_unchanged():
    attacker = Attacker(PLAN)

    # Right sensor on the wrong day, and the wrong sensor on the right day.
    assert attacker.apply("S3", "2026-06-14", (1.2, 2.00)) == (1.2, 2.00)
    assert attacker.apply("S4", "2026-06-13", (0.0, 1.76)) == (0.0, 1.76)
    assert attacker.log == []


def test_missing_reading_is_not_attacked():
    attacker = Attacker(PLAN)
    assert attacker.apply("S3", "2026-06-13", None) is None
    assert attacker.log == []


def test_log_records_real_and_fake_values():
    attacker = Attacker(PLAN)
    attacker.apply("S3", "2026-06-13", (0.0, 2.04))

    assert attacker.log == [{
        "attack": 0,
        "type": "spike",
        "date": "2026-06-13",
        "sensor": "S3",
        "field": "rainfall_mm",
        "real": 0.0,
        "fake": 80.0,
    }]


def test_misspelt_field_fails_straight_away():
    bad_plan = [{"type": "spike", "sensor": "S3", "date": "2026-06-13", "field": "rainfal_mm", "value": 80.0}]
    with pytest.raises(ValueError, match="rainfal_mm"):
        Attacker(bad_plan)


def test_unused_lists_attacks_that_never_ran():
    attacker = Attacker(PLAN)
    attacker.apply("S3", "2026-06-13", (0.0, 2.04))

    assert [a["sensor"] for a in attacker.unused()] == ["S5"]


def test_empty_plan_changes_nothing():
    attacker = Attacker([])
    assert attacker.apply("S3", "2026-06-13", (0.0, 2.04)) == (0.0, 2.04)
    assert attacker.unused() == []


def test_unknown_attack_type_fails_straight_away():
    with pytest.raises(ValueError, match="wobble"):
        Attacker([{"type": "wobble", "sensor": "S3", "date": "2026-06-13", "field": "rainfall_mm"}])


# Flatline

def test_flatline_covers_the_right_dates():
    assert attack_dates(FLATLINE) == ["2026-06-26", "2026-06-27", "2026-06-28"]


def test_flatline_repeats_the_first_day_value():
    attacker = Attacker([FLATLINE])
    seen = [attacker.apply("S7", d, (1.0, level))
            for d, level in [("2026-06-26", 2.68), ("2026-06-27", 2.54), ("2026-06-28", 2.37)]]

    assert seen == [(1.0, 2.68), (1.0, 2.68), (1.0, 2.68)]


def test_flatline_stops_after_its_last_day():
    attacker = Attacker([FLATLINE])
    for d in attack_dates(FLATLINE):
        attacker.apply("S7", d, (0.0, 2.68))

    assert attacker.apply("S7", "2026-06-29", (0.0, 1.90)) == (0.0, 1.90)


def test_flatline_logs_every_frozen_day():
    attacker = Attacker([FLATLINE])
    for d, level in [("2026-06-26", 2.68), ("2026-06-27", 2.54), ("2026-06-28", 2.37)]:
        attacker.apply("S7", d, (0.0, level))

    assert [(e["real"], e["fake"]) for e in attacker.log] == [(2.68, 2.68), (2.54, 2.68), (2.37, 2.68)]


def test_describe_gives_a_readable_summary():
    assert describe(FLATLINE) == "flatline on S7 river_level_m from 2026-06-26 to 2026-06-28"
    assert describe(PLAN[0]) == "spike on S3 rainfall_mm on 2026-06-13"


# Drift

def test_drift_adds_a_little_more_each_day():
    attacker = Attacker([DRIFT])
    seen = [attacker.apply("S2", d, (0.0, 1.50)) for d in attack_dates(DRIFT)]

    assert seen == [(0.0, 1.56), (0.0, 1.62), (0.0, 1.68)]


def test_drift_stops_after_its_last_day():
    attacker = Attacker([DRIFT])
    for d in attack_dates(DRIFT):
        attacker.apply("S2", d, (0.0, 1.50))

    assert attacker.apply("S2", "2026-07-21", (0.0, 1.50)) == (0.0, 1.50)


def test_drift_on_rainfall_is_rejected():
    with pytest.raises(ValueError, match="river_level_m"):
        Attacker([{**DRIFT, "field": "rainfall_mm"}])


def test_day_after_is_the_snap_back_date():
    assert day_after(DRIFT) == "2026-07-21"
    assert day_after(PLAN[0]) == "2026-06-14"


def test_describe_drift():
    assert describe(DRIFT) == "drift on S2 river_level_m of +0.06 a day from 2026-07-18 to 2026-07-20"


# Fake advisories

def test_fake_figures_quotes_made_up_numbers_under_an_approved_name():
    attacker = Attacker([FAKE_FIGURES])
    [fake] = attacker.fake_advisories("2026-06-07", week_of_readings())

    assert fake["source"] == "Water Corporation"
    assert (fake["avg_rain_mm"], fake["avg_level_change_m"]) == (1.5, -0.8)


def test_fake_figures_log_shows_the_real_figures_too():
    attacker = Attacker([FAKE_FIGURES])
    attacker.fake_advisories("2026-06-07", week_of_readings())

    entry = attacker.log[0]
    assert entry["field"] == "advisory"
    assert entry["sensor"] == "ADV-F1"
    assert entry["real"] == (14.0, -0.06)
    assert entry["fake"] == (1.5, -0.8)


def test_fake_source_copies_the_real_figures():
    attacker = Attacker([FAKE_SOURCE])
    [fake] = attacker.fake_advisories("2026-06-07", week_of_readings())

    assert fake["source"] == "WA Water Watch"
    assert (fake["avg_rain_mm"], fake["avg_level_change_m"]) == (14.0, -0.06)


def test_fake_advisories_only_go_out_on_their_date():
    attacker = Attacker([FAKE_FIGURES])
    assert attacker.fake_advisories("2026-06-06", week_of_readings()) == []
    assert attacker.log == []


def test_fake_source_with_no_readings_is_skipped_and_reported_unused():
    attacker = Attacker([FAKE_SOURCE])
    assert attacker.fake_advisories("2026-06-07", {}) == []
    assert attacker.unused() == [FAKE_SOURCE]


def test_advisory_attacks_leave_sensor_readings_alone():
    attacker = Attacker([FAKE_FIGURES, FAKE_SOURCE])
    assert attacker.apply("S1", "2026-06-07", (2.0, 0.94)) == (2.0, 0.94)


def test_fake_source_using_an_approved_name_is_rejected():
    with pytest.raises(ValueError, match="approved"):
        Attacker([{**FAKE_SOURCE, "source": config.APPROVED_SOURCES[0]}])


def test_fake_figures_without_figures_is_rejected():
    bad = {k: v for k, v in FAKE_FIGURES.items() if k != "avg_rain_mm"}
    with pytest.raises(ValueError, match="avg_rain_mm"):
        Attacker([bad])


def test_fake_advisory_with_a_backwards_period_is_rejected():
    with pytest.raises(ValueError, match="ends before it starts"):
        Attacker([{**FAKE_SOURCE, "period_start": "2026-06-07", "period_end": "2026-06-01"}])


def test_describe_fake_advisories():
    assert describe(FAKE_FIGURES) == "fake figures posing as Water Corporation on 2026-06-07"
    assert describe(FAKE_SOURCE) == "fake advisory from 'WA Water Watch' on 2026-06-07"
