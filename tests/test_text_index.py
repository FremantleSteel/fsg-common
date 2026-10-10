"""fsg_common.text_index (#68): refusals, filtering by lane and customer type,
delete by Opportunity id, and the recheck the nightly job runs."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from fsg_common import text_index as ti
from fsg_common.text_index import (
    DEFENCE_CUSTOMER,
    HOSTED_AI,
    LOCAL_AI,
    NON_DEFENCE_CUSTOMER,
    NOT_A_TENDER,
    IndexRefused,
    TextIndex,
)

READ_AT = "2026-10-10T12:00:00+08:00"


@pytest.fixture
def idx():
    index = TextIndex(":memory:")
    yield index
    index.close()


def add(idx, text, opp="OPP-1", det="No NDA", flag=False, ref=None, source="a.md"):
    return idx.add(text, source=source, opportunity_id=opp, determination=det,
                   automated_processing_prohibited=flag, level_read_at=READ_AT,
                   source_hash="sha256:00", approval_reference=ref)


def sources(result):
    return sorted(h.source for h in result.hits)


# --- an absent level refuses; a present one inserts -------------------------

@pytest.mark.parametrize("det", [None, "", "  ", "Under review", "under review",
                                 "Not a value"])
def test_absent_or_undecided_level_refuses(idx, det):
    with pytest.raises(IndexRefused):
        add(idx, "purlin spacing", det=det)
    assert idx.db.execute("SELECT COUNT(*) FROM rows").fetchone()[0] == 0


def test_present_level_inserts(idx):
    add(idx, "purlin spacing", det="Restricted")
    assert idx.count("OPP-1") == 1


def test_absent_opportunity_refuses_unless_marked_not_a_tender(idx):
    with pytest.raises(IndexRefused):
        add(idx, "handover note", opp=None)
    add(idx, "handover note", opp=NOT_A_TENDER, source="handover.md")
    hits = idx.search("handover", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER)
    assert [(h.source, h.opportunity_id) for h in hits.hits] == [("handover.md", None)]


def test_flag_must_be_a_bool_or_none(idx):
    with pytest.raises(IndexRefused):
        add(idx, "x", flag="no")


# --- a search names its lane and customer type ------------------------------

@pytest.mark.parametrize("lane,customer", [(None, NON_DEFENCE_CUSTOMER),
                                           (HOSTED_AI, None), ("", ""),
                                           ("hosted", NON_DEFENCE_CUSTOMER)])
def test_search_without_lane_or_customer_refuses(idx, lane, customer):
    add(idx, "baseplate grout")
    with pytest.raises(IndexRefused):
        idx.search("baseplate", lane=lane, customer_type=customer)


def test_fts_query_matches_words_and_misses_others(idx):
    add(idx, "Handover: the baseplate grout is by others", source="h1.md")
    add(idx, "Galvanising is to AS/NZS 4680", source="h2.md")
    hits = idx.search("baseplate AND grout", lane=HOSTED_AI,
                      customer_type=NON_DEFENCE_CUSTOMER)
    assert sources(hits) == ["h1.md"]
    assert "[baseplate]" in hits.hits[0].snippet
    assert idx.search("purlin", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER
                      ) == ti.SearchResult((), withheld=0, truncated=False)


# --- the limit and what a search says it left out ------------------------------

@pytest.mark.parametrize("limit", [0, -1, 1.5, "3", True])
def test_limit_must_be_positive_whole_or_none(idx, limit):
    add(idx, "cleat")
    with pytest.raises(IndexRefused, match="limit"):
        idx.search("cleat", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER,
                   limit=limit)


def test_limit_none_returns_every_permitted_match(idx):
    for i in range(60):
        add(idx, f"cleat {i}", opp=f"O-{i}")
    result = idx.search("cleat", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER,
                        limit=None)
    assert (len(result.hits), result.truncated) == (60, False)
    capped = idx.search("cleat", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER)
    assert (len(capped.hits), capped.truncated) == (50, True)


def test_filter_runs_before_the_limit(idx):
    # Ten restricted rows rank above the one ordinary row; a limit applied
    # before the filter would return nothing to a hosted search.
    for i in range(10):
        add(idx, "gusset gusset gusset", opp=f"O-r{i}", det="Restricted",
            source=f"restricted-{i}")
    add(idx, "gusset plate with a long run of other words in the note",
        opp="O-ord", source="ordinary")
    assert levels_rank_restricted_first(idx)
    result = idx.search("gusset", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER,
                        limit=1)
    assert [h.source for h in result.hits] == ["ordinary"]
    assert (result.withheld, result.truncated) == (10, False)


def levels_rank_restricted_first(idx):
    first = idx.db.execute("SELECT rowid FROM rows_fts WHERE rows_fts MATCH 'gusset'"
                           " ORDER BY rank LIMIT 1").fetchone()[0]
    return idx.db.execute("SELECT determination FROM rows WHERE id = ?",
                          (first,)).fetchone()[0] == "Restricted"


def test_search_counts_withheld_and_truncated(levels):
    hosted = levels.search("steel", lane=HOSTED_AI, customer_type=NON_DEFENCE_CUSTOMER,
                           limit=2)
    assert (len(hosted.hits), hosted.withheld, hosted.truncated) == (2, 6, True)
    local = levels.search("steel", lane=LOCAL_AI, customer_type=DEFENCE_CUSTOMER)
    assert (len(local.hits), local.withheld, local.truncated) == (6, 3, False)


# --- the filter ----------------------------------------------------------------

@pytest.fixture
def levels(idx):
    add(idx, "steel note", opp="O-ord", det="No NDA", source="ordinary")
    add(idx, "steel note", opp="O-ord2", det="No NDA", flag=None, source="ordinary-noflag")
    add(idx, "steel note", opp="O-res", det="Restricted", source="restricted")
    add(idx, "steel note", opp="O-def", det="Defence - restricted", source="defence")
    add(idx, "steel note", opp="O-na", det="NDA not applicable to this job", source="na")
    add(idx, "steel note", opp="O-ai", det="No NDA", flag=True, source="ai-forbidden")
    add(idx, "steel note", opp="O-apr", det="Approval received", ref="letter 3",
        source="approved")
    add(idx, "steel note", opp="O-apx", det="Approval received", source="approved-noref")
    add(idx, "steel note", opp="O-nof", det="Restricted", flag=None, source="res-noflag")
    return idx


def test_hosted_never_sees_restricted_defence_or_ai_forbidden(levels):
    for customer in (DEFENCE_CUSTOMER, NON_DEFENCE_CUSTOMER):
        hits = levels.search("steel", lane=HOSTED_AI, customer_type=customer)
        assert sources(hits) == ["approved", "ordinary", "ordinary-noflag"]


def test_local_sees_defence_only_for_a_defence_customer(levels):
    assert sources(levels.search("steel", lane=LOCAL_AI,
                                 customer_type=DEFENCE_CUSTOMER)) == [
        "approved", "approved-noref", "defence", "ordinary", "ordinary-noflag",
        "restricted"]
    assert sources(levels.search("steel", lane=LOCAL_AI,
                                 customer_type=NON_DEFENCE_CUSTOMER)) == [
        "approved", "approved-noref", "ordinary", "ordinary-noflag", "restricted"]


# --- delete by Opportunity id ----------------------------------------------------

def test_delete_leaves_zero_and_other_opportunities_untouched(idx):
    for i in range(3):
        add(idx, f"chunk {i} cleat", opp="OPP-1")
    add(idx, "chunk cleat", opp="OPP-2", source="b.md")
    assert idx.count("OPP-1") == 3
    assert idx.delete_by_opportunity("OPP-1") == 3
    assert idx.count("OPP-1") == 0
    assert idx.count("OPP-2") == 1
    hits = idx.search("cleat", lane=LOCAL_AI, customer_type=NON_DEFENCE_CUSTOMER)
    assert sources(hits) == ["b.md"]
    assert idx.db.execute("SELECT COUNT(*) FROM rows_fts").fetchone()[0] == 1


MARKER = "zqxjvdestroymarker"


def test_delete_destroys_the_text_in_the_file(tmp_path):
    # A MATCH returning nothing is not enough: the words must leave the file.
    path = tmp_path / "index.db"
    idx = TextIndex(path)
    for i in range(5):
        add(idx, f"{MARKER} cleat {i}", opp="OPP-1", source=f"a{i}.md")
    add(idx, "kept cleat", opp="OPP-2", source="b.md")
    assert MARKER.encode() in path.read_bytes()
    idx.delete_by_opportunity("OPP-1")
    assert not any(MARKER.encode() in (b or b"") for (b,) in
                   idx.db.execute("SELECT block FROM rows_fts_data"))
    idx.close()
    files = sorted(tmp_path.iterdir())  # the index, and any journal or WAL left
    assert path in files
    assert [f.name for f in files if MARKER.encode() in f.read_bytes()] == []
    reopened = TextIndex(path)  # an existing file gets both settings again
    assert sources(reopened.search("cleat", lane=LOCAL_AI,
                                   customer_type=NON_DEFENCE_CUSTOMER)) == ["b.md"]
    reopened.close()


def test_delete_refuses_when_secure_delete_is_off(idx):
    add(idx, "chunk cleat")
    idx.db.execute("PRAGMA secure_delete = OFF")
    with pytest.raises(RuntimeError, match="secure delete is off"):
        idx.delete_by_opportunity("OPP-1")
    assert idx.count("OPP-1") == 1


class _SkipFtsDelete:
    """A connection whose full-text delete does nothing, to prove the read-back."""

    def __init__(self, db):
        self._db = db

    def execute(self, sql, *args):
        if sql.startswith("DELETE FROM rows_fts"):
            return self._db.execute("SELECT 0")
        return self._db.execute(sql, *args)

    def __enter__(self):
        return self._db.__enter__()

    def __exit__(self, *exc):
        return self._db.__exit__(*exc)

    def close(self):
        self._db.close()


def test_delete_raises_when_full_text_rows_remain(idx):
    add(idx, "chunk cleat")
    idx.db = _SkipFtsDelete(idx.db)
    with pytest.raises(RuntimeError, match="1 full-text rows remain"):
        idx.delete_by_opportunity("OPP-1")


def test_delete_of_an_id_with_no_rows_is_zero_and_blank_refuses(idx):
    assert idx.delete_by_opportunity("OPP-none") == 0
    for blank in (None, "", " "):
        with pytest.raises(IndexRefused):
            idx.delete_by_opportunity(blank)


def test_delete_raises_when_rows_remain_on_read_back(idx, monkeypatch):
    add(idx, "chunk cleat")
    # real-gate test: test_delete_leaves_zero_and_other_opportunities_untouched
    monkeypatch.setattr(idx, "count", lambda _opp: 1)
    with pytest.raises(RuntimeError, match="remain"):
        idx.delete_by_opportunity("OPP-1")


# --- recheck --------------------------------------------------------------------

def test_recheck_removes_rows_that_no_longer_qualify_and_updates_the_rest(idx):
    add(idx, "bolt note", opp="O-gone")
    add(idx, "bolt note", opp="O-undecided")
    add(idx, "bolt note", opp="O-tighter", source="tighter")
    add(idx, "bolt note", opp="O-same", source="same")
    add(idx, "bolt note", opp=NOT_A_TENDER, source="own")
    now = {"O-gone": None, "O-undecided": ("Under review", None, None),
           "O-tighter": ("Restricted", False, None), "O-same": ("No NDA", False, None)}
    result = idx.recheck(now.__getitem__, read_at="2026-10-11T02:00:00+08:00")
    assert result == ti.RecheckResult(checked=4, removed=2, updated=1,
                                      not_a_tender_rows=1)
    assert idx.count("O-gone") == idx.count("O-undecided") == 0
    assert sources(idx.search("bolt", lane=HOSTED_AI,
                              customer_type=NON_DEFENCE_CUSTOMER)) == ["own", "same"]


def test_recheck_propagates_an_unreadable_level(idx):
    add(idx, "bolt note")

    def unreadable(_):
        raise OSError("CRM unreachable")

    with pytest.raises(OSError):
        idx.recheck(unreadable, read_at=READ_AT)
    assert idx.count("OPP-1") == 1


# --- the table agrees with the crm's copy ---------------------------------------

# The crm checkout beside this repo's clone or beside its worktrees folder.
CRM_GATE = next((p / "fsg-estimating-crm/scripts/lib/nda_gate.py"
                 for p in Path(__file__).resolve().parents[2:4]
                 if (p / "fsg-estimating-crm/scripts/lib/nda_gate.py").exists()),
                Path("fsg-estimating-crm/scripts/lib/nda_gate.py"))


@pytest.mark.skipif(not CRM_GATE.exists(), reason=f"no crm checkout at {CRM_GATE}")
def test_permits_match_crm_nda_gate():
    spec = importlib.util.spec_from_file_location("crm_nda_gate", CRM_GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    for lane in (HOSTED_AI, LOCAL_AI):
        crm = {d for d in gate.DETERMINATION_VERDICTS if gate.permits(d, lane)}
        assert crm == ti.PERMITS[lane], lane
    assert gate.LOCAL_PERMIT_NEEDS_FLAG == ti.LOCAL_PERMIT_NEEDS_FLAG
    assert set(gate.DETERMINATION_VERDICTS) - {ti.UNDER_REVIEW} == ti.INDEXABLE
