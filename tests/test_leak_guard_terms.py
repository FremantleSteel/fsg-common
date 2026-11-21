"""The client term list and masked output in `fsg_common.leak_guard.run()`
(crm#3698, moved from fsg-estimating-crm PR 3697).

A config with `require_term_list=True` refuses with no list, unless
`--terms-optional` is given, and then says names were NOT checked. A list
that is named but missing, empty or unreadable refuses in every mode. A
match never prints the term. Every email and phone value printed is masked.

Every term, name, email and number here is made up.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from fsg_common import leak_guard

TERM = "Zorbex Pty Ltd"
EMAIL = "quill.more@zorbex-fixture.test"
MOBILE = "0400 000 017"

STRICT = leak_guard.GuardConfig(
    repo_holds="Test repo.", client_data_lives="Elsewhere.",
    enable_pii=True, enable_near_misses=True, require_term_list=True)
LOOSE = leak_guard.GuardConfig(repo_holds="Test repo.", client_data_lives="Elsewhere.",
                               enable_pii=True)


def _run(argv, config=STRICT) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = leak_guard.run(argv, config)
    return code, out.getvalue() + err.getvalue()


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(leak_guard.TERMS_ENV, raising=False)


@pytest.fixture
def leaky(tmp_path) -> Path:
    f = tmp_path / "card.ps1"
    f.write_text(f"# client: {TERM.upper()}\nWrite-Host 'hello'\n", encoding="utf-8")
    return f


@pytest.fixture
def terms(tmp_path) -> Path:
    f = tmp_path / "terms.txt"
    f.write_text(f"# made-up list\n\n{TERM}\n", encoding="utf-8")
    return f


# --- the planted-term test: a made-up term blocks and is never printed -----

def test_planted_term_blocks_and_is_masked(terms, leaky):
    code, report = _run(["--terms", str(terms), "--files", str(leaky)])
    assert code == 1, report
    assert "client term (line 3 of the term list)" in report
    assert "zorbex" not in report.lower()


def test_planted_term_in_the_file_path_blocks(terms, tmp_path):
    d = tmp_path / "Zorbex Pty Ltd"
    d.mkdir()
    f = d / "notes.bin"
    f.write_bytes(b"\x00\x01\x02")
    code, report = _run(["--terms", str(terms), "--files", str(f)])
    assert code == 1, report
    assert "file path holds a client term (line 3 of the term list)" in report


def test_the_env_variable_loads_the_list(monkeypatch, terms, leaky):
    monkeypatch.setenv(leak_guard.TERMS_ENV, str(terms))
    assert _run(["--files", str(leaky)])[0] == 1


def test_a_given_list_is_checked_even_when_the_config_does_not_require_one(terms, leaky):
    assert _run(["--terms", str(terms), "--files", str(leaky)], LOOSE)[0] == 1


def test_a_clean_file_passes_and_says_names_were_checked(terms, tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("nothing to see\n", encoding="utf-8")
    code, report = _run(["--terms", str(terms), "--files", str(f)])
    assert code == 0, report
    assert "client names checked against 1 term(s)" in report


# --- an absent list is "nothing was checked", never "ok" ------------------

@pytest.mark.parametrize("mode", [["--files"], ["--all"], []])
def test_no_list_refuses_in_every_mode(leaky, mode):
    argv = mode + ([str(leaky)] if mode == ["--files"] else [])
    code, report = _run(argv)
    assert code == 2, report
    assert leak_guard.NOT_LOADED in report
    assert "ok --" not in report


def test_retired_exclusion_variable_is_not_read(monkeypatch, terms, leaky):
    monkeypatch.setenv("FSG_EXCLUSIONS", str(terms))
    code, report = _run(["--files", str(leaky)])
    assert code == 2 and leak_guard.NOT_LOADED in report


def test_a_config_without_the_flag_never_reads_the_variable(monkeypatch, tmp_path):
    """fsg-common's own script keeps the terms themselves in that name."""
    monkeypatch.setenv(leak_guard.TERMS_ENV, "Quillmore\nZorbex")
    f = tmp_path / "clean.md"
    f.write_text("nothing to see\n", encoding="utf-8")
    assert _run(["--files", str(f)], LOOSE)[0] == 0


