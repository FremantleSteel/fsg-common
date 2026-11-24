"""The one exit-code rule (crm#2815 item 6)."""
from __future__ import annotations

import io

from fsg_common.refused import Refused, exit_code, run_check


def _run(fn):
    buf = io.StringIO()
    return run_check(fn, out=buf), buf.getvalue()


def test_empty_is_pass():
    assert _run(lambda: []) == (0, "PASS\n")


def test_finding_is_one_and_listed():
    code, text = _run(lambda: ["a is stale"])
    assert code == 1 and "FINDING: a is stale" in text


def test_refused_is_two_not_one():
    def check():
        raise Refused("no heartbeat file")

    code, text = _run(check)
    assert code == 2 and text == "REFUSED: no heartbeat file\n"


def test_missing_file_is_two():
    def check():
        open("/no/such/file.txt").close()

    assert _run(check)[0] == 2


def test_no_list_is_two_not_pass():
    assert exit_code(None) == 2
    assert _run(lambda: None)[0] == 2


def test_other_errors_propagate():
    import pytest

    def check():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        _run(check)
