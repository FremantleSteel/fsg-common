"""crm#1964: fast-forward only, refuse everything else, on throwaway repos only."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fsg_common import sync_main_clones as s


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "core.autocrlf=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Clones(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = self.tmp / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        (self.origin / "a.txt").write_text("1\n", encoding="utf-8")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-qm", "one")
        self.root = self.tmp / "clones"
        self.root.mkdir()
        self.clone = self.root / "fsg-common"
        git(self.root, "clone", "-q", str(self.origin), str(self.clone))

    def advance_origin(self):
        (self.origin / "a.txt").write_text("2\n", encoding="utf-8")
        git(self.origin, "commit", "-qam", "two")
        return git(self.origin, "rev-parse", "HEAD")

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def test_current_clone_is_current(self):
        self.assertEqual(s.sync_one(self.clone, check=False)[0], "CURRENT")

    def test_behind_clone_is_fast_forwarded(self):
        new = self.advance_origin()
        state, detail = s.sync_one(self.clone, check=False)
        self.assertEqual(state, "UPDATED", detail)
        self.assertEqual(self.head(), new)

    def test_check_reports_behind_and_changes_nothing(self):
        before = self.head()
        self.advance_origin()
        self.assertEqual(s.sync_one(self.clone, check=True)[0], "BEHIND")
        self.assertEqual(self.head(), before)

    def test_dirty_tree_is_refused_and_left_alone(self):
        before = self.head()
        self.advance_origin()
        (self.clone / "a.txt").write_text("local edit\n", encoding="utf-8")
        state, detail = s.sync_one(self.clone, check=False)
        self.assertEqual(state, "REFUSED")
        self.assertIn("tracked", detail)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.clone / "a.txt").read_text(encoding="utf-8"), "local edit\n")
        self.assertEqual(git(self.clone, "stash", "list"), "")  # never stashed

    def test_other_branch_is_refused(self):
        self.advance_origin()
        git(self.clone, "checkout", "-q", "-b", "feature")
        state, detail = s.sync_one(self.clone, check=False)
        self.assertEqual((state, "feature" in detail), ("REFUSED", True))

    def test_diverged_main_is_refused_not_reset(self):
        self.advance_origin()
        (self.clone / "b.txt").write_text("mine\n", encoding="utf-8")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-qm", "local")
        mine = self.head()
        state, detail = s.sync_one(self.clone, check=False)
        self.assertEqual(state, "REFUSED")
        self.assertIn("diverged", detail)
        self.assertEqual(self.head(), mine)

    def test_untracked_file_is_left_alone(self):
        new = self.advance_origin()
        (self.clone / "notes.txt").write_text("keep\n", encoding="utf-8")
        self.assertEqual(s.sync_one(self.clone, check=False)[0], "UPDATED")
        self.assertEqual(self.head(), new)
        self.assertTrue((self.clone / "notes.txt").exists())

    def test_unreachable_origin_is_not_established(self):
        git(self.clone, "remote", "set-url", "origin", str(self.tmp / "gone"))
        self.assertEqual(s.sync_one(self.clone, check=False)[0], "NOT ESTABLISHED")

    def test_absent_clone_is_absent(self):
        self.assertEqual(s.sync_one(self.root / "nope", check=False)[0], "ABSENT")

    def test_main_exit_codes(self):
        self.assertEqual(s.main(["--root", str(self.root), "--repo", "fsg-common"]), 0)
        self.advance_origin()
        self.assertEqual(
            s.main(["--root", str(self.root), "--repo", "fsg-common", "--check"]), 1)
        git(self.clone, "remote", "set-url", "origin", str(self.tmp / "gone"))
        self.assertEqual(s.main(["--root", str(self.root), "--repo", "fsg-common"]), 2)

    def test_default_root_from_a_worktree_is_the_main_clones_folder(self):
        wt = self.tmp / "elsewhere" / "wt"
        git(self.clone, "worktree", "add", "-q", "-b", "x", str(wt))
        self.assertEqual(s.default_root(wt).resolve(), self.root.resolve())


if __name__ == "__main__":
    unittest.main()
