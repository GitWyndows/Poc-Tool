"""Detection rules: spikes that disagree with the other sensors, and sensors stuck on one value."""
from statistics import median

import config

FIELDS = ("rainfall_mm", "river_level_m")


class Detector:
    def __init__(self):
        # Each sensor's last trusted river level, so a flagged value never becomes tomorrow's baseline.
        self.last_level = {}

        # Recent reported values per (sensor, field), just long enough to spot a flatline.
        self.history = {}

        # Flatlines already reported, so a stuck sensor raises one alert rather than one every day.
        self.flat_alerted = set()

    def check_day(self, date, readings):
        """Return a list of alerts for one day, given {sensor_id: (rainfall_mm, river_level_m) or None}."""
        present = {sid: r for sid, r in readings.items() if r is not None}
        self._record(present)

        alerts = self._check_flatline(date, present)
        alerts += self._check_rain_spike(date, present)
        alerts += self._check_river_jump(date, present)
        return alerts

    def _record(self, present):
        # One extra day is kept so a run can be seen changing, not just sitting still.
        for sid, reading in present.items():
            for i, field in enumerate(FIELDS):
                values = self.history.setdefault((sid, field), [])
                values.append(reading[i])
                del values[:-(config.FLATLINE_DAYS + 1)]

    def _is_flat(self, sid, field):
        # Exactly equal, since a real gauge reading to 0.01 m almost never repeats for days while the river moves.
        recent = self.history.get((sid, field), [])[-config.FLATLINE_DAYS:]
        return len(recent) == config.FLATLINE_DAYS and len(set(recent)) == 1

    def _has_moved(self, sid, field):
        # The full range over the window, so a slow steady fall still counts as moving.
        recent = self.history.get((sid, field), [])[-config.FLATLINE_DAYS:]
        return max(recent) - min(recent) >= config.FLATLINE_MIN_MOVE[field]

    def _check_flatline(self, date, present):
        alerts = []
        for field in FIELDS:
            for sid in present:
                key = (sid, field)

                # Once the value moves again, the sensor can be flagged afresh if it sticks later.
                if not self._is_flat(sid, field):
                    self.flat_alerted.discard(key)
                    continue
                if key in self.flat_alerted:
                    continue

                # A flat value only matters if the others moved, since every gauge reads 0 mm on a dry week.
                others = [o for o in present if o != sid and len(self.history.get((o, field), [])) >= config.FLATLINE_DAYS]
                moving = [o for o in others if self._has_moved(o, field)]
                if len(others) < 3 or len(moving) < len(others) / 2:
                    continue

                self.flat_alerted.add(key)
                value = self.history[key][-1]
                alerts.append(self._alert(date, sid, field, value,
                                          f"stuck at {value} for {config.FLATLINE_DAYS} days while "
                                          f"{len(moving)} of {len(others)} other sensors changed"))
        return alerts

    def _check_rain_spike(self, date, present):
        alerts = []

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
        return alerts

    def _check_river_jump(self, date, present):
        alerts = []

        # A stuck gauge snapping back is expected, so its first new value becomes the baseline without a check.
        for sid in present:
            if (sid, "river_level_m") in self.flat_alerted:
                self.last_level.pop(sid, None)

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

        # Only unflagged, unstuck levels are trusted as the next day's starting point.
        for sid, r in present.items():
            if sid not in flagged_level and (sid, "river_level_m") not in self.flat_alerted:
                self.last_level[sid] = r[1]

        return alerts

    @staticmethod
    def _alert(date, sensor_id, field, value, reason):
        return {"date": date, "sensor": sensor_id, "field": field, "value": value, "reason": reason}
