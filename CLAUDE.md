# CLAUDE.md

Context for any Claude Code session working in this repo. Read before touching anything here.

Every message to David and every commit message follows `fsg-estimating-crm/docs/how-to-report.md`.

General working rules (tokens, smallest change, detached jobs, never discarding David's uncommitted work, hooks are policy, hand-backs) live in David's user-level `CLAUDE.md` and the `fsg-lane` skill, not here.

## What this is

The code shared by the FSG estimating repos, as one package instead of copies kept in step by hand. The estimating part is `fsg_common.sections`: FSG's steel section library (`data/fsg_sections.json`, a snapshot of the workbook's `90_Lists`), the resolver that turns a drawing's notation into a canonical `Section_ID` or an honest miss, the two rounding policies, and the estimator's substitution list. Two repos import it: `fsg-tender-review` (`resolve.py` is a shim over it) and `fsg-bluebeam-steel-standards` (`tools/fsg_mto/sections.py`, which vendors a copy into the share payload). It decides tonnages for both, so the rules below are invariants, not suggestions.

It also carries shared repo tooling (leak guard, `COMMANDS.md` generator, PR-body check, reading-path cap); `README.md` lists it. A plausible answer is not better than an honest unresolved result.

## This repo is public

**Nothing private goes in it**: no labour rates or prices, no client, tender or person names, no client documents, no credentials, no paths to the S: drive or the job archive. Read what you are staging before every `git add`.

| Rule | What catches it |
| --- | --- |
| No client data, PII or secrets in any commit | `fsg_common.leak_guard` (CI and the pre-commit hook); `tests/test_leak_guard.py` |
| Sessions working as Claude may not push, open a PR on, merge or comment in this repo. They hand David a patch (`git format-patch`) and he pushes it | A person. There is no check |

## An absent input must not answer

Absent is a third state. It is never the same answer as zero, false, none-found or pass.

- A notation that cannot be read is `unresolved`, with the reason, never an empty string treated as a match.
- A sibling repo, ref or git object that is missing makes `parity_report.py` say "could not be established", never "no difference".
- A count over a set that was never enumerated says so.

**The test:** run the path with the input missing and read what it claims. Pair it with a control proving the same code still answers when the input is present. A test you have never seen fail is not evidence: break the code once and watch it fail.

## Decision boundary

Claude may implement a recorded FSG estimator decision. Claude must not invent, reinterpret, generalise or re-derive one.

If correct behaviour cannot be established from (1) the invariants here, (2) existing tests, (3) recorded policy or substitution data, or (4) the referenced estimator decision, stop and put the question to David. Do not settle it by choosing the conventional engineering reading, outside manufacturer or standards data, the cleanest implementation, the behaviour that makes two consumers agree, or the nearest plausible section. An open policy question stays open until it is decided.

If guidance conflicts, the order is: these invariants; recorded estimator decisions and FSG data; the current task; verification and release rules; implementation guidance; history. A task that conflicts with an invariant is reported to David, never quietly relaxed.

## Invariants

