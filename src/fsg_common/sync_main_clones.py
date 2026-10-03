"""Fast-forward the five FSG main clones to origin/main, and nothing else.

crm#1964. On 3 Oct 2026 the `fsg-common` main clone sat three merged PRs
behind origin. The tender-review venv and the global Python import
`fsg_common` from that clone as an editable install, so tender-review's
pre-commit hook regenerated `docs/COMMANDS.md` with the old generator during a
merge commit, and a green PR (tr#865) went red. Nothing kept the clones
current and nothing said they were behind.

    python scripts/sync_main_clones.py            # fast-forward each clone
    python scripts/sync_main_clones.py --check    # report only, change nothing
    python scripts/sync_main_clones.py --root DIR # clones live in DIR

What it will and will not do, per clone:

  * fetch `origin main` (this only moves the remote-tracking ref);
  * fast-forward `main` with `git merge --ff-only`, and only when the clone is
    on `main` with no tracked change. Untracked files are left alone; git
    itself refuses a fast-forward that would overwrite one.
  * never reset, stash, rebase, check out or delete anything. A dirty tree, a
    branch other than `main`, or a `main` that has diverged from origin is
    REFUSED and named, for a person to sort out. Those clones are where David
    runs paste cards, and a peer session may be mid-edit in one.

Each clone gets one line: CURRENT, UPDATED (old..new), BEHIND (in --check),
REFUSED (with the reason), ABSENT, or NOT ESTABLISHED (fetch failed, so its
state is unknown -- never reported as current). Exit 0 when every present
clone is current or updated, 1 when any is refused or behind under --check,
2 when any could not be established.

The default root is the directory holding the main clone of the repo this is
run from (worked out from `git rev-parse --git-common-dir`, so a worktree
anywhere finds the same clones).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPOS = (
    "fsg-estimating-crm",
    "fsg-estimating-tools",
    "fsg-tender-review",
    "fsg-bluebeam-steel-standards",
    "fsg-common",
)

Git = Callable[..., "subprocess.CompletedProcess[str]"]


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                          text=True, timeout=300)


def default_root(start: Path | None = None) -> Path | None:
    """The folder that holds the main clone of the repo `start` belongs to."""
    result = _git(start or Path.cwd(), "rev-parse", "--path-format=absolute",
                  "--git-common-dir")
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).parent.parent


def sync_one(path: Path, check: bool, git: Git = _git) -> tuple[str, str]:
    """(state, detail) for one clone. Changes nothing unless it can fast-forward."""
    if not path.exists():
        return "ABSENT", str(path)
    if git(path, "rev-parse", "--git-dir").returncode != 0:
        return "REFUSED", "not a git repository"
    branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if branch != "main":
        return "REFUSED", f"on {branch or 'a detached HEAD'}, not main"
    status = git(path, "status", "--porcelain", "--untracked-files=no").stdout
    if status.strip():
        changed = len(status.strip().splitlines())
        return "REFUSED", f"{changed} tracked file(s) changed; commit or discard them by hand"
    if git(path, "fetch", "--quiet", "origin", "main").returncode != 0:
        return "NOT ESTABLISHED", "git fetch origin main failed"
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    remote = git(path, "rev-parse", "refs/remotes/origin/main").stdout.strip()
    if not head or not remote:
        return "NOT ESTABLISHED", "could not read HEAD or origin/main"
    if head == remote:
        return "CURRENT", head[:12]
    if git(path, "merge-base", "--is-ancestor", head, remote).returncode != 0:
        return "REFUSED", f"main {head[:12]} has diverged from origin/main {remote[:12]}"
    if check:
        return "BEHIND", f"{head[:12]}..{remote[:12]}"
    merged = git(path, "merge", "--ff-only", "--quiet", remote)
    if merged.returncode != 0:
        why = (merged.stderr or merged.stdout).strip().splitlines()
        return "REFUSED", f"fast-forward refused: {why[-1] if why else 'no reason given'}"
    return "UPDATED", f"{head[:12]}..{remote[:12]}"


def main(argv: list[str] | None = None, script: str | Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fast-forward the FSG main clones.")
    ap.add_argument("--root", type=Path, help="folder holding the clones")
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--repo", action="append", help="limit to these repo names")
    args = ap.parse_args(argv)
    root = args.root or default_root(Path(script).resolve().parent if script else None)
    if root is None:
        print("NOT ESTABLISHED: not inside a git repository and no --root given")
        return 2
    worst = 0
    for name in args.repo or REPOS:
        state, detail = sync_one(root / name, args.check)
        print(f"{state:<16} {name:<30} {detail}")
        if state == "NOT ESTABLISHED":
            worst = 2
        elif state in ("REFUSED", "BEHIND") and worst < 2:
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
