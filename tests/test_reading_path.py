"""`fsg_common.reading_path`: the estate-wide reading-path cap, crm#557/635.

Each rule is shown failing, not only passing -- a check only ever observed
green is not evidence.
"""
from __future__ import annotations

import os
import subprocess as sp
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from fsg_common import reading_path as rp


def _reader(words_per_file: dict[tuple[str, str], int]):
    """A `read(repo, path)` that returns `n` space-separated words for each
    file named in `words_per_file`, and raises KeyError for anything else --
    so a test naming the wrong file fails loudly rather than silently
    reading zero."""
    def read(repo: str, path: str) -> str:
        n = words_per_file[(repo, path)]
        return " ".join(["w"] * n)
    return read


class WordCount(unittest.TestCase):
    def test_matches_wc_w_semantics(self):
        self.assertEqual(rp.word_count("one two  three\nfour\tfive"), 5)

    def test_empty_and_whitespace_only(self):
        self.assertEqual(rp.word_count(""), 0)
        self.assertEqual(rp.word_count("   \n\t  "), 0)

    def test_an_em_dash_is_its_own_token_not_glued_to_a_neighbour(self):
        self.assertEqual(rp.word_count("word one — word two"), 5)


class Measure(unittest.TestCase):
    def test_sums_every_named_file(self):
        counts = rp.measure(_reader({f: 10 for f in rp.FILES}), files=rp.FILES)
        self.assertEqual(sum(counts.values()), 10 * len(rp.FILES))
        self.assertEqual(set(counts), set(rp.FILES))

    def test_a_file_that_cannot_be_read_refuses_rather_than_dropping_it(self):
        def read(repo: str, path: str) -> str:
            if (repo, path) == rp.FILES[2]:
                raise rp.Unavailable(f"{repo}/{path}: pretend 404")
            return "w " * 10

        with self.assertRaises(rp.Unavailable):
            rp.measure(read, files=rp.FILES)


class Verdict(unittest.TestCase):
    def _counts(self, total: int) -> dict[tuple[str, str], int]:
        counts = {f: 0 for f in rp.FILES}
        counts[rp.FILES[0]] = total
        return counts

    def test_the_total_prints_on_every_run_pass_or_fail(self):
        code_pass, lines_pass = rp.verdict(self._counts(rp.WORD_LIMIT - 1))
        code_fail, lines_fail = rp.verdict(self._counts(rp.WORD_LIMIT + 1))
        self.assertEqual(code_pass, 0)
        self.assertEqual(code_fail, 1)
        self.assertTrue(any("TOTAL" in line for line in lines_pass))
        self.assertTrue(any("TOTAL" in line for line in lines_fail))

    def test_at_the_limit_passes_and_over_it_fails(self):
        code_at, _ = rp.verdict(self._counts(rp.WORD_LIMIT))
        self.assertEqual(code_at, 0)
        code_over, lines_over = rp.verdict(self._counts(rp.WORD_LIMIT + 1))
        self.assertEqual(code_over, 1)
        self.assertTrue(any("OVER LIMIT by 1 word" in line for line in lines_over))

    def test_the_cap_is_7500_exactly_with_a_control_either_side(self):
        """crm#1798: 7,500 passes, 7,501 fails. Pins the number itself, so
        the other tests (all relative to WORD_LIMIT) cannot hide a drift."""
        self.assertEqual(rp.WORD_LIMIT, 7_500)
        code_at, _ = rp.verdict(self._counts(7_500))
        code_over, _ = rp.verdict(self._counts(7_501))
        self.assertEqual(code_at, 0)
        self.assertEqual(code_over, 1)

    def test_a_synthetic_push_over_the_cap_fails(self):
        """The fixture proving the gate catches growth, not just runs under
        a limit it happens to already be under."""
        counts = {
            rp.FILES[0]: 7_208,
            rp.FILES[1]: 5_763,
            rp.FILES[2]: 6_900,
            rp.FILES[3]: 1_615,
            rp.FILES[4]: 1_087 + 8_000,  # the synthetic bloat
        }
        code, lines = rp.verdict(counts)
        self.assertEqual(code, 1)
        total = sum(counts.values())
        self.assertGreater(total, rp.WORD_LIMIT)
        self.assertTrue(any("OVER LIMIT" in line for line in lines))


