"""Public advisories: the weekly notices an agency publishes from its sensor readings."""
from datetime import date

import config


def make_advisory(advisory_id, published, period_start, period_end, source, avg_rain_mm, avg_level_change_m):
    """Build one advisory as a dict, the same shape whether it's genuine or fake."""
    # Checked here so a broken advisory fails where it's made, not later when it's read.
    if date.fromisoformat(period_end) < date.fromisoformat(period_start):
        raise ValueError(f"{advisory_id}: period ends before it starts.")

    return {
        "id": advisory_id,
        "published": published,
        "period_start": period_start,
        "period_end": period_end,
        "source": source,
        # Rounded to what a public notice would quote, which the checker will need to allow for.
        "avg_rain_mm": round(avg_rain_mm, 1),
        "avg_level_change_m": round(avg_level_change_m, 2),
    }


def format_period(start, end):
    """Turn two ISO dates into a short range, e.g. "22-28 Jun" or "29 Jun - 5 Jul"."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if s.month == e.month:
        return f"{s.day}-{e.day} {e:%b}"
    return f"{s.day} {s:%b} - {e.day} {e:%b}"


def advisory_text(advisory):
    """The sentence the public would read, built only from the advisory's own fields."""
    change = advisory["avg_level_change_m"]
    direction = "up" if change > 0 else "down" if change < 0 else "unchanged"
    amount = f" {abs(change):.2f} m" if change else ""

    return (f"{advisory['source']} weekly update "
            f"({format_period(advisory['period_start'], advisory['period_end'])}): "
            f"average rainfall {advisory['avg_rain_mm']:.1f} mm, river levels {direction}{amount}.")


def weekly_figures(readings_by_date, start, end):
    """Return (average weekly rainfall, average river-level change) across the sensors, or None if there's no data."""
    # ISO date strings sort in date order, so a plain comparison picks out the period.
    days = [d for d in sorted(readings_by_date) if start <= d <= end]

    # Each sensor's rainfall for the week is added up first, then those totals are averaged across the sensors.
    totals = {}
    for d in days:
        for sid, reading in readings_by_date[d].items():
            if reading is not None:
                totals[sid] = totals.get(sid, 0.0) + reading[0]

    # The change is measured from the first day of the period to the last, for sensors that reported on both.
    first = readings_by_date.get(start, {})
    last = readings_by_date.get(end, {})
    changes = [last[sid][1] - first[sid][1] for sid in first if first.get(sid) and last.get(sid)]

    if not totals or not changes:
        return None
    return sum(totals.values()) / len(totals), sum(changes) / len(changes)


class AdvisoryWriter:
    """Publishes a genuine advisory every few days from the readings as reported."""

    def __init__(self, source=None):
        self.source = source or config.APPROVED_SOURCES[0]

        # Every day's reported readings, so any period can be looked back over.
        self.readings_by_date = {}

        # The days collected since the last advisory went out.
        self.period = []
        self.count = 0

    def record(self, date, readings):
        """Store one day's readings, and return an advisory if one is due today, otherwise None."""
        # The agency only has what its own system reports, so tampered readings end up in its advisories too.
        self.readings_by_date[date] = dict(readings)
        self.period.append(date)

        if len(self.period) < config.ADVISORY_EVERY_DAYS:
            return None

        start, end = self.period[0], self.period[-1]
        self.period = []

        figures = weekly_figures(self.readings_by_date, start, end)
        if figures is None:
            return None

        # Published on the last day of the period, so the notice appears as soon as the week is complete.
        self.count += 1
        return make_advisory(f"ADV-{self.count:02d}", end, start, end, self.source, *figures)


# Running this file directly prints every advisory for the 90 days and whether the checker accepts it.
if __name__ == "__main__":
    import sys

    from attacks import Attacker
    from detection import Detector
    from main import load_sensors

    sensors, dates = load_sensors()
    attacking = "--attack" in sys.argv
    attacker = Attacker(config.ATTACKS + config.ADVISORY_ATTACKS if attacking else [])
    writer = AdvisoryWriter()
    detector = Detector()

    for d in dates:
        readings = {s.id: attacker.apply(s.id, d, s.read(d)) for s in sensors}
        detector.check_day(d, readings)

        published = [writer.record(d, readings)] + attacker.fake_advisories(d, writer.readings_by_date)
        for advisory in filter(None, published):
            alerts = detector.check_advisory(advisory)
            print(f"{advisory['id']:<7} {advisory_text(advisory)}")
            print(f"        {'ALERT: ' + alerts[0]['reason'] if alerts else 'OK'}")
