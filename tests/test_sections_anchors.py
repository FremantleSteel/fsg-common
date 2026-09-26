"""The behaviours `fsg-tender-review/CLAUDE.md` names, pinned as assertions.

`test_sections_parity.py` proves this package answers what the two source
resolvers answer. That is agreement, not correctness, and the two come
apart: `10 SQ ROD` and `M30 THREADED ROD` were wrong in BOTH resolvers for
months while every parity check passed, because neither token was in the
vocabulary being compared.

So these tests do the other half. Each one states the rule from CLAUDE.md
and checks the answer against it, so a change that moves both copies the
same wrong way still goes red here.
"""
from __future__ import annotations

import pytest
from vocabulary import ANCHORS, OBSERVED_GAPS

from fsg_common import sections


def test_the_library_loaded_at_all():
    """A resolver over an empty library resolves nothing and reports it as an
    honest miss, so every test below would pass green against no data."""
    lib = sections.library()
    assert len(lib) > 700, f"only {len(lib)} sections -- is the snapshot right?"


def test_provenance_is_stated():
    """Rows, date and hash, on every run. A result nobody can attribute to a
    library version is not reproducible."""
    line = sections.vintage_line()
    assert "ABSENT" not in line, line
    assert "sections, generated" in line


# --- the resolver's own rules ---------------------------------------------

def test_200_pfc_is_22_9_kg_per_m():
    section, how = sections.resolve("200 PFC")
    assert section.section_id == "200PFC"
    assert section.mass_kg_per_m == 22.9
    assert how == "exact"


def test_the_spaced_and_library_spellings_agree():
    assert sections.resolve("200 PFC")[0] == sections.resolve("200PFC")[0]


# --- tr#359, fsg-tender-review, 6 Sep 2026: a trailing H orientation suffix
# on the glued-angle dialect must not block resolution, and must not be
# treated as anything but noise to discard.

def test_a_trailing_h_orientation_suffix_does_not_block_the_glued_angle_dialect():
    """A transmission-tower drawing's own convention: `L90x6H` marks a
    Horizontal member on the same section a diagonal carries unmarked. The
    `H` names an orientation, not a different section -- it must resolve
    identically to the unmarked form."""
    with_h, how_with = sections.resolve("L90x6H")
    without_h, how_without = sections.resolve("L90x6")
    assert with_h == without_h == sections.resolve("90EA6")[0]
    assert how_with == how_without == "canonical"


def test_the_h_suffix_is_case_and_space_insensitive_like_the_rest_of_the_dialect():
    for raw in ("L90x6H", "L90X6H", "l90x6h", "L90x6 H"):
        section, how = sections.resolve(raw)
        assert section is not None and section.section_id == "90EA6", raw


def test_a_doubled_or_malformed_suffix_still_refuses():
    """The fix is scoped to exactly one trailing `H`, not "any junk after the
    numbers" -- a second letter is not a known convention and must not be
    silently swallowed."""
    section, how = sections.resolve("L90x6HH")
    assert section is None


def test_the_h_suffix_does_not_leak_into_an_unrelated_ambiguous_case():
    """The suffix rule only ever fires inside the already-narrow glued-angle
    *pair* pattern (`L<leg>x<thickness>H`). tr#359's companion fix later made
    a bare/glued-L *triple* (`90x90x8`, `L90x90x8`, `90x90x8L`) resolve on
    its own -- so `sections.resolve("90x90x8")[0] is None` is no longer true
    about the world, and asserting it here would pin a fact this package no
    longer holds rather than the scoping rule this test exists to check.

    What still needs pinning is that neither fix's own shape leaks into the
    OTHER's: an `H` suffix stapled onto a full triple, whether the triple
    already carries a leading or trailing glued `L`, is not a spelling
    either dialect uses on its own, and must stay an honest miss rather than
    one fix's leniency covering for the other's."""
    assert sections.resolve("90x90x8H")[0] is None       # bare triple + H, no L anywhere
    assert sections.resolve("L90x90x8H")[0] is None       # leading-L triple + H
    assert sections.resolve("90x90x8LH")[0] is None       # trailing-glued-L triple + H


def test_a_bare_depth_is_unresolved_with_its_candidates_named():
    """`250UB` is genuinely three commercial sizes. The drawing has not
    chosen, so the resolver must not either -- but it names them, or the
    estimator gets a flat 'unresolved' and no way to raise a useful RFI."""
    section, how = sections.resolve("250UB")
    assert section is None
    assert how == "unresolved"
    named = [s.section_id for s in sections.ambiguous_candidates("250UB")]
    assert named == ["250UB26", "250UB31", "250UB37"]


