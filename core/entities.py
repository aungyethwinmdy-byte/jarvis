"""Pull the named people and bodies out of state-paper article text.

WHY THIS EXISTS

    The question that started it, 2026-09-30, in the user's own words:

        "ဒီနေ့ မြန်မာ့အလင်းသတင်းစာထဲ ဘယ်ဝန်ကြီးတွေ ပါသလဲ"

    *"Which ministers appear in today's Myanma Alinn."* That is not a keyword
    question — no single keyword answers it, and answering "ဝန်ကြီး: 775 articles"
    is not an answer. It is a **distinct-entity** question: read the day, find
    every minister named, list them. A keyword search cannot do that and the
    model must not guess at names, because a name spoken wrongly is worse than
    a name not spoken.

WHAT IT MATCHES

    Burmese prints a titled person as **title + name**, and the title is the
    anchor. Measured 2026-09-30 over the 2026-09-29 ကြေးမုံ edition:

        ပြည်ထောင်စုဝန်ကြီး ဒေါက်တာသက်သက်ဇင်သည် …
        ဒုတိယဝန်ကြီး ဦးမျိုးမြင့်က …
        ဝန်ကြီး ဦးဟန်ဝင်းအောင်က …

    so the pattern is a known title followed by a Burmese personal name. The
    name may begin with an honorific the paper attaches to the person rather
    than the office — `ဦး` (Mr), `ဒေါ်` (Ms), `ဒေါက်တာ` (Dr) — which is kept,
    because that is how the paper names them and how a reader recognises them.

THE TWO TRAPS, BOTH MEASURED

    1. **The word after the title is often not a name.** In
       `ဝန်ကြီးဌာန` (ministry) and `ဝန်ကြီးချုပ်` (chief minister) the title is
       a prefix of a longer word; in `ဝန်ကြီး သည်` it is followed by a particle.
       Measured: of 30 raw `ဝန်ကြီး` + next-token matches, **the top four were
       ဌာန, ချုပ်, နှင့်, များ** — every one a false positive. So there is a stop
       list, and a name must survive it.

    2. **Burmese glues the case particle onto the name.** `ဦးမျိုးမြင့်က`,
       `ဒေါက်တာသက်သက်ဇင်သည်`, `ဦးတင်ဦးလွင်နှင့်` — the trailing `က` / `သည်` /
       `နှင့်` is grammar, not part of the name. Left attached, the same person
       appears three times under three spellings. They are stripped.

    This module does not try to be a Burmese NLP pipeline. It extracts what the
    title anchors, refuses to invent the rest, and every extraction it returns
    carries the sentence it came from so the caller can show its work.
"""
from __future__ import annotations

import re
from collections import Counter

# Titles, longest first so `ပြည်ထောင်စုဝန်ကြီး` is not read as `ဝန်ကြီး` plus a
# stray prefix. `ဒုတိယဝန်ကြီး` (deputy minister) is kept distinct from
# `ဝန်ကြီး` on purpose: the user asked about ministers, and flattening a deputy
# into a minister would overstate what the paper said.
_TITLES: tuple[tuple[str, str], ...] = (
    # The two top state offices, added 2026-09-30 after the owner asked
    # *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာမှာ နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့
    # သတင်းတွေ ရှိလား"* and this module returned `[]` for the president and both
    # vice-presidents — the talkers knew only ministerial ranks. Measured over
    # the 25 editions of September 2026: `နိုင်ငံတော်သမ္မတ` occurs 139 times in
    # the database and `ဒုတိယသမ္မတ` 27, so the text was there to find and the
    # only defect was the rank list. They sit **above** the ministerial entries
    # because a longer rank must be tried first.
    ("နိုင်ငံတော်သမ္မတ", "နိုင်ငံတော်သမ္မတ"),
    ("နိုင်ငံတော် သမ္မတ", "နိုင်ငံတော်သမ္မတ"),
    # **No bare `သမ္မတ` entry, deliberately.** The first version of this list
    # had one, and a survey of six editions (2026-09-13/16/20/23/24/28) showed
    # why it cannot work: every bare occurrence was either `…သမ္မတနိုင်ငံ`
    # (“republic” — `ဘယ်လာရုစ်သမ္မတနိုင်ငံ`, `ဆိုရှယ်လစ်သမ္မတနိုင်ငံ`), a foreign
    # head of state (`သမ္မတ ပရာဘိုဝို`, `သမ္မတထရမ့်`), or a vocative
    # (`အဆွေတော် သမ္မတကြီးခင်ဗျား`). **Not one referred to Myanmar's president
    # by a name** — the paper always writes the full `နိုင်ငံတော်သမ္မတ` for him.
    # Keeping the entry therefore bought no correct answer and produced four
    # wrong ones, so the office is anchored on the full form only. The guard
    # below is kept as the safety net for the spaced variant.
    ("ဒုတိယသမ္မတ", "ဒုတိယသမ္မတ"),
    ("ဒုတိယ သမ္မတ", "ဒုတိယသမ္မတ"),
    ("ပြည်ထောင်စုဝန်ကြီး", "ပြည်ထောင်စုဝန်ကြီး"),
    ("ပြည်ထောင်စု ဝန်ကြီး", "ပြည်ထောင်စုဝန်ကြီး"),
    ("ဒုတိယဝန်ကြီး", "ဒုတိယဝန်ကြီး"),
    ("ဒုတိယ ဝန်ကြီး", "ဒုတိယဝန်ကြီး"),
    ("ဝန်ကြီးချုပ်", "ဝန်ကြီးချုပ်"),
    # Measured 2026-10-01 over the corpus: `ဗိုလ်မှူးကြီး` ("Colonel") is a rank
    # the state papers print constantly — 8 occurrences in a single pass — and
    # it sits *between* a ministerial title and the person's name:
    #
    #     လုံခြုံရေးနှင့်နယ်စပ်ရေးရာဝန်ကြီး ဗိုလ်မှူးကြီး ညီလန်းချိုက …
    #
    # Without this entry the walk stopped at `ဝန်ကြီး`, took the next token, and
    # listed a person called `ဗိုလ်မှူးကြီး`. Refusing it in `_NOT_A_NAME` alone
    # would have been worse than the bug: a real regional minister would vanish
    # from the answer. Anchoring it extracts `ညီလန်းချို`, which is the person
    # the paper is actually naming.
    ("ဗိုလ်မှူးကြီး", "ဗိုလ်မှူးကြီး"),
    ("ဝန်ကြီး", "ဝန်ကြီး"),
)

