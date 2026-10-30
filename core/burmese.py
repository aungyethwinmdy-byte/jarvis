"""Burmese text matching helpers — shared by the search pipelines.

WHY THIS FILE EXISTS (2026-10-18)

    The owner asked JARVIS for `ကျောက်မျက်ပြပွဲ` (the gem emporium). Every search
    pipeline answered "မတွေ့ပါ" — the MOI index, the live site search, the
    state-paper database and the newsroom archive — while the story sat in all
    four, because they all match a query as a **contiguous substring** and the
    sources spell the event **`မြန်မာ့ကျောက်မျက်ရတနာပြပွဲ`**: the word `ရတနာ`
    rides inside the site's own name, so the query is not a substring of
    anything. The whitespace-token fallbacks never fire for this, because a
    Burmese compound is one word — there is no space to work with.

    A sub-phrase can only be a *phrase* when it spans whole syllables, and
    Burmese syllables are written as one unbroken cluster, so candidates are
    cut at cluster starts, not at arbitrary offsets. A wrong (over-split)
    boundary only produces a candidate that matches nothing and falls through —
    the fallback can afford to be wrong, being last.

    The logic lived in `core/moi_index.py` until this same day, when the
    reporter database search (`actions/reporter_news.py`) and the newsroom
    archive search (`actions/newsroom_search.py`) missed the emporium the same
    way. A second copy of the cutter would have been exactly the defect class
    this project bans, so it moved here; `moi_index.partials` is re-exported so
    its existing callers keep working unchanged.
"""
from __future__ import annotations

import re

# The comparison form for a search term — whitespace removed and lower-cased.
# The same rule `moi_client` measures on its own pages: the sources write
# `နိုင်ငံတော် သမ္မတ` and `နိုင်ငံတော်သမ္မတ` alike, and only a de-spaced haystack
# can match both.
def _plain(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


_ASAT = "\u103A"          # ် — syllable final
_VIRAMA = "\u1039"        # ္ — stacked consonant mark
_MEDIALS = "\u103B\u103C\u103D\u103E"        # ျ ြ ွ ှ
# A consonant after any of these rime marks has its own syllable already
# complete behind it — the marks themselves never start one.
_RIME_MARKS = "\u102C\u102D\u102E\u102F\u1030\u1031\u1032\u1036\u1037\u1038"


def _is_base_consonant(ch: str) -> bool:
    return "\u1000" <= ch <= "\u1021" or ch == "\u1023"


def _syllable_starts(text: str) -> list[int]:
    """Where a Burmese syllable may begin in `text`.

    A position starts a syllable when it opens with a base consonant **after**
    a syllable is already complete: the previous syllable closed on asat or
    virama, the previous char was a medial (which always attaches to the onset
    before it) or a vowel sign, or the previous char is a bare base consonant
    (a consonant with no marks ends a syllable — modern Unicode writes stacks
    with `VIRAMA`). A consonant followed directly by asat is that syllable's
    coda, never an onset — which is what keeps `ကျောက်` one cluster at the `က်`.
    """
    out = []
    for i, ch in enumerate(text):
        if not _is_base_consonant(ch):
            continue
        if i == 0:
            out.append(i)
        elif text[i + 1 : i + 2] == _ASAT:      # coda of the current syllable
            continue
        else:
            prev = text[i - 1]
            if (prev == _ASAT or prev == _VIRAMA
                    or prev in _MEDIALS or prev in _RIME_MARKS
                    or _is_base_consonant(prev)):
                out.append(i)
    return out


def partials(term: str, cap: int = 10, min_len: int = 5) -> list[str]:
    """Sub-phrases of a query, longest first then leftmost — never the whole.

    Every fragment spans whole syllable clusters from one cluster start to
    another, so `ကျောက်မျက်ပြပွဲ` yields `ကျောက်မျက်ပြ`, `ကျောက်မျက်`,
    `မျက်ပြပွဲ` … and never a mid-syllable fragment like `ျောက်မျ`. Fragments
    shorter than `min_len` codepoints are not phrases a news search needs.
    `cap` bounds how many tries the callers will pay for — each live-site try
    is one request, and locally each is one LIKE pass.
    """
    flat = _plain(term)
    if len(flat) < min_len + 1:
        return []
    bounds = _syllable_starts(flat)
    stops = bounds + [len(flat)]
    fragments: set[str] = set()
    for start in bounds:
        for stop in stops:
            if stop <= start or stop - start == len(flat):
                continue
            fragment = flat[start:stop]
            if len(fragment) >= min_len:
                fragments.add(fragment)
    # Longest first; ties read left-to-right in the query's own order.
    ranked = sorted(fragments, key=lambda f: (-len(f), flat.find(f)))
    return ranked[:cap]
