from rest_framework.test import APIClient


def test_health_returns_ok():
    response = APIClient().get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_json_for_browser_accept_header():
    response = APIClient().get(
        "/api/health", HTTP_ACCEPT="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"status": "ok"}
