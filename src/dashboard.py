"""A web dashboard for the replay: gauge charts, alerts, advisories, the attack log and the score on one page.

    python src/dashboard.py                    # then open http://127.0.0.1:5000
    python src/dashboard.py --host 0.0.0.0     # reachable from outside the machine, which Docker needs

Pick the scenario at the top of the page (clean data, mixed attacks or the coordinated attack). Play steps through
the days like a live feed, with the page moving on one day each second.
"""
import argparse
import math

from flask import Flask, abort, render_template_string, request
from markupsafe import Markup, escape

import config
from advisories import AdvisoryWriter, advisory_text
from attacks import Attacker, attacked_sensors, day_after, describe, score, tampered_advisories
from detection import Detector
from main import load_sensors, plan_for, run_day

SCENARIOS = {"clean": "Clean data", "mixed": "Mixed attacks", "coordinated": "Coordinated attack"}

# Chart size in SVG units; the browser scales it to fit, so these only set the shape.
CHART_WIDTH, CHART_HEIGHT, CHART_PAD = 600, 190, 28

app = Flask(__name__)


def build_view(scenario, days=None):
    """Replay a scenario for the first `days` days (or all of them), returning everything the page shows."""
    sensors, dates = load_sensors()
    shown = dates if days is None else dates[:days]
    plan = [] if scenario == "clean" else plan_for(scenario)

    attacker, detector, writer = Attacker(plan), Detector(), AdvisoryWriter()
    flows_by_day, alerts, advisories = {}, [], []
    for day in shown:
        flows, published, day_alerts = run_day(day, sensors, attacker, detector, writer)
        flows_by_day[day] = flows
        alerts += day_alerts
        advisories += published

    # The ground truth is only used for the attack log, the score and the shaded days, never by the detector.
    real = {day: {s.id: s.read(day) for s in sensors} for day in shown}
    caught, late, missed, false_alarms = score(alerts, attacker)
    attacked_days = {}
    for entry in attacker.log:
        attacked_days.setdefault(entry["sensor"], set()).add(entry["date"])

    flagged = {a["sensor"] for a in alerts}
    gauges = []
    for s in sensors:
        values = [flows_by_day[d][s.id] for d in shown]
        alert_days = {a["date"] for a in alerts if a["sensor"] == s.id}
        gauges.append({
            "id": s.id, "name": s.name, "latest": values[-1] if values else None,
            "alerts": len(alert_days),
            "chart": svg_chart(dates, values, alert_days, attacked_days.get(s.id, set())),
        })

    # During Play, an attack that hasn't reached its snap-back day yet is still running rather than missed.
    running = [a for a in late + missed if day_after(a) > shown[-1]]
    late = [a for a in late if a not in running]
    missed = [a for a in missed if a not in running]
    status = ({id(a): "caught" for a in caught} | {id(a): "late" for a in late} | {id(a): "missed" for a in missed}
              | {id(a): "running" for a in running})
    return {
        "scenario": scenario, "dates": dates, "shown": shown, "plan": plan,
        "gauges": gauges,
        "alerts": sorted(alerts, key=lambda a: a["date"], reverse=True),
        "advisories": [{**a, "text": advisory_text(a), "flagged": a["id"] in flagged}
                       for a in sorted(advisories, key=lambda a: (a["published"], a["id"]), reverse=True)],
        "attacks": [{"text": describe(a), "status": status.get(id(a), "not run yet"),
                     "gauges": ", ".join(attacked_sensors(a)) or "advisory"} for a in plan],
        "score": {"caught": len(caught), "late": len(late), "missed": len(missed), "running": len(running),
                  "ran": len(caught) + len(late) + len(missed) + len(running),
                  "false": len(false_alarms), "alerts": len(alerts)},
        "false_alarms": false_alarms,
        "tampered": tampered_advisories(writer.published, real) if plan else [],
        "limits": [{"id": s.id, "name": s.name, "jump": math.exp(detector.jump_limit[s.id]),
                    "drift": math.exp(detector.drift_limit[s.id])} for s in sensors if s.id in detector.jump_limit],
    }


