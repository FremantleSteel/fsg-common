"""fsg_common.nda_levels (crm#2260 steps 1 and 3): every value and use pinned
by hand, absent, unknown and retired inputs refuse, the box rule of D2 = A,
the destruction column, and the JSON equal to the Python."""
from __future__ import annotations

import json

import pytest

from fsg_common import nda_levels as nl

HOSTED, LOCAL = "hosted-ai", "local-ai"

# value -> (level, hosted permits, local permits, destruction), written by hand.
EXPECTED = {
    "Under review":                   ("not decided", False, False, "person"),
    "No NDA":                         ("ordinary", True, True, "tool"),
    "Unrestricted":                   ("ordinary", True, True, "tool"),
    "Approval received":              ("ordinary", True, True, "tool"),
    "Restricted":                     ("restricted", False, True, "held"),
    "Defence - restricted":           ("defence", False, True, "person"),
}
# D3 = A (crm#2260 step 3): the two values the enum lost, written by hand.
RETIRED = ("Approval in progress", "NDA not applicable to this job")
# Not a value: each must refuse both uses, have no level, and go to a person.
NOT_VALUES = [None, "", "   ", "\t", "unrestricted", "UNRESTRICTED", "under review",
              "defence - restricted", "Defence", "Defence – restricted",
              "Unrestricted2", "PERMIT", "Approved", ["No NDA"], ("No NDA",),
              {"value": "No NDA"}, 0, 1, True, b"No NDA", "No NDA", *RETIRED,
              " Approval in progress ", "nda not applicable to this job"]


def test_the_values_are_the_crm_enum_in_order():
    assert nl.VALUES == tuple(EXPECTED)
    assert nl.KNOWN_VALUES == set(EXPECTED)
    assert len(nl.VALUES) == 6


def test_the_retired_values_are_named_and_are_not_values():
    assert nl.RETIRED_VALUES == RETIRED
    assert not set(RETIRED) & nl.KNOWN_VALUES
    for gone in ("APPROVAL_IN_PROGRESS", "NOT_APPLICABLE_TO_JOB"):
        assert not hasattr(nl, gone)


@pytest.mark.parametrize("value", list(EXPECTED))
def test_every_value_and_use_has_the_pinned_answer(value):
    level, hosted, local, destroy = EXPECTED[value]
    assert nl.level_of(value) == level
    assert nl.permits(value, HOSTED) is hosted
    assert nl.permits(value, LOCAL) is local
    assert nl.destruction(value) == destroy
    # A padded stored value is the same value for the verdict.
    assert nl.permits(f"  {value} ", HOSTED) is hosted
    assert nl.permits(f"  {value} ", LOCAL) is local


@pytest.mark.parametrize("value", NOT_VALUES, ids=repr)
def test_a_value_not_in_the_table_never_answers(value):
    for use in (HOSTED, LOCAL):
        assert nl.verdict(value, use) is None
        assert nl.permits(value, use) is False
        for flag in (False, None):
            assert nl.clears_local(value, automated_processing_prohibited=flag) is False
    assert nl.level_of(value) is None
    assert nl.destruction(value) == nl.DESTROY_PERSON
    assert value not in nl.TOOL_LEVELS


def test_verdict_kinds_that_are_not_plain_refusals():
    v = nl.verdict
    assert v("Under review", HOSTED) == v("Under review", LOCAL) == nl.CANNOT_EVALUATE
    assert v("Defence - restricted", HOSTED) == nl.REFUSE_ABSOLUTE
    assert v("Restricted", HOSTED) == nl.REFUSE
    for row in nl.VERDICTS.values():
        assert set(row) == {HOSTED, LOCAL}
        assert set(row.values()) <= set(nl.KINDS)


@pytest.mark.parametrize("use", [None, "", "hosted", "local", "HOSTED-AI", "copy"])
def test_an_unknown_use_raises_and_never_answers(use):
    for call in (lambda: nl.permits("No NDA", use), lambda: nl.verdict("No NDA", use),
                 lambda: nl.permitted_for(use)):
        with pytest.raises(ValueError):
            call()


def test_use_and_the_box_have_no_default():
    with pytest.raises(TypeError):
        nl.permits("No NDA")  # noqa
    with pytest.raises(TypeError):
        nl.clears_local("No NDA")  # noqa


