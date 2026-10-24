"""
Flask API and static file server for the calculator.

Routes:
    GET  /                              -> the frontend (index.html)
    GET  /api/sla-defaults              -> {"sla_days": {...}}
    POST /api/calculate                 -> {"expression": "1 + 2"} -> {"result": "3"}
    POST /api/sla/due-date              -> {"severity", "discovered", "sla_days"?}
    POST /api/sla/remediation-metrics   -> {"records": [...], "sla_days"?}

Every error response has the same shape: {"error": "human-readable message"}.
"""

from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from calculator import CalculationError, calculate
from security_metrics import (
    DEFAULT_SLA_DAYS,
    MetricsError,
    count_within_sla,
    is_within_sla,
    mean_time_to_remediate,
    parse_date,
    parse_records,
    parse_severity,
    resolve_sla_days,
    sla_compliance_percent,
    sla_due_date,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# static_url_path="" serves frontend files from the site root (/styles.css, /app.js).
app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024  # reject request bodies over 100 KB


class InvalidRequest(ValueError):
    """Raised when the request itself is malformed, e.g. the body isn't a JSON object."""


def read_json_body():
    # silent=True returns None (instead of raising) for a missing, wrong-type or broken JSON body.
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidRequest("Request body must be a JSON object")
    return body


# ---------- Routes ----------

@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/sla-defaults")
def sla_defaults():
    return jsonify({"sla_days": DEFAULT_SLA_DAYS})


@app.post("/api/calculate")
def calculate_endpoint():
    body = read_json_body()
    if "expression" not in body:
        raise InvalidRequest('Missing "expression" field')
    return jsonify({"result": calculate(body["expression"])})


@app.post("/api/sla/due-date")
def due_date_endpoint():
    body = read_json_body()
    severity = parse_severity(body.get("severity"))
    discovered = parse_date(body.get("discovered"), "Discovered date")
    sla_days = resolve_sla_days(body.get("sla_days"))

    due_date = sla_due_date(severity, discovered, sla_days)
    return jsonify({
        "severity": severity,
        "discovered": discovered.isoformat(),
        "sla_days": sla_days[severity],
        "due_date": due_date.isoformat(),
    })


@app.post("/api/sla/remediation-metrics")
def remediation_metrics_endpoint():
    body = read_json_body()
    records = parse_records(body.get("records"))
    sla_days = resolve_sla_days(body.get("sla_days"))

    return jsonify({
        "mttr_days": mean_time_to_remediate(records),
        "sla_compliance_percent": sla_compliance_percent(records, sla_days),
        "within_sla_count": count_within_sla(records, sla_days),
        "total_count": len(records),
        "records": [
            {
                "severity": record.severity,
                "days_to_remediate": record.days_to_remediate,
                "due_date": sla_due_date(record.severity, record.discovered, sla_days).isoformat(),
                "within_sla": is_within_sla(record, sla_days),
            }
            for record in records
        ],
    })


# ---------- Error handling: always answer with {"error": "..."} ----------

@app.errorhandler(CalculationError)
@app.errorhandler(MetricsError)
@app.errorhandler(InvalidRequest)
def handle_bad_input(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(HTTPException)
def handle_http_error(error):
    # 404 Not Found, 405 Method Not Allowed, 413 Payload Too Large, ...
    return jsonify({"error": error.description}), error.code


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    # Log the details for us; show the user a generic message (never a stack trace).
    app.logger.exception("Unexpected error")
    return jsonify({"error": "Something went wrong on the server. Please try again."}), 500


# ---------- Security headers on every response ----------

@app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


if __name__ == "__main__":
    # debug=False on purpose: Flask's interactive debugger lets anyone who can
    # reach it run code on this machine. Bind to localhost only.
    app.run(host="127.0.0.1", port=5000, debug=False)