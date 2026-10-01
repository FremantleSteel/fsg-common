"""`fsg_common.merge_commands_index`: the union, the real conflict, the absent input."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fsg_common import merge_commands_index as m


def run(base, ours, theirs):
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, doc in (("b", base), ("o", ours), ("t", theirs)):
            p = Path(d) / name
            p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
            paths.append(str(p))
        rc = m.main(paths)
        return rc, (Path(paths[1]).read_text(encoding="utf-8"))


BASE = {"groups": [], "assign": {"a.py": "x"}, "aliases": {}}


class Union(unittest.TestCase):
    def test_two_new_keys_merge_with_no_conflict(self):
        o = {**BASE, "assign": {"a.py": "x", "b.py": "y"}}
        t = {**BASE, "assign": {"a.py": "x", "c.py": "z"}}
        rc, text = run(BASE, o, t)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(text)["assign"], {"a.py": "x", "b.py": "y", "c.py": "z"})

    def test_one_side_changed_takes_that_side(self):
        t = {**BASE, "assign": {"a.py": "new"}}
        rc, text = run(BASE, BASE, t)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(text)["assign"], {"a.py": "new"})


class Refusals(unittest.TestCase):
    def test_same_key_different_values_is_a_marked_conflict(self):
        o = {**BASE, "assign": {"a.py": "ours"}}
        t = {**BASE, "assign": {"a.py": "theirs"}}
        rc, text = run(BASE, o, t)
        self.assertEqual(rc, 1)
        self.assertIn("<<<<<<<", text)
        self.assertIn(">>>>>>>", text)

    def test_invalid_json_side_refuses_and_leaves_ours_untouched(self):
        rc, text = run(BASE, "not json {", BASE)
        self.assertEqual(rc, 1)
        self.assertEqual(text, "not json {")

    def test_too_few_arguments_refuses(self):
        self.assertEqual(m.main(["only-one"]), 2)


if __name__ == "__main__":
    unittest.main()
