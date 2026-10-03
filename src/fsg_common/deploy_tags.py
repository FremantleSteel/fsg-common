"""Git tags recording what commit was actually deployed, per artefact.

The one shared copy (crm#1976, 4 Oct 2026). `scripts/deploy_tags.py` in
fsg-estimating-crm (crm#554, #607) and fsg-estimating-tools (tools#302, ported
from crm) had diverged: of 11 shared functions only 4 were identical, and each
copy carried fixes the other lacked. This is the union. Every rule either copy
enforced is kept; where they conflicted outright, the fail-closed behaviour
wins. Each repo's `scripts/deploy_tags.py` is a thin wrapper that points
`REPO_ROOT` at its own checkout and then *becomes* this module
(`sys.modules[__name__] = fsg_common.deploy_tags`), so a test that patches
`deploy_tags.<name>` patches the code that runs.

WHY DEPLOY TAGS EXIST. Nothing in the estate recorded what is deployed versus
what merely sits on `main`. A drift check that compares live against `main` or
the working tree cannot tell "not yet deployed" (expected) from "someone
edited live directly" (the one case worth an alarm). A deploy tag answers one
narrow question: what commit did this artefact's live copy last come from,
CONFIRMED? Deploy scripts call `create()` only after reading the artefact back
from live, so a tag is never speculative. `compare()` is what a drift check
calls:

    match        live equals the content at the newest deploy tag.
    behind       live equals the content at an OLDER deploy tag.
    ahead        live matches no recorded deploy tag (and, when `live_mtime`
                 is given, was written at or after the newest tag): someone
                 changed live directly, bypassing the deploy script.
    unrecorded   live matches no tag, but `live_mtime` PREDATES the newest
                 tag (tools#379): more consistent with an untagged deploy
                 than with a live edit. Only reported when `live_mtime` is
                 supplied; without it, this is `ahead`.
    inverted     the tag record points BACKWARDS: the newest tag (by tagger
                 date) names a strict ANCESTOR of a commit an older tag names
                 (crm#554, the FSG-V case of 24 Sep 2026, where a stale deploy
                 made a stale live copy read MATCH). No content verdict.
    tag-mismatch the newest tag RECORDS a content hash (`fsg-content-sha256:`)
                 that disagrees with the content at its own commit. Only
                 checked when `compare()` is given a single `path`.
    refused      no tag, not a git checkout, an unanswerable ancestry
                 question, unreadable content or record. Never falls back to
                 `main` or the working tree.

TWO CONTENT MODELS. `path=` reads one tracked file at each tag. `content_at_fn=`
(tools: the `.xlam` is six VBA modules; the template's live bytes are a build
output, compared through `recorded_hash()`'s `sha256:<hex>` note line) takes a
callable `tag -> bytes | None`. Exactly one must be given.

PUSHING. A tag is pushed to `origin` inside the same call that makes it
(`push=True`), because `fetch.pruneTags=true` in a shared clone deletes an
unpushed local tag on any sibling worktree's fetch, with no reflog (crm#554,
tools#322). The push names the tag OBJECT's sha, so a ref pruned between
creation and push still reaches origin, and origin is read back before
success is reported (tools#463).

GIT ENVIRONMENT. Every git child runs with the GIT_* variables removed except
transport ones (tools#317): a hook exports GIT_DIR, and a `git -C <temp repo>`
child that inherits it acts on the real repository. On 24 Sep 2026 that
pushed 8 fake deploy tags from a test run.

TWO PER-REPO SETTINGS, pending David (crm#1976). Both default fail-closed here;
a wrapper may relax one to keep its repo's behaviour until he decides:

    REFUSE_ROLLBACK             create() refuses a deploy whose commit is a
                                strict ancestor of one already tagged (crm).
                                tools did not refuse.
    CLI_CREATE_REQUIRES_ORIGIN  `deploy_tags.py create` exits 3 unless origin
                                holds the tag (tools#463). crm exited 0.

Tag shape: `deploy/<artefact>/<yyyy-mm-dd>[.<n>]`. `sanitize()` collapses the
artefact id to one ref segment, so two ids can never collide as a ref
directory/file pair. A tag is never moved; a second same-day deploy gets `.2`.

    python scripts/deploy_tags.py create  --artefact n8n/FSG-L-drawing-register-sync
    python scripts/deploy_tags.py latest  --artefact xlam
    python scripts/deploy_tags.py list    --artefact xlam
    python scripts/deploy_tags.py compare --artefact template \\
        --path templates/FSG_Estimating_Template.xlsx --live-file /tmp/live.xlsx
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

TAG_ROOT = "deploy"

#: Set by each repo's wrapper to its own checkout; read at call time.
REPO_ROOT: str = os.getcwd()

#: See "TWO PER-REPO SETTINGS" in the module docstring.
REFUSE_ROLLBACK = True
CLI_CREATE_REQUIRES_ORIGIN = True

#: The two annotation lines `create(path=...)` writes and `recorded_content()`
#: reads (crm). Distinct from tools' `sha256:<hex>` note line (`recorded_hash`).
CONTENT_SHA_PREFIX = "fsg-content-sha256:"
CONTENT_PATH_PREFIX = "fsg-content-path:"

_KEPT_GIT_VARS = frozenset({
    "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSH_VARIANT",
    "GIT_TERMINAL_PROMPT",
})

#: Set by a test process (tools' tests/_git_env.py). While set, push_tag()
#: refuses any origin that is not a directory on this machine.
UNDER_TEST_VAR = "FSG_GIT_UNDER_TEST"

_UNSET = object()


def _root(repo_root: str | None) -> str:
    return str(repo_root) if repo_root else REPO_ROOT


def git_env(**extra: str) -> dict[str, str]:
    """The current environment minus every GIT_* variable except transport
    ones, plus `extra` (tools#317). Built fresh on every call."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") or k in _KEPT_GIT_VARS}
    env.update(extra)
    return env


def _git_text(repo_root: str | None, *args: str, timeout: int = 30):
    return subprocess.run(["git", "-C", _root(repo_root), *args], capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, check=False,
                          env=git_env())


def _push_refusal(repo_root: str | None) -> str | None:
    """While under test, why `origin` must not be pushed to, or None (tools#317).

    Outside a test this is always None. Under test, an origin that is not an
    existing local directory is refused before `git push` runs. No origin at
    all is not refused here: the push then fails by itself.
    """
    if not os.environ.get(UNDER_TEST_VAR):
        return None
    got = _git_text(repo_root, "remote", "get-url", "--push", "origin")
    if got.returncode != 0:
        return None
    url = got.stdout.strip()
    local = url[len("file://"):] if url.startswith("file://") else url
    if url and "://" not in local and os.path.isdir(local):
        return None
    return (f"REFUSED: {UNDER_TEST_VAR} is set and origin for {_root(repo_root)} is "
            f"{url!r}, which is not a local directory. A test must never push "
            "to a real remote (tools#317). Nothing was pushed.")


def sanitize(artefact: str) -> str:
    """Collapse `artefact` to one safe git-ref path segment with no `/`."""
    if not artefact or not artefact.strip():
        raise ValueError("an artefact id is required, e.g. 'xlam' or "
                         "'n8n/FSG-L-drawing-register-sync'")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", artefact.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    if not s:
        raise ValueError(f"artefact id sanitizes to nothing usable: {artefact!r}")
    return s


def tag_glob(artefact: str) -> str:
    """The `refs/tags/...` pattern matching every deploy tag for `artefact`."""
    return f"refs/tags/{TAG_ROOT}/{sanitize(artefact)}/*"


def is_git_checkout(repo_root: str | None = None) -> tuple[bool, str | None]:
    """`(True, None)` for a git working tree, else `(False, problem)`.

    crm#1476: an empty `for-each-ref` from a directory that is not a checkout
    at all (the monitor tree is shipped as a `git archive` extraction) read as
    "never deployed" for ~20 workflows with 72 real tags in history.
    """
    out = _git_text(repo_root, "rev-parse", "--is-inside-work-tree")
    if out.returncode == 0 and out.stdout.strip() == "true":
        return True, None
    return False, (out.stderr.strip()[:200]
                   or f"`git -C {_root(repo_root)} rev-parse --is-inside-work-tree` "
                      f"exited {out.returncode}")


def all_tags(artefact: str, *, repo_root: str | None = None) -> list[str]:
    """Every deploy tag for `artefact`, newest-created (`creatordate`) first."""
    out = _git_text(repo_root, "for-each-ref", "--sort=-creatordate",
                    "--format=%(refname:short)", tag_glob(artefact))
    if out.returncode != 0:
        return []
    return [n for n in out.stdout.splitlines() if n.strip()]


def latest(artefact: str, *, repo_root: str | None = None) -> str | None:
    """The most recently created deploy tag for `artefact`, or None."""
    tags = all_tags(artefact, repo_root=repo_root)
    return tags[0] if tags else None


def commit_of(tag: str, *, repo_root: str | None = None) -> str | None:
    """The commit `tag` names, or None if it cannot be resolved here.
    None means "could not establish": every caller treats it as a refusal."""
    out = _git_text(repo_root, "rev-parse", "--verify", f"{tag}^{{commit}}")
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _tag_creation_ts(tag: str, *, repo_root: str | None = None) -> float | None:
    """The tag's `creatordate` as a Unix timestamp, or None (tools#379)."""
    out = _git_text(repo_root, "for-each-ref", "--format=%(creatordate:unix)",
                    f"refs/tags/{tag}")
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def _resolve_tag(name: str, repo_root: str | None) -> str | None:
    """The tag OBJECT's sha for `refs/tags/<name>`, or None (tools#463)."""
    got = _git_text(repo_root, "rev-parse", "--verify", "-q", f"refs/tags/{name}")
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else None


def remote_has(name: str, repo_root: str | None = None) -> bool:
    """True only when `origin` itself reports `refs/tags/<name>` (tools#463)."""
    got = _git_text(repo_root, "ls-remote", "origin", f"refs/tags/{name}")
    return got.returncode == 0 and bool(got.stdout.strip())


@dataclass
class Inversion:
    """`newest_tag` was created later but names a strict ancestor of the
    commit `older_tag` names."""
    newest_tag: str
    newest_commit: str
    older_tag: str
    older_commit: str


def _strict_ancestor(maybe_ancestor: str, descendant: str, *,
                     repo_root: str | None = None) -> tuple[bool | None, str | None]:
    """Is `maybe_ancestor` a STRICT ancestor of `descendant`? `(answer, problem)`.

    `merge-base --is-ancestor` exits 0 yes, 1 no, anything else could not
    answer, which is returned as a problem, never as "no".
    """
    if maybe_ancestor == descendant:
        return False, None
    out = _git_text(repo_root, "merge-base", "--is-ancestor", maybe_ancestor, descendant)
    if out.returncode == 0:
        return True, None
    if out.returncode == 1:
        return False, None
    return None, (f"`git merge-base --is-ancestor {maybe_ancestor[:12]} "
                  f"{descendant[:12]}` exited {out.returncode} "
                  f"({out.stderr.strip()[:200] or 'no stderr'})")


def ancestry_inversion(tags: list[str], *, repo_root: str | None = None
                       ) -> tuple[Inversion | None, str | None]:
    """Does the newest tag point backwards against any older one?
    `(None, None)` no; `(Inversion, None)` yes; `(None, problem)` unanswerable."""
    if len(tags) < 2:
        return None, None
    newest = tags[0]
    newest_commit = commit_of(newest, repo_root=repo_root)
    if newest_commit is None:
        return None, (f"the commit behind {newest!r} could not be resolved in "
                      f"{_root(repo_root)}")
    for older in tags[1:]:
        older_commit = commit_of(older, repo_root=repo_root)
        if older_commit is None:
            return None, (f"the commit behind {older!r} could not be resolved "
                          f"in {_root(repo_root)}")
        answer, problem = _strict_ancestor(newest_commit, older_commit,
                                           repo_root=repo_root)
        if problem is not None:
            return None, problem
        if answer:
            return Inversion(newest, newest_commit, older, older_commit), None
    return None, None


def push_tag(name: str, *, repo_root: str | None = None, timeout: int = 30,
             obj: str | None = None) -> tuple[bool, str]:
    """Push one already-created tag to `origin`. Returns (ok, message); never
    raises. Pushes the tag OBJECT's sha (a pruned local ref does not stop it)
    and reads origin back before reporting success (tools#463)."""
    refusal = _push_refusal(repo_root)
    if refusal is not None:
        return False, refusal
    root = _root(repo_root)
    cmd = ["git", "-C", root, "push", "origin", f"refs/tags/{name}"]
    obj = obj or _resolve_tag(name, repo_root)
    if obj is None:
        return False, (
            f"PUSH FAILED for {name} -- it is GONE LOCALLY TOO: the tag does not "
            f"exist locally any more, so nothing was pushed and there is no local "
            f"copy to push by hand. This is the fetch.pruneTags=true race (crm#554, "
            f"tools#322/#463): a fetch in a worktree sharing this clone deleted it. "
            f"Re-tag the commit the deploy actually shipped: python "
            f"scripts/deploy_tags.py create --artefact <artefact> --commit <sha>")
    result = subprocess.run(["git", "-C", root, "push", "origin",
                             f"{obj}:refs/tags/{name}"],
                            capture_output=True, text=True, encoding="utf-8",
                            timeout=timeout, check=False, env=git_env())
    if result.returncode == 0:
        remote = _git_text(repo_root, "ls-remote", "origin", f"refs/tags/{name}")
        if remote.returncode != 0 or remote.stdout.split()[:1] != [obj]:
            return False, (f"PUSH FAILED for {name} -- push exited 0 but origin does "
                           f"not hold {obj[:12]} at refs/tags/{name}. Run by hand: "
                           f"{' '.join(cmd)}")
        if _resolve_tag(name, repo_root) is None:
            _git_text(repo_root, "update-ref", f"refs/tags/{name}", obj)
        return True, f"pushed {name} to origin"
    return False, (
        f"PUSH FAILED for {name} -- it exists LOCALLY ONLY. A fetch.pruneTags=true "
        f"fetch in ANY worktree sharing this clone can delete it before anyone "
        f"notices, with no reflog to recover it (crm#554, tools#322). Run by hand, "
        f"now, before any fetch: {' '.join(cmd)}\n"
        f"git said: {result.stderr.strip()[:300]}")


def content_at(tag: str, path: str, *, repo_root: str | None = None) -> bytes | None:
    """The bytes `path` held at `tag`, or None if the tag or path can't be read."""
    if _git_text(repo_root, "rev-parse", "--verify", f"{tag}:{path}").returncode != 0:
        return None
    out = subprocess.run(["git", "-C", _root(repo_root), "show", f"{tag}:{path}"],
                         capture_output=True, timeout=60, check=False, env=git_env())
    if out.returncode != 0:
        return None
    return out.stdout


def content_sha256(data: bytes) -> str:
    """The one hash this module records and checks with."""
    return hashlib.sha256(data).hexdigest()


def create(artefact: str, *, repo_root: str | None = None, commit: str = "HEAD",
           when: dt.datetime | None = None, note: str = "", push: bool = False,
           allow_rollback: bool = False,
           path: str | None = None) -> tuple[str | None, str]:
    """Create a deploy tag at `commit`. Returns (tag_name, sha), or
    (None, reason) on failure; never raises, so a caller mid-deploy can print
    the reason and carry on. Never overwrites a tag; a same-day redeploy gets
    `.2`, `.3`. Pass distinct `when` values a second apart when backfilling.

    Rollback (crm): when `REFUSE_ROLLBACK` is on, a `commit` that is a strict
    ancestor of one this artefact is already tagged at is refused, as is an
    ancestry question that cannot be answered; `allow_rollback=True` records
    it anyway, for a deliberate rollback.

    `path` (crm) records the sha256 of that file at `commit` as
    `fsg-content-sha256:` / `fsg-content-path:` lines; an unreadable `path`
    refuses rather than writing a tag that looks pre-scheme.

    After `git tag`, the ref is read back; a tag that does not resolve is a
    failure (tools#463). `push=True` pushes it at once (crm#554, tools#322).
    """
    root = _root(repo_root)
    resolved = _git_text(repo_root, "rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved.returncode != 0:
        return None, (f"{commit!r} does not resolve to a commit in {root}: "
                      f"{resolved.stderr.strip()[:200]}")
    sha = resolved.stdout.strip()

    if REFUSE_ROLLBACK and not allow_rollback:
        for prior in all_tags(artefact, repo_root=repo_root):
            prior_sha = commit_of(prior, repo_root=repo_root)
            if prior_sha is None:
                return None, (
                    f"NOT tagging {artefact!r} at {sha[:12]}: the commit behind the "
                    f"existing tag {prior!r} could not be resolved in {root}, so "
                    f"whether this deploy goes BACKWARDS could not be established. "
                    f"Fix the tag, or pass allow_rollback=True to record it anyway.")
            backwards, problem = _strict_ancestor(sha, prior_sha, repo_root=repo_root)
            if problem is not None:
                return None, (
                    f"NOT tagging {artefact!r} at {sha[:12]}: whether it goes "
                    f"BACKWARDS relative to {prior!r} could not be established -- "
                    f"{problem}. Pass allow_rollback=True to record it anyway.")
            if backwards:
                return None, (
                    f"NOT tagging {artefact!r} at {sha[:12]}: that commit is a strict "
                    f"ANCESTOR of {prior_sha[:12]}, which {prior!r} already records "
                    f"as deployed, so this deploy shipped EARLIER content. Recording "
                    f"it would make `compare()` report MATCH for a stale live copy "
                    f"(crm#554, the FSG-V case, 24 Sep 2026). Check the checkout this "
                    f"deploy ran from; if the rollback was deliberate, re-run with "
                    f"allow_rollback=True.")

    stamp = when or dt.datetime.now(dt.timezone.utc)
    safe = sanitize(artefact)
    base = f"{TAG_ROOT}/{safe}/{stamp.date().isoformat()}"
    existing = set(_git_text(repo_root, "tag", "--list", f"{TAG_ROOT}/{safe}/*").stdout.split())
    name, n = base, 2
    while name in existing:
        name = f"{base}.{n}"
        n += 1

    content_lines = ""
    if path is not None:
        blob = content_at(sha, path, repo_root=repo_root)
        if blob is None:
            return None, (
                f"NOT tagging {artefact!r} at {sha[:12]}: {path!r} could not be read "
                f"at that commit, so the content hash this tag was asked to record "
                f"could not be computed. Commit the file, or call create() without "
                f"`path`.")
        content_lines = (f"\n\n{CONTENT_SHA_PREFIX} {content_sha256(blob)}"
                         f"\n{CONTENT_PATH_PREFIX} {path}")

    message = (f"deploy: {artefact} at {sha[:12]}"
               + (f"\n\n{note}" if note else "") + content_lines + "\n")
    extra = {}
    if when is not None:
        extra["GIT_COMMITTER_DATE"] = when.astimezone(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    made = subprocess.run(["git", "-C", root, "tag", "-a", name, sha, "-m", message],
                          capture_output=True, text=True, encoding="utf-8", timeout=30,
                          env=git_env(**extra), check=False)
    if made.returncode != 0:
        return None, f"git tag failed: {made.stderr.strip()[:300]}"
    obj = _resolve_tag(name, repo_root)
    if obj is None:
        return None, (f"git tag exited 0 but refs/tags/{name} does not resolve in "
                      f"{root}; no tag exists, nothing was pushed")
    if push:
        ok, msg = push_tag(name, repo_root=repo_root, obj=obj)
        print(msg, file=sys.stdout if ok else sys.stderr)
    return name, sha


def tag_message(tag: str, *, repo_root: str | None = None) -> str | None:
    """The full annotated message of `tag`, or None (missing or lightweight)."""
    out = _git_text(repo_root, "for-each-ref", "--format=%(contents)", f"refs/tags/{tag}")
    if out.returncode != 0 or not out.stdout:
        return None
    return out.stdout


_SHA256_NOTE_RE = re.compile(r"(?m)^sha256:([0-9a-f]{64})$")


def recorded_hash(tag: str, *, repo_root: str | None = None) -> str | None:
    """The `sha256:<hex>` line a deploy script put in `tag`'s note, or None
    (tools#321: the template's live bytes are a build output, compared by
    hash through `content_at_fn`)."""
    msg = tag_message(tag, repo_root=repo_root)
    if msg is None:
        return None
    m = _SHA256_NOTE_RE.search(msg)
    return m.group(1) if m else None


@dataclass
class RecordedContent:
    """What a tag's `fsg-content-*` lines record: the hash and the path it is of."""
    sha256: str
    path: str | None


def recorded_content(tag: str, *, repo_root: str | None = None
                     ) -> tuple[RecordedContent | None, str | None]:
    """`(RecordedContent, None)` a hash is recorded; `(None, None)` none is
    (the tag predates the scheme -- never read as agreement); `(None, problem)`
    the annotation could not be read or is malformed -- refuse on it."""
    if _git_text(repo_root, "rev-parse", "--verify", f"{tag}^{{commit}}").returncode != 0:
        return None, (f"{tag!r} could not be resolved in {_root(repo_root)}, so its "
                      "annotation could not be read")
    out = _git_text(repo_root, "tag", "-l", "--format=%(contents)", tag)
    if out.returncode != 0:
        return None, (f"could not read {tag!r}'s annotation: "
                      f"{out.stderr.strip()[:200] or 'no stderr'}")
    sha = path = None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith(CONTENT_SHA_PREFIX):
            sha = line[len(CONTENT_SHA_PREFIX):].strip().lower()
        elif line.startswith(CONTENT_PATH_PREFIX):
            path = line[len(CONTENT_PATH_PREFIX):].strip() or None
    if sha is None:
        return None, None
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        return None, (f"{tag!r} carries a {CONTENT_SHA_PREFIX} line that is not a "
                      f"sha256: {sha[:80]!r}. A malformed record is not an absent "
                      "one and is not a matching one either.")
    return RecordedContent(sha, path), None


@dataclass
class DriftOutcome:
    """One `compare()` verdict; see the module docstring for each status."""
    status: str  # match|behind|ahead|unrecorded|inverted|tag-mismatch|refused
    tag: str | None
    reason: str
    inverted_against: str | None = None
    newest_commit: str | None = None
    inverted_against_commit: str | None = None
    recorded_sha256: str | None = None
    tagged_content_sha256: str | None = None

    @property
    def drifted(self) -> bool:
        return self.status in ("behind", "ahead", "unrecorded", "inverted",
                               "tag-mismatch")


def _identity(data: bytes) -> bytes:
    return data


def compare(artefact: str, path_or_live=_UNSET, live=_UNSET, *,
            path: str | None = None,
            content_at_fn: Callable[[str], bytes | None] | None = None,
            repo_root: str | None = None, normalize=_identity,
            live_mtime: float | None = None) -> DriftOutcome:
    """Does `live` match the tag we last deployed `artefact` from?

    Two call shapes, both kept (crm#1976): crm's `compare(artefact, path,
    live)` and tools' `compare(artefact, live, path=... | content_at_fn=...)`.
    When `live` is supplied (positionally or by keyword) the second argument
    is the path; otherwise it is `live`. Exactly one of a path or
    `content_at_fn` must result.

    `normalize` is applied to live and to every tag's content, and must be the
    same notion of "identical" the deploy script used. `live_mtime` only
    changes what a content-match-to-nothing is called (`unrecorded`).
    """
    if live is _UNSET:
        live = None if path_or_live is _UNSET else path_or_live
    else:
        if path is not None:
            raise TypeError("compare(): path given both positionally and by keyword")
        path = None if path_or_live is _UNSET else path_or_live
    if (path is None) == (content_at_fn is None):
        raise ValueError("compare() needs exactly one of path= or content_at_fn=")
    label = repr(path) if path is not None else f"{artefact!r}'s content"
    read: Callable[[str], bytes | None] = (
        (lambda tag: content_at(tag, path, repo_root=repo_root))
        if path is not None else content_at_fn)

    checkout_ok, checkout_problem = is_git_checkout(repo_root)
    if not checkout_ok:
        return DriftOutcome("refused", None,
            f"{_root(repo_root)!r} is not a git checkout ({checkout_problem}) -- deploy "
            "tags live in git history, so this cannot be answered here. Expected on a "
            "tree shipped as a `git archive` extraction; run it from a real checkout. "
            "This is not the same fact as an artefact that was never tagged.")
    tags = all_tags(artefact, repo_root=repo_root)
    if not tags:
        return DriftOutcome("refused", None,
            f"no deploy tag exists for {artefact!r} ({tag_glob(artefact)}) -- "
            "nothing is recorded as deployed, so live cannot be compared "
            "against a deploy record. Deploy it once through a script that "
            "calls deploy_tags.create(), or tag the commit it actually came "
            "from by hand with 'python scripts/deploy_tags.py create'.")
    newest = tags[0]

    inversion, ancestry_problem = ancestry_inversion(tags, repo_root=repo_root)
    if ancestry_problem is not None:
        return DriftOutcome("refused", newest,
            f"the deploy tags for {artefact!r} could not be ordered by commit "
            f"ancestry -- {ancestry_problem}. An ancestry question that could not "
            "be answered is not an answer of 'the record is sound'.")
    if inversion is not None:
        return DriftOutcome("inverted", newest,
            f"the deploy tag record for {artefact!r} POINTS BACKWARDS, so live was "
            f"not compared against anything. The newest tag by tagger date, "
            f"{inversion.newest_tag!r} ({inversion.newest_commit[:12]}), names a "
            f"commit that is a strict ANCESTOR of the one an older tag, "
            f"{inversion.older_tag!r} ({inversion.older_commit[:12]}), already names "
            f"-- the later deploy shipped EARLIER content. Establish which commit "
            f"live should hold, redeploy from it, and tag that; comparing live "
            f"against {inversion.newest_tag!r} would report MATCH for the bad deploy.",
            inverted_against=inversion.older_tag,
            newest_commit=inversion.newest_commit,
            inverted_against_commit=inversion.older_commit)

    newest_content = read(newest)
    if newest_content is None:
        return DriftOutcome("refused", newest,
            f"{label} is not readable at {newest!r} -- cannot compare.")

    recorded = None
    tagged_sha = None
    if path is not None:
        recorded, record_problem = recorded_content(newest, repo_root=repo_root)
        if record_problem is not None:
            return DriftOutcome("refused", newest,
                f"the content hash recorded on {newest!r} could not be read -- "
                f"{record_problem}. An unreadable record is not an absent one and "
                "is not a matching one.")
        if recorded is not None and recorded.path is not None and recorded.path != path:
            return DriftOutcome("refused", newest,
                f"{newest!r} records a content hash for {recorded.path!r}, but this "
                f"comparison is about {path!r}. A hash of a different file settles "
                "nothing here, either way.")
        tagged_sha = content_sha256(newest_content)
        if recorded is not None and recorded.sha256 != tagged_sha:
            return DriftOutcome("tag-mismatch", newest,
                f"{newest!r} RECORDS content sha256 {recorded.sha256[:12]} for "
                f"{path!r}, but the content at the commit that same tag names hashes "
                f"to {tagged_sha[:12]}. The tag was written against a different tree "
                "than the one it points at, so live was not compared against it.",
                recorded_sha256=recorded.sha256, tagged_content_sha256=tagged_sha)

    if live is None:
        return DriftOutcome("refused", newest,
            "live content could not be read -- cannot compare against the tag.")

    live_n, newest_n = normalize(live), normalize(newest_content)
    if live_n == newest_n:
        if recorded is None:
            basis = (" (that tag records no content hash -- it predates the scheme, "
                     "so this verdict rests on the tree at the tag)"
                     if path is not None else "")
            return DriftOutcome("match", newest, f"live matches {newest!r}{basis}")
        if normalize is _identity:
            return DriftOutcome("match", newest,
                f"live hashes to {content_sha256(live)[:12]}, the content sha256 "
                f"{newest!r} records having deployed",
                recorded_sha256=recorded.sha256, tagged_content_sha256=tagged_sha)
        return DriftOutcome("match", newest,
            f"live matches {newest!r}, whose recorded content hash "
            f"({recorded.sha256[:12]}) agrees with its own commit. The hash settles "
            "the tag, not live: this caller normalizes, so the live verdict is the "
            "normalized comparison.",
            recorded_sha256=recorded.sha256, tagged_content_sha256=tagged_sha)

    for older in tags[1:]:
        older_content = read(older)
        if older_content is not None and normalize(older_content) == live_n:
            return DriftOutcome("behind", newest,
                f"live matches an EARLIER deploy tag ({older!r}), not the newest "
                f"({newest!r}) -- the most recent confirmed deploy has not reached "
                "live.")

    if live_mtime is not None:
        newest_ts = _tag_creation_ts(newest, repo_root=repo_root)
        if newest_ts is not None and live_mtime < newest_ts:
            newest_when = dt.datetime.fromtimestamp(newest_ts, dt.timezone.utc)
            live_when = dt.datetime.fromtimestamp(live_mtime, dt.timezone.utc)
            return DriftOutcome("unrecorded", newest,
                f"live matches no recorded deploy tag for {artefact!r}, but its mtime "
                f"({live_when.isoformat()}) predates the newest tag's own creation "
                f"time ({newest!r}, {newest_when.isoformat()}) -- consistent with a "
                "deploy that shipped without ever calling deploy_tags.create() (check "
                "CHANGELOG for an undocumented deploy in this window and backfill a "
                "tag for it), NOT proof that live was edited directly after the last "
                "confirmed deploy. Do not treat this the way AHEAD should be treated.")

    return DriftOutcome("ahead", newest,
        f"live matches no recorded deploy tag for {artefact!r} (newest is "
        f"{newest!r}) -- someone changed live directly, bypassing the deploy script.")


# --------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _repo_root_arg(p):
        p.add_argument("--repo-root", default=None, help=argparse.SUPPRESS)

    c = sub.add_parser("create", help="tag the commit an artefact was just deployed from")
    c.add_argument("--artefact", required=True)
    c.add_argument("--commit", default="HEAD")
    c.add_argument("--note", default="")
    c.add_argument("--allow-rollback", action="store_true",
                   help="record a deploy whose commit is an ANCESTOR of one this "
                        "artefact is already tagged at (refused by default where "
                        "rollback refusal is on). Only for a deliberate rollback.")
    c.add_argument("--path", default=None,
                   help="repo-relative path of the artefact; records its sha256 at "
                        "the tagged commit in the tag's annotation")
    _repo_root_arg(c)

    lst = sub.add_parser("latest", help="the newest deploy tag for an artefact")
    lst.add_argument("--artefact", required=True)
    _repo_root_arg(lst)

    la = sub.add_parser("list", help="every deploy tag for an artefact, newest first")
    la.add_argument("--artefact", required=True)
    _repo_root_arg(la)

    cmp_ = sub.add_parser("compare", help="does a live copy on disk match the newest "
                          "deploy tag?")
    cmp_.add_argument("--artefact", required=True)
    cmp_.add_argument("--path", required=True, help="repo-relative path, as tracked")
    cmp_.add_argument("--live-file", required=True,
                      help="local file holding the live content (read it yourself "
                           "first -- this module never fetches live state)")
    _repo_root_arg(cmp_)

    args = ap.parse_args(argv)
    root = args.repo_root or REPO_ROOT

    if args.cmd == "create":
        name, info = create(args.artefact, repo_root=root, commit=args.commit,
                            note=args.note, push=True,
                            allow_rollback=args.allow_rollback, path=args.path)
        if name is None:
            print(f"NOT created: {info}", file=sys.stderr)
            return 1
        if CLI_CREATE_REQUIRES_ORIGIN and (_resolve_tag(name, root) is None
                                           or not remote_has(name, root)):
            print(f"{name} created but NOT confirmed on origin (see PUSH FAILED "
                  "above); the deploy record is missing until it is pushed",
                  file=sys.stderr)
            return 3
        print(f"{name}  ({info[:12]})")
        return 0
    if args.cmd == "latest":
        tag = latest(args.artefact, repo_root=root)
        if tag is None:
            print(f"no deploy tag for {args.artefact!r}", file=sys.stderr)
            return 1
        print(tag)
        return 0
    if args.cmd == "list":
        tags = all_tags(args.artefact, repo_root=root)
        if not tags:
            print(f"no deploy tag for {args.artefact!r}", file=sys.stderr)
            return 1
        for t in tags:
            print(t)
        return 0
    if args.cmd == "compare":
        try:
            with open(args.live_file, "rb") as fh:
                live = fh.read()
        except OSError as err:
            print(f"REFUSED  live file {args.live_file} could not be read "
                  f"({type(err).__name__}: {err}) -- nothing was compared. "
                  f"If it exists, it is probably open in another process.")
            return 2
        outcome = compare(args.artefact, args.path, live, repo_root=root)
        print(f"{outcome.status.upper()}  {outcome.reason}")
        if outcome.status == "refused":
            return 2
        return 1 if outcome.drifted else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
