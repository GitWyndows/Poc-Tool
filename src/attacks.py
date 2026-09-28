"""Attacks on sensor data (spikes, flatlines, drift) and on public advisories (fake figures, fake source), all logged."""
from datetime import date, timedelta

import config
from advisories import make_advisory, weekly_figures

# The two values a reading holds, in the order Sensor.read() returns them.
FIELDS = ("rainfall_mm", "river_level_m")
SENSOR_TYPES = ("spike", "flatline", "drift")
ADVISORY_TYPES = ("fake_figures", "fake_source")
TYPES = SENSOR_TYPES + ADVISORY_TYPES


def attack_dates(attack):
    """Return every date an attack covers, as "YYYY-MM-DD" strings."""
    # Spikes and fake advisories each happen on a single day.
    if attack["type"] == "spike" or attack["type"] in ADVISORY_TYPES:
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
    if attack["type"] == "fake_figures":
        return f"fake figures posing as {attack['source']} on {attack['date']}"
    if attack["type"] == "fake_source":
        return f"fake advisory from '{attack['source']}' on {attack['date']}"
    dates = attack_dates(attack)
    if attack["type"] == "drift":
        return (f"drift on {attack['sensor']} {attack['field']} of {attack['rate']:+.2f} a day "
                f"from {dates[0]} to {dates[-1]}")
    return f"flatline on {attack['sensor']} {attack['field']} from {dates[0]} to {dates[-1]}"


def check_advisory_attack(attack):
    """Raise a clear error if a planned fake advisory is missing something or contradicts itself."""
    needed = ["date", "period_start", "period_end", "source"]
    if attack["type"] == "fake_figures":
        needed += ["avg_rain_mm", "avg_level_change_m"]

    for key in needed:
        if key not in attack:
            raise ValueError(f"{attack['type']} attack is missing '{key}'.")

    if attack["period_end"] < attack["period_start"]:
        raise ValueError(f"{attack['type']} attack period ends before it starts.")

    # An approved source with real figures would just be a genuine advisory, so this type needs an unapproved one.
    if attack["type"] == "fake_source" and attack["source"] in config.APPROVED_SOURCES:
        raise ValueError(f"fake_source attack uses '{attack['source']}', which is an approved source.")


class Attacker:
    def __init__(self, plan):
        # Checking the plan up front means a typo in config.py fails straight away instead of silently doing nothing.
        for attack in plan:
            if attack.get("type") not in TYPES:
                raise ValueError(f"Unknown attack type '{attack.get('type')}'. Use one of {TYPES}.")

            if attack["type"] in ADVISORY_TYPES:
                check_advisory_attack(attack)
                continue

            if attack["field"] not in FIELDS:
                raise ValueError(f"Unknown field '{attack['field']}' in attack plan. Use one of {FIELDS}.")

            # Rain arrives as separate daily amounts, so a slow creep only makes sense for river level.
            if attack["type"] == "drift" and attack["field"] != "river_level_m":
                raise ValueError("Drift attacks only work on river_level_m.")

        self.plan = plan

        # Sensor attacks are keyed by (sensor, date), so each reading needs only one lookup to find its attacks.
        self.targets = {}

        # Fake advisories are keyed by the date they go out.
        self.advisory_targets = {}

        for attack_id, attack in enumerate(plan):
            if attack["type"] in ADVISORY_TYPES:
                self.advisory_targets.setdefault(attack["date"], []).append(attack_id)
                continue
            for d in attack_dates(attack):
                self.targets.setdefault((attack["sensor"], d), []).append(attack_id)

        # The value a flatline repeats, captured from the real reading on its first day.
        self.frozen = {}

        # Numbers the fake advisories as ADV-F1, ADV-F2 and so on, only so the score can tell them apart.
        self.fake_count = 0

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

    def fake_advisories(self, date, readings_by_date):
        """Return the fake advisories planned for this date, logging each one."""
        fakes = []

        for attack_id in self.advisory_targets.get(date, []):
            attack = self.plan[attack_id]

            # What an honest advisory for that period would have said, kept for the log.
            real = weekly_figures(readings_by_date, attack["period_start"], attack["period_end"])

            if attack["type"] == "fake_figures":
                figures = (attack["avg_rain_mm"], attack["avg_level_change_m"])
            else:
                # Copying the real figures means the numbers hold up, leaving only the source to give it away.
                if real is None:
                    continue
                figures = real

            self.fake_count += 1
            advisory = make_advisory(f"ADV-F{self.fake_count}", date, attack["period_start"],
                                     attack["period_end"], attack["source"], *figures)
            fakes.append(advisory)

            # Advisories have no sensor, so the advisory's ID takes that slot and scoring treats it like any other attack.
            self.log.append({
                "attack": attack_id,
                "type": attack["type"],
                "date": date,
                "sensor": advisory["id"],
                "field": "advisory",
                "real": None if real is None else (round(real[0], 1), round(real[1], 2)),
                "fake": (advisory["avg_rain_mm"], advisory["avg_level_change_m"]),
            })

        return fakes

    def unused(self):
        """Return planned attacks that never ran, usually from a wrong sensor ID or date."""
        ran = {entry["attack"] for entry in self.log}
        return [a for attack_id, a in enumerate(self.plan) if attack_id not in ran]
