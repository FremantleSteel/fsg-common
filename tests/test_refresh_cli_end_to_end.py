"""`refresh_from_workbook.py` end to end, against real .xlsx files.

The unit tests either side of this one exercise `validation_failures` and
`provenance_refusals` as functions. That is not enough on its own: the accident
this guards against was a **command someone ran**, and every part of it lived
in `main()` -- which workbook got read, which committed copy got compared, and
whether anything was written. A guard that is correct as a function and unwired
in `main()` would pass every other test in this repo.

So these build actual workbooks with openpyxl, run `main()` against a temporary
data directory, and assert on the exit code and on the bytes on disk.

**The committed library is never the target.** `DATA_DIR` is monkeypatched to a
`tmp_path` in every test here; nothing in this file can write to
`src/fsg_common/sections/data/`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import refresh_from_workbook as R  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


def _workbook(path: Path, *, pfc75: float = 5.92, rhs: float = 16.70):
    """A minimal but structurally real `90_Lists`.

    Only the cells the reader actually touches are populated; the two masses
    that moved in the 1 Sep accident are parameters, so a "stale" workbook here
    differs from a current one exactly the way the real ones did -- in values,
    with nothing structurally wrong.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = R.SHEET_LISTS

    # Weight-class boundaries (AI9:AI11) and labour rates (AH14:AJ19).
    for row, value in ((9, 25.0), (10, 40.0), (11, 80.0)):
        ws.cell(row=row, column=35, value=value)
    for row, name in zip(range(14, 20), ["EL", "L", "M", "H", "WB", "PL/BIS"],
                         strict=True):
        ws.cell(row=row, column=34, value=name)
        ws.cell(row=row, column=35, value=30.0)
        ws.cell(row=row, column=36, value=24.0)
    ws.cell(row=23, column=36, value=12.0)
    ws.cell(row=25, column=36, value=7.85)

    # Section rows, kept clear of the config block above.
    rows = [("310UB40", "TYP", 40.4), ("200PFC", "TYP", 22.9),
            ("75PFC", "TYP", pfc75), ("125x75RHS6", "TYP", rhs)]
    for i, (sid, cat, mass) in enumerate(rows, start=100):
        ws.cell(row=i, column=R.COL_SECTION_ID, value=sid)
        ws.cell(row=i, column=R.COL_CATEGORY, value=cat)
        ws.cell(row=i, column=R.COL_BUILD_DEFAULT, value="Y")
        ws.cell(row=i, column=R.COL_MASS_FINAL, value=mass)
    wb.save(path)
    return path


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(R, "DATA_DIR", str(d))
    return d


def _library(data_dir: Path) -> dict:
    return json.loads((data_dir / "fsg_sections.json").read_text(encoding="utf-8"))


def test_a_first_generation_writes(tmp_path, data_dir, capsys):
    """The control. With no committed copy there is nothing to contradict, and
    the ordinary run must work -- otherwise every refusal below proves only
    that the script is broken."""
    wb = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(wb)]) == 0
    lib = _library(data_dir)
    assert lib["_provenance"]["source"] == str(wb)
    assert {s["section_id"] for s in lib["sections"]} == {
        "310UB40", "200PFC", "75PFC", "125x75RHS6"}


def test_regenerating_from_the_SAME_workbook_still_writes(tmp_path, data_dir):
    """The second control, and the one that matters most: the normal correction
    loop -- edit the workbook, re-run -- must not be blocked by this guard."""
    wb = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(wb)]) == 0
    _workbook(wb, pfc75=5.93)                       # a real correction
    assert R.main(["--workbook", str(wb)]) == 0
    got = {s["section_id"]: s["mass_kg_per_m"] for s in _library(data_dir)["sections"]}
    assert got["75PFC"] == 5.93


def test_a_DIFFERENT_workbook_is_REFUSED_and_nothing_is_written(
        tmp_path, data_dir, capsys):
    """The 1 Sep accident, reproduced: a second workbook that reads perfectly
    cleanly and carries the pre-correction masses."""
    live = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(live)]) == 0
    before = (data_dir / "fsg_sections.json").read_bytes()

    stale = _workbook(tmp_path / "stale.xlsx", pfc75=6.65, rhs=17.92)
    assert R.main(["--workbook", str(stale)]) == 4
    assert (data_dir / "fsg_sections.json").read_bytes() == before, (
        "the committed copy was overwritten by the refused run")

    err = capsys.readouterr().err
    assert "REFUSING TO WRITE" in err
    assert str(stale) in err and str(live) in err, (
        "the refusal must name both workbooks; 'provenance mismatch' alone is "
        "not something an operator can act on")


