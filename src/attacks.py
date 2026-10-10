"""Attacks on gauge readings (spikes, flatlines, drift, coordinated drift) and on public advisories (fake figures,
fake source, stale advisory), all logged so detection can be scored against them."""
from datetime import date, timedelta

import config
from advisories import make_advisory, weekly_figures

SENSOR_TYPES = ("spike", "flatline", "drift", "coordinated")
ADVISORY_TYPES = ("fake_figures", "fake_source", "stale_advisory")
TYPES = SENSOR_TYPES + ADVISORY_TYPES

# What each attack type must say, so a typo in config.py fails straight away instead of silently doing nothing.
NEEDED = {
    "spike": ["sensor", "date", "factor"],
    "flatline": ["sensor", "start", "days"],
    "drift": ["sensor", "start", "days", "rate"],
    "coordinated": ["sensors", "start", "days", "rate"],
    "fake_figures": ["date", "source", "avg_flow_ml", "change_pct"],
    "fake_source": ["date", "source"],
    "stale_advisory": ["date", "weeks_old"],
}


def attack_dates(attack):
    """Return every date an attack covers, as "YYYY-MM-DD" strings."""
    # Spikes and advisory attacks each happen on a single day.
    if "date" in attack:
        return [attack["date"]]

    start = date.fromisoformat(attack["start"])
    return [(start + timedelta(days=i)).isoformat() for i in range(attack["days"])]


def attacked_sensors(attack):
    """The gauges an attack tampers with, which is several for a coordinated drift and none for an advisory."""
    if attack["type"] == "coordinated":
        return list(attack["sensors"])
    return [attack["sensor"]] if attack["type"] in SENSOR_TYPES else []


def day_after(attack):
    """The first date after an attack ends, when a tampered gauge snaps back to its real value."""
    last = date.fromisoformat(attack_dates(attack)[-1])
    return (last + timedelta(days=1)).isoformat()


def describe(attack):
    """A short plain-English summary of an attack, for printing."""
    if attack["type"] == "spike":
        return f"spike on {attack['sensor']} of x{attack['factor']} on {attack['date']}"
    if attack["type"] == "fake_figures":
        return f"fake figures posing as {attack['source']} on {attack['date']}"
    if attack["type"] == "fake_source":
        return f"fake advisory from '{attack['source']}' on {attack['date']}"
    if attack["type"] == "stale_advisory":
        return f"stale advisory reusing a week from {attack['weeks_old']} weeks earlier on {attack['date']}"

    dates = attack_dates(attack)
    if attack["type"] == "drift":
        return f"drift on {attack['sensor']} of {attack['rate']:+.0%} a day from {dates[0]} to {dates[-1]}"
    if attack["type"] == "coordinated":
        return (f"coordinated drift on {', '.join(attack['sensors'])} of {attack['rate']:+.0%} a day "
                f"from {dates[0]} to {dates[-1]}")
    return f"flatline on {attack['sensor']} from {dates[0]} to {dates[-1]}"


def advisory_period(attack):
    """The week an advisory attack claims to describe, ending on the day it goes out unless it's a stale one."""
    end = date.fromisoformat(attack["date"]) - timedelta(weeks=attack.get("weeks_old", 0))
    start = end - timedelta(days=config.ADVISORY_EVERY_DAYS - 1)
    return start.isoformat(), end.isoformat()


def check_attack(attack):
    """Raise a clear error if a planned attack is missing something or falls outside the checked period."""
    if attack.get("type") not in TYPES:
        raise ValueError(f"Unknown attack type '{attack.get('type')}'. Use one of {TYPES}.")

    for key in NEEDED[attack["type"]]:
        if key not in attack:
            raise ValueError(f"{attack['type']} attack is missing '{key}'.")

    known = {sid for sid, _ in config.SENSORS}
    if attack["type"] == "coordinated" and len(set(attack["sensors"])) < 2:
        raise ValueError(f"{describe(attack)}: a coordinated drift needs at least two different gauges.")
    for sid in attacked_sensors(attack):
        if sid not in known:
            raise ValueError(f"{describe(attack)}: '{sid}' is not one of the gauges in config.py.")

    # An approved source with real figures would just be a genuine advisory, so this type needs an unapproved one.
    if attack["type"] == "fake_source" and attack["source"] in config.APPROVED_SOURCES:
        raise ValueError(f"{describe(attack)}: '{attack['source']}' is an approved source.")

    # A stale advisory can only reuse a week the readings cover.
    if attack["type"] == "stale_advisory" and advisory_period(attack)[0] < config.START_DATE:
        raise ValueError(f"{describe(attack)}: the week it reuses starts before {config.START_DATE}.")

    # An attack during learning would be learned as normal, widening the limits instead of testing them.
    dates = attack_dates(attack)
    if dates[0] <= config.LEARN_END or dates[-1] > config.END_DATE:
        raise ValueError(f"{describe(attack)}: attacks must fall between {config.LEARN_END} and "
                         f"{config.END_DATE}, after the learning period.")


