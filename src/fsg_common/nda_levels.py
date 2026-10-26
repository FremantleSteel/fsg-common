"""The NDA levels table: one source for every FSG repo (crm#2260 steps 1 and 3).

The owner's decision D1 = A (Desk v81, 13 Oct 2026): one levels table, here;
fsg-estimating-crm and fsg-tender-review import it instead of keeping copies.
Before this, crm `scripts/lib/nda_gate.py`, tr `nda.py`, `text_index.py` and
two destruction lists each carried the table and tests held them equal.

**The values are the CRM's `Opportunity.cNdaDetermination` options**, in the
enum's order. Each one carries its level, its verdict for each AI use, and
what the destruction tools may do at it:

    Value                            level        hosted            local            destruction
    Under review                     not decided  CANNOT_EVALUATE   PERMIT           person
    No NDA                           ordinary     PERMIT            PERMIT           tool
    Unrestricted                     ordinary     PERMIT            PERMIT           tool
    Approval received                ordinary     PERMIT            PERMIT           tool
    Restricted                       restricted   REFUSE            PERMIT           held
    Defence - restricted             defence      REFUSE_ABSOLUTE   PERMIT           person

**"Under review" permits a local read** (tr#1125, 26 Oct 2026; the owner's
Desk answer: "A: Bring the others into line with the local lane, in the
shared levels table (recommended)"). It applies tender-review ADR 49: nobody
has set the level yet, which is a reason not to send the material to a
hosted model, not a reason to stop FSG's own hardware reading it. Hosted
still refuses it (CANNOT_EVALUATE), the level is still "not decided", and the
destruction tools still send it to a person. A caller that needs "has a
person decided?" asks `level_of()`, never the local column.

**Six values, not eight** (D3 = A, crm#2260 step 3, 13 Oct 2026).
"Approval in progress" (the same verdicts as Restricted: a task state, not a
level) and "NDA not applicable to this job" (refused both uses, yet the
purge treated it as No NDA) are gone. They are listed in `RETIRED_VALUES`
for messages only: neither has a verdict, a level or a mapping here, so a
record still carrying one refuses like any unknown value until the crm
migration card rewrites it, with a person's YES.

Asked by the caller, because they are not properties of the value:

- `Approval received` needs an approval reference before a hosted use
  (`HOSTED_NEEDS_APPROVAL_REFERENCE`).
- The NDA record's "automated processing prohibited" box, ticked, refuses
  both uses at every level. Unticked or not recorded does not stop a local
  read (D2 = A, crm#2260, tender-review ADR 45); `clears_local()` is that rule.

**An absent input never answers.** A value not in the table (blank, None,
wrong case, a list, a renamed option) has no verdict and no level: `verdict()`
returns None, `permits()` and `clears_local()` return False, and the
destruction tools send it to a person. A use nobody wrote down raises.

`data/nda_levels.json` is generated from this file for the consumers that
cannot import Python (the n8n Code nodes' tests). Regenerate it with
`python -m fsg_common.nda_levels --write`; `--check` exits 1 when it differs.
`tests/test_nda_levels.py` fails when the two disagree.

Standard library only: crm's system1-svc image copies this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import MappingProxyType

# --- the values (Opportunity.cNdaDetermination, in the enum's order) --------
UNDER_REVIEW = "Under review"
NO_NDA = "No NDA"
UNRESTRICTED = "Unrestricted"
APPROVAL_RECEIVED = "Approval received"
RESTRICTED = "Restricted"
DEFENCE_RESTRICTED = "Defence - restricted"

# Removed by D3 = A (crm#2260 step 3). Not values: no verdict, no level, no
# mapping. A record holding one refuses as unknown and goes to a person.
RETIRED_VALUES = ("Approval in progress", "NDA not applicable to this job")

# --- the two AI uses ---------------------------------------------------------
HOSTED_AI = "hosted-ai"   # a model run by a third party
LOCAL_AI = "local-ai"     # a model on FSG-controlled hardware
USES = (HOSTED_AI, LOCAL_AI)

# --- verdict kinds -----------------------------------------------------------
# Four kinds, not two, because two must be told apart from a plain refusal:
# CANNOT_EVALUATE (nobody has decided; send the operator to do the review) and
# REFUSE_ABSOLUTE (no approval turns this into a permit). Callers branch on
# `permits()` only; the kind is for what the operator is told.
PERMIT = "PERMIT"
REFUSE = "REFUSE"
CANNOT_EVALUATE = "CANNOT_EVALUATE"
REFUSE_ABSOLUTE = "REFUSE_ABSOLUTE"
KINDS = (PERMIT, REFUSE, CANNOT_EVALUATE, REFUSE_ABSOLUTE)

# --- levels ------------------------------------------------------------------
LEVEL_NOT_DECIDED = "not decided"
LEVEL_ORDINARY = "ordinary"
LEVEL_RESTRICTED = "restricted"
LEVEL_DEFENCE = "defence"

# --- what the destruction tools may do (crm#2203, crm#2198, crm#2206) -------
DESTROY_TOOL = "tool"      # the tool may act
DESTROY_HELD = "held"      # held for a person until the owner decides
DESTROY_PERSON = "person"  # always a person: not decided, or defence material

_ROWS = (
    # value,                 level,              hosted,          local,           destruction
    # Local PERMIT since tr#1125 (tender-review ADR 49); hosted unchanged.
    (UNDER_REVIEW,           LEVEL_NOT_DECIDED,  CANNOT_EVALUATE, PERMIT,          DESTROY_PERSON),
    (NO_NDA,                 LEVEL_ORDINARY,     PERMIT,          PERMIT,          DESTROY_TOOL),
    (UNRESTRICTED,           LEVEL_ORDINARY,     PERMIT,          PERMIT,          DESTROY_TOOL),
    (APPROVAL_RECEIVED,      LEVEL_ORDINARY,     PERMIT,          PERMIT,          DESTROY_TOOL),
    # Hosted starts the approval letter process. Local inference is not a
    # disclosure to a third party (tender-review ADR 8).
    (RESTRICTED,             LEVEL_RESTRICTED,   REFUSE,          PERMIT,          DESTROY_HELD),
    # tender-review ADR 43: the tightest level of the same process.
    (DEFENCE_RESTRICTED,     LEVEL_DEFENCE,      REFUSE_ABSOLUTE, PERMIT,          DESTROY_PERSON),
)

VALUES = tuple(r[0] for r in _ROWS)
KNOWN_VALUES = frozenset(VALUES)
LEVELS = MappingProxyType({r[0]: r[1] for r in _ROWS})
VERDICTS = MappingProxyType({
    r[0]: MappingProxyType({HOSTED_AI: r[2], LOCAL_AI: r[3]}) for r in _ROWS})
DESTRUCTION = MappingProxyType({r[0]: r[4] for r in _ROWS})
TOOL_LEVELS = tuple(v for v in VALUES if DESTRUCTION[v] == DESTROY_TOOL)
HELD_LEVELS = tuple(v for v in VALUES if DESTRUCTION[v] == DESTROY_HELD)

HOSTED_NEEDS_APPROVAL_REFERENCE = frozenset({APPROVAL_RECEIVED})


def _value(determination) -> str | None:
    """The table key for a stored value, or None. Surrounding whitespace is
    dropped (a padded import is the same value); anything that is not a
    string, and any other spelling, is not a value."""
    if not isinstance(determination, str):
        return None
    text = determination.strip()
    return text if text in KNOWN_VALUES else None


def _use(use) -> str:
    if use not in USES:
        raise ValueError(f"unknown use {use!r}; expected one of {USES}")
    return use


def verdict(determination, use: str) -> str | None:
    """The verdict kind for this value and use, or None for anything that is
    not a value in the table. An unknown `use` raises: answering it would be
    a default."""
    use = _use(use)
    value = _value(determination)
    return None if value is None else VERDICTS[value][use]


def permits(determination, use: str) -> bool:
    """Whether this value allows `use`. Not in the table refuses. `use` has
    no default."""
    return verdict(determination, use) == PERMIT


def permitted_for(use: str) -> frozenset[str]:
    """The exact values that permit `use`."""
    use = _use(use)
    return frozenset(v for v in VALUES if VERDICTS[v][use] == PERMIT)


def level_of(determination) -> str | None:
    """The level an exact value sits at, or None for one not in the table."""
    if not isinstance(determination, str):
        return None
    return LEVELS.get(determination)


def clears_local(determination, *, automated_processing_prohibited) -> bool:
    """The local-AI answer once the NDA record's box is known, or not.

    - True refuses at every level.
    - False, or None (no NDA record carries the box), gives the table's
      local answer. Since 13 Oct 2026 (D2 = A, crm#2260, tender-review
      ADR 45) None no longer refuses Restricted and Defence - restricted.
    - Anything else is not an answer and refuses.

    The value itself is still required: blank and anything not in the table
    refuse. Under review clears like any value whose local column permits
    (tr#1125, ADR 49), unless the box is ticked. The keyword has no default,
    so every caller states which case it is in.
    """
    if automated_processing_prohibited is not None and not isinstance(
            automated_processing_prohibited, bool):
        return False
    if automated_processing_prohibited is True:
        return False
    return permits(determination, LOCAL_AI)


def destruction(determination) -> str:
    """What a destruction tool may do at this exact value. Anything not in the
    table goes to a person."""
    if not isinstance(determination, str):
        return DESTROY_PERSON
    return DESTRUCTION.get(determination, DESTROY_PERSON)


# --- the generated JSON ------------------------------------------------------
JSON_PATH = Path(__file__).resolve().parent / "data" / "nda_levels.json"


def as_document() -> dict:
    """The table as the JSON file carries it."""
    return {
        "generated_by": "python -m fsg_common.nda_levels --write (never edit by hand)",
        "uses": list(USES),
        "values": [
            {"value": v, "level": LEVELS[v], HOSTED_AI: VERDICTS[v][HOSTED_AI],
             LOCAL_AI: VERDICTS[v][LOCAL_AI], "destruction": DESTRUCTION[v]}
            for v in VALUES],
        "hosted_needs_approval_reference": sorted(HOSTED_NEEDS_APPROVAL_REFERENCE),
        "retired_values_refuse": list(RETIRED_VALUES),
        "automated_processing_prohibited_true_refuses": list(USES),
    }


def render() -> str:
    return json.dumps(as_document(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """`--write` regenerates the JSON; `--check` exits 1 when it differs or is
    missing. One of the two is required."""
    args = sys.argv[1:] if argv is None else argv
    if args == ["--write"]:
        JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(render(), encoding="utf-8", newline="\n")
        print(f"wrote {JSON_PATH}")
        return 0
    if args == ["--check"]:
        try:
            on_disk = JSON_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read {JSON_PATH}: {exc}")
            return 1
        if on_disk != render():
            print(f"{JSON_PATH} differs from the table; run "
                  f"python -m fsg_common.nda_levels --write")
            return 1
        print(f"{JSON_PATH} matches the table")
        return 0
    print("usage: python -m fsg_common.nda_levels --write | --check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
