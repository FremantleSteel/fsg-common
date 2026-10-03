"""Generate docs/COMMANDS.md -- the task-to-command index.

`check_claude_md_coverage.py` solves the adjacent problem: it catches a module,
doc or script that CLAUDE.md has never heard of. It cannot catch the failure
this file exists for, which is UNFINDABILITY -- a tool that IS documented, in a
sentence about something else.

The worked example, and the reason David asked: `extract-year-registers` is
documented. It appears in one clause inside a table cell whose subject is the
warehouse rebuild rule. A session that knows its TASK ("import the tender
register") and not the tool's NAME searches for *import*, *RFQ*, *register* and
finds nothing. The rationale axis is load-bearing and is not shrunk by this
file; this adds the second axis it never had.

    python scripts/gen_commands_index.py            # write docs/COMMANDS.md
    python scripts/gen_commands_index.py --check     # exit 1 on drift
    python scripts/gen_commands_index.py --stdout    # print, write nothing

WHAT IT ENUMERATES

  * Every CLI subcommand: an `X.add_parser("name", help=...)` in a tracked
    `cli.py` or `__main__.py`, read with `ast`, never by regex.
  * Every operator script: a tracked `.py` / `.ps1` under COMMAND_DIRS.
  * Every subcommand a SCRIPT defines of its own (`deploy_receipt.py record`),
    which nothing else in any repo lists.

Tracked means `git ls-files`. An untracked file is deliberately not indexed:
`--check` has to answer the same way for everyone, and a working tree does not.
That is a real limit, so it is stated rather than left to be discovered.

WHERE THE ONE-LINE PURPOSE COMES FROM -- and it is never written here

  * `.py`  : the first non-empty line of the module docstring.
  * `.ps1` : the `.SYNOPSIS` block, or the leading `#` comment paragraph where
             the file uses that convention instead. Both are in live use, and
             reading only the first reported 23 real scripts in
             fsg-estimating-tools as having no purpose at all.

Nothing is paraphrased, invented or improved. A file with no docstring renders
as `(no docstring -- see the file)` and is counted in the Gaps section, because
an index that quietly writes a description for it would be inventing the one
thing a reader is entitled to trust.

The single normalisation: a docstring that opens by repeating the file's own
name (`branch_delta.py -- what does this branch add?`) has that prefix removed,
because the name is already the row it is sitting in.

THE CITATION IS A FILE, NEVER A LINE

A generated citation carries the file (`tools/fsg_mto/cli.py`), not `cli.py:1082`. Line
numbers were tried and removed (bluebeam#76): regenerating at the exact head of
a real merge changed 54 rows in fsg-tender-review's own index, all with
identical command names -- nothing added, removed or renamed -- because an
unrelated 11-line insertion elsewhere in that repo's `cli.py` shifted every
citation below it by exactly +11. `--check` went red with "the code has
commands this file does not", which was not true.

Measured here rather than assumed from that repo: of the 27 commits that ever
touched `tools/fsg_mto/cli.py`, 26 changed its line count. A line-number
citation in this file's index is therefore a drift generator on almost every
touching commit, for reasons that have nothing to do with the index's own
subject -- and the shift lands on any OTHER branch too, once its author has
pushed and can no longer regenerate.

Nothing is lost that the row did not already carry: the subcommand name is in
the same row, so `grep -n 'add_parser("resolve"' tools/fsg_mto/cli.py` is one
step. A stale line number is worse than none -- it sends the reader
confidently to the wrong function, which is the silently-permissive answer
this codebase refuses everywhere else.

It also repairs the POSITIVE CONTROL below. `--selftest` injects a subcommand
ABOVE the first `add_parser` call, so while citations carried line numbers the
injection shifted every one of them: `--check` would have failed on the shift
alone, and the selftest could not tell "noticed the new command" from "noticed
the line move". It now fails only for the reason it claims.

WHERE THE GROUPING COMES FROM -- `scripts/commands_index.json`

The grouping is the entire point and it cannot be derived, so it is a recorded
human decision that this script reads, in the shape `substitutions.json` already
uses in this codebase: a person edits it, the tool consumes it, the tool never
writes it.

A tool the sidecar does not file lands under "Unfiled" and `--check` FAILS.
That is the anti-drift mechanism: a new subcommand cannot be added without
someone saying which task it serves. Filing it is one line.

FILING A COMMAND IN ITS OWN FILE (crm#1798, David's decision of 3 Oct 2026)

A command may say which group it belongs in, and which task phrases find it,
in its own file instead of the sidecar:

    # commands-index-group: what-live-holds
    # commands-index-task: is the scheduled check-in routine running
    # commands-index-task: run it for one quote => python scripts/x.py --quote Q

In a script, these are real `#` comments (read with `tokenize` for `.py`, so
a docstring that only describes the syntax is never read as a filing), and
they file the whole script. Above an `add_parser(...)` call in a `cli.py`,
the contiguous comment lines directly above the call file that subcommand. A
task line maps its phrase to the command's own run line unless it says
`=> <invocation>`. The sidecar's `assign` and `aliases` keep working; a file
filed in both places must agree, and a phrase claimed twice is a problem.

Why: GitHub's merge button does a plain text merge. It runs no custom merge
driver and, measured on 3 Oct 2026 with the merges API on scratch branches,
does not honour `merge=union` either: two branches each inserting one line at
the same point in docs/COMMANDS.md returned HTTP 409. Every new filing in the
sidecar appended to the tail of a JSON object, so any two such pull requests
conflicted there. Filed in its own file, a new command touches no line any
other pull request touches except its own rows here.

NO LINE HERE COUNTS ANYTHING

The page used to open with totals ("414 scripts") and the Gaps section with a
count. Every new command changed those lines, so every two pull requests that
each added one conflicted on them -- and with `merge=union` they would have
merged into a page with both counts on it. Every line is now a function of
one command or of nothing, sorted, so two additions at different points merge
as text into exactly what regenerating gives. Two additions that sort next to
each other in one table still conflict (the same insertion point): git says
so, and the page is never silently stale.

THE SIDECAR'S `assign` AND `aliases` ARE KEPT SORTED (crm#1798, second half)

Measured 3 Oct 2026 on two scratch branches off fsg-estimating-crm main, each
adding one script filed in the sidecar and merged with no driver and no
attributes, as GitHub merges: a hand-appended entry at the tail of `assign`
conflicted every time (both branches edit the same last line and its comma),
while the same two entries at their sorted places merged clean. A sidecar
that is not sorted has a second cost: `merge_commands_index.py` writes both
objects sorted, so the first local merge on any branch re-sorts the whole
object and that branch then carries reordering hunks that collide with other
pull requests' lines (crm#1905's last update moved six keys). So writing the
page also sorts those two objects in place -- the content is untouched, only
the order -- and `--check` fails while either is out of order. A lane that
appends its line at the tail and regenerates, as instructed, ends up with the
line at its sorted place. `groups` keeps its hand order: it is the page's
section order.

POSITIVE CONTROL

`--check` must be observed failing or it is not a check. `--selftest` proves it
on a copy in a temp dir, by injecting a subcommand that the sidecar cannot know
about, and reports the exit code.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

# The consuming repo's own paths. They are set by `configure()` from the thin
# wrapper's location (crm#1719 slice 3), never from this module's own, which
# lives in site-packages: every function below reads them at call time.
ROOT: Path = Path.cwd()
SCRIPT: Path = Path.cwd() / "scripts" / "gen_commands_index.py"
OUT: Path = ROOT / "docs" / "COMMANDS.md"
SIDECAR: Path = SCRIPT.parent / "commands_index.json"


def configure(script: str | Path) -> None:
    """Point this module at the repo whose wrapper script is `script`."""
    global ROOT, SCRIPT, OUT, SIDECAR
    SCRIPT = Path(script).resolve()
    ROOT = SCRIPT.parent.parent
    OUT = ROOT / "docs" / "COMMANDS.md"
    SIDECAR = SCRIPT.parent / "commands_index.json"

# Directories that hold something an operator or CI actually runs. `tools/` is
# here for fsg-common and fsg-bluebeam-steel-standards; a repo without one just
# yields nothing.
COMMAND_DIRS = ("scripts/", "tools/")

# Vendored copies of the shared package, test trees, and build droppings. These
# are not commands and never were.
SKIP_SEGMENTS = ("fsg_common", "__pycache__", "tests", "fsg_mto", "node_modules")

BANNER = "<!-- GENERATED by scripts/gen_commands_index.py -- do not edit by hand. -->"


# ---------------------------------------------------------------- reading files


def read_text(path: Path) -> str:
    """utf-8, then cp1252.

    Several scripts in fsg-estimating-crm are cp1252 and their em-dashes
    become U+FFFD under a plain utf-8 read -- which would then be committed
    into COMMANDS.md and re-diff on every machine that read them differently.
    """
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.splitlines()


def skipped(rel: str) -> bool:
    return any(seg in SKIP_SEGMENTS for seg in rel.split("/")[:-1])


# ------------------------------------------------------------ purpose extraction


def _strip_self_name(text: str, filename: str) -> str:
    """Drop a docstring's leading repeat of its own filename."""
    stem = filename.rsplit(".", 1)[0]
    for prefix in (filename, stem):
        if text.startswith(prefix):
            rest = text[len(prefix):]
            for sep in (" -- ", " - ", " --", ": ", " "):
                if rest.startswith(sep):
                    return rest[len(sep):].lstrip()
            if not rest:
                return ""
    return text


