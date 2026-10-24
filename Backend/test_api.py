"""Endpoint tests using Flask's test client (no running server needed)."""

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


# ---------- /api/calculate ----------

def test_calculate_returns_exact_decimal_result(client):
    response = client.post("/api/calculate", json={"expression": "0.1 + 0.2"})
    assert response.status_code == 200
    assert response.get_json() == {"result": "0.3"}


def test_calculate_divide_by_zero_is_400_with_message(client):
    response = client.post("/api/calculate", json={"expression": "5 / 0"})
    assert response.status_code == 400
    assert "divide by zero" in response.get_json()["error"]


@pytest.mark.parametrize("request_kwargs, message", [
    ({"data": "hello", "content_type": "text/plain"}, "JSON object"),
    ({"data": "{not json", "content_type": "application/json"}, "JSON object"),
    ({"json": ["1 + 1"]}, "JSON object"),
    ({"json": {}}, 'Missing "expression"'),
    ({"json": {"expression": 5}}, "must be text"),
])
def test_calculate_rejects_malformed_requests(client, request_kwargs, message):
    response = client.post("/api/calculate", **request_kwargs)
    assert response.status_code == 400
    assert message in response.get_json()["error"]


# ---------- /api/sla-defaults and /api/sla/due-date ----------

def test_sla_defaults(client):
    response = client.get("/api/sla-defaults")
    assert response.status_code == 200
    assert response.get_json()["sla_days"] == {"Critical": 15, "High": 30, "Medium": 90, "Low": 180}


def test_due_date_default_policy(client):
    response = client.post("/api/sla/due-date", json={"severity": "critical", "discovered": "2026-01-01"})
    assert response.status_code == 200
    assert response.get_json() == {
        "severity": "Critical",
        "discovered": "2026-01-01",
        "sla_days": 15,
        "due_date": "2026-01-16",
    }


def test_due_date_custom_policy(client):
    response = client.post("/api/sla/due-date", json={
        "severity": "Critical", "discovered": "2026-01-01", "sla_days": {"Critical": 7},
    })
    assert response.get_json()["due_date"] == "2026-01-08"


@pytest.mark.parametrize("body, message", [
    ({"severity": "Severe", "discovered": "2026-01-01"}, "Unknown severity"),
    ({"severity": "High"}, "Discovered date is required"),
    ({"severity": "High", "discovered": "01/02/2026"}, "YYYY-MM-DD"),
    ({"severity": "High", "discovered": "2026-01-01", "sla_days": {"High": 0}}, "between 1 and 3650"),
])
def test_due_date_validation(client, body, message):
    response = client.post("/api/sla/due-date", json=body)
    assert response.status_code == 400
    assert message in response.get_json()["error"]


# ---------- /api/sla/remediation-metrics ----------

SAMPLE_RECORDS = [
    {"severity": "Critical", "discovered": "2026-09-01", "fixed": "2026-09-10"},
    {"severity": "High", "discovered": "2026-08-03", "fixed": "2026-09-14"},
    {"severity": "Medium", "discovered": "2026-06-15", "fixed": "2026-08-20"},
]


def test_remediation_metrics(client):
    response = client.post("/api/sla/remediation-metrics", json={"records": SAMPLE_RECORDS})
    data = response.get_json()
    assert response.status_code == 200
    assert data["mttr_days"] == 39.0
    assert data["sla_compliance_percent"] == 66.7
    assert data["within_sla_count"] == 2
    assert data["total_count"] == 3
    assert data["records"][1] == {
        "severity": "High", "days_to_remediate": 42, "due_date": "2026-09-02", "within_sla": False,
    }


def test_remediation_metrics_wrong_date_order(client):
    bad = [{"severity": "High", "discovered": "2026-02-01", "fixed": "2026-01-01"}]
    response = client.post("/api/sla/remediation-metrics", json={"records": bad})
    assert response.status_code == 400
    assert response.get_json()["error"].startswith("Record 1:")


# ---------- General behaviour ----------

def test_unknown_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert "error" in response.get_json()


def test_index_serves_frontend_with_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Remediation Console" in response.data
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"