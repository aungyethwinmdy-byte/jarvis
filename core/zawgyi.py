"""Zawgyi ↔ Unicode for the state-paper database, which holds both.

WHY THIS EXISTS

    Measured 2026-09-29: `articles` mixes encodings in the same column. Searching
    the same word both ways:

        ပြန်လည်  Unicode 641   |  ြပန်လည်  Zawgyi 118
        သတိပေး  Unicode  92   |  သတိေပး  Zawgyi  15

    **118 articles containing `ြပန်လည်` are invisible to a Unicode search for
    `ပြန်လည်`.** Sample of 1,000: 9% of headlines and 62% of body_text are Zawgyi.

WHAT THIS DOES — AND WHAT IT DELIBERATELY REFUSES TO DO

    **It converts in one direction only: Unicode → Zawgyi, and only for a search
    query.** That is what closes the gap, and it is the direction that can be
    done without risk: the result is a search term, so a rule that fires wrongly
    returns the wrong articles and the user sees them — nothing is destroyed.

    **It does NOT convert stored text on the way out.** The first version tried,
    and testing against real rows showed it was worse than leaving the text
    alone:

        clean('နေပြည်တော်')            → 'နပညေြ်တော်'          (valid → garbage)
        clean('…ရွာသွန်းခြင်း')         → '…ရွာသနွ်းခငြ်'         (valid → garbage)

    Two causes, both now designed out:
      1. The rules were applied in a loop until stable. Zawgyi→Unicode and
         Unicode→Zawgyi are inverses, so a second pass undid the first and a
         sixth pass left noise. **One pass per rule, in a fixed order.**
      2. `is_suspect` treated a medial before a consonant as Zawgyi — but `ပြည်`
         is `ပ` + `ြ` + `ည`, which is correct Unicode. **A detector that flags
         ordinary Burmese cannot be trusted to decide what to rewrite.**

    So a suspect row is **labelled, not rewritten**: the user is told it is in the
    other encoding. He can see broken text; he cannot see text that was silently
    changed into different text.

NO LIBRARY

    None is installed and **pip cannot reach PyPI from this machine** (measured
    2026-09-29: `SSL: UNEXPECTED_EOF_WHILE_READING` against pypi.org), so the
    rules are hand-written and tested against rows pulled from the database
    rather than against a specification.
"""
from __future__ import annotations

import re

# ── Detection ────────────────────────────────────────────────────────────────
#
# Two heuristics were tried and **both were wrong**, which is worth recording
# because the third looks similar and is not:
#
#   1. A hand-written class of combining marks flagged **46%** of the corpus.
#   2. Adding "medial before a consonant" flagged **82%**, and flagged
#      `နေပြည်တော်` — a correctly encoded place name. `ခြင်း` is `ခ`+`ြ`+`င`+`်`+`း`,
#      all valid.
#
# **A heuristic that flags most of the corpus is not a detector.** What is left
# cannot occur in correct Unicode:
#
#   - `ɪ` `ɫ` and the phonetic-extension block — Latin letters that appear when a
#     Zawgyi font's glyphs were mapped to the wrong code points.
#   - `း` (visarga) immediately before `ေ`. Unicode stores `ေ` first, always.
_LATIN_INTRUDERS = re.compile(r"[\u026a\u026b\u0270\u1d00-\u1d7f]")
_VISARGA_BEFORE_E = re.compile(r"[\u1038][\u1031]")


def is_suspect(text: str) -> bool:
    """True when this text carries markers that cannot occur in Unicode Burmese.

    Narrow on purpose. It decides only whether to *label* a row — nothing is
    rewritten on the strength of it.
    """
    if not text:
        return False
    return bool(_LATIN_INTRUDERS.search(text) or _VISARGA_BEFORE_E.search(text))


# ── Unicode → Zawgyi, for a search query only ────────────────────────────────
#
# Zawgyi stores these before their consonant; Unicode stores them after. One
# pass per rule, in this order, with no convergence loop — see the module
# docstring for what the loop did.
_E     = "\u1031"      # ေ
_CONSONANT = "\u1000-\u1021"

