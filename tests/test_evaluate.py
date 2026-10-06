"""Tests for evaluate.py, using a few scenarios at a time so they stay quick."""
import sys

import pytest

import config
import evaluate
from main import load_sensors


@pytest.fixture(scope="module")
def data():
    """The real gauges and dates, loaded once for every test here."""
    return load_sensors()


def only(*labels):
    """Just the named scenarios from the full list."""
    return [s for s in evaluate.SCENARIOS if s[0] in labels]


def run(data, *labels, by_gauge=False):
    """Evaluate just the named scenarios on the real data."""
    sensors, dates = data
    return evaluate.evaluate(sensors, dates, only(*labels), by_gauge)


def test_every_run_ends_up_caught_late_or_missed(data):
    rows = run(data, "spike x1.5", "drift +5% a day, 14 days")

    for t in rows.values():
        assert t["caught"] + t["late"] + t["missed"] == t["runs"]

    # Slow drift is the attack most often noticed only at the snap-back, so it must show up as late, not caught.
    drift = rows["drift +5% a day, 14 days"]
    assert drift["late"] > drift["caught"]


def test_runs_cover_every_gauge_and_every_start_date_that_fits(data):
    rows = run(data, "spike x3", "flatline 7 days", "fake source")

    # 62 July and August days for a spike, 56 that leave room for a 7-day flatline, and advisories have no gauge.
    assert rows["spike x3"]["runs"] == 62 * 5
    assert rows["flatline 7 days"]["runs"] == 56 * 5
    assert rows["fake source"]["runs"] == 62


def test_big_spikes_and_fake_advisories_are_always_caught(data):
    rows = run(data, "spike x3", "fake figures, flow 1% low", "fake source")

    for t in rows.values():
        assert t["caught"] == t["runs"]


def test_by_gauge_gives_one_row_per_gauge(data):
    rows = run(data, "spike x3", "fake source", by_gauge=True)

    assert list(rows) == [f"spike x3  ({sid})" for sid, _ in config.SENSORS] + ["fake source"]
    assert all(t["runs"] == 62 for t in rows.values())


def test_fake_figures_understate_the_real_week(data):
    sensors, dates = data
    clean = {day: {s.id: s.read(day) for s in sensors} for day in dates}
    attack = evaluate.make_attack("fake_figures", {"understate": 0.30}, "-", "2026-07-19", clean)

    # The real week of 13-19 July averaged 370.7 ML/day, so 30% low is about 259.5.
    assert attack["avg_flow_ml"] == pytest.approx(370.73 * 0.7, abs=0.01)
    assert attack["source"] in config.APPROVED_SOURCES


def test_clean_replay_has_no_false_alarms(data):
    sensors, dates = data
    (caught, late, missed, false_alarms), advisories = evaluate.replay(sensors, dates, [])
    assert (caught, late, missed, false_alarms) == ([], [], [], [])
    assert advisories == 13


def test_main_prints_the_clean_line_and_a_row_per_scenario(monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "SCENARIOS", only("spike x3", "fake source"))
    monkeypatch.setattr(sys, "argv", ["evaluate.py"])
    evaluate.main()
    out = capsys.readouterr().out

    assert "Clean data: 0 false alarm(s) in 310 gauge-days and 13 advisories checked" in out
    assert "spike x3" in out and "fake source" in out
    assert out.count("100%") == 2
