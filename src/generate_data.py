"""Creates data/readings.csv with fake daily readings for all 8 sensors.

    python src/generate_data.py

How the numbers are made:
  - Rainfall: each day the whole area either gets rain or it doesn't.
    On rainy days each sensor gets a slightly different amount, so nearby
    sensors roughly agree (like real weather).
  - River level: every sensor has its own normal level. Rain pushes the
    level up and it slowly drops back down on dry days.
"""
import csv
import random
from datetime import date, timedelta

import config

# About 15 rain days a month (just picked at random although am told fewer than the average Perth winter).
RAIN_CHANCE = 0.50

# Gives roughly 105 mm a month (about 25% below a typical Perth winter).
AVG_RAIN_MM = 7.0

# Keeping 85% each day makes the river fall gradually, as a real catchment drains.
DRAIN_RATE = 0.85

# Converts rain to river rise, so a 10 mm day lifts the level by about 20 cm.
RAIN_TO_LEVEL = 0.02


def main():
    # A fixed seed means every team member generates the identical file.
    random.seed(config.RANDOM_SEED)
    start = date.fromisoformat(config.START_DATE)

    # Sensors get different normal levels, since real rivers don't all sit at the same height.
    base_level = {sid: random.uniform(0.8, 1.5) for sid, _ in config.SENSORS}
    extra_water = {sid: 0.0 for sid, _ in config.SENSORS}

    # Creating the folder first stops the write failing on a fresh copy of the repo.
    config.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    # newline="" and a plain "\n" stop Windows adding blank rows or different line endings.
    with open(config.DATA_FILE, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["date", "sensor_id", "rainfall_mm", "river_level_m"])

        for day in range(config.NUM_DAYS):
            today = start + timedelta(days=day)

            # Rain is decided once for the whole area, because nearby sensors see the same weather.
            # expovariate makes light rain common and heavy downpours rare, like real rainfall.
            area_rain = random.expovariate(1 / AVG_RAIN_MM) if random.random() < RAIN_CHANCE else 0.0

            for sid, _ in config.SENSORS:
                # A small spread per sensor, so they roughly agree without being identical.
                rain = area_rain * random.uniform(0.7, 1.3)

                # Yesterday's extra water carries over, so the river responds to rain over several days.
                extra_water[sid] = extra_water[sid] * DRAIN_RATE + rain * RAIN_TO_LEVEL
                level = base_level[sid] + extra_water[sid]

                # Rounded to the precision real gauges report.
                writer.writerow([today.isoformat(), sid, round(rain, 1), round(level, 2)])

    # Printing the count makes a short or failed write obvious straight away.
    rows = config.NUM_DAYS * len(config.SENSORS)
    print(f"Wrote {rows} readings ({config.NUM_DAYS} days x {len(config.SENSORS)} sensors) to {config.DATA_FILE}")


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
