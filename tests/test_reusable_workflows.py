"""crm#2815 item 4: the reusable workflows keep their contract (text checks, no YAML library)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
NAMES = ["reusable-pr-body.yml", "reusable-leak-guard.yml", "reusable-commands-index.yml"]


def body(name: str) -> str:
    return (WF / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", NAMES)
def test_is_callable_with_a_required_runner_and_no_default(name):
    t = body(name)
    assert re.search(r"^on:\n  workflow_call:", t, re.M)
    block = re.search(r"^      runs-on:\n(?P<b>(?:        .*\n)+)", t, re.M)
    assert block, "runs-on input missing"
    assert "required: true" in block["b"]
    assert "default:" not in block["b"]
    assert "runs-on: ${{ inputs.runs-on }}" in t


@pytest.mark.parametrize("name", NAMES)
def test_actions_are_pinned_to_a_commit(name):
    for ref in re.findall(r"uses:\s+(\S+)", body(name)):
        if ref.startswith("actions/"):
            assert re.search(r"@[0-9a-f]{40}$", ref), ref


@pytest.mark.parametrize("name", NAMES)
def test_no_input_is_interpolated_into_a_shell_line(name):
    """Inputs reach the shell through env, never inside run: text (script injection)."""
    for run in re.findall(r"run:\s*[|>]?\n?((?:\s{10,}.*\n?)+)", body(name)):
        assert "${{" not in run.replace("${{ github.event.pull_request.number }}", "").replace(
            "${{ github.repository }}", ""), run


def test_pr_body_needs_a_version_and_leak_guard_does_not_echo_terms():
    assert "fsg-common-ref:" in body("reusable-pr-body.yml")
    assert re.search(r"fsg-common-ref:\n(?:        .*\n)*        required: true",
                     body("reusable-pr-body.yml"))
    t = body("reusable-leak-guard.yml")
    assert "echo " not in t and "FSG_LEAK_TERMS_TEXT: ${{ secrets.FSG_LEAK_TERMS }}" in t
