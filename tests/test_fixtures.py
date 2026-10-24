import json
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = ROOT / "data" / "incidents-v1.jsonl"
ORACLE_PATH = ROOT / "data" / "incidents-v1.oracle.json"

REQUIRED_EVENT_FIELDS = {
    "fixture_id",
    "event_id",
    "aggregate_id",
    "event_type",
    "occurred_at",
    "observed_at",
    "sequence",
    "schema_version",
    "evidence_label",
    "payload",
}
ALLOWED_EVIDENCE_LABELS = {
    "synthetic_business_record",
    "synthetic_protocol_evidence",
    "synthetic_chain_observation",
    "synthetic_system_observation",
    "synthetic_control_observation",
    "synthetic_operator_decision",
}
REQUIRED_EXCEPTION_SCENARIOS = {
    "authorization_reject",
    "preparation_failure",
    "timeout_then_late_success",
    "conclusive_settlement_failure",
    "paid_lost_delivery",
    "repeated_event_across_restart",
    "duplicate_request",
    "second_authorization_for_paid_order",
    "amount_asset_recipient_network_mismatch",
    "payment_evidence_reused_across_orders",
    "prefinality_observation_invalidated",
    "concurrent_refund_approvals_unknown_outcome",
}
ORACLE_ONLY_KEYS = {
    "expected_payment_state",
    "expected_fulfillment_state",
    "expected_exception_type",
    "expected_financials",
    "permissible_actions",
    "forbidden_actions",
    "closure_evidence",
    "actionable",
}


def load_events():
    with EVENTS_PATH.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def load_oracle():
    with ORACLE_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def nested_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from nested_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_keys(child)


class FixtureCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_events()
        cls.oracle = load_oracle()
        cls.cases = cls.oracle["cases"]

    def test_jsonl_and_oracle_are_parseable(self):
        self.assertGreater(len(self.events), 16)
        self.assertEqual(self.oracle["oracle_version"], "1.0.0")
        self.assertIsInstance(self.cases, list)

    def test_every_event_has_stable_required_fields_and_types(self):
        for event in self.events:
            self.assertEqual(set(event), REQUIRED_EVENT_FIELDS, event["event_id"])
            self.assertIsInstance(event["payload"], dict)
            self.assertIsInstance(event["sequence"], int)
            self.assertGreater(event["sequence"], 0)
            self.assertEqual(event["schema_version"], "1.0.0")
            for timestamp in (event["occurred_at"], event["observed_at"]):
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                self.assertIsNotNone(parsed.tzinfo)

    def test_event_ids_are_globally_unique(self):
        event_ids = [event["event_id"] for event in self.events]
        self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_exactly_four_happy_paths_and_twelve_required_exceptions(self):
        happy = [case for case in self.cases if case["category"] == "happy_path"]
        exceptions = [case for case in self.cases if case["category"] == "exception"]
        self.assertEqual(len(self.cases), 16)
        self.assertEqual(len(happy), 4)
        self.assertEqual(len(exceptions), 12)
        self.assertEqual({case["scenario"] for case in exceptions}, REQUIRED_EXCEPTION_SCENARIOS)

    def test_event_and_oracle_case_sets_match(self):
        event_cases = {event["fixture_id"] for event in self.events}
        oracle_cases = {case["fixture_id"] for case in self.cases}
        self.assertEqual(event_cases, oracle_cases)
        self.assertEqual(len(oracle_cases), len(self.cases))

    def test_per_case_ingestion_sequence_and_observation_time_are_monotonic(self):
        grouped = defaultdict(list)
        for event in self.events:
            grouped[event["fixture_id"]].append(event)
        for fixture_id, events in grouped.items():
            sequences = [event["sequence"] for event in events]
            observed = [event["observed_at"] for event in events]
            self.assertEqual(sequences, list(range(1, len(events) + 1)), fixture_id)
            self.assertEqual(observed, sorted(observed), fixture_id)

    def test_all_events_have_declared_synthetic_evidence_labels(self):
        labels = {event["evidence_label"] for event in self.events}
        self.assertTrue(labels)
        self.assertLessEqual(labels, ALLOWED_EVIDENCE_LABELS)
        self.assertNotIn(None, labels)
        self.assertNotIn("real", labels)

    def test_expected_outcomes_are_absent_from_event_input(self):
        input_keys = set(nested_keys(self.events))
        self.assertTrue(ORACLE_ONLY_KEYS.isdisjoint(input_keys))
        oracle_keys = set(nested_keys(self.oracle))
        self.assertTrue(ORACLE_ONLY_KEYS.issubset(oracle_keys))

    def test_oracle_cases_define_operational_and_financial_expectations(self):
        required = {
            "fixture_id",
            "category",
            "scenario",
            "expected_payment_state",
            "expected_fulfillment_state",
            "expected_exception_type",
            "actionable",
            "permissible_actions",
            "forbidden_actions",
            "closure_evidence",
            "expected_financials",
        }
        for case in self.cases:
            self.assertEqual(set(case), required, case["fixture_id"])
            self.assertTrue(case["closure_evidence"], case["fixture_id"])
            financials = case["expected_financials"]
            self.assertEqual(
                set(financials),
                {"captured_atomic", "reserved_refund_atomic", "completed_refund_atomic"},
            )
            self.assertLessEqual(
                financials["reserved_refund_atomic"] + financials["completed_refund_atomic"],
                financials["captured_atomic"],
                case["fixture_id"],
            )


if __name__ == "__main__":
    unittest.main()
