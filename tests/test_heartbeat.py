import datetime as dt
import os

import pytest

from fsg_common import heartbeat
from fsg_common.refused import Refused

NOW = dt.datetime(2026, 11, 25, 12, 0, 0, tzinfo=dt.timezone.utc)
H6 = dt.timedelta(hours=6)


@pytest.mark.parametrize("text", ["2026-11-25T11:00:00Z", "2026-11-25 11:00:00 UTC",
                                  "2026-11-25T19:00:00+08:00\n"])
def test_three_stamp_forms_are_one_instant(text):
    assert heartbeat.parse_stamp(text) == dt.datetime(2026, 11, 25, 11, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("text", ["", "  \n", "never", "2026-11-25T11:00:00"])
def test_unreadable_stamp_is_refused(text):
    with pytest.raises(Refused):
        heartbeat.parse_stamp(text)


def test_fresh_and_stale():
    assert heartbeat.age_findings(NOW - dt.timedelta(hours=5), H6, NOW) == []
    out = heartbeat.age_findings(NOW - dt.timedelta(hours=7), H6, NOW)
    assert "stale" in out[0]


def test_future_stamp_is_refused_not_fresh():
    with pytest.raises(Refused):
        heartbeat.age_findings(NOW + dt.timedelta(hours=2), H6, NOW)


def _now_stamp(delta):
    return (dt.datetime.now(dt.timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_cli_exit_codes(tmp_path, capsys):
    f = tmp_path / "hb.txt"
    args = ["--file", str(f), "--max-age-hours", "6"]
    f.write_text(_now_stamp(dt.timedelta(hours=1)))
    assert heartbeat.main(args) == 0
    f.write_text(_now_stamp(dt.timedelta(hours=9)))
    assert heartbeat.main(args) == 1
    assert "stale" in capsys.readouterr().out
    # never ran / unreadable is 2, not 1
    assert heartbeat.main(["--file", str(tmp_path / "missing"), "--max-age-hours", "6"]) == 2
    f.write_text("")
    assert heartbeat.main(args) == 2
    f.write_text("garbage")
    assert heartbeat.main(args) == 2
    assert heartbeat.main(["--file", str(f), "--max-age-hours", "0"]) == 2


def test_mtime_mode(tmp_path):
    f = tmp_path / "hb.txt"
    f.write_text("anything")
    args = ["--file", str(f), "--max-age-hours", "6", "--mtime"]
    assert heartbeat.main(args) == 0
    old = dt.datetime.now().timestamp() - 9 * 3600
    os.utime(f, (old, old))
    assert heartbeat.main(args) == 1
