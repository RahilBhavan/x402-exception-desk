import re
import tempfile
import unittest
from pathlib import Path

from exception_desk.export import render_operator_report, write_operator_report


class OperatorReportTests(unittest.TestCase):
    def setUp(self):
        self.projection = {
            "case_id": "CASE-007",
            "payment_state": "observed",
            "delivery_state": "delivery_pending",
            "payment_evidence": {"transaction_ref": "0xabc"},
            "delivery_evidence": [],
            "refund_reservation": {
                "state": "approved_reserved",
                "reserved_amount_atomic": 1250,
            },
            "fixture_hash": "sha256:fixture",
            "run_id": "run-007",
            "applied_event_ids": ["evt-1", "evt-2"],
        }
        self.exception = {
            "type": "settled_not_delivered",
            "owner": "operations",
            "evidence_gaps": ["delivery acknowledgment"],
            "allowed_actions": ["retry delivery using original entitlement"],
            "forbidden_actions": ["request another payment"],
        }
        self.policies = {
            "fifo": {"overdue_count": 7, "unfinished_value_atomic": 9000},
            "deadline_first": {"overdue_count": 3, "unfinished_value_atomic": 4000},
        }

    def test_contains_critical_operator_sections_and_separate_states(self):
        report = render_operator_report(self.projection, self.exception, self.policies)

        for label in (
            "SIMULATED DATA · NOT LIVE · NO ACTIONS EXECUTED",
            "Payment state",
            "observed",
            "Delivery state",
            "delivery_pending",
            "Evidence gaps",
            "Allowed next actions",
            "Forbidden actions",
            "Refund reservation state",
            "approved_reserved",
            "Queue-policy comparison: absolute metrics",
            "overdue_count",
            '<th scope="col">FIFO</th>',
            '<th scope="col">Deadline First</th>',
        ):
            self.assertIn(label, report)
        self.assertIn('<script src="operator-report.js" defer></script>', report)
        self.assertNotIn("<script>", report.lower())
        self.assertIn("fixture_hash", report)
        self.assertIn("evt-1", report)

    def test_escapes_all_caller_controlled_content(self):
        payload = '<script>alert("owned")</script>'
        projection = {
            "payment_state": payload,
            "delivery_state": "pending & waiting",
            "payment_evidence": {payload: "<img src=x onerror=boom>"},
            "refund_reservation": payload,
        }
        exception = {
            "evidence_gaps": [payload],
            "allowed_actions": [payload],
            "forbidden_actions": [payload],
            "note": payload,
        }
        policies = {"fifo": {payload: payload}, "deadline_first": {payload: payload}}

        report = render_operator_report(
            projection,
            exception,
            policies,
            title=payload,
            stylesheet_href='bad.css" onload="alert(1)',
        )

        self.assertNotIn(payload, report)
        self.assertNotIn("<img src=x", report)
        self.assertNotIn('href="bad.css" onload=', report)
        self.assertIn("&lt;script&gt;alert(&quot;owned&quot;)&lt;/script&gt;", report)
        self.assertIn("pending &amp; waiting", report)
        self.assertIn("bad.css&quot; onload=&quot;alert(1)", report)

    def test_interactive_controls_are_accessible_and_external_only(self):
        report = render_operator_report(self.projection, self.exception, self.policies)

        for fragment in (
            'aria-label="Case navigation"',
            '<label for="case-picker">Case</label>',
            'id="filter-actionable"',
            'id="filter-blocked"',
            'aria-live="polite"',
            'aria-describedby="unsafe-help-0"',
            'href="#case-workspace"',
            'href="operations-memo.pdf"',
            '<caption>Queue policy outcomes</caption>',
            'scope="col"',
        ):
            self.assertIn(fragment, report)
        self.assertNotIn("onclick=", report.lower())
        self.assertNotIn("javascript:", report.lower())
        self.assertFalse(re.search(r'tabindex="[1-9]', report))

    def test_optional_cases_are_rendered_and_escaped(self):
        report = render_operator_report(
            self.projection,
            self.exception,
            self.policies,
            cases=[{
                "projection": {"case_id": "CASE-008<script>", "payment_state": "failed"},
                "exception": {"allowed_actions": [], "evidence_gaps": ["receipt"]},
                "traceability": {"run_id": "run-008"},
            }],
        )
        self.assertIn("CASE-008&lt;script&gt;", report)
        self.assertNotIn("CASE-008<script>", report)
        self.assertIn('id="case-panel-1"', report)
        self.assertIn('data-actionable="false"', report)
        self.assertIn("run-008", report)

    def test_static_primary_case_remains_readable_without_javascript(self):
        report = render_operator_report(self.projection, self.exception, self.policies)
        primary_start = report.index('id="case-panel-0"')
        primary_tag_end = report.index(">", primary_start)
        self.assertNotIn(" hidden", report[primary_start:primary_tag_end])
        self.assertIn("Payment, delivery, and refund states", report)
        self.assertIn("Operator action boundaries", report)

    def test_accepts_row_shaped_policy_results(self):
        policies = [
            {"policy": "fifo", "metrics": {"overdue_count": 8}},
            {"policy": "deadline-first", "metrics": {"overdue_count": 2}},
        ]

        report = render_operator_report(self.projection, self.exception, policies)

        self.assertIn("<td>8</td><td>2</td>", report)

    def test_formats_policy_floats_and_value_weighted_unit(self):
        policies = {"fifo": {"value_weighted_overdue_minutes": 4428900000.11772,
                             "p95_resolution_delay_minutes": 107.05000000074506}}

        report = render_operator_report(self.projection, self.exception, policies)

        self.assertIn("value_weighted_overdue (USDC-minutes)", report)
        self.assertIn("<td>4,428.9</td>", report)
        self.assertIn("<td>107.1</td>", report)
        self.assertNotIn("4428900000", report)
        self.assertIn("NOT AFFILIATED WITH OR ENDORSED BY COINBASE", report)

    def test_renders_every_policy_in_the_comparison(self):
        policies = {
            **self.policies,
            "value_first": {"overdue_count": 4},
            "hybrid": {"overdue_count": 2},
        }

        report = render_operator_report(self.projection, self.exception, policies)

        for heading in ("FIFO", "Deadline First", "Value First", "Hybrid"):
            self.assertIn('<th scope="col">{}</th>'.format(heading), report)

    def test_summary_block_leads_with_the_result(self):
        policies = {
            "fifo": {"overdue_count": 6, "total_control_failures": 0,
                     "value_weighted_overdue_minutes": 4428900000.0},
            "deadline_first": {"overdue_count": 6, "total_control_failures": 0,
                               "value_weighted_overdue_minutes": 1582200000.0},
            "hybrid": {"overdue_count": 4, "total_control_failures": 0,
                       "value_weighted_overdue_minutes": 982100000.0},
        }
        def metric(vwo, p95):
            return {"value_weighted_overdue_minutes": {"win_rate": vwo},
                    "p95_resolution_delay_minutes": {"win_rate": p95}}

        sweep = {"scenario_count": 3600, "summary": {
            "fifo": metric(0.074, 0.5), "deadline_first": metric(0.22, 0.111), "hybrid": metric(0.405, 0.213)}}

        report = render_operator_report(self.projection, self.exception, policies, sweep=sweep)

        self.assertIn("<h1>x402 payment exception desk</h1>", report)
        summary = report.index('id="summary"')
        self.assertLess(report.index("SIMULATED DATA"), summary)
        self.assertLess(summary, report.index('id="case-panel-0"'))
        for fragment in (
            "FIFO stays because the predeclared replacement gate did not pass.",
            "Across 3,600 simulated scenarios, no queue policy wins on every objective.",
            "FIFO 4,428.9 vs Hybrid 982.1 USDC-minutes",
            "64% value-weighted overdue cut, but overdue cases 6 vs 6: not passed",
            "FIFO 7.4% vs Hybrid 40.5%",
            "FIFO 50.0%, the best of any policy on this metric",
            "How to read this page",
            'href="#policy-comparison"', 'href="#case-workspace"', 'href="operations-memo.pdf"',
        ):
            self.assertIn(fragment, report)
        self.assertNotIn('id="summary"', render_operator_report(self.projection, self.exception, policies))

    def test_missing_fields_are_visible_and_report_can_be_written(self):
        report = render_operator_report({}, {}, {})
        self.assertIn("Not provided", report)
        self.assertIn("No policy metrics provided.", report)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.html"
            returned = write_operator_report(destination, {}, {}, {})
            self.assertEqual(destination, returned)
            self.assertEqual(report, destination.read_text(encoding="utf-8"))
            script = Path(directory) / "operator-report.js"
            self.assertTrue(script.exists())
            self.assertIn("REFUSED", script.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
