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
    monkeypatch.delenv(leak_guard.LEGACY_TERMS_ENV, raising=False)


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
    # crm#3698 checker fix 4: the path itself is masked, never printed whole.
    assert "zorbex" not in report.lower(), report
    assert "[client term]/notes.bin" in report


def test_a_term_in_the_path_is_masked_in_every_message(terms, tmp_path):
    d = tmp_path / "zorbex_pty_ltd"
    d.mkdir()
    f = d / "card.ps1"
    f.write_text(f"# {TERM}\n# {EMAIL}\n", encoding="utf-8")
    code, report = _run(["--terms", str(terms), "--files", str(f)])
    assert code == 1, report
    assert "customer email address" in report and "client term (line 3" in report
    assert "zorbex" not in report.lower(), report


def test_the_older_variable_name_loads_the_list(monkeypatch, terms, leaky):
    # crm#3698 checker fix 1: the owner's laptop sets FSG_LEAK_TERMS_FILE.
    monkeypatch.setenv(leak_guard.LEGACY_TERMS_ENV, str(terms))
    code, report = _run(["--files", str(leaky)])
    assert code == 1, report
    assert "client term (line 3 of the term list)" in report


def test_both_names_on_two_different_files_refuse(monkeypatch, terms, leaky, tmp_path):
    # crm#3698 step 3, one list: two variables naming two files used to let
    # the current name win quietly, so two checks could read two lists.
    monkeypatch.setenv(leak_guard.TERMS_ENV, str(terms))
    monkeypatch.setenv(leak_guard.LEGACY_TERMS_ENV, str(tmp_path / "missing.txt"))
    code, report = _run(["--files", str(leaky)])
    assert code == 2 and "two different files" in report, report


def test_both_names_on_the_same_file_load_it(monkeypatch, terms, leaky):
    monkeypatch.setenv(leak_guard.TERMS_ENV, str(terms))
    monkeypatch.setenv(leak_guard.LEGACY_TERMS_ENV, str(terms))
    assert _run(["--files", str(leaky)])[0] == 1


def test_a_broken_older_name_refuses_like_the_current_one(monkeypatch, leaky, tmp_path):
    monkeypatch.setenv(leak_guard.LEGACY_TERMS_ENV, str(tmp_path / "missing.txt"))
    code, report = _run(["--terms-optional", "--files", str(leaky)])
    assert code == 2, report
    assert leak_guard.LEGACY_TERMS_ENV in report


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


# --- whole-word matching, the same in every repo (owner's choice, 21 Nov) --

@pytest.mark.parametrize("text,blocks", [
    ("QUILLMORE_tender.md", True),
    ("quillmore-quote", True),
    ("Quillmoreish notes", False),
])
def test_a_term_matches_as_a_whole_word(tmp_path, text, blocks):
    lst = tmp_path / "terms.txt"
    lst.write_text("Quillmore\n", encoding="utf-8")
    f = tmp_path / "a.md"
    f.write_text(text + "\n", encoding="utf-8")
    assert (_run(["--terms", str(lst), "--files", str(f)])[0] == 1) is blocks


def test_a_space_in_a_term_matches_a_file_name_separator(terms, tmp_path):
    f = tmp_path / "a.md"
    f.write_text("see zorbex_pty-ltd.xlsx\n", encoding="utf-8")
    assert _run(["--terms", str(terms), "--files", str(f)])[0] == 1


# --- the guard honours its own allowed-address list (owner's decision, 22 Nov
# 2026, "Guard honours own list"). A term that is EXACTLY an address on the
# config's allowed list is not checked: whole term, case-insensitive, never a
# domain or a part of one. Every address here is made up.

OWN = "fixture.owner@zorbex-fixture.test"
OWN_CONFIG = leak_guard.GuardConfig(
    repo_holds="Test repo.", client_data_lives="Elsewhere.",
    enable_pii=True, require_term_list=True,
    allowed_email_addresses=frozenset({OWN}))


def _own_list(tmp_path, *lines) -> Path:
    f = tmp_path / "own-terms.txt"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


