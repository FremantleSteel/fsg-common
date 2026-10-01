#!/usr/bin/env python3
"""Generate docs/COMMANDS.md -- the task-to-command index (thin wrapper).

crm#1719 slice 3: the generator lives in `fsg_common.gen_commands_index`, one
copy for all five repos (they were four drifting copies). Fix it there, never
here. This wrapper only tells the shared code which checkout it is running in.

    python scripts/gen_commands_index.py            # write docs/COMMANDS.md
    python scripts/gen_commands_index.py --check     # exit 1 on drift
    python scripts/gen_commands_index.py --stdout    # print, write nothing
    python scripts/gen_commands_index.py --selftest  # prove --check can fail
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from fsg_common.gen_commands_index import *  # noqa: E402,F401,F403
from fsg_common.gen_commands_index import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(script=__file__))
