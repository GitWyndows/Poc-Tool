"""Tests for dashboard.py, using Flask's test client so no server or browser is needed."""
import re

import pytest

pytest.importorskip("flask", reason="the dashboard needs Flask: pip install -r requirements.txt")

import dashboard  # noqa: E402  (imported after the skip, so the rest of the tests still run without Flask)


@pytest.fixture
def client():
    return dashboard.app.test_client()


def page(client, query=""):
    response = client.get(f"/{query}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_clean_page_shows_every_gauge_and_no_alerts(client):
    html = page(client)

    assert "Streamflow Tamper Watch" in html
    assert all(name in html for name in ["Lefroy Brook - Cascades", "Donnelly River - Strickland"])
    assert "No alerts" in html
    assert "Attack log" not in html
    assert html.count('<svg viewBox=') == 5


def test_mixed_page_shows_the_score_attack_log_and_flagged_advisories(client):
    html = page(client, "?scenario=mixed")

    assert '<div class="big">7 of 9</div>' in html
    assert "spike on 608171 of x3.0 on 2026-07-15" in html
    assert "published 14 days after its week ended" in html
    assert html.count('<span class="flagged">flagged</span>') == 3
    assert "Genuine advisories that quoted tampered readings" in html


def test_coordinated_page_lists_the_advisories_that_carried_the_drift(client):
    html = page(client, "?scenario=coordinated")

    assert "coordinated drift on 607022, 607013" in html
    assert '<td class="late">late</td>' in html
    assert "475.4 ML/day, +147%" in html


def test_play_shows_part_of_the_run_and_moves_on_a_day(client):
    html = page(client, "?scenario=mixed&day=45&play=1")

    assert "day 45 of 92" in html
    assert 'content="1; url=?scenario=mixed&day=46&play=1"' in html
    assert ">Stop</a>" in html


def test_play_stops_on_the_last_day(client):
    html = page(client, "?scenario=mixed&day=92&play=1")
    assert 'http-equiv="refresh"' not in html


def test_attack_still_running_is_not_counted_as_missed(client):
    # On 20 July the coordinated drift has only just started, so it can't have been missed yet.
    html = page(client, "?scenario=coordinated&day=50")

    assert "(1 still running)" in html
    assert '<td class="running">running</td>' in html
    assert re.search(r'<div class="big">0</div><div class="what">attacks missed', html)


def test_unknown_scenario_is_refused(client):
    response = client.get("/?scenario=<script>")
    assert response.status_code == 400
    assert "<script>" not in response.get_data(as_text=True)


def test_out_of_range_day_is_clamped(client):
    assert "day 1 of 92" in page(client, "?day=-5")
    assert "day 92 of 92" in page(client, "?day=500")


def test_chart_marks_learning_attacks_and_alerts():
    dates = ["2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"]
    svg = str(dashboard.svg_chart(dates, [10.0, 12.0, 30.0, 11.0], {"2026-07-02"}, {"2026-07-02", "2026-07-03"}))

    assert svg.count('class="learning"') == 1
    assert svg.count('class="attacked"') == 2
    assert svg.count('class="alert-dot"') == 1
    assert "Alert on 2026-07-02: 30.00 ML/day" in svg