@pytest.mark.parametrize("term", [OWN, OWN.upper(), f"  {OWN}  "])
def test_a_term_that_is_an_allowed_address_is_not_flagged(tmp_path, term):
    lst = _own_list(tmp_path, term, TERM)
    f = tmp_path / "mail-redirect.md"
    f.write_text(f"test mail goes to {OWN}\n", encoding="utf-8")
    code, report = _run(["--terms", str(lst), "--files", str(f)], OWN_CONFIG)
    assert code == 0, report
    assert "checked against 1 term(s)" in report
    assert "1 term(s) not checked: each is exactly an address this guard allows" in report
    assert OWN not in report.lower() and "zorbex" not in report.lower(), report


def test_a_planted_term_still_blocks_beside_an_allowed_address(tmp_path, leaky):
    lst = _own_list(tmp_path, OWN, TERM)
    leaky.write_text(leaky.read_text(encoding="utf-8") + f"# {OWN}\n", encoding="utf-8")
    code, report = _run(["--terms", str(lst), "--files", str(leaky)], OWN_CONFIG)
    assert code == 1, report
    assert "client term (line 2 of the term list)" in report
    assert "line 1 of the term list" not in report
    assert "zorbex" not in report.lower(), report


@pytest.mark.parametrize("term", [
    "zorbex-fixture.test",                    # the allowed address's domain
    "@zorbex-fixture.test",
    "fixture.owner",                          # a part of the allowed address
    "fixture.owner@zorbex-fixture.test.au",   # holds the allowed address
    "a.fixture.owner@zorbex-fixture.test",
])
def test_a_term_that_only_shares_part_of_an_allowed_address_still_blocks(tmp_path, term):
    lst = _own_list(tmp_path, term)
    f = tmp_path / "notes.md"
    f.write_text(f"see {term} here\n", encoding="utf-8")
    code, report = _run(["--terms", str(lst), "--files", str(f)], OWN_CONFIG)
    assert code == 1, report
    assert "client term (line 1 of the term list)" in report
    assert "zorbex" not in report.lower(), report


def test_a_list_of_only_allowed_addresses_refuses(tmp_path, leaky):
    # Nothing would be checked, the same as an empty list.
    lst = _own_list(tmp_path, OWN)
    code, report = _run(["--terms", str(lst), "--terms-optional", "--files", str(leaky)],
                        OWN_CONFIG)
    assert code == 2, report
    assert leak_guard.NOT_LOADED in report
    assert "zorbex" not in report.lower(), report


def test_check_skips_an_allowed_address_term_too(tmp_path):
    # The exemption sits where terms are compared, so `check()` callers get it.
    f = tmp_path / "a.md"
    f.write_text(f"{OWN}\n", encoding="utf-8")
    assert leak_guard.check([str(f)], OWN_CONFIG, terms=[(1, OWN)]) == []
    f.write_text("fixture.owner\n", encoding="utf-8")
    assert leak_guard.check([str(f)], OWN_CONFIG, terms=[(1, "fixture.owner")]) != []


# --- a term hit wholly inside an allowed address is skipped (owner's decision,
# 23 Nov 2026, "guard changes- A"). The same term in plain text, or inside any
# address not on the list, still blocks. The term has two words and no "@",
# and matches inside the address because a space also matches ".". Every
# term and address here is made up.

SPAN_TERM = "Vantor Quell"
SPAN_OWN = "vantor.quell@zorbex-fixture.test"
SPAN_CONFIG = leak_guard.GuardConfig(
    repo_holds="Test repo.", client_data_lives="Elsewhere.",
    enable_pii=True, require_term_list=True,
    allowed_email_addresses=frozenset({SPAN_OWN}))


def _span_run(tmp_path, text, config=SPAN_CONFIG) -> tuple[int, str]:
    lst = _own_list(tmp_path, SPAN_TERM)
    f = tmp_path / "mail-redirect.md"
    f.write_text(text, encoding="utf-8")
    return _run(["--terms", str(lst), "--files", str(f)], config)


def _never_printed(report):
    assert "vantor" not in report.lower() and "quell" not in report.lower(), report


