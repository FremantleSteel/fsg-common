import os
import subprocess
import sys

import pytest

from fsg_common import vendor

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


@pytest.fixture
def repo(tmp_path):
    co = tmp_path / "fsg-common"
    (co / "src" / "fsg_common" / "sections").mkdir(parents=True)
    (co / "src" / "fsg_common" / "a.py").write_text("A = 1\n")
    (co / "src" / "fsg_common" / "sections" / "s.json").write_text("{}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(co), *cmd], check=True, env=env)
    sha = subprocess.run(["git", "-C", str(co), "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True).stdout.strip()
    consumer = tmp_path / "consumer"
    (consumer / "scripts" / "fsg_common").mkdir(parents=True)
    (consumer / "scripts" / "fsg_common" / "a.py").write_bytes(b"A = 1\r\n")
    (consumer / "fsg-common.pin").write_text(sha + "\n")
    return co, consumer, sha


def args_for(consumer, co, vendor_dir=None, pin=None):
    return ["--check", "--pin", str(pin or consumer / "fsg-common.pin"),
            "--vendor-dir", str(vendor_dir or consumer / "scripts" / "fsg_common"),
            "--exclude", "sections/", "--checkout", str(co)]


def test_identical_passes_and_crlf_is_not_drift(repo, capsys):
    co, consumer, _ = repo
    assert vendor.main(args_for(consumer, co)) == 0
    assert "PASS" in capsys.readouterr().out


def test_changed_file_is_exit_1_and_named(repo, capsys):
    co, consumer, _ = repo
    (consumer / "scripts" / "fsg_common" / "a.py").write_text("A = 2\n")
    assert vendor.main(args_for(consumer, co)) == 1
    assert "differs from upstream at the pin: a.py" in capsys.readouterr().out


def test_extra_and_missing_files_named(repo, capsys):
    co, consumer, _ = repo
    d = consumer / "scripts" / "fsg_common"
    (d / "a.py").unlink()
    (d / "b.py").write_text("")
    assert vendor.main(args_for(consumer, co)) == 1
    out = capsys.readouterr().out
    assert "missing from the vendored copy: a.py" in out
    assert "not in upstream at the pin: b.py" in out


def test_absent_inputs_are_exit_2_not_pass(repo, capsys):
    co, consumer, sha = repo
    pin = consumer / "fsg-common.pin"
    pin.write_text("abc\n")
    assert vendor.main(args_for(consumer, co)) == 2
    pin.write_text("0" * 40 + "\n")
    assert vendor.main(args_for(consumer, co)) == 2  # commit not in checkout
    assert vendor.main(args_for(consumer, co, pin=consumer / "nope.pin")) == 2
    pin.write_text(sha + "\n")  # valid pin: the next two must fail on their own input
    assert vendor.main(args_for(consumer, co, vendor_dir=consumer / "gone")) == 2
    assert vendor.main(args_for(consumer, consumer / "no-such")) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_module_runs_with_dash_m(repo):
    co, consumer, _ = repo
    (consumer / "scripts" / "fsg_common" / "a.py").write_text("A = 2\n")
    r = subprocess.run([sys.executable, "-m", "fsg_common.vendor", *args_for(consumer, co)],
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": SRC})
    assert r.returncode == 1 and "a.py" in r.stdout
