"""A full-text index (SQLite FTS5) whose every row carries its NDA level (#68).

One module so the NDA filter lives in one place and no consumer re-implements
it. Standard library only (`sqlite3`).

**The levels are the CRM's `Opportunity.cNdaDetermination` values**, and the
table below is ADR 43's (fsg-tender-review, 9 Oct 2026), restated from
`fsg-estimating-crm/scripts/lib/nda_gate.py` (`DETERMINATION_VERDICTS`,
`LOCAL_PERMIT_NEEDS_FLAG`) and `fsg-tender-review/src/fsg_tender_review/nda.py`
(`_PERMITS`). `tests/test_text_index.py` compares it with the crm copy.

    Determination                    hosted  local
    Under review (or none)           refused at insert
    No NDA, Unrestricted             yes     yes
    Approval received                yes, with an approval reference
    Restricted, Approval in progress no      yes, flag recorded
    NDA not applicable to this job   no      no
    Defence - restricted             no      yes, flag recorded, defence customer only

`automated_processing_prohibited` set True excludes a row from both lanes.

**An absent input never answers.** A row with no determination, `Under review`
or an unknown value is refused, with the reason. A row with no Opportunity id is
refused unless the caller passes `NOT_A_TENDER`, which says the text is FSG's
own. A search must name its lane and customer type, or it is refused, and it
returns a `SearchResult` that says how many matches the level filter withheld and
whether the limit cut the list, so an empty or short list is never read as "no
such text".

**A delete destroys the text, not only the match** (crm#2229, crm#2090). Every
connection sets SQLite's `secure_delete` pragma and the FTS5 `secure-delete`
option; measured on 10 Oct 2026, either alone leaves the deleted words in the
file. The delete then reads back the rows, the full-text rows and both settings,
and raises if any of them is wrong.

The index is derived and disposable: every row names its source and the source's
hash, nothing is authored in it, and a consumer rebuilds it from those sources.
The module writes no logs.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

HOSTED_AI = "hosted-ai"
LOCAL_AI = "local-ai"
LANES = (HOSTED_AI, LOCAL_AI)

DEFENCE_CUSTOMER = "defence"
NON_DEFENCE_CUSTOMER = "non-defence"
CUSTOMER_TYPES = (DEFENCE_CUSTOMER, NON_DEFENCE_CUSTOMER)  # tr eoi_kb.CUSTOMERS

UNDER_REVIEW = "Under review"
APPROVAL_RECEIVED = "Approval received"
DEFENCE_RESTRICTED = "Defence - restricted"
NOT_APPLICABLE_TO_JOB = "NDA not applicable to this job"

PERMITS = {
    HOSTED_AI: frozenset({"No NDA", "Unrestricted", APPROVAL_RECEIVED}),
    LOCAL_AI: frozenset({"No NDA", "Unrestricted", APPROVAL_RECEIVED,
                         "Restricted", "Approval in progress", DEFENCE_RESTRICTED}),
}
LOCAL_PERMIT_NEEDS_FLAG = frozenset({"Restricted", "Approval in progress",
                                     DEFENCE_RESTRICTED})
# Every value that may be stored: decided, recognised. `Under review` is not one.
INDEXABLE = PERMITS[LOCAL_AI] | {NOT_APPLICABLE_TO_JOB}


class _NotATender:
    def __repr__(self) -> str:
        return "NOT_A_TENDER"


NOT_A_TENDER = _NotATender()
"""Pass as `opportunity_id` for FSG's own text, which belongs to no tender."""


class IndexRefused(ValueError):
    """An input was absent or not recognised. The message says which."""


@dataclass(frozen=True)
class Hit:
    source: str
    opportunity_id: str | None
    determination: str
    snippet: str


@dataclass(frozen=True)
class SearchResult:
    """`hits` in rank order. `withheld` matches the level filter removed for this
    lane and customer type; `truncated` is True when more permitted matches
    existed than `limit` returned."""
    hits: tuple[Hit, ...]
    withheld: int
    truncated: bool