class Attacker:
    def __init__(self, plan):
        for attack in plan:
            check_attack(attack)
        self.plan = plan

        # Sensor attacks are keyed by (gauge, date), so each reading needs only one lookup to find its attacks.
        self.targets = {}

        # Advisory attacks are keyed by the date they go out.
        self.advisory_targets = {}

        for attack_id, attack in enumerate(plan):
            if attack["type"] in ADVISORY_TYPES:
                self.advisory_targets.setdefault(attack["date"], []).append(attack_id)
                continue
            for sid in attacked_sensors(attack):
                for d in attack_dates(attack):
                    self.targets.setdefault((sid, d), []).append(attack_id)

        # The value a flatline repeats, captured from the real reading on its first day.
        self.frozen = {}

        # Numbers the fake advisories as ADV-F1, ADV-F2 and so on, only so the score can tell them apart.
        self.fake_count = 0

        # The ground truth (what was changed, kept separate so detection can later be marked against it).
        self.log = []

    def apply(self, sensor_id, date, flow):
        """Return the flow as the attacker wants it seen, logging any change."""
        for attack_id in self.targets.get((sensor_id, date), []):
            attack = self.plan[attack_id]
            real = flow

            if attack["type"] == "spike":
                flow = round(real * attack["factor"], 2)
            elif attack["type"] in ("drift", "coordinated"):
                # Each day adds the same percentage on top of the last, so no single day looks unusual.
                day_number = attack_dates(attack).index(date) + 1
                flow = round(real * (1 + attack["rate"]) ** day_number, 2)
            else:
                # A stuck gauge keeps repeating whatever it last reported before it froze.
                flow = self.frozen.setdefault(attack_id, real)

            self.log.append({"attack": attack_id, "type": attack["type"], "date": date,
                             "sensor": sensor_id, "real": real, "fake": flow})
        return flow

    def fake_advisories(self, date, readings_by_date):
        """Return the fake advisories planned for this date, logging each one."""
        fakes = []
        for attack_id in self.advisory_targets.get(date, []):
            attack = self.plan[attack_id]
            start, end = advisory_period(attack)

            # The figures for the week the advisory names, which a fake source or a stale notice quotes as they are.
            real = weekly_figures(readings_by_date, start, end)
            if real is None:
                continue

            figures = (attack["avg_flow_ml"], attack["change_pct"] / 100) if attack["type"] == "fake_figures" else real

            # A stale notice reuses a genuine old week under the genuine source, so only its dates give it away.
            source = attack.get("source", config.APPROVED_SOURCES[0])

            self.fake_count += 1
            advisory = make_advisory(f"ADV-F{self.fake_count}", date, start, end, source, *figures)
            fakes.append(advisory)

            # Advisories have no gauge, so the advisory's ID takes that slot and scoring treats it like any other attack.
            self.log.append({"attack": attack_id, "type": attack["type"], "date": date, "sensor": advisory["id"],
                             "real": (round(real[0], 1), round(real[1] * 100)),
                             "fake": (advisory["avg_flow_ml"], advisory["change_pct"])})
        return fakes


def tampered_advisories(advisories, real_by_date):
    """Return (advisory, real flow, real change) for each advisory whose figures only hold because readings were tampered.

    These are the genuine notices in a coordinated attack: they match the readings the agency saw, so the advisory
    check passes, but they don't match what the rivers really did.
    """
    tampered = []
    for advisory in advisories:
        real = weekly_figures(real_by_date, advisory["period_start"], advisory["period_end"])
        if real is None:
            continue
        flow, change = real
        if (abs(advisory["avg_flow_ml"] - flow) > config.ADVISORY_FLOW_TOLERANCE_ML
                or abs(advisory["change_pct"] - change * 100) > config.ADVISORY_CHANGE_TOLERANCE_PCT):
            tampered.append((advisory, flow, change))
    return tampered


def score(alerts, attacker):
    """Mark the alerts against the attack log, returning lists of caught, caught late and missed attacks, and false alarms."""
    alert_keys = {(a["date"], a["sensor"]) for a in alerts}
    attacked_keys = {(e["date"], e["sensor"]) for e in attacker.log}

    # An alert the day an attack stops, on that gauge, is caused by the snap-back rather than being false.
    end_keys = {(day_after(attacker.plan[e["attack"]]), e["sensor"]) for e in attacker.log}

    caught, caught_late, missed = [], [], []
    for attack_id in sorted({e["attack"] for e in attacker.log}):
        attack = attacker.plan[attack_id]
        keys = {(e["date"], e["sensor"]) for e in attacker.log if e["attack"] == attack_id}
        late_keys = {(day_after(attack), sensor) for _, sensor in keys}

        # Caught means an alert on the right gauge (or advisory) while the attack was running.
        if keys & alert_keys:
            caught.append(attack)
        elif late_keys & alert_keys:
            caught_late.append(attack)
        else:
            missed.append(attack)

    false_alarms = sorted(alert_keys - attacked_keys - end_keys)
    return caught, caught_late, missed, false_alarms
