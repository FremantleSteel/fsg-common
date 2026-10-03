"""fsg_common.leak_guard: the shared engine, and the new historical-blob
content read that no source repo had. See the module's own docstring for
which repo each ported piece came from and why the PII/co-occurrence layer
stays repo-specific rather than being ported here.

Falsification convention followed throughout, same as the rest of this
package: a positive control (a real leak-shaped string the rule must still
catch) and a negative control (real legitimate content it must still pass)
for every pattern, not just a green assertion.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

import pytest

from fsg_common import leak_guard

CONFIG = leak_guard.GuardConfig(
    repo_holds="This test repo holds code and docs only.",
    client_data_lives="Client data stays elsewhere.",
    allowed_paths=(re.compile(r"^docs/assets/.*\.png$"),),
)


# --- extensions and filenames ------------------------------------------------

def test_a_blocked_extension_refuses():
    problems = leak_guard.check(["drawing.pdf"], CONFIG, read_content=False)
    assert problems and "client drawings" in problems[0]


def test_an_allowed_path_exempts_only_the_extension_rule():
    problems = leak_guard.check(["docs/assets/diagram.png"], CONFIG, read_content=False)
    assert problems == []


def test_a_clean_source_extension_is_not_blocked():
    problems = leak_guard.check(["src/module.py"], CONFIG, read_content=False)
    assert problems == []


def test_a_dotenv_file_is_always_blocked_by_name():
    problems = leak_guard.check([".env"], CONFIG, read_content=False)
    assert problems and "credentials file" in problems[0]


def test_dotenv_example_is_not_blocked_by_name():
    problems = leak_guard.check([".env.example"], CONFIG, read_content=False)
    assert problems == []


# --- secret patterns: positive and negative controls -------------------------

def _scan_text(text: str, config: leak_guard.GuardConfig = CONFIG) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sample.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return leak_guard.check([p], config)


def test_fsg_workbook_password_is_caught():
    hits = _scan_text('FSG_WORKBOOK_PASSWORD=hunter2\n')
    assert any("workbook/register password" in h for h in hits)


def test_generic_password_eq_form_is_caught():
    hits = _scan_text('password = "correct-horse-battery-staple"\n')
    assert any("hardcoded password" in h for h in hits)


def test_generic_password_colon_json_form_is_caught():
    hits = _scan_text('{"password": "correct-horse-battery-staple"}\n')
    assert any("hardcoded password" in h for h in hits)


def test_identifier_prefixed_password_is_now_caught():
    """The gap fsg-tender-review#92 measured and closed 1 Sep 2026: a
    letter immediately before `password` (`dbpassword=`, `_password=`) used
    to be deliberately unmatched, on a prediction that it usually names an
    environment variable. Measured false: 25 real occurrences in one repo,
    zero new false positives from removing the restriction."""
    for text in ('workbook_password = "s3cr3tVal123"\n',
                 'register_password="s3cr3tVal123"\n'):
        hits = _scan_text(text)
        assert any("hardcoded password" in h for h in hits), text


def test_a_bare_environment_variable_name_is_not_a_false_positive():
    """The value shape (a quoted 3+ char literal) is what discriminates a
    real secret from a variable NAME -- `workbook_password=None` has no
    quoted value and must not match on the name alone."""
    hits = _scan_text('workbook_password=None\n')
    assert not any("hardcoded password" in h for h in hits)


def test_a_password_value_containing_a_slash_is_still_caught():
    """crm's own 29 Aug fix excluded `/` from the value class to avoid
    matching a path; measured wrong 2 Sep 2026 -- `/` is in the base64
    alphabet and every default password-generator charset, so the
    exclusion missed 5 of 6 realistic generated secrets."""
    hits = _scan_text('password = "aB3/xY9zQw1+Lm4="\n')
    assert any("hardcoded password" in h for h in hits)


def test_a_password_value_that_is_actually_a_path_is_not_caught():
    hits = _scan_text("password = '/mnt/data/fremantle-crm-production/.env'\n")
    assert not any("hardcoded password" in h for h in hits)


def test_a_password_value_that_is_a_template_expression_is_not_caught():
    for text in ('"password": "={{$json.pw}}"\n', '"password": "${VAR}"\n'):
        hits = _scan_text(text)
        assert not any("hardcoded password" in h for h in hits), text


def test_escaped_quote_eq_form_is_caught():
    """fsg-estimating-tools#116-adjacent, 3 Sep 2026: a value inside a JSON
    string or Python docstring where the quote characters are themselves
    backslash-escaped -- GENERIC_PASSWORD_RE requires a real quote and
    cannot see this."""
    hits = _scan_text('password = \\"correct-horse-battery\\"\n')
    assert any("hardcoded password" in h for h in hits)


def test_escaped_quote_colon_form_is_caught():
    hits = _scan_text('\\"password\\": \\"correct-horse-battery\\"\n')
    assert any("hardcoded password" in h for h in hits)


def test_a_placeholder_value_is_not_caught():
    """The value shape says of itself that it is synthetic -- a fixture
    testing the parser, not a real credential."""
    hits = _scan_text('password = "not-a-real-credential"\n')
    assert not any("hardcoded password" in h for h in hits)


def test_a_value_behind_a_literal_escape_sequence_is_still_caught():
    """The `\\b`-boundary defect every pattern in every source repo carried
    until 27 Aug 2026: a value in source text sitting right after a
    LITERAL `\\n`/`\\r`/`\\t` (not a real newline) is invisible to `\\b`,
    because the escape's own letter is a word character."""
    hits = _scan_text('"Name\\npassword = \'s3cr3tVal123\'"\n')
    assert any("hardcoded password" in h for h in hits)


