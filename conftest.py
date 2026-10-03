"""Put `src/` and `tests/` on the path so the suite runs from a bare checkout.

No editable install, no venv step. `vocabulary.py` lives in `tests/` because
it is shared by the tests and by `tools/parity_report.py`, and neither
should have to reach into the other's directory by relative path.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for path in (ROOT / "src", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# FremantleSteel/fsg-estimating-crm#1981 (the tools#317 leak class): a git hook
# exports GIT_DIR, GIT_INDEX_FILE and other GIT_* variables, and a test's
# `git -C <tmp>` child that inherits them writes to the REAL repository
# (`GIT_DIR` wins over `-C`). Remove every GIT_* from this pytest process before
# any test, or code under test, starts git. Measured 4 Oct 2026: with GIT_DIR on
# a decoy, a full run on main failed 27 tests and committed into the decoy.
import os  # noqa: E402

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