@pytest.mark.parametrize("content,needle", [
    (None, "does not exist"),
    ("# only a comment\n\n   \n", "holds no terms"),
    (b"\xff\xfe\x00bad", "could not be read"),
])
def test_a_named_but_unusable_list_refuses_even_when_optional(tmp_path, leaky, content, needle):
    f = tmp_path / "list.txt"
    if isinstance(content, bytes):
        f.write_bytes(content)
    elif content is not None:
        f.write_text(content, encoding="utf-8")
    code, report = _run(["--terms", str(f), "--terms-optional", "--files", str(leaky)])
    assert code == 2, report
    assert leak_guard.NOT_LOADED in report and needle in report


def test_a_directory_as_the_list_refuses(tmp_path, leaky):
    code, report = _run(["--terms", str(tmp_path), "--files", str(leaky)])
    assert code == 2 and leak_guard.NOT_LOADED in report


def test_optional_without_a_list_runs_the_other_checks_and_says_so(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("nothing to see\n", encoding="utf-8")
    code, report = _run(["--terms-optional", "--files", str(f)])
    assert code == 0
    assert "client names were NOT checked" in report
    g = tmp_path / "pii.md"
    g.write_text(f"Email: {EMAIL}\n", encoding="utf-8")
    assert _run(["--terms-optional", "--files", str(g)])[0] == 1


# --- emails and phone numbers are masked in the report --------------------

def test_email_and_phone_are_masked(terms, tmp_path):
    f = tmp_path / "pii.md"
    f.write_text(f"Email: {EMAIL}\nMobile: {MOBILE}\n", encoding="utf-8")
    code, report = _run(["--terms", str(terms), "--files", str(f)])
    assert code == 1, report
    assert "customer email address (q***@***.test)" in report
    assert "Australian phone number (**** *** *17)" in report
    assert EMAIL not in report and "quill" not in report
    assert MOBILE not in report


def test_masking_applies_without_the_flag_too(tmp_path):
    f = tmp_path / "pii.md"
    f.write_text(f"Email: {EMAIL}\n", encoding="utf-8")
    code, report = _run(["--files", str(f)], LOOSE)
    assert code == 1 and EMAIL not in report


def test_near_miss_numbers_are_masked(terms, tmp_path):
    f = tmp_path / "nearmiss.md"
    f.write_text("Mobile: +61 400 000 0123\n", encoding="utf-8")
    code, report = _run(["--terms", str(terms), "--files", str(f)])
    assert "mistyped AU number" in report, report
    assert "400 000 0123" not in report
    assert "23)" in report


@pytest.mark.parametrize("msg,masked", [
    ("a.md:1: Australian phone number ((08) 9000 0017)",
     "a.md:1: Australian phone number ((**) **** **17)"),
    ("a.md:2: looks like a mistyped AU number (+61 (0)8 9000 00271)",
     "a.md:2: looks like a mistyped AU number (+** (*)* **** ***71)"),
    ("a.md:3: non-AU international number +44 (0)20 7946 0017",
     "a.md:3: non-AU international number +** (*)** **** **17"),
])
def test_mask_message_takes_the_whole_bracketed_value(msg, masked):
    assert leak_guard.mask_message(msg) == masked


@pytest.mark.parametrize("value,masked", [
    ("a.b@c.example.test", "a***@***.test"),
    ("+61 400 000 017", "+** *** *** *17"),
    ("@x", "***@***"),
])
def test_mask_value(value, masked):
    assert leak_guard.mask_value(value) == masked


def test_check_itself_still_returns_the_raw_value(tmp_path):
    f = tmp_path / "pii.md"
    f.write_text(f"Email: {EMAIL}\n", encoding="utf-8")
    assert any(EMAIL in p for p in leak_guard.check([str(f)], LOOSE))
