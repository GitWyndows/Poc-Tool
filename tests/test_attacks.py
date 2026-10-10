"""Tests for attacks.py: the right flow is changed, fake advisories go out, everything is logged, and scoring is fair."""
import pytest

import config
from advisories import make_advisory
from attacks import Attacker, attack_dates, day_after, describe, score, tampered_advisories

SPIKE = {"type": "spike", "sensor": "608171", "date": "2026-07-15", "factor": 3.0}

FLATLINE = {"type": "flatline", "sensor": "608002", "start": "2026-07-22", "days": 3}

DRIFT = {"type": "drift", "sensor": "607022", "start": "2026-08-08", "days": 3, "rate": 0.10}

FAKE_FIGURES = {"type": "fake_figures", "date": "2026-07-07", "source": "Water Corporation",
                "avg_flow_ml": 40.0, "change_pct": -65}

FAKE_SOURCE = {"type": "fake_source", "date": "2026-07-07", "source": "WA Water Watch"}

COORDINATED = {"type": "coordinated", "sensors": ["607022", "607013"], "start": "2026-07-20", "days": 3, "rate": 0.10}

STALE = {"type": "stale_advisory", "date": "2026-07-14", "weeks_old": 1}


def week_of_readings():
    """Seven July days where five gauges carry 20 to 26 ML/day, so combined flow averages 115 and rises 30%."""
    return {f"2026-07-{i + 1:02d}": {f"G{g}": 20.0 + i for g in range(5)} for i in range(7)}


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
    ({**FAKE_FIGURES, "date": "2026-06-28"}, "after the learning period"),
    ({k: v for k, v in FAKE_FIGURES.items() if k != "change_pct"}, "missing 'change_pct'"),
    ({**FAKE_SOURCE, "source": config.APPROVED_SOURCES[0]}, "is an approved source"),
    ({**COORDINATED, "sensors": ["607022"]}, "needs at least two different gauges"),
    ({**COORDINATED, "sensors": ["607022", "S9"]}, "'S9' is not one of the gauges"),
    ({**STALE, "date": "2026-07-01", "weeks_old": 4}, "starts before 2026-06-01"),
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


# Fake advisories

def test_fake_figures_quotes_made_up_numbers_under_an_approved_name():
    [fake] = Attacker([FAKE_FIGURES]).fake_advisories("2026-07-07", week_of_readings())

    assert fake["source"] == "Water Corporation"
    assert (fake["avg_flow_ml"], fake["change_pct"]) == (40.0, -65)
    assert (fake["period_start"], fake["period_end"]) == ("2026-07-01", "2026-07-07")


def test_fake_figures_log_shows_the_real_figures_too():
    attacker = Attacker([FAKE_FIGURES])
    attacker.fake_advisories("2026-07-07", week_of_readings())

    entry = attacker.log[0]
    assert entry["sensor"] == "ADV-F1"
    assert (entry["real"], entry["fake"]) == ((115.0, 30), (40.0, -65))


def test_fake_source_copies_the_real_figures():
    [fake] = Attacker([FAKE_SOURCE]).fake_advisories("2026-07-07", week_of_readings())

    assert fake["source"] == "WA Water Watch"
    assert (fake["avg_flow_ml"], fake["change_pct"]) == (115.0, 30)


def test_fake_advisories_only_go_out_on_their_date():
    attacker = Attacker([FAKE_FIGURES])
    assert attacker.fake_advisories("2026-07-06", week_of_readings()) == []
    assert attacker.log == []


def test_advisory_attacks_leave_readings_alone():
    attacker = Attacker([FAKE_FIGURES, FAKE_SOURCE])
    assert attacker.apply("608171", "2026-07-07", 33.32) == 33.32


def test_describe_fake_advisories():
    assert describe(FAKE_FIGURES) == "fake figures posing as Water Corporation on 2026-07-07"
    assert describe(FAKE_SOURCE) == "fake advisory from 'WA Water Watch' on 2026-07-07"


# Coordinated drift

def test_coordinated_drift_moves_every_listed_gauge_the_same_way():
    attacker = Attacker([COORDINATED])
    seen = {sid: [attacker.apply(sid, d, 100.0) for d in attack_dates(COORDINATED)] for sid in ("607022", "607013")}

    assert seen == {"607022": [110.0, 121.0, 133.1], "607013": [110.0, 121.0, 133.1]}
    assert attacker.apply("608171", "2026-07-20", 50.0) == 50.0
    assert len(attacker.log) == 6


def test_describe_coordinated_drift():
    assert describe(COORDINATED) == "coordinated drift on 607022, 607013 of +10% a day from 2026-07-20 to 2026-07-22"


# Stale advisories

def two_weeks_of_readings():
    """Fourteen July days where combined flow is 100 ML/day in the first week and 200 in the second."""
    return {f"2026-07-{i + 1:02d}": {f"G{g}": 20.0 if i < 7 else 40.0 for g in range(5)} for i in range(14)}


def test_stale_advisory_reuses_an_old_week_under_the_genuine_source():
    [stale] = Attacker([STALE]).fake_advisories("2026-07-14", two_weeks_of_readings())

    # Published on 14 July but describing 1-7 July, with that week's genuine figures and the approved source.
    assert (stale["published"], stale["period_start"], stale["period_end"]) == ("2026-07-14", "2026-07-01", "2026-07-07")
    assert (stale["avg_flow_ml"], stale["source"]) == (100.0, config.APPROVED_SOURCES[0])


def test_describe_stale_advisory():
    assert describe(STALE) == "stale advisory reusing a week from 1 weeks earlier on 2026-07-14"


# Advisories built on tampered readings

def test_tampered_advisories_lists_only_notices_that_differ_from_the_real_readings():
    real = week_of_readings()
    honest = make_advisory("ADV-01", "2026-07-07", "2026-07-01", "2026-07-07", "Water Corporation", 115.0, 0.30)
    inflated = make_advisory("ADV-02", "2026-07-07", "2026-07-01", "2026-07-07", "Water Corporation", 150.0, 0.30)

    [(advisory, flow, change)] = tampered_advisories([honest, inflated], real)
    assert advisory["id"] == "ADV-02"
    assert (flow, change) == pytest.approx((115.0, 0.30))


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


def test_flagged_fake_advisory_counts_as_caught():
    attacker = Attacker([FAKE_SOURCE])
    attacker.fake_advisories("2026-07-07", week_of_readings())
    caught, _, _, false = score([alert("2026-07-07", "ADV-F1")], attacker)
    assert (caught, false) == ([FAKE_SOURCE], [])


def test_unflagged_fake_advisory_is_missed():
    attacker = Attacker([FAKE_SOURCE])
    attacker.fake_advisories("2026-07-07", week_of_readings())
    _, _, missed, _ = score([], attacker)
    assert missed == [FAKE_SOURCE]


def test_coordinated_drift_is_caught_by_an_alert_on_any_of_its_gauges():
    attacker = Attacker([COORDINATED])
    for sid in COORDINATED["sensors"]:
        for d in attack_dates(COORDINATED):
            attacker.apply(sid, d, 50.0)

    caught, _, _, false = score([alert("2026-07-21", "607013")], attacker)
    assert (caught, false) == ([COORDINATED], [])


def test_flagged_stale_advisory_counts_as_caught():
    attacker = Attacker([STALE])
    attacker.fake_advisories("2026-07-14", two_weeks_of_readings())
    caught, _, _, _ = score([alert("2026-07-14", "ADV-F1")], attacker)
    assert caught == [STALE]
