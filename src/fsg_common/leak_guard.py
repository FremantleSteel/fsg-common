"""The leak guard: refuse to commit a client document, customer PII, or a
credential. One engine, four repos -- `fsg-tender-review`, `fsg-estimating-
crm`, `fsg-bluebeam-steel-standards` and `fsg-estimating-tools` each carried
an independently-evolved copy of this script (26 Aug - 7 Sep 2026), and each
found and fixed a DIFFERENT real bug the others still carry. Consolidated
7 Sep 2026 (fsg-estimating-tools#116, David: "Yes -- one guard, all repos" --
"the strictest leak guard becomes the shared one... reading both and keeping
the better reasoning, not unioning the patterns").

## What came from where, and why

**File discovery and the zero-files refusal** (`range_files`, `range_ever_
added`, `range_deletions`, the `main()` population-selection and "examined
nothing is not the same as found nothing" refusal) -- `fsg-tender-review`'s
copy, the most complete: its own `range_files` already unions a commit-walk
so a file added then deleted mid-range is still scanned (git history keeps
the blob), and its `--files` handling distinguishes "given, but empty" from
"not given at all" (GNU `xargs` with no `-r` runs a command once on empty
input, which `nargs="*"`'s falsy `[]` could not tell apart from "no --files
flag" -- tr, 4 Sep 2026).

**The historical-content read is NEW here, not ported from anywhere.**
Every existing copy read a `--range`'s file list from git objects but a
file's CONTENT from the working tree with a plain `open()` -- correct only
when the tree already matches the range's own history, which is false for a
file the range's commit-walk finds (added then deleted before the tip, so
never on disk at any point the tree could be checked out to) and false from
inside a pre-commit hook checking a commit that has not been created yet
(`fsg-bluebeam-steel-standards#64`, 7 Sep 2026: this repo's own vendored-file
deletion was the first thing in four repos' history to trigger it -- the
hook's `--range <empty-tree>..HEAD` self-test failed on a file the commit
being made would delete, because HEAD had not moved yet and the working
tree already had). That PR's fix (fall back to `git show <range-target>:
<path>`) is not general enough for tender-review's own shape of the same
problem: a file added then deleted mid-range is absent from EVERY ref, not
just the working tree, so `_range_path_sources()` below finds the actual
commit within the range that most recently touched each such path and reads
the blob from THERE.

**Secret patterns** -- `fsg-estimating-crm`'s unified `password[=:]"value"`
form (measured against real false positives twice: the identifier-prefix
lookbehind it used to carry was tested and reversed by `fsg-tender-review`'s
own PR #92 on 1 Sep 2026 -- 25 real `workbook_password=`/`register_password=`
occurrences here, zero new false positives from removing it, because the
VALUE shape, a quoted 3+ character literal, was doing the discriminating
work all along; and the `/`-exclusion crm's own 29 Aug fix added was itself
measured wrong on 2 Sep -- `/` is in the base64 alphabet, so excluding it
missed five of six realistic generated secrets. crm's current pattern lets
`/` back in with three shape tests at the ACTUAL point of past confusion
instead: not path-shaped, not template-expression-shaped, no leading
whitespace). Plus `fsg-estimating-tools`' two ESCAPED-quote variants (`=`
and `:` forms where the quote characters are themselves backslash-escaped in
the source text, e.g. inside a JSON string or a Python string literal) --
tender-review's own PR #92 named this "gap 3, needs a different rule" and
left it open in both repos it touched; tools closed it independently on
3 Sep 2026 and crm's unified pattern does not cover it (it requires a real,
unescaped quote character). Kept as tools wrote them rather than merged into
crm's pattern, per the "read both, keep the better reasoning, do not union"
instruction -- each is proven in its own repo's tests and a hand-built
hybrid would be proven in neither.

**PII (email/phone) is `fsg-estimating-crm`'s alone** -- the only one of the
four repos with a leak guard that ever had it, added 26 Aug 2026 (this repo
holds real customer data) and put through a dedicated boundary-defect audit
27 Aug 2026 (every pattern opened with `\\b`, which is blind to a value
sitting behind a LITERAL escape sequence in source text -- "Name\\n0400 111
222" has the word-character `n` of `\\n` immediately before the digits, so
`\\b` finds no boundary -- fixed per-pattern, not with one blunt rule) and a
phone-format census against 8,445 real values on 27 Aug 2026 (the WA
bracketed-area-code landline format the patterns could not match until
then). `EMAIL_RE`, `AU_MOBILE_RE`, `AU_LANDLINE_RE` and their allowlist
machinery are ported near-verbatim, because this is the one part of the
sibling copies that already went through exactly the falsification rigor
this whole file exists to preserve.

**Deliberately NOT ported (since crm#1719 slice 4, 1 Oct 2026: ported, but
OFF unless `GuardConfig.enable_espocrm_detectors` is set -- the reasoning below
is why it is off by default)**: `RECORD_ID_RE`, `LITERAL_ID_NAME_RE`,
`NON_CONTACT_TYPE_RE`, the proximity co-occurrence check, and the JSON
`name`+id-literal / n8n `pinData` detectors. These protect against a
re-identification risk specific to EspoCRM record ids sitting next to a
real person's name in THIS repo's own one-off migration scripts
(`fix_blob_accounts.ps1`-shaped incidents) -- the other three repos have no
EspoCRM records and no such scripts, so porting this would add PROXIMITY-
BASED matching that fires on nothing real in three of four repos while
adding a live false-positive surface (a bare 17-hex-character string is not
uniquely an EspoCRM id -- a git SHA prefix is the same shape). David's
decision covers "phone/email detection reaches every repo"; this is a
narrower, repo-specific extension of it that stays in
`fsg-estimating-crm`'s own script.

## How a consumer uses this

A repo does not call `main()` directly with its own flags -- it builds a
`GuardConfig` naming what is actually different about it (the refusal
banner's wording, its own `ALLOWED` path exemptions, any extra secret
pattern, whether PII detection applies) and calls `run(argv, config)`.
Everything else -- the regex engine, the range machinery, the zero-files
refusal, the historical-blob fallback -- is this module's, not the
caller's, so a fix here reaches every repo the next time each bumps its
`fsg-common.pin`, the same mechanism `sections.py` already uses.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

# --- extensions and filenames -----------------------------------------------

#: The baseline every consumer repo already blocked identically. A repo may
#: add its own extras via `GuardConfig.extra_blocked_extensions`.
DEFAULT_BLOCKED_EXTENSIONS: dict[str, str] = {
    ".pdf": "client drawings and specifications",
    ".dwg": "CAD", ".dxf": "CAD", ".ifc": "models", ".rvt": "models",
    ".xls": "job workbooks (client and commercial data)",
    ".xlsx": "job workbooks (client and commercial data)",
    ".xlsm": "job workbooks (client and commercial data)",
    ".xlsb": "job workbooks (client and commercial data)",
    ".csv": "extracts -- usually client, project or commercial data",
    ".jsonl": "crawl indexes (client, project and job names)",
    ".db": "the history warehouse (client and commercial data)",
    ".sqlite": "the history warehouse",
    ".sqlite3": "the history warehouse",
    ".png": "rendered pages / screenshots that may show client data",
    ".jpg": "scans/photos", ".jpeg": "scans/photos",
    ".tif": "scans", ".tiff": "scans",
    ".zip": "packs",
    ".key": "credentials", ".pem": "credentials", ".pfx": "credentials",
}

#: Filenames that are always wrong regardless of extension, in every repo.
BLOCKED_NAMES: tuple[re.Pattern, ...] = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.[^/]*$(?<!\.example)"),
)

# --- secret patterns ---------------------------------------------------------

#: `FSG_WORKBOOK_PASSWORD=`/`FSG_REGISTER_PASSWORD=` -- identical in every
#: repo since this was first written, and narrow enough (a named variable, not
#: a generic word) that the value need not even be quoted.
FSG_CREDENTIAL_RE = re.compile(
    r"FSG_(?:WORKBOOK|REGISTER)_PASSWORD[ \t]*=[ \t]*['\"]?\S+", re.I)

#: The generic `password[=:]"value"` form, crm's current pattern (see module
#: docstring). Matches both `=` and `:` (JSON/YAML), an UNESCAPED quoted
#: value of 3+ non-space characters, and refuses a value that looks like a
#: path (`/p`, `./p`, `../p`, `~/p`, `C:\p`) or a template expression
#: (`{{ ... }}`, `${VAR}`) -- the two shapes that cost this pattern real
#: coverage before they were measured and fixed.
#:
#: The operator spacing is `[ \t]*`, NOT `\s*` -- found by tender-review's
#: OWN test suite (`test_an_assignment_split_across_a_newline_is_not_a_
#: secret`) failing against crm's literal pattern, not by inspection. `\s`
#: matches a real newline, so `password =\n'secret'\n` (an assignment split
#: across a line) matched, and tender-review's own history names the exact
#: incident this reproduces: `FSG_WORKBOOK_PASSWORD=` with an EMPTY value
#: followed by any non-blank next line matched and reported that line's
#: first token as the password. crm's copy of this pattern carries the bug;
#: tender-review's OWN generic-password pattern (a DIFFERENT rule at the
#: time, before this consolidation) already used `[ \t]*` for exactly this
#: reason. Kept as `[ \t]*` here -- the better reasoning, not crm's literal
#: text -- consistent with the module's own "read both, don't union"
#: instruction; this is the one place crm's pattern needed a real edit
#: rather than a straight port.
GENERIC_PASSWORD_RE = re.compile(
    r"password"
    r"['\"]?"                # the JSON key's own closing quote
    r"[ \t]*[=:][ \t]*"      # `=` (python/env) or `:` (json/yaml)
    r"['\"]"
    r"(?!\s)"                # not the space after a CLOSING quote
    r"(?![~.]{0,2}/)"        # not /p, ./p, ../p, ~/p
    r"(?![A-Za-z]:[\\/])"    # not C:\p or C:/p
    r"(?![=$]\{?\{)"         # not ={{expr}} or ${VAR}
    r"(?!\{\{)"              # not {{ expr }}
    r"[^'\"\s]{3,}"          # a secret has no spaces in it
    r"['\"]", re.I)

#: The escaped-quote `=` form -- `password = \"secret\"`, where the quote
#: characters are themselves backslash-escaped in the source text (inside a
#: JSON string or a Python string literal). `fsg-estimating-tools`, 3 Sep
#: 2026. `GENERIC_PASSWORD_RE` cannot see this: it requires a real, unescaped
#: quote character immediately after the operator.
ESCAPED_PASSWORD_EQ_RE = re.compile(
    r"password[ \t]*=[ \t]*\\+['\"][^'\"\\]{3,}\\+['\"]", re.I)

#: The escaped-quote `:` form -- a credential inside a doubly-escaped JSON
#: document or a captured request body. `fsg-estimating-tools`, 3 Sep 2026,
#: with one fix made HERE, 7 Sep 2026, found by this consolidation's own
#: falsification rather than carried over unread: the source pattern
#: delimited the VALUE with `\\*` (zero or more backslashes), so it also
#: matched the plain, UNESCAPED case with none of `GENERIC_PASSWORD_RE`'s
#: template/path exclusions -- `"password": "={{$json.pw}}"`, a real n8n
#: expression shape, matched as a hardcoded password. Changed to `\\+`
#: (one or more) so this pattern only ever fires on a value that is
#: actually escaped, which is the one case `GENERIC_PASSWORD_RE` cannot
#: see; the KEY side stays `\\*`, since whether `"password"` itself is
#: escaped is independent of whether its value is.
ESCAPED_PASSWORD_COLON_RE = re.compile(
    r"\\*['\"]password\\*['\"][ \t]*:[ \t]*\\+['\"][^'\"\\]{3,}\\+['\"]", re.I)

#: The four secret patterns every repo gets. `GuardConfig.extra_secret_
#: patterns` is for something genuinely repo-specific, not a substitute for
#: widening one of these.
DEFAULT_SECRET_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (FSG_CREDENTIAL_RE, "a workbook/register password assigned in tracked source"),
    (GENERIC_PASSWORD_RE, "a hardcoded password"),
    (ESCAPED_PASSWORD_EQ_RE, "a hardcoded password"),
    (ESCAPED_PASSWORD_COLON_RE, "a hardcoded password"),
)

DEFAULT_SCAN_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".md", ".ps1", ".sh", ".toml", ".yaml", ".yml",
    ".json", ".txt", ".cfg", ".ini",
})

#: `.env.example` documents variable names with empty values on purpose, and
#: this module's own source necessarily contains every pattern it looks for.
DEFAULT_CONTENT_SCAN_SKIP: tuple[re.Pattern, ...] = (
    re.compile(r"(^|/)\.env\.example$"),
    re.compile(r"(^|/)check_no_client_data\.py$"),
    re.compile(r"(^|/)leak_guard\.py$"),
)

# --- PII (email/phone), optional per repo -----------------------------------
#
# See the module docstring for the boundary-defect and phone-census history
# behind these three. Ported from fsg-estimating-crm, the only source.

# The local part starts on a letter or digit, and the lookbehind blocks only a
# word character or backslash: a leading `-` `.` `_` `%` `+` is punctuation
# around the address (`${X:-a@b.com}` is the address `a@b.com`, not
# `-a@b.com`), and capturing it made the exact-address allowlist miss.
EMAIL_RE = re.compile(
    r"(?:(?<=\\[nrt])|(?<![A-Za-z0-9\\]))"
    r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

AU_MOBILE_RE = re.compile(r"(?<![0-9])(?:\+61[ \-]?|0[ \-]?)4(?:[ \-]?\d){8}\b")

AU_LANDLINE_RE = re.compile(
    r"(?<![0-9])(?:"
    r"(?:\+61[ \-]?\(?0?\)?[ \-]?[2378]|\(0[2378]\)|0[2378])(?:[ \-]?\d){8}"
    r"|61[2378][ \-]\d{4}[ \-]\d{4}"
    r"|(?:\+61[ \-]?)?[69]\d{3} \d{4}"
    r")\b")

#: RFC 2606 reserves `.invalid` for exactly this: a synthetic address
#: guaranteed to never resolve to a real mailbox.
DEFAULT_ALLOWED_EMAIL_TLDS: frozenset[str] = frozenset({"invalid"})

#: A value that announces itself as synthetic -- a fixture testing the
#: parser itself, not a real credential/contact. Deliberately a VALUE-shape
#: allowance, never a per-file one: it travels with the string, so it cannot
#: exempt a file wholesale the way a path-based rule could.
PLACEHOLDER_VALUE_RE = re.compile(
    r"not-?a-?(?:real-?)?(?:credential|password|secret|key)"
    r"|fake|dummy|synthetic|placeholder|example|changeme|xxxxx",
    re.I,
)


@dataclass(frozen=True)
class GuardConfig:
    """What is actually different between repos. Everything not listed here
    is this module's, shared, and fixed once for all four consumers.

    `repo_holds` / `client_data_lives` fill the BLOCKED banner -- the two
    lines every repo's own script wrote by hand, in its own words, naming
    what it holds and where the real thing actually lives instead.
    """

    repo_holds: str
    client_data_lives: str
    extra_blocked_extensions: dict[str, str] = field(default_factory=dict)
    allowed_paths: tuple[re.Pattern, ...] = ()
    extra_secret_patterns: tuple[tuple[re.Pattern, str], ...] = ()
    extra_content_scan_skip: tuple[re.Pattern, ...] = ()
    extra_scan_extensions: frozenset[str] = frozenset()
    enable_pii: bool = False
    allowed_email_addresses: frozenset[str] = frozenset()
    allowed_email_domains: frozenset[str] = frozenset()
    allowed_email_tlds: frozenset[str] = DEFAULT_ALLOWED_EMAIL_TLDS
    role_account_local_parts: frozenset[str] = frozenset()
    #: crm#1719 slice 4. Off by default: record-id/name proximity, the JSON
    #: merge-plan shape and populated n8n `pinData` (see the block above).
    enable_espocrm_detectors: bool = False
    #: Non-blocking channel for mistyped `+61` and non-AU international
    #: numbers; reported through `check(near_misses=[...])`, never in `problems`.
    enable_near_misses: bool = False
    #: Repo-relative paths whose PII/record-id/near-miss detection is skipped
    #: because the file's job is to exercise a parser. Secret patterns and the
    #: extension/filename rules still apply to them. Exact paths, never a tree.
    pii_exempt_paths: frozenset[str] = frozenset()

    @property
    def blocked_extensions(self) -> dict[str, str]:
        return {**DEFAULT_BLOCKED_EXTENSIONS, **self.extra_blocked_extensions}

    @property
    def secret_patterns(self) -> tuple[tuple[re.Pattern, str], ...]:
        return DEFAULT_SECRET_PATTERNS + self.extra_secret_patterns

    @property
    def content_scan_skip(self) -> tuple[re.Pattern, ...]:
        return DEFAULT_CONTENT_SCAN_SKIP + self.extra_content_scan_skip

    @property
    def scan_extensions(self) -> frozenset[str]:
        return DEFAULT_SCAN_EXTENSIONS | self.extra_scan_extensions



# --- EspoCRM-specific detectors, OFF unless a config opts in -----------------
#
# crm#1719 slice 4 (1 Oct 2026): moved here from `fsg-estimating-crm`'s own
# `scripts/check_no_client_data.py`, behind `GuardConfig.enable_espocrm_
# detectors` / `enable_near_misses`, so crm's script can become a thin wrapper
# like the other three. The reasoning in the "Deliberately NOT ported" note
# above still holds, and is why they are OFF by default: a config that does not
# ask for them gets exactly the behaviour it had before. They are `_`-private
# to the module like the other detectors; `check()` is the surface.
#
# The first block below is verbatim from crm, comments included -- the
# incidents they cite are that repo's.

# EspoCRM record ids observed live are 17 lowercase-hex characters. A bare id
# is just a database key, not PII by itself -- what makes it re-identifying is
# sitting next to a real person's contact details (fix_tender_import_contact_
# conflicts.ps1 paired names+phones with the record id that resolves them;
# contact_merge_plan.json mapped names to record ids directly). So this is
# only ever checked for CO-OCCURRENCE with an email/phone match, never
# flagged bare -- a bare reference in CHANGELOG.md/espocrm/workflows/etc. is
# normal, expected, and not what this control is for.
# `(?<![0-9A-Za-z_])` is the boundary; plus the `(?<=\\[nrt])` branch so an id
# following a literal escape sequence is seen. n/r/t are not hex, so no
# ambiguity about where the match starts.
RECORD_ID_RE = re.compile(r"(?:(?<=\\[nrt])|(?<![0-9A-Za-z_]))[0-9a-f]{17}\b")
PROXIMITY_WINDOW_LINES = 5

# The PowerShell/Python hashtable-literal equivalent of the JSON
# name+survivor/dupes shape above: this project's own convention for a
# one-off "move these records" script is a `@{ id = '<hex>'; name = 'Real
# Person'; ... }` literal, one per line (confirmed real incident:
# fix_blob_accounts.ps1's $contactMoves array). No email/phone needed nearby
# for this one to be identifying -- the id IS the resolving key. Scoped to a
# single physical line deliberately, matching how this project actually
# writes these literals.
LITERAL_ID_NAME_RE = re.compile(
    r"(?:id\s*=\s*['\"][0-9a-f]{17}['\"].{0,200}?name\s*=\s*['\"][^'\"]+['\"]"
    r"|name\s*=\s*['\"][^'\"]+['\"].{0,200}?id\s*=\s*['\"][0-9a-f]{17}['\"])",
    re.IGNORECASE,
)
# A "name" next to a record id is only a person's name when the literal is
# actually describing a Contact -- the identical shape is used throughout
# this project's own one-off cleanup scripts to describe a CDocument/Task/
# Opportunity/CProspect/CEOI's own display name (confirmed real, harmless
# case: cleanup_test_records.ps1's $targets array), which is not personal
# data. A literal naming any OTHER entity type on the same line is exempted;
# one naming Contact, or naming no type at all (fix_blob_accounts.ps1's real
# incident -- no `type` key present), still triggers.
# This one is an EXEMPTION, so a missing left boundary fails in the dangerous
# direction: unanchored, it also matched `contentType`, `mimeType`,
# `entityType` and even `prototype`, any of which would have silently
# exempted a line pairing a live record id with a real person's name. Same
# escape-tolerant boundary as everywhere else, so `type` must be its own
# word.
NON_CONTACT_TYPE_RE = re.compile(
    r"(?:(?<=\\[nrt])|(?<![A-Za-z0-9_]))type\s*=\s*['\"](?!contact['\"])[^'\"]+['\"]",
    re.IGNORECASE)

# Almost every EspoCRM/n8n JSON record has a "name" alongside relational
# foreign-key ids (accountId, createdById, modifiedById, the record's own
# "id") -- that is completely normal and not a PII pairing. What actually
# leaked (contact_merge_plan.json) is a narrower, more specific shape: a
# person's "name" sitting directly alongside "survivor"/"dupes" -- a
# reconciliation plan mapping one name to several different record ids for
# the same underlying person. Keying on that vocabulary, rather than "name
# next to any id", is what keeps this from false-positiving on every
# ordinary CRM record dump.
MERGE_PLAN_SIBLING_KEYS = {"survivor", "dupes"}


def _json_name_id_pairs(norm_path: str, body: str) -> list[str]:
    """Walks parsed JSON looking for the contact-merge-plan shape: a dict with
    a non-empty "name" string sitting alongside a "survivor" and/or "dupes"
    key. Returns human-readable problem strings (never the name/id values
    themselves -- the shape alone is enough to act on), or [] if the file
    isn't JSON or has no such shape.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return []

    problems: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            keys_lower = {k.lower() for k in node}
            if "name" in keys_lower and (keys_lower & MERGE_PLAN_SIBLING_KEYS):
                name_val = node.get("name")
                if isinstance(name_val, str) and name_val.strip():
                    problems.append(
                        f"{norm_path}: a \"name\" field sits alongside "
                        "survivor/dupes record-id fields -- this is the "
                        "contact-merge-plan shape that leaked 65 real names "
                        "mapped to 156 live record ids before"
                    )
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return problems