# Ranks that *contain* `ဝန်ကြီး` as a suffix. When the short form is found, a
# match on one of these immediately before it means the text was really the
# longer rank — skip, do not add a phantom `ဝန်ကြီး`. Derived from the `_TITLES`
# spellings above rather than typed by hand: `ပြည်ထောင်စု` is 11 codepoints, not
# the 7 a reader would guess, so a hand-picked window silently matched nothing.
# Whitespace is allowed between the rank and `ဝန်ကြီး` (`ပြည်ထောင်စု ဝန်ကြီး`).
_SHORT_TITLE_GUARD_RE = re.compile(r"(ပြည်ထောင်စု|ဒုတိယ)\s*$")

# (No `_BARE_PRESIDENT_GUARD_RE`: there is no bare `သမ္မတ` entry to guard.
# A survey of six September editions — see the note on `_TITLES` — found every
# bare occurrence was `…သမ္မတနိုင်ငံ` (“republic”), a foreign head of state, or
# a vocative. The office is anchored on `နိုင်ငံတော်သမ္မတ` alone.)

# Honorifics the paper writes in front of a personal name. Kept with the name —
# "ဒေါက်တာ သက်သက်ဇင်" is how the person is named, not simply "သက်သက်ဇင်".
_HONORIFICS = ("ဒေါက်တာ", "ဦး", "ဒေါ်", "ဆရာတော်", "နိုင်ဦး")

# Zawgyi spellings of the same honorific, and the OCR-mangled forms. Measured
# 2026-09-30: `ဒေက်တာ` and `ဒေါက်တာ` both occur, for the same word, within one
# edition — the pipeline mixes encodings. Left alone, one person is listed twice
# under two spellings of "Dr". Normalised before anything else compares them.
_HONORIFIC_FIXES = {
    "ဒေက်တာ": "ဒေါက်တာ",
    "ေဒါက္တာ": "ဒေါက်တာ",
    "ဦး": "ဦး",
}

# The same idea applied to a personal name, and it exists because the pipeline
# mangles names the way it mangles honorifics. Measured 2026-09-30 over the
# September editions: the vice-president born `ဦးညိုစော` also appears as
# `ဦးညိမ်းဇော်` and `ဦးညိမ်းစော`, always in the `ဒုတိယသမ္မတ` slot — the OCR
# confuses `ို` with `ိမ်း` and `စော` with `ဇော`. Keyed only for names where the
# variants were confirmed to be one person by their office; **this is not a
# general normaliser.** `_name_key` cannot do this job — it strips the killer
# and visarga, and these variants differ by whole syllables, so a rule loose
# enough to merge them would merge unrelated people.
_NAME_FIXES = {
    "ညိမ်းဇော်": "ညိုစော",
    "ညိမ်းစော": "ညိုစော",
    # Measured 2026-09-13: the paper breaks the line inside her name —
    # `ဒုတိယသမ္မတ ဒေါ်နန်း နီနီအေး` — so the first syllable came back alone.
    "နန်း": "နန်းနီနီအေး",
}

