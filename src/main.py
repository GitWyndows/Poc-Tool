"""Replays the DWER streamflow CSV day by day, printing each gauge's flow, the weekly advisories, and any alerts.

    python src/main.py                 # all 92 days
    python src/main.py --days 5        # first 5 days only
    python src/main.py --delay 1       # wait 1 second between days (looks "live")
    python src/main.py --attack        # apply the sensor and advisory attacks in config.py, then score the detector

The data file is checked strictly before anything runs, so a gap or typo stops the tool instead of
quietly skewing the results. June is spent learning how the gauges normally behave, and checks start in July.
"""
import argparse
import csv
import math
import sys
import time
from datetime import date, timedelta

import config
from advisories import AdvisoryWriter, advisory_text
from attacks import Attacker, describe, score
from detection import Detector
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


def print_day(day_number, day, sensors, flows, advisories, alerts):
    # Fixed column widths keep the table lined up however long each value is.
    learning = "  |  learning" if day <= config.LEARN_END else ""
    print(f"\nDay {day_number}  |  {day}{learning}")
    print(f"{'Gauge':<8}{'Name':<32}{'Flow (ML/day)':>15}")
    print("-" * 55)

    # The flows shown are the ones the detector saw, so a tampered value appears exactly as a defender would see it.
    flagged = {a["sensor"] for a in alerts}
    for s in sensors:
        mark = "  <-- ALERT" if s.id in flagged else ""
        print(f"{s.id:<8}{s.name:<32}{flows[s.id]:>15.2f}{mark}")

    # Genuine and fake advisories are printed the same way, with nothing marking which is which.
    for advisory in advisories:
        mark = "  <-- ALERT" if advisory["id"] in flagged else ""
        print(f"  ADVISORY {advisory['id']:<7}{advisory_text(advisory)}{mark}")

    # Reasons go under the table so the columns stay aligned.
    for a in alerts:
        print(f"  ALERT {a['sensor']} {a['rule']}: {a['reason']}")


def print_limits(detector, sensors):
    """Show the limits learned in June, so it's clear how big a change has to be before it's flagged."""
    if not detector.jump_limit:
        print(f"\nStill learning, so nothing was checked. Checks start after {config.LEARN_END}.")
        return

    # Limits are shown as how many times bigger or smaller a change can be than the others' before it's flagged.
    print(f"\nLimits learned from {config.START_DATE} to {config.LEARN_END}")
    print(f"{'Gauge':<8}{'Name':<32}{'Jump':>8}{'Drift':>8}")
    print("-" * 56)
    for s in sensors:
        jump, drift = math.exp(detector.jump_limit[s.id]), math.exp(detector.drift_limit[s.id])
        print(f"{s.id:<8}{s.name:<32}{f'x{jump:.2f}':>8}{f'x{drift:.2f}':>8}")


def print_attack_log(attacker):
    # Printed only at the end, so the daily tables look exactly as a defender would see them.
    print("\n" + "=" * 56)
    print("ATTACK LOG (ground truth)")
    print("=" * 56)

    # Grouped by attack, so a week-long flatline reads as one entry rather than seven.
    for attack_id, attack in enumerate(attacker.plan):
        entries = [e for e in attacker.log if e["attack"] == attack_id]
        if not entries:
            print(f"Skipped: {describe(attack)} falls outside the days shown.")
            continue

        first, last = entries[0], entries[-1]
        if attack["type"] == "fake_figures":
            (fake_flow, fake_change), (real_flow, real_change) = first["fake"], first["real"]
            detail = (f"{first['sensor']} claimed {fake_flow:.1f} ML/day, {fake_change:+d}% "
                      f"when the readings showed {real_flow:.1f} ML/day, {real_change:+d}%")
        elif attack["type"] == "fake_source":
            detail = f"{first['sensor']} copied the real figures under an unapproved name"
        elif attack["type"] == "spike":
            detail = f"real {first['real']:.2f} -> fake {first['fake']:.2f} ML/day"
        elif attack["type"] == "drift":
            detail = f"{last['fake'] / last['real'] - 1:+.0%} off by the last day"
        else:
            detail = f"frozen at {first['fake']:.2f} ML/day for {len(entries)} days"
        print(f"{describe(attack)}: {detail}")


def print_score(alerts, attacker):
    caught, caught_late, missed, false_alarms = score(alerts, attacker)
    ran = len(caught) + len(caught_late) + len(missed)

    print("\n" + "=" * 56)
    print("DETECTION SCORE")
    print("=" * 56)
    print(f"Attacks caught:  {len(caught)} of {ran}")
    print(f"Caught late:     {len(caught_late)}  (only noticed when the attack stopped)")
    print(f"Attacks missed:  {len(missed)}")
    print(f"False alarms:    {len(false_alarms)}")

    # Listing them by name shows exactly where a rule needs work.
    for attack in caught_late:
        print(f"  LATE         {describe(attack)}")
    for attack in missed:
        print(f"  MISSED       {describe(attack)}")
    for day, sensor in false_alarms:
        print(f"  FALSE ALARM  {day}  {sensor}")


def main():
    # argparse handles the options and builds the --help message for free.
    parser = argparse.ArgumentParser(description="Replay daily streamflow for the five DWER gauges and check it.")
    parser.add_argument("--days", type=int, help="Only show this many days")
    parser.add_argument("--delay", type=float, default=0, help="Seconds to wait between days")
    parser.add_argument("--attack", action="store_true", help="Apply the attacks planned in config.py")
    args = parser.parse_args()

    # Caught here with a clear message, since 0 days would quietly show nothing and a negative pause would crash.
    if args.days is not None and args.days < 1:
        parser.error("--days must be 1 or more")
    if args.delay < 0:
        parser.error("--delay can't be negative")

    sensors, dates = load_sensors()

    # Attacks are opt-in so a clean run is always available to compare against.
    attacker = Attacker(config.ATTACKS if args.attack else [])
    detector = Detector()
    writer = AdvisoryWriter()
    all_alerts = []

    shown_dates = dates if args.days is None else dates[:args.days]

    print(f"Streamflow from {len(sensors)} DWER gauges, {dates[0]} to {dates[-1]}")

    # Counting from 1 so the output reads "Day 1" rather than "Day 0".
    for i, day in enumerate(shown_dates, start=1):
        # Every reading passes through the attacker first, and the detector sees only what comes out, never the log.
        flows = {s.id: attacker.apply(s.id, day, s.read(day)) for s in sensors}
        alerts = detector.check_day(day, flows)

        # Genuine and fake advisories go out together and are checked the same way.
        advisories = [writer.record(day, flows)] + attacker.fake_advisories(day, writer.readings_by_date)
        advisories = [a for a in advisories if a is not None]
        for advisory in advisories:
            alerts += detector.check_advisory(advisory)

        all_alerts += alerts
        print_day(i, day, sensors, flows, advisories, alerts)

        # The pause makes the replay look like a live feed during a demo.
        if args.delay:
            time.sleep(args.delay)

    print_limits(detector, sensors)
    if args.attack:
        print_attack_log(attacker)
    print_score(all_alerts, attacker)


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
