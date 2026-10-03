# Adopting the package in the two consumer repos

**Superseded — this adoption is done.** This file is the design, written before either
shim existed. Both repos now import `fsg_common.sections`: `fsg-tender-review/src/
fsg_tender_review/resolve.py` is a shim over it, and `fsg-bluebeam-steel-standards/
tools/fsg_mto/sections.py` re-exports it. **The `RoundingPolicy`/`_policy.py`/
`BLUEBEAM` mechanism this file's code examples and warning below describe was deleted
7 Sep 2026** — both source resolvers had already converged on `canonical` for the one
notation they used to disagree on (`273 CHS 6.4`), so there is nothing left for a
policy parameter to pick between; see `CLAUDE.md`'s "The CHS 6.4 rounding question" and
`README.md`'s "The one thing that used to differ, and how it was settled" for the
current state. Kept below as history, not as a plan to execute — do not follow the
steps or code as written; read each consumer's own module docstring for what it
actually does today.

The order matters: Bluebeam first, because it is the larger copy (878 lines
against 848) and the one whose answers currently depend on a sibling
checkout it does not control.

## Install

Both repos add one line to `requirements.txt`:

```
fsg-common @ git+https://github.com/FremantleSteel/fsg-common@v0.1.0
```

Pin a tag, not a branch. A resolver that changes under a consumer without a
version bump is the drift this package exists to end.

## fsg-bluebeam-steel-standards

`tools/fsg_mto/sections.py` becomes a shim. Keep the file: `deploy.py` tracks
it by path (`SILENT_CONSEQUENCE["fsg_mto/sections.py"]`) and four modules
import from it by relative path.

```python
"""Shim. The resolver lives in `fsg_common.sections`; this re-exports it.

The toolkit keeps its historical rounding verdict until the estimators
answer FremantleSteel/fsg-tender-review#184 item 1 -- see fsg_common's
`sections/_policy.py`. That is why `library()` here is not the package
default.
"""
from fsg_common.sections import *          # noqa: F401,F403
from fsg_common.sections import (          # names the toolkit's tests import
    _NON_STEEL, _SHAPE_MODIFIER, _looks_like_mark,
)
from fsg_common.sections import BLUEBEAM as _POLICY
from fsg_common.sections import (
    load_section_library as _load_workbook,
    load_section_library_from_snapshot as _load_snapshot,
)


def load_section_library(workbook_path):
    return _load_workbook(workbook_path, rounding=_POLICY)


def load_section_library_from_snapshot(json_path):
    return _load_snapshot(json_path, rounding=_POLICY)
```

Three things to get right, each found by reading the repo rather than
assuming:

1. **`tools/tests/test_offline.py` imports private names** -- `_NON_STEEL`,
   `_SHAPE_MODIFIER` and `_looks_like_mark` -- so a shim that re-exports only
   the public surface breaks the suite. They are re-exported above.
2. **The two library loaders must pass `BLUEBEAM`**, or the toolkit's answer
   for `273 CHS 6.4` silently changes from `nearest` to `canonical`. That is
   the one behaviour the package deliberately does not settle, and a shim
   that forgets it settles it by accident.
3. **`deploy.py`'s stale-file consequence text needs rewording.** It says a
   stale `fsg_mto/sections.py` "changes take-off NUMBERS", which stops being
   true once the file is eight lines of re-export: the numbers then come from
   the installed `fsg-common` version. The deploy check should track the
   package version instead, or the warning points at the wrong file.

`default_snapshot_path()` changes meaning, deliberately. It returns the
packaged snapshot rather than reaching into an `fsg-tender-review` checkout,
so the toolkit stops depending on a working tree it does not control.
`FSG_SECTIONS_SNAPSHOT` still overrides.

## fsg-tender-review

`src/fsg_tender_review/resolve.py` becomes the same kind of shim, with the
package default policy, so no call site changes:

```python
"""Shim. The resolver lives in `fsg_common.sections`."""
from fsg_common.sections import *  # noqa: F401,F403
from fsg_common.sections import _looks_like_mark, _NON_STEEL, _SHAPE_MODIFIER  # noqa: F401
```

`classification.py` keeps everything except `Section`, which it re-exports
from the package so `classification.Section` still resolves:

```python
from fsg_common.sections import Section  # noqa: F401
```

`classification.sections()`, `config()`, `labour_rates()` (from a private file since crm#1775) and the band and
weight-class functions stay where they are. They read the same JSON file, and
that file should become the packaged one so there is a single snapshot rather
than two that can drift -- which is the whole point.

Then three things are deleted outright, and deleting them is most of the
value:

- `tests/test_resolver_twin_parity.py`
- `scripts/check_twin_parity.py` and `scripts/twin_parity_baseline.txt`
- the pre-commit hook entry that runs the parity gate

They exist to keep two copies in step. With one copy there is nothing to keep
in step, and the vocabulary they compared on is already ported into this
package's `tests/vocabulary.py`.

`scripts/refresh_from_workbook.py` also goes, replaced by the package's copy.
It is the only writer of the snapshot, and two writers is how the two copies
would drift again.

## Checking the adoption

Per rule 21 of `fsg-estimating-crm/docs/multi-session-working.md`, a clean
merge is not the check. After each shim:

```
python -m pytest -q                          # in the consumer repo
python tools/parity_report.py                # in fsg-common
python tools/known_issues.py                 # in fsg-common
```

`parity_report.py` reads both consumers at a pinned git ref and still
compares them against the package. Run it after the shims land: it is the
thing that says the shim did not change an answer, and it keeps working
because it reads the sibling repos' git objects rather than their imports.
