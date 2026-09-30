# CLAUDE.md

Context for any Claude Code session working in this repo. Read before touching anything here.

Every message to David and every commit message follows `fsg-estimating-crm/docs/how-to-report.md`.

## What this is

The code shared by the FSG estimating repos, as one package instead of copies kept in step
by hand. Today that is `fsg_common.sections`: FSG's steel section library (`data/
fsg_sections.json`, a snapshot of the workbook's `90_Lists`), the resolver that turns a
drawing's notation into a canonical `Section_ID` or an honest miss, the two rounding policies
the source resolvers disagreed on, and the estimator's substitution list. Two repos import
it: `fsg-tender-review` (`resolve.py` is a shim over it) and `fsg-bluebeam-steel-standards`
(`tools/fsg_mto/sections.py`, which vendors a copy into the share payload).
This repo decides tonnages for both, so it carries their non-negotiables.

## Invariants

Each rule says what to do and what catches you if you don't.

| Rule | What catches it |
| --- | --- |
| **A section the library cannot resolve is a finding, never a guess.** `200 PFC` joins to `200PFC`; `250UB` is three sections and stays unresolved with its candidates named; `6 x 100 x 10 FL` is an honest miss, not 100FL6. A candidate that lands on no real row does not resolve. | `tests/test_sections_anchors.py`, `tests/test_resolver.py`; `tools/parity_report.py` scores whether a change moved the right notations. |
| **Matching is on `mass_kg_per_m`, never the id's digits.** FSG's ids round the mass (250UB25.7 is filed 250UB26), so `nearest` is a tolerance on mass with a margin over the runner-up, and a decimal wall that only the head moved is the same section. | `NEAREST_TOLERANCE`, `NEAREST_MARGIN`, `HEAD_TOLERANCE` in `_resolver.py` and their tests. |
| **The estimators' decisions of 30 Sep 2026 are recorded, not re-derived** (`fsg-tender-review#184`). A bare cold-formed code (`Z20015`) is the `LYS-` row: an exact alias, `cold-formed-bare-lysaght`, refusing on a miss and never snapping to the nearest wall (62% heavy) or to `STR-`. Stratco and Lysaght are interchangeable for pricing (`vendor_equivalences` in `substitutions.json`, pinned to `COLD_FORMED_VENDORS`). **A BT or CT id's trailing number is FSG's nominal mass, rounded to the whole kg/m, and the stored mass is that number (`100BT12` = 12 kg/m)** - 45 rows, a convention, not errors; never re-derive them. | `tests/test_sections_anchors.py`. |
| **A modifier is one of three kinds and they do not blur.** *Material* refuses (`STAINLESS 10 ROD`, `SS`, `ALUMINIUM` give `material-mismatch`). *Finish* drops (`GALV` is the same steel). *Shape* drops only where the library carries that shape (`10 SQ ROD` is 10SQ); where it does not (`THREADED`, `HEX`) the answer is `shape-modifier`, naming the word and the plain section it ruled out, never that section asserted as canonical. | `_NON_STEEL` and `_SHAPE_MODIFIER` in `_resolver.py`; `tests/vocabulary.py` carries the notations. |
| **Every change runs `python tools/parity_report.py` against both consumers before it merges.** It reads each consumer's resolver out of its git object store at a pinned ref, never a working tree, and prints the snapshot's rows, date and hash every time. Exit 1 is a disagreement or a comparison it could not establish; neither is a pass. Since both consumers import this package, A-vs-B and A-vs-C are near-tautologies; the report's value is the snapshot identity line and the B-vs-C policy difference (`273 CHS 6.4`, carried deliberately in `_policy.py`). | A person, and the parity report's own exit code. |
| **Fix the case named and the case beside it.** The 6 Sep 2026 code review found eight fixes in five days that broke the neighbouring notation (the sorted flat-bar candidate read `6 x 100 x 10 FL` as 100FL6 while making `FL 100 X 10` work). Every resolver change ships with the neighbouring spellings pinned in the same test file. | `tests/test_resolver.py` is the pattern: the fix and its neighbours together. |