@pytest.mark.parametrize("text", [
    f"test mail goes to {SPAN_OWN}\n",
    f"ALLOWED = {{'{SPAN_OWN.upper()}', 'x@y.invalid'}}\n",
    f"<{SPAN_OWN}>, <{SPAN_OWN}>\n",
])
def test_a_term_inside_an_allowed_address_passes(tmp_path, text):
    code, report = _span_run(tmp_path, text)
    assert code == 0, report
    assert "checked against 1 term(s)" in report
    _never_printed(report)


@pytest.mark.parametrize("text", [
    "letter to Vantor Quell\n",
    "see vantor_quell-notes.xlsx\n",
    "vantor.quell\n",
])
def test_the_same_term_in_plain_text_still_blocks(tmp_path, text):
    code, report = _span_run(tmp_path, text)
    assert code == 1, report
    assert "client term (line 1 of the term list)" in report
    _never_printed(report)


@pytest.mark.parametrize("addr", [
    "vantor.quell@zorbex-fixtura.test",     # one character different
    "vantor.quell@zorbex-fixture.tesu",     # one character different
    "vantor.quell@zorbex-fixture.test.au",  # holds the allowed address
    "a.vantor.quell@zorbex-fixture.test",   # holds the allowed address
])
def test_the_same_term_inside_an_address_not_on_the_list_still_blocks(tmp_path, addr):
    code, report = _span_run(tmp_path, f"mail to {addr}\n")
    assert code == 1, report
    assert "client term (line 1 of the term list)" in report
    _never_printed(report)


@pytest.mark.parametrize("text,line", [
    (f"{SPAN_OWN} and Vantor Quell\n", 1),
    (f"Vantor Quell <{SPAN_OWN}>\n", 1),
    (f"to: {SPAN_OWN}\nfrom: Vantor Quell\n", 2),
])
def test_an_allowed_address_beside_the_term_still_blocks_the_plain_hit(tmp_path, text,
                                                                         line):
    code, report = _span_run(tmp_path, text)
    assert code == 1, report
    assert f"mail-redirect.md:{line}: client term (line 1 of the term list)" in report
    _never_printed(report)


@pytest.mark.parametrize("config", [STRICT, OWN_CONFIG])
def test_a_planted_term_with_no_allowed_address_blocks(tmp_path, config):
    # The guard planted-term test: no address on the list, so nothing is skipped,
    # not even the term inside an address.
    code, report = _span_run(tmp_path, f"test mail goes to {SPAN_OWN}\n", config)
    assert code == 1, report
    assert "client term (line 1 of the term list)" in report
    _never_printed(report)


def test_check_skips_a_term_inside_an_allowed_address_too(tmp_path):
    f = tmp_path / "a.md"
    f.write_text(f"{SPAN_OWN}\n", encoding="utf-8")
    assert leak_guard.check([str(f)], SPAN_CONFIG, terms=[(1, SPAN_TERM)]) == []
    f.write_text(f"{SPAN_OWN} Vantor Quell\n", encoding="utf-8")
    assert leak_guard.check([str(f)], SPAN_CONFIG, terms=[(1, SPAN_TERM)]) != []


def test_a_hit_that_runs_out_of_an_allowed_address_still_blocks(tmp_path):
    # Wholly inside, not merely touching: this hit starts in the address and
    # ends in the plain text after it.
    lst = _own_list(tmp_path, "Fixture Test Ops")
    f = tmp_path / "a.md"
    f.write_text(f"{SPAN_OWN} ops\n", encoding="utf-8")
    code, report = _run(["--terms", str(lst), "--files", str(f)], SPAN_CONFIG)
    assert code == 1, report
    assert "client term (line 1 of the term list)" in report
    assert "fixture test ops" not in report.lower(), report


# --- review fixes on PR 91 (crm#3698) --------------------------------------

def test_a_term_file_with_a_bom_still_checks_its_first_line(tmp_path, leaky):
    # A list saved by Windows PowerShell 5.1 or Notepad's "UTF-8 with BOM"
    # starts with U+FEFF. Read as plain utf-8, the line-1 term carried the
    # BOM, could never match, and the run still counted it as checked.
    lst = tmp_path / "bom-terms.txt"
    lst.write_bytes(b"\xef\xbb\xbf" + f"{TERM}\n".encode())
    assert leak_guard.load_terms(str(lst)) == [(1, TERM)]
    code, report = _run(["--terms", str(lst), "--files", str(leaky)])
    assert code == 1, report
    assert "client term (line 1 of the term list)" in report
    assert "zorbex" not in report.lower(), report


