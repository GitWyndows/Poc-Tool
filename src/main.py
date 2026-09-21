"""Reads the CSV and prints each day's sensor readings to the terminal.

    python src/main.py                 # all 90 days
    python src/main.py --days 5        # first 5 days only
    python src/main.py --delay 1       # wait 1 second between days (looks "live")
    python src/main.py --attack        # apply the attacks planned in config.py

Run generate_data.py first if data/readings.csv doesn't exist.
"""
import argparse
import csv
import sys
import time

import config
from attacks import Attacker
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


def print_day(day_number, date, sensors, attacker):
    # Fixed column widths keep the table lined up however long each value is.
    print(f"\nDay {day_number}  |  {date}")
    print(f"{'Sensor':<8}{'Name':<24}{'Rainfall (mm)':>15}{'River level (m)':>18}")
    print("-" * 65)

    for s in sensors:
        # The attacker sits between the sensor and the output, just as tampering in transit would.
        reading = attacker.apply(s.id, date, s.read(date))

        # A gap is shown rather than skipped, so a silent sensor is visible in the output.
        if reading is None:
            print(f"{s.id:<8}{s.name:<24}{'no data':>15}{'no data':>18}")
        else:
            rain, level = reading
            print(f"{s.id:<8}{s.name:<24}{rain:>15.1f}{level:>18.2f}")


def print_attack_log(attacker, all_dates, shown_dates):
    # Printed only at the end, so the daily tables look exactly as a defender would see them.
    print("\n" + "=" * 65)
    print("ATTACK LOG (ground truth)")
    print("=" * 65)

    if not attacker.log:
        print("No attacks were applied.")

    for entry in attacker.log:
        unit = "mm" if entry["field"] == "rainfall_mm" else "m"
        print(f"{entry['date']}  {entry['sensor']}  {entry['field']:<14} "
              f"real {entry['real']:>6.2f} {unit:<2}  ->  fake {entry['fake']:>6.2f} {unit}")

    # A planned attack that never ran would otherwise look like one the detector missed.
    known_ids = {sid for sid, _ in config.SENSORS}
    for a in attacker.unused():
        if a["sensor"] not in known_ids or a["date"] not in all_dates:
            print(f"WARNING: planned attack on {a['sensor']} for {a['date']} never ran. Check the ID and date.")
        elif a["date"] not in shown_dates:
            print(f"Skipped: attack on {a['sensor']} for {a['date']} falls outside the days shown.")


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

    # Note that --days 0 counts as not set, so it shows every day.
    shown_dates = dates[:args.days] if args.days else dates

    # Counting from 1 so the output reads "Day 1" rather than "Day 0".
    for i, date in enumerate(shown_dates, start=1):
        print_day(i, date, sensors, attacker)

        # The pause makes the replay look like a live feed during a demo.
        if args.delay:
            time.sleep(args.delay)

    if args.attack:
        print_attack_log(attacker, dates, shown_dates)


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
