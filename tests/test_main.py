"""Tests for main.py: loading, printing, scoring, and full runs from start to finish."""
import sys

import pytest

import config
import generate_data
import main
from attacks import Attacker
from detection import Detector


@pytest.fixture
def data_file(tmp_path, monkeypatch):
    """Generate a fresh CSV in a temporary folder, so tests never touch the real data file."""
    path = tmp_path / "readings.csv"
    monkeypatch.setattr(config, "DATA_FILE", path)
    generate_data.main()
    return path


def run(monkeypatch, capsys, *args):
    """Run main.py with the given options and return what it printed."""
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    main.main()
    return capsys.readouterr().out


# Loading

def test_load_sensors_reads_every_sensor_and_day(data_file):
    sensors, dates = main.load_sensors()

    assert len(sensors) == 8
    assert len(dates) == config.NUM_DAYS
    assert dates[0] == config.START_DATE


def test_missing_csv_stops_with_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_FILE", tmp_path / "missing.csv")
    with pytest.raises(SystemExit, match="generate_data.py"):
        main.load_sensors()


def test_unknown_sensor_rows_are_ignored(tmp_path, monkeypatch):
    path = tmp_path / "readings.csv"
    path.write_text("date,sensor_id,rainfall_mm,river_level_m\n"
                    "2026-06-01,S1,1.0,1.20\n"
                    "2026-06-01,S99,5.0,9.99\n")
    monkeypatch.setattr(config, "DATA_FILE", path)

    sensors, dates = main.load_sensors()
    assert dates == ["2026-06-01"]
    assert all(s.id != "S99" for s in sensors)


# Printing a day

def test_print_day_marks_the_flagged_sensor(data_file, capsys):
    sensors, _ = main.load_sensors()
    attacker = Attacker(config.ATTACKS)

    alerts = main.print_day(13, "2026-06-13", sensors, attacker, Detector())
    out = capsys.readouterr().out

    assert [a["sensor"] for a in alerts] == ["S3"]
    assert "80.0" in out and "<-- ALERT" in out


# Scoring

def test_score_counts_caught_missed_and_false_alarms(capsys):
    attacker = Attacker([
        {"type": "spike", "sensor": "S1", "date": "d1", "field": "rainfall_mm", "value": 50.0},
        {"type": "spike", "sensor": "S2", "date": "d2", "field": "rainfall_mm", "value": 50.0},
    ])
    attacker.apply("S1", "d1", (0.0, 1.0))
    attacker.apply("S2", "d2", (0.0, 1.0))

    # One real catch, and one alert on a sensor that was never attacked.
    alerts = [
        {"date": "d1", "sensor": "S1", "field": "rainfall_mm"},
        {"date": "d3", "sensor": "S4", "field": "rainfall_mm"},
    ]
    main.print_score(alerts, attacker)
    out = capsys.readouterr().out

    assert "Attacks caught:  1 of 2" in out
    assert "Attacks missed:  1" in out
    assert "False alarms:    1" in out


def test_right_sensor_wrong_field_is_not_a_catch(capsys):
    attacker = Attacker([{"type": "spike", "sensor": "S1", "date": "d1", "field": "rainfall_mm", "value": 50.0}])
    attacker.apply("S1", "d1", (0.0, 1.0))

    main.print_score([{"date": "d1", "sensor": "S1", "field": "river_level_m"}], attacker)
    assert "Attacks caught:  0 of 1" in capsys.readouterr().out


# Full runs

def test_clean_run_has_no_false_alarms(data_file, monkeypatch, capsys):
    out = run(monkeypatch, capsys)
    assert "False alarms:    0" in out
    assert "ATTACK LOG" not in out


def test_attack_run_catches_every_planned_attack(data_file, monkeypatch, capsys):
    out = run(monkeypatch, capsys, "--attack")
    total = len(config.ATTACKS)

    assert f"Attacks caught:  {total} of {total}" in out
    assert "False alarms:    0" in out


def test_short_run_marks_later_attacks_as_skipped(data_file, monkeypatch, capsys):
    out = run(monkeypatch, capsys, "--attack", "--days", "20")

    assert "Skipped:" in out
    assert "WARNING" not in out


def test_wrong_sensor_id_in_plan_gives_a_warning(data_file, monkeypatch, capsys):
    bad_plan = [{"type": "spike", "sensor": "S99", "date": "2026-06-13", "field": "rainfall_mm", "value": 80.0}]
    monkeypatch.setattr(config, "ATTACKS", bad_plan)

    out = run(monkeypatch, capsys, "--attack")
    assert "WARNING: spike on S99" in out


def test_flatline_counts_as_one_caught_attack(data_file, monkeypatch, capsys):
    plan = [{"type": "flatline", "sensor": "S7", "start": "2026-06-26", "days": 7, "field": "river_level_m"}]
    monkeypatch.setattr(config, "ATTACKS", plan)

    out = run(monkeypatch, capsys, "--attack")
    assert "frozen at 2.68 m for 7 days" in out
    assert "Attacks caught:  1 of 1" in out
    assert "False alarms:    0" in out
