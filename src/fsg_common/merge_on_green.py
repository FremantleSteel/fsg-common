"""Merge a PR only if its checks are green, then prune.

The one shared implementation (crm#1719, 3 Oct 2026). It was
`fsg-estimating-crm/scripts/merge_on_green.py` only; each repo's
`scripts/merge_on_green.py` is now a thin wrapper calling `main()` here, so
every repo merges through the same gate. Stdlib only.

crm#1714. The coordinator merged a red PR (#1703) by chaining a checks read
and a merge, and spent many calls per PR on watch / read / merge / worktree
remove / branch -D / pull. This is one command that gates, merges and cleans up.

    python scripts/merge_on_green.py 1714 -R FremantleSteel/<repo>

Works for any FremantleSteel repo via -R. Never checks a branch out in a clone.

1. WAIT. Polls every 30 s (--interval) up to --timeout seconds. Superseded runs
   are ignored: a CANCELLED run, and older runs of a check name that has a
   newer one. A path-filtered check that never ran is ABSENT, not passed: it is
   never in the rollup, so the report says how many checks were actually seen,
   and a PR with NO usable check refuses (absent input must not answer) unless
   --allow-no-checks.
2. REFUSE (exit 1, plain reason, nothing merged) on: any FAILURE or TIMED_OUT
   (also ACTION_REQUIRED / STARTUP_FAILURE / ERROR); "Generated with" or
   "Co-Authored-By" in the body or first comment; body plus first comment of
   400 words or more; no closing keyword and no "No issue:" line (these three
   are fsg_common.pr_body.check, the same rules CI holds); mergeable not
   MERGEABLE; a draft; a PR that is not open.
3. MERGE: squash, --delete-branch, then confirm the PR reads MERGED.
4. CLEAN UP: find the local worktree (under C:\\Users\\dkagi) whose branch is the
   PR head, in the clone this repo maps to; refuse to remove a dirty one but
   still report the merge; otherwise remove it and delete the local branch;
   fast-forward the main clone only if it is on main and clean.

Exit codes: 0 merged and clean, 1 refused, 2 still pending at timeout,
3 merged but cleanup incomplete. A merged PR is always reported as merged.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import PureWindowsPath
from types import SimpleNamespace

from fsg_common import pr_body

OK, REFUSED, PENDING, INCOMPLETE = 0, 1, 2, 3
HOME = r"C:\Users\dkagi"
BAD = {"FAILURE", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
GOOD = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FIELDS = ("number,state,isDraft,mergeable,body,comments,headRefName,"
          "baseRefName,statusCheckRollup")


def run(cmd: list[str], cwd: str | None = None) -> SimpleNamespace:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return SimpleNamespace(rc=p.returncode, out=p.stdout, err=p.stderr)


def summarise_checks(rollup):
    """(failed, pending, passed, superseded) check names, superseded runs dropped."""
    latest: dict[str, dict] = {}
    superseded: list[str] = []

    def stamp(c):
        return c.get("startedAt") or c.get("completedAt") or ""

    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        if c.get("conclusion") == "CANCELLED":
            superseded.append(name)
            continue
        if name in latest:
            superseded.append(name)
            if stamp(c) <= stamp(latest[name]):
                continue
        latest[name] = c
    failed, pending, passed = [], [], []
    for name, c in sorted(latest.items()):
        if "state" in c and "status" not in c:      # legacy StatusContext
            done = c["state"] not in ("PENDING", "EXPECTED")
            concl = c["state"] if done else None
        else:
            concl, done = c.get("conclusion"), c.get("status") == "COMPLETED"
        if concl in BAD:
            failed.append(f"{name} ({concl})")
        elif not done or concl is None:
            pending.append(name)
        elif concl in GOOD:
            passed.append(name)
        else:
            failed.append(f"{name} ({concl})")      # unknown conclusion never passes
    return failed, pending, passed, superseded


def _under_home(path: str) -> bool:
    a = [p.casefold() for p in PureWindowsPath(path).parts]
    h = [p.casefold() for p in PureWindowsPath(HOME).parts]
    return a[:len(h)] == h and len(a) > len(h)


def worktrees(porcelain: str) -> list[dict]:
    out, cur = [], {}
    for line in porcelain.splitlines() + [""]:
        if not line.strip():
            if cur:
                out.append(cur)
            cur = {}
        elif " " in line:
            k, v = line.split(" ", 1)
            cur[k] = v
        else:
            cur[line] = True
    return out


def cleanup(pr: dict, clone: str, git) -> tuple[list[str], bool]:
    """Returns (report lines, complete). Never raises the merge away."""
    notes, complete = [], True
    branch = pr["headRefName"]

    def g(*a, cwd=clone):
        return git(["git", "-C", cwd, *a])

    r = g("worktree", "list", "--porcelain")
    if r.rc != 0:
        return [f"cleanup: cannot list worktrees in {clone}: {r.err.strip()}"], False
    wts = worktrees(r.out)
    mine = [w for w in wts if w.get("branch") == f"refs/heads/{branch}"]
    main_path = wts[0]["worktree"] if wts else clone
    for w in mine:
        path = w["worktree"]
        if PureWindowsPath(path) == PureWindowsPath(main_path):
            notes.append(f"cleanup: branch {branch} is checked out in the main clone; not removed")
            complete = False
        elif not _under_home(path):
            notes.append(f"cleanup: worktree {path} is outside {HOME}; not touched")
            complete = False
        else:
            st = g("status", "--porcelain", cwd=path)
            if st.rc != 0:
                notes.append(f"cleanup: cannot read status of {path}: "
                             f"{st.err.strip()}; not removed")
                complete = False
            elif st.out.strip():
                notes.append(f"cleanup: worktree {path} is DIRTY; not removed. "
                             "Commit or discard there, then remove it by hand.")
                complete = False
            else:
                rm = g("worktree", "remove", path)
                if rm.rc == 0:
                    notes.append(f"cleanup: removed worktree {path}")
                else:
                    notes.append(f"cleanup: worktree remove failed: {rm.err.strip()}")
                    complete = False
    after = g("worktree", "list", "--porcelain")
    still = after.rc != 0 or any(w.get("branch") == f"refs/heads/{branch}"
                                 for w in worktrees(after.out))
    if still:
        notes.append(f"cleanup: local branch {branch} kept (still checked out)")
    elif g("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").rc == 0:
        d = g("branch", "-D", branch)
        if d.rc == 0:
            notes.append(f"cleanup: deleted local branch {branch}")
        else:
            notes.append(f"cleanup: branch delete failed: {d.err.strip()}")
            complete = False
    else:
        notes.append(f"cleanup: no local branch {branch} to delete")
    cur = g("rev-parse", "--abbrev-ref", "HEAD")
    base = pr.get("baseRefName") or "main"
    if cur.rc != 0:
        notes.append("cleanup: cannot read the main clone's branch; not fast-forwarded")
        complete = False
    elif cur.out.strip() != base:
        notes.append(f"cleanup: main clone is on {cur.out.strip()}, not {base}; not fast-forwarded")
    else:
        st = g("status", "--porcelain")
        if st.rc != 0:
            notes.append("cleanup: cannot read the main clone's status; not fast-forwarded")
            complete = False
        elif st.out.strip():
            notes.append("cleanup: main clone is dirty; not fast-forwarded")
        else:
            f = g("fetch", "origin", base)
            mg = g("merge", "--ff-only", f"origin/{base}") if f.rc == 0 else f
            if mg.rc == 0:
                notes.append(f"cleanup: fast-forwarded {clone} to origin/{base}")
            else:
                notes.append(f"cleanup: fast-forward failed: {mg.err.strip()}")
                complete = False
    return notes, complete


def main(argv=None, gh=run, git=run, sleep=time.sleep, clock=time.monotonic,
         out=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pr", type=int)
    ap.add_argument("-R", "--repo", required=True,
                    help="owner/name, e.g. FremantleSteel/fsg-estimating-crm")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--timeout", type=float, default=1800, help="seconds to wait for checks")
    ap.add_argument("--clone", help=f"local clone of the repo (default {HOME}\\<repo name>)")
    ap.add_argument("--allow-no-checks", action="store_true")
    a = ap.parse_args(argv)
    clone = a.clone or str(PureWindowsPath(HOME) / a.repo.split("/")[-1])

    def refuse(reason: str) -> int:
        out(f"REFUSED #{a.pr}: {reason}")
        return REFUSED

    deadline = clock() + a.timeout
    while True:
        r = gh(["gh", "pr", "view", str(a.pr), "-R", a.repo, "--json", FIELDS])
        if r.rc != 0:
            return refuse(f"cannot read the PR: {r.err.strip()}")
        pr = json.loads(r.out)
        if pr["state"] != "OPEN":
            return refuse(f"the PR is {pr['state']}, not OPEN")
        if pr["isDraft"]:
            return refuse("the PR is a draft")
        comments = pr.get("comments") or []
        first = comments[0].get("body") if comments else None
        problems = pr_body.check(pr.get("body"), first, None)
        if problems:
            return refuse("; ".join(problems))
        failed, pending, passed, superseded = summarise_checks(pr.get("statusCheckRollup"))
        if failed:
            return refuse("checks failed: " + ", ".join(failed))
        if not pending and not passed and not a.allow_no_checks:
            return refuse("no check reported at all (a path-filtered check that never ran "
                          "is absent, not passed); pass --allow-no-checks to accept that")
        if not pending and pr["mergeable"] != "UNKNOWN":
            if pr["mergeable"] != "MERGEABLE":
                return refuse(f"mergeable is {pr['mergeable']}, not MERGEABLE")
            break
        if clock() >= deadline:
            out(f"PENDING #{a.pr}: still waiting at timeout; "
                f"checks pending: {', '.join(pending) or 'none'}; mergeable {pr['mergeable']}")
            return PENDING
        out(f"waiting: {len(pending)} pending ({', '.join(pending) or 'mergeability'}), "
            f"{len(passed)} passed")
        sleep(a.interval)

    out(f"checks green: {len(passed)} passed, {len(superseded)} superseded run(s) ignored; "
        "checks that never ran are absent from this count")
    mg = gh(["gh", "pr", "merge", str(a.pr), "-R", a.repo, "--squash", "--delete-branch"])
    v = gh(["gh", "pr", "view", str(a.pr), "-R", a.repo, "--json", "state"])
    state = json.loads(v.out)["state"] if v.rc == 0 else "UNKNOWN"
    if state != "MERGED":
        return refuse(f"merge did not complete (state {state}): {(mg.err or mg.out).strip()}")
    out(f"MERGED #{a.pr} into {pr.get('baseRefName', 'main')}")
    notes, complete = cleanup(pr, clone, git)
    for n in notes:
        out(n)
    return OK if complete else INCOMPLETE


if __name__ == "__main__":
    sys.exit(main())
