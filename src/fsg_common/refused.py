"""One exit-code rule for every check (crm#2815 item 6).

    0  pass: the check ran and found nothing wrong
    1  finding: the check ran and found a problem
    2  not established: the check could not run or could not read its input

Absent input is never a pass and never a finding: it is 2. ``Refused`` is the
one exception to raise for "not established"; ``run_check`` turns it into 2.
"""
from __future__ import annotations

import sys
from collections.abc import Callable

PASS = 0
FINDING = 1
NOT_ESTABLISHED = 2


class Refused(Exception):
    """The check could not be established. Carries the reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def exit_code(findings: list | tuple | None) -> int:
    """0 for an empty list, 1 for any finding, 2 when the list was never made.

    ``None`` means the check did not enumerate anything, which is not the same
    as an empty list.
    """
    if findings is None:
        return NOT_ESTABLISHED
    return FINDING if len(findings) else PASS


def run_check(check: Callable[[], list | tuple | None], *, out=None) -> int:
    """Run ``check`` and return the exit code. Prints one line to ``out``.

    ``check`` returns its findings. ``Refused`` (or an OSError reading input)
    gives 2 with ``REFUSED: <reason>``. Any other exception propagates.
    """
    out = out if out is not None else sys.stdout
    try:
        findings = check()
    except Refused as exc:
        print(f"REFUSED: {exc.reason}", file=out)
        return NOT_ESTABLISHED
    except OSError as exc:
        print(f"REFUSED: could not read input: {exc}", file=out)
        return NOT_ESTABLISHED
    code = exit_code(findings)
    if code == NOT_ESTABLISHED:
        print("REFUSED: the check returned no list of findings", file=out)
    elif code == FINDING:
        for item in findings:
            print(f"FINDING: {item}", file=out)
    else:
        print("PASS", file=out)
    return code
