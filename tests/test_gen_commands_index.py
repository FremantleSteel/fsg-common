"""`fsg_common.gen_commands_index` on a throwaway repo: the generator, the gate, the control."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fsg_common import gen_commands_index as g

CLI = '''"""cli."""
import argparse
p = argparse.ArgumentParser()
subparsers = p.add_subparsers()
subparsers.add_parser("alpha", help="does alpha")
'''
TOOL = '"""Do the thing.\n\nMore."""\n'
WRAPPER = (
    "import sys\n"
    "from fsg_common.gen_commands_index import main\n"
    "raise SystemExit(main(script=__file__))\n"
)


def make_repo(root: Path, sidecar: dict | None = None) -> Path:
    (root / "scripts").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "cli.py").write_text(CLI, encoding="utf-8")
    (root / "scripts" / "tool.py").write_text(TOOL, encoding="utf-8")
    (root / "scripts" / "gen_commands_index.py").write_text(WRAPPER, encoding="utf-8")
    side = sidecar or {
        "repo": "demo", "package": "pkg", "cli_prefix": "python -m pkg",
        "groups": [{"id": "g", "title": "G", "blurb": "b"}],
        "assign": {"tool.py": "g", "alpha": "g", "gen_commands_index.py": "g"},
    }
    (root / "scripts" / "commands_index.json").write_text(json.dumps(side), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-qm", "x"], cwd=root, check=True)
    return root / "scripts" / "gen_commands_index.py"


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.script = make_repo(self.tmp / "demo")
        self.root = self.script.parent.parent

    def run_main(self, *argv):
        return g.main(list(argv), script=self.script)

    def test_missing_doc_refuses_then_generate_then_pass(self):
        self.assertEqual(self.run_main("--check"), 1)  # absent input must not pass
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.run_main("--check"), 0)

    def test_citation_is_a_file_never_a_line(self):
        self.run_main()
        doc = (self.root / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        self.assertIn("pkg/cli.py", doc)
        self.assertNotIn("cli.py:", doc)

    def test_stale_report_names_the_missing_command(self):
        self.run_main()
        (self.root / "pkg" / "cli.py").write_text(
            CLI + 'subparsers.add_parser("beta", help="b")\n', encoding="utf-8")
        have = (self.root / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        want, _, _ = g.build()
        report = g.stale_report(have, want)
        self.assertTrue(any("missing a command" in r and "beta" in r for r in report))

    def test_new_unfiled_command_fails_check(self):
        self.run_main()
        (self.root / "scripts" / "extra.py").write_text(TOOL, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        self.assertEqual(self.run_main("--check"), 1)

    def test_configure_is_per_call(self):
        # a second checkout must not inherit the first one's paths
        other = make_repo(self.tmp / "other")
        g.main(["--stdout"], script=other)
        self.assertEqual(g.ROOT, other.parent.parent.resolve())

    def test_selftest_injects_on_a_non_sub_variable(self):
        # the parser variable here is `subparsers`, not `sub`
        proc = subprocess.run(
            [sys.executable, str(self.script), "--selftest"],
            capture_output=True, text=True, cwd=self.root,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(Path(g.__file__).parent.parent)})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