# The word right after a title is very often NOT a name. Measured 2026-09-30:
# the four most frequent `ဝန်ကြီး` + next-token pairs were ဌာန, ချုပ်, နှင့်, များ
# — the ministry word, the chief-minister word, a conjunction and a pluraliser.
# Every one of them reads as a person if it is not refused.
#
# The two entries at the end are **sentence fragments, not tokens**, and they
# are here because the reader window can return them as one unbroken string.
# `…ဝန်ကြီးဌာန ပြည်ထောင်စုဝန်ကြီး ဦးဆောင်သည့် အမျိုးသားစည်းလုံးညီညွတ်ရေးနှင့်
# ငြိမ်းချမ်းရေးဖော်ဆောင်မှု ဗဟိုကော်မတီ` is 145 characters with **no space in
# it at all** — the pipeline's OCR glues a whole headline together — so the
# `ဦးဆောင်…` guard above never saw the word it was written for and the run was
# read as a person. Verified 2026-09-30: the president's own article on that
# edition yielded a person called `ဦးဆောင်သည့်အမျိုးသားစည်းလုံးညီညွတ်ရေးနှင့်`.
# Rewriting the guards as prefixes is the general fix; whether the walk should
# even count these long forms is queued as an open question, not decided here.
_NOT_A_NAME = {
    "ဌာန", "ဌာန၊", "ဌာနက", "ဌာနသည်", "ဌာနများ", "ဌာနပိုင်အဖြစ်",
    "ချုပ်", "ချုပ်က", "ချုပ်နှင့်",
    "သည်", "က", "ကို", "၏", "မှ", "တွင်", "နှင့်", "များ", "များနှင့်",
    "များနှင့်အတူ", "တို့က", "တို့ကလည်း", "တို့သည်", "နှင့်အတူ",
    "အဖွဲ့", "အစည်းအဝေး", "ရုံး", "သို့", "ဖြစ်သည်", "လည်း", "နှင့်အညီ",
    # Measured 2026-09-30 over the whole month: `…ဝန်ကြီး နှင့်အဖွဲ့` — "the
    # minister and his delegation" — matched 19 times and read as a person
    # called "နှင့်အဖွဲ့" (and-delegation). The delegation word is the tell.
    "နှင့်အဖွဲ့", "နှင့်အဖွဲ့ဝင်များ", "အဖွဲ့ဝင်များ", "နှင့်အဖွဲ့က",
    "နှင့်တာဝန်ရှိသူများ", "နှင့်ဌာနဆိုင်ရာများ", "နှင့်တာဝန်ရှိသူ",
    "နှင့်အတူလိုက်ပါ", "အဖွဲ့ချုပ်", "နှင့်အဖွဲ့များ",
    # Measured 2026-09-30 over the September editions, after the presidential
    # ranks were added: these are the tokens that followed `ဒုတိယသမ္မတ` most
    # often without a name being present — `ဒုတိယသမ္မတ အမှာစကား ပြောကြားရာတွင်`
    # (“the vice-president, in his address”) read as a person called
    # “အမှာစကား” (address), and `နိုင်ငံတော်သမ္မတ ဦးဆောင်သည့်` (“led by the
    # president”) as one called “ဦးဆောင်သည့်”. Both are grammar.
    "အမှာစကား", "မိန့်ခွန်း", "ဦးဆောင်သည့်", "ဦးဆောင်လျက်", "ဦးဆောင်မှု",
    "ရုံး", "ရာထူး", "အစိုးရ", "တာဝန်", "ခန့်အပ်", "အဆိုပြု",
    # Measured 2026-09-29 in ကြေးမုံ page 13: `တရုတ်ပြည်သူ့သမ္မတနိုင်ငံသံရုံး`
    # (“the embassy of the People's Republic of China”) — the bare `သမ္မတ`
    # entry read the tail as a titled person called “နိုင်ငံသံရုံး” (national
    # embassy). `သမ္မတနိုင်ငံ` is the *country*, not the office, and a country's
    # name is exactly what makes an embassy.
    "နိုင်ငံသံရုံး", "သံရုံး", "စစ်သံရုံး", "သမ္မတနိုင်ငံ", "နိုင်ငံတော်",
    # Measured 2026-09-13/16/24/28 over the September editions, after the state
    # offices were added. These are what followed `နိုင်ငံတော်သမ္မတ` when the
    # sentence carried no name at all — the paper's ordinary prose about the
    # office. `ရုံးတော်` and `ရုံးတော်၌` are the President's Office (also handled
    # by the prefix guard); the rest are verbs and particles of a reported
    # instruction: “…လမ်းညွှန်ခဲ့သည့်” (“the course the President directed”),
    # “…ကြည့်ရှုစစ်ဆေး” (“inspected”), “…တာဝန်ထမ်းဆောင်” (“serves”).
    "ရုံးတော်", "ရုံးတော်၌", "ရုံးပြောရေးဆိုခွင့်ရှိသူ",
    "လမ်းညွှန်ခဲ့သည့်", "လမ်းညွှန်", "ပြောကြားခဲ့", "ကြည့်ရှုစစ်ဆေး",
    "တာဝန်ထမ်းဆောင်", "တာဝန်ထမ်းဆောင်ချိန်", "တာဝန်ထမ်းဆောင်သည့်",
    "ကြီးခင်ဗျား", "ကြီးက", "အဖြစ်", "နိုင်ငံ", "နိုင်ငံ၌", "များဖြစ်ကြသည့်",
    "ပြောကြားခဲ့သည့်", "နိုင်ငံသို့", "နိုင်ငံဆိုင်ရာ", "ရုံးမှ",
    # The un-spaced forms the OCR actually produces. `_NOT_A_NAME` is matched
    # exactly, and the pipeline glues a whole phrase into one run, so the
    # spaced entry above never fires. Measured 2026-09-30 — see the note at the
    # top of this table.
    "ဦးဆောင်သည့်အမျိုးသားစည်းလုံးညီညွတ်ရေးနှင့်",
    "ဦးဆောင်သည့်အမျိုးသားစည်းလုံးညီညွတ်ရေး",
    # …and one more from the same edition, which is a *compound verb* rather
    # than a fragment: `…ပြည်ထောင်စု ဝန်ကြီး အစားထိုးခန့်အပ်ခြင်းနှင့်` — "the
    # substitution and appointment of a union minister". Measured 2026-09-30:
    # this listed a "person" called `အစားထိုးခန့်အပ်ခြင်း` in the answer to the
    # owner's own test question. `ခန့်အပ်` is already refused on its own, but the
    # paper writes it inside a longer word, so the refusal has to exist in the
    # longer form too.
    "အစားထိုးခန့်အပ်ခြင်း", "အစားထိုးခန့်အပ်ခြင်းနှင့်", "အစားထိုးခန့်အပ်",
    # The subject-marker form of the guard above. Measured 2026-09-30:
    # `ပြည်ထောင်စုဝန်ကြီး အဖြစ်တာဝန်ထမ်းဆောင်ခဲ့သူ` — "he who served as a union
    # minister" — the `အဖြစ်` guard stops at the space, this does not.
    "အဖြစ်တာဝန်ထမ်းဆောင်ခဲ့သူ", "အဖြစ်တာဝန်ထမ်းဆောင်ခဲ့",
    # `ဟောင်း` ("former"), which qualifies a rank rather than naming a person.
    # Measured 2026-09-30: `မေလးရှားဝန်ကြီးချုပ်ဟောင်း` — "former Malaysian prime
    # minister" — was read as a prime minister called `ဟောင်း` and shown in the
    # owner's own answer. The rank word is glued to the front, so the name regex
    # sees only the qualifier. Refusing the whole run is right here: `ဟောင်း`
    # alone is never a Burmese personal name.
    "ဟောင်း", "ဟောင်း၊", "ဟောင်းက", "ဟောင်းသည်", "ဟောင်းနှင့်",
    # Measured 2026-10-01 over the whole corpus (6,896 readable articles, 150
    # distinct extracted names), after the owner's vice-president question came
    # back naming a person called `ထံမှ`:
    #
    #   နိုင်ငံတော်သမ္မတ **ထံမှ** ပြည်ထောင်စု ဝန်ကြီးအဖြစ် ခန့်အပ်လိုကြောင်း
    #       "appointed as a union minister **from** the State President"
    #   ပြည်နယ်ဝန်ကြီးချုပ်**၏ဇနီး**က …            "the **wife of** the chief minister"
    #   ဒုတိယဝန်ကြီး**အဆင့်** ပဉ္စမအကြိမ် …          "**deputy-minister level**, 5th"
    #
    # All three are grammar glued to the rank, and all three were listed as
    # people. The first two are also the same shape as the `ဟောင်း` entry above:
    # the rank word is attached to the front, so the name regex sees only the
    # tail.
    "ထံမှ", "၏ဇနီး", "ဇနီး", "အဆင့်", "အဆင့်၊",
    # …and the fourth from the same measurement is a **rank, not a name** —
    # but it is refused here *and* added to `_TITLES` below, which is the
    # difference from `ဟောင်း`. Measured: `လုံခြုံရေးနှင့်နယ်စပ်ရေးရာဝန်ကြီး
    # ဗိုလ်မှူးကြီး ညီလန်းချိုက` — the Bago minister, **Colonel** Nyi Lan Cho.
    # Refusing it alone would have dropped a real minister from the answer, so
    # the title table anchors it and the real name comes out instead.
    "ဗိုလ်မှူးကြီး",
}

