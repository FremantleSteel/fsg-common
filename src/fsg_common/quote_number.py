"""One quote-number parser for every FSG repo (crm#2814 slice 1).

A quote number is the join key between the CRM, the quote register and the
data built from them. Before this module each repo parsed it its own way.
This is the one reading; the repos move to it one at a time (later slices).

Two series:

    FSG   FSG-<yy>Q-<nnn>     e.g. FSG-99Q-042, revision FSG-99Q-042-A
    PB    PB<yy>-<nnn>        e.g. PB99-042,    revision PB99-042-A

What it reads:

- The prefix in any case. ``FSF`` (any case) reads as FSG: the register
  spells it that way in many rows.
- A number of 1 to 3 digits, leading zeros or not. Output pads to 3.
- A revision after ``-``, ``/`` or one space, in either case. Output always
  writes ``-`` (the owner's decision of 1 Oct 2026).
- A revision glued to the number (``FSG-99Q-042A``) only when the caller
  passes ``glued_revision=True``, which is for file names. Anywhere else a
  glued letter cannot be told from a typo, so it refuses.

What it refuses, each with the reason in ``NotAQuoteNumber.reason``:

- No value, blank, or not text.
- Anything that is not a whole quote number. This matches the whole value;
  it does not search inside a sentence.
- A number of zero, or of 4 or more digits. Whether an older 4-digit number
  is a quote is open question 1 on crm#2814; the mint stops at 999.
- A revision of digits, or of 2 or more letters. Both are open question 2 on
  crm#2814. One letter is the mint's spelling.

The open questions refuse rather than guess. When the owner answers, the
answer changes the rule here and its test, in one place.

It never raises and never hands back the input as though it had parsed. A
refusal is falsy and has no ``number``, so ``if parsed:`` cannot read a
refusal as a quote.

Standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Series = Literal["FSG", "PB"]

_FSG_PREFIXES = ("FSG", "FSF")
_REVISION_SEPARATORS = ("-", "/", " ")
_MAX_NUMBER_DIGITS = 3
_MAX_REVISION_LETTERS = 1
_ASCII_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_DIGITS = "0123456789"


@dataclass(frozen=True)
class QuoteNumber:
    """A parsed quote number. ``revision`` None is the first issue, not revision 0."""

    series: Series
    year: int
    number: int
    revision: str | None
    raw: str

    def base(self) -> str:
        """The number without its revision, e.g. ``FSG-99Q-042``."""
        return format_quote_number(self.series, self.year, self.number)

    def full(self) -> str:
        """The number with its revision, if any, e.g. ``FSG-99Q-042-A``."""
        return format_quote_number(self.series, self.year, self.number, self.revision)

    def __bool__(self) -> bool:
        return True


@dataclass(frozen=True)
class NotAQuoteNumber:
    """The input could not be read as a quote number, and why."""

    raw: object
    reason: str

    def __bool__(self) -> bool:
        return False


def _digits(text: str) -> str:
    n = 0
    while n < len(text) and text[n] in _ASCII_DIGITS:
        n += 1
    return text[:n]


def parse_quote_number(
    raw: object, *, glued_revision: bool = False
) -> QuoteNumber | NotAQuoteNumber:
    """Read ``raw`` as one quote number, or say why it is not one. Never raises."""

    def refuse(reason: str) -> NotAQuoteNumber:
        return NotAQuoteNumber(raw=raw, reason=reason)

    if raw is None:
        return refuse("empty: no value to read")
    if not isinstance(raw, str):
        return refuse(f"not text: got {type(raw).__name__}")
    text = raw.strip()
    if not text:
        return refuse("empty: the value is blank")
    if not text.isascii():
        return refuse("holds characters outside plain ASCII")
    upper = text.upper()

    if upper.startswith("PB"):
        series: Series = "PB"
        rest = upper[2:]
        year_text = rest[:2]
        if len(year_text) != 2 or _digits(year_text) != year_text:
            return refuse("PB number: no two-digit year after PB")
        rest = rest[2:]
        if not rest.startswith("-"):
            return refuse("PB number: no hyphen after the year (PB<yy>-<n>)")
        rest = rest[1:]
    elif upper[:3] in _FSG_PREFIXES:
        series = "FSG"
        rest = upper[3:]
        if not rest.startswith("-"):
            return refuse("prefix is not followed by a hyphen")
        rest = rest[1:]
        year_text = _digits(rest)
        if len(year_text) != 2:
            return refuse(f"year is not two digits (read {year_text!r})")
        rest = rest[2:]
        if not rest.startswith("Q"):
            return refuse("no Q after the year")
        rest = rest[1:]
        if not rest.startswith("-"):
            return refuse("no hyphen after the Q")
        rest = rest[1:]
    else:
        return refuse("no FSG, FSF or PB prefix at the start")

    number_text = _digits(rest)
    if not number_text:
        return refuse("no number after the year")
    if len(number_text) > _MAX_NUMBER_DIGITS:
        return refuse(
            f"number has {len(number_text)} digits; the mint stops at 999 and whether a "
            "longer number is a quote is an open question (crm#2814 question 1)"
        )
    number = int(number_text)
    if number == 0:
        return refuse("number is zero")
    tail = rest[len(number_text):]

    revision: str | None = None
    if tail:
        if tail[0] in _REVISION_SEPARATORS:
            revision = tail[1:]
        elif tail[0] in _ASCII_LETTERS and glued_revision:
            revision = tail
        elif tail[0] in _ASCII_LETTERS:
            return refuse(
                "a letter is glued to the number; a revision needs '-', '/' or a space "
                "before it (file names: pass glued_revision=True)"
            )
        else:
            return refuse(f"unexpected text after the number: {tail!r}")
        reason = _revision_problem(revision)
        if reason:
            return refuse(reason)

    return QuoteNumber(
        series=series, year=2000 + int(year_text), number=number, revision=revision, raw=raw
    )


def _revision_problem(revision: str) -> str | None:
    if not revision:
        return "a revision separator with no revision after it"
    if all(c in _ASCII_DIGITS for c in revision):
        return (
            "revision is digits; whether a revision may be digits is an open question "
            "(crm#2814 question 2)"
        )
    if not all(c in _ASCII_LETTERS for c in revision):
        return f"revision {revision!r} is not a letter"
    if len(revision) > _MAX_REVISION_LETTERS:
        return (
            f"revision has {len(revision)} letters; more than one letter is an open "
            "question (crm#2814 question 2)"
        )
    return None


def format_quote_number(
    series: str, year: int, number: int, revision: str | None = None
) -> str:
    """Write a quote number the canonical way. Raises ValueError on what the parser refuses."""
    if series not in ("FSG", "PB"):
        raise ValueError(f"series must be FSG or PB, not {series!r}")
    if type(year) is not int or not 2000 <= year <= 2099:
        raise ValueError(f"year must be a whole year from 2000 to 2099, not {year!r}")
    if type(number) is not int or not 1 <= number <= 10**_MAX_NUMBER_DIGITS - 1:
        raise ValueError(f"number must be 1 to 999, not {number!r}")
    yy = f"{year % 100:02d}"
    text = f"FSG-{yy}Q-{number:03d}" if series == "FSG" else f"PB{yy}-{number:03d}"
    if revision is None:
        return text
    if not isinstance(revision, str):
        raise ValueError(f"revision must be text or None, not {revision!r}")
    revision = revision.upper()
    reason = _revision_problem(revision)
    if reason:
        raise ValueError(reason)
    return f"{text}-{revision}"
