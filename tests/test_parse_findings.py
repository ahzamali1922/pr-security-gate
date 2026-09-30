import json
import unittest

from scripts.parse_findings import (
    parse_pylint,
    parse_eslint,
    parse_findings
)


class TestParser(unittest.TestCase):

    def test_parse_pylint(self):
        with open(
            "tests/fixtures/pylint_sample.json",
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        findings = parse_pylint(data)

        self.assertEqual(len(findings), 2)

        self.assertEqual(
            findings[0]["file"],
            "demo-app/python/app.py"
        )

        self.assertEqual(
            findings[0]["line"],
            10
        )

        self.assertEqual(
            findings[0]["rule"],
            "broad-exception-caught"
        )

        self.assertEqual(
            findings[0]["severity"],
            "MEDIUM"
        )

        self.assertEqual(
            findings[0]["message"],
            "Catching too general exception Exception"
        )

    def test_parse_eslint(self):
        with open(
            "tests/fixtures/eslint_sample.json",
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        findings = parse_eslint(data)

        self.assertEqual(len(findings), 2)

        self.assertEqual(
            findings[0]["file"],
            "demo-app/javascript/app.js"
        )

        self.assertEqual(
            findings[0]["line"],
            1
        )

        self.assertEqual(
            findings[0]["rule"],
            "no-unused-vars"
        )

        self.assertEqual(
            findings[0]["severity"],
            "HIGH"
        )

        self.assertEqual(
            findings[0]["message"],
            "'fs' is assigned a value but never used."
        )

    def test_parse_combined_findings(self):
        findings = parse_findings(
            "tests/fixtures/pylint_sample.json",
            "tests/fixtures/eslint_sample.json"
        )

        self.assertEqual(len(findings), 4)

        self.assertEqual(
            findings[0]["file"],
            "demo-app/python/app.py"
        )

        self.assertEqual(
            findings[2]["file"],
            "demo-app/javascript/app.js"
        )


if __name__ == "__main__":
    unittest.main()