## The two rounding policies

`TENDER_REVIEW` and `BLUEBEAM` differ on exactly one thing, whether a decimal wall one place
off the library's (`273 CHS 6.4` against 273CHS6.35) is `canonical` or `nearest`. That is an
open estimator question (`fsg-tender-review#184` item 1), carried as data, not settled here.
`resolve()` defaults to `TENDER_REVIEW`; the Bluebeam toolkit passes `BLUEBEAM` everywhere.
`tools/known_issues.py` prints the live state of that question and two others every run.

## Bumping the pin in both consumers

A merge here changes nothing downstream until each consumer moves its pin. Do both the same
day, in this order, and paste the suite counts in each PR:

1. `fsg-tender-review`: put the merged commit's full SHA in `fsg-common.pin` at the repo root;
   `ci.yml` installs from it and `scripts/setup_worktree.py` checks the sibling checkout
   against it. Run the suite (`PYTHONPATH=src pytest -q`).
2. `fsg-bluebeam-steel-standards`: put the same SHA in `fsg-common.pin`, run
   `python scripts/vendor_fsg_common.py` (refreshes `tools/fsg_common/` byte for byte from
   this repo's object store, so a `../fsg-common` checkout must hold the commit), then
   `python tools/tests/test_offline.py`. The share payload carries that vendored copy; the
   share itself only changes when David runs the copy commands `share-status` prints.

The snapshot inside this package is regenerated by `scripts/refresh_from_workbook.py` from the
estimating template; never hand-edit `data/fsg_sections.json`. `data/substitutions.json` is
the estimator's list, edited by hand with `date`, `decided_by`, `reason` and `source` on every
entry; both consumers read this copy and neither keeps its own.

## Where things live

- `docs/COMMANDS.md` — **the second axis: I know the task, what do I run?** Every
  command in this repo on one page, grouped by *what you are trying to do* rather than
  by module, each described by its own docstring verbatim. The rest of this file is
  organised by *rationale*, which is load-bearing and is not shrunk by it — the gap it
  closes is findability, not coverage. Generated by `scripts/gen_commands_index.py` from
  the tracked tree, so it cannot silently fall behind the code; the task grouping is a
  human decision in `scripts/commands_index.json` that the script only reads, so a new
  command stays unfiled and `--check` exits 1 until somebody says which task it serves.
  Never edited by hand. **`--check` fails `ci.yml`'s `checks` job, and nothing stops a merge anyway** — David's decision, 10 Sep 2026. Not in the pre-commit hook: the hook is a local convenience, and this gate has to answer the same way for everyone, which is why it reads `git ls-files` rather than the working tree.
- `scripts/rename_github_org.py` — **prep for crm#655 gate line 7** (the five repos moving to
  an FSG-owned org): catalogues every literal `Rostov-au/` across all five repos' tracked
  files, and with `--apply` rewrites it to `<new-org>/`. Dry-run by default, the new org name
  is never guessed, and it never commits or pushes — five repos need five separate commits.
  `docs/org-rename-catalogue-20260915.md` is the 15 Sep 2026 catalogue (132 occurrences across
  the five repos) this script was written from and verified against. As of that date the org
  does not exist yet, so `--apply` has only ever run against a throwaway clone.

## Test and lint

```
PYTHONPATH=src pytest -q          # 326 tests on 7 Sep 2026
ruff check .
python tools/parity_report.py     # needs ../fsg-tender-review and ../fsg-bluebeam-steel-standards
python tools/known_issues.py      # reports, never gates
```

CI (`.github/workflows/ci.yml`) runs the first two on the self-hosted runner; the parity report
needs both sibling checkouts and runs on a developer machine, per its own docstring.
