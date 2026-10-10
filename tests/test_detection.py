"""Tests for detection.py, using small hand-made days instead of the CSV."""
import math
from datetime import date, timedelta

import pytest

import config
from advisories import AdvisoryWriter, make_advisory
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


# Advisories

def seen_week(detector):
    """Feed the detector a week of July flows, rising 1 ML/day per gauge, as if checks were running."""
    for i in range(7):
        detector.readings_by_date[f"2026-07-{i + 1:02d}"] = {sid: 20.0 + i for sid in GAUGES}


def advisory(source="Water Corporation", flow=115.0, change=0.30, start="2026-07-01", end="2026-07-07"):
    """An advisory for 1-7 July whose figures match seen_week, unless told otherwise."""
    return make_advisory("ADV-01", end, start, end, source, flow, change)


def test_genuine_advisory_raises_nothing():
    detector = Detector()
    seen_week(detector)
    assert detector.check_advisory(advisory()) == []


def test_every_advisory_the_writer_publishes_passes():
    # The writer and the checker must agree, or every genuine notice would be a false alarm.
    detector, writer = Detector(), AdvisoryWriter()
    run(detector, learning_days(), start="2026-06-01")
    for d, flows in detector.readings_by_date.items():
        published = writer.record(d, flows)
        if published:
            assert detector.check_advisory(published) == []


def test_unapproved_source_is_flagged_even_with_real_figures():
    detector = Detector()
    seen_week(detector)
    [alert] = detector.check_advisory(advisory(source="WA Water Watch"))

    assert alert["rule"] == "advisory" and alert["sensor"] == "ADV-01"
    assert alert["reason"] == "source 'WA Water Watch' is not approved"


def test_wrong_flow_is_flagged():
    detector = Detector()
    seen_week(detector)
    [alert] = detector.check_advisory(advisory(flow=60.0))
    assert alert["reason"] == "claims 60.0 ML/day vs 115.0 ML/day in the readings"


def test_wrong_change_is_flagged():
    detector = Detector()
    seen_week(detector)
    [alert] = detector.check_advisory(advisory(change=-0.40))
    assert alert["reason"] == "claims a -40% change vs +30% in the readings"


def test_several_problems_give_one_alert():
    detector = Detector()
    seen_week(detector)
    [alert] = detector.check_advisory(advisory(source="WA Water Watch", flow=60.0, change=-0.40))
    assert alert["reason"].count(";") == 2


def test_rounding_is_allowed_for():
    # A notice quotes 1 decimal place and whole percentages, which mustn't count as a lie.
    detector = Detector()
    seen_week(detector)
    assert detector.check_advisory(advisory(flow=115.04, change=0.304)) == []


def test_advisory_for_a_period_with_no_readings_is_flagged():
    detector = Detector()
    seen_week(detector)
    [alert] = detector.check_advisory(advisory(start="2026-08-01", end="2026-08-07"))
    assert alert["reason"] == "no readings exist for the period it describes"


def test_advisory_built_from_tampered_readings_passes():
    # A known limitation: if the gauges were tampered with, an honest notice repeats the lie and still matches.
    detector = Detector()
    seen_week(detector)
    detector.readings_by_date["2026-07-04"]["C"] = 500.0
    tampered = AdvisoryWriter()
    published = [tampered.record(d, flows) for d, flows in sorted(detector.readings_by_date.items())][-1]

    assert published is not None
    assert detector.check_advisory(published) == []


# Reference period

def test_advisory_covering_the_wrong_number_of_days_is_flagged():
    detector = Detector()
    seen_week(detector)
    [alert] = detector.check_advisory(advisory(start="2026-07-02", end="2026-07-07"))
    assert "covers 6 days instead of 7" in alert["reason"]


def test_advisory_describing_days_after_it_was_published_is_flagged():
    detector = Detector()
    seen_week(detector)
    early = make_advisory("ADV-01", "2026-07-05", "2026-07-01", "2026-07-07", "Water Corporation", 115.0, 0.30)
    [alert] = detector.check_advisory(early)
    assert alert["reason"] == "describes days up to 2026-07-07, after it was published"


def test_old_week_passed_off_as_current_is_flagged():
    # The figures are right for their week, so only the dates give a recycled notice away.
    detector = Detector()
    seen_week(detector)
    stale = make_advisory("ADV-01", "2026-07-21", "2026-07-01", "2026-07-07", "Water Corporation", 115.0, 0.30)
    [alert] = detector.check_advisory(stale)
    assert alert["reason"] == "published 14 days after its week ended"


def test_advisory_a_day_late_is_allowed():
    detector = Detector()
    seen_week(detector)
    late = make_advisory("ADV-01", "2026-07-08", "2026-07-01", "2026-07-07", "Water Corporation", 115.0, 0.30)
    assert detector.check_advisory(late) == []


# Upstream and downstream pairs

def calm(n, start=0):
    """Days where every gauge carries the same flow, rising very slightly so no gauge ever looks stuck."""
    return [day(round(100.0 + 0.01 * (start + i), 2)) for i in range(n)]


@pytest.fixture
def paired(monkeypatch):
    """A detector that treats A as downstream of B, and has learned from a calm June and ten calm July days."""
    monkeypatch.setattr(config, "PAIRS", [("A", "B")])
    d = Detector()
    run(d, learning_days(), start="2026-06-01")
    run(d, calm(10))
    return d


def run_on(detector, days, start="2026-07-11"):
    """Carry on from the paired fixture's last day."""
    return run(detector, days, start)


def apart(i):
    """Day `i` after the fixture, with A up 14% and B down 10% on the others."""
    flows = calm(1, start=10 + i)[0]
    return {**flows, "A": round(flows["A"] * 1.14, 2), "B": round(flows["B"] * 0.90, 2)}


def test_pair_pushed_out_of_range_blames_the_gauge_that_moved(paired):
    # A rises 14% and B falls 10%: each change is inside the jump limit, but together they break the pair's ratio.
    [alert] = run_on(paired, [apart(0)])

    assert (alert["sensor"], alert["rule"]) == ("A", "pair")
    assert alert["reason"].startswith("downstream A carries 1.27x the flow of upstream B, outside the")


def test_pair_a_little_past_the_june_range_is_allowed(paired):
    # June's ratio swung about 10% either way, so 5% each way (about 11% apart) is just past it but inside the margin.
    flows = calm(1, start=10)[0]
    nudged = {**flows, "A": round(flows["A"] * 1.05, 2), "B": round(flows["B"] * 0.95, 2)}
    assert run_on(paired, [nudged]) == []


def test_pair_is_flagged_once_until_it_returns_to_range(paired):
    days = [apart(0), apart(1), apart(2)] + calm(2, start=13) + [apart(5)]
    alerts = run_on(paired, days)
    assert [a["date"] for a in alerts if a["rule"] == "pair"] == ["2026-07-11", "2026-07-16"]


def test_pair_stays_quiet_when_another_rule_already_flagged_the_gauge(paired):
    alerts = run_on(paired, [{**calm(1, start=10)[0], "A": 300.0}])
    assert [a["rule"] for a in alerts] == ["jump"]


def test_pair_stays_quiet_on_ordinary_days(monkeypatch):
    monkeypatch.setattr(config, "PAIRS", [("A", "B")])
    d = Detector()
    run(d, learning_days(), start="2026-06-01")
    assert run(d, learning_days()) == []
