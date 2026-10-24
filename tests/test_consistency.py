import csv
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from exception_desk.consistency import ConsistencyError, assert_artifacts_consistent, audit_artifacts

BOUNDARY = "Chain evidence does not prove delivery."


class ConsistencyTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> None:
        data = root / "data"
        output = root / "artifacts" / "generated"
        data.mkdir(parents=True)
        output.mkdir(parents=True)
        fixture = '{"fixture_id":"case-1","event_id":"event-1"}\n'
        oracle = {"cases": [{"fixture_id": "case-1"}]}
        (data / "incidents-v1.jsonl").write_text(fixture, encoding="utf-8")
        oracle_text = json.dumps(oracle)
        (data / "incidents-v1.oracle.json").write_text(oracle_text, encoding="utf-8")
        meta = {
            "run_id": "run-1",
            "fixture_sha256": sha256(fixture.encode()).hexdigest(),
            "oracle_sha256": sha256(oracle_text.encode()).hexdigest(),
            "policy_workload_hash": "work-1",
            "data_classification": "synthetic",
            "claim_boundary": BOUNDARY,
        }
        summary = {
            **meta, "fixture_count": 1, "event_count": 1, "oracle_cases_passed": 1,
            "inputs": {"fixtures": "data/incidents-v1.jsonl", "oracle": "data/incidents-v1.oracle.json"},
        }
        (output / "build-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (output / "projections.json").write_text(json.dumps({"_meta": meta, "cases": {"case-1": {}}}), encoding="utf-8")
        (output / "oracle-conformance.json").write_text(json.dumps({"_meta": meta, "results": [{"status": "PASS"}]}), encoding="utf-8")
        metrics = {"policy": "fifo", "overdue_count": 0, "median_resolution_delay_minutes": 1,
                   "p95_resolution_delay_minutes": 1, "value_weighted_overdue_minutes": 0,
                   "unfinished_count": 0, "unfinished_value_atomic": 0, "touches": 1,
                   "control_failures": 0, "workload_fingerprint": "work-1"}
        (output / "policy-results.json").write_text(json.dumps({"_meta": meta, "policies": {"fifo": metrics}}), encoding="utf-8")
        (output / "scenario-sweep-summary.json").write_text(
            json.dumps({"_meta": meta, "scenario_count": 12, "summary": {}}), encoding="utf-8"
        )
        summary["scenario_count"] = 12
        (output / "build-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        common = ["run_id", "fixture_sha256", "oracle_sha256", "policy_workload_hash", "data_classification", "claim_boundary"]
        with (output / "reconciliation.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["fixture_id", *common])
            writer.writeheader()
            writer.writerow({"fixture_id": "case-1", **meta})
        with (output / "policy-results.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[*metrics, *common])
            writer.writeheader()
            writer.writerow({**metrics, **meta})
        attrs = " ".join(f'data-{key.replace("_", "-")}="{meta[key]}"' for key in ("run_id", "fixture_sha256", "oracle_sha256", "policy_workload_hash"))
        (output / "operator-report.html").write_text(f'<html {attrs}><body>SIMULATED DATA. {BOUNDARY}</body></html>', encoding="utf-8")

    def test_complete_consistent_bundle_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            report = assert_artifacts_consistent(root)
            self.assertEqual("PASS", report["status"])
            self.assertTrue(all(item["status"] == "PASS" for item in report["checks"]))

    def test_detects_intentional_policy_csv_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            path = root / "artifacts" / "generated" / "policy-results.csv"
            path.write_text(path.read_text(encoding="utf-8").replace("fifo,0,1", "fifo,2,1"), encoding="utf-8")
            report = audit_artifacts(root)
            self.assertEqual("FAIL", report["status"])
            self.assertIn("policy_csv_json_agreement", {item["name"] for item in report["checks"] if item["status"] == "FAIL"})
            with self.assertRaises(ConsistencyError):
                assert_artifacts_consistent(root)

    def test_detects_fixture_drift_and_missing_claim_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            with (root / "data" / "incidents-v1.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"fixture_id":"case-2","event_id":"event-2"}\n')
            html = root / "artifacts" / "generated" / "operator-report.html"
            html.write_text(html.read_text(encoding="utf-8").replace(BOUNDARY, ""), encoding="utf-8")
            failed = {item["name"] for item in audit_artifacts(root)["checks"] if item["status"] == "FAIL"}
            self.assertIn("fixture_manifest_hash", failed)
            self.assertIn("event_count", failed)
            self.assertIn("operator_report:labels", failed)

    def test_detects_scenario_count_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            path = root / "artifacts" / "generated" / "scenario-sweep-summary.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["scenario_count"] = 11
            path.write_text(json.dumps(value), encoding="utf-8")
            failed = {item["name"] for item in audit_artifacts(root)["checks"] if item["status"] == "FAIL"}
            self.assertIn("scenario_count", failed)

    def test_malformed_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            (root / "artifacts" / "generated" / "policy-results.json").write_text("{", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                assert_artifacts_consistent(root)


if __name__ == "__main__":
    unittest.main()
