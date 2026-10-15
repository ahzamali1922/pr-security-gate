import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import feedback  # noqa: E402
import metrics  # noqa: E402
import report_pr  # noqa: E402


def finding(rule="unused-import", message="Unused import os", file="a.py", line=1):
    return {"file": file, "line": line, "rule": rule, "severity": "medium",
            "message": message, "tool": "pylint",
            "suggestion": {"fix": "", "rationale": "r", "source": "gpt"}}


def comment(f, text, cid=1, **extra):
    body = report_pr.suggestion_body(f, text)
    return {"id": cid, "body": body, **extra}


class MetaTest(unittest.TestCase):
    def test_round_trip(self):
        f = finding(message='Undefined variable "x" -->')
        body = report_pr.suggestion_body(f, "x = 1  # -->")
        meta = feedback.parse_meta(body)
        self.assertEqual(meta["message"], 'Undefined variable "x" -->')
        self.assertEqual(meta["text"], "x = 1  # -->")
        self.assertEqual(meta["rule"], "unused-import")

    def test_marker_stays_on_first_line_for_dedupe(self):
        body = report_pr.suggestion_body(finding(), "")
        self.assertTrue(body.splitlines()[0].startswith("<!-- pr-security-gate:"))

    def test_not_our_comment(self):
        self.assertIsNone(feedback.parse_meta("just a human comment"))
        self.assertIsNone(feedback.parse_meta("<!-- pr-gate-meta: !!!notbase64 -->"))
        self.assertIsNone(feedback.parse_meta(None))


class AcceptedTest(unittest.TestCase):
    def test_delete_suggestion_accepted_when_finding_gone(self):
        c = comment(finding(), "")
        out = feedback.compute([c], [])
        self.assertEqual((out["posted"], out["accepted"]), (1, 1))
        self.assertEqual(out["acceptance_rate"], 1.0)

    def test_not_accepted_while_finding_remains(self):
        f = finding()
        out = feedback.compute([comment(f, "")], [f])
        self.assertEqual((out["posted"], out["accepted"]), (1, 0))

    def test_code_suggestion_needs_the_text_in_the_file(self):
        f = finding(rule="bare-except", message="No exception type(s) specified")
        c = comment(f, "    except OSError:")
        present = feedback.compute([c], [], read=lambda path: {"except OSError:"})
        manual = feedback.compute([c], [], read=lambda path: {"except ValueError:"})
        self.assertEqual(present["accepted"], 1)
        self.assertEqual(manual["accepted"], 0)  # fixed by hand some other way

    def test_unreadable_file_is_not_accepted(self):
        f = finding(rule="bare-except")
        out = feedback.compute([comment(f, "except OSError:")], [], read=lambda path: None)
        self.assertEqual(out["accepted"], 0)


class FalsePositiveTest(unittest.TestCase):
    def test_thumbs_down_reaction(self):
        c = comment(finding(), "", reactions={"-1": 1})
        out = feedback.compute([c], [])
        self.assertEqual((out["false_positive"], out["accepted"]), (1, 0))
        self.assertEqual(out["false_positive_rate"], 1.0)

    def test_reply_command(self):
        c = comment(finding(), "", cid=7)
        reply = {"id": 8, "in_reply_to_id": 7, "body": "This is a /false-positive, os is used"}
        self.assertEqual(feedback.compute([c, reply], [finding()])["false_positive"], 1)

    def test_short_command_and_unrelated_reply(self):
        c = comment(finding(), "", cid=7)
        fp = {"id": 8, "in_reply_to_id": 7, "body": "/FP"}
        other = {"id": 9, "in_reply_to_id": 99, "body": "/false-positive"}
        self.assertEqual(feedback.compute([c, fp], [finding()])["false_positive"], 1)
        self.assertEqual(feedback.compute([c, other], [finding()])["false_positive"], 0)

    def test_thumbs_up_is_not_false_positive(self):
        c = comment(finding(), "", reactions={"+1": 3, "-1": 0})
        self.assertEqual(feedback.compute([c], [finding()])["false_positive"], 0)


class RatesTest(unittest.TestCase):
    def test_no_suggestions_gives_none(self):
        out = feedback.compute([], [])
        self.assertEqual((out["posted"], out["acceptance_rate"], out["false_positive_rate"]),
                         (0, None, None))

    def test_mixed(self):
        a, b, c = finding(message="m1"), finding(message="m2"), finding(message="m3")
        comments = [comment(a, "", cid=1), comment(b, "", cid=2, reactions={"-1": 1}),
                    comment(c, "", cid=3)]
        out = feedback.compute(comments, [c])  # a fixed, b marked wrong, c still open
        self.assertEqual((out["posted"], out["accepted"], out["false_positive"]), (3, 1, 1))
        self.assertEqual(out["acceptance_rate"], 0.333)


class MetricsIntegrationTest(unittest.TestCase):
    def test_record_carries_feedback(self):
        t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        fb = {"posted": 2, "accepted": 1, "false_positive": 0}
        self.assertEqual(metrics.make_record([], [], 1, "a", "1", now=t0, feedback=fb)["feedback"], fb)

    def test_record_without_feedback_is_unchanged(self):
        t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        self.assertIsNone(metrics.make_record([], [], 1, "a", "1", now=t0)["feedback"])


if __name__ == "__main__":
    unittest.main()