def test_baseplate_is_pl_and_never_bpl():
    """BPL is Bisalloy. Reading a base plate as Bisalloy prices the wrong
    steel."""
    for raw in ("BASEPLATE 12", "BASE PLATE 12"):
        section, _how = sections.resolve(raw)
        assert section.section_id == "12PL", raw
    assert sections.resolve("12 BPL")[0].section_id == "12BPL"


def test_fsg_ids_round_the_mass_so_matching_is_on_mass_not_digits():
    """`250UB25.7` is stored `250UB26`."""
    section, how = sections.resolve("250UB25.7")
    assert section.section_id == "250UB26"
    assert section.mass_kg_per_m == 25.7
    assert how == "canonical"


# --- bare cold-formed codes, NOT aliased to any vendor (tr#280 tried it 5
# Sep 2026; reverted 7 Sep 2026, fsg-tender-review#184 Q26) ----------------

def test_a_bare_cold_formed_code_refuses_rather_than_assumes_a_vendor():
    """tr#280 aliased these to their Lysaght row for one day. David, relaying
    the estimating team's answer to Q26: do not assume Lysaght -- leave a
    bare code unresolved. Same 9 real archive pairs #7 anchored on, now
    checked the other way."""
    for bare in ("Z20024", "C15019", "Z20015", "Z15019", "C10015",
                 "C20024", "C15015", "C15012", "C15024"):
        section, how = sections.resolve(bare)
        assert section is None, bare
        assert how == "cold-formed", bare


def test_a_vendor_prefixed_cold_formed_code_still_resolves_exact():
    """The revert is scoped to the BARE code only -- a drawing that already
    states the vendor still finds its row, unchanged by tr#280 or its
    reversal."""
    section, how = sections.resolve("LYS-Z20024")
    assert section is not None
    assert section.section_id == "LYS-Z20024"
    assert section.mass_kg_per_m == 7.065
    assert how == "exact"


def test_a_bare_code_with_no_matching_vendor_row_also_refuses():
    """A syntactically valid but non-existent depth/BMT stays the same
    honest `cold-formed` miss whether or not a same-shaped vendor row
    happens to exist elsewhere in the library."""
    section, how = sections.resolve("Z99999")
    assert section is None
    assert how == "cold-formed"


# --- STR-/LYS- cross-vendor aliasing (fsg-tender-review#184 Q27, ANSWERED
# 7 Sep 2026) -------------------------------------------------------------

def test_a_vendor_prefixed_code_aliases_to_the_other_vendors_row():
    """David's answer to Q27: Stramit and Lysaght purlins at matching
    shape/depth/BMT are a genuine standard-product fact. 90_Lists carries
    no `STR-` rows at all, so each of these previously refused
    `cold-formed`; now they alias to the real `LYS-` row and return the
    LIBRARY's mass, never the archive's own STR- figure (0.34% apart for
    C20024, per docs/purlin-residue.md in fsg-tender-review)."""
    for raw, expected_id, expected_mass in (
        ("STR-C20024", "LYS-C20024", 7.064),
        ("STR-C10015", "LYS-C10015", 2.532),
        ("STR-C20019", "LYS-C20019", 5.593),
        ("STR-Z20019", "LYS-Z20019", 5.593),
    ):
        section, how = sections.resolve(raw)
        assert section is not None, raw
        assert section.section_id == expected_id, raw
        assert section.mass_kg_per_m == expected_mass, raw
        assert how == "cold-formed-vendor-equivalent", raw


def test_the_alias_never_crosses_shape_as_well_as_vendor():
    """STR-Z20019 and STR-C20019 share a mass at this depth/BMT but are
    different rows -- the alias may cross the vendor, never the shape."""
    z, _how = sections.resolve("STR-Z20019")
    c, _how = sections.resolve("STR-C20019")
    assert z.section_id == "LYS-Z20019"
    assert c.section_id == "LYS-C20019"
    assert z.section_id != c.section_id


def test_an_already_exact_vendor_row_is_not_rerouted_through_the_alias():
    """The alias only fires when the WRITTEN vendor's own row is missing --
    a code the library already carries stays `exact`, never `cold-formed-
    vendor-equivalent`."""
    section, how = sections.resolve("LYS-C20024")
    assert section.section_id == "LYS-C20024"
    assert how == "exact"


def test_a_vendor_prefixed_code_with_no_equivalent_either_way_still_refuses():
    """`STR-C30024` has no `LYS-C30024` row in the packaged library either
    (docs/purlin-residue.md: that pair's Lysaght mass is archive-only, not
    in 90_Lists) -- stays an honest `cold-formed` refusal, not a guess at
    the nearest real depth."""
    section, how = sections.resolve("STR-C30024")
    assert section is None
    assert how == "cold-formed"
    assert sections.library().get("LYS-C30024") is None


def test_a_vendor_prefixed_nonexistent_depth_bmt_still_refuses():
    section, how = sections.resolve("STR-Z99999")
    assert section is None
    assert how == "cold-formed"


