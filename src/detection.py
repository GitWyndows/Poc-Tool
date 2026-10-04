"""Detection rules for streamflow (sudden jumps, stuck gauges and slow drift, each judged against the other gauges)
and for public advisories (unapproved sources and figures that don't match the readings)."""
import math
from statistics import median

import config
from advisories import weekly_figures


def to_log(flow):
    # Logs turn doubling into the same step at 10 or 300 ML/day, and the +1 lets a dry stream read 0 without breaking.
    return math.log(flow + 1)


def percent(log_change):
    """A change in logs as a plain percentage, e.g. 0.69 becomes "+99%"."""
    return f"{math.exp(log_change) - 1:+.0%}"


class Detector:
    def __init__(self):
        # Each gauge's last trusted flow (as a log), so a flagged value never becomes tomorrow's baseline.
        self.last = {}

        # Yesterday's reported flow (as a log), and gauges flagged for a jump yesterday.
        self.last_raw = {}
        self.jumped = set()

        # Recent reported flows per gauge, just long enough to spot a flatline.
        self.history = {}

        # Flatlines already reported, so a stuck gauge raises one alert rather than one every day.
        self.flat_alerted = set()

        # Each gauge's recent daily gaps from the others, whose total shows how far it has drifted.
        self.gaps = {}

        # Gauges already reported as drifting, which stay under watch until they fall back in line.
        self.drift_alerted = set()

        # The biggest gaps seen while learning, which become each gauge's limits once checking starts.
        self.learned_jump = {}
        self.learned_drift = {}
        self.jump_limit = {}
        self.drift_limit = {}

        # Every day's flows as seen, so an advisory's figures can be checked against them.
        self.readings_by_date = {}

    def check_day(self, date, flows):
        """Return a list of alerts for one day, given {gauge_id: flow in ML/day}."""
        self.readings_by_date[date] = dict(flows)
        learning = date <= config.LEARN_END
        if not learning and not self.jump_limit:
            self._set_limits(flows)

        self._record(flows)
        alerts = [] if learning else self._check_flatline(date, flows)

        # A stuck gauge snapping back is expected, so it restarts from its next value without a check.
        for sid in self.flat_alerted:
            self.last.pop(sid, None)

        # Gauges differ hugely in size, so each day's change is compared rather than the flow itself.
        logs = {sid: to_log(f) for sid, f in flows.items()}
        changes = {sid: log - self.last[sid] for sid, log in logs.items() if sid in self.last}

        if learning:
            self._learn(changes)
        else:
            alerts += self._check_changes(date, flows, changes)

        # While learning every value is trusted; after that, only gauges with no baseline start afresh.
        for sid, log in logs.items():
            if learning or (sid not in changes and sid not in self.flat_alerted):
                self.last[sid] = log
            self.last_raw[sid] = log

        return alerts

    def _learn(self, changes):
        # June is assumed clean, so the biggest gaps seen then show how much these gauges naturally disagree.
        for sid, change in changes.items():
            others = [c for other, c in changes.items() if other != sid]
            if len(others) < 3:
                continue

            gap = change - median(others)
            self.learned_jump.setdefault(sid, []).append(abs(gap))

            self._add_gap(sid, gap)
            if len(self.gaps[sid]) == config.DRIFT_DAYS:
                self.learned_drift.setdefault(sid, []).append(abs(sum(self.gaps[sid])))

    def _set_limits(self, flows):
        # Stopping here beats guessing, since a limit learned from too few days would flag everything.
        for sid in flows:
            if sid not in self.learned_drift:
                raise ValueError(f"{sid} needs at least {config.DRIFT_DAYS + 1} days of learning "
                                 f"up to {config.LEARN_END} before checks can start.")

            # Headroom above the worst June day, since July and August will bring days a little rougher than any in June.
            self.jump_limit[sid] = config.JUMP_MARGIN * max(self.learned_jump[sid])
            self.drift_limit[sid] = config.DRIFT_MARGIN * max(self.learned_drift[sid])

    def _record(self, flows):
        # One extra day is kept so a run can be seen changing, not just sitting still.
        for sid, flow in flows.items():
            values = self.history.setdefault(sid, [])
            values.append(flow)
            del values[:-(config.FLATLINE_DAYS + 1)]

    def _is_flat(self, sid):
        # Exactly equal, since a real gauge reading to four figures almost never repeats for days.
        recent = self.history.get(sid, [])[-config.FLATLINE_DAYS:]
        return len(recent) == config.FLATLINE_DAYS and len(set(recent)) == 1

    def _has_moved(self, sid):
        # The full range over the window, so a slow steady fall still counts as moving.
        recent = self.history.get(sid, [])[-config.FLATLINE_DAYS:]
        return to_log(max(recent)) - to_log(min(recent)) >= config.FLATLINE_MIN_MOVE

    def _check_flatline(self, date, flows):
        alerts = []
        for sid in flows:
            # Once the value moves again, the gauge can be flagged afresh if it sticks later.
            if not self._is_flat(sid):
                self.flat_alerted.discard(sid)
                continue
            if sid in self.flat_alerted:
                continue

            # A flat value only matters if the others moved, since every gauge sits still in a long dry spell.
            others = [o for o in flows if o != sid and len(self.history.get(o, [])) >= config.FLATLINE_DAYS]
            moving = [o for o in others if self._has_moved(o)]
            if len(others) < 3 or len(moving) < len(others) / 2:
                continue

            self.flat_alerted.add(sid)
            alerts.append(self._alert(date, sid, "flatline", flows[sid],
                                      f"stuck at {flows[sid]} ML/day for {config.FLATLINE_DAYS} days while "
                                      f"{len(moving)} of {len(others)} other gauges changed"))
        return alerts

    def _check_changes(self, date, flows, changes):
        alerts = []

        # Gauges under watch are left out of everyone else's comparison, so a drifting gauge can't skew the median.
        trusted = {sid: c for sid, c in changes.items() if sid not in self.drift_alerted}

        for sid, change in changes.items():
            now = to_log(flows[sid])
            others = [c for other, c in trusted.items() if other != sid]

            # A median of fewer than three gauges can be dragged off by a single bad one.
            if len(others) < 3:
                self.last[sid] = now
                continue

            expected = median(others)
            gap = change - expected

            # A drifting gauge is followed without alerts, and released once its recent gaps cancel out.
            if sid in self.drift_alerted:
                self._add_gap(sid, gap)
                if abs(sum(self.gaps[sid])) <= self.drift_limit[sid] / 2:
                    self.drift_alerted.discard(sid)
                    self.gaps[sid] = []
                self.last[sid] = now
                continue

            if abs(gap) > self.jump_limit[sid]:
                # A jump that holds the next day is a lasting shift, already reported, so the new flow is accepted.
                raw_change = now - self.last_raw[sid]
                if sid in self.jumped and abs(raw_change - expected) <= self.jump_limit[sid]:
                    self.jumped.discard(sid)
                    self.last[sid] = now
                    self.gaps[sid] = []
                    continue

                # Otherwise it's flagged, and that value is never trusted as tomorrow's starting point.
                self.jumped.add(sid)
                alerts.append(self._alert(date, sid, "jump", flows[sid],
                                          f"changed {percent(change)} vs {percent(expected)} for the other gauges"))
                continue

            self.jumped.discard(sid)
            self.last[sid] = now
            self._add_gap(sid, gap)

            # Small daily gaps that keep pointing the same way add up, which is how a slow drift gives itself away.
            drift = sum(self.gaps[sid])
            if abs(drift) > self.drift_limit[sid]:
                self.drift_alerted.add(sid)
                alerts.append(self._alert(date, sid, "drift", flows[sid],
                                          f"drifted {percent(drift)} from the other gauges over "
                                          f"{len(self.gaps[sid])} days"))
        return alerts

    def _add_gap(self, sid, gap):
        # Only the last few days are kept, so old differences can't build up forever.
        self.gaps.setdefault(sid, []).append(gap)
        del self.gaps[sid][:-config.DRIFT_DAYS]

    def check_advisory(self, advisory):
        """Return a list with one alert if an advisory's source or figures don't hold up, otherwise an empty list."""
        problems = []

        # Believable figures don't make up for an unknown source, since copying real numbers is how an impersonator works.
        if advisory["source"] not in config.APPROVED_SOURCES:
            problems.append(f"source '{advisory['source']}' is not approved")

        # The figures are rebuilt from the flows the detector has seen, using the same maths as the writer.
        figures = weekly_figures(self.readings_by_date, advisory["period_start"], advisory["period_end"])
        if figures is None:
            problems.append("no readings exist for the period it describes")
        else:
            flow, change = figures
            if abs(advisory["avg_flow_ml"] - flow) > config.ADVISORY_FLOW_TOLERANCE_ML:
                problems.append(f"claims {advisory['avg_flow_ml']:.1f} ML/day vs {flow:.1f} ML/day in the readings")
            if abs(advisory["change_pct"] - change * 100) > config.ADVISORY_CHANGE_TOLERANCE_PCT:
                problems.append(f"claims a {advisory['change_pct']:+d}% change vs {change:+.0%} in the readings")

        if not problems:
            return []

        # One alert per advisory, with every problem listed, so a notice that fails both checks isn't counted twice.
        return [self._alert(advisory["published"], advisory["id"], "advisory", advisory["source"], "; ".join(problems))]

    @staticmethod
    def _alert(date, sensor_id, rule, value, reason):
        return {"date": date, "sensor": sensor_id, "rule": rule, "value": value, "reason": reason}
