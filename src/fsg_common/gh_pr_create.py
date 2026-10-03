"""Open a pull request with `gh pr create`, after checking the body.

The one shared implementation (crm#1719, 3 Oct 2026). It was
`fsg-estimating-crm/scripts/gh_pr_create.py` only (crm#1717); the other repos
had nothing, and their PR-body gate failed 13-23% of runs against crm's 1%,
because only crm checked the body before the PR existed. Each repo's
`scripts/gh_pr_create.py` is now a thin wrapper calling `main()` here.

Lanes kept adding "Generated with" and "Co-Authored-By" lines to PR bodies,
which David's rule forbids and `check_pr_body` refuses only after the PR
exists. This fixes the body first and refuses before creating.

    python scripts/gh_pr_create.py -R FremantleSteel/<repo> \
        --body-file pr_body.md --title "crm#N: what changed" --base main

  * The body comes from `--body` or `--body-file` (exactly one).
  * Any line carrying "Generated with" or "Co-Authored-By" is removed, and the
    removal is printed, never silent.
  * The result is judged by `fsg_common.pr_body.check` (imported, not copied):
    a closing keyword or a `No issue:` line, and under 400 words. On a problem
    it exits 1 and does not call gh.
  * Every other argument passes through to `gh pr create` unchanged; the
    cleaned body goes in as `--body-file`. `-R` is required, as the lane
    rules say, because gh otherwise resolves the repo from the cwd.

Exit 0 created, 1 refused by the body check, 2 bad usage or unreadable input.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable

from fsg_common import pr_body

_ATTRIBUTION = re.compile("|".join(p.pattern for _, p in pr_body.FORBIDDEN_ATTRIBUTION),
                          re.IGNORECASE)


def strip_attribution(body: str) -> tuple[str, list[str]]:
    """The body without attribution lines, and the lines removed."""
    kept: list[str] = []
    removed: list[str] = []
    for line in body.splitlines():
        (removed if _ATTRIBUTION.search(line) else kept).append(line)
    return "\n".join(kept).rstrip() + "\n", removed


def run_gh(args: list[str]) -> int:
    """The one place gh is started; tests replace it (or pass `run_gh=` to main)."""
    return subprocess.run(["gh", *args], check=False).returncode


def main(argv: list[str] | None = None,
         run_gh: Callable[[list[str]], int] | None = None) -> int:
    gh = run_gh or globals()["run_gh"]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--body")
    ap.add_argument("--body-file", "-F", dest="body_file")
    ap.add_argument("-R", "--repo", dest="repo")
    args, rest = ap.parse_known_args(argv)

    if not args.repo:
        print("gh_pr_create: -R owner/repo is required "
              "(gh resolves the repo from the cwd otherwise)", file=sys.stderr)
        return 2
    if (args.body is None) == (args.body_file is None):
        print("gh_pr_create: give exactly one of --body or --body-file", file=sys.stderr)
        return 2
    if args.body_file is not None:
        try:
            with open(args.body_file, encoding="utf-8") as fh:
                body = fh.read()
        except OSError as exc:
            print(f"gh_pr_create: cannot read the body file -- {exc}", file=sys.stderr)
            return 2
    else:
        body = args.body

    body, removed = strip_attribution(body)
    for line in removed:
        print(f"gh_pr_create: removed attribution line: {line.strip()}")
    problems = pr_body.check(body, None, None)
    if problems:
        for p in problems:
            print(f"gh_pr_create: REFUSED -- {p}", file=sys.stderr)
        return 1

    fd, path = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        return gh(["pr", "create", "-R", args.repo, "--body-file", path, *rest])
    finally:
        os.unlink(path)


if __name__ == "__main__":
    sys.exit(main())
