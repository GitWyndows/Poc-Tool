"""Public advisories: the weekly streamflow notices an agency publishes from its gauge readings."""
from datetime import date

import config


def make_advisory(advisory_id, published, period_start, period_end, source, avg_flow_ml, change):
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
        "avg_flow_ml": round(avg_flow_ml, 1),
        "change_pct": round(change * 100),
    }


def format_period(start, end):
    """Turn two ISO dates into a short range, e.g. "22-28 Jun" or "29 Jun - 5 Jul"."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if s.month == e.month:
        return f"{s.day}-{e.day} {e:%b}"
    return f"{s.day} {s:%b} - {e.day} {e:%b}"


def advisory_text(advisory):
    """The sentence the public would read, built only from the advisory's own fields."""
    change = advisory["change_pct"]
    direction = f"up {change}%" if change > 0 else f"down {-change}%" if change < 0 else "unchanged"

    return (f"{advisory['source']} weekly update "
            f"({format_period(advisory['period_start'], advisory['period_end'])}): "
            f"combined streamflow averaged {advisory['avg_flow_ml']:.1f} ML/day, {direction} over the week.")


def weekly_figures(readings_by_date, start, end):
    """Return (average combined flow in ML/day, change from the first day to the last), or None without both ends."""
    # The change needs both ends of the period, so a period the readings don't cover has no figures.
    if start not in readings_by_date or end not in readings_by_date:
        return None

    # ISO date strings sort in date order, so a plain comparison picks out the period.
    days = [d for d in sorted(readings_by_date) if start <= d <= end]

    # Combined flow adds up every gauge, which is how much water the catchments delivered that day.
    combined = [sum(readings_by_date[d].values()) for d in days]
    first, last = combined[0], combined[-1]

    # A period that starts with every stream dry has no sensible percentage change, so it's reported as none.
    change = last / first - 1 if first else 0.0
    return sum(combined) / len(combined), change


class AdvisoryWriter:
    """Publishes a genuine advisory every few days from the readings as reported."""

    def __init__(self, source=None):
        self.source = source or config.APPROVED_SOURCES[0]

        # Every day's reported readings, so any period can be looked back over.
        self.readings_by_date = {}

        # The days collected since the last advisory went out.
        self.period = []
        self.count = 0

    def record(self, date, flows):
        """Store one day's flows, and return an advisory if one is due today, otherwise None."""
        # The agency only has what its own system reports, so tampered readings end up in its advisories too.
        self.readings_by_date[date] = dict(flows)
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
