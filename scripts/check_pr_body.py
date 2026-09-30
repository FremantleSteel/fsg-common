#!/usr/bin/env python3
"""This repo's own copy of the shared pull-request-body gate.

The check itself -- closing keyword, 400-word limit, no attribution line,
`--closing-refs` -- lives in `fsg_common.pr_body` (crm#1719: it was four
drifting copies). This is a thin wrapper, the same shape as
`check_reading_path_word_count.py`. It puts this checkout's own `src` first so
the workflow, which installs nothing, runs the code under test.

    python scripts/check_pr_body.py --event "$GITHUB_EVENT_PATH" --comments first-comment.json
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from fsg_common.pr_body import *  # noqa: E402,F401,F403
from fsg_common.pr_body import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
