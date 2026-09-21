"""False data injection: replaces what a sensor reports on planned days and logs every change."""

# The two values a reading holds, in the order Sensor.read() returns them.
FIELDS = ("rainfall_mm", "river_level_m")


class Attacker:
    def __init__(self, plan):
        # Checking fields up front means a typo in config.py fails straight away instead of silently doing nothing.
        for attack in plan:
            if attack["field"] not in FIELDS:
                raise ValueError(f"Unknown field '{attack['field']}' in attack plan. Use one of {FIELDS}.")

        # Keyed by (sensor, date) so each reading needs only one lookup to see if it's a target.
        self.plan = {(a["sensor"], a["date"]): a for a in plan}

        # The ground truth (what was changed, kept separate so detection can later be marked against it.
        self.log = []

    def apply(self, sensor_id, date, reading):
        """Return the reading as the attacker wants it seen, logging any change."""
        attack = self.plan.get((sensor_id, date))

        # Most readings pass through untouched, and a missing reading has nothing to tamper with.
        if attack is None or reading is None:
            return reading

        # Tuples can't be edited, so the tampered reading is built as a new one.
        values = list(reading)
        i = FIELDS.index(attack["field"])
        real_value = values[i]
        values[i] = attack["value"]

        self.log.append({
            "date": date,
            "sensor": sensor_id,
            "field": attack["field"],
            "real": real_value,
            "fake": attack["value"],
        })
        return tuple(values)

    def unused(self):
        """Return planned attacks that never ran, usually from a wrong sensor ID or date."""
        ran = {(entry["sensor"], entry["date"]) for entry in self.log}
        return [a for key, a in self.plan.items() if key not in ran]
