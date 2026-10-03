#!/usr/bin/env python3
"""Run the reproducers for the open issues the consolidation turned up.

    python tools/known_issues.py

Three behaviours found while proving `fsg_common.sections` matches the two
resolvers it replaces. Issue 2 is not fixed here: this package consolidates
the two copies without moving an answer neither source had already agreed
on, and it changes an answer that is still an open estimator question.
Issues 1 and 3 are the exceptions -- 3 fixed 5 Sep 2026 because both
sources had already agreed on the same answer three days before this
package caught up (catching up to a decision already made, not making a
new one), and 1 fixed 7 Sep 2026 once fsg-tender-review#184 Q25 actually
answered the question this package had been carrying rather than settling.

This is a script rather than a prose list on purpose. A reproducing command
in a document goes stale silently the day someone fixes the thing it
describes, and nobody re-runs it. This one prints OBSERVED next to EXPECTED
every time, and says at the end whether each issue is still live, so the file
cannot quietly outlive its subject.

Exit 0 always. It reports, it does not gate -- `parity_report.py` is the
gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fsg_common import sections  # noqa: E402


def rule(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def issue_1_chs_wall() -> bool:
    """RESOLVED IN TWO STEPS -- 7 Sep 2026 (verdict) and 18 Sep 2026 (mass).
    Was the one notation the two source resolvers disagreed about -- item 1
    of FremantleSteel/fsg-tender-review#184, "Questions for the estimators".

    7 Sep 2026: David, relaying the estimating team's answer, converged both
    resolvers on `canonical` rather than a `RoundingPolicy` split
    (`_policy.py`, now deleted). That step only settled the VERDICT: the
    mass behind it was still `273CHS6.35` at 41.77 kg/m, the library's
    imperial figure, not the metric 6.40 wall the question asked about --
    `how != "canonical"` was the only check this reproducer made, so it
    reported RESOLVED for eleven days on the wrong number.

    18 Sep 2026: David confirmed the mass directly, "Confirm metric, 6.40".
    `_chs_metric_wall()` in `_resolver.py` now returns a synthesised
    `273CHS6.4` row at 42.1 kg/m (AS/NZS 1163 C350L0, not a hand-edit to
    the generated `data/fsg_sections.json`). This reproducer now checks the
    ID and the mass, not only the verdict word.
    """
    rule("1. `273 CHS 6.4` -- the open estimator question (RESOLVED 18 Sep 2026)")
    section, how = sections.resolve("273 CHS 6.4")
    print(f"  {section.section_id} @ {section.mass_kg_per_m} kg/m  -> {how!r}")
    print()
    print("  The library's ladder is imperial pipe (6.35); FSG's three most common")
    print("  archive walls are metric (3.2, 4.8, 6.4). The estimating team's answer:")
    print("  `CHS 6.4` means the metric wall, matching all 94 checkable archive")
    print("  lines (0 closer to imperial). Confirmed 18 Sep 2026: `273CHS6.4` @")
    print("  42.1 kg/m, not the library's own 41.77 imperial figure.")
    live = how != "canonical" or section.section_id != "273CHS6.4"
    print(f"\n  STILL LIVE: {live}   (True means the answer stopped applying -- check why)")
    return live


def issue_2_mass_of_floor_plate() -> bool:
    """`mass_of()` returns kg/m2 for floor plate through a per-metre API.

    Two callers in `fsg-tender-review` multiply the result by a length and
    neither guards on `is_plate`:

        assemble.py:525    (i.qty * i.length_m * (mass_of(i.section_id) or 0.0))
        doubleread.py:201  mass = mass_of(item.section_id) or 0.0

    `variation.TakeoffItem` carries `width_m` (variation.py:189) and neither
    expression uses it, so a floor-plate line is computed as
    `length_m x 49.1` -- correct only when the plate is one metre wide.
    """
    rule("2. `mass_of()` hands back an AREA mass for floor plate")
    got = sections.mass_of("6 mm FLOOR PLATE")
    sec, _ = sections.resolve("6 mm FLOOR PLATE")
    print("  mass_of('6 mm FLOOR PLATE')")
    print(f"    OBSERVED  {got}   (kg/m2, through an API documented per metre)")
    print("    EXPECTED  None    per mass_of's own docstring: 'None for a plate or")
    print("              anything else the library prices by area rather than by length'")
    print(f"    is_plate={sec.is_plate}  kg_per_m2={sec.kg_per_m2}  "
          f"mass_kg_per_m={sec.mass_kg_per_m}")
    print()
    print("  What the two callers compute for one 3.0 m x 2.4 m floor plate:")
    as_coded = 1 * 3.0 * (got or 0.0)
    correct = 3.0 * 2.4 * sec.kg_per_m2
    print(f"    qty * length_m * mass_of   = {as_coded:8.1f} kg   (width_m ignored)")
    print(f"    area * kg_per_m2           = {correct:8.1f} kg")
    print(f"    understated by             = {correct - as_coded:8.1f} kg")
    print()
    print("  The PL family fails the other way in the same two lines: mass_of returns")
    print("  None, `or 0.0` makes it zero, and the plate contributes nothing at all.")
    print(f"    mass_of('12 PL') = {sections.mass_of('12 PL')}  "
          f"(is_plate={sections.resolve('12 PL')[0].is_plate})")
    print()
    print("  NOT ESTABLISHED: whether a floor-plate line reaches either path with a")
    print("  width other than 1 m in a real reading. Both totals are internal checks,")
    print("  not the priced take-off -- which is less severe and more insidious,")
    print("  because a cross-check is trusted by construction.")
    live = got is not None
    print(f"\n  STILL LIVE: {live}")
    return live


def issue_3_ss_is_not_stainless() -> bool:
    """RESOLVED 5 Sep 2026. `_NON_STEEL` now lists `SS`/`S/S` alongside
    `STAINLESS`, matching both source resolvers -- see `_resolver.py`'s own
    comment. Kept as a reproducer rather than deleted: this is exactly the
    "a RESOLVED line means the behaviour changed since 3 Sep 2026, check it
    changed deliberately, then delete that reproducer" case this file's own
    docstring names, and it changed deliberately (both sources already
    agreed on the same answer three days before this package caught up)."""
    rule("3. `SS` is not recognised as stainless")
    rows = ["STAINLESS 10 ROD", "SS 10 ROD", "S/S 10 ROD", "STAINLESS STEEL 10 ROD"]
    live = False
    for raw in rows:
        sec, how = sections.resolve(raw)
        got = f"{sec.section_id} @ {sec.mass_kg_per_m} kg/m" if sec else "refused"
        print(f"    {raw!r:26} -> {how:18} {got}")
        if raw.upper().startswith("S") and "STAINLESS" not in raw.upper() and sec:
            live = True
    print()
    print("  Both source resolvers added `SS`/`S/S` to their own `_NON_STEEL` on")
    print("  3 Sep 2026, in step with each other. This package's port was taken")
    print("  before that same-day change landed, so it was a real (if brief) THIRD")
    print("  copy drifting behind the two it consolidates -- caught by this file's")
    print("  own reproducer and by tools/parity_report.py's live comparison,")
    print("  fixed 5 Sep 2026 by porting the same change.")
    print(f"\n  STILL LIVE: {live}")
    return live


def main() -> int:
    print("fsg-common -- known issues, re-derived live")
    print(f"library: {sections.vintage_line()}")
    results = [
        ("1  273 CHS 6.4, the open estimator question (verdict fixed 7 Sep, "
         "mass fixed 18 Sep 2026)",
         issue_1_chs_wall()),
        ("2  mass_of() returns kg/m2 for floor plate", issue_2_mass_of_floor_plate()),
        ("3  SS is not recognised as stainless (fixed 5 Sep 2026)",
         issue_3_ss_is_not_stainless()),
    ]
    rule("Summary")
    for name, live in results:
        print(f"  {'STILL LIVE' if live else 'RESOLVED  '}  {name}")
    print()
    print("  A RESOLVED line means the behaviour changed since 3 Sep 2026. Check")
    print("  that it changed deliberately, then delete that reproducer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
