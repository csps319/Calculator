"""
Remediation metrics used in vulnerability management.

* SLA due date   - the date a vulnerability must be fixed by, based on its severity.
* MTTR           - Mean Time to Remediate: average days from discovery to fix.
* SLA compliance - percentage of vulnerabilities fixed on or before their due date.

Counting rules:
* Calendar days, dates only (no times or time zones).
* Due date = discovered date + SLA days for that severity.
* A fix ON the due date counts as within SLA.
* A same-day fix counts as 0 days to remediate.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

SEVERITIES = ("Critical", "High", "Medium", "Low")
DEFAULT_SLA_DAYS = {"Critical": 15, "High": 30, "Medium": 90, "Low": 180}
MAX_SLA_DAYS = 3650
MAX_RECORDS = 1000
EARLIEST_DATE = date(1990, 1, 1)
LATEST_DATE = date(2100, 12, 31)
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class MetricsError(ValueError):
    """Raised for invalid metrics input. The message is safe to show to users."""


@dataclass(frozen=True)
class RemediationRecord:
    severity: str
    discovered: date
    fixed: date

    @property
    def days_to_remediate(self):
        return (self.fixed - self.discovered).days


# ---------- Parsing and validation (untrusted input -> clean Python values) ----------

def parse_date(value, field_name):
    """Parse a 'YYYY-MM-DD' string into a date, or raise MetricsError."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MetricsError(f"{field_name} is required")
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value.strip()):
        raise MetricsError(f"{field_name} must be a date in YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        raise MetricsError(f"{field_name} is not a real calendar date: '{value.strip()}'") from None
    if not EARLIEST_DATE <= parsed <= LATEST_DATE:
        raise MetricsError(f"{field_name} must be between {EARLIEST_DATE} and {LATEST_DATE}")
    return parsed


def parse_severity(value):
    """Accept a severity in any letter case ('high', 'HIGH') and return its canonical form ('High')."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MetricsError("Severity is required")
    if not isinstance(value, str):
        raise MetricsError('Severity must be text, e.g. "High"')
    for severity in SEVERITIES:
        if value.strip().lower() == severity.lower():
            return severity
    raise MetricsError(f"Unknown severity '{value.strip()}'. Use one of: {', '.join(SEVERITIES)}")


def resolve_sla_days(overrides=None):
    """Return the SLA policy: the defaults, with any valid overrides applied on top.

    Overrides can be partial, e.g. {"Critical": 7} changes only Critical.
    """
    sla_days = dict(DEFAULT_SLA_DAYS)  # copy, so we never modify the defaults
    if overrides is None:
        return sla_days
    if not isinstance(overrides, dict):
        raise MetricsError("SLA settings must be an object mapping severity to days")

    for key, days in overrides.items():
        severity = parse_severity(key)
        # bool is a subclass of int in Python, so True would otherwise count as 1.
        if isinstance(days, bool) or not isinstance(days, int):
            raise MetricsError(f"SLA days for {severity} must be a whole number")
        if not 1 <= days <= MAX_SLA_DAYS:
            raise MetricsError(f"SLA days for {severity} must be between 1 and {MAX_SLA_DAYS}")
        sla_days[severity] = days
    return sla_days


def parse_records(raw_records):
    """Validate a list of {"severity", "discovered", "fixed"} objects into RemediationRecords.

    Error messages name the record number so the user knows which row to fix.
    """
    if not isinstance(raw_records, list):
        raise MetricsError("Records must be a list of remediation records")
    if not raw_records:
        raise MetricsError("Add at least one remediation record")
    if len(raw_records) > MAX_RECORDS:
        raise MetricsError(f"Too many records: at most {MAX_RECORDS} are allowed")

    records = []
    for number, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, dict):
            raise MetricsError(f"Record {number} must be an object with severity, discovered and fixed")
        try:
            severity = parse_severity(raw.get("severity"))
            discovered = parse_date(raw.get("discovered"), "Discovered date")
            fixed = parse_date(raw.get("fixed"), "Fixed date")
        except MetricsError as error:
            raise MetricsError(f"Record {number}: {error}") from None

        if fixed < discovered:
            raise MetricsError(
                f"Record {number}: Fixed date ({fixed}) is before discovered date ({discovered})"
            )
        records.append(RemediationRecord(severity, discovered, fixed))
    return records


# ---------- Calculations (inputs are already validated) ----------

def _round_one_decimal(value):
    """Round half up to 1 decimal place (2.25 -> 2.3).

    Python's built-in round() uses banker's rounding (2.25 -> 2.2), which looks
    wrong on a dashboard.
    """
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def sla_due_date(severity, discovered, sla_days):
    """The fix-by date: discovered date plus the SLA days for this severity."""
    return discovered + timedelta(days=sla_days[severity])


def is_within_sla(record, sla_days):
    """True if fixed on or before the due date (the due date itself still counts)."""
    return record.fixed <= sla_due_date(record.severity, record.discovered, sla_days)


def mean_time_to_remediate(records):
    """Average days from discovery to fix, rounded to 1 decimal place."""
    if not records:
        raise MetricsError("At least one record is needed to calculate MTTR")
    total_days = sum(record.days_to_remediate for record in records)
    return _round_one_decimal(Decimal(total_days) / len(records))


def count_within_sla(records, sla_days):
    return sum(1 for record in records if is_within_sla(record, sla_days))


def sla_compliance_percent(records, sla_days):
    """Percentage of records fixed within SLA, rounded to 1 decimal place."""
    if not records:
        raise MetricsError("At least one record is needed to calculate SLA compliance")
    compliant = count_within_sla(records, sla_days)
    return _round_one_decimal(Decimal(compliant * 100) / len(records))