import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import parse_findings  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


class ParseFindingsTest(unittest.TestCase):
    def setUp(self):
        self.findings = parse_findings.normalize(
            load("pylint-report.json"), load("eslint-report.json")
        )

    def test_schema(self):
        for finding in self.findings:
            self.assertEqual(
                set(finding),
                {"file", "line", "rule", "severity", "message", "tool"},
            )

    def test_total_count(self):
        self.assertEqual(len(self.findings), 8)

    def test_sorted_most_severe_first(self):
        order = [parse_findings.SEVERITY_ORDER.index(f["severity"]) for f in self.findings]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.findings[0]["severity"], "critical")

    def test_pylint_severity_mapping(self):
        by_rule = {f["rule"]: f for f in self.findings}
        self.assertEqual(by_rule["import-error"]["severity"], "high")
        self.assertEqual(by_rule["unused-import"]["severity"], "medium")
        self.assertEqual(by_rule["missing-function-docstring"]["severity"], "low")

    def test_security_rule_is_bumped(self):
        by_rule = {f["rule"]: f for f in self.findings}
        # bare-except is a pylint warning (medium) -> bumped to high
        self.assertEqual(by_rule["bare-except"]["severity"], "high")
        # no-eval is an eslint warn (medium) -> bumped to high
        self.assertEqual(by_rule["no-eval"]["severity"], "high")

    def test_eslint_mapping(self):
        by_rule = {f["rule"]: f for f in self.findings}
        self.assertEqual(by_rule["no-unused-vars"]["severity"], "high")
        self.assertEqual(by_rule["no-console"]["severity"], "medium")
        self.assertEqual(by_rule["parse-error"]["severity"], "critical")

    def test_eslint_path_is_normalized(self):
        eslint = [f for f in self.findings if f["tool"] == "eslint"]
        for finding in eslint:
            self.assertNotIn("\\", finding["file"])

    def test_empty_reports(self):
        self.assertEqual(parse_findings.normalize([], []), [])
        self.assertEqual(parse_findings.normalize(), [])


if __name__ == "__main__":
    unittest.main()
