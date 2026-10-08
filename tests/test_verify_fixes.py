import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import metrics  # noqa: E402
import report_pr  # noqa: E402
import verify_fixes  # noqa: E402


def f(rule, message, severity="high", line=2, file="a.py"):
    return {"file": file, "line": line, "rule": rule, "severity": severity,
            "message": message, "tool": "pylint"}


BARE = f("bare-except", "No exception type(s) specified")
CONTENT = "try:\n    run()\nexcept:\n    pass\n"


def fake_lint(after):
    """Linter stub: the original content reports BARE, any changed content reports `after`."""
    def lint(path, content):
        return [BARE] if content == CONTENT else after
    return lint


class ApplyFixTest(unittest.TestCase):
    def test_replace_delete_and_multiline(self):
        self.assertEqual(verify_fixes.apply_fix("a\nb\nc", 2, "X"), "a\nX\nc")
        self.assertEqual(verify_fixes.apply_fix("a\nb\nc", 2, ""), "a\nc")
        self.assertEqual(verify_fixes.apply_fix("a\nb\nc", 2, "X\nY"), "a\nX\nY\nc")

    def test_line_out_of_range(self):
        with self.assertRaises(verify_fixes.LintError):
            verify_fixes.apply_fix("a\nb", 5, "X")


class VerifyTest(unittest.TestCase):
    def run_verify(self, after, fail_on="high"):
        return verify_fixes.verify(BARE, 3, "except OSError:", CONTENT, fake_lint(after), fail_on)

    def test_verified_when_finding_is_gone(self):
        out = self.run_verify([])
        self.assertEqual((out["status"], out["new_findings"]), ("verified", 0))

    def test_failed_when_finding_remains(self):
        self.assertEqual(self.run_verify([BARE])["status"], "failed")

    def test_failed_when_fix_introduces_a_blocking_finding(self):
        out = self.run_verify([f("syntax-error", "Parsing failed")])
        self.assertEqual(out["status"], "failed")
        self.assertIn("syntax-error", out["reason"])

    def test_verified_but_counts_a_new_non_blocking_finding(self):
        out = self.run_verify([f("broad-exception-caught", "too general", severity="medium")])
        self.assertEqual((out["status"], out["new_findings"]), ("verified", 1))

    def test_stricter_gate_blocks_the_same_new_finding(self):
        out = self.run_verify([f("broad-exception-caught", "too general", severity="medium")],
                              fail_on="medium")
        self.assertEqual(out["status"], "failed")

    def test_skipped_when_finding_cannot_be_reproduced(self):
        lint = lambda path, content: []  # noqa: E731
        out = verify_fixes.verify(BARE, 3, "except OSError:", CONTENT, lint)
        self.assertEqual(out["status"], "skipped")

    def test_baseline_is_computed_once_per_file(self):
        calls = []

        def lint(path, content):
            calls.append(content)
            return [BARE] if content == CONTENT else []

        baselines = {}
        verify_fixes.verify(BARE, 3, "except OSError:", CONTENT, lint, baselines=baselines)
        verify_fixes.verify(BARE, 3, "except ValueError:", CONTENT, lint, baselines=baselines)
        self.assertEqual(calls.count(CONTENT), 1)


class SyntaxErrorVerifyTest(unittest.TestCase):
    SYNTAX = f("syntax-error", "Parsing failed: 'invalid syntax (a, line 2)'")
    BROKEN = "x = 1\nreturnn x\n"

    def lint_with(self, after):
        return lambda path, content: [self.SYNTAX] if content == self.BROKEN else after

    def test_verified_when_the_file_parses_again_even_if_hidden_findings_appear(self):
        hidden = [f("undefined-variable", "Undefined variable 'suum'"),
                  f("unused-import", "Unused import os", severity="medium")]
        out = verify_fixes.verify(self.SYNTAX, 2, "return x", self.BROKEN, self.lint_with(hidden))
        self.assertEqual((out["status"], out["new_findings"]), ("verified", 2))

    def test_failed_when_the_file_still_does_not_parse(self):
        still = [f("syntax-error", "Parsing failed: 'invalid syntax (a, line 2)'")]
        out = verify_fixes.verify(self.SYNTAX, 2, "return  x y", self.BROKEN, self.lint_with(still))
        self.assertEqual(out["status"], "failed")

    def test_next_syntax_error_is_progress_not_failure(self):
        next_error = f("syntax-error", "Parsing failed: 'unexpected indent (a, line 3)'", line=3)
        out = verify_fixes.verify(self.SYNTAX, 1, "y = 1", self.BROKEN, self.lint_with([next_error]))
        self.assertEqual((out["status"], out.get("partial")), ("verified", True))

    def test_same_error_with_a_different_module_name_still_counts_as_the_same(self):
        same = f("syntax-error", "Parsing failed: 'invalid syntax (other_module, line 2)'")
        out = verify_fixes.verify(self.SYNTAX, 2, "return  x y", self.BROKEN, self.lint_with([same]))
        self.assertEqual(out["status"], "failed")

    def test_error_signature_ignores_the_module_and_line_suffix(self):
        a = f("syntax-error", "Parsing failed: 'invalid syntax (mod, line 9)'", line=9)
        b = f("syntax-error", "Parsing failed: 'invalid syntax (<stdin>, line 9)'", line=9)
        self.assertEqual(verify_fixes.error_signature(a), verify_fixes.error_signature(b))

    def test_partial_fix_note_in_the_report(self):
        item = f("syntax-error", "m")
        item["suggestion"] = {"fix": "try:", "rationale": "r", "source": "ai",
                              "verification": {"status": "verified", "partial": True, "reason": "x"}}
        self.assertIn("another one", report_pr.verification_note(item["suggestion"]))

    def test_message_text_does_not_have_to_match_exactly(self):
        other_message = dict(self.SYNTAX, message="Parsing failed: 'invalid syntax (<stdin>, line 2)'")
        lint = lambda path, content: [other_message] if content == self.BROKEN else []  # noqa: E731
        out = verify_fixes.verify(self.SYNTAX, 2, "return x", self.BROKEN, lint)
        self.assertEqual(out["status"], "verified")


class VerifyAllTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "a.py")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(CONTENT)
        self.finding = dict(BARE, file=self.path, line=3,
                            suggestion={"fix": "except OSError:", "rationale": "r", "source": "ai"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_marks_the_suggestion_and_counts(self):
        tally = verify_fixes.verify_all([self.finding], lint=fake_lint([]))
        self.assertEqual(self.finding["suggestion"]["verification"]["status"], "verified")
        self.assertEqual(tally, {"checked": 1, "verified": 1, "failed": 0, "skipped": 0})

    def test_linter_error_becomes_skipped_not_a_crash(self):
        def broken(path, content):
            raise verify_fixes.LintError("linter missing")
        tally = verify_fixes.verify_all([self.finding], lint=broken)
        self.assertEqual(tally["skipped"], 1)
        self.assertEqual(self.finding["suggestion"]["verification"]["status"], "skipped")

    def test_non_candidates_are_left_alone(self):
        hint = dict(self.finding, suggestion={"fix": "Review it.", "rationale": "r", "source": "rule-based"})
        tally = verify_fixes.verify_all([hint], lint=fake_lint([]))
        self.assertEqual(tally["checked"], 0)
        self.assertNotIn("verification", hint["suggestion"])

    def test_respects_the_max(self):
        items = [dict(self.finding, suggestion=dict(self.finding["suggestion"])) for _ in range(3)]
        self.assertEqual(verify_fixes.verify_all(items, lint=fake_lint([]), max_checks=2)["checked"], 2)

    def test_main_writes_results_in_place_and_a_summary(self):
        src = os.path.join(self.tmp.name, "enriched.json")
        summary = os.path.join(self.tmp.name, "verification.json")
        with open(src, "w", encoding="utf-8") as handle:
            json.dump([self.finding], handle)
        real = verify_fixes.verify_all
        with mock.patch.object(verify_fixes, "verify_all",
                               lambda items, **kw: real(items, lint=fake_lint([]), **kw)):
            self.assertEqual(verify_fixes.main(["--input", src, "--summary", summary]), 0)
        with open(src, encoding="utf-8") as handle:
            saved = json.load(handle)
        with open(summary, encoding="utf-8") as handle:
            tally = json.load(handle)
        self.assertEqual(saved[0]["suggestion"]["verification"]["status"], "verified")
        self.assertEqual(tally["verified"], 1)


class ReportIntegrationTest(unittest.TestCase):
    DIFF = {"a.py": {3: "except:"}}

    def finding(self, verification):
        item = dict(BARE, line=3, severity="high",
                    suggestion={"fix": "except OSError:", "rationale": "r", "source": "ai"})
        if verification:
            item["suggestion"]["verification"] = verification
        return item

    def build(self, verification):
        return report_pr.build_suggestion_comments(
            [self.finding(verification)], self.DIFF, read=lambda *_: "except:")

    def test_failed_fix_gets_no_button(self):
        self.assertEqual(self.build({"status": "failed", "reason": "still reported"}), [])

    def test_verified_fix_gets_a_button_and_a_badge(self):
        out = self.build({"status": "verified", "reason": "ok"})
        self.assertEqual(len(out), 1)
        self.assertIn("Lint-verified", out[0]["body"])
        self.assertIn("```suggestion", out[0]["body"])

    def test_skipped_or_missing_verification_behaves_as_before(self):
        for check in (None, {"status": "skipped", "reason": "no linter"}):
            out = self.build(check)
            self.assertEqual(len(out), 1)
            self.assertNotIn("Lint-verified", out[0]["body"])

    def test_marker_stays_on_the_first_line(self):
        out = self.build({"status": "verified", "reason": "ok"})
        self.assertTrue(out[0]["body"].splitlines()[0].startswith("<!-- pr-security-gate:"))

    def test_summary_comment_shows_the_note(self):
        verified = report_pr.build_comment([self.finding({"status": "verified", "reason": "ok"})])
        failed = report_pr.build_comment([self.finding({"status": "failed", "reason": "still reported"})])
        plain = report_pr.build_comment([self.finding(None)])
        self.assertIn("Lint-verified", verified)
        self.assertIn("Not verified: still reported", failed)
        self.assertNotIn("verified", plain.lower().replace("lint-verified", ""))


class MetricsTest(unittest.TestCase):
    def test_record_carries_verification(self):
        tally = {"checked": 3, "verified": 2, "failed": 1, "skipped": 0}
        record = metrics.make_record([], [], 1, "a", "1", verification=tally)
        self.assertEqual(record["verification"], tally)
        self.assertIsNone(metrics.make_record([], [], 1, "a", "1")["verification"])


if __name__ == "__main__":
    unittest.main()
