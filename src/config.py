from pathlib import Path

# Built from this file's location, so the CSV is found whichever folder the scripts are run from.
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "readings.csv"

# Each (id, name) sensor measures both rainfall and river level. Names are placeholders until the team picks real stations.
SENSORS = [
    ("S1", "Placeholder sensor 1"),
    ("S2", "Placeholder sensor 2"),
    ("S3", "Placeholder sensor 3"),
    ("S4", "Placeholder sensor 4"),
    ("S5", "Placeholder sensor 5"),
    ("S6", "Placeholder sensor 6"),
    ("S7", "Placeholder sensor 7"),
    ("S8", "Placeholder sensor 8"),
]

# June to August covers Perth's wet season, where drought shows up as a drier-than-normal winter.
START_DATE = "2026-06-01"

# Matches the roughly 90-day replay window in the project proposal.
NUM_DAYS = 90

# A fixed seed means everyone generates the same data, so test results can be compared.
RANDOM_SEED = 42
