"""Build reproducible local artifacts for the simulated exception desk."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .case_projection import oracle_conformance
from .consistency import assert_artifacts_consistent, sha256_file
from .experiments import run_scenario_sweep
from .export import write_operator_report
from .fixtures import group_by_fixture, load_jsonl, load_oracle, reducer_events
from .policy import compare_policy_set, workload_fingerprint
from .reducer import project_case, reduce_events
from .store import EventStore

CLAIM_BOUNDARY = "Chain evidence does not prove delivery."

def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def _policy_cases(groups: dict[str, list[dict[str, Any]]], oracle: dict[str, Any]) -> list[dict[str, Any]]:
    expected = {case["fixture_id"]: case for case in oracle["cases"]}
    cases = []
    for fixture_id, events in groups.items():
        if not expected[fixture_id]["actionable"]:
            continue
        order = next(event for event in events if event["event_type"] == "order_opened")
        cases.append({"case_id": fixture_id, "opened_at": events[0]["observed_at"],
            "deadline": order["payload"]["deadline"],
            "amount_atomic": int(order["payload"]["expected_amount_atomic"]),
            "actionable_at": events[-1]["observed_at"], "duration_minutes": 10 + len(events) * 2,
            "control_failures": 0})
    return cases

def _ui_case(fid: str, events: list[dict[str, Any]], state: dict[str, Any],
             expected: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    order_id = events[0]["aggregate_id"]
    projected = project_case(events)
    return {"projection": {"case_id": fid, "order_id": order_id,
        "payment_state": projected["expected_payment_state"],
        "delivery_state": projected["expected_fulfillment_state"],
        "payment_evidence": list(state["chain_observations"].values()),
        "delivery_evidence": state["fulfillments"].get(order_id, {}),
        "refund_reservation": projected["expected_financials"],
        "evidence_timeline": [{"event_id": e["event_id"], "event_type": e["event_type"],
            "occurred_at": e["occurred_at"]} for e in events],
        "applied_event_ids": state["applied_event_ids"]},
        "exception": {"type": expected["expected_exception_type"],
            "evidence_gaps": expected["closure_evidence"] if expected["actionable"] else [],
            "allowed_actions": expected["permissible_actions"],
            "forbidden_actions": expected["forbidden_actions"]},
        "traceability": {**meta, "fixture_id": fid, "event_count": len(events)}}

def build(root: Path) -> dict[str, Any]:
    data_dir, output = root / "data", root / "artifacts" / "generated"
    output.mkdir(parents=True, exist_ok=True)
    fixture_path, oracle_path = data_dir / "incidents-v1.jsonl", data_dir / "incidents-v1.oracle.json"
    events, oracle = load_jsonl(fixture_path), load_oracle(oracle_path)
    groups = group_by_fixture(events)
    states: dict[str, Any] = {}
    database = output / "exception-desk.sqlite"
    if database.exists():
        database.unlink()
    with EventStore(database) as store:
        for fid, fixture_events in groups.items():
            store.append_many(reducer_events(fixture_events))
            states[fid] = reduce_events(fixture_events)

    policy_cases = _policy_cases(groups, oracle)
    latest_deadline = max(_parse_time(case["deadline"]) for case in policy_cases)
    workload_hash = workload_fingerprint(policy_cases)
    results = compare_policy_set(policy_cases, horizon=(latest_deadline + timedelta(hours=4)).isoformat())
    conformance = oracle_conformance(groups, oracle)
    fixture_hash, oracle_hash = sha256_file(fixture_path), sha256_file(oracle_path)
    run_id = "run-" + hashlib.sha256(f"exception-desk-v2:{fixture_hash}:{oracle_hash}:{workload_hash}".encode()).hexdigest()[:16]
    meta = {"run_id": run_id, "fixture_sha256": fixture_hash, "oracle_sha256": oracle_hash,
        "policy_workload_hash": workload_hash, "data_classification": "synthetic",
        "claim_boundary": CLAIM_BOUNDARY}
    outputs = {"projections.json": {"_meta": meta, "cases": states},
        "policy-results.json": {"_meta": meta, "policies": results},
        "oracle-conformance.json": {"_meta": meta, "results": conformance}}
    for name, payload in outputs.items():
        (output / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scenario = run_scenario_sweep()
    scenario.pop("scenarios")
    (output / "scenario-sweep-summary.json").write_text(json.dumps({"_meta": meta, **scenario}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    common = ["run_id", "fixture_sha256", "oracle_sha256", "policy_workload_hash", "data_classification", "claim_boundary"]
    metrics = ["policy", "overdue_count", "median_resolution_delay_minutes", "p95_resolution_delay_minutes",
        "value_weighted_overdue_minutes", "unfinished_count", "unfinished_value_atomic", "touches",
        "control_failures", "workload_fingerprint"]
    with (output / "policy-results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=metrics + common, lineterminator="\n")
        writer.writeheader()
        for result in results.values():
            writer.writerow({**{f: result[f] for f in metrics}, **meta})
    with (output / "reconciliation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["fixture_id", "captured_atomic", "reserved_refund_atomic", "completed_refund_atomic", *common], lineterminator="\n")
        writer.writeheader()
        for case in oracle["cases"]:
            writer.writerow({"fixture_id": case["fixture_id"], **case["expected_financials"], **meta})

    expected = {case["fixture_id"]: case for case in oracle["cases"]}
    cases = [_ui_case(fid, es, states[fid], expected[fid], meta) for fid, es in groups.items()]
    first = cases[0]
    report = output / "operator-report.html"
    write_operator_report(report, first["projection"], first["exception"], results,
        stylesheet_href="operator-report.css", cases=cases[1:], traceability=first["traceability"], sweep=scenario)
    html = report.read_text(encoding="utf-8")
    attrs = " ".join(f'data-{k.replace("_", "-")}="{meta[k]}"' for k in ("run_id", "fixture_sha256", "oracle_sha256", "policy_workload_hash"))
    html = html.replace('<html lang="en" class="no-js">', f'<html lang="en" class="no-js" {attrs}>').replace(
        "Operator decision support. Verify evidence and authorization before acting.", f"Operator decision support. {CLAIM_BOUNDARY} Verify evidence and authorization before acting.")
    report.write_text(html, encoding="utf-8")
    shutil.copyfile(root / "web" / "operator-report.css", output / "operator-report.css")

    summary = {**meta, "status": "simulated_build_complete",
        "latest_observed_at": max(event["observed_at"] for event in events),
        "fixture_count": len(groups), "event_count": len(events), "policy_workload_count": len(policy_cases),
        "oracle_cases_passed": sum(row["status"] == "PASS" for row in conformance),
        "scenario_count": scenario["scenario_count"],
        "inputs": {"fixtures": "data/incidents-v1.jsonl", "oracle": "data/incidents-v1.oracle.json"},
        "output_directory": "artifacts/generated"}
    (output / "build-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    audit = assert_artifacts_consistent(root)
    (output / "consistency-audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return summary

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    print(json.dumps(build(parser.parse_args().root.resolve()), indent=2))

if __name__ == "__main__":
    main()
