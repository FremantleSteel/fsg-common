#!/usr/bin/env python3
"""Merge a PR only if its checks are green, then prune.

This repo's thin wrapper (crm#1719, 3 Oct 2026); the logic lives in
`fsg_common.merge_on_green`, one copy for all five repos. It puts this checkout's own
`src` first so a run uses the code under test.

    python scripts/merge_on_green.py <pr> -R FremantleSteel/fsg-common
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from fsg_common.merge_on_green import *  # noqa: E402,F401,F403
from fsg_common.merge_on_green import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
