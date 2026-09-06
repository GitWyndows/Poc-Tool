"""POC Tool - proper name still under consideration.

    python src/main.py seed

Loads the catchment stations and computes neighbour relationships.
Station list is provisional, see note in config.py.
"""
import math
import sys

import config
import db


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points.

    Subtracting coordinates doesn't work because a degree of longitude is
    about 95 km near Perth and shrinks to nothing at the poles (Haversine
    accounts for the curve). The 6371.0 is the Earth's radius in km and is
    what makes the result come out in km.
    """
    r = 6371.0
    # Python trig works in radians rather than degrees.
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def seed():
    conn = db.connect()

    # Wiping first means seed can be re-run as often as we like during
    # development. A second run would otherwise hit duplicate ids or leave
    # stale rows behind. Neighbours has to go first because it references
    # stations.
    conn.execute("DELETE FROM neighbours")
    conn.execute("DELETE FROM stations")

    # The ? placeholders leave the values to SQLite, which is a habit worth
    # keeping even where the data isn't user-supplied.
    conn.executemany("INSERT INTO stations VALUES (?, ?, ?, ?, ?)", config.STATIONS)

    # Every detection rule ends up asking whether a gauge is saying
    # something its neighbours disagree with, so who sits next to whom is
    # what the rest of the tool stands on. Working it out from coordinates
    # rather than hardcoding pairs means the relationships recompute
    # themselves once real stations go in.
    rows = conn.execute("SELECT * FROM stations").fetchall()
    for a in rows:
        # Distance comes first in the tuple so that sorted() orders by it
        # without needing a key.
        dists = sorted(
            (haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]), b["id"])
            for b in rows
            # Skipping self matters because a distance of zero would sort
            # first and take a slot. Comparing like with like matters
            # because a rain gauge reads millimetres and a river gauge
            # reads metres.
            if b["id"] != a["id"] and b["type"] == a["type"]
        )
        for dist, bid in dists[:config.N_NEIGHBOURS]:
            conn.execute("INSERT INTO neighbours VALUES (?, ?, ?)",
                         (a["id"], bid, round(dist, 2)))

    # Changes sit in memory until committed and the file on disk stays as
    # it was.
    conn.commit()

    # A quick count makes a short load obvious straight away.
    n_rain = sum(1 for r in rows if r["type"] == "rainfall")
    n_river = len(rows) - n_rain
    print(f"Seeded {len(rows)} stations ({n_rain} rainfall, {n_river} river).")
    print("NOTE: station list is provisional. See config.py.\n")

    for a in rows:
        # Reading back out of the database rather than printing the list we
        # just built shows that the write actually landed.
        nb = conn.execute(
            "SELECT neighbour_id, distance_km FROM neighbours "
            "WHERE station_id = ? ORDER BY distance_km", (a["id"],)
        ).fetchall()
        near = ", ".join(f"{n['neighbour_id']} ({n['distance_km']} km)" for n in nb)
        print(f"  {a['id']}  {a['name'][:24]:<26} {a['type']:<9} -> {near}")

    # The rules take a median across a station's neighbours, and a median
    # of one value is just that value, so a single lying neighbour would
    # drag the comparison with it. Two is the practical minimum. This
    # becomes real once we pick actual stations, since a catchment with
    # only two river gauges leaves the neighbour rules doing nothing.
    thin = [a["id"] for a in rows
            if conn.execute("SELECT COUNT(*) c FROM neighbours WHERE station_id = ?",
                            (a["id"],)).fetchone()["c"] < 2]
    if thin:
        print(f"\nWARNING: {', '.join(thin)} have fewer than two neighbours. "
              f"Neighbour-based rules cannot run on them.")

    conn.close()


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    # Fine for a single command. Worth moving to argparse once replay and
    # detect land.
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        seed()
    else:
        print(__doc__)
