"""Tests for attacks.py: the right flow is changed, every change is logged, and scoring marks alerts fairly."""
import pytest

from attacks import Attacker, attack_dates, day_after, describe, score

SPIKE = {"type": "spike", "sensor": "608171", "date": "2026-07-15", "factor": 3.0}

FLATLINE = {"type": "flatline", "sensor": "608002", "start": "2026-07-22", "days": 3}

DRIFT = {"type": "drift", "sensor": "607022", "start": "2026-08-08", "days": 3, "rate": 0.10}


def alert(day, sensor):
    """Just the parts of an alert that scoring looks at."""
    return {"date": day, "sensor": sensor}


# Spikes

def test_spike_multiplies_the_real_flow():
    assert Attacker([SPIKE]).apply("608171", "2026-07-15", 33.32) == 99.96


def test_untargeted_readings_pass_through_unchanged():
    attacker = Attacker([SPIKE])

    # Right gauge on the wrong day, and the wrong gauge on the right day.
    assert attacker.apply("608171", "2026-07-16", 30.0) == 30.0
    assert attacker.apply("608002", "2026-07-15", 20.0) == 20.0
    assert attacker.log == []


def test_log_records_real_and_fake_values():
    attacker = Attacker([SPIKE])
    attacker.apply("608171", "2026-07-15", 33.32)

    assert attacker.log == [{"attack": 0, "type": "spike", "date": "2026-07-15",
                             "sensor": "608171", "real": 33.32, "fake": 99.96}]


def test_empty_plan_changes_nothing():
    attacker = Attacker([])
    assert attacker.apply("608171", "2026-07-15", 33.32) == 33.32
    assert attacker.log == []


# Checking the plan

@pytest.mark.parametrize("bad, message", [
    ({"type": "wobble", "sensor": "608171", "date": "2026-07-15"}, "Unknown attack type 'wobble'"),
    ({"type": "spike", "sensor": "608171", "date": "2026-07-15"}, "missing 'factor'"),
    ({**SPIKE, "sensor": "S3"}, "'S3' is not one of the gauges"),
    ({**SPIKE, "date": "2026-06-20"}, "after the learning period"),
    ({**FLATLINE, "start": "2026-08-30"}, "after the learning period"),
])
def test_bad_plans_fail_straight_away(bad, message):
    with pytest.raises(ValueError, match=message):
        Attacker([bad])


# Flatlines

def test_flatline_covers_the_right_dates():
    assert attack_dates(FLATLINE) == ["2026-07-22", "2026-07-23", "2026-07-24"]


def test_flatline_repeats_the_first_day_value():
    attacker = Attacker([FLATLINE])
    seen = [attacker.apply("608002", d, flow) for d, flow in zip(attack_dates(FLATLINE), [18.01, 17.2, 16.9])]

    assert seen == [18.01, 18.01, 18.01]
    assert [(e["real"], e["fake"]) for e in attacker.log] == [(18.01, 18.01), (17.2, 18.01), (16.9, 18.01)]


def test_flatline_stops_after_its_last_day():
    attacker = Attacker([FLATLINE])
    for d in attack_dates(FLATLINE):
        attacker.apply("608002", d, 18.01)

    assert attacker.apply("608002", "2026-07-25", 15.0) == 15.0


# Drift

def test_drift_adds_the_same_percentage_on_top_each_day():
    attacker = Attacker([DRIFT])
    seen = [attacker.apply("607022", d, 100.0) for d in attack_dates(DRIFT)]

    assert seen == [110.0, 121.0, 133.1]


def test_drift_stops_after_its_last_day():
    attacker = Attacker([DRIFT])
    for d in attack_dates(DRIFT):
        attacker.apply("607022", d, 100.0)

    assert attacker.apply("607022", "2026-08-11", 100.0) == 100.0


def test_day_after_is_the_snap_back_date():
    assert day_after(DRIFT) == "2026-08-11"
    assert day_after(SPIKE) == "2026-07-16"


def test_describe_gives_a_readable_summary():
    assert describe(SPIKE) == "spike on 608171 of x3.0 on 2026-07-15"
    assert describe(FLATLINE) == "flatline on 608002 from 2026-07-22 to 2026-07-24"
    assert describe(DRIFT) == "drift on 607022 of +10% a day from 2026-08-08 to 2026-08-10"


# Scoring

def attacked(*plan):
    """An attacker that has run every attack in the plan over its dates."""
    attacker = Attacker(list(plan))
    for attack in plan:
        for d in attack_dates(attack):
            attacker.apply(attack["sensor"], d, 50.0)
    return attacker


def test_alert_during_the_attack_counts_as_caught():
    caught, late, missed, false = score([alert("2026-08-09", "607022")], attacked(DRIFT))
    assert (caught, late, missed, false) == ([DRIFT], [], [], [])


def test_alert_on_the_snap_back_day_counts_as_late_not_false():
    caught, late, missed, false = score([alert("2026-08-11", "607022")], attacked(DRIFT))
    assert (caught, late, missed, false) == ([], [DRIFT], [], [])


def test_attack_with_no_alert_is_missed():
    caught, late, missed, false = score([], attacked(SPIKE))
    assert (caught, late, missed, false) == ([], [], [SPIKE], [])


def test_alert_on_the_wrong_gauge_is_a_false_alarm():
    # The right day isn't enough; an alert on an untouched gauge points the defender at the wrong place.
    caught, late, missed, false = score([alert("2026-07-15", "607013")], attacked(SPIKE))
    assert (missed, false) == ([SPIKE], [("2026-07-15", "607013")])


def test_one_alert_catches_a_long_attack_once():
    alerts = [alert(d, "608002") for d in attack_dates(FLATLINE)]
    caught, _, _, false = score(alerts, attacked(FLATLINE, SPIKE))
    assert (caught, false) == ([FLATLINE], [])
