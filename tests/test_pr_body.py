"""`fsg_common.pr_body`: the two rules, their edges, and the absent inputs.

Audit 6 Sep 2026, Part 4, sessions' item 7. Each rule is shown failing, not
only passing: a check only ever observed green is not evidence.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fsg_common import pr_body as cpb

SHORT = "Closes #12\n\nOne sentence of what changed.\n\nTests: 7 before, 9 after."


class TheClosingKeyword(unittest.TestCase):
    def test_the_plain_forms_pass(self):
        for body in ("Closes #12", "closes #12", "Fixes #3", "Resolves #4", "Closed #5",
                     "Fixed: #6", "fix #7", "Resolves FremantleSteel/fsg-estimating-crm#12",
                     "Closes https://github.com/FremantleSteel/fsg-estimating-crm/issues/12"):
            self.assertEqual(cpb.check(body, None, "dkagi"), [], body)

    def test_a_reference_without_a_keyword_fails(self):
        for body in ("See #12 for context.", "#12", "Related to #12.", "Part of tr#12."):
            problems = cpb.check(body, None, "dkagi")
            self.assertEqual(len(problems), 1, body)
            self.assertIn("no closing keyword", problems[0])

    def test_a_repo_nickname_shorthand_with_a_keyword_still_fails(self):
        """`crm#447` / `tools#65` read fine to a person but are not one of
        GitHub's three forms -- no slash means GitHub reads it as plain
        text. Three PRs made exactly this mistake on 18 Sep 2026 (crm#820,
        crm#821, tools#344): the keyword was present, so a person skimming
        the body would assume the check was wrong, not the body."""
        for body in ("Closes crm#447", "Fixes tools#65", "Resolves tr#12"):
            problems = cpb.check(body, None, "dkagi")
            self.assertEqual(len(problems), 1, body)
            self.assertIn("no closing keyword", problems[0])
            # The message must say what WOULD have worked, not just that
            # this didn't -- the point of this test is the message, not
            # only the verdict.
            self.assertIn("owner/repo#N", problems[0])
            self.assertIn("crm#447", problems[0])

    def test_an_issue_url_passes_but_a_pull_url_does_not(self):
        """GitHub closes an issue only from an `/issues/N` URL. A `/pull/N`
        URL links a pull request and closes no issue, so a keyword in front
        of one is a keyword GitHub ignores -- the same false-green the
        `crm#N` shorthand gives, and squarely what crm#960 is about. The
        positive control is the second loop: it must go red."""
        for body in ("Closes https://github.com/FremantleSteel/fsg-estimating-crm/issues/12",
                     "Resolves https://github.com/owner/repo/issues/3"):
            self.assertEqual(cpb.check(body, None, "dkagi"), [], body)
        for body in ("Closes https://github.com/FremantleSteel/fsg-estimating-crm/pull/12",
                     "Resolves https://github.com/owner/repo/pull/3"):
            problems = cpb.check(body, None, "dkagi")
            self.assertEqual(len(problems), 1, body)
            self.assertIn("no closing keyword", problems[0])
            self.assertIn("pull/N", problems[0])

    def test_the_keyword_alone_is_not_enough(self):
        self.assertTrue(cpb.check("This fixes the bug.", None, "dkagi"))
        self.assertTrue(cpb.check("Closes nothing.", None, "dkagi"))

    def test_a_stated_no_issue_line_passes_and_says_why(self):
        self.assertEqual(cpb.check("No issue: dependency bump.\n\nTests: none.", None, "dkagi"), [])
        # The reason is required: an empty "No issue:" is not a statement.
        self.assertTrue(cpb.check("No issue:\n\nTests: none.", None, "dkagi"))

    def test_the_heading_form_of_no_issue_is_accepted(self):
        """crm#960: four lanes in one evening wrote `## No issue:` with the
        reason on the next line and the gate rejected all four. A heading with
        its reason underneath is a normal, unambiguous way to write a PR body,
        so it passes; the same body was rejected before this fix."""
        for body in ("## No issue:\nPure dependency bump, no tracked work.",
                     "# No issue:\nDocs typo only.",
                     "**No issue:** internal tooling tweak.",
                     "> No issue: reverting my own noise commit.",
                     "- No issue: config-only change."):
            self.assertEqual(cpb.check(body, None, "dkagi"), [], body)

    def test_a_bare_no_issue_heading_with_no_reason_still_fails(self):
        # The guard is that the reason is STATED. A heading with a blank line
        # under it, or nothing under it, does not state one.
        for body in ("## No issue:\n\nSome later unrelated section.",
                     "## No issue:"):
            problems = cpb.check(body, None, "dkagi")
            self.assertEqual(len(problems), 1, body)
            self.assertIn("no closing keyword", problems[0])

    def test_the_no_issue_helper_directly(self):
        self.assertTrue(cpb.states_no_issue("## No issue:\nreason here"))
        self.assertTrue(cpb.states_no_issue("No issue: reason here"))
        self.assertFalse(cpb.states_no_issue("## No issue:\n\nseparate paragraph"))
        self.assertFalse(cpb.states_no_issue("No issue:"))
        self.assertFalse(cpb.states_no_issue("Notes on the issue: whatever"))

    def test_an_empty_body_fails_with_its_own_reason(self):
        for body in (None, "", "   \n"):
            problems = cpb.check(body, None, "dkagi")
            self.assertEqual(len(problems), 1)
            self.assertIn("empty", problems[0])


class PartOf(unittest.TestCase):
    """crm#1965: lane rule 5 allows `Part of #N`; the gate now agrees."""

    def test_part_of_an_issue_passes_before_merge(self):
        for body in ("Part of #12\n\nSlice 2.", "part of: #12",
                     "Part of FremantleSteel/fsg-estimating-crm#1798",
                     "Part of https://github.com/FremantleSteel/fsg-common/issues/7"):
            self.assertEqual(cpb.check(body, None, "dkagi"), [], body)

    def test_control_part_of_with_no_real_reference_still_fails(self):
        for body in ("Part of tr#12.", "Part of the 1798 work.", "Part of #"):
            problems = cpb.check(body, None, "dkagi")
            self.assertEqual(len(problems), 1, body)
            self.assertIn("no closing keyword", problems[0])
            self.assertIn("Part of #N", problems[0])

    def test_on_merge_part_of_excuses_an_empty_close_list(self):
        self.assertEqual(cpb.check("Part of #12\n\nSlice 2.", None, "dkagi",
                                   closing_refs=[]), [])

    def test_on_merge_a_failed_close_is_not_excused_by_part_of(self):
        """`Closes crm#5` resolved to nothing; a `Part of` line beside it must
        not turn GitHub's empty answer green -- the closed-on-merge check
        stays its own check."""
        problems = cpb.check("Closes crm#5\nPart of #12", None, "dkagi", closing_refs=[])
        self.assertEqual(len(problems), 1)
        self.assertIn("closingIssuesReferences", problems[0])


class TheWordLimit(unittest.TestCase):
    def _body_of(self, n: int) -> str:
        return "Closes #1 " + " ".join(["w"] * (n - 2))

    def test_one_under_the_limit_passes(self):
        body = self._body_of(cpb.WORD_LIMIT - 1)
        self.assertEqual(cpb.word_count(body), cpb.WORD_LIMIT - 1)
        self.assertEqual(cpb.check(body, None, "dkagi"), [])

    def test_at_the_limit_fails(self):
        body = self._body_of(cpb.WORD_LIMIT)
        problems = cpb.check(body, None, "dkagi")
        self.assertEqual(len(problems), 1)
        self.assertIn(f"{cpb.WORD_LIMIT} words", problems[0])

    def test_the_first_comment_counts_toward_the_limit(self):
        body = self._body_of(300)
        self.assertEqual(cpb.check(body, " ".join(["c"] * 99), "dkagi"), [])
        problems = cpb.check(body, " ".join(["c"] * 100), "dkagi")
        self.assertEqual(len(problems), 1)
        self.assertIn("first comment 100", problems[0])

    def test_both_rules_can_fail_together(self):
        problems = cpb.check(" ".join(["w"] * 500), None, "dkagi")
        self.assertEqual(len(problems), 2)


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
        body = SHORT + "\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"
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


class GitHubsOwnAnswer(unittest.TestCase):
    """crm#960's real remaining work: when `closingIssuesReferences` is
    supplied it decides rule 1, not the body text. Body parsing can only
    approximate what GitHub will close; its own field is the fact."""

    def test_a_populated_refs_list_passes_whatever_the_body_says(self):
        # No closing keyword in the body at all -- but GitHub resolved one,
        # so the merge WILL close it. The body form is then moot.
        self.assertEqual(cpb.check("Some prose with no keyword.", None, "dkagi",
                                   closing_refs=[933]), [])

    def test_an_empty_refs_list_fails_even_when_the_body_looks_linked(self):
        """The positive control for the whole issue. A cross-repo
        `owner/repo#N` satisfies the body regex, so the pre-merge body-only
        job passes it -- but GitHub closes no issue here, which only
        `closingIssuesReferences` reveals. It must go red."""
        for body in ("Fixes some-org/other-repo#12", "Closes crm/tools#5",
                     "Resolves https://github.com/o/r/pull/9"):
            problems = cpb.check(body, None, "dkagi", closing_refs=[])
            self.assertEqual(len(problems), 1, body)
            self.assertIn("closingIssuesReferences", problems[0])
            self.assertIn("empty", problems[0])

    def test_an_empty_refs_list_is_excused_by_a_no_issue_line(self):
        body = "No issue: closes none, addresses crm#936.\n\nWhat changed."
        self.assertEqual(cpb.check(body, None, "dkagi", closing_refs=[]), [])

    def test_an_empty_refs_list_with_an_ordinary_body_fails(self):
        problems = cpb.check("Closes #933\n\nWhat changed.", None, "dkagi", closing_refs=[])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("closingIssuesReferences", problems[0])

    def test_none_means_not_fetched_and_the_body_still_decides(self):
        # The default: the pre-merge job passes no refs, so the body rules run
        # exactly as before -- the shorthand still fails with its own message.
        self.assertEqual(cpb.check("Closes #933", None, "dkagi"), [])
        self.assertIn("no closing keyword", cpb.check("Closes crm#933", None, "dkagi")[0])


class TheClosingRefsParser(unittest.TestCase):
    def test_the_gh_pr_view_wrapper_object_is_read(self):
        listing = json.dumps({"closingIssuesReferences": [{"number": 933}, {"number": 12}]})
        self.assertEqual(cpb.closing_issue_numbers(listing), [933, 12])

    def test_a_bare_list_is_read_too(self):
        self.assertEqual(cpb.closing_issue_numbers(json.dumps([{"number": 5}])), [5])

    def test_an_empty_list_is_a_real_answer_not_an_error(self):
        self.assertEqual(cpb.closing_issue_numbers("[]"), [])
        self.assertEqual(cpb.closing_issue_numbers('{"closingIssuesReferences": []}'), [])

    def test_a_non_list_payload_is_refused(self):
        with self.assertRaises(ValueError):
            cpb.closing_issue_numbers(json.dumps("nope"))


class Exemptions(unittest.TestCase):
    def test_a_bot_author_is_exempt_whatever_the_body(self):
        long_and_unlinked = " ".join(["release", "notes"] * 400)
        self.assertEqual(cpb.check(long_and_unlinked, None, "dependabot[bot]"), [])

    def test_a_person_is_not(self):
        self.assertTrue(cpb.check("Bumps ruff from 1 to 2.", None, "dkagi"))


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

    def test_an_event_with_a_good_body_exits_0(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": SHORT, "user": {"login": "dkagi"}}}))
        comments = self._tmp("c.json", json.dumps([{"body": "Looks fine."}]))
        self.assertEqual(cpb.main(["--event", event, "--comments", comments]), 0)

    def test_an_event_with_a_bad_body_exits_1(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": "See #12.", "user": {"login": "dkagi"}}}))
        self.assertEqual(cpb.main(["--event", event, "--comments", self._tmp("c.json", "[]")]), 1)

    def test_a_bot_event_exits_0(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": "x " * 900, "user": {"login": "dependabot[bot]"}}}))
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

    def test_closing_refs_decide_the_verdict_on_a_merged_pr(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": "Fixes some-org/other#12\n\nWhat changed.",
                              "user": {"login": "dkagi"}}}))
        comments = self._tmp("c.json", "[]")
        empty = self._tmp("refs-empty.json", json.dumps({"closingIssuesReferences": []}))
        full = self._tmp("refs-full.json",
                         json.dumps({"closingIssuesReferences": [{"number": 12}]}))
        # Body regex would pass this cross-repo ref, but GitHub closes nothing.
        self.assertEqual(cpb.main(
            ["--event", event, "--comments", comments, "--closing-refs", empty]), 1)
        # Same body, but GitHub did resolve a close: it passes.
        self.assertEqual(cpb.main(
            ["--event", event, "--comments", comments, "--closing-refs", full]), 0)

    def test_an_unreadable_closing_refs_file_cannot_evaluate(self):
        event = self._tmp("event.json", json.dumps(
            {"pull_request": {"body": SHORT, "user": {"login": "dkagi"}}}))
        bad = self._tmp("bad.json", "{not json")
        self.assertEqual(cpb.main(["--event", event, "--closing-refs", bad]), 2)

    def test_local_use_with_body_and_comment_files(self):
        body = self._tmp("body.md", SHORT)
        comment = self._tmp("comment.md", " ".join(["c"] * 390))
        self.assertEqual(cpb.main(["--body-file", body]), 0)
        self.assertEqual(cpb.main(["--body-file", body, "--comment-file", comment]), 1)