# n8n pins a node's last output into the workflow JSON so a developer can
# iterate without re-running upstream nodes. That output is whatever the
# node actually returned -- for a node that PATCHes EspoCRM, a live
# Opportunity with the customer's name, contact details and commercials.
# It survives an export and lands in git looking like ordinary workflow
# config.
#
# The rule is deliberately blunt: any populated pinData blocks, regardless
# of what is in it. Every FSG-* workflow in this repo ships "pinData": {},
# so demanding that costs nothing and needs no per-file allowlist. Re-pin
# freely while developing; just clear the pins before committing (n8n:
# "Unpin" on the node, or set the key back to {}).
def _json_populated_pindata(norm_path: str, body: str) -> list[str]:
    """Blocks any non-empty n8n `pinData` map. Reports the node name and a
    field count only -- never the pinned values, which are the very thing
    being kept out of the report."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return []

    problems: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            pin = node.get("pinData")
            if isinstance(pin, dict) and pin:
                for node_name, rows in pin.items():
                    fields = 0
                    if isinstance(rows, list):
                        for row in rows:
                            item = row.get("json", row) if isinstance(row, dict) else row
                            if isinstance(item, dict):
                                fields += sum(
                                    1 for v in item.values()
                                    if v not in (None, "", 0, [], {})
                                )
                    problems.append(
                        f"{norm_path}: n8n pinData is populated on node "
                        f"\"{node_name}\" ({fields} field(s) with values) -- "
                        "a pinned node output is real API data, not a "
                        "fixture; clear the pin before committing"
                    )
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return problems


def _find_record_id_hits(body: str) -> list[tuple[int, str]]:
    return [(body.count("\n", 0, m.start()) + 1, m.group(0))
            for m in RECORD_ID_RE.finditer(body)]


def _proximity_pairing_hits(
    email_hits: list[tuple[int, str]],
    phone_hits: list[tuple[int, str]],
    id_hits: list[tuple[int, str]],
) -> list[str]:
    """For non-JSON text: flags a record-id only when an email or phone match
    (already past the allowlists above) lands within PROXIMITY_WINDOW_LINES of
    it -- the shape fix_tender_import_contact_conflicts.ps1 had (name/phone on
    one line, the resolving record id a couple of lines later)."""
    contact_lines = [ln for ln, _ in email_hits] + [ln for ln, _ in phone_hits]
    if not contact_lines:
        return []
    problems = []
    for id_line, id_val in id_hits:
        if any(abs(id_line - cl) <= PROXIMITY_WINDOW_LINES for cl in contact_lines):
            problems.append(
                f"{id_line}: record id {id_val!r} appears within "
                f"{PROXIMITY_WINDOW_LINES} lines of a customer email/phone match"
            )
    return problems


# --- Near-miss / advisory-only channel --------------------------------------
# REPORTS, NEVER BLOCKS. A blocking rule is the one that acquires exemptions
# when it fires on something legitimate, and exemptions are what opened three
# holes in this guard's history already (see git blame on this file's
# predecessor). A near-miss is a separate signal: it surfaces the value
# without changing what the strict patterns do or what they refuse.

# `+61` followed by a subscriber-digit count that is NOT the valid 9. A real
# AU number in E.164 is +61 plus 9 digits; this catches 8 or 10-11, a typo in
# a real number rather than a foreign one.
# `[ -]` not `[\s-]`: a bare \s matches a newline, so the capture ran past
# the end of the line and carried it into the reported value.
AU_NEAR_MISS_RE = re.compile(r"\+61[ -]?(\d[ -]?){8,11}(?!\d)")

# A non-AU international number: `+` then a country code that is NOT 61, then
# enough digits to be a subscriber number. Measured 1 Sep 2026 over all 350
# tracked text files with a deliberately loose `+CC` shape: 26 candidates, 25
# of them `+61` the strict patterns already cover, 1 a line of documentation
# prose -- zero version strings, zero offsets, zero ids, because requiring a
# literal `+` AND at least 7 following digits excludes `+1.2.3`, `+0800` and
# every offset-shaped token by construction. `(?!61)`: `+615...` is a valid
# non-AU-shaped string only if the digits after 61 do not form an AU
# subscriber number, and the AU patterns above already own that case.
INTL_PHONE_RE = re.compile(
    r"(?<![0-9A-Za-z_.])\+(?!61[ \-]?\d)\d{1,3}[ \-]?(?:\d[ \-]?){6,14}\d(?!\d)")


def _find_international_numbers(body: str) -> list[tuple[int, str]]:
    """Non-AU international numbers -- reported, never blocking."""
    return [(body.count("\n", 0, m.start()) + 1, m.group(0))
            for m in INTL_PHONE_RE.finditer(body)]


def _find_phone_near_misses(body: str) -> list[tuple[int, str]]:
    """Values shaped like a mistyped AU number: `+61` with the wrong number of
    subscriber digits.

    A malformed number is still personal data. Anything the strict patterns
    already catch is excluded, so a valid number is never reported twice.
    """
    strict = {m for _line, m in _find_phone_hits(body)}
    out = []
    for m in AU_NEAR_MISS_RE.finditer(body):
        text = m.group(0)
        if any(text in s or s in text for s in strict):
            continue
        digits = re.sub(r"\D", "", text)
        if len(digits) == 11:            # +61 plus the valid 9
            continue
        out.append((body.count("\n", 0, m.start()) + 1, text.strip()))
    return out



def _looks_like_text(path: str) -> bool:
    """Content sniff for files whose extension is not in `scan_extensions`.

    Extensionless files (`.githooks/pre-commit`, `.gitattributes`) and an
    unforeseen extension cannot be decided by an extension rule at all --
    found 27 Aug 2026 leaving 9-24 tracked files never opened by an
    extension-only version of this check, across two repos independently.
    So the decision is made on content instead: a NUL byte in the first
    8 KB, or bytes that are not valid UTF-8, means binary; anything else is
    treated as text and scanned.

    Deliberately crude, and biased towards scanning. A false "text" verdict
    costs a few wasted regex passes over a binary file; a false "binary"
    verdict is a silent hole, which is the failure being corrected here.
    """
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        # NOT False -- that would be the silent hole this docstring names,
        # taken on a read error. True routes the file to the caller's own
        # read, which records an unreadable file as a problem, not a skip.
        return True
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _run(*args: str) -> list[str]:
    out = subprocess.run(args, capture_output=True, text=True, check=False)
    return [line for line in out.stdout.splitlines() if line.strip()]


class IndexUnreadable(RuntimeError):
    """`git diff --cached` failed: the index could not be read."""


def staged_files() -> list[str]:
    """The staged paths. A git failure raises `IndexUnreadable`: an index that
    could not be read is not an index with nothing staged."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise IndexUnreadable((out.stderr or "git failed").strip())
    return [line for line in out.stdout.splitlines() if line.strip()]


