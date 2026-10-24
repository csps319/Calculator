"""Unit tests for SLA due dates, MTTR and SLA compliance."""

from datetime import date

import pytest

from security_metrics import (
    DEFAULT_SLA_DAYS,
    MetricsError,
    RemediationRecord,
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


def record(severity, discovered, fixed):
    return RemediationRecord(severity, date.fromisoformat(discovered), date.fromisoformat(fixed))


# Sample data: 9 days (Critical, within 15), 42 days (High, breaches 30), 66 days (Medium, within 90)
SAMPLE = [
    record("Critical", "2026-09-01", "2026-09-10"),
    record("High", "2026-08-03", "2026-09-14"),
    record("Medium", "2026-06-15", "2026-08-20"),
]


# ---------- SLA due date ----------

@pytest.mark.parametrize("severity, discovered, expected", [
    ("Critical", "2026-01-01", "2026-01-16"),
    ("High", "2026-01-01", "2026-01-31"),
    ("Medium", "2026-01-01", "2026-04-01"),
    ("Low", "2026-01-01", "2026-06-30"),
    ("Critical", "2028-02-20", "2028-03-06"),   # leap year (29 Feb exists)
    ("Critical", "2026-02-20", "2026-03-07"),   # non-leap year
    ("High", "2026-12-15", "2027-01-14"),       # crosses a year boundary
])
def test_due_date_with_default_policy(severity, discovered, expected):
    due = sla_due_date(severity, date.fromisoformat(discovered), DEFAULT_SLA_DAYS)
    assert due == date.fromisoformat(expected)


def test_due_date_with_custom_policy():
    sla_days = resolve_sla_days({"Critical": 7})
    assert sla_due_date("Critical", date(2026, 1, 1), sla_days) == date(2026, 1, 8)


# ---------- SLA policy validation ----------

def test_resolve_sla_days_defaults_and_copy():
    sla_days = resolve_sla_days(None)
    assert sla_days == DEFAULT_SLA_DAYS
    sla_days["Critical"] = 1
    assert DEFAULT_SLA_DAYS["Critical"] == 15   # defaults were not modified


def test_resolve_sla_days_partial_and_case_insensitive_override():
    assert resolve_sla_days({"high": 45}) == {"Critical": 15, "High": 45, "Medium": 90, "Low": 180}


@pytest.mark.parametrize("overrides, message", [
    ({"Severe": 10}, "Unknown severity"),
    ({"High": 0}, "between 1 and 3650"),
    ({"High": -5}, "between 1 and 3650"),
    ({"High": 3651}, "between 1 and 3650"),
    ({"High": 1.5}, "whole number"),
    ({"High": "30"}, "whole number"),
    ({"High": True}, "whole number"),
    ({"High": None}, "whole number"),
    ([15, 30], "must be an object"),
])
def test_resolve_sla_days_rejects_bad_policy(overrides, message):
    with pytest.raises(MetricsError, match=message):
        resolve_sla_days(overrides)


# ---------- Severity and date parsing ----------

@pytest.mark.parametrize("raw, expected", [("critical", "Critical"), ("  HIGH ", "High"), ("Low", "Low")])
def test_parse_severity_normalises_case(raw, expected):
    assert parse_severity(raw) == expected


@pytest.mark.parametrize("raw, message", [
    ("Severe", "Unknown severity"),
    ("", "required"),
    (None, "required"),
    (5, "must be text"),
])
def test_parse_severity_rejects_bad_values(raw, message):
    with pytest.raises(MetricsError, match=message):
        parse_severity(raw)


def test_parse_date_accepts_iso_date():
    assert parse_date("2026-03-01", "Fixed date") == date(2026, 3, 1)


@pytest.mark.parametrize("raw, message", [
    ("", "required"),
    (None, "required"),
    ("2026-02-30", "not a real calendar date"),
    ("2026-13-01", "not a real calendar date"),
    ("03/01/2026", "YYYY-MM-DD"),
    ("20260301", "YYYY-MM-DD"),
    ("2026-3-1", "YYYY-MM-DD"),
    (20260301, "YYYY-MM-DD"),
    ("1989-12-31", "between"),
    ("2101-01-01", "between"),
])
def test_parse_date_rejects_bad_values(raw, message):
    with pytest.raises(MetricsError, match=message):
        parse_date(raw, "Fixed date")


# ---------- Record list validation ----------

def test_parse_records_valid():
    records = parse_records([{"severity": "high", "discovered": "2026-01-01", "fixed": "2026-01-05"}])
    assert records == [record("High", "2026-01-01", "2026-01-05")]


def test_same_day_fix_is_zero_days():
    records = parse_records([{"severity": "Low", "discovered": "2026-01-01", "fixed": "2026-01-01"}])
    assert records[0].days_to_remediate == 0


@pytest.mark.parametrize("raw_records, message", [
    ([{"severity": "High", "discovered": "2026-01-05", "fixed": "2026-01-01"}], r"Record 1: Fixed date .* before"),
    ([{"severity": "High", "discovered": "2026-01-01", "fixed": "2026-01-02"},
      {"severity": "High", "discovered": "2026-01-01"}], "Record 2: Fixed date is required"),
    ([{"severity": "Urgent", "discovered": "2026-01-01", "fixed": "2026-01-02"}], "Record 1: Unknown severity"),
    ([{"discovered": "2026-01-01", "fixed": "2026-01-02"}], "Record 1: Severity is required"),
    (["not an object"], "Record 1 must be an object"),
    ([], "at least one"),
    (None, "must be a list"),
    ("2026-01-01", "must be a list"),
    ([{"severity": "High", "discovered": "2026-01-01", "fixed": "2026-01-02"}] * 1001, "at most 1000"),
])
def test_parse_records_rejects_bad_input(raw_records, message):
    with pytest.raises(MetricsError, match=message):
        parse_records(raw_records)


# ---------- MTTR ----------

def test_mttr_sample():
    assert mean_time_to_remediate(SAMPLE) == 39.0   # (9 + 42 + 66) / 3


def test_mttr_same_day_fix():
    assert mean_time_to_remediate([record("Low", "2026-01-01", "2026-01-01")]) == 0.0


def test_mttr_rounds_half_up():
    # 1 + 2 + 3 + 3 = 9 days over 4 records = 2.25 -> 2.3 (round() would give 2.2)
    records = [
        record("Low", "2026-01-01", "2026-01-02"),
        record("Low", "2026-01-01", "2026-01-03"),
        record("Low", "2026-01-01", "2026-01-04"),
        record("Low", "2026-01-01", "2026-01-04"),
    ]
    assert mean_time_to_remediate(records) == 2.3


def test_mttr_repeating_decimal():
    records = [
        record("Low", "2026-01-01", "2026-01-02"),
        record("Low", "2026-01-01", "2026-01-02"),
        record("Low", "2026-01-01", "2026-01-03"),
    ]
    assert mean_time_to_remediate(records) == 1.3   # 4 / 3


def test_mttr_requires_records():
    with pytest.raises(MetricsError):
        mean_time_to_remediate([])


# ---------- SLA compliance ----------

def test_fix_on_due_date_is_within_sla():
    assert is_within_sla(record("Critical", "2026-01-01", "2026-01-16"), DEFAULT_SLA_DAYS)


def test_fix_one_day_late_breaches_sla():
    assert not is_within_sla(record("Critical", "2026-01-01", "2026-01-17"), DEFAULT_SLA_DAYS)


def test_compliance_sample():
    assert count_within_sla(SAMPLE, DEFAULT_SLA_DAYS) == 2
    assert sla_compliance_percent(SAMPLE, DEFAULT_SLA_DAYS) == 66.7


def test_compliance_all_and_none():
    on_time = [record("High", "2026-01-01", "2026-01-10")]
    late = [record("High", "2026-01-01", "2026-03-01")]
    assert sla_compliance_percent(on_time, DEFAULT_SLA_DAYS) == 100.0
    assert sla_compliance_percent(late, DEFAULT_SLA_DAYS) == 0.0


def test_custom_policy_changes_compliance():
    forty_days = [record("High", "2026-01-01", "2026-02-10")]
    assert sla_compliance_percent(forty_days, DEFAULT_SLA_DAYS) == 0.0
    assert sla_compliance_percent(forty_days, resolve_sla_days({"High": 45})) == 100.0


def test_compliance_requires_records():
    with pytest.raises(MetricsError):
        sla_compliance_percent([], DEFAULT_SLA_DAYS)