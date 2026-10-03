# fsg-common

Code shared by the four FSG estimating repos. Pure Python, standard library
only.

It started as one module, `fsg_common.sections`: FSG's steel section
library and the resolver that turns a drawing's own notation into a canonical
`Section_ID`, or into an honest miss. It now carries seven more, added 30 Sep to
3 Oct 2026 as the repos' copy-pasted scripts were consolidated (crm#1719):

| Module | What it is |
|---|---|
| `fsg_common.sections` | the section library and resolver (below) |
| `fsg_common.leak_guard` | the leak guard, one engine for four repos; crm's EspoCRM detectors, near-misses, PII exemptions and `--all` are opt-in (#48) |
| `fsg_common.gen_commands_index` | generates `docs/COMMANDS.md`, the task-to-command index (#47) |
| `fsg_common.merge_commands_index` | the git merge driver for `scripts/commands_index.json` (#44) |
| `fsg_common.pr_body` | the pull-request-body check, wrapped by each repo's `scripts/check_pr_body.py` |
| `fsg_common.reading_path` | the compulsory-reading-path word cap |
| `fsg_common.gh_pr_create` | opens a PR after stripping attribution and running the PR-body check, wrapped by each repo's `scripts/gh_pr_create.py` (crm-only until 3 Oct) |
| `fsg_common.merge_on_green` | merges a PR only when its checks are green, then prunes the worktree, wrapped by each repo's `scripts/merge_on_green.py` (crm-only until 3 Oct) |
| `fsg_common.sync_main_clones` | fast-forwards the five main clones to origin/main and refuses anything else (crm#1964), wrapped by each repo's `scripts/sync_main_clones.py` |
| `fsg_common.deploy_tags` | git tags recording what commit is deployed, per artefact: the union of crm's and tools' copies (crm#1976), wrapped by `scripts/deploy_tags.py` in crm and tools |

The public section snapshot no longer carries the labour rates (#46, crm#1775 D1):
each consumer reads them from its own private file. A merge here changes nothing
downstream until each consumer moves its pin.

```python
from fsg_common import sections

section, how = sections.resolve("200 PFC")
# ('200PFC', 22.9, 'exact')
```

## Why it exists

The resolver existed twice. `fsg-tender-review/src/fsg_tender_review/
resolve.py` was 848 lines, `fsg-bluebeam-steel-standards/tools/fsg_mto/
sections.py` was 878, and the two were kept in step by a git hook, a parity
test and a baseline script. The audit of 2 Sep 2026 (Part 3.8) called for one
package instead, and this is the first module of it.

The two copies had already drifted once. On 26 Aug 2026 they were found to
disagree on seven notations, one of them a different mass: `6 mm FLOOR PLATE`
was 49.1 kg/m2 in one and 47.1 in the other.

## The deliverable is the proof, not the move

```
python tools/parity_report.py
```

reads both source repos at a pinned git ref, runs one corpus of 836 notations
through all three implementations, and prints a count. As of 3 Sep 2026:

| Comparison | Agree | Differ |
|---|---|---|
| `fsg_common` (tender-review policy) vs `fsg-tender-review` | 836 | 0 |
| `fsg_common` (bluebeam policy) vs `fsg-bluebeam-steel-standards` | 836 | 0 |
| the two source resolvers against each other | 835 | 1 |

The corpus is three layers: the 70-entry twin-parity vocabulary ported from
`fsg-tender-review/tests/test_resolver_twin_parity.py` (**deleted 5 Sep 2026 with
the twin-parity gate it served — the vocabulary survives only here and in that
repo's git history; noted 10 Sep 2026 so a reader does not go looking**), 23 anchors naming the
rules `fsg-tender-review/CLAUDE.md` states in prose, and every one of the 750
section ids in the library fed back in as a notation. The third layer is there
because a corpus only catches what it exercises, and the two hardest defects
this resolver has had were both cases where the twins agreed with each other
and were both wrong.

## The one thing that used to differ, and how it was settled

`273 CHS 6.4` used to resolve to `273CHS6.35` at 41.77 kg/m in both repos --
`fsg-tender-review` labelled it `canonical`, the Bluebeam toolkit labelled it
`nearest`. Same section, same mass, different verdict, and the verdict decided
whether an estimator was asked to look at the line. That was an open question
for FSG's estimators, item 1 of FremantleSteel/fsg-tender-review#184, carried by a
`RoundingPolicy` parameter (`_policy.py`) rather than picked.

**Answered in two steps.** 7 Sep 2026: both resolvers converged on
`canonical` and `_policy.py` was deleted -- but that only settled the
VERDICT. The mass behind it was still the library's own `273CHS6.35`, the
imperial 6.35 mm wall, not the metric 6.40 mm one the question actually
asked about. 18 Sep 2026: David confirmed the mass directly, "Confirm
metric, 6.40". `273 CHS 6.4` now resolves to a synthesised `273CHS6.4` at
42.1 kg/m (AS/NZS 1163 C350L0) -- a resolver rule (`_chs_metric_wall()` in
`_resolver.py`), not a hand-edit to the generated `data/fsg_sections.json`,
because `90_Lists` has never carried a metric-wall CHS row at all:

```python
sections.resolve("273 CHS 6.4")   # -> ('273CHS6.4', 42.1, 'canonical')
sections.resolve("273 CHS 6.35")  # -> ('273CHS6.35', 41.77, 'exact')
```

The question's wider half -- whether `90_Lists` should carry a full metric
CHS range of its own, rather than this package asserting individual walls --
is still open.

## Layout

```
src/fsg_common/sections/
    _resolver.py    the grammar and SectionLibrary; a near-verbatim copy
    _section.py     the Section dataclass
    _snapshot.py    reading the library, from the packaged JSON or a workbook
    substitutions.py  an estimator's recorded size swap
    data/           the generated section snapshot. Never hand-edit.
scripts/refresh_from_workbook.py   regenerates data/fsg_sections.json
tools/parity_report.py             the three-way comparison
tests/vocabulary.py                the corpus, shared by tests and tools
```

## The snapshot ships inside the package

`data/fsg_sections.json` is generated from `90_Lists` in the estimating
workbook and is byte-identical to the copy both source repos read today.
Never hand-edit it; change the workbook and run
`scripts/refresh_from_workbook.py`.

This is a behaviour change for the Bluebeam toolkit, and a deliberate one. Its
`default_snapshot_path()` pointed at whatever `fsg-tender-review` checkout sat
next to it on disk, so its answers depended on a working tree it did not
control. On 2 Sep 2026 two sessions disagreed about whether `Z20024` resolves,
one reading 733 sections and the other 750, and nothing reported a difference.
`FSG_SECTIONS_SNAPSHOT` still overrides the path when you need it to.

## Running the checks

```
python -m pytest -q          # 260 tests, no sibling repos needed
python -m ruff check .
python tools/parity_report.py   # needs both sibling checkouts
```

`parity_report.py` is not a test. It needs both sibling repos on disk, which
CI does not have, and it fails loudly rather than skipping when it cannot
establish the comparison, because a gate that compared nothing has not agreed
with anything.

## Not built yet

The audit named five modules. Only `sections` is built, because it was the
largest copy and the one with a live drift risk. Still duplicated across the
four repos: `check_no_client_data.py` (four copies, already drifted, 919 lines
in the CRM against 260 in tender-review), the sector enum, the revision
sequence, the `.env` readers and the `FSG_SSH_HOST` resolution.
