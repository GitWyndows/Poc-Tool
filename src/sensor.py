"""A single field sensor that reports rainfall and river level."""


class Sensor:
    def __init__(self, sensor_id, name):
        self.id = sensor_id
        self.name = name

        # Keyed by date so a day's reading is found straight away, where a list would need searching.
        self.readings = {}

    def add_reading(self, date, rainfall_mm, river_level_m):
        """Store one day of data for this sensor."""
        # A tuple so a stored reading can't be changed by accident. A repeated date silently overwrites the earlier one.
        self.readings[date] = (rainfall_mm, river_level_m)

    def read(self, date):
        """Return (rainfall_mm, river_level_m) for a date, or None if missing."""
        # .get() returns None rather than crashing, since real sensors do drop out.
        return self.readings.get(date)
