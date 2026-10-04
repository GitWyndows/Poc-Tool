"""Settings shared by every script, so a change here applies everywhere."""
from pathlib import Path

# Built from this file's location, so the CSV is found whichever folder the scripts are run from.
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "stream_flow.csv"

# The five DWER stream gauges in the Warren and Donnelly catchments, as (station number, name).
SENSORS = [
    ("607022", "Lefroy Brook - Cascades"),
    ("607013", "Lefroy Brook - Rainbow Trail"),
    ("608171", "Fly Brook - Boat Landing Road"),
    ("608002", "Carey Brook - Staircase Rd"),
    ("608151", "Donnelly River - Strickland"),
]

# The replay period. The data file must cover every one of these days for every gauge.
START_DATE = "2026-06-01"
END_DATE = "2026-08-31"

# June is treated as clean and used to learn how much the gauges naturally disagree; checks start the day after.
LEARN_END = "2026-06-30"

# A day's change is flagged when its gap from the other gauges is 1.5 times the biggest gap seen while learning.
JUMP_MARGIN = 1.5

# A gauge is flagged as stuck after reporting the exact same value this many days in a row.
FLATLINE_DAYS = 4

# Other gauges only count as moving if their flow changed by about 5% or more over those days (0.05 in logs).
FLATLINE_MIN_MOVE = 0.05

# Drift is the total of a gauge's daily gaps from the others over this many days.
DRIFT_DAYS = 10

# That total is flagged when it's 1.5 times the biggest total seen while learning.
DRIFT_MARGIN = 1.5

# The settings below are still set for the old rainfall and river-level data, until those parts are rebuilt for flow.

# Planned attacks, only used with --attack. Spikes fake one day, flatlines freeze a sensor, and drift adds a little more each day.
ATTACKS = [
    {"type": "spike", "sensor": "S3", "date": "2026-06-13", "field": "rainfall_mm", "value": 80.0},
    {"type": "spike", "sensor": "S6", "date": "2026-07-15", "field": "rainfall_mm", "value": 45.0},
    {"type": "spike", "sensor": "S5", "date": "2026-08-10", "field": "river_level_m", "value": 3.20},
    {"type": "flatline", "sensor": "S7", "start": "2026-06-26", "days": 7, "field": "river_level_m"},
    {"type": "drift", "sensor": "S2", "start": "2026-07-18", "days": 14, "field": "river_level_m", "rate": 0.06},
]

# Advisories from any other source are treated as untrustworthy, however believable their figures.
APPROVED_SOURCES = ["Water Corporation", "Bureau of Meteorology", "Department of Water and Environmental Regulation"]

# A genuine advisory is published every this many days, covering the days since the last one.
ADVISORY_EVERY_DAYS = 7

# Planned fake advisories, only used with --attack. Fake figures pose as an approved source with made-up numbers,
# while a fake source quotes the real numbers under a name that isn't approved.
ADVISORY_ATTACKS = [
    {"type": "fake_figures", "date": "2026-06-28", "period_start": "2026-06-22", "period_end": "2026-06-28",
     "source": "Water Corporation", "avg_rain_mm": 6.5, "avg_level_change_m": -0.85},
    {"type": "fake_source", "date": "2026-08-16", "period_start": "2026-08-10", "period_end": "2026-08-16",
     "source": "WA Water Watch"},
]
