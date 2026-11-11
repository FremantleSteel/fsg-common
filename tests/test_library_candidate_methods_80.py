"""fsg-common#80: `ambiguous_candidates` and `absent_size_candidates` are
methods on `SectionLibrary`, so a library built from a live workbook names
candidates from that workbook and never from the packaged snapshot.

Before this, `ambiguous_candidates(raw)` was a free function that always read
`library()`, the snapshot. A consumer holding its own library (a workbook
run) could only get the snapshot's answer from it: a silent wrong answer.
The free functions stay, as thin wrappers over `library()`.

The rows in the small libraries below are invented on purpose (`250UB99`,
`777UB11`): a size the snapshot does not carry can only be named by a method
that reads the library it was called on.
"""
from __future__ import annotations

from fsg_common import sections
from fsg_common.sections import Section, SectionLibrary


def _row(section_id: str, mass: float) -> Section:
    return Section(section_id=section_id, category="Beam", build_default="",
                   mass_kg_per_m=mass, plate_thickness_mm=None,
                   plate_kg_per_m2=None)


def _ids(found: list[Section]) -> list[str]:
    return [s.section_id for s in found]


# A stand-in for a workbook that differs from the snapshot: one invented UB
# at a depth the snapshot also stocks, one family the snapshot does not have.
WORKBOOK = SectionLibrary([
    _row("250UB99", 99.0),
    _row("777UB11", 11.0),
    _row("777UB15", 15.0),
])


# --- ambiguous_candidates: no size given ------------------------------------

def test_ambiguous_candidates_reads_the_library_it_is_called_on():
    assert _ids(WORKBOOK.ambiguous_candidates("250UB")) == ["250UB99"]
    assert _ids(WORKBOOK.ambiguous_candidates("777 UB")) == ["777UB11", "777UB15"]


def test_ambiguous_candidates_is_not_the_snapshots_answer():
    """The control: the snapshot names three real 250UBs and nothing at 777,
    so a method that quietly read `library()` fails both lines."""
    snapshot = _ids(sections.ambiguous_candidates("250UB"))
    assert "250UB99" not in snapshot and len(snapshot) > 1
    assert sections.ambiguous_candidates("777 UB") == []


def test_ambiguous_candidates_still_empty_where_it_must_be():
    for text in ("250UB99", "WIDGET 250", "", None, "UB"):
        assert WORKBOOK.ambiguous_candidates(text) == [], text


# --- absent_size_candidates: a size the library does not carry ---------------

def test_absent_size_candidates_reads_the_library_it_is_called_on():
    assert _ids(WORKBOOK.absent_size_candidates("777UB13")) == [
        "777UB11", "777UB15"]
    # The snapshot stocks 250UB26/31/37; this library stocks only 250UB99.
    assert _ids(WORKBOOK.absent_size_candidates("250UB50")) == ["250UB99"]


def test_absent_size_candidates_never_answers_where_something_else_does():
    # No size given: that is ambiguous_candidates' case.
    assert WORKBOOK.absent_size_candidates("777UB") == []
    # Resolves in this library: no gap to report.
    assert WORKBOOK.get("777UB15") is not None
    assert WORKBOOK.absent_size_candidates("777UB15") == []
    # A head the library does not stock, a word that is no family, nothing.
    for text in ("888UB13", "WIDGET50*3", "", None):
        assert WORKBOOK.absent_size_candidates(text) == [], text


def test_an_empty_library_names_nothing():
    empty = SectionLibrary([])
    assert empty.ambiguous_candidates("250UB") == []
    assert empty.absent_size_candidates("250UB50") == []


# --- the free functions are wrappers over library(), unchanged ---------------

NOTATIONS = ("250UB", "100 x 100 SHS", "250x150RHS", "100TFB", "BT100*11",
             "BT125*13", "200 PFC", "SHS100*100*6.0", "250UB37", "BT9999*11",
             "WIDGET50*3", "", None)


def test_free_functions_equal_the_snapshot_librarys_methods():
    lib = sections.library()
    for text in NOTATIONS:
        assert sections.ambiguous_candidates(text) == \
            lib.ambiguous_candidates(text), text
        assert sections.absent_size_candidates(text) == \
            lib.absent_size_candidates(text), text


def test_absent_size_free_function_names_the_snapshots_rows():
    """The same expectations tender-review's own copy pins today, so its
    calls can move to this function without changing an answer."""
    expected = {
        "BT100*11": ["100BT12", "100BT15"],
        "BT125*13": ["125BT15", "125BT18"],
        "BT155*16": ["155BT20", "155BT23"],
    }
    for text, ids in expected.items():
        assert sections.resolve(text)[0] is None, text
        assert _ids(sections.absent_size_candidates(text)) == ids, text
    for text in ("250UB", "100x100SHS", "250x150RHS"):
        assert sections.ambiguous_candidates(text), text
        assert sections.absent_size_candidates(text) == [], text
    for text in ("200 PFC", "SHS100*100*6.0", "250UB37", "BT9999*11",
                 "WIDGET50*3"):
        assert sections.absent_size_candidates(text) == [], text


def test_a_subclass_inherits_both_methods():
    """Bluebeam's `SectionLibrary` subclasses this one; once its copies go,
    it gets these by inheritance."""
    class Sub(SectionLibrary):
        pass

    sub = Sub(WORKBOOK.sections)
    assert _ids(sub.ambiguous_candidates("250UB")) == ["250UB99"]
    assert _ids(sub.absent_size_candidates("777UB13")) == ["777UB11", "777UB15"]