def range_files(rev_range: str) -> list[str]:
    """Every path the range ever ADDED, not the paths it net-added.

    `git diff A..B` is the NET difference between two commits. A PDF
    committed in the middle of a branch and deleted before the tip does not
    appear in it -- and that is precisely the case this guard exists for,
    because git history keeps the blob whatever the tip looks like.

    `git log --diff-filter=AM` walks the commits instead of comparing the
    ends, so a file that came and went is listed. The union is scanned:
    the two-dot diff still contributes renames, which `log --name-only`
    reports under the new name only.
    """
    net = _run("git", "diff", "--name-only", "--diff-filter=ACMR", rev_range)
    ever = _run("git", "log", "--pretty=format:", "--name-only",
                "--diff-filter=AM", rev_range)
    return sorted({p for p in net + ever if p})


def range_deletions(rev_range: str) -> list[str]:
    """The paths the range net-DELETES. A range that only removes files has
    nothing to scan and is not the empty range the refusal in `run()` exists
    for: a PR that deletes one file and nothing else must not be refused for
    selecting "no files" when it could not have leaked anything."""
    return sorted(p for p in _run("git", "diff", "--name-only",
                                  "--diff-filter=D", rev_range) if p)


def _range_path_sources(rev_range: str) -> dict[str, str]:
    """For every path `range_files` can name via its commit-walk half, the
    MOST RECENT commit within the range that added or modified it -- not
    the range's own endpoint.

    This is what makes reading a range's file CONTENT correct, not just its
    file LIST. A path can be in `range_files` because some earlier commit in
    the range added or modified it and a later commit in the SAME range
    deleted it again before the tip -- that file is absent from the working
    tree, absent from the range's target ref, and absent from every
    currently-checked-out state; the only place its content still exists is
    the specific commit that last touched it. `git log` walks newest-first
    by default, so the first commit seen for a path in this walk is already
    the most recent one.
    """
    out = _run("git", "log", "--pretty=format:@@%H", "--name-only",
              "--diff-filter=AM", rev_range)
    sources: dict[str, str] = {}
    current: str | None = None
    for line in out:
        if line.startswith("@@"):
            current = line[2:]
            continue
        if current and line not in sources:
            sources[line] = current
    return sources


