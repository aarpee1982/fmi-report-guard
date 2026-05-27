from fastapi.testclient import TestClient

from fmi_report_guard.api import app


def test_health_reports_openai_config_state(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["openai_configured"] is False


def test_judge_requires_openai_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/judge",
        json={
            "candidate": {
                "title": "Android Smartphone Market",
                "estimated_year": 2026,
                "estimated_value_usd_mn": 900000,
                "forecast_year": 2036,
                "forecast_value_usd_mn": 1690000,
                "cagr_percent": 6.5,
            },
            "matches": [],
        },
    )

    assert response.status_code == 503


def test_judge_returns_without_model_call_when_no_matches(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = TestClient(app)

    response = client.post(
        "/api/judge",
        json={
            "candidate": {
                "title": "Android Smartphone Market",
                "estimated_year": 2026,
                "estimated_value_usd_mn": 900000,
                "forecast_year": 2036,
                "forecast_value_usd_mn": 1690000,
                "cagr_percent": 6.5,
            },
            "matches": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["should_escalate"] is False
