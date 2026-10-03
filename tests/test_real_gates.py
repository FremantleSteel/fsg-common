"""The real gate, run for real, behind every stub that replaces it.

Each test here is cited by a `# real-gate test: <name>` comment beside a stub
(guarded by `test_gate_stub_citations.py`). Each refusal has a control that
clears, so a gate disabled to "always refuse" or "never refuse" fails one.

Only transport is faked: `urllib.request.urlopen`, a `gh` runner, a git
subprocess. The decision that turns a bad response into REFUSED is real code.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import urllib.error
import urllib.request
from types import SimpleNamespace as R
from unittest import mock

import pytest

from fsg_common import merge_on_green as m
from fsg_common import reading_path as rp


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


@pytest.fixture(autouse=True)
def _no_sleep():
    # not-a-gate: the retry back-off is wall-clock time, not a decision
    with mock.patch.object(rp.time, "sleep", lambda s: None):
        yield


# --- reading_path: an unreadable API response is REFUSED, never a count -----

@pytest.mark.parametrize("code", [401, 403, 404, 500])
def test_read_via_api_http_error_is_unavailable(code):
    with mock.patch.object(urllib.request, "urlopen", side_effect=_http(code)):
        with pytest.raises(rp.Unavailable) as e:
            rp.read_via_api("fsg-estimating-crm", "CLAUDE.md", "tok")
    assert str(code) in str(e.value)


def test_read_via_api_unreachable_is_unavailable():
    with mock.patch.object(urllib.request, "urlopen",
                           side_effect=urllib.error.URLError("down")):
        with pytest.raises(rp.Unavailable):
            rp.read_via_api("r", "CLAUDE.md", "tok")


def test_read_via_api_control_returns_the_text():
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_Resp(b"one two three")):
        assert rp.read_via_api("r", "CLAUDE.md", "tok") == "one two three"


def test_a_transient_5xx_is_retried_once_but_a_404_is_not():
    calls = []

    def flaky(req, timeout=0):
        calls.append(1)
        if len(calls) == 1:
            raise _http(503)
        return _Resp(b"a b")

    with mock.patch.object(urllib.request, "urlopen", side_effect=flaky):
        assert rp.read_via_api("r", "CLAUDE.md", "tok") == "a b"
    assert len(calls) == 2
    calls.clear()

    def not_found(req, timeout=0):
        calls.append(1)
        raise _http(404)

    with mock.patch.object(urllib.request, "urlopen", side_effect=not_found):
        with pytest.raises(rp.Unavailable):
            rp.read_via_api("r", "CLAUDE.md", "tok")
    assert len(calls) == 1


def _main_with_api(side_effect_or_return, tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("w " * 10, encoding="utf-8")
    env = {"FSG_COMMON_PAT": "tok"}
    patch = (mock.patch.object(urllib.request, "urlopen", side_effect=side_effect_or_return)
             if callable(side_effect_or_return) or isinstance(side_effect_or_return, Exception)
             else mock.patch.object(urllib.request, "urlopen", return_value=side_effect_or_return))
    with mock.patch.dict(os.environ, env), patch:
        code = rp.main("fsg-common", [], repo_root=str(tmp_path))
    return code, capsys.readouterr().out


def test_main_refuses_when_the_api_answers_404(tmp_path, capsys):
    code, out = _main_with_api(_http(404), tmp_path, capsys)
    assert code == 2
    assert "REFUSED" in out and "not a pass" in out


def test_main_control_clears_when_the_api_answers(tmp_path, capsys):
    def answer(req, timeout=0):
        return _Resp(b"w " * 10)
    code, out = _main_with_api(answer, tmp_path, capsys)
    assert code == 0, out
    assert "TOTAL" in out


# --- merge_on_green: an unreadable gh answer never merges -------------------

def _view(**kw):
    d = {"number": 5, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE",
         "body": "Closes #5\n\nShort.", "comments": [], "headRefName": "feat-x",
         "baseRefName": "main",
         "statusCheckRollup": [{"name": "ci", "status": "COMPLETED",
                                "conclusion": "SUCCESS", "startedAt": "2026-10-01T00:00:00Z"}]}
    d.update(kw)
    return d


def _go(gh):
    lines = []
    ticks = iter(range(0, 100000, 30))
    rc = m.main(["5", "-R", "FremantleSteel/fsg-common", "--timeout", "100"],
                gh=gh, git=lambda c: R(rc=0, out="", err=""),
                sleep=lambda s: None, clock=lambda: next(ticks), out=lines.append)
    return rc, " ".join(lines)


def test_merge_refuses_when_gh_cannot_read_the_pr():
    merged = []

    def gh(cmd):
        if cmd[2] == "merge":
            merged.append(1)
        return R(rc=1, out="", err="HTTP 502")

    rc, text = _go(gh)
    assert rc == m.REFUSED and "cannot read the PR" in text and not merged


def test_merge_refuses_when_the_merge_did_not_complete():
    def gh(cmd):
        if cmd[2] == "merge":
            return R(rc=1, out="", err="blocked by branch protection")
        if cmd[-1] == "state":
            return R(rc=0, out=json.dumps({"state": "OPEN"}), err="")
        return R(rc=0, out=json.dumps(_view()), err="")

    rc, text = _go(gh)
    assert rc == m.REFUSED and "did not complete" in text


def test_merge_refuses_when_the_state_read_after_merge_fails():
    def gh(cmd):
        if cmd[2] == "merge":
            return R(rc=0, out="", err="")
        if cmd[-1] == "state":
            return R(rc=1, out="", err="boom")
        return R(rc=0, out=json.dumps(_view()), err="")

    rc, text = _go(gh)
    assert rc == m.REFUSED and "UNKNOWN" in text


def test_merge_control_merges_when_everything_is_readable():
    merged = []

    def gh(cmd):
        if cmd[2] == "merge":
            merged.append(1)
            return R(rc=0, out="", err="")
        if cmd[-1] == "state":
            return R(rc=0, out=json.dumps({"state": "MERGED" if merged else "OPEN"}), err="")
        return R(rc=0, out=json.dumps(_view()), err="")

    rc, text = _go(gh)
    assert rc == m.OK and merged and "MERGED #5" in text


# --- leak_guard: the real index read -----------------------------------------

def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True)


def _repo(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@t.com", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    return tmp_path


def test_real_staged_files_sees_a_blocked_file_and_a_clean_one(tmp_path, monkeypatch):
    from test_leak_guard import CONFIG

    from fsg_common import leak_guard
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ok.txt").write_text("fine\n", encoding="utf-8")
    _git("add", "ok.txt", cwd=tmp_path)
    assert leak_guard.run([], CONFIG) == 0                    # control: clears
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4")
    _git("add", "scan.pdf", cwd=tmp_path)
    assert leak_guard.run([], CONFIG) == 1                    # real gate refuses
