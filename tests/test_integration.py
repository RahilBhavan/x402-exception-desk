import json
import tempfile
import unittest
from pathlib import Path

from exception_desk.cli import build
from exception_desk.fixtures import group_by_fixture, load_jsonl, reducer_events
from exception_desk.reducer import reduce_events

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def test_timeout_late_success_recovers_original_attempt_without_second_charge(self):
        groups = group_by_fixture(load_jsonl(ROOT / "data" / "incidents-v1.jsonl"))
        events = reducer_events(groups["ex-03-timeout-late-success"])
        state = reduce_events(events)
        self.assertEqual(1, len(state["payment_attempts"]))
        attempt = next(iter(state["payment_attempts"].values()))
        self.assertTrue(attempt["timed_out"])
        self.assertEqual("observed", attempt["outcome"])
        order = state["orders"]["order-ex-03"]
        self.assertEqual("observed", order["payment_state"])
        self.assertEqual("prepared", order["delivery_state"])

    def test_build_generates_reproducible_local_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("data", "web"):
                (root / name).mkdir()
            for source in ("incidents-v1.jsonl", "incidents-v1.oracle.json"):
                (root / "data" / source).write_bytes((ROOT / "data" / source).read_bytes())
            (root / "web" / "operator-report.css").write_bytes(
                (ROOT / "web" / "operator-report.css").read_bytes()
            )
            summary = build(root)
            output = root / "artifacts" / "generated"
            self.assertEqual(16, summary["fixture_count"])
            self.assertEqual(65, summary["event_count"])
            self.assertEqual("artifacts/generated", summary["output_directory"])
            self.assertIn("SIMULATED DATA", (output / "operator-report.html").read_text())
            results = json.loads((output / "policy-results.json").read_text())
            policies = results["policies"]
            self.assertEqual({"fifo", "deadline_first", "value_first", "hybrid"}, set(policies))
            self.assertEqual(1, len({row["workload_fingerprint"] for row in policies.values()}))
            self.assertEqual("PASS", json.loads((output / "consistency-audit.json").read_text())["status"])
            self.assertTrue((output / "scenario-sweep-summary.json").exists())
            self.assertTrue((output / "exception-desk.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
