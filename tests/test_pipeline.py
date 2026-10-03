import datetime
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import gate  # noqa: E402
import metrics  # noqa: E402
import report_pr  # noqa: E402
import suggest_fixes  # noqa: E402

HIGH = {"file": "a.py", "line": 1, "rule": "bare-except", "severity": "high",
        "message": "m", "tool": "pylint"}
LOW = {"file": "a.py", "line": 2, "rule": "missing-function-docstring", "severity": "low",
       "message": "m", "tool": "pylint"}


class SuggestTest(unittest.TestCase):
    def test_fallback_without_token(self):
        out = suggest_fixes.enrich([HIGH, LOW])
        self.assertEqual(out[0]["suggestion"]["source"], "rule-based")
        self.assertIn("specific exception", out[0]["suggestion"]["fix"])

    def test_llm_reply_used(self):
        def fake(*_):
            return '```json\n{"fix": "use OSError", "rationale": "narrower"}\n```'
        out = suggest_fixes.enrich([HIGH], token="t", llm=fake)
        self.assertEqual(out[0]["suggestion"]["fix"], "use OSError")

    def test_llm_failure_falls_back(self):
        def broken(*_):
            return "not json"
        out = suggest_fixes.enrich([HIGH], token="t", llm=broken)
        self.assertEqual(out[0]["suggestion"]["source"], "rule-based")


class GateTest(unittest.TestCase):
    def test_blocks_high(self):
        self.assertEqual(len(gate.blocking([HIGH, LOW], "high")), 1)

    def test_passes_low_only(self):
        self.assertEqual(gate.blocking([LOW], "high"), [])


class ReportTest(unittest.TestCase):
    def test_comment_contains_marker_and_findings(self):
        body = report_pr.build_comment(suggest_fixes.enrich([HIGH, LOW]))
        self.assertIn(report_pr.MARKER, body)
        self.assertIn("Gate failed", body)
        self.assertIn("Suggested fix", body)
        self.assertLess(body.index("High"), body.index("Low"))

    def test_clean_comment(self):
        self.assertIn("Gate passed", report_pr.build_comment([]))


class MetricsTest(unittest.TestCase):
    def test_time_to_fix(self):
        t0 = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        fail = metrics.make_record([HIGH], [], 5, "a", "1", now=t0)
        self.assertFalse(fail["gate_passed"])
        self.assertIsNone(fail["time_to_fix_minutes"])
        ok = metrics.make_record([], [fail], 5, "b", "2",
                                 now=t0 + datetime.timedelta(minutes=30))
        self.assertTrue(ok["gate_passed"])
        self.assertEqual(ok["time_to_fix_minutes"], 30.0)

    def test_other_pr_ignored(self):
        t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        fail = metrics.make_record([HIGH], [], 1, "a", "1", now=t0)
        ok = metrics.make_record([], [fail], 2, "b", "2", now=t0)
        self.assertIsNone(ok["time_to_fix_minutes"])


if __name__ == "__main__":
    unittest.main()