# **Only the ya-yit `ြ` moves in front of its consonant.** `ျ` (ya-pin),
# `ွ` (wa-swe) and `ှ` (ha-hto) stay where Unicode puts them.
#
# Measured 2026-10-01 over 6.9 M characters of the corpus, counting each
# candidate spelling of the same word:
#
#     ပြောင်   ေြပာင် 312   ေပြာင် 1   ြေပာင် 0
#     မြောက်   ေြမာက် 386   ြေမာက် 1
#     ကျော်    ေကျာ် 452    ျေကာ် 0
#     မြန်မာ   ြမန်မာ 875   (no ေ — the medial still moves)
#
# The old `_MEDIALS` held `ြ ွ ှ` and was used for BOTH jobs. That is wrong in
# two directions at once, and only one of them was visible:
#
#   * it **omitted `ျ`** from the `ေ` rule, so `to_zawgyi("ကျော်")` returned the
#     word **unchanged** — and `ကျော်` / `ကျောင်း` / `ချောင်` are among the most
#     common syllables in Burmese. The OR search never reached the Zawgyi
#     spelling, which occurs **452** times in the corpus. That is the same miss
#     the module was written to fix (`ြပန်လည်`, 118 articles) and it was still
#     there for `ျ`.
#   * it **included `ွ` and `ှ`**, which do not move, so those were reordered
#     into a spelling that occurs nowhere.
_MOVING_MEDIAL = "\u103c"                        # ြ — moves before the consonant
_ALL_MEDIALS   = "\u103b\u103c\u103d\u103e"      # ျ ြ ွ ှ — read, never moved

# `ေ` moves in front of the consonant it belongs to, **and in front of a `ြ`
# that is already there**: `သတိပေး` → `သတိေပး`, `ပြောင်` → `ေြပာင်`.
# The consonant may carry any medial, so the pattern allows one.
_ZA_E = re.compile(rf"([{_CONSONANT}][{_ALL_MEDIALS}]?)({_E})")
# …and `ြ` moves before its base consonant: `ပြန်` → `ြပန်`.
_ZA_MEDIAL = re.compile(rf"([{_CONSONANT}])([{_MOVING_MEDIAL}])")

# Latin intrusions → the Burmese they stand for. Read off real rows: `ရɪာ` is
# `ရွာ` and `ေရɫ` is `ရွှေ`, so `ɪ` is `ွ` and `ɫ` is `ွ`+`ှ`.
_INTRUDERS = {"\u026a": "\u103d", "\u026b": "\u103d\u103e"}


def to_zawgyi(text: str) -> str:
    """Best-effort Unicode → Zawgyi, for searching the other half of the column.

    **`ေ` moves first, then `ြ`.** Measured 2026-10-01: with the medial rule
    first, `ပြောင်` came out as `ြေပာင်`, which occurs **0** times in the
    corpus, instead of `ေြပာင်`, which occurs **312**. Running `ေ` first lets
    the `ြ` rule then move the medial in front of a consonant that already has
    its `ေ`, which is the order the paper actually prints.

    Only the ordering rules are applied; the Latin intrusions are NOT
    re-created, because inventing `ɪ` would be guessing at a broken mapping and
    a search does not need it — a row that holds `ɪ` holds the surrounding
    Burmese too.
    """
    if not text:
        return text
    text = _ZA_E.sub(lambda m: m.group(2) + m.group(1), text)
    text = _ZA_MEDIAL.sub(lambda m: m.group(2) + m.group(1), text)
    return text


