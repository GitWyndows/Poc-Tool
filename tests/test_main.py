"""Tests for main.py: strict loading of the streamflow CSV, printing it, checking it, and scoring attacks."""
import sys

import pytest

import config
import main

IDS = [sid for sid, _ in config.SENSORS]


def write_csv(tmp_path, monkeypatch, rows, header="date,sensor_id,flow_ml"):
    """Write a CSV to a temporary folder and point the tool at it, so tests never touch the real file."""
    path = tmp_path / "flow.csv"
    path.write_text("\n".join([header] + rows) + "\n")
    monkeypatch.setattr(config, "DATA_FILE", path)
    return path


def full_rows(skip=None, flow="10.0"):
    """One row per gauge per replay day, leaving out the (date, gauge) in `skip`."""
    return [f"{d},{sid},{flow}" for d in main.replay_dates() for sid in IDS if (d, sid) != skip]


def problems(exc):
    """The message a load stopped with."""
    return str(exc.value)


# The real file

def test_real_file_loads_every_gauge_and_day():
    sensors, dates = main.load_sensors()

    assert [s.id for s in sensors] == IDS
    assert dates[0] == config.START_DATE and dates[-1] == config.END_DATE
    assert len(dates) == 92
    assert all(s.read(d) is not None for s in sensors for d in dates)


def test_real_file_values_match_dwer():
    # Spot checks read straight from DWER's export.
    sensors = {s.id: s for s in main.load_sensors()[0]}
    assert sensors["607022"].read("2026-06-01") == 66.35
    assert sensors["608171"].read("2026-08-11") == 163.6
    assert sensors["608151"].read("2026-08-31") == 171.4


# Strict loading

def test_complete_file_loads(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, full_rows())
    sensors, dates = main.load_sensors()
    assert sensors[0].read(dates[0]) == 10.0


def test_missing_file_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_FILE", tmp_path / "nope.csv")
    with pytest.raises(SystemExit, match="No data found"):
        main.load_sensors()


def test_wrong_header_stops(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, full_rows(), header="date,sensor_id,rainfall_mm,river_level_m")
    with pytest.raises(SystemExit, match="must start with the header date,sensor_id,flow_ml"):
        main.load_sensors()


def test_missing_day_stops(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, full_rows(skip=("2026-07-16", "607013")))
    with pytest.raises(SystemExit, match="607013 is missing 1 day"):
        main.load_sensors()


def test_repeated_day_stops(tmp_path, monkeypatch):
    rows = full_rows()
    write_csv(tmp_path, monkeypatch, rows + [rows[0]])
    with pytest.raises(SystemExit, match="appears more than once"):
        main.load_sensors()


def test_unknown_gauge_stops(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, full_rows() + ["2026-06-01,610001,5.0"])
    with pytest.raises(SystemExit, match="gauge '610001' is not one of the gauges"):
        main.load_sensors()


@pytest.mark.parametrize("bad_row, message", [
    ("2026-06-01,607022,lots", "is not a number"),
    ("2026-06-01,607022,-3", "zero or more"),
    ("2026-06-01,607022,nan", "zero or more"),
    ("2026-06-31,607022,5.0", "not a real date"),
    ("2026-09-01,607022,5.0", "not a real date"),
    ("2026-06-01,607022", "columns instead of 3"),
])
def test_bad_rows_are_reported_with_their_line(tmp_path, monkeypatch, bad_row, message):
    write_csv(tmp_path, monkeypatch, full_rows(skip=("2026-06-01", "607022")) + [bad_row])
    with pytest.raises(SystemExit) as exc:
        main.load_sensors()

    assert message in problems(exc)
    assert "line 461" in problems(exc)


def test_long_lists_of_problems_are_cut_short(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, full_rows(flow="oops"))
    with pytest.raises(SystemExit) as exc:
        main.load_sensors()

    assert "has 465 problem(s)" in problems(exc)
    assert "...and 455 more" in problems(exc)


def test_zero_flow_is_allowed(tmp_path, monkeypatch):
    # A stream that stops flowing reads zero, which is real data rather than an error.
    write_csv(tmp_path, monkeypatch, full_rows(flow="0.000"))
    sensors, dates = main.load_sensors()
    assert sensors[0].read(dates[0]) == 0.0


# Printing

def flows_on(sensors, day):
    """Each gauge's real flow on one day, as the detector would see it with no attacks."""
    return {s.id: s.read(day) for s in sensors}


def test_print_day_shows_every_gauge_and_its_flow(capsys):
    sensors, dates = main.load_sensors()
    main.print_day(1, dates[0], sensors, flows_on(sensors, dates[0]), [])
    out = capsys.readouterr().out

    assert "Day 1  |  2026-06-01  |  learning" in out
    assert all(sid in out for sid in IDS)
    assert "Lefroy Brook - Cascades" in out and "66.35" in out


def test_print_day_shows_the_flows_as_seen_and_marks_alerts(capsys):
    sensors, _ = main.load_sensors()
    flows = {**flows_on(sensors, "2026-07-15"), "608171": 99.96}
    alert = {"date": "2026-07-15", "sensor": "608171", "rule": "jump", "value": 99.96, "reason": "changed +152%"}
    main.print_day(45, "2026-07-15", sensors, flows, [alert])
    out = capsys.readouterr().out

    assert "Day 45  |  2026-07-15\n" in out
    assert "99.96  <-- ALERT" in out
    assert "ALERT 608171 jump: changed +152%" in out


def test_days_option_limits_the_output(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--days", "3"])
    main.main()
    out = capsys.readouterr().out

    assert "Day 3  |  2026-06-03" in out
    assert "Day 4" not in out
    assert "Still learning, so nothing was checked" in out


def test_full_run_shows_all_92_days(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py"])
    main.main()
    out = capsys.readouterr().out

    assert "Day 92  |  2026-08-31" in out
    assert out.startswith("Streamflow from 5 DWER gauges, 2026-06-01 to 2026-08-31")


def test_clean_real_data_raises_no_alerts(monkeypatch, capsys):
    # The real readings are untampered, so every alert here would be a false alarm.
    monkeypatch.setattr(sys, "argv", ["main.py"])
    main.main()
    out = capsys.readouterr().out

    assert "ALERT" not in out
    assert "False alarms:    0" in out
    assert "Limits learned from 2026-06-01 to 2026-06-30" in out
    assert "ATTACK LOG" not in out


# Attacks

def test_attack_run_logs_and_scores_the_planned_attacks(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--attack"])
    main.main()
    out = capsys.readouterr().out

    # The planned attacks are chosen to show both what the detector catches and where it falls short.
    assert "spike on 608171 of x3.0 on 2026-07-15: real 33.32 -> fake 99.96 ML/day" in out
    assert "Attacks caught:  4 of 6" in out
    assert "LATE         drift on 608151" in out
    assert "MISSED       spike on 608002 of x1.5" in out
    assert "False alarms:    0" in out


def test_attacks_after_the_days_shown_are_reported_as_skipped(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--attack", "--days", "50"])
    main.main()
    out = capsys.readouterr().out

    assert "Skipped: spike on 607013 of x0.5 on 2026-08-05 falls outside the days shown." in out
    assert "Attacks caught:  1 of 1" in out


def test_bad_attack_plan_stops_before_anything_runs(monkeypatch):
    monkeypatch.setattr(config, "ATTACKS", [{"type": "spike", "sensor": "S3", "date": "2026-07-15", "factor": 3.0}])
    monkeypatch.setattr(sys, "argv", ["main.py", "--attack"])
    with pytest.raises(ValueError, match="'S3' is not one of the gauges"):
        main.main()
