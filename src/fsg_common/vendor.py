"""``python -m fsg_common.vendor --check`` (crm#2815 item 3).

Compare a repo's vendored copy of ``fsg_common`` with ``src/fsg_common`` at the
commit its pin file names. Replaces the three per-repo vendor scripts' check.

    python -m fsg_common.vendor --check --vendor-dir scripts/fsg_common --exclude sections/

Exit codes follow ``fsg_common.refused``: 0 identical, 1 drift (every file is
named), 2 not established (pin unreadable, commit or reference not reachable).
The reference is read from the git object store of a fsg-common checkout
(``--checkout``, else ``FSG_COMMON_PATH``, else ``../fsg-common``), never from a
working tree. Line endings are not drift.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

from fsg_common.refused import Refused, run_check

UPSTREAM_SUBDIR = "src/fsg_common"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def read_pin(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError as exc:
        raise Refused(f"cannot read pin {path}: {exc}") from exc
    if not _SHA.match(text):
        raise Refused(f"{path} must hold one full 40-character SHA; it holds {text!r}")
    return text


def _git(repo: str, *args: str, binary: bool = False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                              text=not binary, env=env)
    except OSError as exc:
        raise Refused(f"cannot run git: {exc}") from exc


def find_checkout(explicit: str | None, repo_root: str) -> str:
    cand = explicit or os.environ.get("FSG_COMMON_PATH") or \
        os.path.join(repo_root, "..", "fsg-common")
    cand = os.path.abspath(cand)
    if os.path.isdir(cand) and _git(cand, "rev-parse", "--git-dir").returncode == 0:
        return cand
    raise Refused(f"no fsg-common git checkout at {cand}")


def upstream_files(checkout: str, sha: str) -> dict[str, bytes]:
    if _git(checkout, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        raise Refused(f"commit {sha} is not in {checkout} (fetch it and retry)")
    listing = _git(checkout, "ls-tree", "-r", "--name-only", sha, UPSTREAM_SUBDIR)
    names = [n.strip() for n in listing.stdout.split("\n") if n.strip()]
    if listing.returncode != 0 or not names:
        raise Refused(f"{UPSTREAM_SUBDIR} is empty or absent at {sha}")
    files: dict[str, bytes] = {}
    for name in names:
        blob = _git(checkout, "show", f"{sha}:{name}", binary=True)
        if blob.returncode != 0:
            raise Refused(f"could not read {name} at {sha}")
        files[name[len(UPSTREAM_SUBDIR) + 1:]] = blob.stdout
    return files


def vendored_files(vendor_dir: str) -> dict[str, bytes]:
    if not os.path.isdir(vendor_dir):
        raise Refused(f"vendor directory {vendor_dir} does not exist")
    files: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(vendor_dir):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, vendor_dir).replace(os.sep, "/")
            with open(full, "rb") as fh:
                files[rel] = fh.read()
    return files


def _eol(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def compare(upstream: dict[str, bytes], ours: dict[str, bytes],
            exclude: tuple[str, ...] = ()) -> list[str]:
    """One line per file that differs; empty means identical."""
    if exclude:
        upstream = {k: v for k, v in upstream.items() if not k.startswith(exclude)}
    lines: list[str] = []
    for rel in sorted(set(upstream) | set(ours)):
        if rel not in ours:
            lines.append(f"missing from the vendored copy: {rel}")
        elif rel not in upstream:
            lines.append(f"not in upstream at the pin: {rel}")
        elif _eol(upstream[rel]) != _eol(ours[rel]):
            lines.append(f"differs from upstream at the pin: {rel}")
    return lines


def check(pin: str, vendor_dir: str, exclude: tuple[str, ...] = (),
          checkout: str | None = None, repo_root: str = ".") -> list[str]:
    sha = read_pin(pin)
    ours = vendored_files(vendor_dir)
    upstream = upstream_files(find_checkout(checkout, repo_root), sha)
    return compare(upstream, ours, exclude)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m fsg_common.vendor")
    ap.add_argument("--check", action="store_true", required=True,
                    help="compare the vendored copy with the pin; write nothing")
    ap.add_argument("--vendor-dir", required=True)
    ap.add_argument("--pin", default="fsg-common.pin")
    ap.add_argument("--exclude", action="append", default=[],
                    help="upstream path prefix not vendored, e.g. sections/")
    ap.add_argument("--checkout", default=None)
    args = ap.parse_args(argv)
    root = os.path.dirname(os.path.abspath(args.pin))
    return run_check(lambda: check(args.pin, args.vendor_dir, tuple(args.exclude),
                                   args.checkout, root))


if __name__ == "__main__":
    sys.exit(main())