def test_the_vendor_alias_is_exact_never_through_nearest():
    """Falsifies the mechanism: no vendor-prefixed candidate spelling is
    itself library-resolvable independently of this alias, so `nearest()`
    could never reach one on its own."""
    from fsg_common.sections import canonical_candidates
    for raw in ("STR-C20024", "STR-C10015", "STR-C20019"):
        for candidate in canonical_candidates(raw):
            assert sections.library().get(candidate) is None, (raw, candidate)


# --- the three kinds of modifier, which must not blur ---------------------

def test_a_material_modifier_refuses():
    """90_Lists is entirely steel. Matching aluminium or stainless against it
    prices a different metal as steel."""
    for raw in ("STAINLESS 10 ROD", "STAINLESS 12 PL", "6061-T6 100 x 50 RHS"):
        section, how = sections.resolve(raw)
        assert section is None, raw
        assert how == "material-mismatch", raw


def test_a_finish_modifier_drops_because_the_mass_is_unchanged():
    """GALV is the same steel at the same mass."""
    plain = sections.resolve("10 ROD")[0]
    for raw in ("GALV 10 ROD", "GALVANISED 10 ROD", "10 ROD (BLACK)"):
        section, _how = sections.resolve(raw)
        assert section == plain, raw
        assert section.mass_kg_per_m == plain.mass_kg_per_m, raw
    assert sections.resolve("HDG 200 PFC")[0].section_id == "200PFC"


def test_a_shape_modifier_drops_only_where_the_library_has_that_shape():
    """`10SQ` through `40SQ` are real rows, so square evidence has somewhere
    real to go and the answer is the square bar, not the round one."""
    section, how = sections.resolve("10 SQ ROD")
    assert section.section_id == "10SQ"
    assert how == "canonical"
    assert sections.resolve("40 SQ ROD")[0].section_id == "40SQ"


def test_a_shape_the_library_lacks_is_an_honest_miss_not_a_guess():
    """There is no 24SQ row. The answer is a miss, never the round bar."""
    section, how = sections.resolve("24 SQ ROD")
    assert section is None
    assert how == "unresolved"


def test_threaded_and_hex_refuse_rather_than_assert_the_plain_section():
    """A threaded rod runs 7-14% lighter than the plain bar of the same
    nominal diameter. Dropping the word and returning the plain section is a
    confidently wrong mass, not a near miss."""
    for raw in ("THREADED ROD 16", "M20 THREADED ROD", "M30 THREADED ROD",
                "16 HEX ROD", "HEX BAR 24"):
        section, how = sections.resolve(raw)
        assert section is None, raw
        assert how == "shape-modifier", raw


def test_a_shape_modifier_refusal_names_the_word_and_the_section_ruled_out():
    """A refusal an estimator cannot act on is only half the rule. The word
    says why; the anchor says what plain bar the rate is quoted off."""
    assert sections.shape_modifier("M30 THREADED ROD") == "THREADED"
    assert sections.shape_modifier("16 HEX ROD") == "HEX"
    anchor = sections.shape_modifier_candidates("M30 THREADED ROD")
    assert [s.section_id for s in anchor] == ["30ROD"]


def test_floor_plate_is_priced_by_area():
    section, _how = sections.resolve("6 mm FLOOR PLATE")
    assert section.section_id == "6FP"
    assert section.is_plate
    # 49.1 until 24 Sep 2026: that was 90_Lists column G's stale formula cache
    # (fsg-estimating-tools#385), 2.00 kg over the true 6 mm plate mass of
    # 47.1 kg/m2 in column F. The anchor was pinning the defect.
    assert section.kg_per_m2 == 47.1


def test_mass_of_hands_back_an_AREA_mass_for_floor_plate():
    """A trap, pinned as behaviour because it is behaviour, not a wish.

    `mass_of()` is documented to return "None for a plate or anything else
    the library prices by area rather than by length". That holds for the
    `PL` family, whose `mass_kg_per_m` really is None. It does NOT hold for
    floor plate: `90_Lists` files an `FP` row's kg/m2 in the kg/m COLUMN, so
    `mass_kg_per_m` is 47.1 and `mass_of` returns it through an API named and
    documented per metre.

    A caller doing `qty * length_m * mass_of(...)` on a floor-plate line
    therefore multiplies kg/m2 by metres. That is precisely the arithmetic
    `Section.is_plate` was added to stop, reached through a different door,
    and `is_plate` is right here while `mass_of` is the one that forgets.

    Carried, not fixed. Changing `mass_of` changes what two callers in
    `fsg-tender-review` compute, and this package exists to consolidate the
    resolver without moving any answer. Raised for that repo; run
    `tools/known_issues.py` for the live reproducer.
    """
    assert sections.mass_of("6 mm FLOOR PLATE") == 47.1
    assert sections.resolve("6 mm FLOOR PLATE")[0].kg_per_m2 == 47.1
    # the PL family, where the documented contract does hold
    assert sections.mass_of("12 PL") is None
    assert sections.resolve("12 PL")[0].is_plate