def test_a_bom_before_a_comment_line_does_not_make_it_a_term(tmp_path):
    lst = tmp_path / "bom-comment.txt"
    lst.write_bytes(b"\xef\xbb\xbf" + f"# made-up list\n{TERM}\n".encode())
    assert leak_guard.load_terms(str(lst)) == [(2, TERM)]


def test_a_check_wrapper_without_the_terms_keyword_still_runs(monkeypatch, tmp_path):
    # fsg-tender-review's guard replaces leak_guard.check with a wrapper whose
    # signature predates `terms=`. With no list loaded, run() must not pass
    # the keyword, or that guard crashes with a TypeError on the pin bump.
    real = leak_guard.check
    seen = []

    def wrapper(paths, config, path_sources=None, read_content=True,
                near_misses=None):
        seen.append(paths)
        return real(paths, config, path_sources=path_sources,
                    read_content=read_content, near_misses=near_misses)

    # real-gate test: test_planted_term_blocks_and_is_masked (the wrapper calls the real check)
    monkeypatch.setattr(leak_guard, "check", wrapper)
    f = tmp_path / "clean.md"
    f.write_text("nothing to see\n", encoding="utf-8")
    code, report = _run(["--files", str(f)], LOOSE)
    assert code == 0, report
    assert seen == [[str(f)]]


# --- a short term warns, never blocks on its own (the owner's Desk answer
# of 24 Nov 2026, crm#3698). Both terms are made up.

SHORT = "Qzv"          # 3 characters: a hit warns
LONG = "Wrex"          # 4 characters: a hit blocks, as before


def _short_long(tmp_path, text) -> tuple[int, str]:
    lst = _own_list(tmp_path, SHORT, LONG)
    f = tmp_path / "notes.md"
    f.write_text(text, encoding="utf-8")
    return _run(["--terms", str(lst), "--files", str(f)])


def test_a_short_term_hit_warns_and_passes(tmp_path):
    code, report = _short_long(tmp_path, "see qzv here\n")
    assert code == 0, report
    assert "WARN -- " in report
    assert "client term (line 1 of the term list)" in report
    assert "1 of them under 4 characters" in report
    assert "qzv" not in report.lower(), report


def test_a_four_letter_term_hit_still_blocks(tmp_path):
    code, report = _short_long(tmp_path, "see wrex here\n")
    assert code == 1, report
    assert "client term (line 2 of the term list)" in report
    assert "WARN -- " not in report
    assert "wrex" not in report.lower(), report


def test_a_short_and_a_long_hit_in_one_file_blocks_and_warns(tmp_path):
    code, report = _short_long(tmp_path, "qzv and wrex\n")
    assert code == 1, report
    assert "BLOCKED" in report and "WARN -- " in report
    assert "qzv" not in report.lower() and "wrex" not in report.lower(), report


def test_a_short_term_in_a_file_path_warns(tmp_path):
    lst = _own_list(tmp_path, SHORT, LONG)
    f = tmp_path / "qzv_notes.md"
    f.write_text("nothing here\n", encoding="utf-8")
    code, report = _run(["--terms", str(lst), "--files", str(f)])
    assert code == 0, report
    assert "file path holds a client term (line 1" in report


def test_check_itself_still_blocks_on_a_short_term(tmp_path):
    # Only run() splits the list; a caller of check() that hands it a short
    # term gets the safe answer, a block.
    f = tmp_path / "notes.md"
    f.write_text("see qzv here\n", encoding="utf-8")
    assert leak_guard.check([str(f)], LOOSE, terms=[(1, SHORT)])


def test_short_term_length_is_four():
    assert leak_guard.SHORT_TERM_LENGTH == 4
    assert leak_guard.is_short_term(" Qzv ")
    assert not leak_guard.is_short_term("Wrex")
