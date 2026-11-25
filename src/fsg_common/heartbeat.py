"""One age check for every heartbeat stamp (crm#2815 item 5).

    python -m fsg_common.heartbeat --file PATH --max-age-hours 6 [--mtime]

Exit 0 fresh, 1 stale, 2 not readable. A missing file, an empty file or a stamp
that does not parse is 2 ("not established"), never 1: "never ran" and "stale"
are different facts and must not share a code. A stamp more than ``SKEW`` in the
future is also 2, because a clock that wrong proves nothing.

Stamp forms read: ``2026-09-07T22:06:09Z``, ``2026-09-07T22:06:09+08:00``,
``2026-09-07 04:34:23 UTC``. A stamp with no zone is refused, not guessed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

from fsg_common.refused import Refused, run_check

SKEW = dt.timedelta(minutes=5)
_UTC_WORD = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2}) UTC$")


def parse_stamp(text: str) -> dt.datetime:
    """An aware datetime from ``text`` or ``Refused``."""
    s = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not s:
        raise Refused("the stamp is empty")
    m = _UTC_WORD.match(s)
    if m:
        s = f"{m.group(1)}T{m.group(2)}+00:00"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(s)
    except ValueError as exc:
        raise Refused(f"stamp {text.strip()[:40]!r} is not a time") from exc
    if when.tzinfo is None:
        raise Refused(f"stamp {s!r} has no time zone")
    return when


def age_findings(when: dt.datetime, max_age: dt.timedelta,
                 now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now(dt.timezone.utc)
    age = now - when
    if age < -SKEW:
        raise Refused(f"stamp {when.isoformat()} is in the future by {-age}")
    if age > max_age:
        return [f"stale: last stamp {when.isoformat()} is {age} old, limit {max_age}"]
    return []


def check_file(path: str, max_age: dt.timedelta, use_mtime: bool = False,
               now: dt.datetime | None = None) -> list[str]:
    try:
        if use_mtime:
            when = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
        else:
            with open(path, encoding="utf-8") as fh:
                when = parse_stamp(fh.read())
    except OSError as exc:
        raise Refused(f"cannot read {path}: {exc}") from exc
    return age_findings(when, max_age, now)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m fsg_common.heartbeat")
    ap.add_argument("--file", required=True)
    ap.add_argument("--max-age-hours", type=float, required=True)
    ap.add_argument("--mtime", action="store_true", help="use the file's modified time")
    args = ap.parse_args(argv)
    if args.max_age_hours <= 0:
        print("REFUSED: --max-age-hours must be positive")
        return 2
    return run_check(lambda: check_file(
        args.file, dt.timedelta(hours=args.max_age_hours), args.mtime))


if __name__ == "__main__":
    sys.exit(main())