# --- the anchor table, as a table -----------------------------------------

@pytest.mark.parametrize("raw,rule", ANCHORS)
def test_every_anchor_resolves_without_raising(raw, rule):
    """The rule text is in the id so a failure names the rule it broke."""
    section, how = sections.resolve(raw)
    assert how in ("exact", "canonical", "nearest", "cold-formed",
                   "cold-formed-vendor-equivalent",
                   "material-mismatch", "shape-modifier", "substitution",
                   "unresolved"), f"{raw}: {rule}"
    if section is not None:
        assert section.section_id


@pytest.mark.parametrize("raw,note", OBSERVED_GAPS)
def test_observed_gaps_are_recorded_not_asserted(raw, note):
    """These do NOT pin desired behaviour. They exist so the corpus covers a
    case the resolvers may be getting wrong, and so a change to it is visible
    rather than silent. See `vocabulary.OBSERVED_GAPS`."""
    section, how = sections.resolve(raw)
    assert how in ("exact", "canonical", "nearest", "unresolved",
                   "material-mismatch", "shape-modifier"), f"{raw}: {note}"


def test_ss_is_recognised_as_stainless():
    """5 Sep 2026: the gap this test used to pin is closed, with the
    estimator's answer already in hand -- both source resolvers added `SS`/
    `S/S` to `_NON_STEEL` on 3 Sep 2026 in step with each other (a decision
    already made, not a fresh one for this package), and fsg-common's own
    port had simply been taken before that same-day change landed.
    """
    assert sections.resolve("SS 10 ROD") == (None, "material-mismatch")
    assert sections.resolve("S/S 10 ROD") == (None, "material-mismatch")
    assert sections.resolve("STAINLESS 10 ROD") == (None, "material-mismatch")
    # The `\b` boundary stays exact: `SHS`/`RHS` are untouched, `SS` inside a
    # longer word is a substring and not a word.
    section, how = sections.resolve("100SHS4")
    assert section is not None and how == "exact"


# --- tools#64: the four purlin profiles neither 90_Lists nor FSG's own
# detailer archive could supply a mass for -- Lysaght/Stratco published
# section-properties tables, DRAFT pending David's approval (tools#64) ----

_TOOLS_64_ROWS = {
    "LYS-C10010": (1.78, 9),
    "LYS-Z15012": (2.89, 3),
    "LYS-C25019": (6.50, 1),
    "STR-Z25019": (6.49, 40),
}


@pytest.mark.parametrize("raw,expected", _TOOLS_64_ROWS.items())
def test_the_four_manufacturer_sourced_purlin_rows_resolve_exact(raw, expected):
    """Before this PR each of these returned `(None, 'cold-formed')` --
    `90_Lists` had no row and FSG's own detailer archive had too few lines
    (or, for `STR-Z25019`, no Lysaght row at all to alias through) to build
    a median. `docs/purlin-residue.md` (fsg-tender-review) named these four
    as the residue: 53 detailer MTO lines with no mass source anywhere in
    the estate. The mass and line count are the manufacturer table read and
    the archive count already established, quoted here as a fixed pair so a
    change to either is visible."""
    expected_mass, _lines = expected
    section, how = sections.resolve(raw)
    assert section is not None, raw
    assert section.section_id == raw, raw
    assert section.mass_kg_per_m == expected_mass, raw
    assert how == "exact", raw
    assert section.source is not None and "tools#64" in section.source, (
        f"{raw}: a manufacturer-sourced row must carry its citation"
    )


def test_the_53_detailer_lines_this_closes_are_named_not_recomputed():
    """This repo carries no warehouse -- the 53-line figure is
    `fsg-tender-review#tools64`'s own measurement (docs/purlin-residue.md),
    not something re-derived here. What this test controls is that the four
    rows the figure depends on all resolve, so the count stays true once a
    peer re-runs it against the live archive."""
    total = sum(lines for _mass, lines in _TOOLS_64_ROWS.values())
    assert total == 53
    for raw in _TOOLS_64_ROWS:
        assert sections.resolve(raw)[0] is not None, raw


def test_a_manufacturer_source_citation_is_the_exception_not_the_rule():
    """Every ordinary `90_Lists` row still carries no `source` -- only the
    four rows this PR adds do. A citation spreading to rows that came from
    the workbook would be a false attribution."""
    lib = sections.library()
    sourced = [s.section_id for s in lib.sections if s.source is not None]
    assert sorted(sourced) == sorted(_TOOLS_64_ROWS)
