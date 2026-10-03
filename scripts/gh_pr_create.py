#!/usr/bin/env python3
"""Open a pull request with `gh pr create`, after checking the body.

This repo's thin wrapper (crm#1719, 3 Oct 2026); the logic lives in
`fsg_common.gh_pr_create`, one copy for all five repos. It puts this checkout's own
`src` first so a run uses the code under test.

    python scripts/gh_pr_create.py -R FremantleSteel/fsg-common --body-file pr_body.md --title "..."
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from fsg_common.gh_pr_create import *  # noqa: E402,F401,F403
from fsg_common.gh_pr_create import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
