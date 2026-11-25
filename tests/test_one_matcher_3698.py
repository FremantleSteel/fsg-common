"""One term list and one matcher for the leak guard, the PR-body check and
`gh_pr_create` (crm#3698, study plan step 3).

A term marked `# fsg: prose-only` in the list still blocks in prose, but a
hit inside a code name (snake_case, a dotted name, a path, backticks, a
fenced block) does not. An unmarked term, which is every client name,
blocks everywhere. Two variables naming two lists refuse.

Every term here is made up; none is ever printed.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from fsg_common import gh_pr_create, leak_guard, pr_body

WORD = "Quellword"          # a made-up ordinary word, marked prose-only
CLIENT = "Zorbex"           # a made-up client name, never marked

CFG = leak_guard.GuardConfig(repo_holds="Test repo.", client_data_lives="Elsewhere.",
                             require_term_list=True)

PROSE = [
    f"The {WORD} level decides who may see it.",
    f"{WORD.upper()} jobs stay off GitHub.",
    f"A {WORD}-based rule.",
    f"Ends with the word {WORD}.",
]
CODE = [
    f"def gate(job, {WORD.lower()}_level):",
    f"see `{WORD.lower()}` in the config",
    f"see `job.{WORD.lower()}` in the config",
    f"open scripts/{WORD.lower()}/gate.py",
    f"open scripts/{WORD.lower()}_gate.py",
    f"read S:\\Estimating\\{WORD}\\notes",
    f"use `--{WORD.lower()}` here",
    f"```\nx = {WORD.lower()}\n```",
    f"x = cfg.{WORD.lower()}",
]


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(leak_guard.TERMS_ENV, raising=False)
    monkeypatch.delenv(leak_guard.LEGACY_TERMS_ENV, raising=False)


@pytest.fixture
def terms(tmp_path) -> Path:
    f = tmp_path / "terms.txt"
    f.write_text(f"# made-up list\n{CLIENT}\n# fsg: prose-only\n{WORD}\n",
                 encoding="utf-8")
    return f


def _guard(argv) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = leak_guard.run(argv, CFG)
    return code, out.getvalue() + err.getvalue()


def _body(argv) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pr_body.main(argv)
    return code, out.getvalue() + err.getvalue()


def _create(argv) -> tuple[int, str, list]:
    calls: list = []
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gh_pr_create.main(argv, run_gh=lambda a: calls.append(a) or 0)
    return code, out.getvalue() + err.getvalue(), calls


def _file(tmp_path, text, name="a.md") -> Path:
    f = tmp_path / name
    f.write_text(text + "\n", encoding="utf-8")
    return f


def _no_term(report: str) -> None:
    low = report.lower()
    assert WORD.lower() not in low and CLIENT.lower() not in low, report


# --- the list ---------------------------------------------------------------

def test_the_mark_applies_to_the_next_term_line_only(terms):
    got = leak_guard.load_terms(str(terms))
    assert [(n, t, leak_guard.is_prose_only(t)) for n, t in got] == [
        (2, CLIENT, False), (4, WORD, True)]


def test_another_comment_between_cancels_the_mark(tmp_path):
    f = _file(tmp_path, f"# fsg: prose-only\n# note\n{WORD}", "t.txt")
    assert not leak_guard.is_prose_only(leak_guard.load_terms(str(f))[0][1])


def test_two_variables_naming_two_lists_refuse(tmp_path, monkeypatch, terms):
    other = _file(tmp_path, CLIENT, "other.txt")
    monkeypatch.setenv(leak_guard.TERMS_ENV, str(terms))
    monkeypatch.setenv(leak_guard.LEGACY_TERMS_ENV, str(other))
    f = _file(tmp_path, "nothing here")
    code, report = _guard(["--files", str(f)])
    assert code == 2 and "two different files" in report, report
    assert _body(["--body-file", str(_file(tmp_path, "Closes #1", "b.md"))])[0] == 2
    assert _create(["-R", "o/r", "--body", "Closes #1"])[0] == 2


def test_two_variables_naming_one_list_are_fine(monkeypatch, terms):
    monkeypatch.setenv(leak_guard.TERMS_ENV, str(terms))
    monkeypatch.setenv(leak_guard.LEGACY_TERMS_ENV, str(terms))
    assert leak_guard.term_list_source() == (leak_guard.TERMS_ENV, str(terms))


# --- the three checks agree --------------------------------------------------

@pytest.mark.parametrize("text", PROSE)
def test_a_prose_only_word_in_prose_is_caught_by_all_three(tmp_path, terms, text):
    f = _file(tmp_path, text)
    code, report = _guard(["--terms", str(terms), "--files", str(f)])
    assert code == 1 and "line 4 of the term list" in report, report
    _no_term(report)
    body = _file(tmp_path, f"Closes #1\n\n{text}", "body.md")
    code, report = _body(["--body-file", str(body), "--terms", str(terms)])
    assert code == 1 and "line 4 of the term list" in report, report
    _no_term(report)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(leak_guard.TERMS_ENV, str(terms))
        code, report, calls = _create(["-R", "o/r", "--body-file", str(body)])
    assert code == 1 and not calls, report
    _no_term(report)


@pytest.mark.parametrize("text", CODE)
def test_a_prose_only_word_in_a_code_name_is_not(tmp_path, terms, text):
    f = _file(tmp_path, text)
    code, report = _guard(["--terms", str(terms), "--files", str(f)])
    assert code == 0, report
    assert "1 hit(s) on a prose-only term sat in a code name" in report, report
    _no_term(report)
    body = _file(tmp_path, f"Closes #1\n\n{text}", "body.md")
    code, report = _body(["--body-file", str(body), "--terms", str(terms)])
    assert code == 0, report
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(leak_guard.TERMS_ENV, str(terms))
        code, report, calls = _create(["-R", "o/r", "--body-file", str(body)])
    assert code == 0 and len(calls) == 1, report


@pytest.mark.parametrize("text", PROSE + CODE)
def test_a_client_name_blocks_in_prose_and_in_code_names(tmp_path, terms, text):
    text = text.replace(WORD, CLIENT).replace(WORD.lower(), CLIENT.lower()) \
               .replace(WORD.upper(), CLIENT.upper())
    f = _file(tmp_path, text)
    code, report = _guard(["--terms", str(terms), "--files", str(f)])
    assert code == 1 and "line 2 of the term list" in report, report
    _no_term(report)
    body = _file(tmp_path, f"Closes #1\n\n{text}", "body.md")
    assert _body(["--body-file", str(body), "--terms", str(terms)])[0] == 1


def test_prose_beside_a_code_name_still_blocks(tmp_path, terms):
    f = _file(tmp_path, f"`{WORD.lower()}_level` is set for {WORD} jobs")
    assert _guard(["--terms", str(terms), "--files", str(f)])[0] == 1


def test_a_file_path_holding_a_client_name_still_blocks(tmp_path, terms):
    d = tmp_path / f"{CLIENT.lower()}_notes"
    d.mkdir()
    f = _file(d, "nothing here")
    code, report = _guard(["--terms", str(terms), "--files", str(f)])
    assert code == 1 and "file path holds a client term" in report, report


def test_a_file_path_holding_a_prose_only_word_does_not(tmp_path, terms):
    d = tmp_path / f"{WORD.lower()}_gate"
    d.mkdir()
    f = _file(d, "nothing here")
    assert _guard(["--terms", str(terms), "--files", str(f)])[0] == 0


def test_an_unmarked_word_in_a_code_name_blocks(tmp_path):
    lst = _file(tmp_path, WORD, "plain.txt")
    f = _file(tmp_path, CODE[0])
    assert _guard(["--terms", str(lst), "--files", str(f)])[0] == 1


# --- absent input ------------------------------------------------------------

def test_pr_body_with_no_list_says_names_were_not_checked(tmp_path):
    body = _file(tmp_path, f"Closes #1\n\n{PROSE[0]}", "body.md")
    code, report = _body(["--body-file", str(body)])
    assert code == 0 and "client names: NOT checked" in report, report


def test_pr_body_with_a_missing_list_cannot_evaluate(tmp_path):
    body = _file(tmp_path, "Closes #1", "body.md")
    code, report = _body(["--body-file", str(body), "--terms", str(tmp_path / "no.txt")])
    assert code == 2 and "CANNOT EVALUATE" in report, report


def test_pr_body_counts_the_terms_it_checked(tmp_path, terms):
    body = _file(tmp_path, "Closes #1\n\nplain words", "body.md")
    code, report = _body(["--body-file", str(body), "--terms", str(terms)])
    assert code == 0 and "checked against 2 term(s) from --terms" in report, report


def test_a_short_term_in_a_pr_body_warns_only(tmp_path):
    lst = _file(tmp_path, "Qzx", "short.txt")
    body = _file(tmp_path, "Closes #1\n\nthe Qzx job", "body.md")
    code, report = _body(["--body-file", str(body), "--terms", str(lst)])
    assert code == 0 and "WARN" in report and "qzx" not in report.lower(), report


def test_the_first_comment_is_checked_too(tmp_path, terms):
    body = _file(tmp_path, "Closes #1", "body.md")
    comment = _file(tmp_path, PROSE[0], "c.md")
    code, report = _body(["--body-file", str(body), "--comment-file", str(comment),
                          "--terms", str(terms)])
    assert code == 1 and "the first comment, line 1" in report, report