def test_an_assignment_split_across_a_REAL_newline_is_not_a_secret():
    """Found by fsg-tender-review's own test suite failing against crm's
    literal pattern, not by inspection: `\\s*` around the operator matches
    a REAL newline (not a literal escape sequence -- this is the opposite
    case from the test above), so `password =` on one line and a value on
    the next used to match, and tender-review's own history names the
    exact incident this reproduces -- `FSG_WORKBOOK_PASSWORD=` with an
    EMPTY value followed by any non-blank next line matched and reported
    that line's first token as the password."""
    hits = _scan_text('password =\n"s3cr3tVal123"\n')
    assert not any("hardcoded password" in h for h in hits)


# --- falsification: prove the fix actually does something --------------------

def test_falsify_the_identifier_prefix_fix_by_reintroducing_the_lookbehind():
    """Not just a green test: build a config carrying ONLY the OLD,
    lookbehind-restricted pattern (isolated from the real, fixed one that
    `DEFAULT_SECRET_PATTERNS` would otherwise also apply) and confirm the
    identifier-prefixed case goes red -- proving the fixture text itself
    discriminates, rather than the assertion above always passing for an
    unrelated reason."""
    old_style = re.compile(
        r"(?<![A-Za-z0-9_])password[ \t]*=[ \t]*['\"][^'\"]{3,}['\"]", re.I)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(leak_guard, "DEFAULT_SECRET_PATTERNS",
                  ((leak_guard.FSG_CREDENTIAL_RE, "fsg cred"),
                   (old_style, "a hardcoded password")))
        isolated = leak_guard.GuardConfig(repo_holds="x", client_data_lives="x")
        hits = _scan_text('workbook_password = "s3cr3tVal123"\n', config=isolated)
    assert not any("hardcoded password" in h for h in hits), (
        "the neutered (old) pattern should NOT catch this -- if it did, "
        "the fixture doesn't actually discriminate the fix")


# --- PII: email --------------------------------------------------------------

PII_CONFIG = leak_guard.GuardConfig(
    repo_holds="x", client_data_lives="x",
    enable_pii=True,
    allowed_email_addresses=frozenset({"staff@fsg.example"}),
    allowed_email_domains=frozenset({"fremantlesteel.com.au"}),
    role_account_local_parts=frozenset({"tenders", "info"}),
)


def test_a_real_looking_customer_email_is_caught():
    hits = _scan_text("Contact: john.smith@gmail.com\n", config=PII_CONFIG)
    assert any("customer email address" in h for h in hits)


def test_an_allowlisted_address_is_not_caught():
    hits = _scan_text("From: staff@fsg.example\n", config=PII_CONFIG)
    assert not any("customer email" in h for h in hits)


