# Project 6 - Proof of Concept Tool

CSG3101 Applied Project, Group 3.

A drought monitoring tool that replays real streamflow data and detects tampering with
sensor readings and fake or inconsistent public advisories.

## Setup (Tested on Clean Windows 11 Install)

1. Install Python Install Manager from the Microsoft Store.
2. On the GitHub repo page, click Code > Download ZIP, then right-click the file and choose Extract All.
3. Open the extracted folder (the one containing this README), right-click an empty space and choose Open in Terminal.
4. Run these two commands. The first downloads Python the first time it's run (answer yes if asked to add it to PATH):

```
   python --version
   python -m pip install -r requirements.txt
```

## Usage

```
python src/main.py                      # replay all 92 days
python src/main.py --days 20            # first 20 days only
python src/main.py --delay 1            # one day per second, like a live feed
python src/main.py --attack             # tamper with readings and advisories, then score the detector
python src/main.py --attack coordinated # drift two gauges together so genuine advisories quote the lie
python src/evaluate.py                  # detection and false-alarm rates for every attack
python src/dashboard.py                 # dashboard at http://127.0.0.1:5000 (Ctrl+C to stop)
python -m pytest                        # run the tests
```

June is spent learning how much the gauges normally disagree, and from 1 July any gauge that strays
further than that is flagged. Every 7 days a public advisory reports the week's combined flow, and
each advisory is checked against the readings. With `--attack`, the run ends with what was really
changed and a score: attacks caught, caught late, missed, and false alarms.

## How detection works

- **Jump:** a gauge whose daily change strays too far from the other gauges' changes.
- **Flatline:** a gauge stuck on the same value for 4 days while the others move.
- **Drift:** small daily differences that keep pointing the same way over 10 days.
- **Pair:** the two Lefroy Brook gauges are on the same stream, so their flows keep a steady ratio.
- **Advisories:** each must come from an approved source, match the readings, and cover the week just ended.

The limits are learned from June and set in `src/config.py`.

## Data

`data/stream_flow.csv` holds daily streamflow in megalitres (ML/day) for 1 June to 31 August 2026:

| Gauge | Name |
|---|---|
| 607022 | Lefroy Brook - Cascades |
| 607013 | Lefroy Brook - Rainbow Trail |
| 608171 | Fly Brook - Boat Landing Road |
| 608002 | Carey Brook - Staircase Rd |
| 608151 | Donnelly River - Strickland |

Source: Department of Water and Environmental Regulation (DWER), Water Information Reporting, daily
total stream discharge volume, exported 4 October 2026 (+/-10% uncertainty).
