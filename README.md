# Project 6 - Proof of Concept Tool

CSG3101 Applied Project, Group 3.

A simulated drought monitoring system that detects tampering with sensor data
and fake or inconsistent public advisories.

## Setup

1. On the GitHub repo page, click Code > Download ZIP.
2. Unzip the file and open the folder
3. Open a terminal in that folder (right click in directory and click "Open in Terminal").

**Note:** Try using `python3` if `python` doesn't work.

## Usage

The tool replays 90 days of readings from 8 sensors. Each day prints as a
table, and any sensor that looks tampered with is marked `<-- ALERT` with a
reason underneath. A detection score is printed at the end.

```
python src/main.py                      # clean run, no attacks
python src/main.py --attack             # run with the attacks planned in src/config.py
python src/main.py --attack --days 20   # first 20 days only
python src/main.py --attack --delay 1   # one day per second, like a live feed
python src/main.py --attack > out.txt   # save the output to a file
python src/main.py --help               # list all options
```

With `--attack`, the run ends with the attack log (what was actually faked)
and the score: attacks caught, caught late, missed, and false alarms.

The sensor data in `data/readings.csv` is already included. To rebuild it
(for example, after changing a setting in `src/config.py`):

```
python src/generate_data.py
```