def test_an_allowlisted_domain_is_not_caught():
    hits = _scan_text("From: anyone@fremantlesteel.com.au\n", config=PII_CONFIG)
    assert not any("customer email" in h for h in hits)


def test_an_invalid_tld_placeholder_is_not_caught():
    hits = _scan_text("Contact: person@example.invalid\n", config=PII_CONFIG)
    assert not any("customer email" in h for h in hits)


def test_a_role_account_local_part_is_not_caught():
    hits = _scan_text("From: tenders@somecompany.com.au\n", config=PII_CONFIG)
    assert not any("customer email" in h for h in hits)


def test_pii_is_not_reported_when_disabled():
    """The default: a repo that does not opt in gets no PII scanning at
    all, same as three of the four source repos before this consolidation."""
    hits = _scan_text("Contact: john.smith@gmail.com\n", config=CONFIG)
    assert not any("customer email" in h for h in hits)


def test_email_behind_a_literal_escape_is_still_caught_without_swallowing_it():
    """The escape-adjacent boundary fix must not swallow the escape LETTER
    into the local part -- that used to silently defeat the allowlists and
    report a wrong address."""
    hits = _scan_text('"Name\\njohn.smith@gmail.com"\n', config=PII_CONFIG)
    matches = [h for h in hits if "customer email" in h]
    assert matches, hits
    assert "njohn.smith@gmail.com" not in matches[0]
    assert "john.smith@gmail.com" in matches[0]


def test_allowlisted_address_behind_compose_default_is_not_caught():
    """`${X:-staff@fsg.example}`: the `-` is the compose default operator,
    not part of the address, so the exact-address allowlist must still match."""
    hits = _scan_text("A: ${X:-staff@fsg.example}\n", config=PII_CONFIG)
    assert not any("customer email" in h for h in hits), hits


def test_non_allowlisted_address_behind_compose_default_is_still_caught():
    hits = _scan_text("A: ${X:-john.smith@gmail.com}\n", config=PII_CONFIG)
    matches = [h for h in hits if "customer email" in h]
    assert matches, hits
    assert "-john.smith" not in matches[0]
    assert "john.smith@gmail.com" in matches[0]


# --- PII: phone ---------------------------------------------------------------

def test_an_au_mobile_is_caught():
    hits = _scan_text("Call 0400 111 222\n", config=PII_CONFIG)
    assert any("Australian phone number" in h for h in hits)


def test_an_au_mobile_with_international_prefix_is_caught():
    hits = _scan_text("Call +61 400 111 222\n", config=PII_CONFIG)
    assert any("Australian phone number" in h for h in hits)


def test_a_wa_bracketed_landline_is_caught():
    """The format the census found the ORIGINAL patterns could not match at
    all -- FSG is a WA fabricator and this is the dominant local business
    landline format."""
    hits = _scan_text("Office (08) 9000 0000\n", config=PII_CONFIG)
    assert any("Australian phone number" in h for h in hits)


def test_a_phone_behind_a_literal_escape_is_still_caught():
    hits = _scan_text('"Name\\n0400 111 222"\n', config=PII_CONFIG)
    assert any("Australian phone number" in h for h in hits)


def test_a_uuid_fragment_is_not_a_false_positive():
    """The unseparated-8-digit local-number form is deliberately NOT
    matched: allowing it fired on hyphen-joined UUID fragments in real n8n
    workflow JSON. Precision won over the last 0.18% of coverage."""
    hits = _scan_text('"id": "9012abcd-6123-4a11-9f00-1234567890ab"\n',
                      config=PII_CONFIG)
    assert not any("Australian phone number" in h for h in hits)


def test_a_dimension_pair_is_not_a_false_positive():
    hits = _scan_text("Plate 200 x 200 x 10 PL\n", config=PII_CONFIG)
    assert not any("Australian phone number" in h for h in hits)


# --- the historical-blob read: the new capability -----------------------------

def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True)


@pytest.fixture()
def throwaway_repo():
    with tempfile.TemporaryDirectory() as d:
        _git("init", "-q", cwd=d)
        _git("config", "user.email", "test@test.com", cwd=d)
        _git("config", "user.name", "test", cwd=d)
        yield d


