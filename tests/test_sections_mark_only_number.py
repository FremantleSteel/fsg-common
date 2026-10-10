"""fsg-common#64: a member mark's digits are never a size.

`B2 - BASEPLATE` resolved to 2PL, canonical. The only number in the text is
the mark's (`B2`, a member tag), and the plate branch took it as the
thickness. A baseplate with no thickness stated is unresolved, and
`mark_only_reason()` says why. It is never a guessed 2PL.

The cases beside it: other marks and separators, the same mark with a real
thickness after it (which must still resolve), and a "mark" that is itself
section notation (`PL10`), whose digits are a size.
"""
from __future__ import annotations

import pytest

from fsg_common import sections


def _id(raw: str) -> str | None:
    section, _how = sections.resolve(raw)
    return section.section_id if section else None


# --- the issue, and the look-alikes beside it -------------------------------

@pytest.mark.parametrize("raw, mark", [
    ("B2 - BASEPLATE", "B2"),       # the issue
    ("C1 - BASEPLATE", "C1"),
    ("B12 - BASEPLATE", "B12"),
    ("BP3 - BASEPLATE", "BP3"),
    ("B2-BASEPLATE", "B2"),         # no spaces round the hyphen
    ("BP3-BASEPLATE", "BP3"),
    ("B2A - BASEPLATE", "B2A"),     # mark with a trailing letter
    ("b2 - baseplate", "B2"),       # case
    ("B2 BASEPLATE", "B2"),         # mark separated by a space only
    ("C1, BASEPLATE", "C1"),        # ... or by a comma
    ("C1 - BASE PLATE", "C1"),
    ("B2 - PLATE", "B2"),
    ("B2 - PL", "B2"),
    ("B2 - CAPPLATE", "B2"),
    ("B16 - ROD", "B16"),           # not only plate: 16ROD was the same guess
])
def test_a_mark_with_no_size_after_it_is_unresolved_with_its_reason(raw, mark):
    assert sections.resolve(raw) == (None, "unresolved")
    reason = sections.mark_only_reason(raw)
    assert reason is not None
    assert mark in reason
    assert "no size" in reason


def test_the_issue_example_is_never_2pl():
    section, how = sections.resolve("B2 - BASEPLATE")
    assert section is None
    assert how == "unresolved"
    assert "2PL" not in sections.canonical_candidates("B2 - BASEPLATE")


# --- controls: a stated thickness still resolves, mark or no mark -----------

@pytest.mark.parametrize("raw, expected", [
    ("BASEPLATE 20", "20PL"),
    ("20 BASEPLATE", "20PL"),
    ("PL20", "20PL"),
    ("BASEPLATE 20THK", "20PL"),
    ("20THK BASEPLATE", "20PL"),
    ("BASE PLATE 12", "12PL"),
    ("2 BASEPLATE", "2PL"),          # a 2 written as a size is a size
    ("BASEPLATE 2", "2PL"),
    ("B2 - BASEPLATE 20", "20PL"),   # the mark's 2 is not read
    ("B2 - 20 BASEPLATE", "20PL"),
    ("B2 - BASEPLATE 20THK", "20PL"),
    ("B2 - 10 THK BASEPLATE", "10PL"),
    ("B2 - BASEPLATE 300X300X20", "20PL"),
    ("B2 - BASEPLATE 2", "2PL"),     # the 2 after the plate word is stated
    ("B2 - 10 SQ", "10SQ"),
    ("C1 100 x 100 x 5 SHS", "100SHS5"),
])
def test_a_stated_size_still_resolves(raw, expected):
    assert _id(raw) == expected
    assert sections.mark_only_reason(raw) is None


@pytest.mark.parametrize("raw, expected", [
    ("PL10 - BASEPLATE", "10PL"),    # the "mark" is itself a plate callout
    ("PL10 BASEPLATE", "10PL"),
])
def test_a_mark_that_is_itself_section_notation_keeps_its_digits(raw, expected):
    assert _id(raw) == expected
    assert sections.mark_only_reason(raw) is None


@pytest.mark.parametrize("raw", ["BASEPLATE", "BASE PLATE", "", "   ", None])
def test_text_with_no_mark_is_not_this_form(raw):
    """No mark, no reason from this function: a bare `BASEPLATE` is the older
    `OBSERVED_GAPS` miss, not a mark that was refused."""
    assert sections.mark_only_reason(raw) is None


@pytest.mark.parametrize("raw, how", [
    ("M12 THREADED ROD", "shape-modifier"),
    ("M20 BOLT", "unresolved"),
    ("M24 WASHER", "unresolved"),
])
def test_a_metric_thread_is_a_size_not_a_mark(raw, how):
    """`M12` has the mark's shape but is a 12 mm thread. Most of the lines
    this shape matched in Tier A on 10 Oct 2026 were M sizes; the reason
    must not call them member marks, and their verdicts do not move."""
    assert sections.mark_only_reason(raw) is None
    assert sections.resolve(raw)[1] == how
