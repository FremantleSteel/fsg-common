"""The section library's write guard: a check cannot save you from a bad write.

Why this file exists
--------------------
`refresh_from_workbook.py --check` reported "up to date" immediately AFTER a
bad regeneration, and it was telling the truth. `--check` is a **consistency**
check -- "does the committed copy match what I would generate now" -- so when
both sides are bad they agree and it says so. It is not broken and it is not
lying; it answers a different question from the one people read it as.

Demonstrated by construction (wt-parallel-f6, 1 Sep 2026), an openpyxl
round-trip of the workbook against the Excel-written original:

    GOOD  733 sections,  77 masses None (10%),  310UB40 = 40.4
    BAD   733 sections, 730 masses None (99%),  310UB40 = None
    committed(bad) vs BAD  ->  UP TO DATE       <- the fail-open

**The section count is identical in both, so counting rows catches nothing** --
that is the obvious guard and it does not work. These tests pin the two that do,
and pin that the count does not.

**The first version of the guard had a fail-open of its own, closed by David on
1 Sep 2026.** It exempted the whole `PL` category from needing a mass, having
measured that every `PL` row in today's library is area-priced. His answer:
*"floor plate is priced by the m2 and other plate by the weight. There are
other types of plate that are also priced by m2 I cant remember them all."*
So a weight-priced plate row whose mass had been lost would have been waved
through -- the exact thing the guard exists to catch. The rule is now keyed on
the pricing BASIS rather than the category, which also means it does not need
the list of m2-priced plate types that nobody has.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import refresh_from_workbook as R  # noqa: E402


def _section(sid, category, mass, area=None):
    return {"section_id": sid, "category": category, "mass_kg_per_m": mass,
            "plate_thickness_mm": None, "plate_kg_per_m2": area}


def _good(n_typ=20):
    """A payload shaped like the real one: 656 per-metre, 72 per-m2, and five
    CUSTOM placeholders with no basis at all."""
    rows = [_section(f"TYP{i}", "TYP", 10.0 + i) for i in range(n_typ)]
    rows += [_section(f"PL{i}", "PL", None, area=78.5) for i in range(8)]
    rows += [_section(f"BIS{i}", "BIS", None, area=78.5) for i in range(4)]
    # David, 1 Sep 2026: "floor plate is priced by the m2 and other plate by
    # the weight". So a PL row with a per-metre mass and no area is CORRECT.
    rows += [_section(f"PLW{i}", "PL", 61.6) for i in range(3)]
    rows += [_section(f"CUSTOM{i}", "CUSTOM", None) for i in range(1, 6)]
    rows.append(_section("310UB40", "TYP", 40.4))
    rows.append(_section("200PFC", "TYP", 22.9))
    return {"sections": rows}


def test_a_good_payload_is_written():
    assert R.validation_failures(_good()) == []


def test_area_priced_rows_may_have_no_per_metre_mass():
    """72 of the real 733 rows are priced by m2 and have no kg/m. A guard that
    refused them would refuse every correct regeneration."""
    payload = _good()
    assert any(s["category"] == "PL" and s["mass_kg_per_m"] is None
               and s["plate_kg_per_m2"] is not None
               for s in payload["sections"])
    assert R.validation_failures(payload) == []


def test_plate_is_not_one_pricing_basis():
    """David, 1 Sep 2026: "floor plate is priced by the m2 and other plate by
    the weight. There are other types of plate that are also priced by m2 I
    cant remember them all."

    So a PL row carrying a per-metre mass and no area is correct, and a guard
    keyed on the CATEGORY would have to know which plate is which. This one is
    keyed on the BASIS instead, so it does not need that list -- which is as
    well, because nobody has it.
    """
    payload = _good()
    assert any(s["category"] == "PL" and s["mass_kg_per_m"] is not None
               for s in payload["sections"])
    assert R.validation_failures(payload) == []


def test_a_weight_priced_plate_row_losing_its_mass_is_REFUSED():
    """The fail-open in this guard's first version. It exempted the whole PL
    category from needing a mass, on the measured observation that every PL row
    in today's library is area-priced -- so a weight-priced plate row whose
    mass had been lost would have been waved through, which is the exact thing
    the guard exists to catch."""
    payload = _good()
    for s in payload["sections"]:
        if s["section_id"].startswith("PLW"):
            s["mass_kg_per_m"] = None
    problems = R.validation_failures(payload)
    assert problems, "a weight-priced plate row lost its mass and was accepted"


def test_an_m2_priced_plate_row_losing_its_area_is_REFUSED():
    payload = _good()
    for s in payload["sections"]:
        if s["category"] == "PL" and s["plate_kg_per_m2"] is not None:
            s["plate_kg_per_m2"] = None
    assert R.validation_failures(payload)


def test_the_custom_placeholders_are_allowed_by_NAME_not_by_category():
    """CUSTOM1..5 are the only legitimate no-basis rows. A real section that
    lands in CUSTOM still has to carry a basis."""
    payload = _good()
    assert R.validation_failures(payload) == []
    payload["sections"].append(_section("CUSTOM-REAL", "CUSTOM", None))
    assert R.validation_failures(payload)


def test_the_openpyxl_round_trip_is_refused():
    """The actual defect: formulas read as text, so every mass becomes None."""
    payload = _good()
    for s in payload["sections"]:
        s["mass_kg_per_m"] = None
    for s in payload["sections"]:
        s["plate_kg_per_m2"] = None      # a density product, also a formula
    problems = R.validation_failures(payload)
    assert problems, "the bad regeneration was accepted"
    assert any("no pricing basis" in p.lower() for p in problems)


def test_the_row_COUNT_is_not_the_guard():
    """Both payloads have identical section counts. A count check passes the
    bad one, which is why it is not the guard."""
    good, bad = _good(), _good()
    for s in bad["sections"]:
        s["mass_kg_per_m"] = None
    assert len(good["sections"]) == len(bad["sections"])
    assert R.validation_failures(good) == []
    assert R.validation_failures(bad) != []


def test_a_partial_corruption_that_spares_the_anchors_is_still_refused():
    """The structural rule catches what an anchor set alone would miss."""
    payload = _good()
    for s in payload["sections"]:
        if s["category"] == "TYP" and s["section_id"].startswith("TYP"):
            s["mass_kg_per_m"] = None
    assert R.validation_failures(payload)


def test_a_corruption_that_spares_the_structure_is_caught_by_the_anchors():
    """And the anchors catch what the structural rule alone would miss: every
    row has A mass, but the wrong one."""
    payload = _good()
    for s in payload["sections"]:
        if s["section_id"] == "310UB40":
            s["mass_kg_per_m"] = 1.0
    problems = R.validation_failures(payload)
    assert any("310UB40" in p for p in problems), problems


def test_a_missing_anchor_is_refused():
    payload = _good()
    payload["sections"] = [s for s in payload["sections"]
                           if s["section_id"] != "200PFC"]
    assert any("200PFC" in p for p in R.validation_failures(payload))


def test_an_empty_read_is_refused_rather_than_written_as_an_empty_library():
    assert R.validation_failures({"sections": []}) == [
        "the workbook produced no sections at all"]


# --- fsg-common#42: a hand-kept `source` survives regeneration -------------

def _row(sid, mass, **kw):
    return {**_section(sid, "TYP", mass), "build_default": "Stick", **kw}


def test_a_source_is_carried_forward_while_the_row_is_unchanged():
    committed = {"sections": [_row("LYS-C10010", 1.78, source="cite")]}
    fresh = {"sections": [_row("LYS-C10010", 1.78), _row("310UB40", 40.4)]}
    out, dropped = R.carry_sources(fresh, committed)
    by = {s["section_id"]: s for s in out["sections"]}
    assert by["LYS-C10010"]["source"] == "cite"
    assert "source" not in by["310UB40"]
    assert dropped == []


def test_a_changed_row_loses_its_source_and_says_so():
    """Control for the carry above: the same code must still refuse when the
    mass moved, or the carry is just 'always copy'."""
    committed = {"sections": [_row("LYS-C10010", 1.78, source="cite")]}
    fresh = {"sections": [_row("LYS-C10010", 1.90)]}
    out, dropped = R.carry_sources(fresh, committed)
    assert "source" not in out["sections"][0]
    assert len(dropped) == 1 and "LYS-C10010" in dropped[0]


def test_a_cited_row_gone_from_the_workbook_is_reported():
    committed = {"sections": [_row("GONE", 1.0, source="cite")]}
    _out, dropped = R.carry_sources({"sections": [_row("310UB40", 40.4)]},
                                    committed)
    assert len(dropped) == 1 and "GONE" in dropped[0]


def test_no_committed_copy_carries_nothing_and_does_not_fail():
    out, dropped = R.carry_sources({"sections": [_row("A", 1.0)]}, None)
    assert dropped == [] and "source" not in out["sections"][0]


def test_the_source_is_inside_the_hashed_body():
    """`--check` compares the hash, so a carried source must move it."""
    a = R.with_provenance({"sections": [_row("A", 1.0)]}, "w.xlsx")
    b = R.with_provenance({"sections": [_row("A", 1.0, source="x")]}, "w.xlsx")
    assert a["_provenance"]["content_sha256"] != b["_provenance"]["content_sha256"]
