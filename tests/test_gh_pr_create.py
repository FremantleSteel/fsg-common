"""`fsg_common.gh_pr_create`, with gh faked: each refusal shown failing.

Ported from fsg-estimating-crm/tests/test_gh_pr_create.py (crm#1719).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fsg_common import gh_pr_create as g


class Fake:
    def __init__(self):
        self.calls, self.bodies = [], []

    def __call__(self, args):
        self.calls.append(args)
        self.bodies.append(Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8"))
        return 0


class GhPrCreate(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self._orig = g.run_gh
        # not-a-gate: transport (starts gh); pr_body.check runs for real and
        # the refusal tests assert gh was never called
        g.run_gh = self.fake
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        # not-a-gate: restores the transport stub above
        g.run_gh = self._orig
        self.tmp.cleanup()

    def body_file(self, text):
        p = Path(self.tmp.name) / "b.md"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_strips_attribution_and_passes_args_through(self):
        b = self.body_file("Closes #5\n\nDone.\n\n🤖 Generated with [Claude Code](x)\n"
                           "Co-Authored-By: X\n")
        rc = g.main(["-R", "o/r", "--body-file", b, "--title", "T", "--base", "main"])
        self.assertEqual(rc, 0)
        self.assertNotIn("Generated", self.fake.bodies[0])
        self.assertNotIn("Co-Authored", self.fake.bodies[0])
        self.assertIn("Closes #5", self.fake.bodies[0])
        a = self.fake.calls[0]
        self.assertEqual(a[:4], ["pr", "create", "-R", "o/r"])
        self.assertIn("--title", a)
        self.assertIn("--base", a)

    def test_body_arg_and_no_issue(self):
        self.assertEqual(g.main(["-R", "o/r", "--body", "No issue: docs only", "--title", "T"]), 0)

    def test_refuses_no_closing_keyword(self):
        self.assertEqual(g.main(["-R", "o/r", "--body", "Just words", "--title", "T"]), 1)
        self.assertEqual(self.fake.calls, [])

    def test_refuses_400_words(self):
        self.assertEqual(g.main(["-R", "o/r", "--body", "Closes #1 " + "w " * 400]), 1)
        self.assertEqual(self.fake.calls, [])

    def test_399_words_passes(self):
        self.assertEqual(g.main(["-R", "o/r", "--body", "Closes #1 " + "w " * 397]), 0)

    def test_requires_repo_and_one_body(self):
        self.assertEqual(g.main(["--body", "Closes #1"]), 2)
        self.assertEqual(g.main(["-R", "o/r"]), 2)
        self.assertEqual(g.main(["-R", "o/r", "--body-file", "/nonexistent/x"]), 2)
        self.assertEqual(self.fake.calls, [])


    def test_run_gh_can_be_injected(self):
        calls = []
        # not-a-gate: transport, the point of this test is the injection seam
        rc = g.main(["-R", "o/r", "--body", "Closes #1", "--title", "T"],
                    run_gh=lambda a: calls.append(a) or 0)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.fake.calls, [])

    def test_no_issue_heading_form_passes(self):
        self.assertEqual(g.main(["-R", "o/r", "--body", "## No issue:\nDocs only.\n"]), 0)

    def test_refuses_pull_url_as_close(self):
        body = "Closes https://github.com/FremantleSteel/fsg-common/pull/12"
        self.assertEqual(g.main(["-R", "o/r", "--body", body]), 1)
        self.assertEqual(self.fake.calls, [])

    def test_refuses_shorthand_close(self):
        self.assertEqual(g.main(["-R", "o/r", "--body", "Closes crm#1719"]), 1)
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