def test_the_stale_workbook_passes_the_CONTENT_guard(tmp_path, data_dir):
    """Which is why the provenance guard had to exist. Read the stale workbook
    directly and check it: no problems at all."""
    stale = _workbook(tmp_path / "stale.xlsx", pfc75=6.65, rhs=17.92)
    assert R.validation_failures(R.read_workbook(str(stale))[0]) == []


def test_override_writes_and_RECORDS_the_reason_in_the_file(tmp_path, data_dir):
    """A deliberate change of source is legitimate -- the share copy moved once
    already. It must leave a trace in the artefact, not just in a console the
    next reader never sees."""
    live = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(live)]) == 0
    moved = _workbook(tmp_path / "moved.xlsx")
    assert R.main(["--workbook", str(moved),
                   "--override", "template relocated on S:, David 2 Sep"]) == 0
    prov = _library(data_dir)["_provenance"]
    assert prov["source"] == str(moved)
    assert prov["override"] == "template relocated on S:, David 2 Sep"


def test_an_EMPTY_override_reason_is_refused():
    """An override with no reason is the accident wearing a flag."""
    assert R.main(["--workbook", "ignored.xlsx", "--override", "   "]) == 2


def test_an_ordinary_run_records_NO_override_key(tmp_path, data_dir):
    """So the key's presence means something when it is there."""
    assert R.main(["--workbook", str(_workbook(tmp_path / "live.xlsx"))]) == 0
    assert "override" not in _library(data_dir)["_provenance"]


def test_check_reports_a_source_mismatch_even_when_the_CONTENTS_MATCH(
        tmp_path, data_dir, capsys):
    """The exact sentence the card is about. `content_sha256` is computed over
    the body only, so two different workbooks holding the same library hash
    identically and `--check` printed `up to date`. It now says what that
    agreement is and is not, and stops reporting success."""
    live = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(live)]) == 0
    twin = _workbook(tmp_path / "twin.xlsx")            # identical contents

    assert R.main(["--workbook", str(twin), "--check"]) == 1
    out = capsys.readouterr().out
    assert "PROVENANCE MISMATCH" in out
    assert "up to date" not in out, (
        "a hash match against the wrong workbook was reported as health")


def test_check_against_the_right_workbook_is_still_up_to_date(
        tmp_path, data_dir, capsys):
    """The control for the test above -- the clean path must stay clean, or the
    check has simply been made useless rather than made honest."""
    live = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(live)]) == 0
    assert R.main(["--workbook", str(live), "--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_check_writes_nothing_even_when_it_refuses(tmp_path, data_dir):
    live = _workbook(tmp_path / "live.xlsx")
    assert R.main(["--workbook", str(live)]) == 0
    before = (data_dir / "fsg_sections.json").read_bytes()
    twin = _workbook(tmp_path / "twin.xlsx")
    R.main(["--workbook", str(twin), "--check"])
    assert (data_dir / "fsg_sections.json").read_bytes() == before


def test_labour_rates_never_reach_the_public_file_but_go_to_the_private_one(
        tmp_path, data_dir):
    """crm#1775 D1. Control: with --labour-rates-out the rates ARE read and written,
    so the absence from the packaged file is a decision, not a failed read."""
    wb = _workbook(tmp_path / "live.xlsx")
    priv = tmp_path / "private" / "rates.json"
    priv.parent.mkdir()
    assert R.main(["--workbook", str(wb), "--labour-rates-out", str(priv)]) == 0
    assert "labour_rates" not in _library(data_dir)
    assert "rates_block" not in _library(data_dir)["_provenance"]["cells"]
    rates = json.loads(priv.read_text(encoding="utf-8"))["labour_rates"]
    assert set(rates) == {"EL", "L", "M", "H", "WB", "PL/BIS"}


def test_the_committed_snapshot_carries_no_labour_rates():
    from fsg_common.sections import _snapshot
    data = json.loads(Path(_snapshot.default_snapshot_path()).read_text(encoding="utf-8"))
    assert "labour_rates" not in data