def first_line(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        line = line.strip()
        if line:
            return " ".join(line.split())
    return ""


def py_purpose(path: Path) -> str:
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return ""
    return _strip_self_name(first_line(ast.get_docstring(tree)), path.name)


def ps1_purpose(path: Path) -> str:
    """The `.SYNOPSIS` block, or -- failing that -- the leading `#` comment.

    Both conventions are in live use and neither is wrong: fsg-tender-review and
    fsg-bluebeam-steel-standards write `<# .SYNOPSIS ... #>`, while most of
    fsg-estimating-tools and all of `scripts/crm-import/` open with a plain `#`
    block. Reading only the first convention reported 23 real scripts in
    fsg-estimating-tools as having no purpose at all, which is exactly the
    silent, permissive wrong answer this index exists to stop producing.
    """
    text = read_text(path)
    at = text.lower().find(".synopsis")
    if at != -1:
        body: list[str] = []
        for line in text[at:].splitlines()[1:]:
            stripped = line.strip()
            if stripped.startswith(".") and len(stripped) > 1 and stripped[1].isupper():
                break
            if stripped.startswith("#>"):
                break
            if stripped:
                body.append(stripped)
            elif body:
                break
        return _strip_self_name(" ".join(body), path.name)

    # Leading `#` block: the first paragraph, minus an opening line that is
    # only the file's own name.
    paragraph: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<#") or (stripped and not stripped.startswith("#")):
            break
        if not stripped.startswith("#"):
            if paragraph:
                break
            continue
        content = stripped.lstrip("#").strip()
        if not content:
            if paragraph:
                break
            continue
        if not paragraph and content == path.name:
            continue
        paragraph.append(content)
    return _strip_self_name(" ".join(paragraph), path.name)


def purpose_of(path: Path) -> str:
    return py_purpose(path) if path.suffix == ".py" else ps1_purpose(path)


# ------------------------------------------------- filing in the command's file

MARKER = re.compile(r"^#\s*commands-index-(group|task):\s*(.*?)\s*$")


def comment_lines(path: Path) -> dict[int, str]:
    """{line number: comment text} for every line that is only a comment.

    `.py` is read with `tokenize`, so text inside a string -- a docstring that
    explains the marker syntax -- is never a comment. `.ps1` has no tokenizer
    here; a line whose first non-blank character is `#` is a comment.
    """
    text = read_text(path)
    lines = text.splitlines()
    found: dict[int, str] = {}
    if path.suffix != ".py":
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                found[number] = stripped
        return found
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return found
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        number = tok.start[0]
        if lines[number - 1].strip().startswith("#"):
            found[number] = tok.string.strip()
    return found


def parse_markers(comments: list[str]) -> dict:
    """{"groups": [...], "tasks": [(phrase, invocation or None), ...]}."""
    groups: list[str] = []
    tasks: list[tuple[str, str | None]] = []
    for comment in comments:
        match = MARKER.match(comment)
        if not match:
            continue
        kind, value = match.groups()
        if kind == "group":
            groups.append(value)
        else:
            phrase, _, run = value.partition("=>")
            tasks.append((" ".join(phrase.split()), run.strip() or None))
    return {"groups": groups, "tasks": tasks}


def block_above(comments: dict[int, str], line: int) -> list[str]:
    """The contiguous comment-only lines directly above `line`."""
    block: list[str] = []
    at = line - 1
    while at in comments:
        block.append(comments[at])
        at -= 1
    return list(reversed(block))


# ------------------------------------------------------------- AST: add_parser


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.Constant)]
        return "".join(parts) if parts else None
    return None


