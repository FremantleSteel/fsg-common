"""`scripts/check_pr_body.py`: the attribution rule, its edges, and the
absent inputs.

David's rule, all five FSG repos, 16 Sep 2026: no commit carries a
Co-Authored-By trailer and no pull request or document carries a
Generated-with-Claude-Code line. Each case is shown failing, not only
passing: a check only ever observed green is not evidence.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_pr_body as cpb  # noqa: E402

SHORT = "Closes #1\n\nOne sentence of what changed.\n\nTests: 7 before, 9 after."


class TheAttributionRule(unittest.TestCase):
    """David's rule, all five repos, 16 Sep 2026: no commit carries a
    Co-Authored-By trailer and no pull request or document carries a
    Generated-with-Claude-Code line."""

    def test_a_co_authored_by_trailer_in_the_body_is_refused(self):
        body = SHORT + "\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
        problems = cpb.check(body, None, "dkagi")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Co-Authored-By", problems[0])

    def test_a_generated_with_line_in_the_body_is_refused(self):
        body = SHORT + "\n\n\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)"
        problems = cpb.check(body, None, "dkagi")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Generated with", problems[0])

    def test_a_generated_with_line_in_the_first_comment_is_refused(self):
        problems = cpb.check(SHORT, "Generated with Claude Code.", "dkagi")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("the first comment", problems[0])

    def test_the_match_is_not_case_sensitive(self):
        problems = cpb.check(SHORT + "\n\nco-authored-by: someone", None, "dkagi")
        self.assertEqual(len(problems), 1, problems)

    def test_both_phrases_present_gives_two_problems(self):
        body = SHORT + "\n\nCo-Authored-By: x\nGenerated with Claude Code."
        problems = cpb.check(body, None, "dkagi")
        self.assertEqual(len(problems), 2, problems)

    def test_a_clean_body_with_neither_phrase_still_passes(self):
        """The control: this check must not also refuse everything."""
        self.assertEqual(cpb.check(SHORT, None, "dkagi"), [])
        self.assertEqual(cpb.check(SHORT, "Looks fine, thanks.", "dkagi"), [])


class Exemptions(unittest.TestCase):
    def test_a_bot_author_is_exempt_whatever_the_body(self):
        tainted = SHORT + "\n\nCo-Authored-By: x"
        self.assertEqual(cpb.check(tainted, None, "dependabot[bot]"), [])

    def test_a_person_is_not(self):
        self.assertTrue(cpb.check(SHORT + "\n\nGenerated with Claude Code.", None, "dkagi"))


class TheFirstComment(unittest.TestCase):
    def test_the_earliest_comment_is_taken(self):
        listing = json.dumps([{"body": "first"}, {"body": "second"}])
        self.assertEqual(cpb.first_comment_body(listing), "first")

    def test_no_comments_yet_is_none_not_empty_string(self):
        self.assertIsNone(cpb.first_comment_body("[]"))

    def test_a_non_list_is_refused(self):
        with self.assertRaises(ValueError):
            cpb.first_comment_body(json.dumps({"message": "Not Found"}))


class TheCommandLine(unittest.TestCase):
    def _tmp(self, name: str, text: str) -> str:
        path = Path(self.dir.name) / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_an_event_with_a_clean_body_exits_0(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": SHORT, "user": {"login": "dkagi"}}}))
        comments = self._tmp("c.json", json.dumps([{"body": "Looks fine."}]))
        self.assertEqual(cpb.main(["--event", event, "--comments", comments]), 0)

    def test_an_event_with_a_tainted_body_exits_1(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": SHORT + "\n\nCo-Authored-By: x",
                               "user": {"login": "dkagi"}}}))
        self.assertEqual(cpb.main(["--event", event, "--comments", self._tmp("c.json", "[]")]), 1)

    def test_a_bot_event_exits_0(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": "Generated with Claude Code.",
                               "user": {"login": "dependabot[bot]"}}}))
        self.assertEqual(cpb.main(["--event", event]), 0)

    def test_an_unreadable_comments_file_cannot_evaluate(self):
        """Absent input does not answer: exit 2, never a pass."""
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": SHORT, "user": {"login": "dkagi"}}}))
        missing = str(Path(self.dir.name) / "nope.json")
        self.assertEqual(cpb.main(["--event", event, "--comments", missing]), 2)
        bad = self._tmp("bad.json", "{not json")
        self.assertEqual(cpb.main(["--event", event, "--comments", bad]), 2)

    def test_no_input_at_all_cannot_evaluate(self):
        self.assertEqual(cpb.main([]), 2)

    def test_local_use_with_body_and_comment_files(self):
        body = self._tmp("body.md", SHORT)
        comment = self._tmp("comment.md", "Co-Authored-By: x")
        self.assertEqual(cpb.main(["--body-file", body]), 0)
        self.assertEqual(cpb.main(["--body-file", body, "--comment-file", comment]), 1)


class TheWrapperIsThin(unittest.TestCase):
    """crm#1719: the script is a wrapper over the one shared implementation,
    so a fix made in `fsg_common.pr_body` reaches this repo's gate."""

    def test_the_script_delegates_to_the_shared_module(self):
        from fsg_common import pr_body
        self.assertIs(cpb.main, pr_body.main)
        self.assertIs(cpb.check, pr_body.check)


class TheWorkflowRunsIt(unittest.TestCase):
    """The check is only a check if a workflow calls it on the events that
    change a body: `edited` is the one a plain `pull_request:` trigger omits."""

    def test_the_workflow_names_the_script_and_the_edited_event(self):
        text = (REPO / ".github" / "workflows" / "pr-body.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/check_pr_body.py", text)
        self.assertIn("edited", text)
        self.assertIn("/comments", text)


if __name__ == "__main__":
    unittest.main()