# Trailing grammar glued onto a Burmese name. Longest first, so `နှင့်အတူ` is
# tried before `နှင့်`. The sentence terminator `။` and the clause mark `၊` are
# in the list because the name regex is greedy and runs straight through them —
# measured 2026-09-30: `ဒေါက်တာသက်သက်ဇင်သည်။` came back whole, and the same
# person was then counted twice under two strings.
_SUFFIXES = ("နှင့်အတူ", "နှင့်", "သည်။", "သည်", "တို့", "ကလည်း", "လည်း", "က",
             "ကို", "၏", "မှာ", "မှ", "တွင်", "၊", "။",
             # The accusative `အား` and the locative `၌`, measured 2026-09-24:
             # `ဦးမင်းအောင်လှိုင်အား` (“to U Min Aung Hlaing”) came back with the
             # particle attached and was tallied as a second person.
             "အား", "၌", "ထံ", "အတွက်")

# Burmese personal names run two to five syllables with no spaces. The range is
# generous on the low end because a two-syllable name is common (ဦးစော), and on
# the high end because compound names exist. **Greedy**, because the input to
# it is already cut at the sentence boundary by `_NAME_END` — an earlier
# non-greedy version matched two characters and every name came back truncated.
_NAME_RE = re.compile(
    r"[\u1000-\u109F][\u1000-\u109F\u103A\u1039\u103B-\u103E]{1,24}")
# A name stops at any of these — it is the cue the greedy match kept running
# through. Splitting on them first is more reliable than a lookahead on a
# script this dense.
_NAME_END = re.compile(r"[၊။\s]")

# A name is at least two syllables and not a bare honorific.
_MIN_SYLLABLES = 2

# Countries that the state papers print directly after a rank — “the President
# [of] Vietnam and Cambodia”, “US President Trump”. A country is never the name
# of the person the rank belongs to, so it is refused rather than guessed at.
# Measured 2026-09-13/16/24/28, the four that actually occurred plus the
# neighbours named in the same editions.
_COUNTRIES = {
    "ဗီယက်နမ်", "ကမ္ဘောဒီးယား", "လာအို", "ထိုင်း", "တရုတ်", "အိန္ဒိယ",
    "ဘင်္ဂလားဒေ့ရှ်", "ဂျပန်", "ကိုရီးယား", "ရုရှား", "အမေရိက", "အေမရိက",
    "အင်ဒိုနီးရှား", "မလေးရှား", "စင်္ကာပူ", "ဖိလစ်ပိုင်", "နီပေါ", "သီရိလင်္ကာ",
    "ပါကစ္စတန်", "ဆားဗီးယား", "ဆာဗီးယား", "အီရန်", "အစ္စရေး", "ပါလက်စတိုင်း",
    "အီဂျစ်", "တူရကီ", "ပြင်သစ်", "ဂျာမနီ", "ဗြိတိန်", "ဩစတြေးလျ", "ကနေဒါ",
    "ဘရာဇီး", "တောင်အာဖရိက", "ဆော်ဒီအာရေဗျ", "ကာတာ", "ကူဝိတ်", "အိုမန်",
}


