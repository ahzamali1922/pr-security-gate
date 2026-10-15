import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import suggest_fixes  # noqa: E402

FINDING = {"file": "a.py", "line": 1, "rule": "bare-except", "severity": "high",
           "message": "m", "tool": "pylint"}
REPLY = '{"fix": "except OSError:", "rationale": "narrower"}'


def completed(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class CopilotCommandTest(unittest.TestCase):
    def run_call(self, model="copilot", result=None):
        result = result or completed(REPLY)
        with mock.patch.object(suggest_fixes.subprocess, "run", return_value=result) as run:
            text = suggest_fixes.call_copilot("the prompt", "secret-token", model, "")
        return text, run

    def test_command_uses_prompt_mode_and_silent_output(self):
        text, run = self.run_call()
        command = run.call_args.args[0]
        self.assertEqual(text, REPLY)
        self.assertEqual(command[1:], ["-p", "the prompt", "-s"])

    def test_default_model_is_not_forced(self):
        _, run = self.run_call()
        self.assertNotIn("--model", run.call_args.args[0])

    def test_custom_model_is_passed(self):
        _, run = self.run_call(model="claude-haiku-4.5")
        self.assertEqual(run.call_args.args[0][-2:], ["--model", "claude-haiku-4.5"])

    def test_token_goes_in_environment_not_in_the_command(self):
        _, run = self.run_call()
        self.assertEqual(run.call_args.kwargs["env"]["COPILOT_GITHUB_TOKEN"], "secret-token")
        self.assertNotIn("secret-token", " ".join(run.call_args.args[0]))

    def test_no_tool_permissions_are_granted(self):
        _, run = self.run_call()
        self.assertFalse(any("allow" in part for part in run.call_args.args[0]))

    def test_nonzero_exit_raises_oserror(self):
        with self.assertRaises(OSError):
            self.run_call(result=completed(stderr="not logged in", code=1))

    def test_timeout_raises_oserror(self):
        with mock.patch.object(suggest_fixes.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("copilot", 1)):
            with self.assertRaises(OSError):
                suggest_fixes.call_copilot("p", "t", "copilot", "")


class CopilotEnrichTest(unittest.TestCase):
    def test_reply_becomes_a_suggestion(self):
        out = suggest_fixes.enrich([FINDING], token="t", model="copilot",
                                   llm=lambda *_: REPLY)
        self.assertEqual(out[0]["suggestion"]["fix"], "except OSError:")
        self.assertEqual(out[0]["suggestion"]["source"], "copilot")

    def test_failure_falls_back_to_rule_based(self):
        def broken(*_):
            raise OSError("copilot CLI exited 1")
        out = suggest_fixes.enrich([FINDING], token="t", model="copilot", llm=broken)
        self.assertEqual(out[0]["suggestion"]["source"], "rule-based")


class ProviderChoiceTest(unittest.TestCase):
    def run_main(self, env, which):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "f.json"), os.path.join(tmp, "o.json")
            with open(src, "w", encoding="utf-8") as handle:
                json.dump([], handle)
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(suggest_fixes.shutil, "which", return_value=which), \
                    mock.patch("builtins.print") as printed:
                suggest_fixes.main(["--input", src, "--output", dst])
        return " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)

    def test_copilot_chosen_when_token_and_cli_present(self):
        out = self.run_main({"COPILOT_GITHUB_TOKEN": "t", "GEMINI_API_KEY": "g"}, "/bin/copilot")
        self.assertIn("AI provider: GitHub Copilot CLI", out)

    def test_other_provider_used_when_cli_missing(self):
        out = self.run_main({"COPILOT_GITHUB_TOKEN": "t", "GEMINI_API_KEY": "g"}, None)
        self.assertIn("not installed", out)
        self.assertIn("AI provider: Gemini", out)

    def test_empty_token_is_ignored(self):
        out = self.run_main({"COPILOT_GITHUB_TOKEN": "", "GEMINI_API_KEY": "g"}, "/bin/copilot")
        self.assertIn("AI provider: Gemini", out)


if __name__ == "__main__":
    unittest.main()
