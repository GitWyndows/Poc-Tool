"""A single stream gauge that reports daily flow."""


class Sensor:
    def __init__(self, sensor_id, name):
        self.id = sensor_id
        self.name = name

        # Keyed by date so a day's flow is found straight away, where a list would need searching.
        self.readings = {}

    def add_reading(self, date, flow_ml):
        """Store one day's flow, in megalitres."""
        self.readings[date] = flow_ml

    def read(self, date):
        """Return the flow in megalitres for a date, or None if there isn't one."""
        return self.readings.get(date)
