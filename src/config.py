from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "poc_tool.db"

# ---------------------------------------------------------------------------
# PLACEHOLDER STATIONS -- NOT AGREED. Do not cite these anywhere.
#
# Invented names at plausible Perth Hills coordinates, here so the pipeline
# can be built and tested before the team settles on a real catchment.
# Nothing in the code depends on which stations these are: it only needs an
# id, a type and a lat/lon. Replacing this list is a one-commit change, and
# neighbour distances recompute themselves because they are derived from
# coordinates rather than hardcoded.
#
# Criteria for the real set, when we choose it:
#   1. ONE catchment, or a small contiguous area. The detection rules
#      compare each gauge against its neighbours, which only works if
#      those gauges see broadly the same weather. Stations scattered
#      across the state have no relationship to compare against.
#   2. At least 5 rainfall and 3 river gauges. With three of a type you can
#      take a median of two neighbours; with fewer, one compromised gauge
#      is half the comparison group.
#   3. Overlapping coverage; all stations need data across the same
#      90-day window.
#
# Sources: BoM Climate Data Online (rainfall), DWER Water Information
# Reporting (river level), data.wa.gov.au (station locations).
# ---------------------------------------------------------------------------

# (id, name, type, lat, lon)
STATIONS = [
    ("R1", "Placeholder rainfall 1", "rainfall", -31.9560, 116.1640),
    ("R2", "Placeholder rainfall 2", "rainfall", -31.9010, 116.2050),
    ("R3", "Placeholder rainfall 3", "rainfall", -31.8580, 116.2610),
    ("R4", "Placeholder rainfall 4", "rainfall", -31.9720, 116.0580),
    ("R5", "Placeholder rainfall 5", "rainfall", -32.0100, 116.1290),
    ("W1", "Placeholder river 1",    "river",    -31.9450, 116.1990),
    ("W2", "Placeholder river 2",    "river",    -31.9210, 116.2530),
    ("W3", "Placeholder river 3",    "river",    -31.9880, 116.0900),
]

# Number of nearest same-type stations each gauge is compared against.
N_NEIGHBOURS = 3
