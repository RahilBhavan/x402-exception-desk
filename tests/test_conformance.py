import unittest
from pathlib import Path

from exception_desk.case_projection import oracle_conformance
from exception_desk.case_projection import project_case as compatibility_project_case
from exception_desk.fixtures import group_by_fixture, load_jsonl, load_oracle
from exception_desk.reducer import project_case

ROOT = Path(__file__).resolve().parents[1]


class OracleConformanceTests(unittest.TestCase):
    def test_all_sixteen_cases_match_pre_authored_oracle(self):
        groups = group_by_fixture(load_jsonl(ROOT / "data" / "incidents-v1.jsonl"))
        oracle = load_oracle(ROOT / "data" / "incidents-v1.oracle.json")
        results = oracle_conformance(groups, oracle)
        self.assertEqual(16, len(results))
        self.assertEqual([], [row for row in results if row["status"] != "PASS"])

    def test_compatibility_api_is_the_canonical_reducer_function(self):
        self.assertIs(project_case, compatibility_project_case)

    def test_fixture_envelope_projects_directly_without_a_second_adapter(self):
        groups = group_by_fixture(load_jsonl(ROOT / "data" / "incidents-v1.jsonl"))
        projection = project_case(groups["ex-03-timeout-late-success"])
        self.assertEqual("observed", projection["expected_payment_state"])
        self.assertEqual("delivery_pending_after_late_settlement",
                         projection["expected_exception_type"])


if __name__ == "__main__":
    unittest.main()