def _strip_suffix(name: str) -> str:
    """Remove the case particle Burmese glues onto the name.

    Loops, because more than one particle can be attached at once —
    `သက်သက်ဇင်သည်။` carries the subject marker *and* the terminator, and one
    pass leaves the other behind.
    """
    changed = True
    while changed and name:
        changed = False
        for suf in _SUFFIXES:
            if len(name) > len(suf) + 4 and name.endswith(suf):
                name = name[: -len(suf)]
                changed = True
                break
    return name


def _split_honorific(name: str) -> tuple[str, str]:
    """('ဒေါက်တာ', 'သက်သက်ဇင်') — or ('', name) when there is none.

    A mangled honorific is repaired **in place**, not only when it is the whole
    string: `_HONORIFIC_FIXES` keys are the bare forms (`ဒေက်တာ`), but this
    function always sees the honorific with a name attached
    (`ဒေက်တာအေးထွန်း`). Looking up the joined string found nothing, so the
    mangled and the correct spelling stayed two different people.
    """
    for bad, good in _HONORIFIC_FIXES.items():
        if name.startswith(bad):
            name = good + name[len(bad):]
            break
    for h in _HONORIFICS:
        if name.startswith(h) and len(name) > len(h) + 2:
            return h, name[len(h):]
    return "", name


def _syllables(text: str) -> int:
    """Rough Burmese syllable count: base letters, not marks."""
    return len(re.findall(r"[\u1000-\u1021]", text))


def _name_key(name: str) -> str:
    """A comparison key for a Burmese personal name.

    Two normalisations, both measured on real rows, and both about the same
    person being reported twice:

    - **The stacked consonant is dropped.** `နိုင်ဦး` and `နိုင်းဦး` are the same
      name with the killer mark written or not; the pipeline produced both.
    - **A trailing `း` is dropped with it**, since it usually *is* the mark.

    This is deliberately narrow. It is not a general Burmese normaliser — it
    exists for the two variants seen, so it cannot silently fuse two people who
    merely resemble each other.
    """
    key = name.replace("\u103a", "")          # ္  the killer / virama
    key = key.replace("\u1038", "")           # း  visarga — the mark above
    return key.strip()


def _is_name_shape(candidate: str) -> bool:
    """Is this plausibly a personal name rather than a stray word?"""
    core = _strip_suffix(candidate)
    _hon, bare = _split_honorific(core)
    if not bare or bare in _NOT_A_NAME or core in _NOT_A_NAME:
        return False
    # A country is not a person. Measured 2026-09-16, ကြေးမုံ page 3:
    # `နိုင်ငံတော်သမ္မတ ဗီယက်နမ်နှင့် ကမ္ဘောဒီးယားနိုင်ငံ ခရီးစဉ်` — “the President's
    # Vietnam-and-Cambodia trip” — and the country came back as the name of the
    # person. A state paper names many countries directly after a rank; the
    # closed list is the same idea as the ministry glossary, one level down.
    if bare in _COUNTRIES:
        return False
    # A bare honorific is not a name — `ဒုတိယဝန်ကြီး ဒေါက်တာ` truncates to
    # `ဒေါက်တာ` when the next token is grammar, and that is not a person.
    if core in _HONORIFICS or bare in _HONORIFICS:
        return False
    if _syllables(bare) < _MIN_SYLLABLES:
        return False
    core2 = _strip_suffix(bare)
    if core2 in _NOT_A_NAME or not core2:
        return False
    # A name never begins with a connective or a pluraliser. `နှင့်` ("and") is
    # glued to the front of the next phrase in "…ဝန်ကြီး နှင့်အဖွဲ့" — the
    # minister and his delegation — and `များ` ("plural") in "…ဝန်ကြီးများက"
    # — "the ministers (subject)". Both read as people until this was added.
    if bare.startswith(("နှင့်", "တို့", "များ")):
        return False
    # A name does not contain the ministry word or a sentence particle. The
    # ranks are in here too, measured 2026-09-30: `ဒုတိယသမ္မတများဖြစ်ကြသည့် ဦးညိုစော`
    # (“the vice-presidents, U Nyio Saw”) puts the pluralised rank *before* the
    # name, and when `သမ္မတ` was added to `_TITLES` the greedy name regex read
    # `သမ္မတများဖြစ်ကြသည့်` straight back out as the president's name.
    if any(bad in bare for bad in ("ဌာန", "ချုပ်", "သတင်းစာ", "ဝန်ကြီး",
                                   "သမ္မတ")):
        return False
    return True


