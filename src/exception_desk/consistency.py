"""Cross-artifact integrity checks for generated exception-desk evidence.

The checker is deliberately independent of the build command.  A build can call
``assert_artifacts_consistent`` after writing its outputs; reviewers can call the
same function against an unpacked package.  It validates identity and counts,
not merely the presence of files.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SYNTHETIC_LABEL = "synthetic"
CLAIM_BOUNDARY = "chain evidence does not prove delivery"
JSON_FILES = (
    "projections.json",
    "oracle-conformance.json",
    "policy-results.json",
    "scenario-sweep-summary.json",
)
CSV_FILES = ("reconciliation.csv", "policy-results.csv")


class ConsistencyError(RuntimeError):
    """Raised when one or more generated artifacts disagree."""

    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        super().__init__("artifact consistency failed: " + "; ".join(report.get("errors", [])))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    nested = value.get("_meta", value.get("metadata"))
    return nested if isinstance(nested, Mapping) else value


def _payload(value: Any, *keys: str) -> Any:
    if not isinstance(value, Mapping):
        return value
    for key in keys:
        if key in value:
            return value[key]
    return value


def _same_number(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return left == right


def audit_artifacts(root: Path) -> dict[str, Any]:
    """Return a machine-readable PASS/FAIL report for one generated build."""
    root = Path(root)
    output = root / "artifacts" / "generated"
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if condition else "FAIL", "detail": detail})
        if not condition:
            errors.append(f"{name}: {detail}")

    required = [output / "build-summary.json", output / "operator-report.html"]
    required += [output / name for name in JSON_FILES + CSV_FILES]
    required += [root / "data" / "incidents-v1.jsonl", root / "data" / "incidents-v1.oracle.json"]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    check("required_files", not missing, "missing: " + ", ".join(missing) if missing else "all inputs and outputs present")
    if missing:
        return {"status": "FAIL", "checks": checks, "errors": errors, "metadata": {}}

    summary = json.loads((output / "build-summary.json").read_text(encoding="utf-8"))
    expected = {
        "run_id": summary.get("run_id"),
        "fixture_sha256": summary.get("fixture_sha256"),
        "oracle_sha256": summary.get("oracle_sha256"),
        "policy_workload_hash": summary.get("policy_workload_hash"),
    }
    check("identity_fields", all(expected.values()), "summary contains run, fixture, oracle, and policy workload identities")

    actual_fixture_hash = sha256_file(root / "data" / "incidents-v1.jsonl")
    actual_oracle_hash = sha256_file(root / "data" / "incidents-v1.oracle.json")
    check("fixture_manifest_hash", expected["fixture_sha256"] == actual_fixture_hash, "fixture input matches manifest hash")
    check("oracle_manifest_hash", expected["oracle_sha256"] == actual_oracle_hash, "oracle input matches manifest hash")
    inputs = summary.get("inputs", {})
    check(
        "manifest_inputs",
        isinstance(inputs, Mapping)
        and inputs.get("fixtures") == "data/incidents-v1.jsonl"
        and inputs.get("oracle") == "data/incidents-v1.oracle.json",
        "summary names the two authoritative input paths",
    )

    json_values: dict[str, Any] = {}
    for name in JSON_FILES:
        value = json.loads((output / name).read_text(encoding="utf-8"))
        json_values[name] = value
        meta = _metadata(value)
        identity_ok = all(wanted and meta.get(key) == wanted for key, wanted in expected.items())
        labels_ok = (
            str(meta.get("data_classification", "")).lower() == SYNTHETIC_LABEL
            and CLAIM_BOUNDARY in str(meta.get("claim_boundary", "")).lower()
        )
        check(f"{name}:identity", identity_ok, "shared run and input identities match summary")
        check(f"{name}:labels", labels_ok, "synthetic and delivery claim-boundary labels are present")

    projections = _payload(json_values["projections.json"], "cases", "projections")
    conformance = _payload(json_values["oracle-conformance.json"], "results", "cases")
    fixture_count = len(projections) if isinstance(projections, Mapping) else -1
    pass_count = (
        sum(row.get("status") == "PASS" for row in conformance if isinstance(row, Mapping))
        if isinstance(conformance, list) else -1
    )
    event_count = sum(1 for line in (root / "data" / "incidents-v1.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    oracle = json.loads((root / "data" / "incidents-v1.oracle.json").read_text(encoding="utf-8"))
    oracle_count = len(oracle.get("cases", [])) if isinstance(oracle, Mapping) else -1
    check("case_count", fixture_count == oracle_count == summary.get("fixture_count"), "projection, oracle, and summary case counts agree")
    check("event_count", event_count == summary.get("event_count"), "source event count agrees with summary")
    check("oracle_pass_count", pass_count == oracle_count == summary.get("oracle_cases_passed"), "every oracle case passes and agrees with summary")
    scenario_count = json_values["scenario-sweep-summary.json"].get("scenario_count")
    check("scenario_count", scenario_count == summary.get("scenario_count"), "scenario sweep and summary counts agree")

    csv_rows: dict[str, list[dict[str, str]]] = {}
    for name in CSV_FILES:
        with (output / name).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        csv_rows[name] = rows
        identity_ok = bool(rows) and all(expected.values()) and all(
            all(row.get(key) == wanted for key, wanted in expected.items()) for row in rows
        )
        labels_ok = bool(rows) and all(
            row.get("data_classification", "").lower() == SYNTHETIC_LABEL
            and CLAIM_BOUNDARY in row.get("claim_boundary", "").lower()
            for row in rows
        )
        check(f"{name}:identity", identity_ok, "every row carries shared run and input identities")
        check(f"{name}:labels", labels_ok, "every row carries synthetic and claim-boundary labels")
    check("reconciliation_case_count", len(csv_rows["reconciliation.csv"]) == fixture_count, "one reconciliation row exists per case")

    policy_json = _payload(json_values["policy-results.json"], "policies", "results")
    policy_rows = {row.get("policy"): row for row in csv_rows["policy-results.csv"]}
    metric_fields = (
        "overdue_count", "median_resolution_delay_minutes", "p95_resolution_delay_minutes",
        "value_weighted_overdue_minutes", "unfinished_count", "unfinished_value_atomic",
        "touches", "control_failures", "workload_fingerprint",
    )
    agreement = isinstance(policy_json, Mapping) and set(policy_json) == set(policy_rows)
    if agreement:
        agreement = all(
            _same_number(metrics.get(field), policy_rows[name].get(field))
            for name, metrics in policy_json.items() for field in metric_fields
        )
    check("policy_csv_json_agreement", agreement, "policy names and all exported metrics agree")
    workload_ok = isinstance(policy_json, Mapping) and bool(policy_json) and all(
        metrics.get("workload_fingerprint") == expected["policy_workload_hash"]
        for metrics in policy_json.values()
    )
    check("policy_workload_identity", workload_ok, "all policies use the declared identical workload")

    html = (output / "operator-report.html").read_text(encoding="utf-8").lower()
    html_identity = all(expected.values()) and all(
        f'data-{key.replace("_", "-")}="{value}"'.lower() in html
        for key, value in expected.items()
    )
    html_labels = "simulated data" in html and CLAIM_BOUNDARY in html
    check("operator_report:identity", html_identity, "HTML embeds shared run and input identities")
    check("operator_report:labels", html_labels, "HTML visibly labels synthetic data and the delivery claim boundary")

    return {
        "status": "PASS" if not errors else "FAIL",
        "checks": checks,
        "errors": errors,
        "metadata": expected,
    }


def assert_artifacts_consistent(root: Path) -> dict[str, Any]:
    """Return the report or raise ``ConsistencyError`` on any drift."""
    report = audit_artifacts(root)
    if report["status"] != "PASS":
        raise ConsistencyError(report)
    return report
