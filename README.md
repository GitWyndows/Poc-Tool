# Project 6 - Proof of Concept Tool

CSG3101 Applied Project, Group 3.

A drought monitoring tool that replays real streamflow data and detects tampering with
sensor readings and fake or inconsistent public advisories.

## Setup (Windows 11)

The tool runs in Docker, so nothing else needs installing and it behaves the same on every machine.

1. **Install Docker Desktop.** Download it from https://www.docker.com/products/docker-desktop and
   run the installer, leaving **Use WSL 2** ticked. Restart the computer when it asks.
2. **Start Docker Desktop.** Open it from the Start menu, accept the terms, and wait until it shows
   **Engine running**. It needs to be open whenever you use the tool.
3. **Download the project.** On the GitHub repo page, click **Code > Download ZIP**. Right-click
   the downloaded file and choose **Extract All**.
4. **Open a terminal in the project folder.** Open the extracted folder (the one containing this
   README), right-click an empty space and choose **Open in Terminal**.

## Usage

**Dashboard:**

```
docker compose up
```

Open http://localhost:5000 in a browser. The first run takes a few minutes to build; after that it
starts in seconds. Press Ctrl+C in the terminal to stop it.

The page shows a chart for each gauge, the alerts, the advisories, the attack log and the score.
Pick Clean data, Mixed attacks or Coordinated attack at the top, and use Play from day 1 to step
through the replay like a live feed.

**Command line:**

```
docker compose run --rm poc python src/main.py                      # all 92 days
docker compose run --rm poc python src/main.py --days 20            # first 20 days only
docker compose run --rm poc python src/main.py --attack             # tamper with readings and advisories, then score the detector
docker compose run --rm poc python src/main.py --attack coordinated # drift two gauges together so genuine advisories quote the lie
docker compose run --rm poc python src/evaluate.py                  # detection and false-alarm rates for every attack
docker compose run --rm poc python -m pytest                        # run the tests
```

The tool replays daily streamflow from five DWER stream gauges for June to August 2026. June is
spent learning how much the gauges normally disagree, and from 1 July any gauge that strays further
than that is flagged with an alert. Every 7 days a public advisory reports the week's combined flow,
and each advisory is checked against the readings.

With `--attack`, the run ends with the attack log (what was really changed) and a score: attacks
caught, caught late, missed, and false alarms. It also lists any genuine advisories that quoted
tampered readings. These pass every advisory check, so only the gauge checks can catch them.

After changing any code, rebuild with `docker compose build` (or `docker compose up --build`).

## Without Docker

1. Install the **Python install manager** from the Microsoft Store.
2. In a terminal in the project folder, run `python --version` (the first run downloads Python),
   then install the packages the dashboard and tests need:

```
   python -m pip install -r requirements.txt
```

3. Run the same commands without the Docker part, for example `python src/main.py --attack`,
   `python src/evaluate.py` or `python src/dashboard.py` (then open http://127.0.0.1:5000).

If typing `python` opens the Microsoft Store instead, click Start, open **Manage app execution
aliases**, and turn on the **Python** aliases.

## How detection works

- **Jump:** a gauge whose daily change strays too far from the other gauges' changes.
- **Flatline:** a gauge stuck on the exact same value for 4 days while the others move.
- **Drift:** small daily differences that keep pointing the same way over 10 days.
- **Pair:** the two Lefroy Brook gauges are on the same stream, so their flows keep a steady
  ratio. A ratio outside the June range is flagged.
- **Advisories:** each one must come from an approved source, match the readings for its week,
  and cover a full week that has just ended.

All the limits are learned from June and set in `src/config.py`.

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
