"""Attacks on gauge readings (spikes, flatlines, drift), all logged so detection can be scored against them."""
from datetime import date, timedelta

import config

TYPES = ("spike", "flatline", "drift")

# What each attack type must say, so a typo in config.py fails straight away instead of silently doing nothing.
NEEDED = {
    "spike": ["sensor", "date", "factor"],
    "flatline": ["sensor", "start", "days"],
    "drift": ["sensor", "start", "days", "rate"],
}


def attack_dates(attack):
    """Return every date an attack covers, as "YYYY-MM-DD" strings."""
    # A spike happens on a single day.
    if attack["type"] == "spike":
        return [attack["date"]]

    start = date.fromisoformat(attack["start"])
    return [(start + timedelta(days=i)).isoformat() for i in range(attack["days"])]


def day_after(attack):
    """The first date after an attack ends, when a tampered gauge snaps back to its real value."""
    last = date.fromisoformat(attack_dates(attack)[-1])
    return (last + timedelta(days=1)).isoformat()


def describe(attack):
    """A short plain-English summary of an attack, for printing."""
    if attack["type"] == "spike":
        return f"spike on {attack['sensor']} of x{attack['factor']} on {attack['date']}"

    dates = attack_dates(attack)
    if attack["type"] == "drift":
        return f"drift on {attack['sensor']} of {attack['rate']:+.0%} a day from {dates[0]} to {dates[-1]}"
    return f"flatline on {attack['sensor']} from {dates[0]} to {dates[-1]}"


def check_attack(attack):
    """Raise a clear error if a planned attack is missing something or falls outside the checked period."""
    if attack.get("type") not in TYPES:
        raise ValueError(f"Unknown attack type '{attack.get('type')}'. Use one of {TYPES}.")

    for key in NEEDED[attack["type"]]:
        if key not in attack:
            raise ValueError(f"{attack['type']} attack is missing '{key}'.")

    if attack["sensor"] not in {sid for sid, _ in config.SENSORS}:
        raise ValueError(f"{describe(attack)}: '{attack['sensor']}' is not one of the gauges in config.py.")

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

        # Keyed by (gauge, date), so each reading needs only one lookup to find its attacks.
        self.targets = {}
        for attack_id, attack in enumerate(plan):
            for d in attack_dates(attack):
                self.targets.setdefault((attack["sensor"], d), []).append(attack_id)

        # The value a flatline repeats, captured from the real reading on its first day.
        self.frozen = {}

        # The ground truth: what was changed, kept separate so detection can later be marked against it.
        self.log = []

    def apply(self, sensor_id, date, flow):
        """Return the flow as the attacker wants it seen, logging any change."""
        for attack_id in self.targets.get((sensor_id, date), []):
            attack = self.plan[attack_id]
            real = flow

            if attack["type"] == "spike":
                flow = round(real * attack["factor"], 2)
            elif attack["type"] == "drift":
                # Each day adds the same percentage on top of the last, so no single day looks unusual.
                day_number = attack_dates(attack).index(date) + 1
                flow = round(real * (1 + attack["rate"]) ** day_number, 2)
            else:
                # A stuck gauge keeps repeating whatever it last reported before it froze.
                flow = self.frozen.setdefault(attack_id, real)

            self.log.append({"attack": attack_id, "type": attack["type"], "date": date,
                             "sensor": sensor_id, "real": real, "fake": flow})
        return flow


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

        # Caught means an alert on the right gauge while the attack was running.
        if keys & alert_keys:
            caught.append(attack)
        elif (day_after(attack), attack["sensor"]) in alert_keys:
            caught_late.append(attack)
        else:
            missed.append(attack)

    false_alarms = sorted(alert_keys - attacked_keys - end_keys)
    return caught, caught_late, missed, false_alarms
