"""The one quote-number parser (crm#2814 slice 1).

Every number here is invented: year 99 cannot occur, so none is a live quote.
Each spelling the repos meet has a test, with the neighbour beside it: the
case that must still parse and the case that must refuse.
"""
from __future__ import annotations

import pytest

from fsg_common.quote_number import (
    NotAQuoteNumber,
    QuoteNumber,
    format_quote_number,
    parse_quote_number,
)


def _ok(raw, **kw) -> QuoteNumber:
    got = parse_quote_number(raw, **kw)
    assert isinstance(got, QuoteNumber), f"{raw!r} refused: {getattr(got, 'reason', got)}"
    return got


def _refused(raw, **kw) -> NotAQuoteNumber:
    got = parse_quote_number(raw, **kw)
    assert isinstance(got, NotAQuoteNumber), f"{raw!r} parsed as {got!r}"
    assert got.reason, "a refusal must carry its reason"
    return got


# --- Controls: valid numbers still parse -------------------------------------


def test_canonical_fsg_number_parses():
    q = _ok("FSG-99Q-901")
    assert (q.series, q.year, q.number, q.revision) == ("FSG", 2099, 901, None)
    assert q.base() == "FSG-99Q-901"
    assert q.full() == "FSG-99Q-901"
    assert q.raw == "FSG-99Q-901"


@pytest.mark.parametrize("raw", ["FSF-99Q-901", "FSf-99Q-901", "fsg-99q-901", "fsf-99q-901"])
def test_register_prefix_spellings_read_as_fsg(raw):
    q = _ok(raw)
    assert q.series == "FSG"
    assert q.base() == "FSG-99Q-901"
    assert q.raw == raw


@pytest.mark.parametrize(
    "raw", ["FSG-99Q-901-A", "FSG-99Q-901/A", "FSG-99Q-901 A", "FSG-99Q-901/a", "FSF-99Q-901/A"]
)
def test_revision_separators_all_read(raw):
    q = _ok(raw)
    assert q.revision == "A"
    assert q.base() == "FSG-99Q-901"
    assert q.full() == "FSG-99Q-901-A"


def test_two_letter_revision_refuses_pending_the_owner():
    # Open question 2 on crm#2814: up to how many letters? One is the mint's
    # spelling; more waits for the answer, so it refuses rather than guesses.
    r = _refused("FSG-99Q-901-AB")
    assert "2 letters" in r.reason
    assert "open question" in r.reason


def test_short_number_is_padded_to_three():
    q = _ok("FSG-99Q-9")
    assert q.number == 9
    assert q.base() == "FSG-99Q-009"


def test_leading_zeros_do_not_change_the_number():
    assert _ok("FSG-99Q-009").number == _ok("FSG-99Q-9").number == 9


def test_surrounding_whitespace_is_ignored_but_kept_in_raw():
    q = _ok("  FSG-99Q-901 \n")
    assert q.base() == "FSG-99Q-901"
    assert q.raw == "  FSG-99Q-901 \n"


def test_pb_series_parses():
    q = _ok("PB99-901")
    assert (q.series, q.year, q.number, q.revision) == ("PB", 2099, 901, None)
    assert q.base() == "PB99-901"
    assert _ok("pb99-901-b").full() == "PB99-901-B"
    assert _ok("PB99-901/B").revision == "B"


def test_glued_revision_reads_only_when_asked():
    # A file name writes FSG-99Q-901A. Outside file names a glued letter
    # cannot be told from a typo, so it refuses unless the caller asks.
    _refused("FSG-99Q-901A")
    assert _ok("FSG-99Q-901A", glued_revision=True).full() == "FSG-99Q-901-A"
    assert _ok("PB99-901B", glued_revision=True).revision == "B"
    # The control: glued_revision does not invent a revision.
    assert _ok("FSG-99Q-901", glued_revision=True).revision is None


# --- An absent or malformed input refuses, with a reason ---------------------


@pytest.mark.parametrize("raw", [None, "", "   ", "\n"])
def test_absent_input_refuses(raw):
    r = _refused(raw)
    assert "empty" in r.reason or "no value" in r.reason


@pytest.mark.parametrize("raw", [901, 99.901, b"FSG-99Q-901", ["FSG-99Q-901"]])
def test_non_text_refuses(raw):
    assert "not text" in _refused(raw).reason


@pytest.mark.parametrize(
    "raw, words",
    [
        ("XYZ-99Q-901", "prefix"),
        ("99Q-901", "prefix"),  # a bare number needs a caller that knows the series
        ("FSG-99-901", "Q"),
        ("FSG-9Q-901", "year"),
        ("FSG-99Q-", "number"),
        ("FSG-99Q-ABC", "number"),
        ("FSG-99Q-901-ABC", "revision"),
        ("FSG-99Q-901-", "revision"),
        ("FSG-99Q-901 extra words", "revision"),
        ("PB-99-901", "PB"),
        ("PB99901", "PB"),
        ("See FSG-99Q-901 attached", "prefix"),  # match, not search
    ],
)
def test_malformed_number_refuses_with_its_reason(raw, words):
    r = _refused(raw)
    assert words.lower() in r.reason.lower(), r.reason
    assert r.raw == raw


def test_number_zero_refuses():
    assert "zero" in _refused("FSG-99Q-000").reason


def test_four_digit_number_refuses_pending_the_owner():
    # Open question 1 on crm#2814: allow 4 digits, or exactly up to 999?
    # Until it is answered a 4-digit number is not read as a quote.
    r = _refused("FSG-99Q-1000")
    assert "4 digits" in r.reason
    assert "open question" in r.reason


def test_digit_revision_refuses_pending_the_owner():
    # Open question 2 on crm#2814: may a revision be digits?
    r = _refused("FSG-99Q-901-1")
    assert "digits" in r.reason
    assert "open question" in r.reason


def test_refusal_is_never_truthy_and_carries_no_number():
    r = _refused("FSG-99Q-ABC")
    assert not r
    assert not hasattr(r, "number")
    assert bool(_ok("FSG-99Q-901"))


def test_parser_never_raises_on_odd_input():
    for raw in [object(), "\x00", "FSG-99Q-901" * 50, "ＦSG-99Q-901", "FSG-99Q-٩٠١"]:
        assert isinstance(parse_quote_number(raw), NotAQuoteNumber)


# --- format_quote_number -----------------------------------------------------


def test_format_round_trips_through_the_parser():
    for args in [("FSG", 2099, 901, None), ("FSG", 2099, 9, "A"), ("PB", 2099, 42, "B")]:
        text = format_quote_number(*args)
        q = _ok(text)
        assert (q.series, q.year, q.number, q.revision) == args
        assert q.full() == text


def test_format_spellings():
    assert format_quote_number("FSG", 2099, 9) == "FSG-99Q-009"
    assert format_quote_number("FSG", 2099, 901, "a") == "FSG-99Q-901-A"
    assert format_quote_number("PB", 2099, 901, "B") == "PB99-901-B"


@pytest.mark.parametrize(
    "args",
    [
        ("FSF", 2099, 901, None),
        ("FSG", 1999, 901, None),
        ("FSG", 2099, 0, None),
        ("FSG", 2099, 1000, None),
        ("FSG", 2099, 901, "1"),
        ("FSG", 2099, 901, "AB"),
        ("FSG", 2099, 901, ""),
        ("FSG", None, 901, None),
        ("FSG", 2099, True, None),
    ],
)
def test_format_refuses_what_the_parser_would_refuse(args):
    with pytest.raises(ValueError):
        format_quote_number(*args)
