"""Attacks on sensor data: single-day spikes, multi-day flatlines and slow drift, with every change logged."""
from datetime import date, timedelta

# The two values a reading holds, in the order Sensor.read() returns them.
FIELDS = ("rainfall_mm", "river_level_m")
TYPES = ("spike", "flatline", "drift")


def attack_dates(attack):
    """Return every date an attack covers, as "YYYY-MM-DD" strings."""
    if attack["type"] == "spike":
        return [attack["date"]]

    start = date.fromisoformat(attack["start"])
    return [(start + timedelta(days=i)).isoformat() for i in range(attack["days"])]


def day_after(attack):
    """The first date after an attack ends, when a tampered sensor snaps back to its real value."""
    last = date.fromisoformat(attack_dates(attack)[-1])
    return (last + timedelta(days=1)).isoformat()


def describe(attack):
    """A short plain-English summary of an attack, for printing."""
    if attack["type"] == "spike":
        return f"spike on {attack['sensor']} {attack['field']} on {attack['date']}"
    dates = attack_dates(attack)
    if attack["type"] == "drift":
        return (f"drift on {attack['sensor']} {attack['field']} of {attack['rate']:+.2f} a day "
                f"from {dates[0]} to {dates[-1]}")
    return f"flatline on {attack['sensor']} {attack['field']} from {dates[0]} to {dates[-1]}"


class Attacker:
    def __init__(self, plan):
        # Checking the plan up front means a typo in config.py fails straight away instead of silently doing nothing.
        for attack in plan:
            if attack.get("type") not in TYPES:
                raise ValueError(f"Unknown attack type '{attack.get('type')}'. Use one of {TYPES}.")
            if attack["field"] not in FIELDS:
                raise ValueError(f"Unknown field '{attack['field']}' in attack plan. Use one of {FIELDS}.")

            # Rain arrives as separate daily amounts, so a slow creep only makes sense for river level.
            if attack["type"] == "drift" and attack["field"] != "river_level_m":
                raise ValueError("Drift attacks only work on river_level_m.")

        self.plan = plan

        # Keyed by (sensor, date) so each reading needs only one lookup to find the attacks aimed at it.
        self.targets = {}
        for attack_id, attack in enumerate(plan):
            for d in attack_dates(attack):
                self.targets.setdefault((attack["sensor"], d), []).append(attack_id)

        # The value a flatline repeats, captured from the real reading on its first day.
        self.frozen = {}

        # The ground truth: what was changed, kept separate so detection can later be marked against it.
        self.log = []

    def apply(self, sensor_id, date, reading):
        """Return the reading as the attacker wants it seen, logging any change."""
        attack_ids = self.targets.get((sensor_id, date))

        # Most readings pass through untouched, and a missing reading has nothing to tamper with.
        if attack_ids is None or reading is None:
            return reading

        # Tuples can't be edited, so the tampered reading is built as a new one.
        values = list(reading)

        for attack_id in attack_ids:
            attack = self.plan[attack_id]
            i = FIELDS.index(attack["field"])
            real_value = values[i]

            if attack["type"] == "spike":
                values[i] = attack["value"]
            elif attack["type"] == "drift":
                # The offset grows by the same amount each day, so no single day looks unusual.
                day_number = attack_dates(attack).index(date) + 1
                values[i] = round(real_value + attack["rate"] * day_number, 2)
            else:
                # A stuck sensor keeps repeating whatever it last reported before it froze.
                self.frozen.setdefault(attack_id, real_value)
                values[i] = self.frozen[attack_id]

            self.log.append({
                "attack": attack_id,
                "type": attack["type"],
                "date": date,
                "sensor": sensor_id,
                "field": attack["field"],
                "real": real_value,
                "fake": values[i],
            })

        return tuple(values)

    def unused(self):
        """Return planned attacks that never ran, usually from a wrong sensor ID or date."""
        ran = {entry["attack"] for entry in self.log}
        return [a for attack_id, a in enumerate(self.plan) if attack_id not in ran]