def _read_body(
    path: str, path_sources: dict[str, str] | None
) -> tuple[str | None, str | None]:
    """The content to scan for *path* -- the working tree, or, for a
    `--range` check, the git blob at the specific commit
    `_range_path_sources` names for it, if the working-tree read fails --
    paired with a detail string that is non-`None` only when the read
    failed for a reason worth naming separately from a genuine absence.

    Returns `(content, None)` on a successful read. Returns `(None,
    None)` when there is nothing to fall back to at all: no
    `path_sources` (a `--files`/staged check, which has no range), or a
    path `_range_path_sources` never found ANY commit for -- the path
    never existed anywhere in the range, which is exactly what "could
    not be read" already means and the caller's existing wording still
    fits. Returns `(None, detail)` for a third case that used to be
    folded into the same `(None, None)` bucket: a commit WAS found (the
    content provably exists somewhere in this range's history), but the
    `git show <commit>:<path>` subprocess itself exited non-zero --
    measured for real, 11-12 Sep 2026 (fsg-estimating-tools#308): a
    Windows checkout with a long enough absolute path makes `git show`
    itself fail with `fatal: failed to stat '<rev>:<path>': Filename too
    long` (exit 128) for a path `_range_path_sources` had just found via
    `git log`, i.e. the content is real and the failure is the checkout's
    own path length, not a sign of anything absent or unsafe. `detail`
    names the command, its exit code and its stderr so a caller can tell
    that apart from a genuine gap -- one is fixable (a shorter checkout
    path), the other is not fixable at all, and folding them into one
    message left an operator debugging content that was never missing
    (`fsg-estimating-tools`#307's own CI verification run hit exactly
    this and had to be traced by hand before it could be dismissed).

    Reading the working tree assumes it already matches whatever the range's
    file list was computed from -- true in CI (the checked-out commit IS the
    range's own target) but false in at least two real, now-measured cases:
    a file added then deleted mid-range (never on disk at any reachable
    state), and a pre-commit hook checking `--range <empty-tree>..HEAD`
    where the commit that will make HEAD move has not been created yet, so
    a file the in-progress commit deletes is still in HEAD's tree (unmoved)
    but already gone from the working tree (fsg-bluebeam-steel-
    standards#64, 7 Sep 2026). `path_sources` is `None` for `--files`/staged
    checks, which have no range and no fallback -- a missing file there is
    exactly what it looks like.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read(), None
    except OSError:
        if not path_sources:
            return None, None
        commit = path_sources.get(path)
        if commit is None:
            return None, None
        # `text=True` would have `subprocess` decode the blob with the
        # PLATFORM'S default encoding (cp1252 on Windows) and raise
        # `UnicodeDecodeError` out of its own reader thread on a genuinely
        # binary blob (a `.zip`, an image) -- found by running this against
        # a real historical binary file, not assumed. Captured as bytes and
        # decoded the same permissive way the working-tree read already is
        # (`errors="ignore"`): a false "text" verdict on binary content
        # costs a few wasted regex passes, which is the same tradeoff
        # `_looks_like_text`'s own docstring already accepts, not a new one.
        out = subprocess.run(["git", "show", f"{commit}:{path}"],
                             capture_output=True, check=False)
        if out.returncode != 0:
            stderr_text = out.stderr.decode("utf-8", errors="ignore").strip()
            first_line = (stderr_text.splitlines()[0] if stderr_text
                          else "(no stderr captured)")
            detail = (f"`git show {commit}:{path}` exited "
                      f"{out.returncode}: {first_line}")
            return None, detail
        return out.stdout.decode("utf-8", errors="ignore"), None


def _allowed(path: str, config: GuardConfig) -> bool:
    return any(rx.match(path) for rx in config.allowed_paths)


def _find_email_hits(body: str, config: GuardConfig) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for m in EMAIL_RE.finditer(body):
        addr = m.group(0)
        local, _, domain = addr.partition("@")
        if addr.lower() in {a.lower() for a in config.allowed_email_addresses}:
            continue
        domain_l = domain.lower()
        if domain_l in {d.lower() for d in config.allowed_email_domains}:
            continue
        if domain_l.rsplit(".", 1)[-1] in config.allowed_email_tlds:
            continue
        if local.lower() in {p.lower() for p in config.role_account_local_parts}:
            continue
        line = body[:m.start()].count("\n") + 1
        hits.append((line, addr))
    return hits


def _find_phone_hits(body: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for rx in (AU_MOBILE_RE, AU_LANDLINE_RE):
        for m in rx.finditer(body):
            line = body[:m.start()].count("\n") + 1
            hits.append((line, m.group(0)))
    return hits


def check(paths: list[str], config: GuardConfig,
          path_sources: dict[str, str] | None = None,
          read_content: bool = True,
          near_misses: list[str] | None = None) -> list[str]:
    """Blocking problems. `near_misses`, if given and `config.enable_near_
    misses`, is filled with mistyped-AU and non-AU international numbers --
    reported by the caller, never blocking."""
    problems: list[str] = []
    for path in paths:
        norm = path.replace("\\", "/")

        for rx in BLOCKED_NAMES:
            if rx.search(norm):
                problems.append(f"{norm}: credentials file must never be committed")
                break

        ext = os.path.splitext(norm)[1].lower()
        blocked_extensions = config.blocked_extensions
        if ext in blocked_extensions and not _allowed(norm, config):
            problems.append(f"{norm}: {blocked_extensions[ext]} ({ext})")
            continue

        if not read_content:
            continue
        scan_extensions = config.scan_extensions
        if ext not in scan_extensions and not _looks_like_text(path):
            continue
        if any(rx.search(norm) for rx in config.content_scan_skip):
            continue

        body, read_error = _read_body(path, path_sources)
        if body is None:
            if read_error:
                # A commit that touched this path WAS found -- the content
                # provably exists somewhere in this range's history -- but
                # `git show` itself failed. Worded distinctly from the
                # generic gap below on purpose: this is the case measured
                # in fsg-estimating-tools#308 (a Windows checkout whose
                # absolute path is long enough that `git show` itself
                # fails), and it is an ENVIRONMENT failure with a real fix
                # (a shorter checkout path), not evidence the content is
                # absent or unsafe. Still a gap -- this file was NOT
                # scanned either way -- so it still joins `problems` and
                # still blocks, same as the generic gap; only the wording
                # changes, so an operator is not sent chasing content that
                # was never missing.
                problems.append(
                    f"{norm}: git could not read this content even though "
                    f"history says it exists here ({read_error}). This "
                    f"looks like an ENVIRONMENT failure -- a Windows "
                    f"checkout path long enough to make `git show` itself "
                    f"fail is the one measured cause -- not evidence the "
                    f"content is missing or unsafe. The fix is usually a "
                    f"shorter checkout path, not a content change. Still "
                    f"NOT scanned, so this is a gap in the check, not a "
                    f"pass")
            else:
                problems.append(
                    f"{norm}: could not be read, so it was NOT scanned "
                    f"(FileNotFoundError) -- this is a gap in the check, "
                    f"not a pass")
            continue

        for rx, why in config.secret_patterns:
            for hit in rx.finditer(body):
                # `finditer`, not `search`: with `search` a single allowed
                # placeholder earlier in the file would end the scan of
                # that file for this pattern and hide a real credential
                # below it.
                if PLACEHOLDER_VALUE_RE.search(hit.group(0)):
                    continue
                line = body[:hit.start()].count("\n") + 1
                problems.append(f"{norm}:{line}: {why}")
                break
            else:
                continue
            break

        # Secrets above always apply. Everything below is the PII family, and a
        # parser-exercising fixture may be exempted from it by exact path.
        if norm.removeprefix("./") in config.pii_exempt_paths:
            continue

        email_hits: list[tuple[int, str]] = []
        phone_hits: list[tuple[int, str]] = []
        if config.enable_pii or config.enable_espocrm_detectors:
            email_hits = _find_email_hits(body, config)
            phone_hits = _find_phone_hits(body)
        if config.enable_pii:
            for line, addr in email_hits:
                problems.append(f"{norm}:{line}: customer email address ({addr})")
            for line, num in phone_hits:
                problems.append(f"{norm}:{line}: Australian phone number ({num})")

        if near_misses is not None and config.enable_near_misses:
            for line, num in _find_international_numbers(body):
                near_misses.append(
                    f"{path}:{line}: non-AU international number {num}")
            for line, num in _find_phone_near_misses(body):
                near_misses.append(
                    f"{norm}:{line}: looks like a mistyped AU number ({num})")

        if config.enable_espocrm_detectors:
            if ext == ".json":
                problems.extend(_json_name_id_pairs(norm, body))
                problems.extend(_json_populated_pindata(norm, body))
            else:
                id_hits = _find_record_id_hits(body)
                for msg in _proximity_pairing_hits(email_hits, phone_hits, id_hits):
                    problems.append(f"{norm}:{msg}")
                for lineno, line in enumerate(body.splitlines(), start=1):
                    if LITERAL_ID_NAME_RE.search(line) and not NON_CONTACT_TYPE_RE.search(line):
                        problems.append(
                            f"{norm}:{lineno}: a record id and a \"name\" literal "
                            "sit on the same line -- the name+id-literal shape "
                            "that leaked real contact names before"
                        )

    return problems


def tracked_files() -> list[str]:
    return _run("git", "ls-files")


def _make_output_utf8_safe() -> None:
    """A heading or path that cannot be encoded must degrade to a replacement
    character, never take a pre-commit hook down with a codec traceback."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue                      # a redirected non-TTY stream may lack it
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass                          # already detached or not reconfigurable


