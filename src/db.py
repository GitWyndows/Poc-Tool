import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('rainfall', 'river')),
    lat  REAL NOT NULL,
    lon  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS neighbours (
    station_id   TEXT NOT NULL REFERENCES stations(id),
    neighbour_id TEXT NOT NULL REFERENCES stations(id),
    distance_km  REAL NOT NULL,
    PRIMARY KEY (station_id, neighbour_id)
);
"""


def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