def to_unicode(text: str) -> str:
    """Zawgyi → Unicode, **one pass, no loop**.

    Provided for inspecting a row by hand — it is deliberately NOT wired into the
    read path. The rules are the inverse of `to_zawgyi`'s and are exact only for
    text that is cleanly Zawgyi; on text that is already Unicode they reorder it
    into nonsense. `is_suspect` is not a good enough gate to run this
    automatically, so nothing does.

    Measured 2026-10-01, `to_unicode` on **valid** Unicode: 3 of 6 test strings
    came back changed — `နေပြည်တော်` → `နပေညြ်တော်`, `…ရွာသွန်းခြင်း` →
    `…ရွာသနွ်းခငြ်း`. **This is why it stays unwired**, and it is measured
    rather than assumed.
    """
    if not text:
        return text
    for latin, burmese in _INTRUDERS.items():
        text = text.replace(latin, burmese)
    # `ြ` back after its consonant, then `ေ` back after the consonant it follows.
    text = re.sub(rf"([{_MOVING_MEDIAL}])([{_CONSONANT}])",
                  lambda m: m.group(2) + m.group(1), text)
    text = re.sub(rf"([{_E}])([{_CONSONANT}][{_ALL_MEDIALS}]?)",
                  lambda m: m.group(2) + m.group(1), text)
    return text
    return text


# **A `ေ` that is not preceded by a consonant or a medial is illegal Unicode.**
# Zawgyi writes the vowel sign before its consonant (`ေနြပည်ေတာ်`); Unicode
# writes it after (`နေပြည်တော်`). So this counts the strongest single marker
# there is, and it needs **all four medials** — `ျ ြ ွ ှ` (U+103B–103E). Leaving
# `ျ` out was the bug in the conversion rules above, and the same omission here
# made the detector flag ordinary Unicode: `ကျော်` (`က ျ ေ ာ ်`) has its `ေ`
# after `ျ`, so without `ျ` in the class every `ကျော်`/`ကျောင်း`/`ချောင်` looked
# like Zawgyi and **28% of the corpus was flagged**.
_ZG_ALL_MEDIALS = "\u103b\u103c\u103d\u103e"
_ZG_BAD_E = re.compile(rf"(?<![{_CONSONANT}{_ZG_ALL_MEDIALS}])\u1031")

# Per 100 characters. Measured 2026-10-01 over the corpus, per source:
#
#     မြန်မာ့အလင်း 2026-09-29 (read by vision)   n=42   p50 0.00  p90 0.00  max 0.00
#     ကြေးမုံ 2026-09-29      (PDF text layer)   n=328  p50 0.00  p90 2.87  max 6.21
#     ကြေးမုံ 2026-09-30      (PDF text layer)   n=416  p50 0.00  p90 2.52  max 4.34
#
# The vision output scores **exactly zero on every row**, so 1.0 sits well clear
# of both: ordinary Unicode reaches 0.28 at worst, real Zawgyi rows run 2.5–6.2.
_ZG_THRESHOLD = 1.0


def zawgyi_score(text: str) -> float:
    """How Zawgyi-encoded this text looks, per 100 characters. 0.0 when clean."""
    if not text:
        return 0.0
    return len(_ZG_BAD_E.findall(text)) / len(text) * 100


def looks_like_zawgyi(text: str) -> bool:
    """True when `text` is Zawgyi rather than Unicode.

    **Detection only — nothing here converts anything.** `to_unicode` stays
    unwired for the measured reason in its own docstring (it damages valid
    Unicode 3 times out of 6), so the honest use of this is to *say* that a row
    could not be read, not to rewrite it.
    """
    return zawgyi_score(text) > _ZG_THRESHOLD


def variants(query: str) -> list[str]:
    """The query plus its Zawgyi form, deduplicated, for an OR search.

    This is the whole point of the module: it is what makes the 118 articles
    containing `ြပန်လည်` reachable from a Unicode search for `ပြန်လည်`.
    """
    q = (query or "").strip()
    if not q:
        return []
    out = [q]
    other = to_zawgyi(q)
    if other and other != q:
        out.append(other)
    return out


def label(text: str) -> str:
    """Mark a suspect string instead of rewriting it.

    Returns the text unchanged with a short marker appended, so a caller can show
    the user *"this row is in the other encoding"* rather than either showing
    mojibake silently or guessing at a conversion.
    """
    if not text or not is_suspect(text):
        return text
    return f"{text} ⚠️(encoding)"
