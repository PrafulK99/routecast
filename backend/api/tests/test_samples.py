"""Writes real responses (plan, analyze, heatmap) for the frontend to type-check against and use as mock data.

Scenario 3 (storm on the fastest route). The files are rewritten only when their
content changes; the frozen clock and request id make the output deterministic.
`npm run build` checks them against frontend/src/api/types.ts.
"""

import json
from pathlib import Path

from .helpers import ScenarioWeather, analyze_payload, heatmap_payload, storm_on_route_a, two_routes

FIXTURES = Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "fixtures"
HEATMAP_SAMPLE_POINTS = 8  # enough to show the shape without a 120-point file


def write_sample(name, body):
    text = json.dumps(body, indent=2) + "\n"
    path = FIXTURES / name
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path


def test_write_the_analyze_and_heatmap_samples(client, providers):
    providers(two_routes(), ScenarioWeather(storm_on_route_a))

    analysis = client.post("/api/analyze", analyze_payload(load_weight_lb=20_000), format="json")
    assert analysis.status_code == 200
    body = analysis.json()
    heat = client.post(
        "/api/heatmap",
        heatmap_payload(points=body["corridor_points"][:HEATMAP_SAMPLE_POINTS], load_weight_lb=20_000),
        format="json",
    )
    assert heat.status_code == 200

    plan = client.post("/api/plan", analyze_payload(load_weight_lb=20_000), format="json")
    assert plan.status_code == 200
    plan_path = write_sample("plan.sample.json", plan.json())
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan.json()

    analyze_path = write_sample("analyze.sample.json", body)
    heatmap_path = write_sample("heatmap.sample.json", heat.json())

    assert json.loads(analyze_path.read_text(encoding="utf-8")) == body
    assert json.loads(heatmap_path.read_text(encoding="utf-8")) == heat.json()
    # The sample shows what the frontend must handle: a recommendation that differs
    # from the fastest route, with Severe miles and varied levels on the heatmap.
    assert body["recommendation"]["route_id"] == "route-2"
    assert len({level for point in heat.json()["points"] for level in point["levels"]}) > 1
