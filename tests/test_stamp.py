"""The one backup stamp (crm#2815 item 8). Dates are invented."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fsg_common.stamp import format_stamp, parse_stamp


def test_format_is_local_and_padded():
    assert format_stamp(datetime(2026, 1, 2, 3, 4, 5)) == "20260102-030405"


def test_round_trip():
    when = datetime(2026, 11, 24, 23, 59, 58)
    assert parse_stamp(format_stamp(when)) == when


def test_now_default_reads_back():
    assert parse_stamp(format_stamp()) is not None


def test_aware_time_becomes_local():
    aware = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    local = aware.astimezone().replace(tzinfo=None)
    assert format_stamp(aware) == local.strftime("%Y%m%d-%H%M%S")


@pytest.mark.parametrize(
    "bad",
    [None, 20260102, "", "2026-01-02", "20260102_030405", "20260102-0304",
     "20260102-030405 ", "20261302-030405", "20260102-250000", "x20260102-030405"],
)
def test_other_formats_are_not_read(bad):
    assert parse_stamp(bad) is None
