# Project 6 - Proof of Concept Tool

CSG3101 Applied Project, Group 3.

A drought monitoring tool that replays real streamflow data and detects tampering with
sensor readings and fake or inconsistent public advisories.

## Setup

1. On the GitHub repo page, click Code > Download ZIP.
2. Unzip the file and open the folder
3. Open a terminal in that folder (right click in directory and click "Open in Terminal").

**Note:** Try using `python3` if `python` doesn't work.

## Usage

The tool replays daily streamflow from five DWER stream gauges for June to August 2026,
printing each day as a table.

```
python src/main.py                      # all 92 days
python src/main.py --days 20            # first 20 days only
python src/main.py --delay 1            # one day per second, like a live feed
python src/main.py > out.txt            # save the output to a file
python src/main.py --help               # list all options
```

Tampering detection, attacks and public advisories are being rebuilt for real streamflow
data and will return in upcoming updates.

## Data

`data/stream_flow.csv` holds daily streamflow in megalitres (ML/day) for 1 June to
31 August 2026, one row per gauge per day:

```
date,sensor_id,flow_ml
2026-06-01,607022,66.35
```

| Gauge | Name |
|---|---|
| 607022 | Lefroy Brook - Cascades |
| 607013 | Lefroy Brook - Rainbow Trail |
| 608171 | Fly Brook - Boat Landing Road |
| 608002 | Carey Brook - Staircase Rd |
| 608151 | Donnelly River - Strickland |

Source: Department of Water and Environmental Regulation (DWER), Water Information
Reporting, daily total stream discharge volume, exported 4 October 2026. DWER rates all
values in this period at +/-10% uncertainty.

The tool checks the file strictly before running and stops with a list of problems if the
header is wrong, a gauge is unknown or missing, a day is missing or repeated, or a value
isn't a number of zero or more.