class ReadLocal(unittest.TestCase):
    def test_a_repos_own_file_is_read_from_the_tree_not_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CLAUDE.md"
            path.write_text("one two three", encoding="utf-8")
            text = rp.read_local("CLAUDE.md", repo_root=tmp)
            self.assertEqual(rp.word_count(text), 3)

    def test_a_missing_local_file_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rp.Unavailable):
                rp.read_local("CLAUDE.md", repo_root=tmp)


class Token(unittest.TestCase):
    def test_fsg_common_pat_wins_over_the_others(self):
        env = {"FSG_COMMON_PAT": "a", "GH_TOKEN": "b", "GITHUB_TOKEN": "c"}
        old = {k: os.environ.get(k) for k in env}
        try:
            os.environ.update(env)
            self.assertEqual(rp.token(), "a")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_no_credential_is_none_not_an_exception(self):
        old = {k: os.environ.pop(k, None) for k in
               ("FSG_COMMON_PAT", "GH_TOKEN", "GITHUB_TOKEN")}
        try:
            self.assertIsNone(rp.token())
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


class ThisRepoParameterisation(unittest.TestCase):
    """The property that did not exist before this module: which repo is
    "local" is a parameter, not a hardcoded constant -- a repo that owns
    more than one file must read all of them locally, and a repo that owns
    none must refuse rather than silently reading nothing as zero.

    No repo in the real `FILES` owns two files today (fsg-tender-review's
    `docs/README.md` was removed from the compulsory set 25 Sep 2026,
    crm#1009), so the two-file case is exercised here against a synthetic
    `FILES` rather than the real one -- the capability is still real code
    and still needs a test that can fail."""

    def test_a_repo_that_owns_two_files_reads_both_locally(self):
        synthetic_files = rp.FILES + (("fsg-tender-review", "docs/README.md"),)
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "docs"))
            Path(tmp, "CLAUDE.md").write_text("a b c", encoding="utf-8")
            Path(tmp, "docs", "README.md").write_text("d e", encoding="utf-8")

            calls = []

            def api_read(repo, path, tok):
                calls.append((repo, path))
                return "z " * 100

            old = os.environ.get("FSG_COMMON_PAT")
            os.environ["FSG_COMMON_PAT"] = "tok"
            try:
                # not-a-gate: the input list (which files exist), not a decision
                # real-gate test: test_read_via_api_http_error_is_unavailable
                with mock.patch.object(rp, "FILES", synthetic_files), \
                     mock.patch.object(rp, "read_via_api", side_effect=api_read):
                    code = rp.main("fsg-tender-review", [], repo_root=tmp)
            finally:
                if old is None:
                    os.environ.pop("FSG_COMMON_PAT", None)
                else:
                    os.environ["FSG_COMMON_PAT"] = old
            self.assertEqual(code, 0)
            # Both fsg-tender-review files came from disk, never the API.
            self.assertNotIn(("fsg-tender-review", "CLAUDE.md"), calls)
            self.assertNotIn(("fsg-tender-review", "docs/README.md"), calls)
            # Every other repo's file did go over the API.
            other_repos = {repo for repo, _ in synthetic_files if repo != "fsg-tender-review"}
            self.assertEqual({r for r, _ in calls}, other_repos)

    def test_a_repo_that_owns_none_of_the_files_refuses(self):
        code = rp.main("some-other-repo", [], repo_root=tempfile.gettempdir())
        self.assertEqual(code, 2)

    def test_every_real_repo_owns_exactly_one_file_today(self):
        """Not a rule -- just today's fact, pinned so the next reader of
        this test notices if it changes rather than assuming it still
        holds."""
        from collections import Counter
        counts = Counter(repo for repo, _ in rp.FILES)
        self.assertTrue(all(n == 1 for n in counts.values()), counts)


