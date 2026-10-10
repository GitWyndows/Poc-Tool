"""Measures the detector across many attacks: every gauge, every July and August start date, several attack sizes.

    python src/evaluate.py              # one row per attack
    python src/evaluate.py --by-gauge   # one row per attack per gauge

Each run replays all 92 days with a single attack and scores it against the attacker's log, exactly as
main.py --attack does. A clean run is scored too, so the false-alarm rate on untampered data is shown. The last
column counts genuine advisories that quoted tampered readings, which no advisory check can catch.
"""
import argparse

import config
from advisories import AdvisoryWriter, weekly_figures
from attacks import Attacker, advisory_period, attack_dates, score, tampered_advisories
from detection import Detector
from main import load_sensors, run_day

# Each attack to try, as (label, type, settings). Single-gauge attacks run on every gauge; the rest run once per date.
SCENARIOS = [
    ("spike x3", "spike", {"factor": 3.0}),
    ("spike x2", "spike", {"factor": 2.0}),
    ("spike x1.5", "spike", {"factor": 1.5}),
    ("spike x0.67", "spike", {"factor": 0.67}),
    ("spike x0.5", "spike", {"factor": 0.5}),
    ("spike x0.33", "spike", {"factor": 0.33}),
    ("flatline 7 days", "flatline", {"days": 7}),
    ("drift +5% a day, 14 days", "drift", {"days": 14, "rate": 0.05}),
    ("drift +10% a day, 14 days", "drift", {"days": 14, "rate": 0.10}),
    ("drift +15% a day, 14 days", "drift", {"days": 14, "rate": 0.15}),
    ("drift -10% a day, 14 days", "drift", {"days": 14, "rate": -0.10}),
    ("coordinated, Lefroy pair +4% a day, 21 days", "coordinated",
     {"sensors": ["607022", "607013"], "days": 21, "rate": 0.04}),
    ("coordinated, 3 gauges +10% a day, 14 days", "coordinated",
     {"sensors": ["607022", "608171", "608151"], "days": 14, "rate": 0.10}),
    ("coordinated, all 5 gauges +10% a day, 14 days", "coordinated",
     {"sensors": ["607022", "607013", "608171", "608002", "608151"], "days": 14, "rate": 0.10}),
    ("fake figures, flow 30% low", "fake_figures", {"understate": 0.30}),
    ("fake figures, flow 1% low", "fake_figures", {"understate": 0.01}),
    ("fake source", "fake_source", {"source": "WA Water Watch"}),
    ("stale advisory, 2 weeks old", "stale_advisory", {"weeks_old": 2}),
]

# Attacks that don't target a single gauge, so they run once per start date instead of once per gauge.
ONCE_PER_DATE = ("coordinated", "fake_figures", "fake_source", "stale_advisory")


def make_attack(kind, settings, sensor, start, clean):
    """Build one attack starting on `start`, in the same shape as the plan in config.py."""
    if kind == "spike":
        return {"type": "spike", "sensor": sensor, "date": start, **settings}
    if kind in ("flatline", "drift"):
        return {"type": kind, "sensor": sensor, "start": start, **settings}
    if kind == "coordinated":
        return {"type": "coordinated", "start": start, **settings}
    if kind in ("fake_source", "stale_advisory"):
        return {"type": kind, "date": start, **settings}

    # Fake figures understate the real week's flow, so the lie is a believable one rather than a made-up number.
    flow, change = weekly_figures(clean, *advisory_period({"date": start})) or (0.0, 0.0)
    return {"type": "fake_figures", "date": start, "source": config.APPROVED_SOURCES[0],
            "avg_flow_ml": flow * (1 - settings["understate"]), "change_pct": round(change * 100)}


def replay(sensors, dates, plan, clean):
    """Run every day with the planned attacks, returning the score, advisories checked and genuine ones corrupted."""
    attacker, detector, writer = Attacker(plan), Detector(), AdvisoryWriter()
    alerts, advisories = [], 0
    for day in dates:
        _, published, day_alerts = run_day(day, sensors, attacker, detector, writer)
        alerts += day_alerts
        advisories += len(published)
    return score(alerts, attacker), advisories, len(tampered_advisories(writer.published, clean))


def evaluate(sensors, dates, scenarios, by_gauge=False):
    """Run every scenario on every gauge and start date, returning {row label: tallies} in table order."""
    clean = {day: {s.id: s.read(day) for s in sensors} for day in dates}
    checked = [d for d in dates if d > config.LEARN_END]
    rows = {}

    for label, kind, settings in scenarios:
        gauges = ["-"] if kind in ONCE_PER_DATE else [s.id for s in sensors]
        for sensor in gauges:
            key = f"{label}  ({sensor})" if by_gauge and sensor != "-" else label
            tally = rows.setdefault(key, {"runs": 0, "caught": 0, "late": 0, "missed": 0, "false": 0, "tampered": 0})

            for start in checked:
                attack = make_attack(kind, settings, sensor, start, clean)

                # Attacks that would run past the last day are skipped, so every run tests a whole attack.
                if attack_dates(attack)[-1] > config.END_DATE:
                    continue

                (caught, late, missed, false_alarms), _, tampered = replay(sensors, dates, [attack], clean)
                tally["runs"] += 1
                tally["caught"] += len(caught)
                tally["late"] += len(late)
                tally["missed"] += len(missed)
                tally["false"] += len(false_alarms)
                tally["tampered"] += tampered
    return rows


def print_table(rows):
    print(f"{'Attack':<48}{'Runs':>6}{'Caught':>8}{'Late':>7}{'Missed':>8}{'False alarms':>14}{'Bad advisories':>16}")
    print(f"{'':<77}{'per run':>14}{'per run':>16}")
    print("-" * 107)
    for label, t in rows.items():
        runs = t["runs"]
        print(f"{label:<48}{runs:>6}{t['caught'] / runs:>8.0%}{t['late'] / runs:>7.0%}"
              f"{t['missed'] / runs:>8.0%}{t['false'] / runs:>14.2f}{t['tampered'] / runs:>16.2f}")


def main():
    parser = argparse.ArgumentParser(description="Measure detection and false-alarm rates across many attacks.")
    parser.add_argument("--by-gauge", action="store_true", help="Show one row per attack per gauge")
    args = parser.parse_args()

    sensors, dates = load_sensors()
    print(f"Replaying {len(dates)} days once per attack, gauge and start date. This takes about 10 seconds.\n")

    # The clean run shows how often untampered data raises an alert, which every other row is judged against.
    clean = {day: {s.id: s.read(day) for s in sensors} for day in dates}
    (_, _, _, false_alarms), advisories, _ = replay(sensors, dates, [], clean)
    checked_days = len([d for d in dates if d > config.LEARN_END]) * len(sensors)
    print(f"Clean data: {len(false_alarms)} false alarm(s) in {checked_days} gauge-days "
          f"and {advisories} advisories checked\n")

    print_table(evaluate(sensors, dates, SCENARIOS, args.by_gauge))


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