def add_parser_calls(path: Path) -> list[dict]:
    """Every `X.add_parser("name", help=...)`, by ast, in source order."""
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return []
    found: list[dict] = []
    comments = comment_lines(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_parser"):
            continue
        name = _const_str(node.args[0]) if node.args else None
        if not name:
            continue
        text = ""
        for kw in node.keywords:
            if kw.arg in ("help", "description"):
                value = _const_str(kw.value)
                if value:
                    text = " ".join(value.split())
                    if kw.arg == "help":
                        break
        found.append({
            "name": name, "help": text, "line": node.lineno,
            # The object the call is made ON, e.g. "subparsers" in
            # `subparsers.add_parser(...)` -- whatever it is actually
            # spelled as in THIS file, not assumed. `--selftest` reuses it
            # to inject a genuine new subcommand rather than guessing.
            "base": ast.unparse(func.value),
            # crm#1798: the comment block directly above the call files it.
            "own": parse_markers(block_above(comments, node.lineno)),
        })
    found.sort(key=lambda entry: entry["line"])
    return found


# ----------------------------------------------------------------- runnability


def _reports_at_import(node: ast.stmt) -> bool:
    """A module-level statement that PRODUCES OUTPUT, not one that sets up.

    `report_assert_sweep.py` has no `__main__` guard and no parser: it prints
    its entire report from the module body. `ollama_recognise.py` also has a
    module-level call -- `sys.path.insert(...)` -- and is a library, which is
    what CLAUDE.md says it is. "Any top-level call" cannot tell those apart and
    called the library a command, so the signal is narrowed to the small set
    that only a script does.
    """
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
        return False
    func = node.value.func
    if isinstance(func, ast.Name):
        return func.id in {"print", "main", "exit"}
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return (func.value.id, func.attr) in {("sys", "exit"), ("sys", "stdout")}
    return False


def is_runnable(path: Path) -> bool:
    """A command, or an importable helper that happens to sit in scripts/?

    Three positive signals, because this codebase uses all three:
      * `if __name__ == "__main__":`
      * an `argparse.ArgumentParser`
      * output produced at module level -- see `_reports_at_import`.

    A module-level ASSIGNMENT is deliberately not a signal.
    """
    if path.suffix == ".ps1":
        return True
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return True  # cannot prove it is a helper; show it rather than hide it
    for node in tree.body:
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name):
                if test.left.id == "__name__":
                    return True
        if _reports_at_import(node):
            return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "ArgumentParser":
            return True
        if isinstance(node, ast.Name) and node.id == "ArgumentParser":
            return True
    return False


