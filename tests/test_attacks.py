"""Tests for attacks.py: the right value is changed, and every change is logged."""
import pytest

from attacks import Attacker, attack_dates, describe

PLAN = [
    {"type": "spike", "sensor": "S3", "date": "2026-06-13", "field": "rainfall_mm", "value": 80.0},
    {"type": "spike", "sensor": "S5", "date": "2026-08-10", "field": "river_level_m", "value": 3.20},
]

FLATLINE = {"type": "flatline", "sensor": "S7", "start": "2026-06-26", "days": 3, "field": "river_level_m"}


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
