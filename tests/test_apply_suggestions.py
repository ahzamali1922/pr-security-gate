import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import report_pr  # noqa: E402

PATCH = "@@ -1,3 +1,4 @@\n import os\n+try:\n+    run()\n+except:\n     pass\n-old\n"


def finding(fix, rule="bare-except", line=4, source="gpt", file="a.py"):
    return {"file": file, "line": line, "rule": rule, "severity": "high", "message": "m",
            "tool": "pylint",
            "suggestion": {"fix": fix, "rationale": "because", "source": source}}


class PatchTest(unittest.TestCase):
    def test_parse_patch_lines(self):
        lines = report_pr.parse_patch_lines(PATCH)
        self.assertEqual(lines[1], "import os")
        self.assertEqual(lines[4], "except:")
        self.assertNotIn("old", lines.values())

    def test_empty_patch(self):
        self.assertEqual(report_pr.parse_patch_lines(None), {})


class SuggestionTextTest(unittest.TestCase):
    def test_code_fix_keeps_indentation(self):
        text = report_pr.suggestion_text(finding("except OSError:"), "    except:")
        self.assertEqual(text, "    except OSError:")

    def test_rejects_comment_only_fix(self):
        self.assertIsNone(report_pr.suggestion_text(finding("# removed variable"), "x = 1"))
        self.assertIsNone(report_pr.suggestion_text(finding("// console removed"), "console.log(1)"))

    def test_rejects_instruction_sentence(self):
        self.assertIsNone(report_pr.suggestion_text(finding("Catch a specific exception."), "except:"))

    def test_rejects_rule_based_hint(self):
        self.assertIsNone(report_pr.suggestion_text(finding("except OSError:", source="rule-based"), "except:"))

    def test_rejects_unchanged_line(self):
        self.assertIsNone(report_pr.suggestion_text(finding("except:"), "except:"))

    def test_empty_fix_only_for_unused_rules(self):
        self.assertEqual(report_pr.suggestion_text(finding("", rule="unused-import"), "import os"), "")
        self.assertIsNone(report_pr.suggestion_text(finding("", rule="bare-except"), "except:"))


class BuildCommentsTest(unittest.TestCase):
    DIFF = {"a.py": {4: "except:"}}

    def read(self, path, line):
        return "except:"

    def test_builds_suggestion_block(self):
        out = report_pr.build_suggestion_comments(
            [finding("except OSError:")], self.DIFF, read=self.read)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["path"], out[0]["line"], out[0]["side"]), ("a.py", 4, "RIGHT"))
        self.assertIn("```suggestion\nexcept OSError:\n```", out[0]["body"])

    def test_skips_line_outside_diff(self):
        out = report_pr.build_suggestion_comments(
            [finding("except OSError:", line=9)], self.DIFF, read=self.read)
        self.assertEqual(out, [])

    def test_skips_when_file_differs_from_diff(self):
        out = report_pr.build_suggestion_comments(
            [finding("except OSError:")], self.DIFF, read=lambda *_: "something else")
        self.assertEqual(out, [])

    def test_no_duplicate_on_rescan(self):
        first = report_pr.build_suggestion_comments(
            [finding("except OSError:")], self.DIFF, read=self.read)
        again = report_pr.build_suggestion_comments(
            [finding("except OSError:")], self.DIFF, existing_text=first[0]["body"], read=self.read)
        self.assertEqual(again, [])

    def test_delete_suggestion_block_is_empty(self):
        diff = {"a.py": {1: "import os"}}
        out = report_pr.build_suggestion_comments(
            [finding("", rule="unused-import", line=1)], diff, read=lambda *_: "import os")
        self.assertIn("```suggestion\n```", out[0]["body"])


if __name__ == "__main__":
    unittest.main()