# -------------------------------------------------------------- the enumeration


def discover(root: Path, package: str | None,
             cli_prefix: str | None = None) -> tuple[list[dict], list[dict]]:
    """(commands, helpers). Deterministic, sorted, tracked files only.

    `cli_prefix` is how this repo's docs are required to spell an invocation.
    fsg-bluebeam-steel-standards ships a launcher and its own offline suite
    FAILS a doc that writes `python -m fsg_mto` -- two of the three forms
    previously in use were silently dependent on which directory you stood in.
    So the prefix is a per-repo decision in the sidecar, not something this
    script gets to assume.
    """
    commands: list[dict] = []
    helpers: list[dict] = []
    files = tracked_files(root)

    for rel in sorted(files):
        if not rel.endswith(".py"):
            continue
        if rel.rsplit("/", 1)[-1] not in ("cli.py", "__main__.py"):
            continue
        path = root / rel
        if not path.exists():
            continue
        subs = add_parser_calls(path)
        if not subs:
            continue
        prefix = (cli_prefix or (f"python -m {package}" if package
                                 else f"python {rel}"))
        for sub in subs:
            commands.append({
                "key": sub["name"],
                "kind": "cli",
                "run": f"{prefix} {sub['name']}",
                "purpose": sub["help"],
                # The file, never the line -- see "THE CITATION IS A FILE,
                # NEVER A LINE" in this module's docstring (bluebeam#76). A
                # line number here is a drift generator that says nothing:
                # 26 of the 27 commits that ever touched tools/fsg_mto/cli.py
                # changed its line count, so every open PR would go stale on
                # a number unrelated to this index's own subject -- and the
                # shift lands on OTHER branches too, after their author has
                # pushed and can no longer regenerate. The row already
                # carries the anchor a reader needs (the subcommand name), so
                # `grep -n 'add_parser("resolve"' <file>` is one step.
                "source": rel,
                "subcommands": [],
                "own": sub["own"],
            })

    for rel in sorted(files):
        if not rel.startswith(COMMAND_DIRS):
            continue
        if not rel.endswith((".py", ".ps1")):
            continue
        if skipped(rel):
            continue
        path = root / rel
        if not path.exists():
            continue
        name = rel.rsplit("/", 1)[-1]
        if name == "__init__.py":
            continue
        entry = {
            "key": name,
            "kind": "script",
            "run": (f"python {rel}" if rel.endswith(".py")
                    else f"powershell -File {rel}"),
            "purpose": purpose_of(path),
            "source": rel,
            "subcommands": [],
            "own": parse_markers(list(comment_lines(path).values())),
        }
        if not is_runnable(path):
            helpers.append(entry)
            continue
        if rel.endswith(".py"):
            entry["subcommands"] = [
                {"name": s["name"], "help": s["help"]} for s in add_parser_calls(path)
            ]
        commands.append(entry)

    commands.sort(key=lambda e: (e["kind"] != "cli", e["key"]))
    helpers.sort(key=lambda e: e["key"])
    return commands, helpers


# ------------------------------------------------------------------- rendering


def load_sidecar() -> dict:
    if not SIDECAR.exists():
        return {"repo": ROOT.name, "package": None, "cli_prefix": None,
                "groups": [], "assign": {}, "aliases": {}}
    return json.loads(read_text(SIDECAR))


