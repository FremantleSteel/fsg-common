"""One backup stamp: ``YYYYMMDD-HHMMSS`` in local time (crm#2815 item 8).

Backups, bundles and run folders used at least five stamp formats. This is the
one writer and the one reader. A string that is not exactly this format reads
as ``None`` with no guess, so a caller cannot take a bad stamp for an old one.
"""
from __future__ import annotations

import re
from datetime import datetime

STAMP_FORMAT = "%Y%m%d-%H%M%S"
_STAMP_RE = re.compile(r"\d{8}-\d{6}")


def format_stamp(when: datetime | None = None) -> str:
    """Stamp for ``when`` (naive local time), or for now in local time.

    A timezone-aware ``when`` is converted to local time first, so the stamp
    is always local whatever the caller holds.
    """
    if when is None:
        when = datetime.now()
    elif when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when.strftime(STAMP_FORMAT)


def parse_stamp(text: object) -> datetime | None:
    """Read a stamp back. Anything that is not exactly the format is ``None``."""
    if not isinstance(text, str) or not _STAMP_RE.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, STAMP_FORMAT)
    except ValueError:
        return None
