"""Reads the DWER streamflow CSV and prints each day's flow for the five gauges.

    python src/main.py                 # all 92 days
    python src/main.py --days 5        # first 5 days only
    python src/main.py --delay 1       # wait 1 second between days (looks "live")

The data file is checked strictly before anything runs, so a gap or typo stops the tool instead of
quietly skewing the results.
"""
import argparse
import csv
import math
import sys
import time
from datetime import date, timedelta

import config
from sensor import Sensor

HEADER = ["date", "sensor_id", "flow_ml"]

# Enough problems to show what's wrong without burying the message.
MAX_PROBLEMS_SHOWN = 10


def replay_dates():
    """Every date from START_DATE to END_DATE, as "YYYY-MM-DD" strings."""
    start, end = date.fromisoformat(config.START_DATE), date.fromisoformat(config.END_DATE)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def check_row(row, known_ids, dates):
    """Return (date, sensor_id, flow) for a valid row, or a description of what's wrong with it."""
    if len(row) != len(HEADER):
        return f"has {len(row)} columns instead of {len(HEADER)}"

    day, sid, flow_text = row
    if day not in dates:
        return f"date '{day}' is not a real date between {config.START_DATE} and {config.END_DATE}"
    if sid not in known_ids:
        return f"gauge '{sid}' is not one of the gauges in config.py"

    try:
        flow = float(flow_text)
    except ValueError:
        return f"flow '{flow_text}' is not a number"

    # Flow can be zero when a stream stops, but never negative, and "nan" or "inf" would poison every comparison.
    if not math.isfinite(flow) or flow < 0:
        return f"flow '{flow_text}' must be a number of zero or more"
    return day, sid, flow


def load_sensors():
    """Read the CSV into one Sensor per gauge, stopping with every problem listed if the file isn't exactly right."""
    if not config.DATA_FILE.exists():
        sys.exit(f"No data found at {config.DATA_FILE}")

    sensors = {sid: Sensor(sid, name) for sid, name in config.SENSORS}
    dates = replay_dates()
    date_set = set(dates)
    problems = []

    with open(config.DATA_FILE, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != HEADER:
            sys.exit(f"{config.DATA_FILE.name} must start with the header {','.join(HEADER)}, not {header}")

        # Line numbers start at 2 because the header is line 1, which makes problems easy to find in the file.
        for line, row in enumerate(reader, start=2):
            result = check_row(row, sensors, date_set)
            if isinstance(result, str):
                problems.append(f"line {line}: {result}")
                continue

            day, sid, flow = result
            if sensors[sid].read(day) is not None:
                problems.append(f"line {line}: {sid} on {day} appears more than once")
                continue
            sensors[sid].add_reading(day, flow)

    # Every gauge needs every day, since a gap would look like a sensor going quiet.
    for s in sensors.values():
        missing = [d for d in dates if s.read(d) is None]
        if missing:
            problems.append(f"{s.id} is missing {len(missing)} day(s), starting {missing[0]}")

    if problems:
        shown = "\n  ".join(problems[:MAX_PROBLEMS_SHOWN])
        more = f"\n  ...and {len(problems) - MAX_PROBLEMS_SHOWN} more" if len(problems) > MAX_PROBLEMS_SHOWN else ""
        sys.exit(f"{config.DATA_FILE.name} has {len(problems)} problem(s):\n  {shown}{more}")

    return list(sensors.values()), dates


def print_day(day_number, day, sensors):
    # Fixed column widths keep the table lined up however long each value is.
    print(f"\nDay {day_number}  |  {day}")
    print(f"{'Gauge':<8}{'Name':<32}{'Flow (ML/day)':>15}")
    print("-" * 55)

    for s in sensors:
        print(f"{s.id:<8}{s.name:<32}{s.read(day):>15.2f}")


def main():
    # argparse handles the options and builds the --help message for free.
    parser = argparse.ArgumentParser(description="Print daily streamflow for the five DWER gauges.")
    parser.add_argument("--days", type=int, help="Only show this many days")
    parser.add_argument("--delay", type=float, default=0, help="Seconds to wait between days")
    args = parser.parse_args()

    sensors, dates = load_sensors()

    # Note that --days 0 counts as not set, so it shows every day.
    shown_dates = dates[:args.days] if args.days else dates

    print(f"Streamflow from {len(sensors)} DWER gauges, {dates[0]} to {dates[-1]}")

    # Counting from 1 so the output reads "Day 1" rather than "Day 0".
    for i, day in enumerate(shown_dates, start=1):
        print_day(i, day, sensors)

        # The pause makes the replay look like a live feed during a demo.
        if args.delay:
            time.sleep(args.delay)


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
