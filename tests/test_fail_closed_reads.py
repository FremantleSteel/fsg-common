"""Three reads that answered "nothing" when they had read nothing (fsg-common#55).

Each fails on main and has a control that still answers when the input is there.
"""
from __future__ import annotations

import io
import json
import subprocess
import urllib.request
from types import SimpleNamespace as R
from unittest import mock

import pytest

from fsg_common import leak_guard
from fsg_common import merge_on_green as m
from fsg_common import reading_path as rp


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_an_empty_200_from_the_api_is_unreadable_not_zero_words():
    # not-a-gate: transport; measure() runs over the real read_via_api
    with mock.patch.object(urllib.request, "urlopen", return_value=_Resp(b"")):
        with pytest.raises(rp.Unavailable, match="empty"):
            rp.measure(lambda repo, path: rp.read_via_api(repo, path, "t"),
                       files=(("r", "CLAUDE.md"),))


def test_a_nonempty_200_still_counts():
    # not-a-gate: transport; the control for the test above
    with mock.patch.object(urllib.request, "urlopen", return_value=_Resp(b"a b c")):
        got = rp.measure(lambda repo, path: rp.read_via_api(repo, path, "t"),
                         files=(("r", "CLAUDE.md"),))
    assert got == {("r", "CLAUDE.md"): 3}


def test_an_unreadable_index_refuses_instead_of_reporting_nothing_staged(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)                    # not a git repo: git diff fails
    cfg = leak_guard.GuardConfig(repo_holds="r", client_data_lives="c")
    assert leak_guard.run([], cfg) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_a_readable_empty_index_is_still_the_pass_it_always_was(
        tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    cfg = leak_guard.GuardConfig(repo_holds="r", client_data_lives="c")
    assert leak_guard.run([], cfg) == 0
    assert "nothing to check" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "not json", "{}", "null", '{"state": "OPEN"}'])
def test_an_unparseable_pr_answer_refuses_cleanly_and_never_merges(answer):
    calls, lines = [], []
    ticks = iter(range(0, 10000, 30))

    def gh(cmd):
        calls.append(cmd[2])
        return R(rc=0, out=answer, err="")

    rc = m.main(["5", "-R", "o/r", "--timeout", "100"], gh=gh,
                git=lambda c: R(rc=0, out="", err=""), sleep=lambda s: None,
                clock=lambda: next(ticks), out=lines.append)
    assert rc == m.REFUSED and "merge" not in calls
    assert "could not be parsed" in " ".join(lines)


def test_a_wellformed_pr_answer_still_proceeds_past_the_parse():
    lines = []
    ticks = iter(range(0, 10000, 30))
    view = {"number": 5, "state": "CLOSED", "isDraft": False, "mergeable": "MERGEABLE"}
    rc = m.main(["5", "-R", "o/r"], gh=lambda c: R(rc=0, out=json.dumps(view), err=""),
                git=lambda c: R(rc=0, out="", err=""), sleep=lambda s: None,
                clock=lambda: next(ticks), out=lines.append)
    assert rc == m.REFUSED and "is CLOSED, not OPEN" in " ".join(lines)
