"""Every test stub of a gate cites the real-gate test that refuses.

A stub (a `mock.patch`, a `monkeypatch.setattr`, a swapped `run_gh`, the
`Harness` fake) that stands in for a gate hides the real gate from the suite.
fsg-tender-review#870 shipped a routine its live gate refused on every RFQ
while every test passed, because the stub answered clear. So each stub carries,
within the three lines above it, one of:

    # real-gate test: <test function name>   (a test in tests/ that runs the real gate)
    # not-a-gate: <reason>                   (a path, a clock, transport, an input)

The guard fails on an uncited stub, on a citation to a test that does not
exist, and on a scan that finds fewer sites than it should (an empty scan
would pass). `test_real_gates.py` and this file are skipped: they hold the
real gates, faking only transport.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKIP = {"test_real_gates.py", "test_gate_stub_citations.py"}
STUB = re.compile(r"mock\.patch|monkeypatch\.setattr|\brun_gh\s*=|^\s*class Harness\b")
CITE = re.compile(r"#\s*(real-gate test:\s*(\w+)|not-a-gate:\s*\S)")
MIN_SITES = 8


def _test_names() -> set[str]:
    names: set[str] = set()
    for p in TESTS.glob("test_*.py"):
        names |= set(re.findall(r"^\s*def (test_\w+)", p.read_text(encoding="utf-8"), re.M))
    return names


def scan(sources: dict[str, str], names: set[str]) -> tuple[int, list[str]]:
    """(sites found, problems) over {file name: text}."""
    sites, problems = 0, []
    for name, text in sources.items():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not STUB.search(line) or line.lstrip().startswith("#"):
                continue
            sites += 1
            window = lines[max(0, i - 3):i + 1]
            hits = [CITE.search(w) for w in window]
            hits = [h for h in hits if h]
            if not hits:
                problems.append(f"{name}:{i + 1}: stub with no citation: {line.strip()}")
                continue
            for h in hits:
                if h.group(2) and h.group(2) not in names:
                    problems.append(f"{name}:{i + 1}: cites missing test {h.group(2)}")
    return sites, problems


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8")
            for p in sorted(TESTS.glob("test_*.py")) if p.name not in SKIP}


def test_every_stub_cites_a_real_gate_test_or_says_why_not():
    sites, problems = scan(_sources(), _test_names())
    assert sites >= MIN_SITES, f"scan found only {sites} stub sites; the scan is broken"
    assert not problems, "\n".join(problems)


def test_the_guard_fails_on_an_uncited_stub():
    sites, problems = scan({"x.py": "def t():\n    mock.patch.object(a, 'b')\n"}, set())
    assert sites == 1 and "no citation" in problems[0]


def test_the_guard_fails_on_a_citation_to_a_missing_test():
    src = "# real-gate test: test_gone\nmonkeypatch.setattr(a, 'b', 1)\n"
    assert "missing test" in scan({"x.py": src}, {"test_here"})[1][0]


def test_the_guard_passes_a_cited_stub_and_a_not_a_gate():
    src = ("# real-gate test: test_here\nmonkeypatch.setattr(a, 'b', 1)\n"
           "# not-a-gate: a path\nmonkeypatch.setattr(a, 'c', 1)\n")
    assert scan({"x.py": src}, {"test_here"}) == (2, [])
