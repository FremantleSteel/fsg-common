"""Estimator-authored notation substitutions -- a size a drawing states that
`90_Lists` genuinely does not carry, which an estimator has decided to price
as a *different*, real library size.

## Why this exists, and why it is not a resolver rule

`114.3 CHS x 4.8mm` is not a standard size; FSG buys `114.3 CHS x 4.5mm`
instead. `resolve.py` will never guess that on its own -- a resolver that
silently substitutes one wall thickness for another the moment it can't find
an exact match is exactly the kind of guess `CLAUDE.md` forbids, and it would
turn every future genuine miss into a plausible-looking wrong number instead
of an honest "not carried". The substitution is a business decision an
estimator made for *this specific size*, not a pattern `resolve.py` could
safely generalise (a `+0.3mm` rule would misprice the next size that really
is missing).

So this stays a **named, dated, attributed list** an estimator owns
(`data/substitutions.json`) -- the same shape as the workbook's other
operator-authored files -- and `resolve.SectionLibrary.resolve()` consults it
only after every other path (exact, canonical, nearest, cold-formed) has
already failed to find the real, drawn-as-stated section. A hit is reported
as `how="substitution"`, never folded into `"exact"`/`"canonical"`: the
drawing still said 4.8mm, and every caller downstream (`pagedata.py`'s
findings register, `workbook_export.py`'s Notes column) must go on saying so.

## Adding an entry

Edit `data/substitutions.json` directly -- `from`/`to` are section notations
(matched via `resolve.loose_key`, so spacing/case/separators don't matter;
`to` must be a real, existing library `Section_ID`), plus `reason`,
`decided_by`, `date` (ISO), and `source` (where the decision is recorded, for
an audit trail back to the actual estimator answer). One entry so far --
28 Aug 2026, Q4 of `fsg-estimating-tools/docs/questions-for-estimators.md`.
"""

from __future__ import annotations

import functools
import json
import os
from dataclasses import dataclass

from ._resolver import canonical_candidates, loose_key

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "substitutions.json")


@dataclass(frozen=True)
class Substitution:
    from_notation: str
    to_section_id: str
    reason: str
    decided_by: str
    date: str
    source: str

    def describe(self) -> str:
        return (f"substituted to {self.to_section_id} -- {self.reason} "
                f"({self.decided_by}, {self.date}, {self.source})")


@functools.lru_cache(maxsize=1)
def _load() -> dict:
    with open(DATA_FILE, encoding="utf-8") as fh:
        return json.load(fh)


@functools.lru_cache(maxsize=1)
def _by_key() -> dict[str, Substitution]:
    return {
        loose_key(s["from"]): Substitution(
            from_notation=s["from"], to_section_id=s["to"], reason=s["reason"],
            decided_by=s["decided_by"], date=s["date"], source=s["source"])
        for s in _load()["substitutions"]
    }


def lookup(raw: str) -> Substitution | None:
    """A substitution matching `raw` exactly, or None."""
    return _by_key().get(loose_key(raw))


def lookup_any(raw: str) -> Substitution | None:
    """A substitution matching `raw`, or any of its canonical candidates --
    the same "raw, then candidates" order `SectionLibrary.resolve()` checks
    every other path in. The one place this notation grammar is shared with
    `resolve.py`, so a caller wanting the human-readable reason for a
    `how="substitution"` result (e.g. `workbook_export.py`'s Notes column)
    finds the same match `resolve()` itself did, not a narrower one."""
    hit = lookup(raw)
    if hit is not None:
        return hit
    for candidate in canonical_candidates(raw):
        hit = lookup(candidate)
        if hit is not None:
            return hit
    return None


@dataclass(frozen=True)
class VendorEquivalence:
    vendors: tuple[str, ...]
    applies_to: str
    decided_by: str
    date: str
    source: str


@functools.lru_cache(maxsize=1)
def vendor_equivalences() -> tuple[VendorEquivalence, ...]:
    """The estimators' recorded vendor equivalences (STR/LYS, 30 Sep 2026).

    A recorded decision, not a resolver input by itself: `_resolver` carries
    `COLD_FORMED_VENDORS` and a test pins the two together, so the decision
    and the code cannot drift apart unseen."""
    return tuple(
        VendorEquivalence(vendors=tuple(e["vendors"]), applies_to=e["applies_to"],
                          decided_by=e["decided_by"], date=e["date"],
                          source=e["source"])
        for e in _load().get("vendor_equivalences", []))