class TheCommandLine(unittest.TestCase):
    def test_no_credential_refuses_with_exit_2(self):
        old = {k: os.environ.pop(k, None) for k in
               ("FSG_COMMON_PAT", "GH_TOKEN", "GITHUB_TOKEN",
                "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "PR_BASE_SHA")}
        try:
            self.assertEqual(rp.main("fsg-common", []), 2)
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


class DependabotActorExemption(unittest.TestCase):
    _ENV = ("FSG_COMMON_PAT", "GH_TOKEN", "GITHUB_TOKEN",
            "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "PR_BASE_SHA")

    def setUp(self):
        self._old = {k: os.environ.pop(k, None) for k in self._ENV}

    def tearDown(self):
        for k, v in self._old.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def _set(self, **kw):
        for k, v in kw.items():
            os.environ[k] = v

    def test_dependabot_actor_true_only_for_the_exact_platform_case(self):
        self._set(GITHUB_ACTOR="dependabot[bot]", GITHUB_EVENT_NAME="pull_request")
        self.assertTrue(rp.dependabot_actor())

    def test_dependabot_actor_false_for_a_human_pushing_a_commit(self):
        self._set(GITHUB_ACTOR="Rostov-au", GITHUB_EVENT_NAME="pull_request")
        self.assertFalse(rp.dependabot_actor())

    def test_a_dependabot_run_that_did_not_touch_local_files_is_skipped(self):
        self._set(GITHUB_ACTOR="dependabot[bot]", GITHUB_EVENT_NAME="pull_request",
                   PR_BASE_SHA="irrelevant")
        # real-gate test: test_local_file_touched_since_detects_a_real_change
        with mock.patch.object(rp, "local_file_touched_since", return_value=False):
            code = rp.main("fsg-common", [])
        self.assertEqual(code, 0)

    def test_a_dependabot_run_that_did_touch_a_local_file_still_refuses(self):
        self._set(GITHUB_ACTOR="dependabot[bot]", GITHUB_EVENT_NAME="pull_request",
                   PR_BASE_SHA="irrelevant")
        # real-gate test: test_local_file_touched_since_detects_a_real_change
        with mock.patch.object(rp, "local_file_touched_since", return_value=True):
            code = rp.main("fsg-common", [])
        self.assertEqual(code, 2)

    def test_a_dependabot_run_with_an_unmeasurable_diff_still_refuses(self):
        self._set(GITHUB_ACTOR="dependabot[bot]", GITHUB_EVENT_NAME="pull_request")
        # real-gate test: test_local_file_touched_since_with_no_base_sha_is_unmeasurable
        with mock.patch.object(rp, "local_file_touched_since", return_value=None):
            code = rp.main("fsg-common", [])
        self.assertEqual(code, 2)

    def test_a_non_dependabot_actor_with_no_token_still_refuses(self):
        self._set(GITHUB_ACTOR="a-human-with-no-token",
                   GITHUB_EVENT_NAME="pull_request", PR_BASE_SHA="deadbeef")
        self.assertEqual(rp.main("fsg-common", []), 2)

    def test_local_file_touched_since_with_no_base_sha_is_unmeasurable(self):
        self.assertIsNone(rp.local_file_touched_since("", "/tmp", ("CLAUDE.md",)))

    def test_local_file_touched_since_with_no_paths_is_unmeasurable(self):
        self.assertIsNone(rp.local_file_touched_since("HEAD", "/tmp", ()))

    def test_local_file_touched_since_detects_a_real_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            def run(*args):
                sp.run(["git", *args], cwd=tmp, check=True, capture_output=True)
            run("init", "-q")
            run("config", "user.email", "t@example.com")
            run("config", "user.name", "t")
            (Path(tmp) / "CLAUDE.md").write_text("one\n", encoding="utf-8")
            run("add", "CLAUDE.md")
            run("commit", "-q", "-m", "base")
            base = sp.run(["git", "rev-parse", "HEAD"], cwd=tmp, check=True,
                           capture_output=True, text=True).stdout.strip()
            (Path(tmp) / "CLAUDE.md").write_text("two\n", encoding="utf-8")
            run("commit", "-aq", "-m", "edit")
            self.assertTrue(rp.local_file_touched_since(base, tmp, ("CLAUDE.md",)))

    def test_local_file_touched_since_reads_the_real_local_history(self):
        repo_root = str(Path(__file__).resolve().parents[1])
        self.assertFalse(rp.local_file_touched_since("HEAD", repo_root, ("CLAUDE.md",)))


class LiveMeasurement(unittest.TestCase):
    """Real content, real network, real credential -- skipped without one."""

    def test_todays_real_total_is_in_a_sane_band(self):
        tok = rp.token()
        if not tok:
            self.skipTest("no FSG_COMMON_PAT/GH_TOKEN/GITHUB_TOKEN in this environment")

        repo_root = str(Path(__file__).resolve().parents[1])

        def read(repo: str, path: str) -> str:
            return (rp.read_local(path, repo_root) if repo == "fsg-common"
                    else rp.read_via_api(repo, path, tok))

        try:
            counts = rp.measure(read)
        except rp.Unavailable as exc:
            self.skipTest(f"could not reach one of the six files: {exc}")
            return
        total = sum(counts.values())
        print(f"\n  live reading-path total: {total:,} words")
        self.assertGreater(total, 10_000)
        self.assertLess(total, 100_000)


if __name__ == "__main__":
    unittest.main()