def test_permitted_for_is_the_table_column():
    assert nl.permitted_for(HOSTED) == {"No NDA", "Unrestricted", "Approval received"}
    assert nl.permitted_for(LOCAL) == {"No NDA", "Unrestricted", "Approval received",
                                       "Restricted", "Defence - restricted"}


# --- the box (D2 = A, tender-review ADR 45) -----------------------------------

@pytest.mark.parametrize("value", list(EXPECTED))
def test_ticked_refuses_and_unticked_or_unrecorded_is_the_local_column(value):
    local = EXPECTED[value][2]
    assert nl.clears_local(value, automated_processing_prohibited=True) is False
    assert nl.clears_local(value, automated_processing_prohibited=False) is local
    assert nl.clears_local(value, automated_processing_prohibited=None) is local


@pytest.mark.parametrize("bad", [0, 1, "no", "false", "", [], {}])
def test_a_box_that_is_not_a_boolean_refuses(bad):
    assert nl.clears_local("No NDA", automated_processing_prohibited=bad) is False


def test_approval_received_needs_a_reference_for_hosted():
    assert nl.HOSTED_NEEDS_APPROVAL_REFERENCE == {"Approval received"}


# --- destruction ------------------------------------------------------------------

def test_destruction_lists_are_crm_tool_levels_and_held_levels():
    # crm#2206 (owner, Desk v66): a person handles defence, Restricted and
    # anything else; the tool acts only at these three after D3 = A.
    assert nl.TOOL_LEVELS == ("No NDA", "Unrestricted", "Approval received")
    assert nl.HELD_LEVELS == ("Restricted",)


# --- the table cannot be changed by a caller ----------------------------------------

def test_the_table_is_read_only():
    with pytest.raises(TypeError):
        nl.VERDICTS["Restricted"] = {HOSTED: nl.PERMIT, LOCAL: nl.PERMIT}
    with pytest.raises(TypeError):
        nl.VERDICTS["Restricted"][HOSTED] = nl.PERMIT
    with pytest.raises(TypeError):
        nl.LEVELS["Pending"] = "ordinary"
    with pytest.raises(TypeError):
        nl.DESTRUCTION["Restricted"] = "tool"


# --- the generated JSON ---------------------------------------------------------------

def test_the_json_on_disk_is_the_python_table():
    doc = json.loads(nl.JSON_PATH.read_text(encoding="utf-8"))
    assert doc == nl.as_document()
    rows = {r["value"]: (r["level"], r[HOSTED] == "PERMIT", r[LOCAL] == "PERMIT",
                         r["destruction"]) for r in doc["values"]}
    assert rows == EXPECTED
    assert [r["value"] for r in doc["values"]] == list(EXPECTED)
    assert doc["retired_values_refuse"] == list(RETIRED)
    assert nl.main(["--check"]) == 0


def test_check_fails_on_a_drifted_or_missing_json(tmp_path, monkeypatch, capsys):
    drifted = tmp_path / "nda_levels.json"
    doc = nl.as_document()
    doc["values"][4][LOCAL] = "REFUSE"
    drifted.write_text(json.dumps(doc), encoding="utf-8")
    # real-gate test: test_the_json_on_disk_is_the_python_table
    monkeypatch.setattr(nl, "JSON_PATH", drifted)
    assert nl.main(["--check"]) == 1
    # real-gate test: test_the_json_on_disk_is_the_python_table
    monkeypatch.setattr(nl, "JSON_PATH", tmp_path / "absent.json")
    assert nl.main(["--check"]) == 1
    assert nl.main([]) == 2
    assert "cannot read" in capsys.readouterr().out


def test_write_then_check_round_trips(tmp_path, monkeypatch):
    target = tmp_path / "data" / "nda_levels.json"
    # real-gate test: test_the_json_on_disk_is_the_python_table
    monkeypatch.setattr(nl, "JSON_PATH", target)
    assert nl.main(["--write"]) == 0
    assert nl.main(["--check"]) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == nl.as_document()


def test_module_is_standard_library_only():
    # crm's system1-svc image copies this one file.
    src = nl.__file__ and open(nl.__file__, encoding="utf-8").read()
    imports = sorted(ln for ln in src.splitlines() if ln.startswith(("import ", "from ")))
    assert imports == ["from __future__ import annotations", "from pathlib import Path",
                       "from types import MappingProxyType", "import json", "import sys"]
