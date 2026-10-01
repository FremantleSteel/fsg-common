"""Regenerate the packaged copy of the FSG section library and labour rates.

David's decision, 21 Aug 2026: duplicate `90_Lists` rather than import from
the workbook at run time. That keeps every consumer standalone and testable
with no S: drive, at the cost of the copy going stale -- so the generated
file carries the source path, the date it was taken and a content hash, and
`sections.staleness_warning()` surfaces the age.

    python scripts/refresh_from_workbook.py
    python scripts/refresh_from_workbook.py --workbook <path> --check

THE OUTPUT IS GENERATED. Never hand-edit
`src/fsg_common/sections/data/fsg_sections.json`; change `90_Lists` and
re-run this. `--check` re-reads the workbook and compares the content hash,
which is the only check that answers "does the copy still match" -- an age
threshold cannot, and a snapshot one day old has been 17 rows short.

`data_only=True` is not optional: the mass columns are formulas, and reading
them as text turns every mass into None silently.

**Read-only.** openpyxl must never write to the live workbook. This script
opens read_only=True and writes only into `src/fsg_common/sections/data/`.

ONE SNAPSHOT, ONE PLACE. This used to live in `fsg-tender-review`, writing
into that repo, and the Bluebeam toolkit read the file across a sibling
checkout. Both now read the copy this script generates inside the package,
so a consumer cannot answer from a snapshot vintage it did not choose --
**consolidated here 7 Sep 2026** (fsg-common#6/#12): fsg-tender-review's own
`data/fsg_sections.json` and `scripts/refresh_from_workbook.py` are retired,
and this is the only regenerator either consumer has left.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import PureWindowsPath

# Ported from fsg-tender-review's own copy of this script, 7 Sep 2026 (the
# data-twin consolidation, fsg-common#6/#12) -- this default moved there on
# 4 Sep, after this file was first split off on 5 Sep, so this package had
# fallen behind: it still pointed at S:, which was ALREADY known wrong (see
# the superseded comment tender-review carried and this one now carries
# too). Porting the fix rather than picking the older default is the point
# of "make fsg-common's script the only regenerator" -- consolidating onto a
# stale default would have reintroduced the bug the 4 Sep decision fixed.
#
# Corrected 31 Aug 2026, in the source this was ported from. That version
# read `S:\fsg-estimating-tools\templates\FSG_Estimating_Template.xlsx`,
# which does not exist and never has -- S:'s root holds APPS/Admin/
# Business-Dev/EDA/Estimating/LISTJOBS, no `fsg-estimating-tools`. That path
# is the *repo's* layout written as though it were the share's. So the drift
# check could only ever report "workbook not found", and the one number it
# exists to produce was never produced. The regeneration that did work must
# have been given --workbook explicitly.
#
# The live copy is the one the workbook tooling deploys to and backs up
# beside (FSG_Estimating_Template.xlsx.bak-<date>-pre-<change>).
#
# Superseded 4 Sep 2026 by David's decision to move the library's provenance
# from the S: copy to the tracked template in `fsg-estimating-tools`. The S:
# copy is no longer the source: it still carries the coating rates and the
# fictional CHS wall thicknesses the repo template had corrected, so
# regenerating from it would put them back.
#
# Leaving the default pointed at S: would have recreated the bug described
# above in the opposite direction -- a bare `--check` would compare the
# committed copy against a workbook it did not come from, refuse with
# PROVENANCE MISMATCH, and produce no drift number at all. The default has to
# follow the decision, or the drift check stops working the day it is made.
_SIBLING_TEMPLATE = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "fsg-estimating-tools", "templates", "FSG_Estimating_Template.xlsx")

# fsg-common sits alongside the other repos in the same layout CLAUDE.md
# documents. FSG_ESTIMATING_TEMPLATE overrides it for a checkout arranged
# differently, rather than making every call pass --workbook.
DEFAULT_WORKBOOK = os.environ.get("FSG_ESTIMATING_TEMPLATE") or os.path.normpath(
    os.path.abspath(_SIBLING_TEMPLATE))

# `_provenance.source` is a path that lives in *data* (ADR 14): written on one
# host, read back on another, including CI, where this machine's home
# directory names nothing. Recording the absolute path would make
# `same_workbook` answer False everywhere except the machine that generated it
# -- a refusal that reads as a real provenance mismatch and is not one.
#
# So the sibling template is recorded in the layout-relative form the repos
# share, and both sides of the comparison go through this function. A
# workbook anywhere else keeps its literal path: there is no portable name
# for it, and inventing one would be guessing.
PORTABLE_SIBLING = "../fsg-estimating-tools/templates/FSG_Estimating_Template.xlsx"


def portable_source(path):
    r"""The form of `path` that means the same file on every host.

    The sibling template collapses to `PORTABLE_SIBLING`; everything else is
    returned unchanged, `S:\...` included -- the share is already
    host-independent wherever it is mapped at all.

    Comparison is `PureWindowsPath`-based for the same reason `same_workbook`
    is: `os.path` answers differently on Linux and raises nothing when it does.
    """
    if not path:
        return path
    try:
        here = PureWindowsPath(os.path.normpath(os.path.abspath(path)))
        sibling = PureWindowsPath(
            os.path.normpath(os.path.abspath(_SIBLING_TEMPLATE)))
    except (OSError, ValueError):
        return path
    if str(here).casefold() == str(sibling).casefold():
        return PORTABLE_SIBLING
    return path


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "fsg_common",
                        "sections", "data")

SHEET_LISTS = "90_Lists"
FIRST_ROW, LAST_ROW = 6, 1005          # matches 20_MTO's own MATCH range
COL_SECTION_ID, COL_CATEGORY = 1, 2
COL_BUILD_DEFAULT = 4
COL_MASS_FINAL, COL_PLATE_THK, COL_PLATE_KG_M2 = 7, 8, 9

# Weight-class boundaries and labour rates live in 90_Lists!AI9:AJ19. Cell
# references are recorded with the values so a reader can go and check them.
CELLS = {
    "el_max_kg_per_m": "90_Lists!AI9",
    "l_max_kg_per_m": "90_Lists!AI10",
    "m_max_kg_per_m": "90_Lists!AI11",
    "rates_block": "90_Lists!AH14:AJ19",
    "hollow_piece_weight_kg": "90_Lists!AJ23",
    "steel_density_kg_m2_mm": "90_Lists!AJ25",
}


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_workbook(path: str) -> dict:
    import openpyxl

    # data_only=True is required, not optional: the columns we want are computed.
    # 'Mass/m (kg/m) - FINAL' is `=IF(F6="","",F6)` and 'Plate kg/m2' is a
    # density product, so reading formulas gives strings and every mass silently
    # becomes None -- which then makes every weight class None and every labour
    # figure zero. Caught by the tests, but only because they assert real masses.
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[SHEET_LISTS]

        sections = []
        for row in ws.iter_rows(min_row=FIRST_ROW, max_row=LAST_ROW,
                                min_col=1, max_col=9, values_only=True):
            sid = row[COL_SECTION_ID - 1]
            if not sid or not str(sid).strip():
                continue
            sections.append({
                "section_id": str(sid).strip(),
                "category": str(row[COL_CATEGORY - 1] or "").strip(),
                "build_default": str(row[COL_BUILD_DEFAULT - 1] or "").strip(),
                "mass_kg_per_m": _num(row[COL_MASS_FINAL - 1]),
                "plate_thickness_mm": _num(row[COL_PLATE_THK - 1]),
                "plate_kg_per_m2": _num(row[COL_PLATE_KG_M2 - 1]),
            })

        def cell(ref):
            sheet, addr = ref.split("!")
            return wb[sheet][addr].value

        rates = {}
        for r, key in zip(range(14, 20), ["EL", "L", "M", "H", "WB", "PL/BIS"], strict=True):
            rates[key] = {
                "stick_hrs_per_t": _num(ws.cell(row=r, column=35).value),
                "frame_hrs_per_t": _num(ws.cell(row=r, column=36).value),
            }

        config = {
            "el_max_kg_per_m": _num(ws.cell(row=9, column=35).value),
            "l_max_kg_per_m": _num(ws.cell(row=10, column=35).value),
            "m_max_kg_per_m": _num(ws.cell(row=11, column=35).value),
            "hollow_piece_weight_kg": _num(ws.cell(row=23, column=36).value),
            "steel_density_kg_m2_mm": _num(ws.cell(row=25, column=36).value),
        }
    finally:
        wb.close()

    return {"sections": sections, "labour_rates": rates, "config": config}


# --------------------------------------------------------------------------
# The write guard, added 1 Sep 2026.
#
# `--check` is a CONSISTENCY check, not a validity one: it asks "does the
# committed copy match what I would generate now". So after a bad regeneration
# both sides are bad, they agree, and it reports `up to date` **truthfully**.
# It is not broken and it is not lying -- it answers a different question from
# the one people read it as, and no amount of work on the check path can fix
# that. Only the writer can refuse to make both sides wrong together.
#
# Demonstrated by construction (wt-parallel-f6, 1 Sep 2026), an openpyxl
# round-trip of the workbook against the Excel-written original:
#
#     GOOD  733 sections,  77 masses None (10%),  310UB40 = 40.4
#     BAD   733 sections, 730 masses None (99%),  310UB40 = None
#     committed(bad) vs BAD  ->  UP TO DATE       <- the fail-open
#
# **The section count is identical in both, so counting rows catches nothing.**
# That is the obvious guard and it does not work.

# **A section must carry AT LEAST ONE pricing basis: a per-metre mass or a
# per-square-metre mass.** That is the guard, and it is deliberately not a rule
# about categories.
#
# **Corrected 1 Sep 2026 by David, and the correction closed a fail-open in the
# first version of this guard.** That version exempted the whole `PL` category
# from needing a mass, on the measured observation that every `PL` row in
# today's library is priced by area. His answer: *"floor plate is priced by the
# m2 and other plate by the weight. There are other types of plate that are
# also priced by m2 I cant remember them all."*
#
# So plate is **not** one basis, and the exemption was wrong in the direction
# that matters: a weight-priced plate row whose mass had been lost would have
# been waved through, because it sat in an exempted category. The whole point
# of this guard is to catch a lost mass.
#
# Keying on the basis rather than the category also means **the rule does not
# need the list of m2-priced plate types** -- which is as well, since nobody
# has it. Whatever a row is priced by, it must say so; a workbook whose
# formulas did not evaluate says neither, because BOTH columns are computed
# ('Mass/m (kg/m) - FINAL' is `=IF(F6="","",F6)` and 'Plate kg/m2' is a density
# product).
#
# Measured over the committed library, 733 rows:
#     per-metre only   656
#     per-m2 only       72   (39 PL + 33 BIS)
#     NEITHER            5   (CUSTOM1..CUSTOM5, placeholder rows)
#
# The five CUSTOM placeholders are the only legitimate no-basis rows, and they
# are allowed by NAME rather than by category, so a real section that lands in
# CUSTOM still has to carry a basis.
NO_BASIS_ALLOWED = {"CUSTOM1", "CUSTOM2", "CUSTOM3", "CUSTOM4", "CUSTOM5"}

# Known-good masses. `310UB40` is already the anchor the tests use.
MASS_ANCHORS = {"310UB40": 40.4, "200PFC": 22.9}

# --------------------------------------------------------------------------
# The provenance guard, added 2 Sep 2026 -- the OTHER half of the same accident.
#
# The guard above catches a workbook that did not READ cleanly. It does not
# catch a workbook that read perfectly and was simply the WRONG ONE, which is
# what actually happened on 1 Sep 2026: a bare invocation regenerated from the
# 20 Aug copy on the share, and every mass in it was a real number.
#
# Measured by construction on this branch, against the payload committed at
# `bd85cc2` (21 Aug) -- a stale but structurally perfect library:
#
#     validation_failures(stale)  ->  []          <- it would have been written
#     75PFC        6.65  (the corrected library carries 5.92)
#     125x75RHS6  17.92  (the corrected library carries 16.70)
#
# Both controls passed in the same run -- the mass-stripped payload was refused
# and the current committed library was accepted -- so the clean result on the
# stale payload is the guard's real answer, not a broken probe.
#
# Two facts about the accident, and each gets a rule:
#
#   1. The workbook read was NOT the one the committed copy came from. The two
#      `_provenance.source` values differed and nothing compared them --
#      including `--check`, whose `content_sha256` is computed over the body
#      only, so the source is not in the hash it compares.
#   2. The workbook read was OLDER than the committed copy.
#
# **What rule 2 can and cannot prove, stated rather than assumed.** An mtime
# EARLIER than the committed copy's `taken` date proves the workbook cannot
# contain anything decided since -- that direction is sound. An mtime LATER
# proves nothing at all: a copy onto the share stamps `now` regardless of what
# is inside it. So this refuses the staleness it can see and makes no freshness
# claim, which is why it is a guard and not a check.


def same_workbook(a: str | None, b: str | None) -> bool:
    r"""Do two RECORDED workbook paths name the same file?

    **ADR 14.** `_provenance.source` is a path that lives in *data*: it is read
    back out of a committed JSON file and compared on both hosts -- Windows
    here, Linux in CI. `os.path.normcase` is the identity on Linux and `os.sep`
    is `/` there, so a comparison built on them answers **differently on the
    two hosts for the same two strings**, and raises nothing either way.
    `PureWindowsPath` parses Windows semantics wherever it runs, so
    ``S:/Estimating/x.xlsx``, ``S:\Estimating\x.xlsx`` and
    ``S:\ESTIMATING\X.XLSX`` are one workbook on both.

    A missing value on either side is **not** a match. That is the strict
    direction on purpose: an unrecorded source is exactly the state this guard
    exists to stop being written, so it must not read as agreement.
    """
    if not a or not b:
        return False
    return (str(PureWindowsPath(a)).casefold()
            == str(PureWindowsPath(b)).casefold())


def provenance_refusals(*, workbook: str,
                        workbook_date: dt.date | None,
                        committed: dict | None) -> list[str]:
    """Why this workbook must not overwrite the committed copy.

    Empty list means it may. `committed` is the whole committed payload, or
    None when no committed copy exists -- a first generation has nothing to
    contradict and is allowed.
    """
    if not committed:
        return []
    prov = committed.get("_provenance") or {}
    problems: list[str] = []

    recorded = prov.get("source")
    # Both sides through `portable_source`, so the sibling template compares
    # equal whether it was recorded absolute (pre-4 Sep) or relative.
    if not same_workbook(portable_source(workbook), portable_source(recorded)):
        problems.append(
            f"the committed copy came from a DIFFERENT workbook.\n"
            f"      committed: {recorded or '(no source recorded)'}\n"
            f"      reading:   {workbook}\n"
            f"      Regenerating swaps one workbook's library for another's. "
            f"If that is what you mean, say so with --override.")

    taken_raw = prov.get("generated")
    taken = None
    if taken_raw:
        try:
            taken = dt.date.fromisoformat(str(taken_raw))
        except ValueError:
            problems.append(
                f"the committed copy's `generated` date is unreadable "
                f"({taken_raw!r}), so its age cannot be compared with the "
                f"workbook's. Fix the provenance before regenerating.")
    if taken and workbook_date and workbook_date < taken:
        problems.append(
            f"the workbook is OLDER than the committed copy: last modified "
            f"{workbook_date}, committed copy taken {taken}. It cannot carry "
            f"any correction made since. (The reverse says nothing: a copy "
            f"onto the share stamps today's date whatever is inside it.)")
    return problems


def workbook_date(path: str) -> dt.date | None:
    """The workbook's last-modified date, or None if it cannot be read.

    None rather than a raise, so an unstattable file degrades to "the age rule
    could not run" -- which the caller then SAYS, rather than passing silently.
    """
    try:
        return dt.date.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def validation_failures(payload: dict) -> list[str]:
    """Why this payload must not be written. Empty list means it may be.

    Two independent checks, because either alone can be fooled: an anchor set
    would miss a corruption that spared those rows, and a structural rule would
    miss a workbook that evaluated but evaluated wrongly.
    """
    problems: list[str] = []
    sections = payload.get("sections") or []
    if not sections:
        return ["the workbook produced no sections at all"]

    missing = [s for s in sections
               if s.get("mass_kg_per_m") is None
               and s.get("plate_kg_per_m2") is None
               and str(s.get("section_id") or "").strip().upper()
               not in NO_BASIS_ALLOWED]
    if missing:
        shown = ", ".join(str(s.get("section_id")) for s in missing[:5])
        problems.append(
            f"{len(missing)} of {len(sections)} section(s) carry NO pricing "
            f"basis at all -- neither a per-metre mass nor a per-m2 mass "
            f"({shown}{', ...' if len(missing) > 5 else ''}). Both columns are "
            f"formulas, so this is what reading them without data_only=True, "
            f"or through a tool that drops cached values, produces.")

    by_id = {s.get("section_id"): s for s in sections}
    for sid, expected in sorted(MASS_ANCHORS.items()):
        got = (by_id.get(sid) or {}).get("mass_kg_per_m")
        if got is None:
            problems.append(f"anchor {sid} has no mass (expected {expected})")
        elif abs(float(got) - expected) > 0.05:
            problems.append(f"anchor {sid} is {got}, expected {expected}")
    return problems


# --------------------------------------------------------------------------
# Hand-kept `source` citations (fsg-common#42).
#
# `90_Lists` has no source column, so the regenerator used to emit rows with
# no `source` and silently dropped the manufacturer citation tools#64 put on
# four purlin rows (lost in the 1 Oct 2026 regeneration, fsg-common#41). A
# citation is provenance a person wrote. It is carried forward from the
# committed copy, but ONLY while the row it vouches for is unchanged: same id
# and every captured field the same (mass, category, build default, plate
# figures -- the snapshot carries no description column). A row whose mass
# moved no longer has a citation that supports it, so the source is dropped
# and the caller is TOLD, never left to find out afterwards. The source is
# part of the hashed body, so `--check` stays consistent with it.
_ROW_FIELDS = ("category", "build_default", "mass_kg_per_m",
               "plate_thickness_mm", "plate_kg_per_m2")


def carry_sources(payload: dict, committed: dict | None):
    """Return (payload with sources carried forward, notes on any dropped).

    A cited committed row that changed, or is gone from the workbook, is
    reported in the second element, not discarded quietly.
    """
    dropped: list[str] = []
    if not committed:
        return payload, dropped
    old = {s.get("section_id"): s for s in committed.get("sections") or []
           if s.get("source")}
    seen = set()
    for row in payload["sections"]:
        prev = old.get(row["section_id"])
        if prev is None:
            continue
        seen.add(row["section_id"])
        if all(prev.get(f) == row.get(f) for f in _ROW_FIELDS):
            row["source"] = prev["source"]
        else:
            dropped.append(f"{row['section_id']}: row changed since its "
                           f"source was written, source NOT carried")
    for sid in sorted(set(old) - seen):
        dropped.append(f"{sid}: no longer in the workbook, source dropped")
    return payload, dropped


def with_provenance(payload: dict, workbook: str,
                    override: str | None = None) -> dict:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    prov = {}
    if override:
        # Recorded in the artefact, not just printed at the terminal. The whole
        # failure this guards against was invisible afterwards; an override
        # that scrolls past in a console would be too.
        prov["override"] = override
    return {
        "_provenance": {
            **prov,
            "source": portable_source(workbook),
            "sheet": SHEET_LISTS,
            "cells": CELLS,
            "generated": dt.date.today().isoformat(),
            "content_sha256": hashlib.sha256(body.encode()).hexdigest()[:16],
            "note": (
                "Duplicated from the live estimating workbook, not read at run "
                "time. Re-run scripts/refresh_from_workbook.py when the workbook's "
                "section list or labour rates change."
            ),
        },
        **payload,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbook", default=DEFAULT_WORKBOOK)
    ap.add_argument("--check", action="store_true",
                    help="report drift against the committed copy, write nothing")
    ap.add_argument("--override", metavar="REASON",
                    help="write anyway despite a provenance refusal, recording "
                         "REASON in the generated file's _provenance. The reason "
                         "is required, not optional: an override that leaves no "
                         "trace is indistinguishable afterwards from the "
                         "accident it was meant to be different from.")
    args = ap.parse_args(argv)

    if args.override is not None and not args.override.strip():
        print("--override needs a reason", file=sys.stderr)
        return 2

    if not os.path.exists(args.workbook):
        print(f"workbook not found: {args.workbook}", file=sys.stderr)
        return 2

    out_path = os.path.abspath(os.path.join(DATA_DIR, "fsg_sections.json"))
    have = None
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            have = json.load(fh)

    wb_date = workbook_date(args.workbook)
    prov_problems = provenance_refusals(workbook=args.workbook,
                                        workbook_date=wb_date,
                                        committed=have)

    carried, dropped_sources = carry_sources(read_workbook(args.workbook), have)
    for line in dropped_sources:
        print(f"SOURCE DROPPED -- {line}")
    fresh = with_provenance(carried, args.workbook, override=args.override)

    if args.check:
        if have is None:
            print("no committed copy exists")
            return 1
        # Reported BEFORE the hash comparison, because it changes what a hash
        # match means. Two workbooks that happen to hold the same library still
        # are not the same workbook, and "up to date" read against the wrong one
        # is the sentence this whole card exists to stop being printed.
        if prov_problems:
            print("PROVENANCE MISMATCH -- this is not the workbook the "
                  "committed copy came from:")
            for line in prov_problems:
                print(f"  - {line}")
        same = (have.get("_provenance", {}).get("content_sha256")
                == fresh["_provenance"]["content_sha256"])
        if same and prov_problems:
            print(f"  The contents nonetheless MATCH ({len(fresh['sections'])} "
                  f"sections) -- which is agreement between two different "
                  f"workbooks, not confirmation that either is the right one.")
            return 1
        if same:
            # Consistency and validity are different questions. Saying only
            # "up to date" after a bad regeneration is truthful and useless:
            # both sides agree BECAUSE both are wrong. So the check reports
            # validity too, and a valid-looking agreement is stated as such.
            bad = validation_failures(have)
            if bad:
                print(f"MATCHES the workbook ({len(fresh['sections'])} "
                      f"sections) -- BUT BOTH ARE INVALID:")
                for line in bad:
                    print(f"  - {line}")
                print("  A consistency check cannot detect that both sides are "
                      "wrong. Regenerate from the workbook in Excel, not "
                      "through a tool that drops cached formula values.")
                return 1
            print(f"up to date ({len(fresh['sections'])} sections, "
                  f"taken {have['_provenance']['generated']})")
            return 0
        print(f"DRIFT: committed copy taken {have['_provenance']['generated']} "
              f"no longer matches the workbook")
        print(f"  committed: {len(have['sections'])} sections, "
              f"hash {have['_provenance']['content_sha256']}")
        print(f"  workbook:  {len(fresh['sections'])} sections, "
              f"hash {fresh['_provenance']['content_sha256']}")
        return 1

    # The provenance refusal comes first: a workbook that is the wrong one is
    # refused whether or not its contents read cleanly, and the stale 21 Aug
    # library read perfectly cleanly.
    if prov_problems and not args.override:
        print("REFUSING TO WRITE -- provenance:", file=sys.stderr)
        for line in prov_problems:
            print(f"  - {line}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Nothing was written; the committed copy is untouched.",
              file=sys.stderr)
        print("  Point --workbook at the workbook the committed copy names, "
              "or pass --override \"<why>\" to record a deliberate change of "
              "source.", file=sys.stderr)
        return 4
    if prov_problems and args.override:
        print(f"OVERRIDDEN: {args.override}")
        for line in prov_problems:
            print(f"  overriding: {line}")
    if wb_date is None:
        # The age rule could not run. Said, not swallowed -- a guard that goes
        # quiet when it cannot measure is the fail-open this repo keeps finding.
        print("NOTE: the workbook's modified date could not be read, so the "
              "age rule did not run. Source was still compared.")

    # The guard belongs HERE, not on --check. A check cannot detect that both
    # sides are wrong; only the writer can refuse to make them wrong together.
    problems = validation_failures(fresh)
    if problems:
        print("REFUSING TO WRITE -- the workbook did not read cleanly:",
              file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Nothing was written; the committed copy is untouched.",
              file=sys.stderr)
        print("  The mass columns are formulas. Open the workbook in "
              "Excel and save it, or read it with data_only=True against "
              "a file whose cached values are intact.", file=sys.stderr)
        return 3

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(fresh, fh, indent=1, sort_keys=True)
    print(f"wrote {out_path}")
    print(f"  {len(fresh['sections'])} sections")
    print(f"  labour classes: {', '.join(fresh['labour_rates'])}")
    print(f"  hash {fresh['_provenance']['content_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
