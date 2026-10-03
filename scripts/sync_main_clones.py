#!/usr/bin/env python3
"""Fast-forward the five FSG main clones to origin/main (report-only with --check).

This repo's thin wrapper (crm#1964); the logic lives in
`fsg_common.sync_main_clones`. It puts this checkout's own `src` first so a
run uses the code under test.

    python scripts/sync_main_clones.py --check
"""
from __future__ import annotations

# commands-index-group: repo-hygiene
# commands-index-task: my main clones are behind origin / a stale editable fsg_common

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from fsg_common.sync_main_clones import *  # noqa: E402,F401,F403
from fsg_common.sync_main_clones import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(script=__file__))
