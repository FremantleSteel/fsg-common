"""Refuse to commit a client document, a credential or a private name.

This repo is public, so a leak here is published the moment it is pushed.
It runs two checks (crm#2813):

1. **The shared leak guard** (`fsg_common.leak_guard`), the same engine the
   four private repos wrap: client file types, credential files and secret
   patterns.
2. **A private term list.** Client, project and person names, and anything
   else that must not appear here. The list is never committed: it is read
   from one of two environment variables.

   - `FSG_LEAK_TERMS_FILE`: the path to a text file outside this repo, one
     term per line. Blank lines and lines starting with `#` are ignored.
   - `FSG_LEAK_TERMS`: the terms themselves, one per line. This is how CI
     gets them, from a repository secret of the same name.

   Commit messages are checked too: the `commit-msg` hook passes
   `--message-file`, and `--range` reads every message in the range.
   A match is reported by term number, never by the term, and a path that
   holds a term is printed with the term masked (the shared check's output
   too), because a CI log on a public repo is public too.

**An absent input must not answer.** No term list, an unreadable file, a
file inside this repo, an empty list or a term under three characters is
a REFUSAL (exit 2), never a pass. The shared check still runs and reports
first, so a refusal never hides what it found.

    python scripts/check_no_client_data.py              # staged files (the hook)
    python scripts/check_no_client_data.py --range A..B # a commit range (CI)
    python scripts/check_no_client_data.py --all        # every tracked file

Exit 0 clean, 1 blocked, 2 refused (something could not be checked).
"""
# commands-index-group: repo-hygiene

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import subprocess
import sys
from pathlib import Path

# This checkout's own engine, never another installed copy: the guard that
# runs here must be the one this commit ships.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fsg_common import leak_guard  # noqa: E402

TERMS_FILE_ENV = "FSG_LEAK_TERMS_FILE"
TERMS_TEXT_ENV = "FSG_LEAK_TERMS"
MIN_TERM_LENGTH = 3

GUARD_CONFIG = leak_guard.GuardConfig(
    repo_holds="This repo is PUBLIC. It holds shared code and the section "
               "library only.",
    client_data_lives="Client documents, names and credentials stay in the "
                      "private repos and on the office share, never here.",
    # The shared engine's own tests are password samples by design, the same
    # reason the engine skips its own source. Exact path, secret scan only:
    # the private-term check below still reads this file.
    extra_content_scan_skip=(re.compile(r"^tests/test_leak_guard\.py$"),),
)


class TermsUnavailable(Exception):
    """The term list could not be established. The message names why, and
    never quotes a term."""


def _repo_root() -> Path | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out.stdout.strip()).resolve()


def _parse_terms(text: str, source: str) -> list[str]:
    terms: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        if len(term) < MIN_TERM_LENGTH:
            raise TermsUnavailable(
                f"{source} line {lineno} holds a term shorter than "
                f"{MIN_TERM_LENGTH} characters; it would match almost "
                f"anything. Lengthen or remove it")
        terms.append(term)
    if not terms:
        raise TermsUnavailable(
            f"{source} holds no terms, so nothing could be checked. An empty "
            f"list is not a clean list")
    return terms


def load_terms(environ: dict[str, str] | None = None,
               repo_root: Path | None = None) -> list[str]:
    """The private terms, or `TermsUnavailable` saying why not."""
    env = os.environ if environ is None else environ
    path_value = env.get(TERMS_FILE_ENV, "").strip()
    text_value = env.get(TERMS_TEXT_ENV, "")
    if path_value:
        path = Path(path_value).expanduser().resolve()
        root = repo_root if repo_root is not None else _repo_root()
        if root is not None and (path == root or root in path.parents):
            raise TermsUnavailable(
                f"{TERMS_FILE_ENV} points inside this repo, where the list "
                f"could be committed. Keep it outside the repo")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise TermsUnavailable(
                f"{TERMS_FILE_ENV} is set but the file could not be read "
                f"({type(exc).__name__})") from exc
        return _parse_terms(text, TERMS_FILE_ENV)
    if text_value.strip():
        return _parse_terms(text_value, TERMS_TEXT_ENV)
    raise TermsUnavailable(
        f"neither {TERMS_FILE_ENV} nor {TERMS_TEXT_ENV} is set, so the "
        f"private-term check did not run")


def _term_patterns(terms: list[str]) -> list[re.Pattern]:
    # A term matches as a whole word, case-insensitive: "Acme" finds
    # "ACME_tender" and "acme-quote" but not "acmeist". Spaces in a term
    # also match `_`, `-` and `.`, the way a name turns into a file name.
    patterns = []
    for term in terms:
        body = r"[\s_.\-]+".join(re.escape(part) for part in term.split())
        patterns.append(re.compile(
            rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.I))
    return patterns


def _mask(text: str, patterns: list[re.Pattern]) -> str:
    for rx in patterns:
        text = rx.sub("***", text)
    return text


def term_problems(paths: list[str], terms: list[str],
                  path_sources: dict[str, str] | None = None) -> list[str]:
    """One line per path or content hit, naming the term by number only."""
    patterns = _term_patterns(terms)
    problems: list[str] = []
    for path in paths:
        norm = path.replace("\\", "/")
        shown = _mask(norm, patterns)
        for number, rx in enumerate(patterns, start=1):
            if rx.search(norm):
                problems.append(
                    f"{shown}: the file name holds private term #{number}")
        ext = os.path.splitext(norm)[1].lower()
        if ext not in GUARD_CONFIG.scan_extensions and not leak_guard._looks_like_text(path):
            continue
        body, read_error = leak_guard._read_body(path, path_sources)
        if body is None:
            # The shared check above reports an unreadable file as a gap
            # already; say so here too, so this half never reads as clean.
            problems.append(
                f"{shown}: could not be read, so it was NOT checked for "
                f"private terms ({read_error or 'FileNotFoundError'})")
            continue
        for number, rx in enumerate(patterns, start=1):
            hit = rx.search(body)
            if hit:
                line = body[:hit.start()].count("\n") + 1
                problems.append(
                    f"{shown}:{line}: holds private term #{number}")
    return problems


