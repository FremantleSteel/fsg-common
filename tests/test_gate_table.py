"""crm#2815 item 7: the gate table, moved from crm. Absent input is exit 2, never a pass."""
from __future__ import annotations

import json

import pytest

from fsg_common import gate_table as g


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts" / "check_a.py").write_text("")
    (tmp_path / "scripts" / "check_b.py").write_text("")
    (tmp_path / ".github" / "workflows" / "x.yml").write_text("run: python scripts/check_a.py\n")
    (tmp_path / "scripts" / "gates_by_hand.json").write_text(
        json.dumps({"_about": "x",
                    "check_b.py": "By hand before a release; it reads a share no runner can reach."}))
    return tmp_path


def run(repo, *extra):
    return g.main(["--root", str(repo), *extra])


def test_write_then_check_is_clean(repo, capsys):
    assert run(repo) == 0
    table = (repo / "docs" / "gate-table.md").read_text()
    assert "| `check_a.py` | CI: x.yml |" in table and "BY HAND" in table
    assert run(repo, "--check") == 0


def test_unwired_unlisted_script_is_a_finding(repo, capsys):
    (repo / "scripts" / "check_c.py").write_text("")
    assert run(repo) == 1  # write mode reports it too
    assert run(repo, "--check") == 1
    assert "check_c.py is wired to no workflow" in capsys.readouterr().out


def test_stale_by_hand_and_missing_entries(repo, capsys):
    (repo / ".github" / "workflows" / "y.yml").write_text("check_b.py\n")
    (repo / "scripts" / "gates_by_hand.json").write_text(json.dumps({
        "check_b.py": "x" * 40, "check_gone.py": "x" * 40}))
    assert run(repo, "--check") == 1
    out = capsys.readouterr().out
    assert "remove the stale entry" in out and "check_gone.py, which does not exist" in out


def test_stale_table(repo):
    run(repo)
    (repo / "docs" / "gate-table.md").write_text("old\n")
    assert run(repo, "--check") == 1


def test_missing_by_hand_file_is_2_not_pass(repo, capsys):
    (repo / "scripts" / "gates_by_hand.json").unlink()
    assert run(repo, "--check") == 2
    assert "REFUSED" in capsys.readouterr().out


def test_missing_scripts_dir_is_2(tmp_path):
    assert g.main(["--root", str(tmp_path), "--check"]) == 2


def test_by_hand_not_an_object_is_2(repo):
    (repo / "scripts" / "gates_by_hand.json").write_text("[]")
    assert run(repo, "--check") == 2


def test_monitor_module_wires_a_script(repo):
    (repo / "scripts" / "mon_list_t.py").write_text(
        "MONITORS = [{'argv': ['python', 'check_b.py']}]\n")
    (repo / "scripts" / "gates_by_hand.json").write_text("{}")
    assert run(repo, "--check", "--timers-module", "mon_list_t") == 1  # table not written yet
    assert run(repo, "--timers-module", "mon_list_t") == 0
    assert "monitor timer" in (repo / "docs" / "gate-table.md").read_text()


def test_bad_monitor_module_is_2(repo):
    assert run(repo, "--check", "--timers-module", "no_such_mod_xyz") == 2
