"""`fsg_common.merge_on_green` with gh and git faked through the injectable runners.

Ported from fsg-estimating-crm/tests/test_merge_on_green.py (crm#1719), plus the
rules the other repos gain by sharing it.
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace as R

from fsg_common import merge_on_green as m

CLONE = "C:/Users/dkagi/fsg-estimating-crm"
WT = "C:/Users/dkagi/wt-x"


def run_(name, concl="SUCCESS", start="2026-09-30T01:00:00Z", status="COMPLETED"):
    return {"name": name, "status": status, "conclusion": concl, "startedAt": start}


def pr(**kw):
    d = {"number": 5, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE",
         "body": "Closes #5\n\nShort.", "comments": [], "headRefName": "feat-x",
         "baseRefName": "main", "statusCheckRollup": [run_("ci")],
         "changedFiles": 2, "additions": 10, "deletions": 1}
    d.update(kw)
    return d


# not-a-gate: transport (gh and git runners); the gate logic runs for real.
# The unreadable-answer refusals are in test_real_gates.py
class Harness:
    def __init__(self, views, dirty=False, wt=True, cur="main", main_dirty=False,
                 children="[]", extra=()):
        self.children, self.extra = children, list(extra)
        self.views, self.dirty, self.wt = list(views), dirty, wt
        self.cur, self.main_dirty = cur, main_dirty
        self.gitcalls, self.lines, self.merged, self.removed = [], [], False, False

    def gh(self, cmd):
        if cmd[2] == "merge":
            self.merged = True
            return R(rc=0, out="", err="")
        if cmd[2] == "list":
            return R(rc=0 if self.children is not None else 1, out=self.children or "", err="boom")
        if cmd[-1] == "state":
            return R(rc=0, out=json.dumps({"state": "MERGED" if self.merged else "OPEN"}), err="")
        if cmd[-1] == "mergeCommit":
            return R(rc=0, out=json.dumps({"mergeCommit": {"oid": "abc123"}}), err="")
        v = self.views.pop(0) if len(self.views) > 1 else self.views[0]
        return R(rc=0, out=json.dumps(v), err="")

    def git(self, cmd):
        self.gitcalls.append(cmd)
        a = cmd[3:]
        if a[:2] == ["worktree", "list"]:
            s = f"worktree {CLONE}\nHEAD a\nbranch refs/heads/{self.cur}\n\n"
            if self.wt and not self.removed:
                s += f"worktree {WT}\nHEAD b\nbranch refs/heads/feat-x\n\n"
            return R(rc=0, out=s, err="")
        if a[0] == "status":
            d = self.dirty if cmd[2] == WT else self.main_dirty
            return R(rc=0, out=" M f.py\n" if d else "", err="")
        if a[:2] == ["rev-parse", "--abbrev-ref"]:
            return R(rc=0, out=self.cur + "\n", err="")
        if a[:2] == ["worktree", "remove"]:
            self.removed = True
        return R(rc=0, out="", err="")

    def go(self, repo="FremantleSteel/fsg-estimating-crm"):
        argv = ["5", "-R", repo, "--timeout", "100", "--interval", "1", *self.extra]
        t = iter(range(0, 10000, 30))
        return m.main(argv, gh=self.gh, git=self.git, sleep=lambda s: None,
                      clock=lambda: next(t), out=self.lines.append)

    def ran(self, *frag):
        return any(list(frag) == c[3:3 + len(frag)] for c in self.gitcalls)


class Refusals(unittest.TestCase):
    def refused(self, view, text):
        h = Harness([view])
        self.assertEqual(h.go(), m.REFUSED)
        self.assertIn(text, " ".join(h.lines))
        self.assertFalse(h.merged)

    def test_failure(self):
        self.refused(pr(statusCheckRollup=[run_("ci", "FAILURE")]), "ci (FAILURE)")

    def test_timed_out(self):
        self.refused(pr(statusCheckRollup=[run_("ci", "TIMED_OUT")]), "TIMED_OUT")

    def test_generated_with(self):
        self.refused(pr(body="Closes #5\n\nGenerated with Claude Code"), "Generated with")

    def test_co_authored_by_in_first_comment(self):
        self.refused(pr(comments=[{"body": "Co-Authored-By: x"}]), "Co-Authored-By")

    def test_400_words(self):
        self.refused(pr(body="Closes #5 " + "w " * 398), "400 words")

    def test_399_words_merges(self):
        self.assertEqual(Harness([pr(body="Closes #5 " + "w " * 397)]).go(), m.OK)

    def test_no_closing_keyword(self):
        self.refused(pr(body="Just a change."), "closing keyword")

    def test_no_issue_line_is_accepted(self):
        self.assertEqual(Harness([pr(body="No issue: doc typo.")]).go(), m.OK)

    def test_conflicting(self):
        self.refused(pr(mergeable="CONFLICTING"), "CONFLICTING")

    def test_draft(self):
        self.refused(pr(isDraft=True), "draft")

    def test_not_open(self):
        self.refused(pr(state="CLOSED"), "CLOSED")

    def test_no_checks_at_all_is_absent_not_pass(self):
        self.refused(pr(statusCheckRollup=[]), "absent")


class SharedGate(unittest.TestCase):
    """The merge gate GitHub Free cannot give a private repo."""

    def refused(self, h, text):
        self.assertEqual(h.go(), m.REFUSED)
        self.assertIn(text, " ".join(h.lines))
        self.assertFalse(h.merged)

    def test_empty_diff_refuses(self):
        self.refused(Harness([pr(changedFiles=0, additions=0, deletions=0)]), "diff is empty")

    def test_unreadable_diff_refuses(self):
        v = pr()
        del v["changedFiles"]
        self.refused(Harness([v]), "could not be read")

    def test_stacked_parent_with_open_child_refuses(self):
        self.refused(Harness([pr()], children='[{"number": 9}]'), "#9")

    def test_unreadable_child_list_refuses(self):
        self.refused(Harness([pr()], children=None), "cannot list open child PRs")

    def test_garbled_child_list_refuses(self):
        self.refused(Harness([pr()], children='{"x": 1}'), "could not be parsed")

    def test_merge_commit_is_printed(self):
        h = Harness([pr()])
        self.assertEqual(h.go(), m.OK)
        self.assertIn("merge commit abc123", h.lines)

    def test_required_check_missing_refuses_after_waiting(self):
        self.refused(Harness([pr()], extra=["--require", "leak-guard"]), "absent: leak-guard")

    def test_required_check_pending_does_not_merge(self):
        v = pr(statusCheckRollup=[run_("ci"), run_("leak-guard", None, status="IN_PROGRESS")])
        h = Harness([v], extra=["--require", "leak-guard"])
        self.assertEqual(h.go(), m.PENDING)
        self.assertFalse(h.merged)

    def test_required_check_red_refuses(self):
        v = pr(statusCheckRollup=[run_("ci"), run_("leak-guard", "FAILURE")])
        self.refused(Harness([v], extra=["--require", "leak-guard"]), "leak-guard (FAILURE)")

    def test_empty_rollup_with_required_refuses(self):
        self.refused(Harness([pr(statusCheckRollup=[])], extra=["--require", "ci"]), "absent: ci")

    def test_required_check_green_merges(self):
        v = pr(statusCheckRollup=[run_("ci"), run_("leak-guard")])
        self.assertEqual(Harness([v], extra=["--require", "ci", "--require", "leak-guard"]).go(), m.OK)


class Waiting(unittest.TestCase):
    def test_pending_then_green_merges(self):
        h = Harness([pr(statusCheckRollup=[run_("ci", None, status="IN_PROGRESS")]), pr()])
        self.assertEqual(h.go(), m.OK)
        self.assertTrue(h.merged)

    def test_timeout_is_pending_exit_2(self):
        h = Harness([pr(statusCheckRollup=[run_("ci", None, status="IN_PROGRESS")])])
        self.assertEqual(h.go(), m.PENDING)
        self.assertFalse(h.merged)

    def test_cancelled_and_older_runs_are_superseded(self):
        roll = [run_("ci", "FAILURE", "2026-09-30T01:00:00Z"),
                run_("ci", "SUCCESS", "2026-09-30T02:00:00Z"),
                run_("lint", "CANCELLED"), run_("lint", "SUCCESS")]
        self.assertEqual(Harness([pr(statusCheckRollup=roll)]).go(), m.OK)

    def test_newer_failure_beats_older_success(self):
        roll = [run_("ci", "SUCCESS", "2026-09-30T01:00:00Z"),
                run_("ci", "FAILURE", "2026-09-30T02:00:00Z")]
        self.assertEqual(Harness([pr(statusCheckRollup=roll)]).go(), m.REFUSED)

    def test_only_cancelled_is_absent(self):
        self.assertEqual(Harness([pr(statusCheckRollup=[run_("ci", "CANCELLED")])]).go(), m.REFUSED)


class Cleanup(unittest.TestCase):
    def test_clean_worktree_removed_branch_deleted_main_ff(self):
        h = Harness([pr()])
        self.assertEqual(h.go(), m.OK)
        self.assertTrue(h.ran("worktree", "remove", WT))
        self.assertTrue(h.ran("branch", "-D", "feat-x"))
        self.assertTrue(h.ran("merge", "--ff-only", "origin/main"))

    def test_dirty_worktree_kept_but_merge_reported(self):
        h = Harness([pr()], dirty=True)
        self.assertEqual(h.go(), m.INCOMPLETE)
        self.assertTrue(h.merged)
        self.assertFalse(h.ran("worktree", "remove", WT))
        self.assertTrue(any("MERGED" in ln for ln in h.lines))
        self.assertTrue(any("DIRTY" in ln for ln in h.lines))

    def test_main_clone_off_main_not_fast_forwarded(self):
        h = Harness([pr()], cur="other")
        h.go()
        self.assertFalse(h.ran("merge", "--ff-only", "origin/main"))

    def test_dirty_main_clone_not_fast_forwarded(self):
        h = Harness([pr()], main_dirty=True)
        h.go()
        self.assertFalse(h.ran("merge", "--ff-only", "origin/main"))

    def test_no_local_worktree_is_fine(self):
        self.assertEqual(Harness([pr()], wt=False).go(), m.OK)


class SharedAcrossRepos(unittest.TestCase):
    """Rules every repo gains now that crm's helper is the shared one (crm#1719)."""

    def test_default_clone_is_home_plus_repo_name_for_each_repo(self):
        for name in ("fsg-tender-review", "fsg-estimating-tools",
                     "fsg-bluebeam-steel-standards", "fsg-common"):
            h = Harness([pr()], wt=False)
            h.go(repo=f"FremantleSteel/{name}")
            clones = {c[2] for c in h.gitcalls}
            self.assertEqual(clones, {m.HOME + "\\" + name}, name)

    def test_no_issue_heading_form_merges(self):
        # Before slice 1 only crm accepted the `## No issue:` heading form.
        body = "## No issue:\nDocs only, nothing to close.\n"
        self.assertEqual(Harness([pr(body=body)]).go(), m.OK)

    def test_pull_url_is_not_a_close(self):
        # tools/tr/bb's old copies counted a /pull/N URL as a close; GitHub closes nothing.
        body = "Closes https://github.com/FremantleSteel/fsg-common/pull/12\n"
        h = Harness([pr(body=body)])
        self.assertEqual(h.go(), m.REFUSED)
        self.assertFalse(h.merged)


if __name__ == "__main__":
    unittest.main()
