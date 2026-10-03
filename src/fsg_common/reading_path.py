"""The compulsory reading path stays under 30,500 words -- crm#557, crm#635.

## What this is, and why it lives here rather than in five repos

David's decision on crm#557, 11 Sep 2026: cap the compulsory reading path --
one `CLAUDE.md` per FSG repo, plus (at the time) `fsg-tender-review/docs/
README.md`, which that repo's own `CLAUDE.md` named "Start here" -- the
words a session pays for on every single run, before any pointer sends it
anywhere else. Raised from 30,000 to 30,500 on crm#635, 18 Sep 2026.

**Narrowed, not raised again, 25 Sep 2026 (crm#1009).** Headroom fell to
about fifteen words twice in three days -- 30,495/30,500 on 23 Sep, then
30,490/30,500 on 24 Sep -- each time from one lane's ordinary edit to a
`CLAUDE.md` landing in an unrelated repo's PR. David considered raising the
limit again and running another trim pass, and rejected both: "narrow what
counts as compulsory" instead. `fsg-tender-review/docs/README.md` is removed
from `FILES` here. It earned the "Start here" label on 11 Sep, but that
repo's own `CLAUDE.md` has since restated its role as the map, read "before
touching a module you have not touched before" -- on demand, once a pointer
names it, not a page every session pays for regardless of what it touches.
The gate had not caught up to that restatement. The file itself is
untouched, still linked from `CLAUDE.md`'s "Where things live", still the
map -- only this word-cap gate stops counting it.

This check first shipped as a 300-line script duplicated inside
`fsg-estimating-crm` alone (`scripts/check_reading_path_word_count.py`,
12 Sep 2026), running only in that repo's CI. On 19 Sep 2026 a doc edit in
`fsg-tender-review` pushed the shared total over the cap and turned two
unrelated `fsg-estimating-crm` PRs red -- the repo that broke was the one
that did not change, because nothing but crm's own CI ever re-measured the
total. David's decision then: run the identical check in all five repos'
own CI, pre-merge, so each one catches its own overage before it ships.

Five copies of this logic is exactly the failure this estate has already
paid for twice -- `check_twin_parity.py` (deleted, tr#281/5 Sep 2026
adoption) and the `fsg_sections.json` twin (retired, fsg-common#6/#12, 7 Sep
2026) both existed because a resolver was copied into more than one repo and
drifted. `fsg_common` is the shared package all four consumers already
import or vendor for exactly that reason, so the check lives here once and
each repo carries only a thin CLI wrapper that names which repo it is
running in and calls `main()`.

## Parameterisation: `this_repo`, not a module constant

The original script hardcoded `THIS_REPO = "fsg-estimating-crm"` and read
that one repo's file from the local working tree (never the API -- a PR
that edits a repo's own `CLAUDE.md` is judged on the content it proposes,
not on an API call that would still return the pre-PR body). Five repos
need five different answers to "which file(s) are mine", so `this_repo` is
a parameter here, supplied by each repo's own wrapper script -- a single
short string, not something derived by inspecting `__file__`, because once
this module is installed or vendored into a consumer, `__file__` resolves
inside THIS package, not the consumer's checkout. `repo_root` is the same
kind of parameter, defaulting to `os.getcwd()`, which is correct both in a
CI step (actions/checkout leaves you at the repo root) and for a person
running the wrapper from their own checkout.

A repo CAN own more than one local file -- `main()` reads every `FILES`
entry whose repo matches `this_repo` from disk, and everything else over
the GitHub API. No repo currently does (fsg-tender-review was the one
example, until `docs/README.md` was removed from `FILES` on 25 Sep 2026,
crm#1009); the capability stays because a repo splitting its compulsory
rules across two files is a legitimate shape this module should not
special-case away.

## Credential

Same pattern `scripts/vendor_fsg_common.py` and
`fsg-tender-review/scripts/check_fsg_common_pins.py` already use for this
exact problem: `FSG_COMMON_PAT` first (David's classic PAT, `repo` scope),
then `GH_TOKEN`, then `GITHUB_TOKEN`. Three of the four files this module
reads over the API live in private repos; a workflow's own `GITHUB_TOKEN` is
scoped to its own repository and cannot read them. **Absent input must not
answer**: no credential is a REFUSAL (exit 2), never a total that silently
omitted four of five files. A repo whose CI has no `FSG_COMMON_PAT` secret
refuses every run until one is added -- that is this module working, not a
bug to route around.

## The one exemption: a Dependabot-actor pull_request run

fsg-tender-review#639, 18 Sep 2026: GitHub withholds every repository secret
from a `pull_request` run whose actor is `dependabot[bot]` -- confirmed a
maintainer's own re-run of that same run still saw the secret empty; only a
genuinely NEW event restores it. `dependabot_actor()` is true only for the
exact platform-imposed case; even then the skip is not taken on trust --
`local_file_touched_since()` runs a local, tokenless `git diff` to confirm
this run's own diff did not touch any of THIS repo's own local files, and
refuses (never skips) if that cannot be established.

## Word count method

`len(text.split())` -- the same definition POSIX `wc -w` uses with a
correctly configured locale. Measured 12 Sep 2026: a plain `wc -w` in an
unconfigured shell locale mis-splits a multi-byte UTF-8 em dash and
undercounts by about 3% against `str.split()`; this module uses
`str.split()` deliberately so the answer does not depend on the caller's
shell locale. No markdown stripping -- a table cell or a code fence is still
text a session's context window pays for.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER = "FremantleSteel"

# 30,000 originally (David, crm#557, 11 Sep 2026). Raised to 30,500 (David,
# crm#635, 18 Sep 2026), verbatim: "Raise the cap to 30,500."
WORD_LIMIT = 30_500

# The compulsory reading path, per David's decision on crm#557 (11 Sep
# 2026), narrowed by crm#1009 (25 Sep 2026): `fsg-tender-review/docs/
# README.md` removed -- see the module docstring for why. One `CLAUDE.md`
# per repo. A single copy of this tuple, read by all five repos' own
# wrapper scripts -- previously five places this list could silently drift
# apart from each other.
FILES: tuple[tuple[str, str], ...] = (
    ("fsg-estimating-crm", "CLAUDE.md"),
    ("fsg-tender-review", "CLAUDE.md"),
    ("fsg-estimating-tools", "CLAUDE.md"),
    ("fsg-bluebeam-steel-standards", "CLAUDE.md"),
    ("fsg-common", "CLAUDE.md"),
)

API = "https://api.github.com"


class Unavailable(RuntimeError):
    """A file could not be read. Never silently dropped from the total."""


def token() -> str | None:
    """The first credential that can read a private repo in this org."""
    for name in ("FSG_COMMON_PAT", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    return None


def dependabot_actor() -> bool:
    """True only for the exact case GitHub itself withholds every secret from.

    `GITHUB_ACTOR`/`GITHUB_EVENT_NAME` are default environment variables the
    runner sets itself; nothing in a PR's own diff can set them, because a
    `pull_request` run always executes the workflow version from the BASE
    ref.
    """
    return (
        os.environ.get("GITHUB_ACTOR") == "dependabot[bot]"
        and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
    )


def local_file_touched_since(
    base_sha: str, repo_root: str, paths: tuple[str, ...]
) -> bool | None:
    """Whether any of `paths` (this repo's own local files) differ between
    `base_sha` and `HEAD` -- read from the LOCAL git history already on
    disk, no token, no network.

    `True` / `False` only when this could actually be established; `None`
    when it could not (`base_sha` empty, no local paths, git failed, the
    base commit is not reachable). The caller must never treat `None` as
    `False` -- "could not check" is not "unchanged".
    """
    if not base_sha or not paths:
        return None

    def _diff():
        return subprocess.run(
            ["git", "diff", "--name-only", f"{base_sha}...HEAD", "--", *paths],
            cwd=repo_root, capture_output=True, text=True, timeout=30, check=False)

    try:
        result = _diff()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        # `base_sha` is not reachable from a shallow (default) checkout. One
        # best-effort network fetch of just that commit, then one more try --
        # never attempted when the first diff already worked.
        try:
            subprocess.run(
                ["git", "fetch", "--depth", "1", "origin", base_sha],
                cwd=repo_root, capture_output=True, text=True, timeout=30,
                check=False)
            result = _diff()
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
    return result.stdout.strip() != ""


def _get(url: str, tok: str, attempts: int = 2) -> bytes:
    """One GET, retried ONCE on a transient fault and never on an answer.

    This gate is meant to run blocking, so a five-second GitHub blip must
    not turn it red for a reason nobody can act on. A 401/403/404 IS an
    answer and raises immediately; only a connection failure, a timeout or a
    5xx is retried.
    """
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github.raw",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "fsg-check-reading-path-word-count",
    })
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(2)
    raise AssertionError("unreachable: the loop above returns or raises")


def read_local(path: str, repo_root: str) -> str:
    """A file from `repo_root` -- never the API. See the module docstring
    for why the running repo's own file is always read this way."""
    full = os.path.join(repo_root, *path.split("/"))
    try:
        with open(full, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise Unavailable(f"{path}: cannot read {full}: {exc}") from exc


def read_via_api(repo: str, path: str, tok: str) -> str:
    """`path` at `repo`'s default branch, over the GitHub contents API."""
    url = f"{API}/repos/{OWNER}/{repo}/contents/{path}"
    try:
        raw = _get(url, tok)
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code in (401, 403):
            hint = (" -- the token cannot read this private repo; a workflow's "
                    "own GITHUB_TOKEN is scoped to its own repository, use "
                    "FSG_COMMON_PAT")
        elif exc.code == 404:
            hint = (f" -- either {OWNER}/{repo} has no {path}, or the token "
                    "cannot see the repo at all (GitHub returns 404, not 403, "
                    "for a private repo a token may not read)")
        raise Unavailable(f"{repo}/{path}: HTTP {exc.code}{hint}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise Unavailable(f"{repo}/{path}: could not reach the GitHub API: {exc}") from exc
    return raw.decode("utf-8", "replace")


def word_count(text: str) -> int:
    """`len(text.split())` -- the same definition POSIX `wc -w` uses."""
    return len(text.split())


def measure(read, files: tuple[tuple[str, str], ...] = FILES) -> dict[tuple[str, str], int]:
    """`{(repo, path): words}` for every file, or `Unavailable` naming the
    first that could not be read. `read` is injected so tests exercise this
    without a network or a credential."""
    counts: dict[tuple[str, str], int] = {}
    for repo, path in files:
        n = word_count(read(repo, path))
        if n == 0:
            # An empty 200 (or an empty file) is not a file of zero words: the
            # total would shrink silently and the cap would pass on a read
            # that never happened.
            raise Unavailable(f"{repo}/{path}: read back empty (0 words); "
                              "that is an unreadable file, not a count of zero")
        counts[(repo, path)] = n
    return counts


def verdict(counts: dict[tuple[str, str], int], limit: int = WORD_LIMIT) -> tuple[int, list[str]]:
    """`(exit code, lines to print)`. Pure, so tests read the message a
    person would read rather than only the number. Every line prints
    unconditionally, pass or fail -- a number only shown on failure is not
    there when you need to ask about it."""
    total = sum(counts.values())
    lines = [f"  {repo}/{path}: {n:,} words" for (repo, path), n in counts.items()]
    lines.append(f"TOTAL (compulsory reading path): {total:,} words (limit {limit:,})")
    if total > limit:
        lines.append(
            f"OVER LIMIT by {total - limit:,} words. crm#557: David's decision is "
            f"that this path stays under {limit:,} words. Trim one of the files "
            "above, or take the overage back to David before merging.")
        return 1, lines
    lines.append(f"ok -- {limit - total:,} words of headroom")
    return 0, lines


def main(this_repo: str, argv: list[str] | None = None, repo_root: str | None = None) -> int:
    """Entry point each repo's thin wrapper calls, e.g.
    `main("fsg-tender-review", sys.argv[1:])`.

    `this_repo` decides which `FILES` entries are read from `repo_root`
    (default `os.getcwd()`) and which are read over the API -- see the
    module docstring's "Parameterisation" section.
    """
    ap = argparse.ArgumentParser(
        description="The compulsory reading path stays under the word cap "
                     "(crm#557, crm#635).")
    ap.add_argument("--json", action="store_true",
                    help="print the per-file counts as JSON as well as the verdict")
    args = ap.parse_args(argv)

    repo_root = repo_root or os.getcwd()
    local_paths = tuple(path for repo, path in FILES if repo == this_repo)
    if not local_paths:
        known = sorted({repo for repo, _ in FILES})
        print(f"REFUSED: {this_repo!r} owns none of the {len(FILES)} files "
              f"in the compulsory reading path ({known}). This check is "
              "running in the wrong repo, or FILES and the caller have "
              "drifted apart.")
        return 2

    tok = token()
    if not tok:
        if dependabot_actor():
            touched = local_file_touched_since(
                os.environ.get("PR_BASE_SHA", ""), repo_root, local_paths)
            if touched is False:
                print(
                    "SKIPPED (not a pass): this run's actor is dependabot[bot], "
                    "and GitHub withholds every repository secret from a "
                    "pull_request run it triggers -- confirmed 18 Sep 2026 "
                    "(fsg-tender-review#639): a maintainer's own re-run of the "
                    "SAME run still saw the credential empty. This run's own "
                    f"diff was checked against PR_BASE_SHA and does not touch "
                    f"{', '.join(local_paths)}, the file(s) among the "
                    f"{len(FILES)} this repo's own tree could have changed. "
                    "The estate-wide "
                    "total still gets re-measured on every push to main and "
                    "on every PR from any other actor -- real creep is still "
                    "caught, just not by this run.")
                return 0
            reason = (
                f"{', '.join(local_paths)} WAS changed in this diff"
                if touched else
                f"whether this diff touches {', '.join(local_paths)} could "
                "not be established (PR_BASE_SHA missing or unreachable)")
            print(f"REFUSED: actor is dependabot[bot] and no credential is "
                  f"available, and {reason}. That combination is not the "
                  "narrow case this gate may skip for.")
            return 2
        remote_n = len(FILES) - len(local_paths)
        print("REFUSED: no credential. Set FSG_COMMON_PAT (or GH_TOKEN) to a "
              "token that can read the private repos in this org -- `gh auth "
              f"token` locally, `secrets.FSG_COMMON_PAT` in CI. Without one, "
              f"at least {remote_n} of the {len(FILES)} files were never "
              "read, and that is not a word count of zero.")
        return 2

    def read(repo: str, path: str) -> str:
        return read_local(path, repo_root) if repo == this_repo else read_via_api(repo, path, tok)

    try:
        counts = measure(read)
    except Unavailable as exc:
        print(f"REFUSED: {exc}")
        print("No total was computed. This is not a pass and must not be read as one.")
        return 2

    code, lines = verdict(counts)
    for line in lines:
        print(line)
    if args.json:
        print(json.dumps({f"{r}/{p}": n for (r, p), n in counts.items()}, indent=2))
    return code


def _cli() -> int:
    """`python -m fsg_common.reading_path <this-repo>` -- mainly for local
    ad-hoc use; every repo's own wrapper script calls `main()` directly with
    its own name baked in rather than relying on argv[1]."""
    if len(sys.argv) < 2:
        print("usage: python -m fsg_common.reading_path <this-repo> [--json]")
        return 2
    return main(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    sys.exit(_cli())