def run(argv: list[str] | None, config: GuardConfig, *,
        staged=None, tracked=None) -> int:
    """`staged` / `tracked` let a caller supply its own file-list functions,
    looked up at call time (crm's tests reassign them on their wrapper)."""
    staged = staged or staged_files
    tracked = tracked or tracked_files
    _make_output_utf8_safe()
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", dest="rev_range",
                    help="check a commit range instead of the staged files")
    ap.add_argument("--files", nargs="*", help="check these paths explicitly")
    ap.add_argument("--all", action="store_true",
                    help="check every tracked file (CI mode)")
    args = ap.parse_args(argv)

    path_sources: dict[str, str] | None = None
    if args.files:
        paths = args.files
        asked_for = f"--files ({len(args.files)} path(s) given)"
    elif args.files is not None:
        # `--files` GIVEN WITH NO PATHS -- the live CI shape, not a
        # hypothetical: `git ls-files -z | xargs -0 ... --files` runs the
        # command ONCE WITH NO ARGUMENTS on empty input unless xargs was
        # passed `-r`. `nargs="*"` makes that case `[]`, falsy, which used
        # to fall through to `staged_files()` (empty in CI) and report
        # clean. Distinguishing it from `None` is the whole fix.
        paths = []
        asked_for = "--files (given, but with no paths)"
    elif args.rev_range:
        paths = range_files(args.rev_range)
        asked_for = f"--range {args.rev_range}"
        path_sources = _range_path_sources(args.rev_range)
    elif args.all:
        paths = tracked()
        asked_for = "--all"
    else:
        try:
            paths = staged()
        except IndexUnreadable as exc:
            print(f"REFUSED. The staged files could not be read ({exc}), so "
                  "this guard checked nothing.", file=sys.stderr)
            return 2
        asked_for = None            # nothing was requested; the index decides

    # ZERO FILES IS NOT A CLEAN RESULT WHEN A POPULATION WAS ASKED FOR.
    # CI runs `--range <empty-tree>..HEAD`, meant to list every file in
    # HEAD; if that ever came back empty (a shallow clone, a mistyped hash,
    # a rewritten history) the guard would scan nothing and report clean, in
    # green, in the one check whose whole job is to refuse. "Checked
    # everything, found nothing" and "checked nothing" must not look alike.
    #
    # No staged files stays a PASS: an empty index is the normal state of a
    # hook invocation with nothing to commit, nobody asked for a population,
    # and refusing there would make the hook unusable.
    if not paths:
        if asked_for is None:
            print("ok -- no staged files, so there was nothing to check "
                  "(this is not the same as 0 files being clean)")
            return 0
        deleted = range_deletions(args.rev_range) if args.rev_range else []
        if deleted:
            print(f"ok -- {asked_for} only deletes {len(deleted)} file(s) "
                  f"({', '.join(deleted)}); nothing was added or modified, "
                  "so there was nothing to scan (this is not the same as "
                  "0 files being clean)")
            return 0
        print(f"REFUSED. {asked_for} selected NO files, so this guard "
              "checked nothing.", file=sys.stderr)
        print("  A run that examined nothing is not a run that found "
              "nothing. Exiting non-zero", file=sys.stderr)
        print("  rather than reporting clean -- most likely a shallow "
              "clone (CI needs fetch-depth: 0),", file=sys.stderr)
        print("  a bad ref, or a range whose two ends are the same commit.",
              file=sys.stderr)
        return 2

    near_misses: list[str] = []
    problems = check(paths, config, path_sources=path_sources,
                     near_misses=near_misses)

    def _report_near_misses() -> None:
        # After the verdict, never folded into it: a near-miss is worth a
        # human's eye, not a reason to stop a commit.
        if not near_misses:
            return
        print("", file=sys.stderr)
        print(f"  {len(near_misses)} near-miss value(s) -- NOT blocking, "
              f"worth a look:", file=sys.stderr)
        for n in near_misses:
            print(f"    {n}", file=sys.stderr)
        print("    A malformed number is still personal data: it identifies "
              "a person and usually round-trips to a real number by adding "
              "or dropping one digit.", file=sys.stderr)

    if not problems:
        print(f"ok -- {len(paths)} file(s) checked, nothing blocked")
        _report_near_misses()
        return 0

    print(f"BLOCKED. {config.repo_holds}", file=sys.stderr)
    print(f"{config.client_data_lives}\n", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    print("\nGit history keeps a file even after a later deletion, so this "
          "has to be fixed before the commit, not after.", file=sys.stderr)
    return 1
