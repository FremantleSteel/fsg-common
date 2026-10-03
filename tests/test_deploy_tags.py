"""`fsg_common.deploy_tags`: the crm/tools union (crm#1976), on throwaway repos.

Each repo keeps its own full test file (crm and tools `tests/test_deploy_tags.py`,
run against this module through their wrappers). This file covers what only
the union has: both call shapes of `compare()`, the per-repo settings, the
crm rules tools lacked and the tools rules crm lacked.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fsg_common import deploy_tags as dt


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "core.autocrlf=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", str(self.remote))
        self.root = self.tmp / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        # dt.create() runs `git tag -a` itself, so the throwaway repo needs its
        # own identity (CI has no global one).
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "remote", "add", "origin", str(self.remote))
        self.commit("v1")
        # not-a-gate: a path (points the module at the throwaway repo)
        patcher = mock.patch.object(dt, "REPO_ROOT", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("REFUSE_ROLLBACK", True), ("CLI_CREATE_REQUIRES_ORIGIN", True)):
            # not-a-gate: the per-repo settings under test, pinned fail-closed
            p = mock.patch.object(dt, name, value)
            p.start()
            self.addCleanup(p.stop)

    def commit(self, text):
        (self.root / "a.txt").write_text(text, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", text)
        return git(self.root, "rev-parse", "HEAD")

    def tag(self, when, commit="HEAD", **kw):
        import datetime
        name, info = dt.create("art", commit=commit,
                               when=datetime.datetime(2026, 10, 1, 0, 0, when,
                                                      tzinfo=datetime.timezone.utc), **kw)
        self.assertIsNotNone(name, info)
        return name


class CompareCallShapes(Repo):
    def test_crm_shape_path_then_live(self):
        self.tag(1)
        self.assertEqual(dt.compare("art", "a.txt", b"v1").status, "match")

    def test_crm_shape_live_by_keyword(self):
        self.tag(1)
        self.assertEqual(dt.compare("art", "a.txt", live=b"v1").status, "match")

    def test_tools_shape_live_then_path_keyword(self):
        self.tag(1)
        self.assertEqual(dt.compare("art", b"v1", path="a.txt").status, "match")

    def test_tools_shape_content_at_fn(self):
        self.tag(1)
        out = dt.compare("art", b"X", content_at_fn=lambda tag: b"X")
        self.assertEqual(out.status, "match")

    def test_neither_or_both_is_an_error(self):
        with self.assertRaises(ValueError):
            dt.compare("art", b"v1")
        with self.assertRaises(ValueError):
            dt.compare("art", b"v1", path="a.txt", content_at_fn=lambda t: b"")
        with self.assertRaises(TypeError):
            dt.compare("art", "a.txt", b"v1", path="a.txt")


class CrmRulesNowInTools(Repo):
    def test_inversion_is_found_in_content_at_fn_mode_too(self):
        first = git(self.root, "rev-parse", "HEAD")
        self.commit("v2")
        self.tag(1)
        self.tag(2, commit=first, allow_rollback=True)
        out = dt.compare("art", b"v1", content_at_fn=lambda tag: b"v1")
        self.assertEqual(out.status, "inverted")
        self.assertTrue(out.drifted)

    def test_not_a_checkout_is_refused_not_never_deployed(self):
        elsewhere = self.tmp / "plain"
        elsewhere.mkdir()
        out = dt.compare("art", "a.txt", b"v1", repo_root=str(elsewhere))
        self.assertEqual(out.status, "refused")
        self.assertIn("not a git checkout", out.reason)

    def test_rollback_refused_when_on_and_recorded_when_off(self):
        first = git(self.root, "rev-parse", "HEAD")
        self.commit("v2")
        self.tag(1)
        name, why = dt.create("art", commit=first)
        self.assertIsNone(name)
        self.assertIn("strict ANCESTOR", why)
        # not-a-gate: the setting under test, relaxed as tools relaxes it
        with mock.patch.object(dt, "REFUSE_ROLLBACK", False):
            name, _ = dt.create("art", commit=first)
        self.assertIsNotNone(name)

    def test_tag_mismatch_needs_a_path(self):
        self.tag(1, path="a.txt")
        self.assertEqual(dt.compare("art", "a.txt", b"v1").status, "match")


class ToolsRulesNowInCrm(Repo):
    def test_unrecorded_only_with_live_mtime(self):
        self.tag(1)
        self.assertEqual(dt.compare("art", "a.txt", b"other").status, "ahead")
        out = dt.compare("art", "a.txt", b"other", live_mtime=0.0)
        self.assertEqual(out.status, "unrecorded")
        self.assertTrue(out.drifted)

    def test_push_names_the_object_and_reads_origin_back(self):
        name = self.tag(1, push=True)
        self.assertTrue(dt.remote_has(name, str(self.root)))

    def test_a_pruned_local_tag_still_reaches_origin(self):
        real = dt._resolve_tag
        calls = []

        def fake(name, repo_root):
            out = real(name, repo_root)
            if not calls:
                calls.append(1)
                git(self.root, "tag", "-d", name)
            return out
        # not-a-gate: fault injection (prunes the local tag between two reads)
        with mock.patch.object(dt, "_resolve_tag", fake), \
                contextlib.redirect_stdout(io.StringIO()):
            name = self.tag(1, push=True)
        self.assertTrue(dt.remote_has(name, str(self.root)))
        self.assertEqual(dt.latest("art"), name)

    def test_gone_locally_message_carries_both_repos_wording(self):
        ok, msg = dt.push_tag("deploy/art/2000-01-01")
        self.assertFalse(ok)
        self.assertIn("GONE LOCALLY TOO", msg)
        self.assertIn("does not exist locally", msg)
        self.assertNotIn("LOCALLY ONLY", msg)

    def test_git_dir_in_the_environment_does_not_redirect_git(self):
        other = self.tmp / "other"
        other.mkdir()
        git(other, "init", "-q")
        # not-a-gate: an input (a hook-style leaked GIT_DIR)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            name = self.tag(1)
        self.assertIn(name, git(self.root, "tag", "-l"))
        self.assertEqual(git(other, "tag", "-l"), "")

    def test_cli_create_exit_3_unless_origin_holds_it_and_the_setting(self):
        git(self.root, "remote", "remove", "origin")
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(dt.main(["create", "--artefact", "art"]), 3)
            self.commit("v2")
            # not-a-gate: the setting under test, relaxed as crm relaxes it
            with mock.patch.object(dt, "CLI_CREATE_REQUIRES_ORIGIN", False):
                self.assertEqual(dt.main(["create", "--artefact", "art"]), 0)

    def test_cli_compare_unreadable_live_file_is_refused(self):
        self.tag(1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = dt.main(["compare", "--artefact", "art", "--path", "a.txt",
                          "--live-file", str(self.tmp / "missing")])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", out.getvalue())

    def test_recorded_hash_reads_the_tools_note_line(self):
        name = self.tag(1, note="sha256:" + "a" * 64)
        self.assertEqual(dt.recorded_hash(name), "a" * 64)
        self.assertEqual(dt.recorded_content(name), (None, None))


if __name__ == "__main__":
    unittest.main()
