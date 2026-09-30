"""The twin-parity vocabulary, ported into the package that replaced the twins.

`fsg-tender-review/tests/test_resolver_twin_parity.py` compared its resolver
against the Bluebeam toolkit's copy on a shared vocabulary and failed on any
disagreement. That test exists because the two copies were found, on 26 Aug
2026, to disagree on seven notations, one of them a different mass.

Once both repos import this package there are no twins left to compare, so
the vocabulary changes job rather than retiring: every notation in it
resolves without raising, the cheapest broad regression net there is.

**The one notation the twins genuinely disagreed about is answered now, in
two steps.** `273 CHS 6.4` used to produce two different verdicts on
purpose, gated by a `RoundingPolicy` each consumer picked (`_policy.py`,
deleted 7 Sep 2026). fsg-tender-review#184 Q25 settled the verdict then --
both resolvers converge on `canonical` -- but the mass behind that verdict
was still the library's imperial 6.35 row, not the metric 6.40 one the
question actually asked about. David confirmed the mass directly on
18 Sep 2026 ("Confirm metric, 6.40"), and `_chs_metric_wall()` in
`_resolver.py` applies it. The policy split, `TENDER_REVIEW`/`BLUEBEAM`,
and the tests that pinned the disagreement are gone; the notation is now a
plain anchor in `vocabulary.ANCHORS` like any other answered question.

The live three-way comparison against both source repos is
`tools/parity_report.py`, which reads them at a pinned git ref. It is not a
test: it needs both sibling checkouts, which CI does not have.
"""
from __future__ import annotations

import pytest
from vocabulary import VOCABULARY, build, library_sweep

from fsg_common import sections

VERDICTS = {"exact", "canonical", "nearest", "cold-formed",
            "cold-formed-vendor-equivalent", "cold-formed-bare-lysaght",
            "material-mismatch",
            "shape-modifier", "substitution", "unresolved"}


@pytest.fixture(scope="module")
def corpus():
    return build(sections.PACKAGED_SNAPSHOT)


@pytest.mark.parametrize("raw", VOCABULARY)
def test_the_vocabulary_resolves(raw):
    section, how = sections.resolve(raw)
    assert how in VERDICTS, raw
    if how in ("unresolved", "material-mismatch", "shape-modifier", "cold-formed"):
        assert section is None, raw
    else:
        assert section is not None, raw


@pytest.mark.parametrize("raw", VOCABULARY)
def test_the_grammar_functions_never_raise(raw):
    sections.loose_key(raw)
    sections.canonical_candidates(raw)
    sections.cold_formed(raw)
    sections.shape_modifier(raw)
    sections.ambiguous_candidates(raw)
    sections.shape_modifier_candidates(raw)


def test_the_corpus_covers_more_than_its_authors_chose(corpus):
    """Rule 15: a corpus only catches what it exercises. The hand-picked
    cases are paired with every section id in the library, so a change that
    breaks a family nobody listed still goes red."""
    sweep = library_sweep(sections.PACKAGED_SNAPSHOT)
    assert len(sweep) > 700
    assert set(sweep) <= set(corpus)
    assert len(corpus) >= len(sweep) + 50


def test_every_library_section_resolves_to_itself(corpus):
    """The structural check behind the sweep. A section written exactly as
    the library files it must come back as itself, exactly -- any other
    answer means the index and the grammar disagree about the same string."""
    misses = []
    for section_id in library_sweep(sections.PACKAGED_SNAPSHOT):
        section, how = sections.resolve(section_id)
        if section is None or section.section_id != section_id or how != "exact":
            misses.append((section_id, section.section_id if section else None, how))
    assert not misses, f"{len(misses)} section(s) did not round-trip: {misses[:10]}"


# --- the question that used to be open -------------------------------------

def test_the_chs_wall_question_is_settled_not_silently_picked():
    """`273 CHS 6.4` used to produce two different verdicts, gated by a
    `RoundingPolicy` each consumer picked (`_policy.py`, deleted 7 Sep 2026
    once fsg-tender-review#184 Q25 answered the VERDICT). That fix reused
    `_is_rounding`'s answer, the library's own `273CHS6.35` row at 41.77
    kg/m -- the imperial mass, not the metric one Q25 actually asked about.
    David, 18 Sep 2026, asked to confirm or correct that mass directly:
    "Confirm metric, 6.40." This pins the MASS the question turned on, not
    only the verdict -- a bare `how == "canonical"` check would have passed
    on the wrong number for eleven days without ever going red."""
    section, how = sections.resolve("273 CHS 6.4")
    assert section.section_id == "273CHS6.4"
    assert section.mass_kg_per_m == 42.1
    assert how == "canonical"


