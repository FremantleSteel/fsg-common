"""Git merge driver for scripts/commands_index.json -- union, not text-merge.

The one shared copy (crm#1719, slice 2, 1 Oct 2026). `scripts/merge_commands_index.py`
in crm, tools and tender-review is a thin wrapper over this; the three copies were
identical in code (AST diff 0 lines) and differed only in docstrings.

Measured 17 Sep 2026 (crm#788): four branches each filed exactly one new
`assign` entry in one evening, and every pair conflicted, because the JSON
grows by appending a line to the tail of the `assign` object -- the classic
same-anchor-point insertion two branches can never both win. Sorting alone
does not fix it: the two hardest real entries that night,
`apply_next_step_banner_20260917.py` and `apply_opportunity_defaults_20260917.py`,
sort ADJACENT to each other with nothing between them, so a plain three-way
text merge still collides even once the file is alphabetised. PR #779 needed
"take the union, then regenerate" by hand three times on one branch as `main`
kept moving underneath it.

This driver does that union mechanically, at the JSON level, not the text
level: it 3-way-merges `assign`, `aliases` and `groups` (by id) as maps, and
only ever produces a real conflict when both sides changed the SAME key to
DIFFERENT values -- a genuine disagreement about how one script should be
filed, which is correctly a human's decision and is left as one, with
`<<<<<<<`/`=======`/`>>>>>>>` markers wrapped around just that entry so the
ordinary conflict-resolution workflow (edit, pick one, delete the markers)
still works. Two branches adding two DIFFERENT new keys -- the case that hit
four times in one evening and has no real disagreement in it at all -- now
merges with no human step at all. The merged `assign`/`aliases` maps are
always written back sorted by key, which is itself a small mitigation
(non-adjacent new keys were already not colliding before this driver) but is
not the fix: two dated scripts from the same day still sort next to each
other, and it's exactly that case the union merge (not the sort) resolves.

Registration (`.gitattributes` alone cannot carry a driver's *command*, only
the *attribute* -- a documented git limitation):

    git config --local merge.commands-index-union.driver \\
        "python scripts/merge_commands_index.py %O %A %B"

`.githooks/pre-commit` runs this idempotently on every commit in this repo
(`core.hooksPath` is repo-level, so one commit anywhere in this clone's
worktree family registers it for all of them -- see CLAUDE.md). A fresh,
separate clone that has never run this repo's pre-commit hook falls back to
git's ordinary three-way text merge, i.e. today's behaviour, not something
worse: this driver only ever REPLACES a conflict with a clean merge, never
the reverse. CI never merges branches (`gen_commands_index.py --check` runs
against an already-checked-out tree), so it needs nothing registered.

Does not touch `docs/COMMANDS.md`: that file is 100% generated from this one
plus the tracked script tree, so `.githooks/pre-commit` regenerates it
unconditionally during a merge commit instead of trying to merge it as text
at all -- see the "mid-merge" branch of that hook.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

MARK_OURS = "<<<<<<< ours (%A)"
MARK_MID = "======="
MARK_THEIRS = ">>>>>>> theirs (%B)"

_ABSENT = object()  # distinct from JSON `null`, which this file uses ("package")


def load(path: str) -> dict[str, Any] | None:
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def dict3(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[tuple[str, Any, Any]]]:
    """3-way merge of a flat mapping. Returns (merged, conflicts).

    A conflict is a key both sides changed (or one changed and the other
    deleted) to DIFFERENT results. Anything else -- an add on one side only,
    an identical change on both, a change on one side with the other
    untouched -- resolves without a human.
    """
    merged: dict[str, Any] = {}
    conflicts: list[tuple[str, Any, Any]] = []
    keys = set(base) | set(ours) | set(theirs)
    for key in keys:
        b = base.get(key, _ABSENT)
        o = ours.get(key, _ABSENT)
        t = theirs.get(key, _ABSENT)
        if o == t:
            if o is not _ABSENT:
                merged[key] = o
            continue  # both deleted it, or both never had it, or agree
        if o == b:
            if t is not _ABSENT:
                merged[key] = t
            continue  # ours didn't touch it; take theirs (add/change/delete)
        if t == b:
            if o is not _ABSENT:
                merged[key] = o
            continue  # theirs didn't touch it; take ours
        conflicts.append((key, o, t))
    return merged, conflicts


def merge_groups(base: list, ours: list, theirs: list) -> tuple[list, list[tuple[str, Any, Any]]]:
    """Groups are a list, but `id` is the real key -- merge as an id-map,
    then rebuild list order (base order first, then any new ids appended
    ours-then-theirs, deduplicated)."""
    def by_id(seq: list) -> dict[str, dict]:
        return {g["id"]: g for g in seq}

    b, o, t = by_id(base), by_id(ours), by_id(theirs)
    merged_map, conflicts = dict3(b, o, t)
    order: list[str] = []
    seen: set[str] = set()
    for src in (base, ours, theirs):
        for g in src:
            if g["id"] not in seen and g["id"] in merged_map:
                order.append(g["id"])
                seen.add(g["id"])
    return [merged_map[i] for i in order], conflicts


def ordered_top_keys(base: dict, ours: dict, theirs: dict) -> list[str]:
    order: list[str] = []
    for src in (base, ours, theirs):
        for k in src:
            if k not in order:
                order.append(k)
    return order


def render(top_order: list[str], scalars: dict, groups: list,
           assign: dict, aliases: dict,
           assign_conflicts: list[tuple[str, Any, Any]],
           alias_conflicts: list[tuple[str, Any, Any]]) -> str:
    """Build valid JSON via `json.dumps`, then splice in conflict markers.

    A conflicting key gets a UUID sentinel value from `json.dumps` (so the
    surrounding document is always well-formed JSON up to that point) and the
    one line holding the sentinel is replaced with the marker block
    afterwards -- text surgery is confined to single, uniquely-identified
    lines instead of hand-tracking braces and commas.
    """
    sentinels: dict[str, tuple[Any, Any]] = {}
    assign_out = dict(sorted(assign.items()))
    for key, ov, tv in assign_conflicts:
        token = f"__CONFLICT_{uuid.uuid4().hex}__"
        assign_out[key] = token
        sentinels[token] = (key, ov, tv, "assign")
    aliases_out = dict(sorted(aliases.items()))
    for key, ov, tv in alias_conflicts:
        token = f"__CONFLICT_{uuid.uuid4().hex}__"
        aliases_out[key] = token
        sentinels[token] = (key, ov, tv, "aliases")

    doc: dict[str, Any] = {}
    for key in top_order:
        if key == "groups":
            doc[key] = groups
        elif key == "assign":
            doc[key] = dict(sorted(assign_out.items()))
        elif key == "aliases":
            doc[key] = dict(sorted(aliases_out.items()))
        elif key in scalars:
            doc[key] = scalars[key]

    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

    for token, (key, ov, tv, _section) in sentinels.items():
        needle = f'"{token}"'
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if needle in line:
                trailing_comma = line.rstrip("\n").endswith(",")
                comma = "," if trailing_comma else ""
                block = [
                    f"{MARK_OURS}\n",
                    f'    "{key}": {json.dumps(ov)}{comma}\n' if ov is not None else "",
                    f"{MARK_MID}\n",
                    f'    "{key}": {json.dumps(tv)}{comma}\n' if tv is not None else "",
                    f"{MARK_THEIRS}\n",
                ]
                lines[i:i + 1] = [b for b in block if b]
                break
        text = "".join(lines)
    return text


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: merge_commands_index.py <base> <ours> <theirs>", file=sys.stderr)
        return 2
    base_path, ours_path, theirs_path = argv[0], argv[1], argv[2]

    base = load(base_path) or {}
    ours = load(ours_path)
    theirs = load(theirs_path)
    if ours is None or theirs is None:
        print("merge_commands_index: one side is not valid JSON -- falling back "
              "to an ordinary text conflict.", file=sys.stderr)
        return 1  # leave %A as git's own textual merge attempt; refuse to guess

    assign, assign_conflicts = dict3(base.get("assign", {}), ours.get("assign", {}),
                                      theirs.get("assign", {}))
    aliases, alias_conflicts = dict3(base.get("aliases", {}), ours.get("aliases", {}),
                                      theirs.get("aliases", {}))
    groups, group_conflicts = merge_groups(base.get("groups", []), ours.get("groups", []),
                                            theirs.get("groups", []))

    scalar_keys = (set(base) | set(ours) | set(theirs)) - {"assign", "aliases", "groups"}
    scalars: dict[str, Any] = {}
    scalar_conflicts: list[tuple[str, Any, Any]] = []
    for key in scalar_keys:
        b_map = {key: base[key]} if key in base else {}
        o_map = {key: ours[key]} if key in ours else {}
        t_map = {key: theirs[key]} if key in theirs else {}
        merged, conflicts = dict3(b_map, o_map, t_map)
        if key in merged:
            scalars[key] = merged[key]
        scalar_conflicts.extend(conflicts)

    if group_conflicts or scalar_conflicts:
        # Rare (groups/top-level scalars almost never change concurrently);
        # refuse rather than invent a resolution for structure this driver
        # doesn't specialise in rendering as inline markers.
        print("merge_commands_index: conflict outside assign/aliases "
              f"({len(group_conflicts)} group(s), {len(scalar_conflicts)} scalar(s)) "
              "-- resolve by hand.", file=sys.stderr)
        return 1

    top_order = ordered_top_keys(base, ours, theirs)
    text = render(top_order, scalars, groups, assign, aliases,
                  assign_conflicts, alias_conflicts)
    Path(ours_path).write_text(text, encoding="utf-8", newline="\n")

    if assign_conflicts or alias_conflicts:
        for key, ov, tv in assign_conflicts:
            print(f"merge_commands_index: CONFLICT assign[{key!r}]: "
                  f"ours={ov!r} theirs={tv!r}", file=sys.stderr)
        for key, ov, tv in alias_conflicts:
            print(f"merge_commands_index: CONFLICT aliases[{key!r}]: "
                  f"ours={ov!r} theirs={tv!r}", file=sys.stderr)
        print("Resolve the marked entries by hand, then `git add "
              "scripts/commands_index.json` and continue the merge.", file=sys.stderr)
        return 1

    n_added = len(assign) - len(base.get("assign", {}) or {})
    print(f"merge_commands_index: assign merged cleanly "
          f"({len(assign)} entries, net +{n_added} vs base); aliases merged cleanly "
          f"({len(aliases)} entries). Regenerate docs/COMMANDS.md next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
