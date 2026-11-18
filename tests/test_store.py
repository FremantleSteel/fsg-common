"""fsg_common.store: read-only open, refusals, and a control that it answers."""
import sqlite3
import time

import pytest

from fsg_common import store


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "w.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE quote (job_number TEXT)")
    con.execute("INSERT INTO quote VALUES ('FSG-99Q-901')")
    con.commit()
    con.close()
    return p


def test_reads_present_file(db):
    rows = store.read_rows(db, "SELECT job_number FROM quote")
    assert [r["job_number"] for r in rows] == ["FSG-99Q-901"]


def test_write_refused_by_engine(db):
    con = store.open_readonly(db)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO quote VALUES ('x')")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DROP TABLE quote")
    con.close()


def test_missing_file_refuses_and_is_not_created(tmp_path):
    p = tmp_path / "nope.db"
    with pytest.raises(store.StoreUnavailable, match="no data file"):
        store.open_readonly(p)
    assert not p.exists()


def test_empty_file_refuses(tmp_path):
    p = tmp_path / "e.db"
    p.write_bytes(b"")
    with pytest.raises(store.StoreUnavailable, match="empty"):
        store.open_readonly(p)


def test_not_a_database_refuses(tmp_path):
    p = tmp_path / "junk.db"
    p.write_bytes(b"this is not sqlite" * 50)
    with pytest.raises(store.StoreUnavailable, match="cannot be read"):
        store.open_readonly(p)


def test_directory_refuses(tmp_path):
    with pytest.raises(store.StoreUnavailable, match="not a file"):
        store.open_readonly(tmp_path)


def test_age_limit(db):
    later = time.time() + 10 * 86400
    with pytest.raises(store.StoreUnavailable, match="days old"):
        store.open_readonly(db, max_age_days=7, now=later)
    store.open_readonly(db, max_age_days=7, now=time.time()).close()
    store.open_readonly(db, max_age_days=11, now=later).close()


def test_uri_escapes_and_is_readonly():
    u = store.readonly_uri("C:/a b/x#y?z%.db")
    assert u.endswith("?mode=ro") and "#" not in u and u.count("?") == 1


def test_path_with_special_chars_opens(tmp_path):
    d = tmp_path / "a#b"
    d.mkdir()
    p = d / "w.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t (a)")
    con.commit()
    con.close()
    store.open_readonly(p).close()