@dataclass(frozen=True)
class RecheckResult:
    checked: int
    removed: int
    updated: int
    not_a_tender_rows: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    opportunity_id TEXT,
    not_a_tender INTEGER NOT NULL CHECK (not_a_tender IN (0, 1)),
    determination TEXT NOT NULL,
    automated_processing_prohibited INTEGER,
    approval_reference TEXT,
    level_read_at TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    CHECK ((not_a_tender = 1) = (opportunity_id IS NULL))
);
CREATE INDEX IF NOT EXISTS rows_opp ON rows (opportunity_id);
CREATE VIRTUAL TABLE IF NOT EXISTS rows_fts USING fts5 (body);
"""


def _required(name: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IndexRefused(f"{name} is absent; a row without it is not indexed")
    return value.strip()


def _check_level(determination, flag, where: str) -> str:
    if determination is None or not str(determination).strip():
        raise IndexRefused(f"{where}: no NDA determination; an absent level is "
                           f"never defaulted")
    determination = str(determination).strip()
    if determination == UNDER_REVIEW:
        raise IndexRefused(f"{where}: determination is 'Under review'; nobody has "
                           f"decided yet, so it is not indexed")
    if determination not in INDEXABLE:
        raise IndexRefused(f"{where}: determination {determination!r} is not a "
                           f"recognised value")
    if flag is not None and not isinstance(flag, bool):
        raise IndexRefused(f"{where}: automated_processing_prohibited must be "
                           f"True, False or None, not {flag!r}")
    return determination


class TextIndex:
    """One index file. `TextIndex(":memory:")` for tests."""

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        try:
            # Both settings, on every open, so an index made earlier gets them too.
            self.db.execute("PRAGMA secure_delete = ON")
            self.db.executescript(_SCHEMA)
            with self.db:
                self.db.execute("INSERT INTO rows_fts (rows_fts, rank)"
                                " VALUES ('secure-delete', 1)")
        except sqlite3.OperationalError as e:
            self.db.close()
            raise RuntimeError(f"this sqlite3 ({sqlite3.sqlite_version}) cannot "
                               f"build an index whose deletes destroy text: {e}") from e
        self._check_secure_delete("open")

    def _check_secure_delete(self, where: str) -> None:
        pragma = self.db.execute("PRAGMA secure_delete").fetchone()[0]
        option = self.db.execute("SELECT v FROM rows_fts_config"
                                 " WHERE k = 'secure-delete'").fetchone()
        if pragma != 1 or option is None or option[0] != 1:
            raise RuntimeError(f"{where}: secure delete is off (pragma {pragma}, "
                               f"fts5 option {option and option[0]}); a delete "
                               f"would leave the text in the file")

    def close(self) -> None:
        self.db.close()

    def add(self, text: str, *, source: str, opportunity_id, determination,
            automated_processing_prohibited: bool | None, level_read_at: str,
            source_hash: str, approval_reference: str | None = None) -> int:
        """Index one chunk of text. Every keyword is stated by the caller;
        an absent one refuses with the reason. Returns the row id."""
        source = _required("source", source)
        if opportunity_id is NOT_A_TENDER:
            opp, not_a_tender = None, 1
        else:
            opp, not_a_tender = _required(
                "opportunity_id (pass NOT_A_TENDER for FSG's own text)",
                opportunity_id), 0
        determination = _check_level(determination, automated_processing_prohibited,
                                     source)
        level_read_at = _required("level_read_at", level_read_at)
        source_hash = _required("source_hash", source_hash)
        with self.db:
            cur = self.db.execute(
                "INSERT INTO rows (source, opportunity_id, not_a_tender, determination,"
                " automated_processing_prohibited, approval_reference, level_read_at,"
                " source_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source, opp, not_a_tender, determination,
                 None if automated_processing_prohibited is None
                 else int(automated_processing_prohibited),
                 (approval_reference or "").strip() or None, level_read_at,
                 source_hash))
            self.db.execute("INSERT INTO rows_fts (rowid, body) VALUES (?, ?)",
                            (cur.lastrowid, text))
        return cur.lastrowid

    def search(self, query: str, *, lane: str, customer_type: str,
               limit: int | None = 50) -> SearchResult:
        """FTS5 `query`, filtered in SQL to the rows `lane` and `customer_type`
        may see, then cut to `limit` (a positive int; None returns every
        permitted match). Lane and customer type have no default; an absent or
        unknown one refuses."""
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                                  or limit < 1):
            raise IndexRefused(f"limit {limit!r}: a positive whole number, or None "
                               f"for no limit")
        if lane not in LANES:
            raise IndexRefused(f"lane {lane!r}: a search names one of {LANES}")
        if customer_type not in CUSTOMER_TYPES:
            raise IndexRefused(f"customer_type {customer_type!r}: a search names "
                               f"one of {CUSTOMER_TYPES}")
        allowed = set(PERMITS[lane])
        if lane == LOCAL_AI and customer_type != DEFENCE_CUSTOMER:
            allowed.discard(DEFENCE_RESTRICTED)
        allowed = sorted(allowed)
        where = [f"r.determination IN ({','.join('?' * len(allowed))})",
                 "r.automated_processing_prohibited IS NOT 1"]
        params: list = [query, *allowed]
        if lane == LOCAL_AI:
            # Restricted and defence permit a local read only with the flag recorded.
            needs = sorted(LOCAL_PERMIT_NEEDS_FLAG)
            where.append(f"NOT (r.determination IN ({','.join('?' * len(needs))})"
                         " AND r.automated_processing_prohibited IS NULL)")
            params += needs
        else:
            # Hosted: 'Approval received' needs the approval reference recorded.
            where.append("(r.determination != ? OR r.approval_reference IS NOT NULL)")
            params.append(APPROVAL_RECEIVED)
        permitted = " AND ".join(where)
        matched, allowed_n = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN " + permitted + " THEN 1 ELSE 0"
            " END), 0) FROM rows_fts JOIN rows r ON r.id = rows_fts.rowid"
            " WHERE rows_fts MATCH ?", [*params[1:], query]).fetchone()
        sql = ("SELECT r.source, r.opportunity_id, r.determination,"
               " snippet(rows_fts, 0, '[', ']', '...', 12)"
               " FROM rows_fts JOIN rows r ON r.id = rows_fts.rowid"
               " WHERE rows_fts MATCH ? AND " + permitted +
               " ORDER BY rank LIMIT ?")
        params.append(-1 if limit is None else limit)
        hits = tuple(Hit(*row) for row in self.db.execute(sql, params))
        return SearchResult(hits, withheld=matched - allowed_n,
                            truncated=allowed_n > len(hits))

    def count(self, opportunity_id: str) -> int:
        """Rows held for one Opportunity id."""
        opp = _required("opportunity_id", opportunity_id)
        return self.db.execute("SELECT COUNT(*) FROM rows WHERE opportunity_id = ?",
                               (opp,)).fetchone()[0]

    def delete_by_opportunity(self, opportunity_id: str) -> int:
        """Delete every row for one Opportunity id, read back, and return how
        many were deleted. Raises if any remain; an id with no rows returns 0."""
        opp = _required("opportunity_id", opportunity_id)
        self._check_secure_delete(opp)
        ids = [r[0] for r in self.db.execute(
            "SELECT id FROM rows WHERE opportunity_id = ?", (opp,))]
        with self.db:
            self.db.execute("DELETE FROM rows_fts WHERE rowid IN"
                            " (SELECT id FROM rows WHERE opportunity_id = ?)", (opp,))
            deleted = self.db.execute("DELETE FROM rows WHERE opportunity_id = ?",
                                      (opp,)).rowcount
        remaining = self.count(opp)
        text_left = sum(self.db.execute(
            "SELECT COUNT(*) FROM rows_fts WHERE rowid = ?", (i,)).fetchone()[0]
            for i in ids)
        if remaining or text_left:
            raise RuntimeError(f"{opp}: {remaining} rows and {text_left} full-text "
                               f"rows remain after delete")
        self._check_secure_delete(opp)
        return deleted

    def recheck(self, read_level, *, read_at: str) -> RecheckResult:
        """Re-read each indexed Opportunity's level and act on it.

        `read_level(opportunity_id)` returns `(determination,
        automated_processing_prohibited, approval_reference)`, or None when the
        CRM holds no record. It raises when it cannot read; that propagates,
        since an unread level is not a pass. Rows whose level no longer
        qualifies are deleted; rows whose level changed are updated.
        """
        read_at = _required("read_at", read_at)
        ids = [r[0] for r in self.db.execute(
            "SELECT DISTINCT opportunity_id FROM rows WHERE opportunity_id IS NOT NULL")]
        removed = updated = 0
        for opp in ids:
            current = read_level(opp)
            try:
                if current is None:
                    raise IndexRefused(f"{opp}: no CRM record")
                det, flag, ref = current
                det = _check_level(det, flag, opp)
            except IndexRefused:
                removed += self.delete_by_opportunity(opp)
                continue
            with self.db:
                updated += self.db.execute(
                    "UPDATE rows SET determination = ?,"
                    " automated_processing_prohibited = ?, approval_reference = ?,"
                    " level_read_at = ? WHERE opportunity_id = ? AND NOT"
                    " (determination IS ? AND automated_processing_prohibited IS ?"
                    "  AND approval_reference IS ?)",
                    (det, None if flag is None else int(flag),
                     (ref or "").strip() or None, read_at, opp,
                     det, None if flag is None else int(flag),
                     (ref or "").strip() or None)).rowcount
        own = self.db.execute("SELECT COUNT(*) FROM rows WHERE not_a_tender = 1"
                              ).fetchone()[0]
        return RecheckResult(len(ids), removed, updated, own)