def find_titled_people(text: str) -> list[dict]:
    """Every `title + name` in `text`, with the sentence it came from.

    Returns a list of `{title, name, honorific, sentence}` in the order found.
    The sentence is kept so a caller can quote the paper rather than assert a
    name on its own authority.
    """
    if not text:
        return []
    out: list[dict] = []
    for title_src, title_norm in _TITLES:
        start = 0
        while True:
            i = text.find(title_src, start)
            if i < 0:
                break
            start = i + len(title_src)
            # `ဝန်ကြီးချုပ်` must not also be read as `ဝန်ကြီး` + `ချုပ်`, and
            # `ဝန်ကြီးဌာန` must not be read as `ဝန်ကြီး` at all. When the title
            # is the short form and the text continues into a longer word, skip.
            after = text[start:start + 1]
            if title_norm == "ဝန်ကြီး" and after in ("ဌ", "ချ"):
                continue
            # …and the short form must not be read out of a rank that *contains*
            # it. Measured 2026-09-30: `ပြည်ထောင်စုဝန်ကြီး` is the long form in
            # `_TITLES`, but `ဝန်ကြီး` also matched inside it, so one official
            # carrying one office was tallied three times — `ပြည်ထောင်စုဝန်ကြီး`,
            # `ဒုတိယဝန်ကြီး` and a phantom `ဝန်ကြီး`. That inflates `count`,
            # which is the sort key for "most mentioned", so the official would
            # outrank people the edition actually discussed more. The check is
            # on the **preceding** characters, which the after-check cannot see.
            #
            # The window is derived from the prefixes, not written as a number:
            # `ပြည်ထောင်စု` is 11 codepoints, not 7, so a hand-picked "6" made
            # this guard match nothing at all while looking correct. Whitespace
            # before the short form is ignored, because the paper writes both
            # `ပြည်ထောင်စုဝန်ကြီး` and `ပြည်ထောင်စု ဝန်ကြီး` (14 vs 2 in one
            # edition), and the spaced variant is a `_TITLES` entry of its own.
            if title_norm == "ဝန်ကြီး" and _SHORT_TITLE_GUARD_RE.search(
                text[:i]
            ):
                continue
            # Nothing here for a bare `သမ္မတ`: there is no such entry in
            # `_TITLES` (see the note there — a survey of six editions found it
            # never referred to Myanmar's president by name). The `…သမ္မတနိုင်ငံ`
            # and foreign-head-of-state traps are gone with the entry.
            # `သမ္မတနိုင်ငံ` is “republic”, not “president” — the same trap as
            # `ဝန်ကြီးဌာန` for `ဝန်ကြီး`, one rank higher. Measured 2026-09-29:
            # `တရုတ်ပြည်သူ့သမ္မတနိုင်ငံသံရုံး` produced a phantom person.
            if title_src == "သမ္မတ" and text[start:start + 4] == "နိုင်ငံ":
                continue
            # …and the **mirror** trap, which the office prose produces: the rank
            # is a *prefix* of a longer institutional word. `နိုင်ငံတော်သမ္မတရုံးတော်`
            # (“the President's Office”) and `နိုင်ငံတော်သမ္မတရုံး` are body names,
            # not `title + name`, and the tail was being read as a person called
            # `ရုံးတော်`. Measured 2026-09-24/28: 8 of the 11 “people” named by a
            # president query were this one artifact. Same rule as
            # `ဝန်ကြီးဌာန` for `ဝန်ကြီး`, so it is checked the same way — on the
            # **following** characters, which the preceding-guards cannot see.
            if title_src in ("နိုင်ငံတော်သမ္မတ", "နိုင်ငံတော် သမ္မတ") and \
                    text[start:start + 1] == "ရ":
                continue
            if title_src in ("ဒုတိယသမ္မတ", "ဒုတိယ သမ္မတ") and \
                    text[start:start + 1] == "ရ":
                continue
            rest = text[start:start + 40].lstrip()
            # **The paper puts a space between an honorific and the name** —
            # `ပြည်ထောင်စုဝန်ကြီး ဒေါက်တာ မောင်သင်းနှင့်`. Cutting at the first
            # whitespace (below) then left only `ဒေါက်တာ`, `_is_name_shape`
            # refused it as a bare honorific, and the minister was **missing
            # from the answer entirely** — measured 2026-09-30 on the owner's
            # own ကြေးမုံ test question, where `ဒေါက်တာ မောင်သင်း` (page 7) was
            # named as a union minister six times but never listed.
            #
            # So when the run up to the first space is *exactly* an honorific,
            # the space belongs inside the name and is closed up. This is not a
            # general "allow spaces in names" rule: a name is written unspaced
            # (`ဦးခင်မောင်ရီ`), so joining any two words would fuse a name to the
            # verb after it. The honorific list is the tell, and it is short
            # and measured.
            _head = _NAME_END.search(rest)
            if _head and rest[:_head.start()] in _HONORIFICS:
                join_to = _head.end()
                _tail = _NAME_END.search(rest, join_to)
                nxt = rest[join_to:_tail.start()] if _tail else rest[join_to:]
                if nxt:
                    rest = rest[:_head.start()] + nxt
            # Cut at the first sentence or clause mark. The name regex is
            # greedy and the Burmese name range includes the particle letters,
            # so `…သက်သက်ဇင်သည်။` matched as one token until this ran — which
            # made the same person appear twice under two spellings.
            cut = _NAME_END.search(rest)
            if cut:
                rest = rest[:cut.start()]
            m = _NAME_RE.match(rest)
            if not m:
                continue
            raw = m.group(0)
            if not _is_name_shape(raw):
                continue
            core = _strip_suffix(raw)
            honorific, bare = _split_honorific(core)
            if not bare:
                continue
            sent = _sentence_around(text, i)
            out.append({"title": title_norm, "name": bare,
                        "honorific": honorific, "sentence": sent})
    return out


