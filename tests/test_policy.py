import unittest
from fractions import Fraction

from exception_desk.policy import compare_policies, compare_policy_set, simulate_policy


def case(case_id, opened, deadline, amount, actionable, duration, failures=0):
    return {
        "case_id": case_id,
        "opened_at": opened,
        "deadline": deadline,
        "amount_atomic": amount,
        "actionable_at": actionable,
        "duration_minutes": duration,
        "control_failures": failures,
    }


class PolicySimulationTests(unittest.TestCase):
    def test_fifo_and_deadline_first_are_deterministic(self):
        cases = [
            case("older", 0, 100, 5, 0, 10),
            case("urgent", 0, 8, 7, 0, 2, 2),
        ]
        comparison = compare_policies(cases)

        self.assertEqual([x["case_id"] for x in comparison["fifo"]["outcomes"]], ["older", "urgent"])
        self.assertEqual(
            [x["case_id"] for x in comparison["deadline_first"]["outcomes"]],
            ["urgent", "older"],
        )
        self.assertEqual(comparison["fifo"]["workload_fingerprint"], comparison["deadline_first"]["workload_fingerprint"])
        self.assertEqual(comparison["deadline_first"]["control_failures"], 2)

    def test_no_future_leakage(self):
        cases = [
            case("available", 0, 100, 1, 0, 10),
            case("future-urgent", 0, 1, 1, 1, 1),
        ]
        result = simulate_policy(cases, "deadline_first")
        self.assertEqual([x["case_id"] for x in result["outcomes"]], ["available", "future-urgent"])
        self.assertEqual(result["outcomes"][0]["started_at"], 0)

    def test_deadline_first_can_reduce_count_while_worsening_value_weighted_delay(self):
        cases = [
            case("large", 0, 5, 1_000, 0, 10),
            case("small-a", 0, 2, 1, 0, 1),
            case("small-b", 0, 3, 1, 0, 1),
        ]
        comparison = compare_policies(cases)
        fifo = comparison["fifo"]
        deadline = comparison["deadline_first"]

        self.assertLess(deadline["overdue_count"], fifo["overdue_count"])
        self.assertGreater(deadline["value_weighted_overdue_minutes"], fifo["value_weighted_overdue_minutes"])

    def test_value_weighted_overdue_is_exactly_rounded_on_every_python(self):
        # plain sum() is compensated on Python 3.12+ but not on 3.11, so it would differ by version.
        cases = [case(f"c{i}", 0, 0, 1_000_003 + i * 7, 0, 0.3) for i in range(40)]
        result = simulate_policy(cases, "fifo", horizon=10_000)
        exact = sum(Fraction(o["amount_atomic"]) * Fraction(o["overdue_minutes"]) for o in result["outcomes"])
        self.assertEqual(result["value_weighted_overdue_minutes"], float(exact))

    def test_horizon_reports_unfinished_count_and_value(self):
        cases = [case("short", 0, 10, 3, 0, 2), case("long", 1, 20, 11, 1, 10, 2)]
        result = simulate_policy(cases, "fifo", horizon=5)
        self.assertEqual(result["touches"], 1)
        self.assertEqual(result["unfinished_count"], 1)
        self.assertEqual(result["unfinished_value_atomic"], 11)
        self.assertEqual(result["unfinished_control_failures"], 2)
        self.assertEqual(result["total_control_failures"], 2)

    def test_operator_takes_a_case_that_fits_before_the_horizon(self):
        cases = [case("long", 0, 100, 50, 0, 50), case("short", 0, 100, 5, 0, 5)]
        result = simulate_policy(cases, "value_first", horizon=10)
        self.assertEqual(["short"], [x["case_id"] for x in result["outcomes"]])
        self.assertEqual(1, result["unfinished_count"])

    def test_naive_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            simulate_policy([case("naive", "2027-01-01T00:00:00", 100, 1, 0, 1)], "fifo")

    def test_service_time_sensitivity(self):
        base = [case("a", 0, 4, 4, 0, 2), case("b", 0, 5, 6, 0, 2)]
        half = [{**item, "duration_minutes": item["duration_minutes"] / 2} for item in base]
        double = [{**item, "duration_minutes": item["duration_minutes"] * 2} for item in base]
        self.assertEqual(simulate_policy(half, "fifo")["overdue_count"], 0)
        self.assertGreater(simulate_policy(double, "fifo")["overdue_count"], 0)

    def test_resolution_metrics_and_order_tie_break_are_stable(self):
        cases = [case("b", 0, 50, 1, 0, 2), case("a", 0, 50, 1, 0, 1)]
        result = simulate_policy(reversed(cases), "fifo")
        self.assertEqual([x["case_id"] for x in result["outcomes"]], ["a", "b"])
        self.assertEqual(result["median_resolution_delay_minutes"], 2)
        self.assertEqual(result["p95_resolution_delay_minutes"], 3)

    def test_rejects_non_identical_workloads(self):
        original = [case("a", 0, 10, 1, 0, 1)]
        changed = [case("a", 0, 10, 1, 0, 2)]
        with self.assertRaisesRegex(ValueError, "identical workloads"):
            compare_policies(original, deadline_cases=changed)

    def test_rejects_bad_inputs(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            simulate_policy([case("a", 0, 1, 1, 0, 1), case("a", 0, 1, 1, 0, 1)], "fifo")
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            simulate_policy([case("a", 0, 1, 1.5, 0, 1)], "fifo")
        with self.assertRaisesRegex(ValueError, "unknown policy"):
            simulate_policy([], "clairvoyant")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            simulate_policy([], "fifo", operator_count=0)

    def test_value_first_prioritises_unresolved_value(self):
        cases = [
            case("old-small", 0, 100, 1, 0, 1),
            case("new-large", 1, 100, 1_000, 0, 1),
        ]
        result = simulate_policy(cases, "value_first", start_at=2)
        self.assertEqual([item["case_id"] for item in result["outcomes"]], ["new-large", "old-small"])

    def test_hybrid_uses_sla_window_then_value_then_age(self):
        cases = [
            case("outside-huge", 0, 100, 10_000, 0, 1),
            case("near-small", 1, 20, 1, 0, 1),
            case("near-large", 2, 20, 10, 0, 1),
        ]
        result = simulate_policy(cases, "hybrid", start_at=2, sla_window_minutes=30)
        self.assertEqual(
            [item["case_id"] for item in result["outcomes"]],
            ["near-large", "near-small", "outside-huge"],
        )

    def test_parallel_operators_preserve_work_and_identity(self):
        cases = [case("a", 0, 10, 1, 0, 5), case("b", 0, 10, 1, 0, 5)]
        one = simulate_policy(cases, "fifo", operator_count=1)
        two = simulate_policy(cases, "fifo", operator_count=2)
        self.assertEqual(one["workload_fingerprint"], two["workload_fingerprint"])
        self.assertEqual(two["touches"], 2)
        self.assertEqual({item["operator_id"] for item in two["outcomes"]}, {0, 1})
        self.assertEqual(max(item["completed_at"] for item in two["outcomes"]), 5)

    def test_four_policy_comparison_uses_identical_workload(self):
        cases = [case("a", 0, 10, 1, 0, 2), case("b", 0, 20, 10, 0, 2)]
        results = compare_policy_set(cases)
        self.assertEqual(set(results), {"fifo", "deadline_first", "value_first", "hybrid"})
        self.assertEqual(len({item["workload_fingerprint"] for item in results.values()}), 1)


if __name__ == "__main__":
    unittest.main()
