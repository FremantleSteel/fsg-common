"""This repo's own leak guard, `scripts/check_no_client_data.py` (crm#2813).

The planted fixtures are built at run time in a temporary folder, so this
file holds no real file name, key or name. The term used
here is invented and is not anyone's name.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_no_client_data.py"

_spec = importlib.util.spec_from_file_location("check_no_client_data", SCRIPT)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

# An invented client name. Two words, so the space-to-separator rule is used.
TERM = "Zebrafinch " + "Holdings"
# A password-shaped value with none of the placeholder words the shared
# guard deliberately lets through.
KEY_VALUE = "Tr0ub4dor" + "-and-3-horses"
# Built in pieces so this file never holds the assignment itself.
KEY_LINE = "pass" + 'word = "' + KEY_VALUE + '"\n'


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _run_hook(repo: Path, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    """The script as the commit hook runs it: staged files, in a real repo."""
    env = {k: v for k, v in os.environ.items()
           if k not in (guard.TERMS_FILE_ENV, guard.TERMS_TEXT_ENV)}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, env=env,
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    return r


@pytest.fixture
def terms_file(tmp_path: Path) -> Path:
    f = tmp_path / "private" / "terms.txt"
    f.parent.mkdir()
    f.write_text("# private list\n\n" + TERM + "\n", encoding="utf-8")
    return f


# --- the planted fixture is refused, and a clean control passes ---------------

def test_planted_client_file_name_and_key_are_refused(repo, terms_file):
    (repo / "notes").mkdir()
    planted = repo / "notes" / (TERM.replace(" ", "_") + "_tender_scope.txt")
    planted.write_text("scope notes\n", encoding="utf-8")
    (repo / "settings.py").write_text(KEY_LINE, encoding="utf-8")
    (repo / "client_drawing.pdf").write_bytes(b"%PDF-1.4\n")
    _git(repo, "add", ".")

    out = _run_hook(repo, {guard.TERMS_FILE_ENV: str(terms_file)})

    assert out.returncode == 1, out.stdout + out.stderr
    assert "holds private term #1" in out.stderr
    assert "settings.py:1: a hardcoded password" in out.stderr
    assert "client_drawing.pdf" in out.stderr
    # The term itself never reaches the log, not even inside the path.
    assert "zebrafinch" not in (out.stdout + out.stderr).lower()
    assert "notes/***_tender_scope.txt" in out.stderr


def test_clean_control_passes(repo, terms_file):
    (repo / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")

    out = _run_hook(repo, {guard.TERMS_FILE_ENV: str(terms_file)})

    assert out.returncode == 0, out.stdout + out.stderr
    assert "against 1 private term(s), none found" in out.stdout


def test_terms_from_the_ci_variable_also_refuse(repo):
    (repo / "readme.md").write_text(f"Quote for {TERM.upper()}\n",
                                    encoding="utf-8")
    _git(repo, "add", ".")

    out = _run_hook(repo, {guard.TERMS_TEXT_ENV: TERM + "\n"})

    assert out.returncode == 1
    assert "readme.md:1: holds private term #1" in out.stderr


# --- an absent input must not answer ----------------------------------------

def test_no_term_list_refuses_even_on_clean_files(repo):
    (repo / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")

    out = _run_hook(repo, {})

    assert out.returncode == 2
    assert "REFUSED" in out.stderr
    # The shared half still ran and said so; the refusal does not hide it.
    assert "nothing blocked" in out.stdout


def test_unreadable_term_file_refuses(repo, tmp_path):
    (repo / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")

    out = _run_hook(repo, {guard.TERMS_FILE_ENV: str(tmp_path / "missing.txt")})

    assert out.returncode == 2
    assert "could not be read" in out.stderr


@pytest.mark.parametrize("text, why", [
    ("# comments only\n\n", "holds no terms"),
    ("ab\n", "shorter than 3"),
])
def test_empty_or_too_short_list_refuses(text, why):
    with pytest.raises(guard.TermsUnavailable, match=why):
        guard.load_terms({guard.TERMS_TEXT_ENV: text})


def test_term_file_inside_the_repo_refuses(tmp_path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    inside = root / "docs" / "terms.txt"
    inside.write_text(TERM + "\n", encoding="utf-8")
    with pytest.raises(guard.TermsUnavailable, match="inside this repo"):
        guard.load_terms({guard.TERMS_FILE_ENV: str(inside)}, repo_root=root)


def test_file_variable_wins_over_text_variable(tmp_path, terms_file):
    terms = guard.load_terms({guard.TERMS_FILE_ENV: str(terms_file),
                              guard.TERMS_TEXT_ENV: "other words\n"},
                             repo_root=tmp_path / "elsewhere")
    assert terms == [TERM]


# --- matching ---------------------------------------------------------------

@pytest.mark.parametrize("text, found", [
    # Each sample is split so this file never holds the term whole.
    ("zebrafinch" " holdings", True),
    ("ZEBRAFINCH" "-HOLDINGS", True),
    ("Zebrafinch" ".Holdings", True),
    ("Zebrafinch" " Holdingsmore", False),   # a longer word is not the term
    ("Zebrafinch", False),                # one word of two is not the term
])
def test_term_matches_whole_words_any_case(tmp_path, text, found):
    f = tmp_path / "sample.txt"
    f.write_text(text + "\n", encoding="utf-8")
    hits = guard.term_problems([str(f)], [TERM])
    assert bool(hits) is found


def test_the_skip_covers_only_the_engine_tests(repo, terms_file):
    """The one content-scan exemption is that exact path: the same password
    one folder over is still refused."""
    (repo / "tests").mkdir()
    (repo / "tests" / "test_other.py").write_text(KEY_LINE, encoding="utf-8")
    _git(repo, "add", ".")

    out = _run_hook(repo, {guard.TERMS_FILE_ENV: str(terms_file)})

    assert out.returncode == 1
    assert "tests/test_other.py:1: a hardcoded password" in out.stderr


def test_this_repo_is_clean_against_the_invented_term():
    """The whole tracked tree, through the real script, with a term no file
    holds: the shared half and the term half must both pass here, or the CI
    step would be red on main."""
    env = {k: v for k, v in os.environ.items()
           if k not in (guard.TERMS_FILE_ENV, guard.TERMS_TEXT_ENV)}
    env[guard.TERMS_TEXT_ENV] = "Quokka " + "Lumber Pty\n"
    out = subprocess.run([sys.executable, str(SCRIPT), "--all"], cwd=REPO,
                         env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


# --- the term never reaches any output (checker C1035, crm#2813) -------------

def _no_term_anywhere(out: subprocess.CompletedProcess) -> None:
    text = (out.stdout + out.stderr).lower()
    for word in TERM.lower().split():
        assert word not in text, f"{word!r} printed:\n{out.stdout}{out.stderr}"


def test_term_in_a_blocked_file_name_and_content_is_never_printed(repo, terms_file):
    """The shared half prints raw paths; a .pdf named after a client must be
    masked there too, and a content hit must not echo the line."""
    (repo / "d").mkdir()
    stem = TERM.replace(" ", "_")
    (repo / "d" / (stem + "_drawing.pdf")).write_bytes(b"%PDF-1.4\n")
    (repo / "d" / (stem + "_notes.txt")).write_text(
        f"Scope for {TERM}\n", encoding="utf-8")
    _git(repo, "add", ".")

    out = _run_hook(repo, {guard.TERMS_FILE_ENV: str(terms_file)})

    assert out.returncode == 1
    assert "d/***_drawing.pdf" in out.stderr
    assert "d/***_notes.txt:1: holds private term #1" in out.stderr
    _no_term_anywhere(out)


def test_commit_message_file_is_checked(repo, terms_file, tmp_path):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(f"Quote work for {TERM}\n", encoding="utf-8")
    env = {guard.TERMS_FILE_ENV: str(terms_file)}
    out = subprocess.run([sys.executable, str(SCRIPT), "--message-file", str(msg)],
                         cwd=repo, env={**os.environ, **env},
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "commit message (new):1: holds private term #1" in out.stderr
    _no_term_anywhere(out)

    msg.write_text("Tidy the resolver\n", encoding="utf-8")       # control
    out = subprocess.run([sys.executable, str(SCRIPT), "--message-file", str(msg)],
                         cwd=repo, env={**os.environ, **env},
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_range_checks_commit_messages(repo, terms_file):
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "--allow-empty", "-m", "base")
    (repo / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", f"Work for {TERM}")
    env = {k: v for k, v in os.environ.items() if k != guard.TERMS_TEXT_ENV}
    env[guard.TERMS_FILE_ENV] = str(terms_file)
    out = subprocess.run([sys.executable, str(SCRIPT), "--range", "HEAD~1..HEAD"],
                         cwd=repo, env=env, capture_output=True, text=True)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "holds private term #1" in out.stderr
    _no_term_anywhere(out)
