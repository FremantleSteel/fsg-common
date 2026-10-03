"""crm#1798: two pull requests that each add a command never block each other.

GitHub's merge button does a plain text merge: no custom merge driver, and --
measured on 3 Oct 2026 with the merges API -- not `merge=union` either. These
tests merge two branches the same way (a throwaway repo with no
`.gitattributes` and no driver registered), in both orders, and require the
result to merge with no conflict AND to pass `--check` with no regenerate.

The controls prove the test can fail: filing the same two commands in the
sidecar (the old way) conflicts; two commands that sort next to each other in
one table conflict rather than merging stale; and an unfiled command on the
merged tree still fails `--check`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fsg_common import gen_commands_index as g

WRAPPER = (
    "from fsg_common.gen_commands_index import main\n"
    "raise SystemExit(main(script=__file__))\n"
)
SIDE = {
    "repo": "demo", "package": None, "cli_prefix": None,
    "groups": [{"id": "read", "title": "Read things", "blurb": "b"},
               {"id": "write", "title": "Write things", "blurb": "b"}],
    "assign": {"gen_commands_index.py": "read", "check_m.py": "read",
               "check_t.py": "read", "fix_m.py": "write"},
    "aliases": {"see the index": "python scripts/gen_commands_index.py"},
}
ENV = {**os.environ, "PYTHONPATH": str(Path(g.__file__).parent.parent),
       "GIT_CONFIG_NOSYSTEM": "1"}


def script(doc: str, *markers: str) -> str:
    lines = [f'"""{doc}"""', *markers, 'if __name__ == "__main__":', "    pass", ""]
    return "\n".join(lines)


class TwoPullRequests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "demo"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts" / "gen_commands_index.py").write_text(WRAPPER, "utf-8")
        for name in ("check_m.py", "check_t.py", "fix_m.py"):
            (self.root / "scripts" / name).write_text(script(f"Do {name}."), "utf-8")
        self.write_side(SIDE)
        self.git("init", "-q", "-b", "main")
        # No attributes from anywhere: GitHub's merge honours none of ours.
        self.git("config", "core.attributesFile", os.devnull)
        self.regenerate()
        self.commit("base")

    # ------------------------------------------------------------ plumbing

    def git(self, *args, check=True):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "core.autocrlf=false", *args],
            cwd=self.root, capture_output=True, text=True, check=check, env=ENV)

    def gen(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/gen_commands_index.py", *args],
            cwd=self.root, capture_output=True, text=True, env=ENV)

    def regenerate(self):
        self.git("add", "-A")
        done = self.gen()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def write_side(self, side):
        (self.root / "scripts" / "commands_index.json").write_text(
            json.dumps(side, indent=2) + "\n", "utf-8")

    def side(self):
        return json.loads(
            (self.root / "scripts" / "commands_index.json").read_text("utf-8"))

    def branch(self, name, files, sidecar_assign=None, must_pass=True):
        """One pull request: new files, optionally old-style sidecar filing."""
        self.git("checkout", "-q", "-b", name, "main")
        for rel, text in files.items():
            (self.root / rel).write_text(text, "utf-8")
        if sidecar_assign:
            side = self.side()
            side["assign"].update(sidecar_assign)  # appended at the tail
            self.write_side(side)
        self.regenerate()
        if must_pass:
            check = self.gen("--check")
            self.assertEqual(check.returncode, 0, check.stdout)
        self.commit(name)
        self.git("checkout", "-q", "main")

    def merge_both(self, first, second):
        """Merge `first`, then `second`, into a fresh copy of main."""
        self.git("checkout", "-q", "-b", f"main-{first}-{second}", "main")
        one = self.git("merge", "--no-ff", "--no-edit", first, check=False)
        self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
        return self.git("merge", "--no-ff", "--no-edit", second, check=False)

    def both_orders(self):
        return (("pr-a", "pr-b"), ("pr-b", "pr-a"))

    # ------------------------------------------------------------- the cases

    def test_two_new_commands_merge_clean_and_current_in_both_orders(self):
        self.branch("pr-a", {"scripts/apply_a.py": script(
            "Apply A.", "# commands-index-group: write",
            "# commands-index-task: apply the A decision")})
        self.branch("pr-b", {"scripts/report_b.py": script(
            "Report B.", "# commands-index-group: read",
            "# commands-index-task: what does B hold")})
        for first, second in self.both_orders():
            with self.subTest(order=f"{first} then {second}"):
                merged = self.merge_both(first, second)
                self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
                check = self.gen("--check")
                self.assertEqual(check.returncode, 0, check.stdout)
                doc = (self.root / "docs" / "COMMANDS.md").read_text("utf-8")
                self.assertIn("apply the A decision", doc)
                self.assertIn("what does B hold", doc)
                self.git("checkout", "-q", "main")

    def test_two_new_commands_in_one_group_merge_clean(self):
        self.branch("pr-a", {"scripts/check_a.py": script(
            "Check A.", "# commands-index-group: read")})
        self.branch("pr-b", {"scripts/check_z.py": script(
            "Check Z.", "# commands-index-group: read")})
        for first, second in self.both_orders():
            with self.subTest(order=f"{first} then {second}"):
                merged = self.merge_both(first, second)
                self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
                check = self.gen("--check")
                self.assertEqual(check.returncode, 0, check.stdout)
                self.git("checkout", "-q", "main")

    def test_control_filing_in_the_sidecar_still_conflicts(self):
        # The old way: both append to the tail of `assign`. Proves this file
        # can see a conflict, so the clean merges above are evidence.
        self.branch("pr-a", {"scripts/apply_a.py": script("Apply A.")},
                    sidecar_assign={"apply_a.py": "write"})
        self.branch("pr-b", {"scripts/report_b.py": script("Report B.")},
                    sidecar_assign={"report_b.py": "read"})
        merged = self.merge_both("pr-a", "pr-b")
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn("commands_index.json", merged.stdout)

    def test_control_adjacent_rows_conflict_rather_than_merge_stale(self):
        # check_m.py and check_t.py are neighbours, and both new rows land
        # between them. Git must refuse, never write a page in the wrong order.
        self.branch("pr-a", {"scripts/check_n.py": script(
            "Check N.", "# commands-index-group: read")})
        self.branch("pr-b", {"scripts/check_p.py": script(
            "Check P.", "# commands-index-group: read")})
        merged = self.merge_both("pr-a", "pr-b")
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn("COMMANDS.md", merged.stdout)

    def test_control_unfiled_command_on_the_merged_tree_still_fails(self):
        self.branch("pr-a", {"scripts/apply_a.py": script(
            "Apply A.", "# commands-index-group: write")})
        self.branch("pr-b", {"scripts/report_b.py": script("Report B.")},
                    must_pass=False)  # unfiled: its own --check is red
        merged = self.merge_both("pr-a", "pr-b")
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        check = self.gen("--check")
        self.assertEqual(check.returncode, 1, check.stdout)
        self.assertIn("unfiled", check.stdout)


class Filing(unittest.TestCase):
    """The marker reader on its own: what files a command, and what is refused."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text, "utf-8")
        return path

    def own(self, path):
        return g.parse_markers(list(g.comment_lines(path).values()))

    def test_docstring_describing_the_syntax_is_not_a_filing(self):
        path = self.write("x.py", '"""Doc.\n\n# commands-index-group: read\n"""\n')
        self.assertEqual(self.own(path), {"groups": [], "tasks": []})

    def test_comment_files_and_task_maps(self):
        path = self.write("x.py", '"""Doc."""\n# commands-index-group: read\n'
                          "# commands-index-task: find x => python scripts/x.py --y\n"
                          "# commands-index-task: plain x\n")
        own = self.own(path)
        self.assertEqual(own["groups"], ["read"])
        self.assertEqual(own["tasks"], [("find x", "python scripts/x.py --y"),
                                        ("plain x", None)])

    def test_ps1_comment_files(self):
        path = self.write("x.ps1", "# Does x.\n# commands-index-group: write\n")
        self.assertEqual(self.own(path)["groups"], ["write"])

    def test_cli_subcommand_is_filed_by_the_block_directly_above_it(self):
        path = self.write("cli.py", (
            "import argparse\n"
            "sub = argparse.ArgumentParser().add_subparsers()\n"
            "# commands-index-group: read\n"
            "# commands-index-task: look at alpha\n"
            'sub.add_parser("alpha", help="a")\n'
            "\n"
            'sub.add_parser("beta", help="b")\n'))
        calls = {c["name"]: c["own"] for c in g.add_parser_calls(path)}
        self.assertEqual(calls["alpha"]["groups"], ["read"])
        self.assertEqual(calls["alpha"]["tasks"], [("look at alpha", None)])
        self.assertEqual(calls["beta"]["groups"], [])

    def entry(self, groups, source="scripts/x.py", tasks=()):
        return {"key": source.rsplit("/", 1)[-1], "run": f"python {source}",
                "source": source, "own": {"groups": groups, "tasks": list(tasks)}}

    def test_disagreement_unknown_group_and_double_group_are_problems(self):
        side = {"groups": [{"id": "read"}, {"id": "write"}],
                "assign": {"x.py": "read"}}
        self.assertEqual(g.filing_problems([self.entry(["read"])], side), [])
        self.assertTrue(g.filing_problems([self.entry(["write"])], side))
        self.assertTrue(g.filing_problems(
            [self.entry(["nope"], source="scripts/y.py")], side))
        self.assertTrue(g.filing_problems(
            [self.entry(["read", "write"], source="scripts/y.py")], side))

    def test_task_phrase_claimed_twice_is_a_problem(self):
        side = {"aliases": {"do x": "python scripts/other.py"}}
        _, problems = g.merged_aliases([self.entry([], tasks=[("do x", None)])], side)
        self.assertTrue(problems)
        aliases, problems = g.merged_aliases(
            [self.entry([], tasks=[("do y", None)])], side)
        self.assertEqual(problems, [])
        self.assertEqual(aliases["do y"], "python scripts/x.py")


if __name__ == "__main__":
    unittest.main()
