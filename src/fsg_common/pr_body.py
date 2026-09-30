"""A pull request body names the issue it closes and stays short.

The one shared implementation (crm#1719, 30 Sep 2026). It was `scripts/
check_pr_body.py` in four repos and had drifted to three versions; this is the
superset -- `fsg-estimating-crm`'s, which carries every rule the others had
plus the `## No issue:` heading form, the `/pull/N`-is-not-a-close fix and
`--closing-refs`. Each repo's `scripts/check_pr_body.py` is now a thin wrapper
calling `main()` here. Stdlib only, so a CI job needs no dependency but the
pin.

Audit 6 Sep 2026, Part 4, sessions' item 7. The move from the kanban board to
GitHub issues was made so that a merge closes its issue by itself, and on
6 Sep the closing keyword appeared in 14% of merged PR bodies. The same audit
measured a median PR body of 429 words against a house style that asks for
under 120. This check holds both, on every PR, before a person has to.

Three rules, and how each fails:

1. The body carries a closing keyword (`Closes #12`, `Fixes org/repo#12`,
   `Resolves https://github.com/org/repo/issues/12`) -- GitHub only honours
   the keyword in the BODY, never in a comment, and only in one of those
   three shapes. **A repo-nickname shorthand such as `crm#447` or `tools#65`
   reads fine to a person but is not one of them**: there is no slash, so
   GitHub reads it as plain text and closes nothing. Three PRs across two
   repos used exactly that shorthand on 18 Sep 2026 (crm#820, crm#821,
   tools#344) and would have merged without closing their issue had David
   not caught it by hand; the failure message below now names the three
   accepted forms and calls the shorthand out explicitly rather than
   leaving a person to guess why a keyword that "obviously" names the issue
   didn't count. A PR that genuinely closes nothing says so with a
   `No issue:` line carrying the reason -- on the same line, or as a
   `## No issue:` heading with the reason in the line right below it (crm#960:
   four lanes wrote the heading form in one evening and the gate wrongly
   rejected all four, then told them to "add a line `No issue:`" they had
   already written). The absent input is then stated, not silently excused; a
   bare `No issue:` with no reason attached is still not a statement.
   **Body text can only ever APPROXIMATE what GitHub will close.**
   The one thing that decides is GitHub's own `closingIssuesReferences`, the
   list of issues a merge will actually close, resolved by GitHub from the
   body. Given it (`--closing-refs`, from `gh pr view N --json
   closingIssuesReferences`), rule 1 reads that instead of the body: an empty
   list means the merge closes nothing, whatever the body seems to say, and a
   PR run this way on merge is the final word rather than a guess. crm#960:
   a body's `owner/repo#N` or a `/pull/N` URL can satisfy the body regex yet
   resolve to nothing here, and only its own field catches that.
2. The body plus the first comment is under 400 words. The first comment
   counts because that is where a long body goes to hide.
3. Neither the body nor the first comment carries a "Co-Authored-By" trailer
   or a "Generated with" line -- David's rule, all five repos, 16 Sep 2026:
   no commit, pull request or document carries an attribution line.

A bot's PR (Dependabot's release notes are neither short nor linked to an
issue here) is exempt by author, and the report says so.

Absent input does not answer: an empty body fails rule 1 with its own
reason, and a comments file that cannot be read exits 2 (cannot evaluate),
never 0. Run locally with `--body-file` and optionally `--comment-file`; the
pre-merge CI job passes `--event "$GITHUB_EVENT_PATH"` and the first comment
fetched with `gh api`; the on-merge CI job also passes `--closing-refs` so the
close is judged by GitHub's own answer, not the body. Exit 0 when all three
rules hold, 1 when any fails, 2 when the input could not be evaluated.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

WORD_LIMIT = 400
EXEMPT_AUTHORS = frozenset({"dependabot[bot]", "github-actions[bot]"})

# GitHub's closing keywords, then either `#N`, `owner/repo#N` or the issue's
# URL. A bare `#12` or `see #12` is a reference, not a close, and fails.
# The URL form must point at `/issues/N`: GitHub closes an issue only from an
# issue URL, so `.../pull/N` links a pull request and closes no issue -- it is
# a keyword+reference GitHub ignores, exactly like the `crm#N` shorthand, and
# the docstring and failure message already name the issue URL as the accepted
# form.
CLOSING = re.compile(
    r"\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b\s*:?\s*"
    r"(?:https://github\.com/[\w.-]+/[\w.-]+/issues/\d+"
    r"|(?:[\w.-]+/[\w.-]+)?#\d+)",
    re.IGNORECASE,
)
# The start of a `No issue:` line, tolerant of how people actually write it:
# a markdown heading (`## No issue:`), a blockquote (`> No issue:`), a list
# marker (`- No issue:`) or bold (`**No issue:**`) all lead the same
# declaration. `states_no_issue` uses this and then insists on a reason --
# crm#960: four lanes in one evening wrote `## No issue:` with the reason on
# the next line and the gate rejected all four, because the old pattern
# demanded the reason on the SAME line with no heading marker in front. A
# heading with its reason underneath is a normal way to write a PR body and is
# unambiguous to a reader, so it is accepted; a bare `No issue:` with no reason
# anywhere still is not, because the whole point is that the reason is stated.
_NO_ISSUE_LEAD = re.compile(
    r"^[ \t]*(?:>[ \t]*)*(?:#{1,6}[ \t]*)?(?:[-*+][ \t]+)?(?:\*\*|__)?"
    r"No issue:[ \t]*(.*?)[ \t]*(?:\*\*|__)?[ \t]*$",
    re.IGNORECASE)

# David's rule, all five repos, 16 Sep 2026: no commit carries a
# Co-Authored-By trailer and no pull request or document carries a
# Generated-with-Claude-Code line. Case-insensitive, same convention as
# CLOSING above -- a person capitalises either phrase however they type it,
# and the rule is not meant to be dodged by case.
FORBIDDEN_ATTRIBUTION = (
    ("Co-Authored-By", re.compile(r"Co-Authored-By", re.IGNORECASE)),
    ("Generated with", re.compile(r"Generated with", re.IGNORECASE)),
)


def word_count(text: str | None) -> int:
    return len(re.findall(r"\S+", text or ""))


def states_no_issue(body: str | None) -> bool:
    """True when the body carries a `No issue:` declaration WITH a reason.

    Accepts the reason on the same line (`No issue: dependency bump.`) or
    directly below a heading form (`## No issue:` then the reason on the next
    line). A bare `No issue:` with a blank line under it, or none at all, is
    not a statement -- the reason has to be somewhere attached to it, or the
    guard is just a phrase to type to get past the check."""
    if not body:
        return False
    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = _NO_ISSUE_LEAD.match(line)
        if not m:
            continue
        reason = m.group(1).strip().strip("*_#> \t")
        if reason:
            return True
        # No reason on the declaration's own line: take it from the line
        # immediately below, but only if that line is not blank -- a blank
        # line means the next paragraph is a separate section, not the reason.
        if i + 1 < len(lines) and lines[i + 1].strip():
            return True
    return False


def check(body: str | None, first_comment: str | None, author: str | None,
          closing_refs: list[int] | None = None) -> list[str]:
    """The problems with this PR, in order; an empty list is a pass.

    `closing_refs` is GitHub's OWN answer to "what will merging this close",
    from `closingIssuesReferences` (see `closing_issue_numbers`). When it is
    supplied it decides rule 1 outright -- the body text is only ever an
    approximation of what GitHub will actually close, and its own field is the
    thing that decides. `None` means it was not fetched (a local run, or the
    pre-merge body-only job), and then rule 1 falls back to reading the body,
    which still rejects the shorthand and `/pull/` forms and says which forms
    would have worked."""
    if author in EXEMPT_AUTHORS:
        return []
    if not body or not body.strip():
        return ["the PR body is empty: nothing to close an issue with, nothing to read"]
    problems: list[str] = []
    stated_no_issue = states_no_issue(body)
    if closing_refs is None:
        if not CLOSING.search(body) and not stated_no_issue:
            problems.append(
                "no closing keyword in the body -- GitHub honours exactly three forms: "
                "`Closes #N` (this repo), `Fixes owner/repo#N` (another repo), or "
                "`Resolves https://github.com/owner/repo/issues/N`. A repo-nickname "
                "shorthand such as `crm#447` or `tools#65` is NOT one of them: there is "
                "no slash, so GitHub reads it as plain text and closes nothing. Nor is a "
                "`.../pull/N` URL: that links a pull request, not an issue, so it closes "
                "nothing either. If this PR genuinely closes nothing, say so with a "
                "`No issue:` line carrying the reason -- on the same line "
                "(`No issue: dependency bump only`), or as a `## No issue:` heading with "
                "the reason in the line right below it.")
    elif not closing_refs and not stated_no_issue:
        problems.append(
            "GitHub will close no issue on merge: `closingIssuesReferences` is empty. "
            "That is GitHub's own answer, not a reading of the body, so it is final. A "
            "repo-nickname shorthand (`crm#N`), a cross-repo `owner/repo#N` (GitHub does "
            "not auto-close another repo's issue from a merge here), and a `.../pull/N` "
            "URL all read like a close but resolve to nothing in this repo. Use "
            "`Closes #N` for an issue in THIS repo, or state that it closes none with a "
            "`No issue:` line carrying the reason (same line, or a `## No issue:` heading "
            "with the reason right below it).")
    total = word_count(body) + word_count(first_comment)
    if total >= WORD_LIMIT:
        problems.append(
            f"the body plus the first comment is {total} words; the limit is under "
            f"{WORD_LIMIT} (body {word_count(body)}, first comment "
            f"{word_count(first_comment)})")
    for phrase, pattern in FORBIDDEN_ATTRIBUTION:
        found_in = [name for name, text in
                    (("the body", body), ("the first comment", first_comment))
                    if text and pattern.search(text)]
        if found_in:
            problems.append(
                f"{' and '.join(found_in)} carries a \"{phrase}\" line; no commit, pull "
                f"request or document carries an attribution line")
    return problems


def closing_issue_numbers(refs_json: str) -> list[int]:
    """The issue numbers GitHub will auto-close when this PR merges, from a
    `gh pr view N --json closingIssuesReferences` listing. This is GitHub's
    own resolution of the body's keywords, so a repo-nickname shorthand, a
    cross-repo `owner/repo#N` and a `/pull/N` URL are simply absent from it --
    which is exactly why it catches what body parsing cannot. Accepts either
    the `{"closingIssuesReferences": [...]}` wrapper `gh pr view` prints or a
    bare list; an empty list is a real answer (closes nothing), not an error.
    Raises on anything else so an absent input never reads as `closes nothing`."""
    data = json.loads(refs_json)
    if isinstance(data, dict):
        data = data.get("closingIssuesReferences", [])
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list or a closingIssuesReferences object, "
                         f"got {type(data).__name__}")
    numbers: list[int] = []
    for ref in data:
        if isinstance(ref, dict) and "number" in ref:
            numbers.append(int(ref["number"]))
    return numbers


def first_comment_body(comments_json: str) -> str | None:
    """The body of the earliest issue comment in a `gh api .../comments`
    listing, or None when the listing is empty. Raises on anything else."""
    data = json.loads(comments_json)
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list of comments, got {type(data).__name__}")
    if not data:
        return None
    return data[0].get("body") or ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", help="GITHUB_EVENT_PATH: a pull_request event JSON")
    ap.add_argument("--comments", help="JSON list from `gh api repos/O/R/issues/N/comments`")
    ap.add_argument("--closing-refs", dest="closing_refs",
                    help="JSON from `gh pr view N --json closingIssuesReferences`: GitHub's "
                         "own list of what merging closes. When given, it decides rule 1 "
                         "instead of the body text -- run it on a merged PR for the final word")
    ap.add_argument("--body-file", help="local use: a file holding the PR body")
    ap.add_argument("--comment-file", help="local use: a file holding the first comment")
    ap.add_argument("--author", default=None, help="local use: the PR author's login")
    args = ap.parse_args(argv)

    author = args.author
    first_comment: str | None = None
    closing_refs: list[int] | None = None
    comment_state = "first comment: not supplied (counted as 0 words)"
    refs_state = "closingIssuesReferences: not fetched (rule 1 read from the body)"
    try:
        if args.event:
            with open(args.event, encoding="utf-8") as fh:
                event = json.load(fh)
            pr = event.get("pull_request") or {}
            body = pr.get("body")
            author = (pr.get("user") or {}).get("login") or author
        elif args.body_file:
            with open(args.body_file, encoding="utf-8") as fh:
                body = fh.read()
        else:
            print("check_pr_body: give --event or --body-file", file=sys.stderr)
            return 2
        if args.comments:
            with open(args.comments, encoding="utf-8") as fh:
                first_comment = first_comment_body(fh.read())
            comment_state = ("first comment: none yet" if first_comment is None
                             else f"first comment: {word_count(first_comment)} words")
        elif args.comment_file:
            with open(args.comment_file, encoding="utf-8") as fh:
                first_comment = fh.read()
            comment_state = f"first comment: {word_count(first_comment)} words"
        if args.closing_refs:
            with open(args.closing_refs, encoding="utf-8") as fh:
                closing_refs = closing_issue_numbers(fh.read())
            refs_state = ("closingIssuesReferences: empty (GitHub closes nothing)"
                          if not closing_refs
                          else "closingIssuesReferences: "
                               + ", ".join(f"#{n}" for n in closing_refs))
    except (OSError, ValueError) as exc:
        print(f"check_pr_body: CANNOT EVALUATE -- {exc}", file=sys.stderr)
        return 2

    problems = check(body, first_comment, author, closing_refs)
    print(f"check_pr_body: author {author or '?'}; body {word_count(body)} words; "
          f"{comment_state}; {refs_state}; limit under {WORD_LIMIT} together")
    if author in EXEMPT_AUTHORS:
        print(f"check_pr_body: {author} is exempt (a bot's body is not ours to shape)")
        return 0
    if problems:
        for p in problems:
            print(f"::error::{p}")
        return 1
    linked = ("GitHub will close an issue" if closing_refs
              else "a closing keyword is present" if closing_refs is None
              else "a `No issue:` line explains why nothing is closed")
    print(f"check_pr_body: ok -- {linked}, length within the limit, no attribution line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