SORTED_SIDECAR_KEYS = ("assign", "aliases")


def sidecar_order_problems(side: dict) -> list[str]:
    """One problem per sidecar object in SORTED_SIDECAR_KEYS that is out of order."""
    problems: list[str] = []
    for name in SORTED_SIDECAR_KEYS:
        keys = list(side.get(name, {}))
        for before, after in zip(keys, keys[1:], strict=False):
            if after < before:
                problems.append(
                    f"`{name}` in scripts/commands_index.json is not sorted: "
                    f"{after!r} comes after {before!r}. Regenerate to sort it; an "
                    f"entry appended at the tail conflicts on GitHub with every "
                    f"other pull request that appends one.")
                break
    return problems


def sort_sidecar() -> bool:
    """Rewrite the sidecar with `assign` and `aliases` sorted. True if it changed.

    Same layout `merge_commands_index.py` writes (indent 2, ensure_ascii off,
    one trailing newline, LF), so a driver merge and a regenerate agree.
    """
    if not SIDECAR.exists():
        return False
    side = json.loads(read_text(SIDECAR))
    if not sidecar_order_problems(side):
        return False
    for name in SORTED_SIDECAR_KEYS:
        if isinstance(side.get(name), dict):
            side[name] = dict(sorted(side[name].items()))
    SIDECAR.write_text(json.dumps(side, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
    return True


def group_of(entry: dict, assign: dict) -> str | None:
    """Which task group this command is filed under.

    A script may be filed by its path (`scripts/tender_import/retry.py`) or by
    its bare filename (`retry.py`). Path wins, so two same-named scripts in
    different directories can be filed apart. Failing both, the command's own
    `# commands-index-group:` line files it (crm#1798); where the two
    disagree, `filing_problems` says so and `--check` fails.
    """
    side = assign.get(entry["source"]) or assign.get(entry["key"])
    if side:
        return side
    own = entry.get("own", {}).get("groups") or []
    return own[0] if own else None


def merged_aliases(commands: list[dict], side: dict) -> tuple[dict, list[str]]:
    """The sidecar's aliases plus every command's own task lines, and clashes."""
    aliases = dict(side.get("aliases", {}))
    claimed: dict[str, str] = {}
    problems: list[str] = []
    for entry in commands:
        for phrase, run in entry.get("own", {}).get("tasks", []):
            run = run or entry["run"]
            if not phrase:
                problems.append(f"empty task phrase in {entry['source']}")
                continue
            if phrase in aliases and aliases[phrase] != run:
                where = claimed.get(phrase, "scripts/commands_index.json")
                problems.append(
                    f"task phrase claimed twice: {phrase!r} -> `{aliases[phrase]}` "
                    f"({where}) and `{run}` ({entry['source']})")
                continue
            aliases[phrase] = run
            claimed.setdefault(phrase, entry["source"])
    return aliases, problems


def filing_problems(commands: list[dict], side: dict) -> list[str]:
    """A file filed in two groups, filed against the sidecar, or under no group."""
    assign = side.get("assign", {})
    known = {g["id"] for g in side.get("groups", [])}
    problems: list[str] = []
    for entry in commands:
        own = sorted(set(entry.get("own", {}).get("groups") or []))
        sidecar = assign.get(entry["source"]) or assign.get(entry["key"])
        label = f"`{entry['run']}` ({entry['source']})"
        if len(own) > 1:
            problems.append(f"{label} files itself in more than one group: {own}")
        if own and sidecar and sidecar not in own:
            problems.append(f"{label} is filed under {sidecar!r} in "
                            f"scripts/commands_index.json and {own[0]!r} in its own "
                            f"file. Keep one.")
        gid = group_of(entry, assign)
        if gid is not None and gid not in known:
            problems.append(f"{label} is filed under {gid!r}, which is not a group "
                            f"in scripts/commands_index.json")
    return problems


def ambiguous_keys(commands: list[dict], assign: dict) -> list[str]:
    """Bare filenames that name more than one command AND are filed by that name.

    Nothing in any of the five repos does this today. It is checked because the
    failure would be silent: two different tools would take one group and one
    person's filing decision, and the index would look complete.
    """
    seen: dict[str, list[str]] = {}
    for entry in commands:
        seen.setdefault(entry["key"], []).append(entry["source"])
    return sorted(
        key for key, sources in seen.items()
        if len(sources) > 1 and key in assign
    )


def cell(text: str) -> str:
    """One markdown table cell. Pipes and newlines would break the row."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render(commands: list[dict], helpers: list[dict], side: dict) -> str:
    groups = side.get("groups", [])
    assign = side.get("assign", {})
    aliases = side.get("aliases", {})
    order = [g["id"] for g in groups]
    by_id = {g["id"]: g for g in groups}

    buckets: dict[str, list[dict]] = {gid: [] for gid in order}
    unfiled: list[dict] = []
    for entry in commands:
        gid = group_of(entry, assign)
        if gid in buckets:
            buckets[gid].append(entry)
        else:
            unfiled.append(entry)

    out: list[str] = []
    add = out.append
    add(f"# Commands -- {side.get('repo', ROOT.name)}")
    add("")
    add(BANNER)
    add("")
    add("**The second axis.** CLAUDE.md and `docs/README.md` are organised by")
    add("*rationale* -- every rule beside what catches you if you break it. That is")
    add("load-bearing and this file does not replace or shrink any of it. This is the")
    add("axis they do not have: **what am I trying to do, and what do I run?**")
    add("")
    add("Look here when you know the task and not the tool's name. Every description")
    add("below is the tool's own docstring or `help=` string, quoted verbatim -- if one")
    add("reads badly, fix it at the source and regenerate.")
    add("")
    # crm#1798: no line on this page counts anything. A total changes with
    # every new command, so two pull requests that each add one always
    # collided on it, and GitHub's merge button cannot resolve that.
    add("Generated from the tracked tree. Every row is one command and no line")
    add("counts anything, so two pull requests that each add a command edit")
    add("different lines and GitHub merges them cleanly.")
    add("")
    add("**To file a new command**, put its group (an `id` from")
    add("`scripts/commands_index.json`) and any task phrases in the command's own")
    add("file, as comments, rather than in the sidecar:")
    add("")
    add("```")
    add("# commands-index-group: <group-id>")
    add("# commands-index-task: <what someone is trying to do>")
    add("```")
    add("")
    add("```")
    add("python scripts/gen_commands_index.py           # regenerate")
    add("python scripts/gen_commands_index.py --check   # exit 1 if this file is stale")
    add("```")
    add("")

    if aliases:
        add("## Find it by task")
        add("")
        add("Phrases a session actually searches for, mapped to the thing that does it.")
        add("Curated in `scripts/commands_index.json`; add a line whenever you go")
        add("looking for something and the word you tried was not here.")
        add("")
        add("| If you are trying to... | Run |")
        add("| --- | --- |")
        for phrase in sorted(aliases):
            add(f"| {cell(phrase)} | `{cell(aliases[phrase])}` |")
        add("")

    for gid in order:
        entries = buckets[gid]
        if not entries:
            continue
        group = by_id[gid]
        add(f"## {group['title']}")
        add("")
        if group.get("blurb"):
            add(group["blurb"])
            add("")
        add("| Run | What it does | Defined in |")
        add("| --- | --- | --- |")
        for entry in entries:
            purpose = entry["purpose"] or "_(no docstring -- see the file)_"
            add(f"| `{cell(entry['run'])}` | {cell(purpose)} | `{entry['source']}` |")
            for sub in entry["subcommands"]:
                sub_purpose = sub["help"] or "_(no help= -- see the file)_"
                add(f"| &nbsp;&nbsp;`{cell(entry['run'])} {cell(sub['name'])}` "
                    f"| {cell(sub_purpose)} | |")
        add("")

    if unfiled:
        add("## Unfiled")
        add("")
        add("**These have no task group yet, and `--check` is failing because of it.**")
        add("File each one in `scripts/commands_index.json` under `assign`. A tool")
        add("nobody will name a task for is the exact tool nobody will ever find.")
        add("")
        add("| Run | What it does | Defined in |")
        add("| --- | --- | --- |")
        for entry in unfiled:
            purpose = entry["purpose"] or "_(no docstring -- see the file)_"
            add(f"| `{cell(entry['run'])}` | {cell(purpose)} | `{entry['source']}` |")
            for sub in entry["subcommands"]:
                sub_purpose = sub["help"] or "_(no help= -- see the file)_"
                add(f"| &nbsp;&nbsp;`{cell(entry['run'])} {cell(sub['name'])}` "
                    f"| {cell(sub_purpose)} | |")
        add("")

    if helpers:
        add("## Not commands -- importable helpers")
        add("")
        add("These sit in a command directory but are libraries: no `__main__` guard,")
        add("no argument parser, no work at import. Listed so that nothing in the tree")
        add("is invisible, not because you run them.")
        add("")
        add("| File | What it is |")
        add("| --- | --- |")
        for entry in helpers:
            purpose = entry["purpose"] or "_(no docstring -- see the file)_"
            add(f"| `{entry['source']}` | {cell(purpose)} |")
        add("")

    gaps = [e for e in commands + helpers if not e["purpose"]]
    add("## Gaps")
    add("")
    if gaps:
        add("These carry no docstring or `.SYNOPSIS`, so this index cannot say what")
        add("they do. Nothing is invented in")
        add("their place. One sentence at the top of each file fixes it permanently:")
        add("")
        for entry in gaps:
            add(f"- `{entry['source']}`")
    else:
        add("Every command and helper states its own purpose. Nothing was invented.")
    add("")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------ main


def build() -> tuple[str, list[dict], list[str]]:
    return _build()[:3]


def _build() -> tuple[str, list[dict], list[str], list[str]]:
    """(page, unfiled, ambiguous, filing problems no rendered row would show)."""
    side = load_sidecar()
    assign = side.get("assign", {})
    commands, helpers = discover(ROOT, side.get("package"),
                                 side.get("cli_prefix"))
    known = {g["id"] for g in side.get("groups", [])}
    unfiled = [c for c in commands if group_of(c, assign) not in known]
    aliases, alias_problems = merged_aliases(commands, side)
    text = render(commands, helpers, {**side, "aliases": aliases})
    problems = (sidecar_order_problems(side) + filing_problems(commands, side)
                + alias_problems)
    return text, unfiled, ambiguous_keys(commands, assign), problems


_ROW = re.compile(r"^\| (`[^`]+`) \|")


def _runs(doc: str) -> set[str]:
    """The commands a rendered index lists, read back out of its own tables."""
    return {m.group(1) for line in doc.split("\n") if (m := _ROW.match(line))}


def stale_report(have: str, want: str) -> list[str]:
    """Say what actually differs, rather than asserting one cause for all of them.

    The message this replaces read "the code has commands this file does not"
    on ANY textual difference, because the check behind it was whole-document
    equality. That is wrong whenever the command set is unchanged and only a
    docstring, a `help=` string or -- until bluebeam#76 -- a line-number
    citation moved: a gate that names a cause it never checked teaches its
    reader to stop believing it.

    So the sets are compared, and the answer is reported, not assumed.
    """
    here, there = _runs(have), _runs(want)
    out: list[str] = []
    rel = OUT.relative_to(ROOT).as_posix()
    for run in sorted(there - here):
        out.append(f"{rel} is missing a command the code has: {run}")
    for run in sorted(here - there):
        out.append(f"{rel} lists a command the code does not have: {run}")
    if out:
        return out
    # Same commands, different text: a docstring, a `help=` string or a
    # heading changed. Name it as that, and show the first difference so the
    # reader can see which without running a diff of their own.
    # strict=False on purpose: the two documents genuinely differ in length
    # when a row is added or removed, and this branch only ever runs when the
    # command sets already matched, so the common prefix is what is of interest.
    changed = [(a, b) for a, b in
               zip(have.split("\n"), want.split("\n"), strict=False) if a != b]
    detail = (f"; first of {len(changed)}:\n      - {changed[0][0][:120]}"
              f"\n      + {changed[0][1][:120]}") if changed else ""
    return [f"{rel} is stale, but the command list is unchanged -- a "
            f"description or heading moved{detail}"]


def selftest() -> int:
    """Prove --check fails. A check never seen failing is not a check."""
    tmp = Path(tempfile.mkdtemp(prefix="commands-index-selftest-"))
    try:
        work = tmp / ROOT.name
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--depth", "1",
                        str(ROOT), str(work)], check=True, capture_output=True)
        shutil.copy2(SCRIPT, work / "scripts" / SCRIPT.name)
        if SIDECAR.exists():
            shutil.copy2(SIDECAR, work / "scripts" / SIDECAR.name)
        gen = work / "scripts" / SCRIPT.name

        first = subprocess.run([sys.executable, str(gen)], capture_output=True, text=True)
        print(f"  [1] generate in the clone            exit={first.returncode}")
        base = subprocess.run([sys.executable, str(gen), "--check"],
                              capture_output=True, text=True)
        print(f"  [2] --check on a clean clone         exit={base.returncode}"
              f"  (expected 0)")
        if base.returncode != 0:
            print("      CONTROL FAILED: a clean tree must pass, or a later")
            print("      failure proves nothing. Output:")
            print("      " + base.stdout.strip().replace("\n", "\n      "))
            return 1

        # Inject a subcommand no sidecar can know about.
        target = None
        for rel in tracked_files(work):
            if rel.endswith("cli.py") and add_parser_calls(work / rel):
                target = work / rel
                break
        if target is None:
            print("      no cli.py in this repo -- injecting a script instead")
            target = work / "scripts" / "zz_selftest_injected_command.py"
            target.write_text('"""Injected by --selftest. Not a real command."""\n'
                              'if __name__ == "__main__":\n    pass\n',
                              encoding="utf-8")
            subprocess.run(["git", "-C", str(work), "add", "-f", str(target)],
                           check=True, capture_output=True)
            what = "a new script"
        else:
            text = read_text(target)
            calls = add_parser_calls(target)
            anchor = f'add_parser("{calls[0]["name"]}"'
            at = text.index(anchor)
            line_start = text.rindex("\n", 0, at) + 1
            prefix = text[line_start:at]
            indent = prefix[:len(prefix) - len(prefix.lstrip())]
            # A bare expression statement calling .add_parser() again on the
            # SAME action object -- no assignment needed, and no assumption
            # about what that object is called. `calls[0]["base"]` is read
            # from the AST of THIS file's own first call, never hard-coded:
            # this repo spells it `subparsers`, not `sub`, and a literal
            # `sub.add_parser(...)` here raised a SyntaxError (an undefined
            # name on the LHS of `subparsers. = ...`) that --check duly
            # caught -- but by losing every command in the file to a parse
            # failure, not by noticing the one that was actually added.
            inject = (f'{indent}{calls[0]["base"]}.add_parser('
                      f'"zz-selftest-injected", help="injected by --selftest")\n')
            target.write_text(text[:line_start] + inject + text[line_start:],
                              encoding="utf-8")
            what = "a new subcommand `zz-selftest-injected`"

        after = subprocess.run([sys.executable, str(gen), "--check"],
                               capture_output=True, text=True)
        print(f"  [3] --check after adding {what}")
        print(f"      exit={after.returncode}  (expected non-zero)")
        for line in after.stdout.strip().splitlines()[:6]:
            print(f"      {line}")
        if after.returncode == 0:
            print("      SELFTEST FAILED: --check did not notice.")
            return 1
        print("  PASS: --check is observed both passing and failing.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None, script: str | Path | None = None) -> int:
    if script is not None:
        configure(script)
    ap = argparse.ArgumentParser(description="Generate docs/COMMANDS.md")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if docs/COMMANDS.md is stale or a tool is unfiled")
    ap.add_argument("--stdout", action="store_true", help="print, write nothing")
    ap.add_argument("--selftest", action="store_true",
                    help="prove --check fails when it should, and report the exit code")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    resorted = False
    if not args.check and not args.stdout:
        resorted = sort_sidecar()
    text, unfiled, ambiguous, filing = _build()

    if args.stdout:
        sys.stdout.write(text)
        return 0

    if args.check:
        problems: list[str] = []
        if not OUT.exists():
            problems.append(f"{OUT.relative_to(ROOT).as_posix()} does not exist")
        else:
            have = read_text(OUT).replace("\r\n", "\n")
            if have != text:
                problems.extend(stale_report(have, text))
        for entry in unfiled:
            problems.append(
                f"unfiled: `{entry['run']}` ({entry['source']}) has no task group")
        problems.extend(filing)
        for key in ambiguous:
            problems.append(
                f"ambiguous: `{key}` names more than one command but is filed "
                f"once, by bare name. File each by its path instead.")
        if not problems:
            print(f"{OUT.relative_to(ROOT).as_posix()} matches the code.")
            return 0
        print(f"{len(problems)} problem(s):\n")
        for problem in problems:
            print(f"  {problem}")
        print("\n  Regenerate:  python scripts/gen_commands_index.py")
        print("  File a new command with a `# commands-index-group: <id>` comment in")
        print("  its own file, or under `assign` in scripts/commands_index.json.")
        # The case that wastes an hour, because it is invisible in the diff.
        print(
            "\n  IF THIS IS RED IN CI BUT GREEN ON YOUR MACHINE, you are not\n"
            "  going mad and your branch is not wrong. CI checks the MERGE with\n"
            "  `main`, not your branch head. When a script lands on `main` after\n"
            "  you last rebased, the merge holds THAT script beside YOUR older\n"
            "  docs/COMMANDS.md, and this check correctly calls it stale --\n"
            "  against a combination that exists nowhere in either branch.\n"
            "  Nothing in your diff shows it. The fix is:\n"
            "      git fetch origin && git rebase origin/main\n"
            "      python scripts/gen_commands_index.py\n"
            "  It is a standing tax on having a PR open, and it recurs every\n"
            "  time a script lands on `main` while yours is still open.")
        return 1

    # LF on write; `--check` compares newline-insensitively. All five repos set
    # `core.autocrlf=true`, so a checkout can hand this file back with CRLF and
    # a byte comparison would then call an up-to-date index stale on Windows
    # and fresh on Linux -- the same host-dependent, silently-wrong answer
    # ADR 14 is about.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({len(text.splitlines())} lines)")
    if resorted:
        print(f"  sorted `assign` and `aliases` in {SIDECAR.name} (order only)")
    if unfiled:
        print(f"  {len(unfiled)} command(s) UNFILED -- --check will fail until each")
        print("  is given a task group in scripts/commands_index.json:")
        for entry in unfiled[:20]:
            print(f"    {entry['key']}")
        if len(unfiled) > 20:
            print(f"    ... and {len(unfiled) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
