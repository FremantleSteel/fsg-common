"""fsg-common#62: two ways a model's type name writes a section the library
already carries, and the cases beside each.

    UB150x75x14      family first, depth x width x mass   -> 150UB14
    G1 - C10015      member tag, ` - `, then the section   -> LYS-C10015

Both are parsing, not substitution. Each new form must land on the row its
canonical spelling lands on; a mass the library does not carry, a depth it
does not carry, or two readings that disagree stay unresolved with a reason;
a tag that is itself a section is never dropped.
"""
from __future__ import annotations

import pytest

from fsg_common import sections


def _id(raw: str) -> str | None:
    section, _how = sections.resolve(raw)
    return section.section_id if section else None


def _how(raw: str) -> str:
    return sections.resolve(raw)[1]


# --- form 1: family first, depth x width x mass -----------------------------

@pytest.mark.parametrize("raw, canonical", [
    ("UB150x75x14", "150UB14"),
    ("UB 150 x 75 x 14", "150UB14"),
    ("ub150x75x14.0", "150UB14"),
    ("UB150×75×14", "150UB14"),
    ("UB250x146x25.7", "250UB25.7"),
    ("UB250x146x26", "250UB26"),
    ("UC150x152x23.4", "150UC23.4"),
    ("UC150x152x23", "150UC23"),
    ("WB700x275x115", "700WB115"),
    ("WC400x400x144", "400WC144"),
])
def test_a_family_first_name_lands_on_its_canonical_spellings_row(raw, canonical):
    expected, _ = sections.resolve(canonical)
    assert expected is not None
    section, how = sections.resolve(raw)
    assert section is expected
    assert how == "canonical"


def test_the_issue_example_and_its_canonical_form():
    canonical, how = sections.resolve("150UB14")
    assert how == "exact"
    assert sections.resolve("UB150x75x14") == (canonical, "canonical")
    assert canonical.section_id == "150UB14"


def test_the_width_is_never_read_as_the_mass():
    """Before #62 the three numbers went through `nearest()` as depth x mass:
    `WB1000x300x215` came back 1000WB296, 38% heavy. It is 1000WB215."""
    assert _id("WB1000x300x215") == "1000WB215"
    assert _how("WB1000x300x215") == "canonical"


@pytest.mark.parametrize("raw, words", [
    ("UB150x75x99", "no 150UB row has that mass"),
    ("UB250x146x25", "no 250UB row has that mass"),
    ("UB250x146x25.5", "no 250UB row has that mass"),
    ("WB1000x300x999", "no 1000WB row has that mass"),
    ("UB406x178x60", "no 406UB row"),
    ("UC152x152x23", "no 152UC row"),
])
def test_a_mass_or_depth_the_library_does_not_carry_is_refused_with_a_reason(raw, words):
    """A British designation (`UB406x178x60`) is not read as an Australian
    section: the depth must equal the library's own, with no head tolerance."""
    assert sections.resolve(raw) == (None, "unresolved")
    reading = sections.family_first_reading(raw)
    assert reading is not None and reading.section is None
    assert words in reading.reason


def test_two_readings_that_name_different_rows_are_not_guessed():
    """`UB150x18x14`: depth x width x mass says 150UB14, depth x mass x
    length says 150UB18. Before #62 it answered 150UB18."""
    assert sections.resolve("UB150x18x14") == (None, "unresolved")
    reason = sections.family_first_reading("UB150x18x14").reason
    assert "150UB14" in reason and "150UB18" in reason


@pytest.mark.parametrize("raw, expected", [
    ("UB150x14x6000", "150UB14"),
    ("UB250x25.7x6000", "250UB26"),
    ("150 UB 14 x 6000", "150UB14"),
    ("UB150x14", "150UB14"),
    ("UB610101", "610UB101"),
    ("TFB100x45x7.2", "100TFB45"),
    ("PFC200x75x22.9", "200PFC"),
])
def test_the_neighbouring_spellings_answer_as_they_did(raw, expected):
    """A length after the mass, the two-number form, the glued detailer form
    and the families #62 does not touch keep their answers."""
    assert _id(raw) == expected
    assert _how(raw) in ("exact", "canonical")


def test_a_reading_is_none_for_text_that_is_not_the_form():
    for raw in ("150UB14", "UB150x14", "150 x 75 x 14 UB", "PFC200x75x22.9", "", None):
        assert sections.family_first_reading(raw) is None


