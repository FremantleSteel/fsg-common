"""Resolve a drawing's own section notation to FSG's canonical library.

## One resolver, two consumers

This module is the single copy. It replaces two hand-maintained twins that
were held together by a hook, a parity test and a baseline script:

- `fsg-tender-review/src/fsg_tender_review/resolve.py` (848 lines)
- `fsg-bluebeam-steel-standards/tools/fsg_mto/sections.py` (878 lines)

The body below is a near-verbatim copy of the first of those, which was
itself a near-verbatim port of the second. Nothing was rewritten in the
move: the port is nine exact-string edits, listed in `docs/port.md`, and
`diff` against the source shows those and nothing else. Every guard clause
here exists because a first version got a real number wrong -- `200 x 200 x
10 PL` resolving to `200PL` at 1570 kg/m2 instead of `10PL` at 78.5 (20x
over, labelled `canonical` so nothing flagged it); `C1 100 x 100 x 5 SHS`
resolving to `1SHS5`; `ALUMINIUM 100 x 50 x 3 RHS` priced as steel (2.9x
over). A reimplementation would rediscover those one at a time, on real
tenders.

## The one thing the two twins did not agree on -- ANSWERED 7 Sep 2026

They agreed on 834 of 835 notations when measured on 3 Sep 2026
(`tools/parity_report.py`). The exception was a CHS wall written one decimal
short -- `273 CHS 6.4` against the library's `273CHS6.35` -- which
tender-review called `canonical` and the Bluebeam toolkit called `nearest`.
Same section, same mass, different verdict, so it changed whether an
estimator was asked to look.

That was an open question for FSG's estimators
(Rostov-au/fsg-tender-review#184 item 1, "questions-for-estimators.md" Q25),
carried rather than settled by a `RoundingPolicy` each consumer could pick.
David, relaying the estimating team's answer, 7 Sep 2026: read `CHS 6.4` as
the metric 6.40 wall -- matches all 94 checkable archive lines, 0 closer to
the imperial 6.35 the library actually stores. Both resolvers now converge
on `canonical`, the tender-review reading.

**That 7 Sep fix converged the VERDICT, not the MASS, and the two are not
the same thing -- found and corrected 18 Sep 2026.** `_is_rounding`'s
one-decimal clause is what made `273 CHS 6.4` read `canonical` in both
resolvers, and a rounding clause returns the LIBRARY's own number: `273
CHS 6.4` kept coming back as `273CHS6.35` at 41.77 kg/m, the imperial mass,
just now agreed-on rather than disputed. A drawing writing `6.4` was still
priced at the 6.35 mass under a verdict that says "trust this." David,
18 Sep 2026, asked to confirm or correct that reading directly rather than
re-litigate it: **"Confirm metric, 6.40."** The two masses are not close
enough to treat as the same rounding -- 41.77 kg/m against a true 6.40mm
wall's ~42.1 kg/m at this OD (AS/NZS 1163 C350L0, InfraBuild "Know Your
Steel" V9, Jun 2023) is a 0.8% difference, the same order as the archive's
own measured 0.785% mean error against the imperial mass and 0.069% against
the metric one. `90_Lists` has never carried a metric-wall CHS row at any
OD, so this is a library GAP rather than a wrong entry, and
`_CHS_METRIC_6_4_OD_KG_PER_M` below is a resolver rule, not a hand-edit to
`data/fsg_sections.json` -- seeing "do not hand-edit the generated
library" for what an OD-keyed table like the STR-/LYS- one already is.
`_is_rounding`'s one-decimal clause still applies to every OTHER CHS wall
written one decimal short (7.1 for 7.11, 8.2 for 8.18) -- 6.4 is excluded
because it is now claimed by its own exact match, checked before
`_is_rounding` is ever reached. (The question's wider half -- whether
`90_Lists` should carry a metric CHS range of its own, rather than this
repo asserting individual walls -- is still undecided and is not what this
settles; fsg-tender-review#184's other questions stay open.)

## Report how, always

`(Section, how)` out, never a bare mass -- `exact` (the drawing already
wrote the library's own ID), `canonical` (rewritten into library form, or a
rounding of the library's own AS/NZS mass), `nearest` (closest same-depth
section; needs an estimator's eye), `cold-formed-bare-lysaght` (a bare purlin
code read as its `LYS-` row -- estimators, 30 Sep 2026; exact or refused),
`cold-formed` (a real C/Z purlin code
`90_Lists` does not carry -- a library gap, not a misread), `unresolved`,
`material-mismatch` (aluminium/stainless/timber -- refuses rather than
pricing it as steel), `shape-modifier` (THREADED/HEX: a cross-section
90_Lists has no family for -- refuses rather than dropping the word and
pricing the plain shape), or `substitution` (an estimator's recorded
decision, never a resolver guess). A caller that hides *how* behind a bare
mass is the exact failure fsg-tender-review's "masses never come from you"
rule exists to prevent, just moved one step downstream.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable

from ._section import Section

__all__ = [
    "SectionLibrary", "ambiguous_candidates", "canonical_candidates",
    "cold_formed", "library", "loose_key", "mass_of", "resolve",
    "shape_modifier", "shape_modifier_candidates", "vendor_cold_formed",
    "COLD_FORMED", "COLD_FORMED_VENDORS", "HEAD_TOLERANCE", "NEAREST_MARGIN",
    "NEAREST_TOLERANCE",
]

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _trim(n: str) -> str:
    """'2.0' -> '2', '114.30' -> '114.3', '250' -> '250'."""
    if "." not in n:
        return n
    return n.rstrip("0").rstrip(".") or "0"


def loose_key(text: str) -> str:
    """Comparison key: uppercase, no separators, numbers trimmed.

    Makes '25SHS2.0', '25 SHS 2' and '25shs2.00' collide, so a candidate built
    from drawing text can be compared against the library index directly.
    """
    s = str(text).upper().replace("×", "X")
    s = re.sub(r"[\s\-_,]", "", s)
    # Sentence punctuation at the END only. A drawing note reads "...6mm
    # CHEQUER PLATE." and a schedule cell reads "7FP;" -- the full stop is
    # prose, not notation. Interior periods are NOT touched: they are decimal
    # points, and 21.3CHS2 would stop matching the library if they were.
    #
    # Only the families whose ID ends in a letter or has no type keyword were
    # affected -- 7FP, 15R -- because everything else recovered through the
    # canonical path. That made it a narrow, silent miss rather than a visible
    # one. Found by scripts/permute_packs.py.
    s = s.rstrip(".;:")
    return _NUM.sub(lambda m: _trim(m.group(0)), s)


# Drawing-notation keyword -> library type token. Order matters: the first
# pattern that matches wins, so narrower tokens come before broader ones.
_TYPE_WORDS = [
    (r"UNIVERSAL\s+BEAM|(?<![A-Z])UB(?![A-Z])", "UB"),
    (r"UNIVERSAL\s+COLUMN|(?<![A-Z])UC(?![A-Z])", "UC"),
    (r"(?<![A-Z])WB(?![A-Z])", "WB"),
    (r"(?<![A-Z])WC(?![A-Z])", "WC"),
    (r"(?<![A-Z])PFC(?![A-Z])|PARALLEL\s+FLANGE\s+CHANNEL", "PFC"),
    (r"(?<![A-Z])TFC(?![A-Z])", "TFC"),
    (r"(?<![A-Z])TFB(?![A-Z])", "TFB"),
    (r"(?<![A-Z])BT(?![A-Z])", "BT"),
    (r"(?<![A-Z])CT(?![A-Z])", "CT"),
    (r"(?<![A-Z])UA(?![A-Z])|UNEQUAL\s+ANGLE", "UA"),
    (r"(?<![A-Z])EA(?![A-Z])|EQUAL\s+ANGLE|\bANGLE\b", "EA"),
    (r"(?<![A-Z])CHS(?![A-Z])|\bPIPE\b|\bOD\b|CIRCULAR\s+HOLLOW", "CHS"),
    (r"(?<![A-Z])SHS(?![A-Z])|SQUARE\s+HOLLOW", "SHS"),
    (r"(?<![A-Z])RHS(?![A-Z])|RECTANGULAR\s+HOLLOW", "RHS"),
    (r"(?<![A-Z])BPL(?![A-Z])|BISALLOY|(?<![A-Z])BIS(?![A-Z])", "BPL"),
    # Floor/chequer/tread plate is a distinct library family, not plain plate:
    # Its own family by labour rate. The masses no longer differ: 6FP read
    # 49.1 kg/m2 against 6PL's 47.1 until 24 Sep 2026, but that 49.1 was a
    # stale cache of the tread allowance Q3 dropped (fsg-estimating-tools#385),
    # and both are 47.1 now. Keyword-matched, never mass-matched, so nothing
    # below depends on the difference. Must come before the generic
    # PLATE pattern below or it is swallowed as plain PL.
    (r"(?:FLOOR|CHEQUER|CHECKER|TREAD)\s*PLATE", "FP"),
    # Compound spellings are one word on a lot of drawings -- BASEPLATE,
    # CAPPLATE, ENDPLATE. `\bPLATE\b` has no word boundary inside a compound,
    # so `BASE PLATE 20` resolved to 20PL and `BASEPLATE 20` resolved to
    # nothing at all: a silent miss, not a reported one.
    #
    # This is not the library guessing. A baseplate IS a plate -- FSG's library
    # has no separate baseplate family -- so all this does is make the joined
    # spelling agree with the spaced spelling that already worked.
    #
    # The prefixes are named rather than swallowed by a blanket `\w*PLATE`,
    # because two common words end in PLATE and neither is one: TEMPLATE (a
    # setting-out aid) and NAMEPLATE (a label). A blanket rule would price
    # both as steel. Anything not on this list stays unresolved, which is a
    # finding -- the correct outcome per CLAUDE.md.
    (r"(?<![A-Z])(?:BASE|CAP|END|GUSSET|SPLICE|STIFFENER|SEAT|SOLE|COVER|"
     r"CLEAT|PACKER|PACK|SHIM|WEB|FLANGE|FACE|TOP|BOTTOM|BOT)?\s*"
     r"(?:PLATE|PL)(?![A-Z])", "PL"),
    (r"\bFLAT\b|(?<![A-Z])FL(?![A-Z])", "FL"),
    # SQ before ROD, and `SQUARE ROD` spelled out alongside `SQUARE BAR`.
    #
    # `10 SQ ROD` is a 10 mm SQUARE bar; ROD is the loose word for "bar" in
    # that phrase, not the section family. With ROD first it won, the square
    # evidence was discarded, and the answer was 10ROD at 0.631 kg/m against
    # 10SQ's 0.805 -- 21.6% under the estimator's own figure, labelled
    # `canonical`, i.e. asserted rather than flagged. The same wrong branch
    # produced honest misses at 25 and 40, where the ROD family has no entry
    # and the SQ one does; with SQ first they resolve, so no separate
    # fallback is needed. Measured 31 Aug 2026 against Tier B's estimator
    # dialect (4 take-off lines in 1 pack, all `10 SQ ROD`); Tier A's
    # detailer dialect contains no SQ notation at all.
    #
    # Deliberately narrow. SQ stays BELOW plate: `400 SQ. X 20 PL` is a
    # square plate and PL must keep winning it. Swapping only these two
    # neighbours changes an answer solely where BOTH tokens are present --
    # `10 SQ`, `10 SQ BAR`, `10 ROD` and `24 RND BAR` are untouched. Where
    # the square size genuinely is not in the library (`24 SQ ROD`) the
    # result is an honest miss, not the round rod: naming the round section
    # for a square notation is the defect, not a fallback.
    (r"(?<![A-Z])SQ(?![A-Z])|SQUARE\s+(?:BAR|ROD)", "SQ"),
    # `DIA 24 RND BAR`, `24 ROUND BAR`: round bar is the library's ROD family
    # (70 detailer lines, 28 Aug 2026). DIA is a qualifier, not a type.
    (r"(?<![A-Z])ROD(?![A-Z])|(?:RND|ROUND)\s*BAR", "ROD"),
    # Angles are written with a bare 'L' suffix throughout FSG's own estimate
    # sheets ('125 x 125 x 8 L', '150 x 90 x 10 L'); equal vs unequal is decided
    # by the dimensions, not by the word. Last in the list so that every
    # explicit keyword above wins first.
    (r"(?:^|\s)L(?:\s|$)", "L"),
]

# Types whose ID is <first number><TYPE><second number>.
_TWO_NUMBER_TYPES = {"UB", "UC", "WB", "WC", "TFC", "TFB", "BT", "CT", "FL"}

# Cold-formed C/Z purlin designations, as Stramit and Lysaght write them and as
# real FSG drawings and take-offs use them: Z20015 = Z200 at 1.5 mm BMT,
# C25024 = C250 at 2.4 mm. 90_Lists carries these only vendor-prefixed
# (`LYS-Z20024`, resolved `exact`); a BARE code (no vendor prefix) does not
# resolve, even though a same-shaped Lysaght row exists under a prefixed id.
#
# tr#280 (6 Sep 2026) tried aliasing a bare code to its Lysaght row; it was
# REVERTED 7 Sep 2026 on the estimating team's first answer to Q26. The
# estimators then answered again, 30 Sep 2026 (David relaying, fsg-tender-
# review#184, handout Q26): "Does a bare cold formed code mean lysaght - Yes."
# The alias is back, as `cold-formed-bare-lysaght`: an EXACT bare-to-`LYS-`
# lookup on the raw text, refusing (`cold-formed`) on a miss. It never goes
# through `canonical_candidates()`/`nearest()` -- adding bare rows to
# 90_Lists instead makes `Z20015` snap to the nearest wall, `Z20024`, 62%
# heavy (the trap Q2 records). It maps to `LYS-` and never to `STR-`: a bare
# `Z25019` has only a `STR-` row, and stays a refusal.
#
# A VENDOR-prefixed code is different: 90_Lists carries no `STR-` rows at
# all today (Lysaght is the only maker actually priced), but a `STR-`
# notation still resolves where a `LYS-` row exists at the same
# shape/depth/BMT (fsg-tender-review#184 Q27, `cold-formed-vendor-
# equivalent` below) -- the manufacturer IS what the drawing wrote there,
# unlike the bare case just reverted. One with no equivalent either way is
# genuinely uncosted, which is still worth recognising -- it separates
# "this is a purlin the library doesn't carry" from "this is unreadable
# text", very different problems for an estimator.
COLD_FORMED = re.compile(r"^([CZ])(\d{3})(\d{2})$")

# A vendor-prefixed cold-formed code, as the archive actually writes one when
# it names the manufacturer: `STR-C20024`, `LYS-Z20015`. `loose_key` strips
# the hyphen before this ever runs, so the pattern matches the joined form.
_VENDOR_COLD_FORMED = re.compile(r"^(STR|LYS)([CZ])(\d{3})(\d{2})$")

#: The two vendors 90_Lists's cold-formed rows ever carry. Genuinely just
#: these two -- fsg-tender-review#184 Q27 answered Stramit/Lysaght
#: interchangeable at matching depth/BMT; it did not open the door to any
#: other maker, and none has shown up in the archive as a purlin prefix.
COLD_FORMED_VENDORS = ("LYS", "STR")


def cold_formed(raw: str) -> tuple[str, int, float] | None:
    """'Z20015' -> ('Z', 200, 1.5). None if it is not a C/Z purlin code."""
    m = COLD_FORMED.match(loose_key(raw))
    if not m:
        return None
    shape, depth, bmt = m.groups()
    return shape, int(depth), int(bmt) / 10


def vendor_cold_formed(raw: str) -> tuple[str, str, int, float] | None:
    """'STR-C20024' -> ('STR', 'C', 200, 2.4). None if it is not a
    vendor-prefixed C/Z purlin code."""
    m = _VENDOR_COLD_FORMED.match(loose_key(raw))
    if not m:
        return None
    vendor, shape, depth, bmt = m.groups()
    return vendor, shape, int(depth), int(bmt) / 10


# tr#359, fsg-tender-review, 6 Sep 2026: an equal-angle triple with a glued
# `L` at either end and no space ('L90x90x8', '90x90x8L'), or no `L`/type
# word anywhere at all ('90x90x8'). Measured directly against FSG-25Q-319's
# own `dimensions` field before writing this, not assumed (NOT `callouts` --
# `section_recall` reads `callouts` only, so this population and that metric
# never meet; see the field note below): the corpus that actually exists
# there is the GLUED-L shape -- 51 occurrences, 25 distinct leg/leg/
# thickness combinations, all of them a short "mark - notation" legend entry
# ('aa - L45x45x5') -- not the fully bare one, which barely occurs as its
# own isolated string once real drawing text is accounted for (an earlier
# draft of this comment measured "bare, no L anywhere" and found the real
# population was glued-L instead; corrected before this shipped, not
# after). Both shapes are covered here since neither is riskier than the
# other once `L`/type-word detection has already ruled out everything else.
#
# Of the 25 distinct combinations measured, 17 are non-standard thicknesses
# or plainly garbled and correctly resolve to nothing today.
#
# WHAT THIS DOES NOT FIX, found the same night measuring the above: nearly
# every one of these 51 legend entries is itself a short embedded string
# ('aa - L45x45x5', not 'L45x45x5'), and `resolve()` anchors to the WHOLE
# string. Checked directly against all 292 `dimensions` entries anywhere in
# FSG-25Q-319 whose embedded notation names one of that job's 15 priced
# sections (a larger population than the 51 above -- it also includes the
# job's separate schedule-row `dimensions`, e.g. '1130 2 EA 70 x 70 x 5
# 1809 9.8 9.8 345 T201/6/13/180'): only 1 of 292 resolves on the full
# string this fix actually receives; the other 291 refuse, correctly,
# because the section sits inside a longer string this fix was never meant
# to parse. Extracting a section notation out of a legend line or a bill-
# of-materials row is a parsing problem, not a resolver-tolerance one, and
# nothing here touches it.
#
# EXACT lookup only, same discipline as `cold_formed()`'s Lysaght alias
# above and for the identical reason: `canonical_candidates()`/`nearest()`
# round to the closest library mass by design, which is exactly the
# mechanism that would turn one of those 17 garbled triples into a
# confident wrong section instead of an honest miss. This function commits
# to nothing -- `resolve()` is the only caller allowed to decide what an
# exact-or-refuse result means, matching the alias block's own shape.
_BARE_OR_GLUED_L_TRIPLE = re.compile(
    r"^L?\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*(L)?\s*$")


def _bare_equal_angle(raw: str) -> tuple[str, str] | None:
    """`(leg, thickness)` if `raw` is a three-number triple -- bare, or with
    a glued `L` at either end -- and no type word anywhere in it. An EXACT
    candidate to look up, never a `nearest` starting point. `None` for
    anything already carrying its own SPACED `L` or another type word (the
    existing dialect paths own those), a triple with `L` glued to BOTH ends
    (not a spelling this dialect is known to use -- refusing rather than
    guessing which one is noise), an unequal-leg triple (not an equal angle
    notation at all -- a genuinely different shape), or anything that is not
    a plain three-number triple in the first place.
    """
    stripped = str(raw).strip().upper()
    if any(re.search(pattern, stripped) for pattern, _ in _TYPE_WORDS):
        return None
    m = _BARE_OR_GLUED_L_TRIPLE.match(stripped)
    if not m:
        return None
    leg1, leg2, thickness, trailing_l = m.groups()
    if stripped.startswith("L") and trailing_l:
        return None  # 'L90x90x8L' -- not a spelling this dialect uses
    leg1, leg2, thickness = _trim(leg1), _trim(leg2), _trim(thickness)
    if leg1 != leg2:
        return None
    return leg1, thickness


# Materials the steel library cannot price. The alloy designations are the
# ones a real FSG structural aluminium specification names (6061-T6,
# 6063-T5/T6, 5083-H116/H321, 5005-H34).
# A bare four-digit alloy number is also a length, a level and a grid
# reference. `200 UB 25 x 6061 LG` was refused as material-mismatch
# because 6061 appeared anywhere in the string: a real steel section,
# refused, on a number that meant 6061 mm long. An alloy number now has to
# sit next to an alloy word or carry a temper suffix, which is how a
# drawing writes one.
#
# `SS` and `S/S` added 5 Sep 2026 (this package's own known_issues.py issue
# 3): both source resolvers added them 3 Sep 2026 in step with each other
# (fsg-tender-review's own comment cites its twin, #203) -- a decision
# already made and already implemented identically in both repos this
# package consolidates, not a fresh one for this package to make on its
# own. `STAINLESS` was carried and the abbreviation every detailer actually
# types was not, so `SS 10 ROD` returned a CARBON `10ROD` labelled
# `canonical` -- asserted rather than flagged. The `\b` on both sides was
# MEASURED, not assumed, in fsg-tender-review: of 3,841 distinct archive
# profiles exactly ONE matches (`M16 SS BOLT`, which is stainless) and ZERO
# of the library's section ids do.
_NON_STEEL = re.compile(
    r"\b(?:ALUMINI?UM|ALUM|ALLOY|STAINLESS|SS|S/S|TIMBER|GRP|FRP)\b"
    r"|\b(?:6061|6063|5083|5005)[\s-]*T\d+\b"
    r"|\b(?:ALUMINI?UM|ALUM|ALLOY)[\s-]*(?:6061|6063|5083|5005)\b"
    r"|\b(?:6061|6063|5083|5005)[\s-]*(?:ALUMINI?UM|ALUM|ALLOY)\b"
)

# A drawing writes three kinds of modifier around a section, and only two of
# them were ever handled:
#
#   material  STAINLESS 10 ROD   a different metal -- `_NON_STEEL` refuses
#   finish    GALV 10 ROD        same steel, same mass -- drops harmlessly
#   shape     M30 THREADED ROD   same steel, DIFFERENT cross-section
#
# The third kind was being treated as the second: the word was dropped and the
# plain-shape section returned as `canonical`, i.e. asserted as a clean match
# rather than flagged. `10 SQ ROD` was this same defect and closed on 31 Aug
# 2026 (SQ above ROD in `_TYPE_WORDS`) -- but only because the library HAS an
# SQ family, so the square evidence had a real section to go to. THREADED and
# HEX have no family in 90_Lists at all, so there is no section to move the
# answer to, and the honest outcome is a refusal that says why -- exactly as
# `material-mismatch` refuses rather than pricing aluminium as steel.
#
# The mass really does move. Measured against the detailer corpus 31 Aug 2026
# (189 `mto_line` rows carry THREAD, across 11 distinct notations), taking
# each notation's own kg/m from its own weight and length:
#
#   M12 THREADED ROD   0.798 kg/m over 10 lengths    12ROD is 0.909   +13.9%
#   M36 THREADED ROD   7.629 kg/m over 11 rows       36ROD is 8.19     +7.3%
#   M30 THREADED ROD   5.0   kg/m over 55 rows       30ROD is 5.689   +13.8%
#
# -- a threaded rod runs some 7-14% lighter than the plain round bar of the
# same nominal diameter, and the resolver was reporting the heavier one with
# nothing to flag. (The M30 figure is under a per-piece reading of the weight
# column; it is the magnitude that matters here, not the third digit.)
#
# HEX has ZERO incidence in that corpus and is listed on geometry, not on a
# count: a hexagon across flats is ~9.3% lighter than the circle that
# circumscribes it, so the same silent over-read is available the first time a
# drawing writes one. Listing it costs an honest miss, never a wrong number.
#
# Deliberately narrow, same as the SQ fix. Only a word naming a cross-section
# the library cannot price belongs here. GALV, BLACK, PAINTED and the rest are
# finishes and must keep dropping; SQ must NOT be here, because 10SQ..40SQ are
# real library rows and `10 SQ ROD` has a right answer.
_SHAPE_MODIFIER = re.compile(
    r"(?<![A-Z])(?:ALL[\s_-]*)?THREAD(?:ED)?(?![A-Z])"
    r"|(?<![A-Z])HEX(?:AGONAL|AGON)?(?![A-Z])"
    # `M24 ROD` is threaded rod: M is a metric thread designation, and
    # threaded rod is 7 to 14% lighter than the plain bar of the same
    # nominal diameter. It resolved to 24ROD labelled canonical, which is
    # the plain bar's mass asserted as exact. Only immediately before ROD
    # or BAR: `M24` elsewhere on a drawing is a bolt callout and says
    # nothing about the section.
    r"|(?<![A-Z])M\d+(?:\.\d+)?\s*(?=ROD(?![A-Z])|BAR(?![A-Z]))"
)


def shape_modifier(raw: str) -> str | None:
    """The shape-modifying word this notation carries, or None.

    Exposed so a caller can report *which* word made `resolve()` refuse
    instead of a bare verdict: the reason a value carries has to reach the
    operator, and `shape-modifier` alone does not say whether the drawing
    wrote THREADED or HEX.
    """
    found = _SHAPE_MODIFIER.search(str(raw or "").upper())
    return found.group(0) if found else None


# A member mark at the start of a phrase ('C1 100 x 100 x 5 SHS').
_LEADING_MARK = re.compile(r"^[A-Z]{1,3}\d{1,3}[A-Z]?(?=[\s\-,])")

# A dimension group: numbers joined by 'x', e.g. '200 X 200 X 10', '400 SQ. X 20'.
_DIM_GROUP = re.compile(r"\d[\d.]*(?:\s*(?:SQ\.?\s*)?[X*]\s*\d[\d.]*)+")
# '10 THK', '10 THICK', 'THK 10' -- an explicit thickness callout wins outright.
_THK_BEFORE = re.compile(r"(\d[\d.]*)\s*(?:MM\s*)?TH(?:ICK|CK|K)\b")
_THK_AFTER = re.compile(r"\bTH(?:ICK|CK|K)\.?\s*(\d[\d.]*)")
# A number written directly against the plate word, either side of it:
# '10 PL 100 x 6000', 'PLATE 12 250 x 250', '20 BASEPLATE'. The optional
# qualifier is the list `_TYPE_WORDS` accepts in front of PL/PLATE, so
# '20 BASEPLATE' and '20 GUSSET PLATE' read the same way as '20 PL'.
_PL_QUALIFIER = (r"(?:BASE|CAP|END|GUSSET|SPLICE|STIFFENER|SEAT|SOLE|COVER|CLEAT|"
                 r"PACKER|PACK|SHIM|WEB|FLANGE|FACE|TOP|BOTTOM|BOT)?")
_PL_BEFORE = re.compile(r"(\d[\d.]*)\s*(?:MM\s*)?" + _PL_QUALIFIER
                        + r"\s*(?:PLATE|PL)(?![A-Z])")
_PL_AFTER = re.compile(r"(?<![A-Z])" + _PL_QUALIFIER + r"\s*(?:PLATE|PL)\.?\s*(\d[\d.]*)")


def _plate_thickness(text: str, nums: list[str]) -> str:
    """Which number in a plate callout is the thickness.

    Drawings write it four ways, and the library files plate by thickness
    only:

        '12 mm PLATE'            -> 12   the only number
        '200 x 200 x 10 PL'      -> 10   smallest of the dimension group
        'PLATE 10 THK 250 x 250' -> 10   an explicit THK callout beats position
        '10 PL 100 x 6000'       -> 10   a number against the word, outside
                                         the group, beats the group minimum

    Smallest, not last: a plate's thickness is by definition its least
    dimension, and position is a convention that differs between a drawing
    ('200 x 10 PL') and a detailer ('PL10X200'). Taking the last number read
    the detailer's form as a 200 mm plate.

    The fourth form, 7 Sep 2026: `10 PL 100 x 6000` is a 10 mm plate, 100
    wide, 6000 long, and the group minimum read it as 100PL -- ten to twenty
    times the mass, labelled canonical. A number written against the PL
    token and OUTSIDE the dimension group is the thickness the same way a
    THK callout is. Only outside: in `200 x 200 x 10 PL` the adjacent 10 is
    the group's own last member, and the minimum rule answers it unchanged.
    """
    for pattern in (_THK_BEFORE, _THK_AFTER):
        found = pattern.search(text)
        if found:
            return _trim(found.group(1))
    group = _DIM_GROUP.search(text)
    for pattern in (_PL_BEFORE, _PL_AFTER):
        found = pattern.search(text)
        if found and not (group and group.start() <= found.start(1) < group.end()):
            return _trim(found.group(1))
    if group:
        members = _NUM.findall(group.group(0))
        if len(members) >= 2:
            return _trim(min(members, key=float))
    return nums[0]


# Notation the detailing package emits, which is not the notation a drawing
# uses. Measured against 82,213 real MTO lines on 28 Aug 2026: the resolver
# read 51.5% of the `profile` values FSG's own detailers wrote, and these
# three families were 74% of everything it missed --
#
#     PLT10*80      15,486 lines   plate, 10 thick x 80 wide
#     FLT10*90      11,698 lines   flat bar, 10 thick x 90 wide
#     FL10*100       2,147 lines   the same thing, shorter prefix
#
# Two things make this worth a rule rather than a shrug. The dimension order
# is REVERSED from the library's (`100x10 FLAT` is `100FL10`: width first),
# so these were not near-misses, they were silent misses. And `execution.py`
# compares an estimate against what was actually built using exactly this
# data -- reading half of it means measuring the accuracy claim on half the
# evidence.
#
# The order was verified, not assumed: `weight_each_kg / length` across the
# corpus matches thickness x width x 7850 (PLT10*1720 -> 134.95 kg/m measured,
# 135.02 computed), and a 1720 mm thick plate does not exist.
# The width is optional: `PLT10` on its own is 386 lines of this corpus, and a
# plate's library mass depends on thickness alone, so dropping the width loses
# nothing the library was ever going to use.
_DIALECT_PLATE = re.compile(r"^PLT\s*([\d.]+)(?:\s*[*X]\s*([\d.]+))?\s*$")
# The same dialect with the shorter prefix glued to the number: `PL20X180` is
# 20 thick x 180 wide, exactly like `PLT20X180`. Measured 28 Aug 2026 (Tier A):
# read through the drawing path instead, the X-group took the LAST number as
# the thickness -- `PL20X180 -> 180PL`, a 9x overstatement labelled canonical.
# No space allowed after PL: `PL 200 X 10` is a drawing writing width first.
_DIALECT_PLATE_SHORT = re.compile(r"^PL([\d.]+)\s*[*X]\s*([\d.]+)\s*$")
_DIALECT_FLAT = re.compile(r"^FLT?\s*([\d.]+)\s*[*X]\s*([\d.]+)\s*$")
# `FLRPL8x1500`: floor (chequer) plate, 8 thick x 1500 wide -- the FP family,
# not PL (a different labour rate; the masses agree at 47.1 kg/m2 since
# fsg-estimating-tools#385). Width dropped as
# for PLT. Must be tried before the plate patterns, which it would otherwise
# never reach: `PL` does not match, but a looser future pattern might.
_DIALECT_FLOOR_PLATE = re.compile(r"^FLRPL\s*([\d.]+)(?:\s*[*X]\s*([\d.]+))?\s*$")
# Lysaght and Stramit are brands, not section families. Stripping the prefix lets the
# cold-formed path recognise `C15024`/`Z15019` and return the honest
# `cold-formed` outcome instead of a blank.
_DIALECT_VENDOR = re.compile(r"^(?:LYS|STR)\s*[-_ ]\s*")

# `LINERPL13*206.5` is deliberately NOT here. A liner plate is frequently a
# wear plate, and wear plate is Bisalloy -- resolving it to plain PL would be
# the exact BPL/PL confusion CLAUDE.md rules out, only arrived at politely.
# It stays unresolved, which is a finding, which is correct.

# `UB610101`: a detailer's designation order, depth and mass glued with no
# separator and UB written first -- the library files it the other way round,
# `610UB101`. AS/NZS UB depths are three digits throughout the range this
# library carries (150-1200), so the split is fixed rather than guessed per
# notation: first three digits are the depth, the rest is the mass. Ported
# 5 Sep 2026 from both source resolvers, which already agreed on this (added
# the same day in step with each other, `fsg-tender-review`'s
# `docs/library-gap-ranked.md` "Designation order and angle notation") --
# this package's port of `_expand_detailing_dialect` predated that sync, the
# same drift shape as the `SS`/`S/S` gap fixed earlier the same night. A
# split that does not land on a real row simply does not resolve, same as
# any other candidate: this generates a candidate, it does not assert one.
_DIALECT_UB_GLUED = re.compile(r"^UB(\d{3})(\d{2,3})$")
# `L75*6`: FSG's own convention writes a trailing, spaced 'L' for an angle;
# the archive's detailer dialect glues a LEADING 'L' to the leg dimension
# instead, with only two numbers given -- leg and thickness, an equal angle
# implied by there being no second leg. Expanded to the spelled-out
# three-number form ('75 X 75 X 6 ANGLE') so it goes through the same EA
# branch every other equal-angle notation does.
#
# The trailing `H?` (tr#359, fsg-tender-review, 6 Sep 2026): a transmission-
# tower drawing's own convention appends a bare `H` to mark a Horizontal
# member on the same section a diagonal would carry unmarked -- `L90x6H`,
# 10 occurrences in FSG-25Q-319's own `dimensions` field, none of them a
# different section from `L90x6`. NOT `callouts` -- that job's
# `section_recall` reads `callouts` only, so this population and that
# metric never meet regardless of this fix (a peer re-derived the full
# `dimensions` census independently: 890 H-suffix occurrences, 22 distinct
# leg/thickness pairs job-wide, of which 4 name one of the job's 15 priced
# sections; most of those, like the glued/bare-triple population in the
# companion fix, arrive embedded in a longer legend or schedule string that
# `resolve()`'s anchored matching still refuses -- a parsing gap, not
# something this change touches). Measured before widening: `H` never
# appears after a digit anywhere in Tier A's 14,556 archive lines (the
# detailer's own dialect), so this is a drawing-side convention this change
# cannot regress there. Deliberately scoped to `H` alone, not "any trailing
# letter" -- that is every distinct suffix this corpus was measured to
# carry; a different letter is a new finding, not an assumed member of the
# same family.
_DIALECT_ANGLE_GLUED = re.compile(r"^L\s*([\d.]+)\s*[*X]\s*([\d.]+)\s*H?\s*$")


def _expand_detailing_dialect(text: str) -> str:
    """Rewrite detailing-package notation into notation this module reads.

    A rewrite rather than a new branch in `canonical_candidates`, so the
    dialect gets the same demarking, tolerance and material handling as
    everything else instead of a second, subtly different path.
    """
    stripped = text.strip().upper()
    m = _DIALECT_FLOOR_PLATE.match(stripped)
    if m:
        return f"{m.group(1)} FLOOR PLATE"
    m = _DIALECT_PLATE.match(stripped) or _DIALECT_PLATE_SHORT.match(stripped)
    if m:
        # A plate is priced by thickness; the width is the piece, not the
        # section, and the take-off carries it separately. Thickness is the
        # smaller of the two whichever is written first -- the dialect puts
        # it first, but a 180 mm thick x 20 wide plate does not exist.
        dims = [g for g in m.groups() if g]
        return f"{min(dims, key=float)} PLATE"
    m = _DIALECT_FLAT.match(stripped)
    if m:
        thickness, width = m.group(1), m.group(2)
        return f"{width} X {thickness} FLAT"
    m = _DIALECT_UB_GLUED.match(stripped)
    if m:
        depth, mass = m.group(1), m.group(2)
        return f"{depth} UB {mass}"
    m = _DIALECT_ANGLE_GLUED.match(stripped)
    if m:
        leg, thickness = m.group(1), m.group(2)
        return f"{leg} X {leg} X {thickness} ANGLE"
    return _DIALECT_VENDOR.sub("", stripped, count=1)


# A number glued to a letter run that is not a type word or a unit: `250LK`,
# `250LR`. Those are marks. `BIS250LK_250LR` read as a section became a
# 250 mm Bisalloy plate (Tier A, 28 Aug 2026); a notation whose numbers come
# from marks, not sizes, must stay unresolved.
_MARK_OK_SUFFIX = {"MM", "PL", "PFC", "UB", "UC", "WB", "WC", "EA", "UA", "SHS", "RHS",
                   "CHS", "BT", "CT", "TFB", "TFC", "FL", "FLT", "PLT", "ROD", "SQ", "BPL",
                   "FP", "THK", "OD", "DIA", "RND", "BAR", "FLAT", "PLATE", "MS"}


def _looks_like_mark(raw: str) -> bool:
    text = str(raw).upper()
    if "_" not in text:
        return False
    for m in re.finditer(r"\d([A-Z]{2,})(?=_|\s|$)", text):
        if m.group(1) not in _MARK_OK_SUFFIX:
            return True
    return False


def canonical_candidates(raw: str) -> list[str]:
    """Candidate library IDs for a section written the way a drawing writes it.

    Most-specific first. The plain space-stripped form is always included
    last -- so this is never worse than a bare `loose_key()` comparison.
    """
    text = str(raw or "").upper().replace("×", " X ")
    if not text.strip():
        return []
    text = _expand_detailing_dialect(text)
    # A leading member mark is not part of the designation, and leaving it in
    # corrupts the result rather than merely failing: 'C1 100 x 100 x 5 SHS'
    # reads as 1SHS5 -- a real library section, so it comes back labelled
    # canonical with nothing to warn on. Only strip when something is left.
    demarked = _LEADING_MARK.sub("", text, count=1).strip()
    if demarked and _NUM.search(demarked):
        text = demarked
    stripped = re.sub(r"\s", "", text)

    kind = next((tok for pat, tok in _TYPE_WORDS if re.search(pat, text)), None)
    nums = [_trim(n) for n in _NUM.findall(text)]
    out: list[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate not in out:
            out.append(candidate)

    if kind in _TWO_NUMBER_TYPES and len(nums) >= 2:
        add(f"{nums[0]}{kind}{nums[1]}")
        if kind == "FL" and len(nums) == 2:
            # A flat bar is filed width-then-thickness, and a drawing writes it
            # either way round: '100 X 10 FL' resolved and 'FL 100 X 10' did
            # not. Offer the sorted form as well -- widest first, which is what
            # the library uses -- so both spellings reach 100FL10. Offered
            # second, so an exact match on the written order still wins.
            #
            # Exactly two numbers, 7 Sep 2026. With three, the first is a
            # count or a length, not a dimension, and sorting the first two
            # read `6 x 100 x 10 FL` (six off, 100 x 10) as 100FL6 -- 40%
            # under, labelled canonical. The written-order candidate above
            # is still offered, so `100 x 10 FL x 6000` keeps resolving; the
            # count-first spelling is an honest miss until a drawing's
            # quantity grammar is read on purpose rather than by accident.
            wide, thin = max(nums, key=float), min(nums, key=float)
            add(f"{wide}FL{thin}")
    elif kind == "PFC" and nums:
        add(f"{nums[0]}PFC")  # flange width is implied by depth in the library
    elif kind == "EA" and nums:
        # '90 x 90 x 8 EA' -> 90EA8 ; '90 EA 8' -> 90EA8
        if len(nums) >= 3 and nums[0] == nums[1]:
            add(f"{nums[0]}EA{nums[2]}")
        elif len(nums) >= 3:
            # Unequal legs are a UA whatever word the drawing used. `ANGLE`
            # maps to EA here because most angles are equal, but
            # '150 x 90 x 10 ANGLE' resolved to 150EA10 at 21.9 kg/m against a
            # true 17.3 -- 27% over, labelled canonical. The bare `L` branch
            # below already decided this correctly; this one did not, and
            # '100 x 75 x 6 EA' silently discarded the 75.
            add(f"{nums[0]}x{nums[1]}UA{nums[2]}")
        elif len(nums) >= 2:
            add(f"{nums[0]}EA{nums[-1]}")
    elif kind == "UA" and len(nums) >= 3:
        add(f"{nums[0]}x{nums[1]}UA{nums[2]}")
    elif kind == "L" and len(nums) >= 3:
        if nums[0] == nums[1]:
            add(f"{nums[0]}EA{nums[2]}")
        else:
            add(f"{nums[0]}x{nums[1]}UA{nums[2]}")
    elif kind == "SHS" and nums:
        if len(nums) >= 3 and nums[0] == nums[1]:
            add(f"{nums[0]}SHS{nums[2]}")
        elif len(nums) == 2:
            # `100 SHS 3`, `100 x 100 SHS`: side and wall, or a bare head.
            # Exactly two, 7 Sep 2026: with three numbers whose first pair
            # differ, `100 x 50 x 3 SHS` is a rectangular section written
            # with the wrong word, and the old `>= 2` branch made it 100SHS3
            # -- 36% over, labelled canonical. It now stays unresolved; the
            # library's row for those sides is an RHS, and naming it is the
            # estimator's call to make, not the resolver's to assert.
            add(f"{nums[0]}SHS{nums[-1]}")
    elif kind == "RHS" and len(nums) >= 3:
        add(f"{nums[0]}x{nums[1]}RHS{nums[2]}")
    elif kind == "CHS" and len(nums) >= 2:
        add(f"{nums[0]}CHS{nums[1]}")
        # One library row writes a decimal OD without its point: `603CHS3.91`
        # is 60.3 OD x 3.91 wall, confirmed by the estimating team (28 Aug
        # 2026, Q2b: "the correct pipe size is 60.3 OD x 3.91 mm"). Offered
        # second, so the honest spelling still wins wherever both exist, and
        # only when the drawing's OD actually carries a decimal -- 273, 508
        # and 762 are real integer ODs and must not be reinterpreted.
        if "." in nums[0]:
            add(f"{nums[0].replace('.', '')}CHS{nums[1]}")
    elif kind in {"PL", "BPL", "FP"} and nums:
        # Plate is filed by THICKNESS, and drawings write the thickness in
        # three different positions. Taking nums[0] positionally is only
        # right for the simplest one -- see _plate_thickness's own docstring
        # for the 20x-overstatement failure this guards against.
        add(f"{_plate_thickness(text, nums)}{kind}")
    elif kind in {"ROD", "SQ"} and nums:
        # Unlike plate, nums[0] is right by construction here: every ROD and
        # SQ row in the library is a single dimension, so a second number is
        # always a length or a count.
        add(f"{nums[0]}{kind}")

    add(stripped)
    return out


_SPLIT_ID = re.compile(r"^(?P<head>.*?)(?P<type>[A-Z]+)(?P<tail>\d+(?:\.\d+)?)$")

# How far a drawing's trailing number may sit from a library one before a
# nearest-size match is refused. The library rounds masses (250UB26 is
# AS/NZS 250UB25.7), so drawings routinely write a number that is close but
# not equal. 5% clears that rounding while still refusing to turn '200 UB 20'
# into either of its real neighbours, 200UB18 and 200UB22.
NEAREST_TOLERANCE = 0.05
# A nearest match must also be clearly better than the runner-up, or the
# drawing's number sits between two real sections and guessing is not safe.
NEAREST_MARGIN = 1.5
# How far a drawing's *depth/diameter* may sit from the library's before the
# two stop being the same family. Covers nominal-vs-actual outside diameters
# (a drawing's '114 CHS' against the library's 114.3CHS...), nothing wider.
HEAD_TOLERANCE = 0.01


def _split_id(section_id: str) -> tuple[str, str, float] | None:
    """'250UB26' -> ('250', 'UB', 26.0). None if the ID has no trailing size."""
    m = _SPLIT_ID.match(loose_key(section_id))
    if not m:
        return None
    return m.group("head"), m.group("type"), float(m.group("tail"))


# How far a drawing's number may sit from the library's rounded whole-kg/m
# figure and still count as the same section, standard-written rather than
# near-missed. Derived from 85 of 85 `nearest` outcomes in the 28 Aug 2026
# Tier A run, all within 1% on mass -- fsg-tender-review's historical value.
# Fsg-bluebeam-steel-standards had no one-decimal clause at all (whole-number
# rounding only), which is what made `273 CHS 6.4` read `canonical` in one
# repo and `nearest` in the other. ANSWERED 7 Sep 2026
# (Rostov-au/fsg-tender-review#184 Q25): both resolvers converge on this
# clause applying -- see the module docstring's "ANSWERED 7 Sep 2026" section.
# CORRECTED 18 Sep 2026: that convergence settled the verdict but reused
# this clause's library-mass answer for `6.4`, which is the imperial 6.35
# mass -- wrong once "metric, 6.40" was confirmed. `6.4` no longer reaches
# this function at all; `_chs_metric_wall()` claims it first. The clause
# below still governs every other CHS wall written one decimal short.
ROUNDING_TOLERANCE = 0.051


def _is_rounding(candidate: str, section: Section) -> bool:
    """True when the library ID is simply the drawing's number, rounded.

    `90_Lists` stores AS/NZS masses rounded to whole kg/m -- 250UB25.7 is
    filed as 250UB26, 410UB59.7 as 410UB60. A drawing quoting the exact mass
    is therefore not a near-miss needing an estimator's eye, it is the same
    section written the standard's way.

    A drawing that quotes a *different* number ('250 UB 25' against the
    library's 250UB26) still comes back as `nearest`, because that one
    really might be a different section.
    """
    left = _split_id(candidate)
    right = _split_id(section.section_id)
    if not left or not right:
        return False
    if left[1] != right[1]:
        return False
    if round(left[2]) == right[2]:
        return True
    # The same rule one decimal down: the library files a CHS wall as
    # 7.11 / 8.18 (the standard's figure) and a detailer writes 7.1 / 8.2 --
    # a rounding, not a near-miss. NOT 6.4/6.35 any more (CORRECTED 18 Sep
    # 2026): those are two genuinely different AS/NZS 1163 walls, 0.8%
    # apart, and `6.4` is claimed by `_chs_metric_wall()` before this
    # function is ever reached -- see that function and the module
    # docstring's 18 Sep 2026 section.
    return abs(left[2] - right[2]) <= ROUNDING_TOLERANCE


# fsg-tender-review#184 Q25, CONFIRMED METRIC 18 Sep 2026 (David: "Confirm
# metric, 6.40" -- see the module docstring's 18 Sep 2026 section for the
# full history). `90_Lists` has never carried a genuine metric-wall CHS row
# at any OD, so a drawing's `6.4` is a library GAP, not a wrong entry in an
# existing row, and this table is a resolver rule rather than a hand-edit to
# `data/fsg_sections.json` -- the next `scripts/refresh_from_workbook.py`
# run reads `90_Lists` and would silently drop a hand-added row (see that
# script's own docstring, and `fsg_sections.json`'s `_provenance.note`).
#
# Values are AS/NZS 1163 C350L0 published masses, InfraBuild "Know Your
# Steel" V9 (Jun 2023) Structural CHS table, for every OD this library
# already carries a `{OD}CHS6.35` (imperial) sibling for. Cross-checked
# against the plain annulus formula this library's own 6.35mm-wall masses
# already imply to within 0.3% (mass = 0.024661 * t * (D - t), t and D in
# mm) -- every entry below agrees with that formula to two figures except
# where noted. `609.6` has no published cell in InfraBuild's table (listed
# as `610 x 6.4` with mass blank -- not a stocked combination) and is
# formula-only: 95.2 kg/m, flagged `published=False` so a caller that cares
# about provenance can tell the two apart.
_CHS_METRIC_6_4_OD_KG_PER_M: dict[str, tuple[float, bool]] = {
    # OD (matches this library's own spelling): (mass_kg_per_m, published)
    "168.3": (25.5, True),
    "219.1": (33.6, True),
    "273": (42.1, True),
    "323.9": (50.1, True),
    "355.6": (55.1, True),
    "406.4": (63.1, True),
    "457.2": (71.1, True),
    "508": (79.2, True),
    "609.6": (95.2, False),
}

_CHS_METRIC_6_4 = re.compile(r"^(\d+(?:\.\d+)?)CHS6\.4$")


def _chs_metric_wall(candidate: str, by_key: dict[str, Section]) -> Section | None:
    """A `{OD}CHS6.4` candidate, synthesised at the confirmed metric mass.

    Only where the library's own `{OD}CHS6.35` sibling exists -- so this
    never asserts an OD the library carries no other evidence for, and a
    genuinely unknown `CHS 6.4` (a size 90_Lists has no row for at all)
    still falls through to the ordinary `nearest`/`unresolved` path below.
    """
    m = _CHS_METRIC_6_4.match(candidate)
    if not m:
        return None
    od = m.group(1)
    entry = _CHS_METRIC_6_4_OD_KG_PER_M.get(od)
    if entry is None:
        return None
    sibling = by_key.get(loose_key(f"{od}CHS6.35"))
    if sibling is None:
        return None
    mass, _published = entry
    return Section(
        section_id=f"{od}CHS6.4",
        category=sibling.category,
        build_default=sibling.build_default,
        mass_kg_per_m=mass,
        plate_thickness_mm=None,
        plate_kg_per_m2=None,
    )


class SectionLibrary:
    """Wraps whatever `Iterable[Section]` it's given -- `classification.Section`
    here, duck-typed against the same six fields `fsg_mto.sections.Section`
    has, so nothing above this class needed to change on the port."""

    def __init__(self, sections: Iterable[Section]) -> None:
        self.sections: list[Section] = list(sections)
        self._by_key: dict[str, Section] = {}
        self._by_family: dict[tuple[str, str], list[tuple[float, Section]]] = {}
        for sec in self.sections:
            self._by_key.setdefault(loose_key(sec.section_id), sec)
            parts = _split_id(sec.section_id)
            if parts:
                head, kind, size = parts
                self._by_family.setdefault((head, kind), []).append((size, sec))

    def __len__(self) -> int:
        return len(self.sections)

    def get(self, section_id: str) -> Section | None:
        return self._by_key.get(loose_key(section_id))

    def _family(self, head: str, kind: str) -> list[tuple[float, Section]] | None:
        """Same-depth, same-type sections.

        Falls back to a near-equal head, because drawings quote a *nominal*
        outside diameter where the library stores the real one: a real
        drawing writes '114 x 4.8 CHS' for what the library calls
        114.3CHS..., and '168 x 4.8 CHS' for 168.3. The tolerance is derived
        from the library's own values rather than a hardcoded
        nominal-to-OD table.
        """
        exact = self._by_family.get((head, kind))
        if exact:
            return exact
        try:
            wanted = float(head)
        except ValueError:
            return None
        for (other_head, other_kind), family in self._by_family.items():
            if other_kind != kind:
                continue
            try:
                value = float(other_head)
            except ValueError:
                continue
            if value > 0 and abs(value - wanted) / value <= HEAD_TOLERANCE:
                return family
        return None

    def nearest(self, candidate: str) -> Section | None:
        """Closest library section of the same depth and type, or None.

        Deliberately conservative: see NEAREST_TOLERANCE / NEAREST_MARGIN.
        """
        parts = _split_id(candidate)
        if not parts:
            return None
        head, kind, size = parts
        family = self._family(head, kind)
        if not family or size <= 0:
            return None
        ranked = sorted(family, key=lambda pair: abs(pair[0] - size))
        best_delta = abs(ranked[0][0] - size)
        if best_delta / size > NEAREST_TOLERANCE:
            return None
        if len(ranked) > 1:
            runner_up = abs(ranked[1][0] - size)
            if runner_up < best_delta * NEAREST_MARGIN:
                return None  # sits between two real sections; do not guess
        return ranked[0][1]

    def resolve(self, raw: str) -> tuple[Section | None, str]:
        """Resolve drawing text to a library Section.

        Returns ``(section, how)`` where *how* is one of:

        - ``exact``          the drawing already wrote the library's own ID
        - ``canonical``      the drawing's notation was rewritten into
          library form, or is the library's own mass, rounded
        - ``nearest``        matched to the closest same-depth section (the
          library rounds masses); **needs an estimator's eye**, callers must
          surface it
        - ``cold-formed-vendor-equivalent``  a VENDOR-PREFIXED C/Z purlin
          code (`STR-C20024`) whose own row is not in 90_Lists, aliased to
          the OTHER vendor's row at the same shape/depth/BMT -- David's
          answer to fsg-tender-review#184 Q27, 7 Sep 2026: Stramit and
          Lysaght purlins are a genuine standard-product fact at matching
          depth/BMT, not merely close on mass. The manufacturer IS what the
          drawing wrote; only the specific row moved. Exact alias only,
          refusing to ``cold-formed`` on a miss
        - ``cold-formed-bare-lysaght``  a BARE C/Z purlin code (`Z20015`)
          read as the `LYS-` row of the same shape/depth/BMT -- the
          estimators' answer to fsg-tender-review#184 Q26, 30 Sep 2026
          (bare means Lysaght). Exact alias on the raw text only, refusing
          to ``cold-formed`` on a miss; never nearest, never `STR-`
        - ``cold-formed``    a readable C/Z purlin code, bare or vendor-
          prefixed, that 90_Lists does not carry under the id as written --
          a library gap, not a bad read
        - ``material-mismatch``  aluminium/stainless/timber/etc. -- refuses
          rather than pricing it as steel
        - ``shape-modifier`` the notation names a cross-section 90_Lists has
          no family for (THREADED, HEX) -- refuses rather than dropping the
          word and pricing the plain shape. `shape_modifier()` says which
          word it was; `shape_modifier_candidates()` names the plain section
          it declined to assert, so the miss is settleable
        - ``substitution``   a genuine library gap the drawing states, priced
          as a *different* real size because an estimator decided to, for
          this specific size (`substitutions.py`) -- never a resolver guess
        - ``unresolved``     no safe match

        Callers report *how*, so a match reached by rewriting or rounding is
        never silently presented as one the drawing actually stated.
        """
        if not str(raw or "").strip():
            return None, "unresolved"
        # 90_Lists is entirely steel. Matching an aluminium member against it
        # prices aluminium as steel -- see the module docstring's 2.9x
        # example.
        if _NON_STEEL.search(str(raw).upper()):
            return None, "material-mismatch"
        # A shape modifier the library has no family for. Refused here, before
        # any matching, for the same reason `_NON_STEEL` is: every path below
        # would drop the word and hand back the plain-shape section as
        # `canonical`, which is a confidently wrong mass, not a near miss.
        if _SHAPE_MODIFIER.search(str(raw).upper()):
            return None, "shape-modifier"
        if _looks_like_mark(raw):
            return None, "unresolved"
        direct = self.get(raw)
        if direct is not None:
            return direct, "exact"
        candidates = canonical_candidates(raw)
        for candidate in candidates:
            metric = _chs_metric_wall(candidate, self._by_key)
            if metric is not None:
                return metric, "canonical"
            hit = self._by_key.get(loose_key(candidate))
            if hit is not None:
                return hit, "canonical"
        for candidate in candidates:
            hit = self.nearest(candidate)
            if hit is not None:
                return hit, ("canonical"
                             if _is_rounding(candidate, hit)
                             else "nearest")
        # fsg-tender-review#184 Q27, ANSWERED 7 Sep 2026: a VENDOR-PREFIXED
        # cold-formed code (`STR-C20024`, `LYS-Z20015`) whose own exact row
        # is not in 90_Lists tries the OTHER vendor's row at the same
        # shape/depth/BMT before refusing. David, correcting his own first
        # answer: "The lysart and stramit are interchangeable. Purlin
        # sections are standard and can come from either." Unlike the bare
        # alias tr#280 tried and Q26 had reverted the same day (an
        # ASSUMPTION about a notation naming no manufacturer at all), this
        # is a labelled cross-vendor match the estimating team confirmed is
        # a genuine standard-product fact, not a resolver guess -- 90_Lists
        # carries no `STR-` rows at all today (Lysaght is the only maker
        # priced), so every `STR-` notation refused `cold-formed` before
        # this even where the identical product resolves under `LYS-`.
        #
        # EXACT lookup only, raw text only, same discipline the bare alias
        # established: never through `canonical_candidates()`/`nearest()` (a
        # bare library row for one vendor would let `nearest` match two
        # genuinely different BMTs against each other -- the exact danger
        # that alias's own comment measured before it was reverted), and
        # never a schedule-mark-stripped candidate (unmeasured for this
        # notation; the bare alias narrowed to raw-only after finding
        # candidate-stripping conflated a genuinely different vendor's own
        # prefix with no prefix at all -- the same risk applies here in
        # reverse and there is no archive count yet showing a
        # vendor-prefixed code ever appears schedule-marked).
        vf = vendor_cold_formed(raw)
        if vf is not None:
            written_vendor, shape, depth, bmt = vf
            for vendor in COLD_FORMED_VENDORS:
                if vendor == written_vendor:
                    continue
                alt_id = f"{vendor}-{shape}{depth:03d}{round(bmt * 10):02d}"
                hit = self.get(alt_id)
                if hit is not None:
                    return hit, "cold-formed-vendor-equivalent"
        # fsg-tender-review#184 Q26, ANSWERED 30 Sep 2026 ("Does a bare cold
        # formed code mean lysaght - Yes"): a BARE code (`Z20015`) is the
        # `LYS-` row of the same shape/depth/BMT. EXACT lookup, RAW text only:
        # a schedule-marked candidate (`P7 Z20015`) is deliberately not
        # aliased -- unmeasured, and the earlier alias narrowed to raw-only
        # for the same reason. A miss falls through to the `cold-formed`
        # refusal below; it never snaps to a neighbouring wall.
        bare = cold_formed(raw)
        if bare is not None:
            shape, depth, bmt = bare
            hit = self.get(f"LYS-{shape}{depth:03d}{round(bmt * 10):02d}")
            if hit is not None:
                return hit, "cold-formed-bare-lysaght"
        # Check the candidates too, not just the raw text: a schedule line
        # reads 'P7 Z20015', and only the demarked form is recognisable as a
        # purlin. That form is a real code the library may not carry; it is
        # not aliased to a vendor (see the raw-only note above).
        if cold_formed(raw) is not None or any(
            cold_formed(candidate) is not None for candidate in candidates
        ):
            # Real, readable, and genuinely absent from 90_Lists.
            return None, "cold-formed"
        # tr#359, 6 Sep 2026: a bare equal-angle triple, EXACT lookup only --
        # same shape and same reason as the Lysaght alias above. This must
        # never reach `canonical_candidates()`/`nearest()` above, which is
        # why it is checked here directly on `raw` rather than folded into
        # the dialect-expansion candidates those steps already tried: a
        # candidate list `nearest()` can see is a candidate list `nearest()`
        # WILL round, and a bare, non-standard triple rounding to the
        # closest real angle by weight is the confident-wrong-section
        # failure this whole card exists to keep out.
        bare_ea = _bare_equal_angle(raw)
        if bare_ea is not None:
            leg, thickness = bare_ea
            hit = self.get(f"{leg}EA{thickness}")
            if hit is not None:
                return hit, "canonical"
            return None, "unresolved"
        # Last, and only after every other path has failed to find the size
        # the drawing actually states: an estimator-decided substitution to a
        # different, real size (substitutions.py's own docstring on why this
        # is a named list, never a resolver guess).
        from . import substitutions
        sub = substitutions.lookup_any(raw)
        if sub is not None:
            hit = self.get(sub.to_section_id)
            if hit is not None:
                return hit, "substitution"
        return None, "unresolved"


@functools.lru_cache(maxsize=1)
def library() -> SectionLibrary:
    """FSG's section library, from this repo's own duplicated snapshot.

    No live workbook, unlike the module this was vendored from -- this repo
    already solved that problem for `classification.sections()`, generated
    by the same `scripts/refresh_from_workbook.py` this reuses unchanged.

    **Cached, since 3 Sep 2026.** The previous docstring argued it did not
    need to be: `classification.sections()` is itself `lru_cache`d, so this
    is index construction over an already-cached list rather than a re-read.
    That was true and the conclusion was still wrong. Measured on this
    machine, 750 rows:

        library()                    4.621 ms
        resolve on a held library    0.024 ms
        resolve.resolve("200 PFC")   4.237 ms

    So the module-level `resolve()` spent 99.4% of its time rebuilding an
    index it then used once, and a Tier A replay walks tens of thousands of
    notations through it. "Not a re-read" is not the same as "free".

    Safe to cache because nothing mutates what comes back: every assignment
    to `self` in `SectionLibrary` happens in `__init__`, and the only caller
    that touches `.sections` (`scripts/permute_packs.py`) reads it. A caller
    that ever needs a modified library must build its own `SectionLibrary`
    rather than editing this one -- it is now shared.
    """
    from ._snapshot import sections as _sections

    return SectionLibrary(_sections().values())


def resolve(raw: str) -> tuple[Section | None, str]:
    """Convenience wrapper: `sections.resolve("125 x 125 x 9 SHS")` without a
    caller needing to hold onto a `SectionLibrary` itself.
    """
    return library().resolve(raw)


def ambiguous_candidates(raw: str) -> list[Section]:
    """When `resolve()` comes back `unresolved` for a bare depth with no size
    given (`250UB`, not `250UB37`) and the library carries more than one
    section at that depth, the sections it could have meant.

    `250UB` alone is genuinely three commercial sizes (`250UB26`/`31`/`37`)
    -- the drawing hasn't chosen between them, and treating a bare miss the
    same as a real gap loses that distinction. A caller can put the real
    choice in front of an estimator instead of a flat "unresolved". Empty
    whenever the notation doesn't even name a recognised type, or already
    carries a size (a genuine miss at that point, not an ambiguity).
    """
    text = str(raw or "").upper().replace("×", " X ")
    kind = next((tok for pat, tok in _TYPE_WORDS if re.search(pat, text)), None)
    if kind is None:
        return []
    nums = [_trim(n) for n in _NUM.findall(text)]
    if not nums:
        return []

    # A section's head is not always one number. `250UB` is depth alone, but
    # `250x150 RHS` and `65x50 UA` name a two-number head and are just as
    # ambiguous without a wall or leg thickness -- and RHS, SHS and UA between
    # them are a large share of any real pack.
    #
    # This used to require exactly one number, so every two-number family came
    # back unresolved with NO candidates named: the estimator got "unresolved"
    # and no way to raise a useful RFI, on the most common ambiguity there is.
    # Found by scripts/permute_packs.py.
    #
    # The rule is unchanged in substance: candidates are named only when the
    # notation consumes ALL its numbers in the head, i.e. no size was given.
    # A notation carrying a size that still misses is a genuine miss, not an
    # ambiguity, and must stay empty.
    heads = ["X".join(nums)]
    if len(nums) == 2 and nums[0] == nums[1]:
        # A square hollow section is written `100x100 SHS` on drawings and
        # filed `100SHS5` in the library -- resolve() already collapses the
        # equal pair for `100x100x5 SHS`, so candidate naming must too.
        heads.append(nums[0])
    lib = library()
    for head in heads:
        family = lib._family(head, kind)
        # One candidate counts. `100TFB` had exactly one section at that depth
        # (`100TFB45`), and a two-or-more threshold turned the easiest case in
        # the library into a blank: unresolved, with nothing named, when there
        # was precisely one thing it could have meant.
        #
        # It is still not resolved automatically, and that is deliberate --
        # naming the one candidate lets an estimator settle it in a second;
        # picking it silently would be the library guessing, which CLAUDE.md
        # rules out.
        if family:
            return [section for _size, section
                    in sorted(family, key=lambda pair: pair[0])]
    return []


# The nominal diameter inside a metric thread designation. `_SHAPE_MODIFIER`
# refuses `M24 ROD` outright; the anchor needs the 24 back so it can name the
# plain bar that was ruled out.
_M_DESIGNATION = re.compile(r"(?<![A-Z])M(\d+(?:\.\d+)?)")


def shape_modifier_candidates(raw: str) -> list[Section]:
    """For a notation refused as `shape-modifier`, the plain-shape section the
    library *does* hold at that size -- never the answer, always the anchor.

    CLAUDE.md's rule is that a modifier the library cannot resolve to a mass
    becomes an unresolved finding **with candidates named**, not a silently
    dropped word. Refusing on its own only gets the first half: an estimator
    told `M30 THREADED ROD -> shape-modifier` still has to go and find what
    30 mm round bar weighs before they can settle a rate against it.

    So this names it, and callers must present it as the section that was
    ruled out rather than a suggestion. `30ROD` at 5.689 kg/m is precisely
    the wrong answer this refusal exists to stop being asserted -- but it is
    also the number the estimator needs in front of them to price the real
    one, because a threaded rod is quoted off the plain bar it is cut from.

    Empty when the notation carries no shape modifier, or when the plain form
    does not resolve either (`M16 THREADED STUD` -- STUD is not a section
    family, so there is nothing to anchor on and nothing is invented).
    """
    modifier = shape_modifier(raw)
    if modifier is None:
        return []
    # Two passes, and the second keeps the number. `M12 THREADED ROD` carries
    # two modifiers: removing THREADED leaves `M12 ROD`, which is itself one,
    # and removing that outright takes the 12 with it -- leaving ' ROD' with
    # nothing to anchor on, for exactly the notation the anchor exists to
    # serve. The M is a thread designation wrapped around a real nominal
    # diameter, so the anchor drops the letter and keeps the digits.
    plain = _M_DESIGNATION.sub(lambda m: m.group(1) + " ", str(raw).upper())
    plain = _SHAPE_MODIFIER.sub(" ", plain)
    if not _NUM.search(plain):
        return []
    section, how = library().resolve(plain)
    if section is None or how in ("nearest", "unresolved"):
        # `nearest` is already "needs an estimator's eye" for a notation the
        # library does carry; offering it as the anchor for one it does not
        # stacks two soft answers and calls the result help.
        return []
    return [section]


def mass_of(section_id: str) -> float | None:
    """Kilograms per metre for a section written any way at all, or None.

    Thin compatibility wrapper over `resolve()`, for callers that only need a
    mass and not the full `(Section, how)` result -- `assemble.py` and
    `doubleread.py` both predate this vendored resolver and call it this way.
    Returns None for a plate or anything else the library prices by area
    rather than by length (`Section.mass_kg_per_m` is None for those), same
    as it always has.
    """
    if not section_id:
        return None
    # A caller that needs the `how` calls resolve() directly -- which is what
    # scope_growth.nc1_leg() now does rather than coming through here.
    # evidence-ok: this wrapper's documented contract is a mass and nothing else.
    section, _how = resolve(section_id)
    return section.mass_kg_per_m if section else None
