"""Tests for detection.py, using small hand-made days instead of the CSV."""
import config

from detection import Detector

SENSORS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]


def day(rain, level=1.0, **overrides):
    """Build one day of readings where every sensor matches, apart from any overrides."""
    readings = {sid: (rain, level) for sid in SENSORS}
    readings.update(overrides)
    return readings


def flagged(alerts):
    return {(a["sensor"], a["field"]) for a in alerts}


# Rainfall

def test_big_rain_spike_on_dry_day_is_flagged():
    alerts = Detector().check_day("d1", day(0.0, S3=(80.0, 1.0)))
    assert flagged(alerts) == {("S3", "rainfall_mm")}


def test_rain_hidden_on_wet_day_is_flagged():
    # Faking 0 mm while everyone else got 30 mm is as suspicious as a spike.
    alerts = Detector().check_day("d1", day(30.0, S3=(0.0, 1.0)))
    assert flagged(alerts) == {("S3", "rainfall_mm")}


def test_normal_spread_on_heavy_day_is_not_flagged():
    # Sensors differ by up to 30% on real rainy days, which must not raise alerts.
    readings = {"S1": (24.0, 1.0), "S2": (28.0, 1.0), "S3": (39.0, 1.0), "S4": (31.0, 1.0),
                "S5": (26.0, 1.0), "S6": (35.0, 1.0), "S7": (30.0, 1.0), "S8": (33.0, 1.0)}
    assert Detector().check_day("d1", readings) == []


def test_small_spike_gets_through():
    # A known limitation: a fake value under the 10 mm limit is not caught.
    alerts = Detector().check_day("d1", day(0.0, S3=(8.0, 1.0)))
    assert alerts == []


def test_alert_explains_itself():
    alerts = Detector().check_day("d1", day(0.0, S3=(80.0, 1.0)))
    assert alerts[0]["reason"] == "80.0 mm vs 0.0 mm from the other sensors"


# River level

def test_river_level_is_not_checked_on_the_first_day():
    # There's no yesterday to compare against yet.
    alerts = Detector().check_day("d1", day(0.0, S5=(0.0, 3.2)))
    assert alerts == []


def test_river_jump_is_flagged():
    detector = Detector()
    detector.check_day("d1", day(0.0, level=1.0))
    alerts = detector.check_day("d2", day(0.0, level=0.98, S5=(0.0, 2.5)))

    assert flagged(alerts) == {("S5", "river_level_m")}


def test_sensors_at_different_heights_are_not_flagged():
    # Only the daily change is compared, so a river that always sits higher is fine.
    detector = Detector()
    detector.check_day("d1", day(0.0, level=1.0, S5=(0.0, 3.0)))
    alerts = detector.check_day("d2", day(0.0, level=0.98, S5=(0.0, 2.98)))

    assert alerts == []


def test_all_rivers_rising_together_is_not_flagged():
    detector = Detector()
    detector.check_day("d1", day(0.0, level=1.0))
    alerts = detector.check_day("d2", day(40.0, level=1.8))

    assert alerts == []


def test_flagged_level_is_not_used_as_the_next_baseline():
    # Without this, S5 dropping back to normal would look like a second attack.
    detector = Detector()
    detector.check_day("d1", day(0.0, level=1.0))
    detector.check_day("d2", day(0.0, level=0.99, S5=(0.0, 3.2)))
    alerts = detector.check_day("d3", day(0.0, level=0.98))

    assert alerts == []


# Missing data

def test_missing_reading_is_skipped_not_crashed():
    alerts = Detector().check_day("d1", day(0.0, S2=None, S3=(80.0, 1.0)))
    assert flagged(alerts) == {("S3", "rainfall_mm")}


def test_too_few_sensors_means_no_checks():
    # With fewer than three others to compare against, a single bad sensor could fool the median.
    readings = {"S1": (0.0, 1.0), "S2": (0.0, 1.0), "S3": (80.0, 1.0)}
    assert Detector().check_day("d1", readings) == []


# Flatline

def run_days(detector, days):
    """Feed several days through one detector and return every alert raised."""
    alerts = []
    for i, readings in enumerate(days):
        alerts += detector.check_day(f"d{i + 1}", readings)
    return alerts


def test_stuck_river_gauge_is_flagged_on_the_fourth_day():
    # The other rivers fall 5 cm a day while S7 stays at 2.00.
    days = [day(0.0, level=2.0 - 0.05 * i, S7=(0.0, 2.0)) for i in range(config.FLATLINE_DAYS)]
    alerts = run_days(Detector(), days)

    assert flagged(alerts) == {("S7", "river_level_m")}
    assert alerts[0]["date"] == f"d{config.FLATLINE_DAYS}"


def test_stuck_sensor_is_only_flagged_once():
    days = [day(0.0, level=2.0 - 0.05 * i, S7=(0.0, 2.0)) for i in range(8)]
    alerts = run_days(Detector(), days)

    assert len(alerts) == 1


def test_whole_area_dry_week_is_not_a_flatline():
    # Every gauge reading 0 mm for a week is just a dry week.
    alerts = run_days(Detector(), [day(0.0, level=1.0 - 0.05 * i) for i in range(6)])
    assert alerts == []


def test_drizzle_in_other_sensors_does_not_count_as_moving():
    # 0.1 mm differences are gauge noise, not a sign that S1 is stuck.
    days = [day(0.0, level=1.0 - 0.05 * i) for i in range(3)]
    days.append(day(0.1, level=0.85, S1=(0.0, 0.85)))
    assert run_days(Detector(), days) == []


def test_stuck_rain_gauge_during_rain_is_flagged():
    # Others get varied rain while S2 keeps reporting 3.0 mm.
    rain = [2.0, 6.0, 4.0, 9.0]
    days = [day(r, level=1.0 + 0.05 * i, S2=(3.0, 1.0 + 0.05 * i)) for i, r in enumerate(rain)]
    alerts = run_days(Detector(), days)

    assert ("S2", "rainfall_mm") in flagged(alerts)


def test_stuck_gauge_snapping_back_is_not_a_river_jump():
    # S7 is frozen at 2.00 while the others fall, then drops 0.75 m back to its real level.
    days = [day(0.0, level=2.0 - 0.15 * i, S7=(0.0, 2.0)) for i in range(5)]
    days.append(day(0.0, level=1.25, S7=(0.0, 1.25)))
    alerts = run_days(Detector(), days)

    assert [a["field"] for a in alerts] == ["river_level_m"]
    assert "stuck" in alerts[0]["reason"]