def svg_chart(dates, values, alert_days, attacked_days):
    """Draw one gauge's flow as an inline SVG line chart, with learning shaded grey, attacks red and alerts as dots."""
    left, right, top, bottom = CHART_PAD + 14, CHART_WIDTH - 8, 8, CHART_HEIGHT - CHART_PAD
    high = max(values, default=1.0) * 1.1 or 1.0
    step = (right - left) / (len(dates) - 1)

    # The x axis always spans every day, so during Play the line grows from left to right.
    def x(i):
        return left + i * step

    def y(v):
        return bottom - (v / high) * (bottom - top)

    parts = [f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" class="chart" role="img">']

    learn_days = sum(1 for d in dates if d <= config.LEARN_END)
    parts.append(f'<rect class="learning" x="{left}" y="{top}" width="{x(learn_days - 1) - left}" '
                 f'height="{bottom - top}"><title>Learning period</title></rect>')

    # Attacked days are ground truth from the attack log, shown so the audience can see what the detector was up against.
    for i, d in enumerate(dates):
        if d in attacked_days:
            parts.append(f'<rect class="attacked" x="{x(i) - step / 2:.1f}" y="{top}" width="{step:.1f}" '
                         f'height="{bottom - top}"><title>Attacked on {d}</title></rect>')

    parts.append(f'<line class="axis" x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>')
    parts.append(f'<text class="label" x="{left - 4}" y="{top + 10}" text-anchor="end">{high:.0f}</text>')
    parts.append(f'<text class="label" x="{left - 4}" y="{bottom}" text-anchor="end">0</text>')
    for i, d in enumerate(dates):
        if d.endswith("-01"):
            month = {"06": "Jun", "07": "Jul", "08": "Aug"}.get(d[5:7], d[5:7])
            parts.append(f'<text class="label" x="{x(i):.1f}" y="{CHART_HEIGHT - 8}">{month}</text>')

    if values:
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
        parts.append(f'<polyline class="flow" points="{points}"/>')
    for i, v in enumerate(values):
        if dates[i] in alert_days:
            parts.append(f'<circle class="alert-dot" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4">'
                         f'<title>Alert on {dates[i]}: {v:.2f} ML/day</title></circle>')

    parts.append("</svg>")
    return Markup("".join(parts))


@app.route("/")
def index():
    scenario = request.args.get("scenario", "clean")
    if scenario not in SCENARIOS:
        abort(400, f"Unknown scenario '{escape(scenario)}'. Use one of: {', '.join(SCENARIOS)}.")

    # Play shows the first few days and asks the browser to load the next day a second later, like a live feed.
    total = len(load_sensors()[1])
    day = request.args.get("day", type=int)
    days = None if day is None else max(1, min(day, total))
    playing = request.args.get("play") == "1" and days is not None and days < total

    view = build_view(scenario, days)
    return render_template_string(PAGE, v=view, scenarios=SCENARIOS, playing=playing, total=total,
                                  next_day=(days or total) + 1, learn_end=config.LEARN_END)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{% if playing %}<meta http-equiv="refresh" content="1; url=?scenario={{ v.scenario }}&day={{ next_day }}&play=1">{% endif %}
<title>Streamflow Tamper Watch</title>
<style>
  :root { --bg: #f6f7f9; --card: #fff; --text: #1d2330; --muted: #5d6675; --line: #dde1e7;
          --flow: #1f6feb; --alert: #d1242f; --attack: rgba(209, 36, 47, .14); --learn: rgba(93, 102, 117, .10);
          --ok: #1a7f37; --warn: #9a6700; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0f1218; --card: #171b23; --text: #e6e9ef; --muted: #9aa3b2; --line: #2a303b;
            --flow: #58a6ff; --alert: #ff6b6b; --attack: rgba(255, 107, 107, .18); --learn: rgba(154, 163, 178, .12);
            --ok: #3fb950; --warn: #d29922; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.45 system-ui, sans-serif; }
  main { max-width: 1200px; margin: 0 auto; padding: 20px 16px 40px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 0 0 10px; }
  .sub { color: var(--muted); margin: 0 0 16px; }
  nav { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 16px; }
  nav a, .button { padding: 6px 12px; border: 1px solid var(--line); border-radius: 6px; color: var(--text);
                   text-decoration: none; background: var(--card); }
  nav a.on { border-color: var(--flow); color: var(--flow); font-weight: 600; }
  .spacer { flex: 1; }
  .status { color: var(--muted); }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 18px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
  .big { font-size: 24px; font-weight: 650; }
  .card .what { color: var(--muted); font-size: 13px; }
  .gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .gauge header { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
  .gauge .name { font-weight: 600; }
  .gauge .meta { color: var(--muted); font-size: 13px; white-space: nowrap; }
  .chart { width: 100%; height: auto; display: block; margin-top: 6px; }
  .chart .flow { fill: none; stroke: var(--flow); stroke-width: 1.8; }
  .chart .alert-dot { fill: var(--alert); }
  .chart .attacked { fill: var(--attack); }
  .chart .learning { fill: var(--learn); }
  .chart .axis { stroke: var(--line); }
  .chart .label { fill: var(--muted); font-size: 13px; }
  .legend { color: var(--muted); font-size: 13px; margin: -8px 0 16px; }
  .swatch { display: inline-block; width: 12px; height: 12px; border-radius: 2px; vertical-align: -1px; margin: 0 4px 0 10px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 18px; }
  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
  .two > * { min-width: 0; }
  .scroll { max-height: 420px; overflow: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; position: sticky; top: 0; background: var(--card); }
  .nowrap { white-space: nowrap; }
  .flagged { color: var(--alert); font-weight: 600; }
  .caught { color: var(--ok); font-weight: 600; }
  .late { color: var(--warn); font-weight: 600; }
  .missed { color: var(--alert); font-weight: 600; }
  .running, .not { color: var(--muted); font-weight: 600; }
  .empty { color: var(--muted); }
  .note { color: var(--muted); font-size: 13px; margin-top: 8px; }
</style>
</head>
<body>
<main>
  <h1>Streamflow Tamper Watch</h1>
  <p class="sub">Daily streamflow from five DWER gauges in the Warren and Donnelly catchments, June to August 2026.
    June is spent learning how the gauges normally behave; checks start in July.</p>

  <nav>
    {% for key, label in scenarios.items() %}
      <a href="?scenario={{ key }}" class="{{ 'on' if key == v.scenario }}">{{ label }}</a>
    {% endfor %}
    <span class="spacer"></span>
    <span class="status">Showing {{ v.shown[0] }} to {{ v.shown[-1] }} (day {{ v.shown|length }} of {{ total }})</span>
    {% if playing %}
      <a class="button" href="?scenario={{ v.scenario }}">Stop</a>
    {% else %}
      <a class="button" href="?scenario={{ v.scenario }}&day=1&play=1">Play from day 1</a>
    {% endif %}
  </nav>

  <section class="cards">
    {% if v.plan %}
      <div class="card"><div class="big">{{ v.score.caught }} of {{ v.score.ran }}</div><div class="what">attacks caught
        {%- if v.score.running %} ({{ v.score.running }} still running){% endif %}</div></div>
      <div class="card"><div class="big">{{ v.score.late }}</div><div class="what">caught late (when it stopped)</div></div>
      <div class="card"><div class="big">{{ v.score.missed }}</div><div class="what">attacks missed</div></div>
    {% endif %}
    <div class="card"><div class="big">{{ v.score.false }}</div><div class="what">false alarms</div></div>
    <div class="card"><div class="big">{{ v.score.alerts }}</div><div class="what">alerts raised</div></div>
    {% if v.plan %}
      <div class="card"><div class="big">{{ v.tampered|length }}</div><div class="what">genuine advisories quoting tampered readings</div></div>
    {% endif %}
  </section>

  <section class="gauges">
    {% for g in v.gauges %}
      <article class="card gauge">
        <header>
          <span class="name">{{ g.name }} <span class="meta">{{ g.id }}</span></span>
          <span class="meta">{% if g.latest is not none %}{{ '%.2f'|format(g.latest) }} ML/day{% endif %}
            {% if g.alerts %} · <span class="flagged">{{ g.alerts }} alert{{ 's' if g.alerts > 1 }}</span>{% endif %}</span>
        </header>
        {{ g.chart }}
      </article>
    {% endfor %}
  </section>
  <p class="legend"><span class="swatch" style="background: var(--learn)"></span>learning (until {{ learn_end }})
    {% if v.plan %}<span class="swatch" style="background: var(--attack)"></span>attacked (ground truth, hidden from the detector){% endif %}
    <span class="swatch" style="background: var(--alert); border-radius: 50%"></span>alert</p>

  <section class="two">
    <div class="card">
      <h2>Alerts</h2>
      <div class="scroll">
      {% if v.alerts %}
        <table><tr><th>Date</th><th>Gauge or advisory</th><th>Rule</th><th>Reason</th></tr>
        {% for a in v.alerts %}
          <tr><td class="nowrap">{{ a.date }}</td><td class="flagged nowrap">{{ a.sensor }}</td><td>{{ a.rule }}</td><td>{{ a.reason }}</td></tr>
        {% endfor %}</table>
      {% else %}<p class="empty">No alerts{% if v.shown[-1] <= learn_end %} yet, the detector is still learning{% endif %}.</p>{% endif %}
      </div>
    </div>
    <div class="card">
      <h2>Advisories</h2>
      <div class="scroll">
      {% if v.advisories %}
        <table><tr><th>ID</th><th>Notice</th><th>Check</th></tr>
        {% for a in v.advisories %}
          <tr><td class="nowrap">{{ a.id }}</td><td>{{ a.text }}</td>
              <td>{% if a.flagged %}<span class="flagged">flagged</span>{% else %}passed{% endif %}</td></tr>
        {% endfor %}</table>
      {% else %}<p class="empty">The first advisory goes out on day 7.</p>{% endif %}
      </div>
    </div>
  </section>

  {% if v.plan %}
  <section class="card" style="margin-bottom: 18px">
    <h2>Attack log (ground truth)</h2>
    <table><tr><th>Attack</th><th>Target</th><th>Result</th></tr>
    {% for a in v.attacks %}
      <tr><td>{{ a.text }}</td><td>{{ a.gauges }}</td><td class="{{ a.status.split()[0] }}">{{ a.status }}</td></tr>
    {% endfor %}</table>
    {% if v.false_alarms %}
      <p class="note">False alarms: {% for day, sensor in v.false_alarms %}{{ sensor }} on {{ day }}{{ ', ' if not loop.last }}{% endfor %}</p>
    {% endif %}
    {% if v.tampered %}
      <h2 style="margin-top: 16px">Genuine advisories that quoted tampered readings</h2>
      <table><tr><th>ID</th><th>Published figures</th><th>Real figures</th></tr>
      {% for a, flow, change in v.tampered %}
        <tr><td>{{ a.id }}</td><td>{{ '%.1f'|format(a.avg_flow_ml) }} ML/day, {{ '%+d'|format(a.change_pct) }}%</td>
            <td>{{ '%.1f'|format(flow) }} ML/day, {{ '%+d'|format((change * 100)|round|int) }}%</td></tr>
      {% endfor %}</table>
      <p class="note">These passed every advisory check, because they match the readings the agency received.
        Only the gauge checks can catch this.</p>
    {% endif %}
  </section>
  {% endif %}

  {% if v.limits %}
  <section class="card">
    <h2>Limits learned in June</h2>
    <table><tr><th>Gauge</th><th>Name</th><th>Jump</th><th>Drift</th></tr>
    {% for l in v.limits %}
      <tr><td>{{ l.id }}</td><td>{{ l.name }}</td><td>x{{ '%.2f'|format(l.jump) }}</td><td>x{{ '%.2f'|format(l.drift) }}</td></tr>
    {% endfor %}</table>
    <p class="note">How many times bigger or smaller a gauge's change can be than the other gauges' before it's flagged.</p>
  </section>
  {% endif %}
</main>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Serve the streamflow dashboard in a web browser.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on (0.0.0.0 inside Docker)")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    args = parser.parse_args()

    print(f"Dashboard running at http://{'localhost' if args.host == '0.0.0.0' else args.host}:{args.port}")
    app.run(host=args.host, port=args.port)


# Runs only when the file is executed directly rather than imported.
if __name__ == "__main__":
    main()
