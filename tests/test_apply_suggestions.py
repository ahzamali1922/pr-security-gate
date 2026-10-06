import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import report_pr  # noqa: E402
import suggest_fixes  # noqa: E402

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

    def test_rejects_docstring_rules(self):
        f = finding('"""Doc."""', rule="missing-function-docstring")
        self.assertIsNone(report_pr.suggestion_text(f, "    x = 1"))

    def test_rejects_joined_python_statements(self):
        self.assertIsNone(report_pr.suggestion_text(finding('"""Doc."""; x = 1'), "x = 1"))

    def test_allows_semicolon_in_javascript(self):
        f = finding("const a = 1;", rule="no-var", file="a.js")
        self.assertEqual(report_pr.suggestion_text(f, "var a = 1;"), "const a = 1;")

    def test_rejects_fix_that_changes_statement_kind(self):
        f = finding("return sum(prices) + tax", rule="unused-variable")
        self.assertIsNone(report_pr.suggestion_text(f, "    tax = 5"))

    def test_allows_multiline_eval_fix_keeping_the_return(self):
        f = finding("    import ast\n    return ast.literal_eval(text)", rule="eval-used")
        text = report_pr.suggestion_text(f, "    return eval(text)")
        self.assertEqual(text, "    import ast\n    return ast.literal_eval(text)")

    def test_multiline_fix_written_flush_left_is_indented(self):
        f = finding("import ast\nreturn ast.literal_eval(text)", rule="eval-used")
        text = report_pr.suggestion_text(f, "    return eval(text)")
        self.assertEqual(text, "    import ast\n    return ast.literal_eval(text)")

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


class TargetLineTest(unittest.TestCase):
    DIFF = {"a.py": {3: "def calculateds_discount(p):", 26: "    calculate_discount(p)"}}

    def test_fix_goes_on_the_line_the_model_names(self):
        f = finding("def calculate_discount(p):", rule="undefined-variable", line=26)
        f["suggestion"]["line"] = 3
        out = report_pr.build_suggestion_comments(
            [f], self.DIFF, read=lambda path, line: self.DIFF["a.py"][line])
        self.assertEqual(out[0]["line"], 3)
        self.assertIn("flagged at line 26", out[0]["body"])
        self.assertIn("```suggestion\ndef calculate_discount(p):\n```", out[0]["body"])

    def test_pointless_statement_is_deleted(self):
        diff = {"a.py": {1: "dc"}}
        out = report_pr.build_suggestion_comments(
            [finding("", rule="pointless-statement", line=1)], diff, read=lambda *_: "dc")
        self.assertIn("```suggestion\n```", out[0]["body"])

    def test_one_comment_per_target_line(self):
        diff = {"a.py": {1: "dc"}}
        a = finding("", rule="pointless-statement", line=1)
        b = finding("", rule="unused-variable", line=1)
        out = report_pr.build_suggestion_comments([a, b], diff, read=lambda *_: "dc")
        self.assertEqual(len(out), 1)


class TypoHintTest(unittest.TestCase):
    SNIPPET = "1: dc\n3: def calculateds_discount(price, discount):\n26:     calculate_discount(price)"

    def test_hint_points_at_similar_definition(self):
        f = finding("x", rule="undefined-variable", line=26)
        f["message"] = "Undefined variable 'calculate_discount'"
        hint = suggest_fixes.typo_hint(f, self.SNIPPET)
        self.assertIn("calculateds_discount", hint)
        self.assertIn("line 3", hint)
        self.assertIn(hint, suggest_fixes.build_prompt(f, self.SNIPPET, hint))

    def test_no_hint_without_close_match(self):
        f = finding("x", rule="undefined-variable", line=1)
        f["message"] = "Undefined variable 'zzz'"
        self.assertEqual(suggest_fixes.typo_hint(f, self.SNIPPET), "")

    def test_no_hint_for_other_messages(self):
        self.assertEqual(suggest_fixes.typo_hint(finding("x"), self.SNIPPET), "")


class MissingLineTest(unittest.TestCase):
    SNIPPET = "2: def calculateds_discount(price, discount):\n25:     calculate_discount(price, 1)"

    def make(self):
        f = finding("x", rule="undefined-variable", line=25)
        f["message"] = "Undefined variable 'calculate_discount'"
        f.pop("suggestion")
        return f

    def test_definition_fix_without_line_is_moved_to_the_definition(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "app.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\ndef calculateds_discount(price, discount):\n    return price\n\ncalculate_discount(1, 2)\n")
            f = self.make()
            f["file"], f["line"] = path, 5
            reply = '{"fix": "def calculate_discount(price, discount):", "rationale": "typo"}'
            out = suggest_fixes.enrich([f], token="t", llm=lambda *_: reply)
        self.assertEqual(out[0]["suggestion"]["line"], 2)
        self.assertEqual(out[0]["suggestion"]["fix"], "def calculate_discount(price, discount):")

    def test_candidate_found(self):
        candidate = suggest_fixes.typo_candidate(self.make(), self.SNIPPET)
        self.assertEqual(candidate, ("calculate_discount", "calculateds_discount", 2))
        self.assertTrue(suggest_fixes.fix_targets_definition(
            "def calculate_discount(price, discount):", candidate))

    def test_other_fix_is_not_moved(self):
        candidate = ("calculate_discount", "calculateds_discount", 2)
        self.assertFalse(suggest_fixes.fix_targets_definition("calculate_discount(price, 1)", candidate))
        self.assertFalse(suggest_fixes.fix_targets_definition("def other():", candidate))
        self.assertFalse(suggest_fixes.fix_targets_definition("def calculate_discount():", None))


class ReplyLineTest(unittest.TestCase):
    def test_reply_line(self):
        self.assertEqual(suggest_fixes.reply_line('{"line": 3, "fix": "x", "rationale": "y"}'), 3)
        self.assertIsNone(suggest_fixes.reply_line('{"fix": "x", "rationale": "y"}'))
        self.assertIsNone(suggest_fixes.reply_line('{"line": "3", "fix": "x", "rationale": "y"}'))

    def test_enrich_records_other_line_only(self):
        f = finding("x", rule="undefined-variable", line=26)
        f.pop("suggestion")
        other = suggest_fixes.enrich([f], token="t",
                                     llm=lambda *_: '{"line": 3, "fix": "def a():", "rationale": "typo"}')
        same = suggest_fixes.enrich([f], token="t",
                                    llm=lambda *_: '{"line": 26, "fix": "a()", "rationale": "r"}')
        self.assertEqual(other[0]["suggestion"]["line"], 3)
        self.assertNotIn("line", same[0]["suggestion"])


if __name__ == "__main__":
    unittest.main()
