"""Tests for attacks.py: the right value is changed, and every change is logged."""

import pytest
from attacks import Attacker

PLAN = [
    {"sensor": "S3", "date": "2026-06-13", "field": "rainfall_mm", "value": 80.0},
    {"sensor": "S5", "date": "2026-08-10", "field": "river_level_m", "value": 3.20},
]


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
        "date": "2026-06-13",
        "sensor": "S3",
        "field": "rainfall_mm",
        "real": 0.0,
        "fake": 80.0,
    }]


def test_misspelt_field_fails_straight_away():
    bad_plan = [{"sensor": "S3", "date": "2026-06-13", "field": "rainfal_mm", "value": 80.0}]
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
