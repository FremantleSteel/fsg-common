"""FSG's section record: one row of `90_Lists`, as both twins modelled it.

Identical in both source repos -- same six fields, same two properties, same
values -- and verified so by `tests/test_section_shape.py`. The two copies
were `fsg-tender-review`'s `classification.Section` and the Bluebeam
toolkit's `fsg_mto.sections.Section`; the toolkit's docstrings said outright
that it mirrored the other.

The fields come straight from `90_Lists` via
`scripts/refresh_from_workbook.py`. `mass_kg_per_m` is None for a section
priced by area rather than by length -- read `kg_per_m2` for those, and
`is_plate` to know which you have.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    section_id: str
    category: str
    build_default: str
    mass_kg_per_m: float | None
    plate_thickness_mm: float | None
    plate_kg_per_m2: float | None
    source: str | None = None
    """`None` for every ordinary `90_Lists` row. Set only where the mass came
    from somewhere else entirely -- a manufacturer's own published table,
    cited here as a plain string (table name, URL, date read), never a term
    or a client figure. tools#64's four purlin profiles are the first use:
    `90_Lists` and FSG's own detailer archive had no mass for them at all."""

    @property
    def is_plate(self) -> bool:
        """Priced by area, not by length.

        Two families. `PL`/`BPL` rows carry `plate_kg_per_m2` in 90_Lists's
        own plate column. Floor plate (`FP`) does not: its kg/m2 sits in the
        kg/m column with the plate column blank -- deliberate, per the
        estimating team (28 Aug 2026, Q2/Q3: "floor plate and platework
        should be calculated in kg/m2"). Before this property knew that, a
        `6FP` line was `length x 49.1` as though 49.1 were per metre.
        """
        return self.plate_kg_per_m2 is not None or self.section_id.upper().endswith("FP")

    @property
    def kg_per_m2(self) -> float | None:
        """The area mass, whichever column 90_Lists filed it in. None for a
        length-priced section."""
        if self.plate_kg_per_m2 is not None:
            return self.plate_kg_per_m2
        if self.section_id.upper().endswith("FP"):
            return self.mass_kg_per_m
        return None
