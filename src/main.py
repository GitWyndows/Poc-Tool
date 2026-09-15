"""Reads the CSV and prints each day's sensor readings to the terminal.

    python src/main.py                 # all 90 days
    python src/main.py --days 5        # first 5 days only
    python src/main.py --delay 1       # wait 1 second between days (looks "live")

Run generate_data.py first if data/readings.csv doesn't exist.
"""
import argparse
import csv
import sys
import time

import config
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


def print_day(day_number, date, sensors):
    # Fixed column widths keep the table lined up however long each value is.
    print(f"\nDay {day_number}  |  {date}")
    print(f"{'Sensor':<8}{'Name':<24}{'Rainfall (mm)':>15}{'River level (m)':>18}")
    print("-" * 65)

    for s in sensors:
        reading = s.read(date)

        # A gap is shown rather than skipped, so a silent sensor is visible in the output.
        if reading is None:
            print(f"{s.id:<8}{s.name:<24}{'no data':>15}{'no data':>18}")
        else:
            rain, level = reading
            print(f"{s.id:<8}{s.name:<24}{rain:>15.1f}{level:>18.2f}")


def main():
    # argparse handles the options and builds the --help message for free.
    parser = argparse.ArgumentParser(description="Print simulated sensor readings.")
    parser.add_argument("--days", type=int, help="Only show this many days")
    parser.add_argument("--delay", type=float, default=0, help="Seconds to wait between days")
    args = parser.parse_args()

    sensors, dates = load_sensors()

    # Note that --days 0 counts as not set, so it shows every day.
    if args.days:
        dates = dates[:args.days]

    # Counting from 1 so the output reads "Day 1" rather than "Day 0".
    for i, date in enumerate(dates, start=1):
        print_day(i, date, sensors)

        # The pause makes the replay look like a live feed during a demo.
        if args.delay:
            time.sleep(args.delay)


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
