"""One safe way to open the FSG data file for reading (tr#1836, part 1).

Scope: open the SQLite file read-only, refuse clearly when it is missing,
empty, unreadable or too old. Nothing else.

What this module does NOT do, on purpose: the cleared-rows gate. Which rows
may be shown depends on NDA labels, and those belong to fsg-tender-review
(`connect_cleared` there). That gate must wrap `open_readonly`.
A caller that uses `open_readonly` directly sees every row, so it is for the
build's own checks and for tools that read no client-restricted columns, and
each such use must be named in its own repo's allow-list (tr#1836 part 2).

The rule (tender-review ADR 10): nothing is authored in the file, the build
is the only writer, every other reader is read-only. `mode=ro` makes SQLite
itself refuse a write.
"""
from __future__ import annotations

import pathlib
import sqlite3
import time

__all__ = ["StoreUnavailable", "readonly_uri", "open_readonly", "read_rows"]


class StoreUnavailable(RuntimeError):
    """The file cannot be read. The message says why and what to do."""


def readonly_uri(db_path: str | pathlib.Path) -> str:
    """The one URI builder. Forward slashes on every host; `mode=ro`.

    `%`, `?` and `#` in the path are escaped so they cannot change the query.
    """
    p = pathlib.Path(db_path).as_posix()
    p = p.replace("%", "%25").replace("?", "%3F").replace("#", "%23")
    return f"file:{p}?mode=ro"


def open_readonly(db_path: str | pathlib.Path, *,
                  max_age_days: float | None = None,
                  now: float | None = None) -> sqlite3.Connection:
    """Open read-only, or raise `StoreUnavailable`.

    Refuses when the file is missing, is not a file, is empty, is not a
    SQLite database, or (when `max_age_days` is given) was last written more
    than that many days ago. Absent is never an empty answer.
    """
    p = pathlib.Path(db_path)
    if not p.exists():
        raise StoreUnavailable(
            f"no data file at {p}. Build it first; a missing file is not an "
            f"empty one.")
    if not p.is_file():
        raise StoreUnavailable(f"{p} is not a file.")
    try:
        st = p.stat()
    except OSError as e:
        raise StoreUnavailable(f"cannot read {p}: {e}") from e
    if st.st_size == 0:
        raise StoreUnavailable(f"{p} is empty (0 bytes). Rebuild it.")
    if max_age_days is not None:
        age = ((time.time() if now is None else now) - st.st_mtime) / 86400.0
        if age > max_age_days:
            raise StoreUnavailable(
                f"{p} is {age:.1f} days old, over the {max_age_days} day "
                f"limit. Rebuild it.")
    con = None
    try:
        con = sqlite3.connect(readonly_uri(p), uri=True)
        con.row_factory = sqlite3.Row
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as e:
        if con is not None:
            con.close()
        raise StoreUnavailable(f"{p} cannot be read as a database: {e}") from e
    return con


def read_rows(db_path: str | pathlib.Path, sql: str, params: tuple = (),
              **open_kwargs) -> list[sqlite3.Row]:
    """Open read-only, run one query, close. A write statement raises
    `sqlite3.OperationalError` from the engine, not from a pattern match."""
    con = open_readonly(db_path, **open_kwargs)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()
