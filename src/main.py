"""Reads the CSV and prints each day's sensor readings to the terminal.

    python src/main.py                 # all 90 days
    python src/main.py --days 5        # first 5 days only
    python src/main.py --delay 1       # wait 1 second between days (looks "live")
    python src/main.py --attack        # apply the attacks planned in config.py

Detection always runs, and a score is printed at the end.

Run generate_data.py first if data/readings.csv doesn't exist.
"""
import argparse
import csv
import sys
import time

import config
from attacks import Attacker, attack_dates, day_after, describe
from detection import Detector
from sensor import Sensor


def load_sensors():
    """Create the 8 sensors and fill them with data from the CSV."""
    # Checking first gives a clear instruction instead of a confusing file error.
    if not config.DATA_FILE.exists():
        sys.exit(f"No data found at {config.DATA_FILE}\nRun: python src/generate_data.py")

    # Keyed by ID so each CSV row can find its sensor without searching.
    sensors = {sid: Sensor(sid, name) for sid, name in config.SENSORS}
    dates = []

    with open(config.DATA_FILE, newline="") as f:
        # DictReader uses the header names, so the code doesn't break if the columns are reordered.
        for row in csv.DictReader(f):
            sensor = sensors.get(row["sensor_id"])

            # Skipping unknown IDs means a stray row can't crash the run.
            if sensor is None:
                continue

            # CSV values always arrive as text, so they need converting before any maths.
            sensor.add_reading(row["date"], float(row["rainfall_mm"]), float(row["river_level_m"]))

            # Each date appears once per sensor, so this keeps one copy in the order they appear.
            if row["date"] not in dates:
                dates.append(row["date"])

    return list(sensors.values()), dates


def print_day(day_number, date, sensors, attacker, detector):
    # Every reading passes through the attacker first, just as tampering in transit would.
    readings = {s.id: attacker.apply(s.id, date, s.read(date)) for s in sensors}

    # The detector sees only what a defender would: the readings, never the attack log.
    alerts = detector.check_day(date, readings)
    flagged = {a["sensor"] for a in alerts}

    # Fixed column widths keep the table lined up however long each value is.
    print(f"\nDay {day_number}  |  {date}")
    print(f"{'Sensor':<8}{'Name':<24}{'Rainfall (mm)':>15}{'River level (m)':>18}")
    print("-" * 65)

    for s in sensors:
        reading = readings[s.id]

        # Plain ASCII, since some Windows terminals can't print symbols like a warning sign.
        mark = "  <-- ALERT" if s.id in flagged else ""

        # A gap is shown rather than skipped, so a silent sensor is visible in the output.
        if reading is None:
            print(f"{s.id:<8}{s.name:<24}{'no data':>15}{'no data':>18}{mark}")
        else:
            rain, level = reading
            print(f"{s.id:<8}{s.name:<24}{rain:>15.1f}{level:>18.2f}{mark}")

    # Reasons go under the table so the columns stay aligned.
    for a in alerts:
        print(f"  ALERT  {a['sensor']} {a['field']}: {a['reason']}")

    return alerts


def print_attack_log(attacker, all_dates, shown_dates):
    # Printed only at the end, so the daily tables look exactly as a defender would see them.
    print("\n" + "=" * 65)
    print("ATTACK LOG (ground truth)")
    print("=" * 65)

    if not attacker.log:
        print("No attacks were applied.")

    # Grouped by attack, so a week long flatline reads as one entry rather than seven.
    for attack_id, attack in enumerate(attacker.plan):
        entries = [e for e in attacker.log if e["attack"] == attack_id]
        if not entries:
            continue

        unit = "mm" if attack["field"] == "rainfall_mm" else "m"
        first = entries[0]
        last = entries[-1]
        if attack["type"] == "spike":
            detail = f"real {first['real']:.2f} {unit} -> fake {first['fake']:.2f} {unit}"
        elif attack["type"] == "drift":
            detail = f"{last['fake'] - last['real']:+.2f} {unit} off by the last day"
        else:
            detail = f"frozen at {first['fake']:.2f} {unit} for {len(entries)} days"
        print(f"{describe(attack)}: {detail}")

    # A planned attack that never ran would otherwise look like one the detector missed.
    known_ids = {sid for sid, _ in config.SENSORS}
    for a in attacker.unused():
        dates = attack_dates(a)
        if a["sensor"] not in known_ids or dates[0] not in all_dates:
            print(f"WARNING: {describe(a)} never ran. Check the ID and dates.")
        elif dates[0] not in shown_dates:
            print(f"Skipped: {describe(a)} falls outside the days shown.")


def print_score(alerts, attacker):
    alert_keys = {(a["date"], a["sensor"], a["field"]) for a in alerts}
    attacked_keys = {(e["date"], e["sensor"], e["field"]) for e in attacker.log}

    # An alert the day an attack stops, on that sensor, is caused by the snapback rather than being false.
    end_keys = {(day_after(attacker.plan[e["attack"]]), e["sensor"], e["field"]) for e in attacker.log}

    ran = sorted({e["attack"] for e in attacker.log})
    caught, caught_late, missed = [], [], []
    for attack_id in ran:
        attack = attacker.plan[attack_id]
        keys = {(e["date"], e["sensor"], e["field"]) for e in attacker.log if e["attack"] == attack_id}

        # Caught means an alert on the right sensor and field while the attack was running.
        if keys & alert_keys:
            caught.append(attack)
        elif (day_after(attack), attack["sensor"], attack["field"]) in alert_keys:
            caught_late.append(attack)
        else:
            missed.append(attack)

    false_alarms = alert_keys - attacked_keys - end_keys

    print("\n" + "=" * 65)
    print("DETECTION SCORE")
    print("=" * 65)
    print(f"Attacks caught:  {len(caught)} of {len(ran)}")
    print(f"Caught late:     {len(caught_late)}  (only noticed when the attack stopped)")
    print(f"Attacks missed:  {len(missed)}")
    print(f"False alarms:    {len(false_alarms)}")

    # Listing them by name shows exactly where a rule needs work.
    for attack in caught_late:
        print(f"  LATE         {describe(attack)}")
    for attack in missed:
        print(f"  MISSED       {describe(attack)}")
    for date, sensor, field in sorted(false_alarms):
        print(f"  FALSE ALARM  {date}  {sensor}  {field}")


def main():
    # argparse handles the options and builds the --help message for free.
    parser = argparse.ArgumentParser(description="Print simulated sensor readings.")
    parser.add_argument("--days", type=int, help="Only show this many days")
    parser.add_argument("--delay", type=float, default=0, help="Seconds to wait between days")
    parser.add_argument("--attack", action="store_true", help="Apply the attacks planned in config.py")
    args = parser.parse_args()

    sensors, dates = load_sensors()

    # Attacks are opt-in so a clean run is always available to compare against.
    attacker = Attacker(config.ATTACKS if args.attack else [])
    detector = Detector()
    all_alerts = []

    # Note that --days 0 counts as not set, so it shows every day.
    shown_dates = dates[:args.days] if args.days else dates

    # Counting from 1 so the output reads "Day 1" rather than "Day 0".
    for i, date in enumerate(shown_dates, start=1):
        all_alerts += print_day(i, date, sensors, attacker, detector)

        # The pause makes the replay look like a live feed during a demo.
        if args.delay:
            time.sleep(args.delay)

    if args.attack:
        print_attack_log(attacker, dates, shown_dates)

    print_score(all_alerts, attacker)


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
