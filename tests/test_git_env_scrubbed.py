"""FremantleSteel/fsg-estimating-crm#1981: the pytest process carries no GIT_*,
so a test's git child cannot be redirected to a real repo by a hook's GIT_DIR."""
from __future__ import annotations

import os
import subprocess


def _clean():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def test_the_pytest_process_carries_no_git_variables():
    assert [k for k in os.environ if k.startswith("GIT_")] == []


def _decoy(tmp_path):
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=decoy, check=True, capture_output=True,
                   env=_clean())
    return decoy, (decoy / ".git" / "config").read_bytes()


def test_a_git_child_with_a_clean_env_leaves_a_decoy_untouched(tmp_path, monkeypatch):
    decoy, before = _decoy(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    env = _clean()
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "-C", str(target), "config", "user.name", "x"], check=True,
                   capture_output=True, env=env)
    assert (decoy / ".git" / "config").read_bytes() == before


def test_control_an_inherited_git_dir_reaches_the_decoy(tmp_path):
    decoy, _ = _decoy(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    env = {**_clean(), "GIT_DIR": str(decoy / ".git")}
    subprocess.run(["git", "-C", str(target), "config", "user.name", "leaked"], check=True,
                   capture_output=True, env=env)
    assert b"leaked" in (decoy / ".git" / "config").read_bytes()