def test_the_imperial_chs_wall_is_unmoved_by_the_metric_one():
    """Control: `6.35` written out in full still reaches the library's own
    imperial row, unchanged. The metric fix must not blur the two together
    -- they price 0.8% apart, which is the whole reason today's question
    existed."""
    section, how = sections.resolve("273 CHS 6.35")
    assert (section.section_id, how) == ("273CHS6.35", "exact")


def test_the_metric_chs_wall_applies_only_where_the_library_has_a_sibling():
    """`76.1CHS...` carries no `6.35` row in 90_Lists at all (its own
    ladder is 2.3/3.2/3.6/4.5/5.9), so `76.1 CHS 6.4` must not be asserted
    against a size the library holds no other evidence for -- it stays
    unresolved rather than inventing an OD. Control for
    `_chs_metric_wall`'s sibling-existence guard."""
    section, how = sections.resolve("76.1 CHS 6.4")
    assert section is None
    assert how == "unresolved"


def test_other_chs_one_decimal_roundings_are_unaffected():
    """The one-decimal `_is_rounding` clause still governs every CHS wall
    OTHER than 6.4/6.35 -- `60.3CHS8.74` written one decimal short stays a
    rounding of the library's own figure, not a second metric assertion."""
    section, how = sections.resolve("60.3 CHS 8.7")
    assert (section.section_id, how) == ("60.3CHS8.74", "canonical")


def test_whole_number_rounding_is_unaffected_by_the_settled_question():
    """The decimal clause the CHS question turned on is one of two rounding
    rules; the whole-number one was never in dispute. `250 UB 25.7` against
    the library's `250UB26` stays `canonical`."""
    section, how = sections.resolve("250UB25.7")
    assert (section.section_id, how) == ("250UB26", "canonical")


# --- the shape of the record ----------------------------------------------

def test_the_snapshot_threshold_is_the_one_both_repos_agreed_on():
    """The toolkit read 30 with a comment claiming it matched the other
    repo's 90, so the repo that does not refresh the snapshot warned three
    times sooner than the one that does. Aligned 28 Aug 2026."""
    assert sections.STALE_AFTER_DAYS == 90
    assert sections.SNAPSHOT_STALE_AFTER_DAYS == sections.STALE_AFTER_DAYS


def test_absent_provenance_is_not_reported_as_fresh(tmp_path):
    """Absent is a third state, never the same answer as 'checked and fine'
    (rule 27). A snapshot with no generated date gets its own words."""
    import json

    p = tmp_path / "no-provenance.json"
    p.write_text(json.dumps({"sections": [], "_provenance": {}}), encoding="utf-8")
    warning = sections.staleness_warning(str(p))
    assert warning is not None
    assert "cannot be checked" in warning


def test_an_unreadable_snapshot_says_so_rather_than_printing_a_blank(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert "UNREADABLE" in sections.vintage_line(str(p))


# --- the surface a consumer shim needs ------------------------------------

def test_the_names_the_bluebeam_toolkit_imports_are_all_present():
    """`fsg-bluebeam-steel-standards/tools/fsg_mto/cli.py` and its
    `tools/tests/test_offline.py` import these by name from the module this
    package replaces. A shim can only be a re-export if every one of them is
    reachable from `fsg_common.sections`.

    Three are private. That is deliberate and explained in the package
    docstring; the point of this test is that dropping one silently breaks a
    consumer's test suite rather than this one's.
    """
    needed = [
        # cli.py
        "default_snapshot_path", "load_section_library",
        "load_section_library_from_snapshot", "snapshot_staleness_warning",
        "snapshot_vintage",
        # columns.py, schedule.py, takeoff.py
        "Section", "SectionLibrary",
        # test_offline.py, including the private three
        "canonical_candidates", "cold_formed", "loose_key",
        "_NON_STEEL", "_SHAPE_MODIFIER", "_looks_like_mark",
        "COLD_FORMED", "SNAPSHOT_STALE_AFTER_DAYS",
    ]
    missing = [n for n in needed if not hasattr(sections, n)]
    assert not missing, f"a consumer shim would fail on: {missing}"


def test_the_names_fsg_tender_review_imports_are_all_present():
    """The other consumer's surface: `resolve.py`'s public API plus the
    `Section` its `classification.py` exports."""
    needed = [
        "resolve", "library", "SectionLibrary", "Section", "loose_key",
        "canonical_candidates", "cold_formed", "shape_modifier",
        "ambiguous_candidates", "shape_modifier_candidates", "mass_of",
        "substitutions", "COLD_FORMED", "NEAREST_TOLERANCE", "NEAREST_MARGIN",
        "HEAD_TOLERANCE",
    ]
    missing = [n for n in needed if not hasattr(sections, n)]
    assert not missing, f"a consumer shim would fail on: {missing}"