def test_a_family_first_name_behind_a_mark_resolves():
    assert _id("G1 UB150x75x14") == "150UB14"
    assert _id("B1 - UB150x75x14") == "150UB14"
    assert sections.family_first_reading("B1 - UB150x75x14").tag == "B1"


def test_a_mark_that_is_itself_a_section_is_not_dropped_in_front_of_a_triple():
    assert sections.resolve("PL10 - UB150x75x14") == (None, "unresolved")
    assert "PL10 itself reads as a section" in (
        sections.family_first_reading("PL10 - UB150x75x14").reason)


# --- form 2: member tag, ` - `, section -------------------------------------

@pytest.mark.parametrize("tagged, bare", [
    ("G1 - C10015", "C10015"),
    ("P1 - Z15015", "Z15015"),
    ("G12 - Z20015", "Z20015"),
    ("B1 - 200 PFC", "200 PFC"),
    ("C1 - 100 x 100 x 5 SHS", "100 x 100 x 5 SHS"),
    ("G1 - Z25019", "Z25019"),
])
def test_a_tagged_name_lands_where_its_untagged_section_does(tagged, bare):
    expected, bare_how = sections.resolve(bare)
    section, how = sections.resolve(tagged)
    assert section is expected
    # The tag was dropped, so an `exact` on the bare text is `canonical` here.
    assert how == ("canonical" if bare_how == "exact" else bare_how)


def test_the_issue_example_reads_as_its_lysaght_row():
    section, how = sections.resolve("G1 - C10015")
    assert section is not None and section.section_id == "LYS-C10015"
    assert how == "cold-formed-bare-lysaght"


def test_a_tag_in_front_of_a_library_id_is_canonical_not_exact():
    assert sections.resolve("G1 - 150UB14")[1] == "canonical"


# Each verdict measured on origin/main (66fb97f) before #62 and unchanged by
# it: the tag rule does not fire, so the ordinary path answers as it did.
@pytest.mark.parametrize("raw, expected, how", [
    # The tag is a section, so it is kept, and `PL10 - 200` stays a miss.
    ("PL10 - 200", None, "unresolved"),
    # Both sides are sections. The tag is kept, so the Lysaght alias (raw
    # text only) does not fire; the ordinary path's mark strip still sees a
    # purlin code the library does not carry under that id.
    ("PL10 - C10015", None, "cold-formed"),
    # Not a mark's shape, so not a tag. The ordinary path's answer (the
    # first section named) is older than #62 and not touched here.
    ("150UB14 - C10015", "150UB14", "canonical"),
    # What follows does not parse on its own.
    ("G1 - 200", None, "unresolved"),
    # Two tags is not a form anyone has measured.
    ("G1 - B2 - 150UB14", None, "unresolved"),
    # A tag after the section is not this form.
    ("UB150x75x14 - G1", None, "unresolved"),
])
def test_negative_controls_do_not_strip_into_or_across_a_section(raw, expected, how):
    assert (_id(raw), _how(raw)) == (expected, how)


def test_a_tag_that_reads_as_a_section_is_never_split_off():
    for raw in ("PL10 - 200", "PL10 - C10015"):
        tag, _rest = sections.split_member_tag(raw)
        assert sections.library()._reads_as_section(tag)
    assert not sections.library()._reads_as_section("G1")


@pytest.mark.parametrize("raw", ["G1-C10015", "LYS-C10015", "250UB - 37", "P7 Z20015"])
def test_a_hyphen_without_spaces_or_a_space_mark_is_not_a_member_tag(raw):
    """`LYS-C10015` is a vendor prefix and `250UB - 37` a split id; `P7
    Z20015` is the space-marked schedule line the Lysaght alias still
    refuses (`tests/test_sections_anchors.py`)."""
    assert sections.split_member_tag(raw) is None


def test_split_member_tag_shape():
    assert sections.split_member_tag("G1 - C10015") == ("G1", "C10015")
    assert sections.split_member_tag("g1 - c10015") == ("G1", "C10015")
    assert sections.split_member_tag("") is None
    assert sections.split_member_tag(None) is None


def test_a_material_word_after_the_tag_still_refuses():
    assert _how("G1 - SS 10 ROD") == "material-mismatch"
    assert _how("G1 - M24 ROD") == "shape-modifier"