def _sentence_around(text: str, at: int, window: int = 140) -> str:
    """A readable slice of the text around an offset."""
    start = max(0, at - window // 2)
    end = min(len(text), at + window)
    slice_ = text[start:end].strip()
    return re.sub(r"\s+", " ", slice_)


def people_in(articles: list[dict], limit: int = 20,
              rank: str = "") -> list[dict]:
    """The distinct titled people across many articles, most-mentioned first.

    **Merged by person, not by title string.** Measured 2026-09-30: the same
    official appears as `ဒုတိယဝန်ကြီး ဒေါက်တာအေးထွန်း`, `ဝန်ကြီး ဒေါက်တာအေးထွန်း`
    and `ပြည်ထောင်စုဝန်ကြီး ဦးတင်ဦးလွင်` in the same edition, because a paper
    varies the office by context. Keyed on the title string he would be listed
    three times and the user would count three people. So the identity is the
    **name**, the titles are collected onto one entry, and the strongest (the
    most senior, longest form) is what is reported.

    Each entry carries `title`, `name`, `honorific`, `titles` (every form seen),
    `count`, and the article it first appeared in.

    **`rank` filters on every title the person was ever given, not on the
    reported one.** Measured 2026-09-30: asked *"ပြည်ထောင်စုဝန်ကြီး ဘယ်သူတွေ"*
    (which *union* ministers) the plain list answered with 12 names covering
    three different offices — one of them carrying `ဒုတိယဝန်ကြီး` in the
    strongest slot. The user asked about one office and got three. Matching on
    `titles` rather than `title` matters for the person the paper names both
    ways (`ဦးအေးကျော်` is `ဝန်ကြီးချုပ်` **and** `ဒုတိယဝန်ကြီး`): asking either
    office should find him, and the reported title is a display choice, not a
    fact about which office he holds.

    **`rank` may be several offices at once.** Measured 2026-09-30 the owner
    asked *"နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့ သတင်းတွေ ရှိလား"* — one
    question, two offices, and the president is not a vice-president, so a
    single `rank` can only ever answer half of it. A comma-separated string or
    an iterable is read as a set; matching is still against `titles`, so a
    person the paper names both ways is still listed once.
    """
    # Seniority, most senior first. The two state offices lead — a paper that
    # names the president and a minister in one sentence is telling the user
    # about the president. `ဝန်ကြီးချုပ်` outranks a union minister only within
    # a region; here it is listed after the union forms because the union forms
    # are what the user's question ("which ministers") is about.
    _RANK = ("နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ", "ပြည်ထောင်စုဝန်ကြီး",
             "ဝန်ကြီးချုပ်", "ဝန်ကြီး", "ဗိုလ်မှူးကြီး", "ဒုတိယဝန်ကြီး")

    tally: dict[tuple, dict] = {}
    for a in articles:
        text = (a.get("body_text") or a.get("summary") or "")
        if not text:
            continue
        for hit in find_titled_people(text):
            # Key on the *normalised* honorific. `ဒေါက်တာ` and the OCR-mangled
            # `ဒေက်တာ` are one word, and keying on the raw form listed one
            # person twice — measured 2026-09-30 in a single edition.
            hon = _HONORIFIC_FIXES.get(hit["honorific"], hit["honorific"])
            # …and the same for the name, where the pipeline confirmed the
            # variants belong to one person (see `_NAME_FIXES`). The reported
            # name uses the corrected spelling so the user reads one person.
            name = _NAME_FIXES.get(hit["name"], hit["name"])
            key = (hon, _name_key(name))
            slot = tally.setdefault(key, {
                "name": name, "honorific": hon,
                "titles": [], "count": 0,
                "paper": (a.get("newspaper_name") or "").strip(),
                "page": a.get("page_no"),
                "sentence": hit["sentence"],
            })
            slot["count"] += 1
            if hit["title"] not in slot["titles"]:
                slot["titles"].append(hit["title"])

    for slot in tally.values():
        slot["titles"].sort(key=lambda t: _RANK.index(t) if t in _RANK else 99)
        slot["title"] = slot["titles"][0] if slot["titles"] else ""

    rows = list(tally.values())
    if rank:
        # Accept one rank, a comma-separated list, or any iterable — see the
        # docstring: a question can name two offices and one `rank` cannot hold
        # both. Matching stays on `titles`, so asking for president and
        # vice-president together lists each person once under either office.
        if isinstance(rank, str):
            wanted = {r.strip() for r in rank.split(",") if r.strip()}
        else:
            wanted = {str(r).strip() for r in rank if str(r).strip()}
        if wanted:
            rows = [r for r in rows if wanted & set(r["titles"])]

    out = sorted(rows, key=lambda d: (-d["count"], d["name"]))
    return out[:limit]


# ── Ministries ───────────────────────────────────────────────────────────────
#
# The same question can be asked about a ministry instead of a person —
# "ဒီနေ့ ဘယ်ဝန်ကြီးဌာနတွေ ပါလဲ". A ministry is far easier to anchor than a
# person, because the word `ဝန်ကြီးဌာန` always ends it and ministries are a
# closed, known set rather than free text. But the text before it is a variable
# noun phrase (`စိုက်ပျိုးရေး၊ မွေးမြူရေးနှင့် ဆည်မြောင်းဝန်ကြီးဌာန`), so this
# matches against the **known list** rather than trying to parse the phrase —
# a match against a fixed list cannot invent a ministry that does not exist.

# Every union ministry named in the September 2026 state papers, measured
# 2026-09-30 by frequency over both editions. This is a glossary, which is the
# thing this project has wanted since the name-in-summary incident (see
# MEMORY.md): a position the paper prints, spelled the way the paper spells it.
MINISTRIES: tuple[str, ...] = (
    "စိုက်ပျိုးရေး၊ မွေးမြူရေးနှင့် ဆည်မြောင်းဝန်ကြီးဌာန",
    "စိုက်ပျိုးရေး၊ မွေးမြူရေးနှင့်ဆည်မြောင်းဝန်ကြီးဌာန",
    "သမဝါယမနှင့် ကျေးလက်ဖွံ့ဖြိုးရေးဝန်ကြီးဌာန",
    "ဒုတိယဝန်ကြီးဌာန",
    "ပြည်ထဲရေးဝန်ကြီးဌာန",
    "ကာကွယ်ရေးဝန်ကြီးဌာန",
    "နိုင်ငံခြားရေးဝန်ကြီးဌာန",
    "ပြန်ကြားရေးဝန်ကြီးဌာန",
    "ကျန်းမာရေးဝန်ကြီးဌာန",
    "ပညာရေးဝန်ကြီးဌာန",
    "ဘဏ္ဍာရေးနှင့် အခွန်ဝန်ကြီးဌာန",
    "ဘဏ္ဍာရေးနှင့်အခွန်ဝန်ကြီးဌာန",
    "ရင်းနှီးမြှုပ်နှံမှုနှင့် နိုင်ငံခြားစီးပွားဆက်သွယ်ရေးဝန်ကြီးဌာန",
    "စီးပွားရေးနှင့် ကူးသန်းရောင်းဝယ်ရေးဝန်ကြီးဌာန",
    "ဆောက်လုပ်ရေးဝန်ကြီးဌာန",
    "လျှပ်စစ်နှင့် စွမ်းအင်ဝန်ကြီးဌာန",
    "စွမ်းအင်ဝန်ကြီးဌာန",
    "လူဝင်မှုကြီးကြပ်ရေးနှင့် ပြည်သူ့အင်အားဝန်ကြီးဌာန",
    "သာသနာရေးနှင့် ယဉ်ကျေးမှုဝန်ကြီးဌာန",
    "သာသနာရေးဝန်ကြီးဌာန",
    "လယ်ယာစိုက်ပျိုးရေးနှင့် ဆည်မြောင်းဝန်ကြီးဌာန",
    "သယ်ယူပို့ဆောင်ရေးနှင့် ဆက်သွယ်ရေးဝန်ကြီးဌာန",
    "ဆက်သွယ်ရေးနှင့် သတင်းအချက်အလက်နည်းပညာဝန်ကြီးဌာန",
    "အလုပ်သမားဝန်ကြီးဌာန",
    "အလုပ်သမား၊ လူဝင်မှုကြီးကြပ်ရေးနှင့် ပြည်သူ့အင်အားဝန်ကြီးဌာန",
    "လူမှုဝန်ထမ်း၊ ကယ်ဆယ်ရေးနှင့် ပြန်လည်နေရာချထားရေးဝန်ကြီးဌာန",
    "လူမှုဝန်ထမ်းဝန်ကြီးဌာန",
    "ပြည်သူ့ကျန်းမာရေးဝန်ကြီးဌာန",
    "အမျိုးသမီးရေးရာဝန်ကြီးဌာန",
    "အားကစားရေးရာဝန်ကြီးဌာန",
    "အားကစားနှင့် လူငယ်ရေးရာဝန်ကြီးဌာန",
    "ဟိုတယ်နှင့် ခရီးသွားလာရေးဝန်ကြီးဌာန",
    "တည်ဆောက်ရေးဝန်ကြီးဌာန",
    "နယ်စပ်ရေးရာဝန်ကြီးဌာန",
)

_MINISTRY_RE = re.compile(r"([\u1000-\u109F\u1039\u103A\u103B-\u103E\u104A\u104B\s]{2,80}ဝန်ကြီးဌာန)")


def ministries_in(text: str) -> list[str]:
    """The known ministries named in `text`, longest spelling first.

    Matched against `MINISTRIES`, not extracted freely, so a malformed stretch
    of text cannot produce a ministry name that does not exist.

    **Spelling variants collapse to one entry.** The pipeline writes the same
    ministry with and without an internal space
    (`…မွေးမြူရေးနှင့် ဆည်မြောင်း…` vs `…မွေးမြူရေးနှင့်ဆည်မြောင်း…`), which in a
    count reads as two ministries. The comparison ignores whitespace, so the
    first spelling seen wins and the second is not counted again.
    """
    if not text:
        return []
    found: list[str] = []
    keys: list[str] = []

    def key(s: str) -> str:
        return re.sub(r"\s+", "", s)

    # The membership test runs on the **whitespace-free** forms of both sides,
    # not on the raw strings. Measured 2026-09-30: the paper prints
    # `ဘဏ္ဍာရေး နှင့် အခွန်ဝန်ကြီးဌာန` (space after `ရေး`) while the glossary
    # holds `ဘဏ္ဍာရေးနှင့် အခွန်ဝန်ကြီးဌာန`, and the same split appears in
    # `လူမှု ဝန်ထမ်း၊ …`. A raw substring test rejected both, so those two
    # ministries were dropped from an edition that named them. The dedupe below
    # already compared on the stripped key — the *lookup* had not.
    flat = key(text)
    for name in sorted(MINISTRIES, key=len, reverse=True):
        k = key(name)
        if k not in flat:
            continue
        # A longer, more specific spelling already matched, or this is the same
        # ministry under another spelling — either way, not a new entry.
        if any(k == existing or k in existing for existing in keys):
            continue
        found.append(name)
        keys.append(k)
    return found


def ministries_across(articles: list[dict], limit: int = 20) -> list[dict]:
    """Distinct ministries across articles, most-mentioned first.

    **Tallied on the whitespace-free key, not the spelling.** The pipeline
    writes one ministry two ways (`…နှင့် ဆည်မြောင်း…` and `…နှင့်ဆည်မြောင်း…`),
    and different articles pick different ones — so deduping inside a single
    article is not enough; the count itself has to collapse the two, or one
    ministry is reported as two with half its mentions each. The first spelling
    seen is kept as the display form.
    """
    def key(s: str) -> str:
        return re.sub(r"\s+", "", s)

    tally: Counter = Counter()
    display: dict[str, str] = {}
    for a in articles:
        text = (a.get("body_text") or a.get("summary") or "")
        for name in ministries_in(text):
            k = key(name)
            tally[k] += 1
            display.setdefault(k, name)
    return [{"name": display[k], "count": c} for k, c in tally.most_common(limit)]