def test_range_content_read_falls_back_to_the_commit_that_touched_the_path(
        throwaway_repo):
    """The exact fsg-bluebeam-steel-standards#64 scenario: a file exists at
    an EARLIER commit within the range, is deleted by a LATER one, and the
    working tree (already at the later commit) does not have it on disk.
    `check()` must still read and scan its content from the commit that
    last touched it, not report a false 'could not be read'."""
    d = throwaway_repo
    leak_path = os.path.join(d, "sub", "leaky.txt")
    os.makedirs(os.path.dirname(leak_path))
    with open(leak_path, "w", encoding="utf-8") as fh:
        fh.write("FSG_WORKBOOK_PASSWORD=hunter2\n")
    _git("add", "sub/leaky.txt", cwd=d)
    _git("commit", "-q", "-m", "add leaky file", cwd=d)
    commit1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                             capture_output=True, text=True).stdout.strip()
    _git("rm", "-q", "sub/leaky.txt", cwd=d)
    _git("commit", "-q", "-m", "delete leaky file", cwd=d)

    assert not os.path.exists(leak_path)  # confirmed gone from disk

    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        sources = leak_guard._range_path_sources(
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD")
        assert sources.get("sub/leaky.txt") == commit1
        problems = leak_guard.check(["sub/leaky.txt"], CONFIG,
                                    path_sources=sources)
    finally:
        os.chdir(old_cwd)
    assert any("workbook/register password" in p for p in problems), problems


def test_a_binary_blob_reached_via_the_historical_fallback_does_not_crash(
        throwaway_repo):
    """Found by running this against a real historical binary file, not
    assumed: `subprocess.run(..., text=True)` decodes a `git show` blob
    with the PLATFORM'S default encoding (cp1252 on Windows) and raises
    `UnicodeDecodeError` out of its own reader thread on genuinely binary
    content -- a zip, in the real case that found this
    (fsg-bluebeam-steel-standards, `repo-HEAD.zip`, a known, already-
    disclosed historical mistake exempted by path so the extension rule
    does not block it, which is exactly what put it on the content-read
    path this test reproduces). `check()` must treat it the same
    permissive way binary-shaped disk content already is (scanned as
    best-effort text, not crashed on)."""
    d = throwaway_repo
    zip_path = os.path.join(d, "archive.zip")
    # A real zip local-file-header signature plus a byte cp1252 -- Windows'
    # default text codec, and what the real crash decoded with -- leaves
    # UNDEFINED (0x81/0x8D/0x8F/0x90/0x9D). The real failure was "can't
    # decode byte 0x9d"; a byte range that happens to be valid cp1252
    # would pass `text=True` silently and not exercise this at all.
    with open(zip_path, "wb") as fh:
        fh.write(b"PK\x03\x04" + bytes(range(200, 256)) + b"\x9d\x00\x01\x02")
    _git("add", "archive.zip", cwd=d)
    _git("commit", "-q", "-m", "add archive", cwd=d)
    _git("rm", "-q", "archive.zip", cwd=d)
    _git("commit", "-q", "-m", "remove archive", cwd=d)

    assert not os.path.exists(zip_path)

    # Exempted by path, same as the real case -- otherwise the extension
    # rule blocks it before content is ever read, and this test would pass
    # without exercising the crash at all.
    exempt_config = leak_guard.GuardConfig(
        repo_holds="x", client_data_lives="x",
        allowed_paths=(re.compile(r"^archive\.zip$"),))

    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        sources = leak_guard._range_path_sources(
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD")
        assert "archive.zip" in sources
        # Must not raise. This config sets no PII/secret pattern that would
        # match random bytes, so the honest outcome is "no problems", not
        # a crash.
        problems = leak_guard.check(["archive.zip"], exempt_config,
                                    path_sources=sources)
    finally:
        os.chdir(old_cwd)
    assert problems == [], problems


def test_a_path_absent_from_both_disk_and_every_range_commit_still_refuses(
        throwaway_repo):
    """The fallback must not paper over a genuine gap: a path that never
    existed anywhere in the range still reports 'could not be read'."""
    d = throwaway_repo
    with open(os.path.join(d, "ok.txt"), "w", encoding="utf-8") as fh:
        fh.write("nothing interesting\n")
    _git("add", "ok.txt", cwd=d)
    _git("commit", "-q", "-m", "init", cwd=d)

    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        sources = leak_guard._range_path_sources(
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD")
        problems = leak_guard.check(["never/existed.txt"], CONFIG,
                                    path_sources=sources)
    finally:
        os.chdir(old_cwd)
    assert any("could not be read" in p for p in problems), problems


def test_staged_mode_has_no_fallback_and_a_missing_file_stays_a_gap():
    """`--files`/staged checks pass `path_sources=None` -- there is no range
    and nothing to fall back to, so a missing file is exactly what it looks
    like, not silently papered over."""
    problems = leak_guard.check(["/definitely/does/not/exist.txt"], CONFIG)
    assert any("could not be read" in p for p in problems), problems


def test_a_git_show_environment_failure_is_worded_distinctly_from_a_gap(
        throwaway_repo, monkeypatch):
    """fsg-estimating-tools#308, measured for real 11-12 Sep 2026 (PR #307's
    own CI-verification run, then reproduced deliberately here): a Windows
    checkout whose absolute path is long enough makes `git show` itself
    fail -- `fatal: failed to stat '<rev>:<path>': Filename too long`, exit
    128 -- for a path `_range_path_sources` had JUST found a real commit
    for. The stderr below is a verbatim copy of a live reproduction (a
    genuine six-level-deep tracked path under a short repo root, well
    within `fsg-common`'s own checkout length), not invented text.

    `_range_path_sources` runs for real here and genuinely finds the
    commit -- the content provably exists in this range's history. Only
    the final `git show` call is mocked, to the exact failure measured,
    so this proves `check()`'s WORDING, not the reproduction itself (that
    part doesn't need re-proving on every CI machine, which may not even
    be Windows). Before this fix, `_read_body` returned `None` for this
    case exactly as it does for a path that never existed anywhere in the
    range -- the two were indistinguishable. This is the falsification
    that they no longer are.
    """
    d = throwaway_repo
    leak_path = os.path.join(d, "leaky.docx")
    with open(leak_path, "w", encoding="utf-8") as fh:
        fh.write("FSG_WORKBOOK_PASSWORD=hunter2\n")
    _git("add", "leaky.docx", cwd=d)
    _git("commit", "-q", "-m", "add leaky file", cwd=d)
    commit1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                             capture_output=True, text=True).stdout.strip()
    _git("rm", "-q", "leaky.docx", cwd=d)
    _git("commit", "-q", "-m", "delete leaky file", cwd=d)
    assert not os.path.exists(leak_path)

    real_run = subprocess.run

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "show"]:
            target = args[2]
            return subprocess.CompletedProcess(
                args, 128, stdout=b"",
                stderr=(f"fatal: failed to stat '{target}': "
                        f"Filename too long\n").encode())
        return real_run(args, **kwargs)

    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        sources = leak_guard._range_path_sources(
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD")
        assert sources.get("leaky.docx") == commit1, sources
        # real-gate test: test_a_genuine_gap_does_not_pick_up_the_environment_wording
        monkeypatch.setattr(leak_guard.subprocess, "run", fake_run)
        problems = leak_guard.check(["leaky.docx"], CONFIG,
                                    path_sources=sources)
    finally:
        os.chdir(old_cwd)

    assert len(problems) == 1, problems
    msg = problems[0]
    # The distinguishing content: the real command, its exit code, its
    # stderr, and an explicit steer towards the real fix.
    assert "Filename too long" in msg, msg
    assert "128" in msg, msg
    assert "ENVIRONMENT" in msg, msg
    assert "shorter checkout path" in msg, msg
    # And NOT the generic gap's wording -- the two must read as different
    # problems, not the same message with extra words appended.
    assert "FileNotFoundError" not in msg, msg
    # Still a gap either way: this file was not scanned, so it still
    # blocks, exactly as the generic gap already does.
    assert "not a pass" in msg, msg


def test_a_genuine_gap_does_not_pick_up_the_environment_wording(
        throwaway_repo):
    """The control in the other direction: a path with NO commit source at
    all (never touched anywhere in the range) must keep the ORIGINAL
    generic wording, not the new environment-failure one -- the two stay
    distinguishable both ways, not just when an environment failure is
    forced."""
    d = throwaway_repo
    with open(os.path.join(d, "ok.txt"), "w", encoding="utf-8") as fh:
        fh.write("nothing interesting\n")
    _git("add", "ok.txt", cwd=d)
    _git("commit", "-q", "-m", "init", cwd=d)

    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        sources = leak_guard._range_path_sources(
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD")
        problems = leak_guard.check(["never/existed.txt"], CONFIG,
                                    path_sources=sources)
    finally:
        os.chdir(old_cwd)

    assert len(problems) == 1, problems
    assert "FileNotFoundError" in problems[0], problems
    assert "ENVIRONMENT" not in problems[0], problems


# --- run(): population selection and the zero-files refusal ------------------

def test_no_staged_files_is_a_pass_not_a_refusal(monkeypatch, capsys):
    # real-gate test: test_real_staged_files_sees_a_blocked_file_and_a_clean_one
    monkeypatch.setattr(leak_guard, "staged_files", lambda: [])
    rc = leak_guard.run([], CONFIG)
    assert rc == 0
    assert "nothing to check" in capsys.readouterr().out


def test_files_given_with_no_paths_is_a_refusal_not_a_silent_pass(capsys):
    """The live CI shape: `xargs -0` with no `-r` runs the command once
    with no arguments on empty input. `nargs='*'` makes that `[]`, which
    must not be indistinguishable from `--files` never being passed."""
    rc = leak_guard.run(["--files"], CONFIG)
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err


def test_an_empty_range_refuses_rather_than_reporting_clean(
        throwaway_repo, capsys):
    d = throwaway_repo
    with open(os.path.join(d, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    _git("add", "a.txt", cwd=d)
    _git("commit", "-q", "-m", "init", cwd=d)
    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        rc = leak_guard.run(["--range", "HEAD..HEAD"], CONFIG)
    finally:
        os.chdir(old_cwd)
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err


def test_a_deletion_only_range_passes_rather_than_refusing(
        throwaway_repo, capsys):
    d = throwaway_repo
    with open(os.path.join(d, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    _git("add", "a.txt", cwd=d)
    _git("commit", "-q", "-m", "init", cwd=d)
    c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                        capture_output=True, text=True).stdout.strip()
    _git("rm", "-q", "a.txt", cwd=d)
    _git("commit", "-q", "-m", "delete only", cwd=d)
    old_cwd = os.getcwd()
    os.chdir(d)
    try:
        rc = leak_guard.run(["--range", f"{c1}..HEAD"], CONFIG)
    finally:
        os.chdir(old_cwd)
    out = capsys.readouterr()
    assert rc == 0
    assert "only deletes" in out.out


# --- GuardConfig composition ---------------------------------------------------

def test_extra_blocked_extensions_add_to_the_default_set():
    config = leak_guard.GuardConfig(
        repo_holds="x", client_data_lives="x",
        extra_blocked_extensions={".xlam": "an add-in"})
    assert ".xlam" in config.blocked_extensions
    assert ".pdf" in config.blocked_extensions  # the shared baseline survives


def test_extra_secret_patterns_add_to_not_replace_the_defaults():
    import re as _re
    marker = (_re.compile(r"MARKER_SECRET"), "a repo-specific marker")
    config = leak_guard.GuardConfig(
        repo_holds="x", client_data_lives="x",
        extra_secret_patterns=(marker,))
    names = [why for _rx, why in config.secret_patterns]
    assert "a repo-specific marker" in names
    assert "a hardcoded password" in names


# --- EspoCRM detectors, near-misses, exemptions, --all (crm#1719 slice 4) ----
# Each has a positive control (the shape it exists for) and a negative control
# (the same code with the flag off, or an ordinary neighbour of the shape).

import io  # noqa: E402
from contextlib import redirect_stderr, redirect_stdout  # noqa: E402

ESPO = leak_guard.GuardConfig(
    repo_holds="x", client_data_lives="y", enable_pii=True,
    enable_espocrm_detectors=True, enable_near_misses=True,
    pii_exempt_paths=frozenset({"tests/test_parser.py"}),
)
RID = "0123456789abcdef0"  # 17 hex characters


def _check(tmp_path, name, body, config=ESPO, near=None):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return leak_guard.check([str(f)], config, near_misses=near)


def test_record_id_beside_a_phone_is_blocked_and_bare_id_is_not(tmp_path):
    near = _check(tmp_path, "a.md", f"call 0400 111 222\nid {RID}\n")
    assert any("record id" in p for p in near)
    assert _check(tmp_path, "b.md", f"just an id {RID}\n") == []


def test_espocrm_detectors_are_off_unless_configured(tmp_path):
    off = leak_guard.GuardConfig(repo_holds="x", client_data_lives="y", enable_pii=True)
    body = f"x\n$m = @{{ id = '{RID}'; name = 'Some Person' }}\n"
    assert _check(tmp_path, "c.ps1", body, config=ESPO)
    assert _check(tmp_path, "c.ps1", body, config=off) == []


def test_id_name_literal_is_blocked_unless_it_names_another_entity_type(tmp_path):
    hit = f"$m = @{{ id = '{RID}'; name = 'Some Person' }}\n"
    ok = f"$m = @{{ id = '{RID}'; name = 'Doc'; type = 'CDocument' }}\n"
    assert any("name\" literal" in p for p in _check(tmp_path, "d.ps1", hit))
    assert _check(tmp_path, "e.ps1", ok) == []
    # `contentType` must not count as `type` (the exemption's own boundary)
    sneaky = f"$m = @{{ id = '{RID}'; name = 'Some Person'; contentType = 'x' }}\n"
    assert _check(tmp_path, "f.ps1", sneaky)


def test_json_merge_plan_shape_blocks_and_ordinary_record_does_not(tmp_path):
    plan = '[{"name": "Some Person", "survivor": "a", "dupes": ["b"]}]'
    rec = f'{{"name": "Some Person", "accountId": "{RID}", "id": "{RID}"}}'
    assert any("survivor/dupes" in p for p in _check(tmp_path, "p.json", plan))
    assert _check(tmp_path, "r.json", rec) == []


def test_populated_pindata_blocks_and_empty_does_not(tmp_path):
    full = '{"pinData": {"Node A": [{"json": {"name": "x", "n": 1}}]}}'
    probs = _check(tmp_path, "w.json", full)
    assert any("pinData" in p and "Node A" in p for p in probs)
    assert not any("x" == p for p in probs)
    assert _check(tmp_path, "w2.json", '{"pinData": {}}') == []


def test_near_misses_are_reported_not_blocking(tmp_path):
    near: list[str] = []
    probs = _check(tmp_path, "n.md", "ring +61 4111 2222\nand +44 7911 123456\n", near=near)
    assert probs == []
    assert any("mistyped AU" in n for n in near)
    assert any("international" in n for n in near)
    # a valid E.164 AU number is a blocking hit, not a near-miss
    near2: list[str] = []
    assert _check(tmp_path, "n2.md", "ring +61411122233\n", near=near2)
    assert near2 == []


def test_pii_exempt_path_skips_pii_but_never_secrets(tmp_path):
    body = 'x = "0400 111 222"\npassword = "hunter2hunter2"\n'
    probs = _check(tmp_path, "tests/test_parser.py", body)
    # path is absolute here, so exemption (an exact repo-relative path) applies
    # only when the caller passes it that way; assert both ways.
    assert any("password" in p for p in probs)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        probs = leak_guard.check(["tests/test_parser.py"], ESPO)
    finally:
        os.chdir(cwd)
    assert any("hardcoded password" in p for p in probs)
    assert not any("phone" in p for p in probs)


def test_run_all_refuses_when_the_tracked_list_is_empty():
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = leak_guard.run(["--all"], ESPO, tracked=lambda: [])
    assert rc == 2 and "--all" in err.getvalue()


def test_run_all_scans_what_tracked_returns(tmp_path):
    f = tmp_path / "ok.md"
    f.write_text("plain\n", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = leak_guard.run(["--all"], ESPO, tracked=lambda: [str(f)])
    assert rc == 0 and "1 file(s) checked" in out.getvalue()
    bad = tmp_path / "bad.md"
    bad.write_text("a@person.test.com\n", encoding="utf-8")
    with redirect_stdout(out), redirect_stderr(err):
        assert leak_guard.run(["--all"], ESPO, tracked=lambda: [str(bad)]) == 1
