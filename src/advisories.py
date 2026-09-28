"""Public advisories: the weekly notices an agency publishes from its sensor readings."""
from datetime import date


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


# Running this file directly shows what an advisory looks like, without needing the rest of the tool.
if __name__ == "__main__":
    import config

    genuine = make_advisory("ADV-04", "2026-06-29", "2026-06-22", "2026-06-28",
                            config.APPROVED_SOURCES[0], 24.63, -0.1249)
    print(genuine)
    print(advisory_text(genuine))
    print()

    fake = make_advisory("ADV-05", "2026-07-06", "2026-06-29", "2026-07-05",
                         "WA Water Watch", 3.0, 0.0)
    print(fake)
    print(advisory_text(fake))