| Rule | What catches it |
| --- | --- |
| **A section the library cannot resolve is a finding, never a guess.** `200 PFC` joins to `200PFC`. `250UB` is three sections and stays unresolved with its candidates named. `6 x 100 x 10 FL` is an honest miss, not `100FL6`. A candidate that lands on no real row does not resolve. | `tests/test_sections_anchors.py`, `tests/test_resolver.py`; `tools/parity_report.py` |
| **Matching is on `mass_kg_per_m`, never the id's digits.** FSG ids round the mass (`250UB25.7` is filed `250UB26`), so `nearest` is a tolerance on mass with a margin over the runner-up, and a decimal wall where only the head moved is the same section. | `NEAREST_TOLERANCE`, `NEAREST_MARGIN`, `HEAD_TOLERANCE` in `_resolver.py` and their tests |
| **The estimators' decisions of 30 Sep 2026 are recorded, not re-derived** (`fsg-tender-review#184`). A bare cold-formed code (`Z20015`) is the `LYS-` row: an exact alias, `cold-formed-bare-lysaght`, a miss if the alias is absent, never snapped to the nearest wall or to a `STR-` row. | `tests/test_sections_anchors.py` |
| **Vendor equivalence is pricing, not resolution.** Stratco and Lysaght are interchangeable for pricing (`vendor_equivalences` in `substitutions.json`, pinned to `COLD_FORMED_VENDORS`). It never changes what the resolver returns. | `tests/test_sections_anchors.py` |
| **A BT or CT id's trailing number is FSG's nominal mass, rounded to the whole kg/m, and the stored mass is that number** (`100BT12` = 12 kg/m). Those 45 rows are a convention, not errors. Never rebuild them from geometry or outside tables. | `tests/test_sections_anchors.py` |
| **A modifier is material, finish or shape, and they do not blur.** *Material* refuses (`STAINLESS 10 ROD`, `SS`, `ALUMINIUM` give `material-mismatch`). *Finish* drops (`GALV` is the same steel). *Shape* drops only where the library carries that shape (`10 SQ ROD` is `10SQ`); where it does not (`THREADED`, `HEX`) the answer is `shape-modifier`, naming the word and the plain section it ruled out, never that section asserted as canonical. | `_NON_STEEL` and `_SHAPE_MODIFIER` in `_resolver.py`; `tests/vocabulary.py` |
| **Fix the case named and the case beside it.** The 6 Sep 2026 review found eight fixes in five days that broke the neighbouring notation: a flat-bar fix read `6 x 100 x 10 FL` as `100FL6` while making `FL 100 X 10` work. Pin the neighbours in the same test file (spacing, reordered dimensions, decimal and rounded wall, modifier present and absent, a real candidate and a similar one that does not exist): a small set, not volume. | `tests/test_resolver.py` is the pattern |
| **Never weaken a test to make a change pass**, and never hand-edit generated output (`data/fsg_sections.json`, `docs/COMMANDS.md`). Fix the source or generator and regenerate. | A person; `gen_commands_index.py --check` in CI |

## The two rounding policies

`TENDER_REVIEW` and `BLUEBEAM` differ on one thing: whether a decimal wall one place off the library's (`273 CHS 6.4` against `273CHS6.35`) is `canonical` or `nearest`. That is an open estimator question (`fsg-tender-review#184` item 1), carried as data and not settled here. `resolve()` defaults to `TENDER_REVIEW`; the Bluebeam toolkit passes `BLUEBEAM`. Do not remove the difference to make the consumers agree. `tools/known_issues.py` prints the live state; it reports and never gates.

## Parity is honest or it is not a pass

Before a resolver or library change merges, run `python tools/parity_report.py`. It reads each consumer's resolver from its git object store at a pinned ref, never a working tree, and prints the snapshot's rows, date and hash every time. Both consumers import this package, so its value is the snapshot identity line and the policy difference.

Exit 1 is a disagreement or a comparison it could not establish. Neither is a pass. If a sibling repo, ref or object is missing, do not build state to get a pass: say exactly what could not be established and mark the change not fully verified. Never write "all checks pass" or "fully verified" if a required check did not run or could not answer. Report what changed, what you left alone, the neighbours you pinned, each check's outcome and the parity result.

## Bumping the pin in both consumers

A merge here changes nothing downstream until each consumer moves its pin. Use the same merged full SHA in both repos, the same day, and paste the suite results in each PR. Steps: `docs/bumping-the-pin.md`. Never hand-edit the vendored copy in `fsg-bluebeam-steel-standards`. `data/fsg_sections.json` is regenerated by `scripts/refresh_from_workbook.py`, never hand-edited; `data/substitutions.json` is the estimator's list, edited by hand with `date`, `decided_by`, `reason` and `source` on every entry. Both consumers read this copy.

## Where things live

- `docs/COMMANDS.md` answers "I know the task, what do I run?". Generated by `scripts/gen_commands_index.py` from the tracked tree, never edited by hand. A new command stays unfiled, and `--check` exits 1, until its task group is chosen in `scripts/commands_index.json` or a `# commands-index-group:` comment. Check it before inventing a command.

## Test and lint

```
PYTHONPATH=src pytest -q <the tests you touch>   # laptop: no full suite, at most -n 2
ruff check .
python tools/parity_report.py     # needs ../fsg-tender-review and ../fsg-bluebeam-steel-standards
python tools/known_issues.py      # reports, never gates
```