def _selected_paths(argv: list[str]) -> tuple[list[str], dict[str, str] | None]:
    """The same population the shared guard chose for the same flags."""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--range", dest="rev_range")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--all", action="store_true")
    args, _ = ap.parse_known_args(argv)
    if args.files is not None:
        return list(args.files), None
    if args.rev_range:
        return (leak_guard.range_files(args.rev_range),
                leak_guard._range_path_sources(args.rev_range))
    if args.all:
        return leak_guard.tracked_files(), None
    return leak_guard.staged_files(), None


def check(paths: list[str], read_content: bool = True,
          path_sources: dict[str, str] | None = None) -> list[str]:
    return leak_guard.check(paths, GUARD_CONFIG, path_sources=path_sources,
                            read_content=read_content)


def _run_shared_masked(argv: list[str], patterns: list[re.Pattern]) -> int:
    """The shared guard, with every line it prints masked: it prints raw
    paths, and a file name can hold a private term."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = leak_guard.run(argv, GUARD_CONFIG)
    sys.stdout.write(_mask(out.getvalue(), patterns))
    sys.stderr.write(_mask(err.getvalue(), patterns))
    return rc


def message_problems(messages: list[tuple[str, str]],
                     patterns: list[re.Pattern]) -> list[str]:
    """`(label, text)` per commit message; hits named by term number only."""
    problems = []
    for label, text in messages:
        for number, rx in enumerate(patterns, start=1):
            hit = rx.search(text)
            if hit:
                line = text[:hit.start()].count("\n") + 1
                problems.append(f"commit message {label}:{line}: holds "
                                f"private term #{number}")
    return problems


def _range_messages(rev_range: str) -> list[tuple[str, str]]:
    out = subprocess.run(["git", "log", "--format=%H%x00%B%x01", rev_range],
                         capture_output=True, text=True, encoding="utf-8",
                         check=True).stdout
    messages = []
    for chunk in out.split("\x01"):
        if "\x00" in chunk:
            sha, body = chunk.split("\x00", 1)
            messages.append((sha.strip()[:12], body))
    return messages


def _refuse_no_terms(exc: Exception) -> None:
    print(f"REFUSED. Private-term check: {exc}.", file=sys.stderr)
    print(f"  Set {TERMS_FILE_ENV} to a term file outside this repo, or "
          f"{TERMS_TEXT_ENV} to the terms (CI reads a repository secret).",
          file=sys.stderr)


def _report(problems: list[str], what: str) -> None:
    print(f"BLOCKED. A private term would be published in this public repo "
          f"({what}).", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    print("\nTerms are named by number in the term list, never printed here.",
          file=sys.stderr)


def check_message_file(path: str) -> int:
    """The commit-msg hook: the message about to be committed."""
    try:
        terms = load_terms()
        text = Path(path).read_text(encoding="utf-8")
    except (TermsUnavailable, OSError) as exc:
        _refuse_no_terms(exc)
        return 2
    problems = message_problems([("(new)", text)], _term_patterns(terms))
    if problems:
        _report(problems, "commit message")
        return 1
    print(f"ok -- commit message checked against {len(terms)} private term(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--message-file" in argv:
        i = argv.index("--message-file")
        if i + 1 >= len(argv):
            print("REFUSED. --message-file needs a path.", file=sys.stderr)
            return 2
        return check_message_file(argv[i + 1])
    if "-h" in argv or "--help" in argv:
        return leak_guard.run(argv, GUARD_CONFIG)

    try:
        terms = load_terms()
    except TermsUnavailable as exc:
        # No terms, so nothing to mask with: the shared half prints as is.
        shared_rc = leak_guard.run(argv, GUARD_CONFIG)
        _refuse_no_terms(exc)
        return max(shared_rc, 2)
    patterns = _term_patterns(terms)
    shared_rc = _run_shared_masked(argv, patterns)

    rev_range = argv[argv.index("--range") + 1] if "--range" in argv else None
    if rev_range:
        try:
            msg_problems = message_problems(_range_messages(rev_range), patterns)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"REFUSED. Commit messages in {rev_range} could not be read "
                  f"({type(exc).__name__}).", file=sys.stderr)
            return max(shared_rc, 2)
        if msg_problems:
            _report(msg_problems, "commit messages")
            shared_rc = max(shared_rc, 1)
        else:
            print("ok -- commit messages in the range hold no private term")

    try:
        paths, path_sources = _selected_paths(argv)
    except leak_guard.IndexUnreadable as exc:
        print(f"REFUSED. Private-term check: the staged files could not be "
              f"read ({exc}).", file=sys.stderr)
        return max(shared_rc, 2)
    if not paths:
        # The shared guard has already said whether an empty selection is
        # fine (nothing staged) or a refusal (a range that selected nothing).
        print("private terms -- no files selected, so nothing was checked")
        return shared_rc

    problems = term_problems(paths, terms, path_sources)
    if not problems:
        print(f"ok -- {len(paths)} file(s) checked against {len(terms)} "
              f"private term(s), none found")
        return shared_rc
    _report(problems, "files")
    return max(shared_rc, 1)


if __name__ == "__main__":
    raise SystemExit(main())
