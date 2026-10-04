"""Tests for detection.py, using small hand-made days instead of the CSV."""
import math
from datetime import date, timedelta

import pytest

import config
from detection import Detector, percent

GAUGES = ["A", "B", "C", "D", "E"]


def day(flow=100.0, **overrides):
    """Build one day of flows where every gauge matches, apart from any overrides."""
    flows = {sid: flow for sid in GAUGES}
    flows.update(overrides)
    return flows


def learning_days(wobble=1.1, jumpy=None, sizes=None):
    """Thirty June days where one gauge at a time reads 10% high, so every gauge learns the same small limits."""
    days = []
    for i in range(30):
        # A tiny steady rise, since real flows never repeat exactly and a repeat would look like a stuck gauge.
        base = 100.0 + 0.01 * i
        flows = {sid: round(base * (sizes or {}).get(sid, 100.0) / 100, 2) for sid in GAUGES}

        # A 7-day cycle (five gauges, then two calm days) so a 10-day drift window never cancels out exactly.
        if i % 7 < 5:
            sid = GAUGES[i % 7]
            flows[sid] = round(flows[sid] * wobble, 2)

        # A jumpy gauge also swings 50% on alternate days, so it should learn a wider limit than the rest.
        if jumpy and i % 2:
            flows[jumpy] = round(flows[jumpy] * 1.5, 2)
        days.append(flows)
    return days


def run(detector, days, start="2026-07-01"):
    """Feed days to the detector from `start`, returning every alert raised."""
    first = date.fromisoformat(start)
    alerts = []
    for i, flows in enumerate(days):
        alerts += detector.check_day((first + timedelta(days=i)).isoformat(), flows)
    return alerts


def flagged(alerts):
    return {(a["sensor"], a["rule"]) for a in alerts}


@pytest.fixture
def detector():
    """A detector that has already learned from a calm June."""
    d = Detector()
    run(d, learning_days(), start="2026-06-01")
    return d


# Learning

def test_nothing_is_flagged_while_learning():
    # June is assumed clean, so even a wild value or a stuck gauge only shapes what's learned.
    days = learning_days()
    days[10]["C"] = 900.0
    for flows in days[14:22]:
        flows["D"] = 50.0
    assert run(Detector(), days, start="2026-06-01") == []


def test_limits_come_from_the_biggest_june_gap(detector):
    run(detector, [day()])

    # Each wobble is a 10% gap, so the jump limit is 1.5 times that, measured in logs.
    expected = config.JUMP_MARGIN * math.log(111 / 101)
    assert detector.jump_limit["A"] == pytest.approx(expected, rel=0.001)


def test_a_jumpy_gauge_learns_a_wider_limit():
    d = Detector()
    run(d, learning_days(jumpy="C"), start="2026-06-01")
    run(d, [day()])

    assert d.jump_limit["C"] > 2 * d.jump_limit["A"]


def test_checks_refuse_to_start_without_learning():
    with pytest.raises(ValueError, match="needs at least 11 days of learning"):
        Detector().check_day("2026-07-01", day())


def test_july_with_the_same_wobble_as_june_is_not_flagged(detector):
    assert run(detector, learning_days()) == []


# Jumps

def test_one_day_spike_is_flagged(detector):
    alerts = run(detector, [day(), day(C=300.0)])
    assert flagged(alerts) == {("C", "jump")}


def test_alert_explains_itself(detector):
    [alert] = run(detector, [day(), day(C=300.0)])

    # 100 to 300 is +200%, and the +1 that lets a dry stream read zero nudges it slightly.
    assert alert["reason"] == "changed +198% vs +0% for the other gauges"
    assert alert["value"] == 300.0


def test_all_gauges_rising_together_is_not_flagged(detector):
    # A storm lifts every stream at once, which is real.
    assert run(detector, [day(), day(300.0)]) == []


def test_gauges_of_different_sizes_rising_by_the_same_share_are_not_flagged():
    # A small brook and a big river both up 50% is the same news, even though one gained 150 ML/day and the other 5.
    sizes = {"A": 10.0, "B": 40.0, "C": 100.0, "D": 200.0, "E": 300.0}
    d = Detector()
    run(d, learning_days(sizes=sizes), start="2026-06-01")

    assert run(d, [sizes, {sid: f * 1.5 for sid, f in sizes.items()}]) == []


def test_small_fake_change_gets_through(detector):
    # A known limitation: a change inside the learned limit (here about +15%) is not caught.
    assert run(detector, [day(), day(C=112.0)]) == []


def test_snapping_back_after_a_spike_is_not_flagged(detector):
    # The spiked value is never trusted, so the next real value is compared with the day before the spike.
    alerts = run(detector, [day(), day(C=300.0), day()])
    assert len(alerts) == 1


def test_lasting_shift_is_flagged_once(detector):
    alerts = run(detector, [day(), day(C=300.0), day(C=300.0), day(C=300.0)])
    assert [a["date"] for a in alerts] == ["2026-07-02"]


def test_faked_dry_stream_is_flagged(detector):
    # Zero flow works with the logs, so a gauge faking a stopped stream is caught rather than crashing.
    alerts = run(detector, [day(), day(C=0.0)])
    assert flagged(alerts) == {("C", "jump")}


# Flatlines

def moving_days(n, stuck=None):
    """Days where every gauge falls 5% a day, with `stuck` frozen at 100 if given."""
    return [{sid: 100.0 if sid == stuck else round(100.0 * 0.95 ** i, 2) for sid in GAUGES} for i in range(n)]


def test_stuck_gauge_is_flagged_once(detector):
    alerts = run(detector, moving_days(8, stuck="D"))
    assert flagged(alerts) == {("D", "flatline")}
    assert alerts[0]["date"] == "2026-07-04"


def test_stuck_while_every_stream_is_steady_is_not_flagged(detector):
    # In a long dry spell every gauge can sit still, and nothing has gone wrong.
    assert run(detector, [day()] * 8) == []


def test_unstuck_gauge_does_not_raise_a_jump(detector):
    days = moving_days(6, stuck="D") + moving_days(8)[6:]
    alerts = run(detector, days)
    assert flagged(alerts) == {("D", "flatline")}


# Drift

def drifting_days(n, rate):
    """Days where gauge B creeps up by `rate` (e.g. 0.05 for 5%) more each day than the others."""
    return [day(B=round(100.0 * (1 + rate) ** (i + 1), 2)) for i in range(n)]


def test_slow_drift_is_flagged(detector):
    # Each step stays well inside the jump limit, but they add up.
    alerts = run(detector, drifting_days(14, 0.05))
    assert flagged(alerts) == {("B", "drift")}
    assert alerts[0]["reason"].startswith("drifted +")


def test_drifting_gauge_is_only_flagged_once(detector):
    alerts = run(detector, drifting_days(20, 0.05))
    assert len(alerts) == 1


def test_drifting_gauge_is_released_once_back_in_line(detector):
    # After the snap-back, the same gauge drifting again later is a new alert.
    days = drifting_days(10, 0.05) + [day()] * 12 + drifting_days(10, 0.05)
    alerts = run(detector, days)
    assert [a["rule"] for a in alerts] == ["drift", "drift"]


def test_very_slow_drift_gets_through(detector):
    # A known limitation: 1% a day stays inside the learned drift limit for the 10-day window.
    assert run(detector, drifting_days(20, 0.01)) == []


# Percentages

@pytest.mark.parametrize("log_change, text", [(0.0, "+0%"), (math.log(2), "+100%"), (math.log(0.5), "-50%")])
def test_percent_turns_logs_into_plain_changes(log_change, text):
    assert percent(log_change) == text
