"""Spike detection: flags a sensor whose reading is far out of line with the other sensors that day."""
from statistics import median

import config


class Detector:
    def __init__(self):
        # Each sensor's last trusted river level, so a flagged value never becomes tomorrow's baseline.
        self.last_level = {}

    def check_day(self, date, readings):
        """Return a list of alerts for one day, given {sensor_id: (rainfall_mm, river_level_m) or None}."""
        alerts = []
        present = {sid: r for sid, r in readings.items() if r is not None}

        # Rainfall is compared directly, because sensors in the same area see much the same weather.
        for sid, (rain, _) in present.items():
            others = [r[0] for other, r in present.items() if other != sid]

            # A median of fewer than three sensors can be dragged off by a single bad one.
            if len(others) < 3:
                continue

            expected = median(others)
            gap = abs(rain - expected)

            # Both limits must be passed, so small differences on light days and normal spread on heavy days are ignored.
            if gap > max(config.RAIN_ALERT_MM, config.RAIN_ALERT_RATIO * expected):
                alerts.append(self._alert(date, sid, "rainfall_mm", rain,
                                          f"{rain:.1f} mm vs {expected:.1f} mm from the other sensors"))

        # River levels differ by site, so the daily rise or fall is compared instead of the level itself.
        changes = {sid: r[1] - self.last_level[sid] for sid, r in present.items() if sid in self.last_level}
        flagged_level = set()

        for sid, change in changes.items():
            others = [c for other, c in changes.items() if other != sid]
            if len(others) < 3:
                continue

            expected = median(others)
            if abs(change - expected) > config.LEVEL_ALERT_M:
                level = present[sid][1]
                flagged_level.add(sid)
                alerts.append(self._alert(date, sid, "river_level_m", level,
                                          f"changed {change:+.2f} m vs {expected:+.2f} m for the other sensors"))

        # Only unflagged levels are trusted as the next day's starting point.
        for sid, r in present.items():
            if sid not in flagged_level:
                self.last_level[sid] = r[1]

        return alerts

    @staticmethod
    def _alert(date, sensor_id, field, value, reason):
        return {"date": date, "sensor": sensor_id, "field": field, "value": value, "reason": reason}
