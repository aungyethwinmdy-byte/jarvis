"""Index a state-paper article into one of the owner's sections (ကဏ္ဍ).

WHY THIS EXISTS

    The owner's ask, 2026-09-30, in his own words:

        "database မှာ နိုင်ငံတော်သမ္မတသတင်းဆို နိုင်ငံတော်သမ္မတ ကဏ္ဍတစ်ခု …
         သတင်းစာမှာ ပါဝင်တဲ့ သတင်းအချက်အလက်အလိုက် ခွဲခြားသိမ်းဆည်းတဲ့ စနစ် …
         ငါက ဂျာဗစ်ကိုမေးလိုက်ရင် … နိုင်ငံတော်သမ္မတ ကဏ္ဍကို သွားပြီး
         သိမ်းဆည်းထားတဲ့ သတင်းကိုပြောပြရမယ်။"

    He wants eleven sections, the paper indexed into them, and a question
    ("today's State President news?") answered **from the section**, not from a
    keyword sweep of the whole paper.

WHERE THE SECTION IS STORED — and why it is `article_type`

    Measured 2026-09-30 against `zdsxuxwonkovuesjepfa`: the `articles` table has
    **no `section` column**, and PostgREST cannot add one (verified: no
    `exec_sql` / `exec` RPC exists, so no DDL is reachable from here).

    What it does have is `article_type`, and the database itself already treats
    that as the section field: the `newspaper_articles` view exposes
    `article_type` **as `section`** (same 7,510 rows, same distribution,
    `id`-for-`id`). Writing `article_type` is writing that view's `section`.

    It is also **free**: measured over all 7,510 rows, 7,362 are the literal
    default `'General'` and the other 148 are ad-hoc English labels
    (`Business / Market Rates`, `Front Page / Diplomatic`) concentrated on
    2026-09-01..10 and a 2024-08-31 test batch — an abandoned early experiment.
    A grep of both projects (`E:\\test\\my_reporter-main`, `E:\\Mark-LIV-main`)
    finds **no code that reads or writes `article_type` at all**, so nothing
    depends on the old values. They are backed up before the first write.

    So the section lives in the column the database already calls `section`.
    A dedicated column would be tidier and needs one line of SQL in the
    Supabase editor; this needs none, and works today.

THE RULE — measured, not guessed

    **The headline decides; the body is the fallback.** A paper's headline is
    its own statement of what a story is about, so it is consulted first, and
    every section word counts there. Only when no headline word matches is the
    body read, and there only the **section's own word** counts
    (`စီးပွားရေး`, `ပညာရေး`, …) — never the broad topical vocabulary
    (`တက္ကသိုလ်`, `ဘဏ်`, `ဆေးရုံ`). Measured 2026-09-30: over 6,722 readable
    articles the broad words match `ကျောင်း` 1,016 times and `လွှတ်တော်` 1,587
    — a third of the paper — so a body-wide sweep on those would file the whole
    edition under two sections.

    **The three offices require the office to be the subject.** Measured over
    the corpus, `နိုင်ငံတော်သမ္မတ` appears in 72 headlines and 140 bodies, so a
    rule that counts any mention files education, transport and parliament
    stories under the President. An office therefore counts only when it is
    **named in the headline**, or **named in the opening of the story** (its
    first sentence) — the two places a Burmese paper states the principal
    actor. Measured 2026-10-01: headline 72 + first sentence 44, against 22 for
    the "anywhere, twice" rule it replaced, and **every one of the 22 beyond the
    first sentence was a single parliament story** in which the president merely
    issued an order. See `_RULES` for the full table.

    **Precedence is ordered by strength of evidence.** One article can match
    several sections and a single label has to win, so the rules are grouped:

    1. the editorial's **printed marker** and the **three offices**, decided
       across the headline and the body together;
    2. every other section, on the **headline**;
    3. every other section, on its own word in the **body**.

    The offices come before the topics deliberately. Measured 2026-09-30: a
    story headlined *"ဒဂုံတက္ကသိုလ် ဘွဲ့နှင်းသဘင် အခမ်းအနား ကျင်းပ"* that names
    `နိုင်ငံတော်သမ္မတ` twice in the body was filed under **education**, because
    the headline pass matched the topical word `တက္ကသိုလ်` (university) and
    returned before the office rule was consulted. The three offices are the
    owner's first three and the ones he gave an example of, so a single topical
    noun must not outrank the office a story is about.

    **The editorial is found by its printed marker, not its subject.**
    Measured: the paper sets the word in brackets at the end of the headline —
    `… ပြေးဆွဲပေး (အယ်ဒီတာ့အာဘော်)`. Every editorial row carries it. Detecting
    an editorial by what it is *about* is impossible — the six editorials in
    the corpus are about education, transport, diplomacy, air quality and the
    economy — so without the marker the section could never be populated.

    **Everything that matches nothing is `အခြား` (other).** The owner's eleven
    sections do not cover the whole paper (sport, religion, announcements), and
    a story forced into the nearest section is a wrong index entry. `အခြား` is
    honest and is reported as such.

WHAT THIS IS NOT

    These are **not the paper's own printed section names**. The extraction
    keeps the article text and not the page furniture, so the printed section
    heading is not in the database. This is JARVIS's own subject index of the
    paper, and every answer it produces says so.
"""
from __future__ import annotations

import re
from typing import Optional

# ── The sections ─────────────────────────────────────────────────────────────
#
# `slug` is for code and for the model's parameter; `label` is what is stored
# in the database and what is spoken. The Burmese label is the stored form
# because the owner reads Burmese and the database is Burmese throughout —
# translating a section name on the way in would be the same mistake as
# translating a search term.

SECTIONS: tuple[tuple[str, str], ...] = (
    ("president",      "နိုင်ငံတော်သမ္မတ"),
    ("vice_president", "ဒုတိယသမ္မတများ"),
    ("union_minister", "ပြည်ထောင်စုဝန်ကြီးများ"),
    ("article",        "ဆောင်းပါး"),
    ("politics",       "နိုင်ငံရေး"),
    ("economy",        "စီးပွားရေး"),
    ("social",         "လူမှုရေး"),
    ("education",      "ပညာရေး"),
    ("health",         "ကျန်းမာရေး"),
    ("disaster",       "သဘာဝဘေး"),
    ("editorial",      "အယ်ဒီတာအာဘော်"),
)

# Everything the eleven do not cover. Reported, never hidden — see the module
# docstring.
OTHER = "အခြား"

LABELS: tuple[str, ...] = tuple(label for _slug, label in SECTIONS) + (OTHER,)
LABEL_BY_SLUG: dict[str, str] = dict(SECTIONS)
SLUG_BY_LABEL: dict[str, str] = {label: slug for slug, label in SECTIONS}

# What the owner (or the model) may call a section. Every entry is a form the
# owner actually writes — `သမ္မတ` alone for the president, `ဝန်ကြီး` for the
# union ministers. Longest first, so `ဒုတိယသမ္မတ` is matched before `သမ္မတ`.
#
# **The vice-president's entries come before the president's, and that order is
# the whole correctness of the table.** Measured 2026-09-30, on the first
# version which listed the president first: `resolve_section("ဒုတိယသမ္မတ")`
# returned `နိုင်ငံတော်သမ္မတ` — `သမ္မတ` is a substring of `ဒုတိယသမ္မတ`, so the
# shorter alias matched first and the owner asking about a vice-president would
# have been answered from the president's section. This is the same trap
# `core/entities.py` guards with `_SHORT_TITLE_GUARD_RE`, and here the fix is
# simply the order: **a longer alias must always be tested before a shorter one
# that it contains.**
_SECTION_ALIASES: tuple[tuple[str, str], ...] = (
    ("ဒုတိယသမ္မတများ", "vice_president"),
    ("ဒုတိယသမ္မတ", "vice_president"),
    ("နိုင်ငံတော်သမ္မတ", "president"),
    ("သမ္မတ", "president"),
    ("ပြည်ထောင်စုဝန်ကြီးများ", "union_minister"),
    ("ပြည်ထောင်စုဝန်ကြီး", "union_minister"),
    ("ဝန်ကြီးများ", "union_minister"),
    ("ဝန်ကြီး", "union_minister"),
    ("ဆောင်းပါး", "article"),
    ("နိုင်ငံရေး", "politics"),
    ("စီးပွားရေး", "economy"),
    ("လူမှုရေး", "social"),
    ("ပညာရေး", "education"),
    ("ကျန်းမာရေး", "health"),
    ("သဘာဝဘေး", "disaster"),
    ("ဘေးအန္တရာယ်", "disaster"),
    ("အယ်ဒီတာအာဘော်", "editorial"),
    ("အယ်ဒီတာ့အာဘော်", "editorial"),
    ("အာဘော်", "editorial"),
    ("editorial", "editorial"),
    ("အခြား", ""),
)

# ── The rules ────────────────────────────────────────────────────────────────
#
# `strong` are the section's own words and count anywhere; `weak` are topical
# vocabulary and count **in the headline only**. `scope` says where a strong
# word counts when it is not in the headline:
#
#   "lede" — only the opening of the body (the offices; see below)
#   "body" — the whole body, once

_RULES: tuple[dict, ...] = (
    # ── The editorial, by its printed marker ──
    # **First, because it is the strongest evidence there is: the paper printed
    # it.** Measured: the word is set in brackets at the end of the headline —
    # `… ပြေးဆွဲပေး (အယ်ဒီတာ့အာဘော်)` — and every editorial row carries it.
    # Detecting an editorial by its *subject* is impossible: the six in the
    # corpus are about education, transport, diplomacy, air quality and the
    # economy, so without the marker the section could never be populated, and
    # below the topic rules it would be swallowed by whatever it discusses.
    {"slug": "editorial", "scope": "body",
     "strong": ("အယ်ဒီတာ့အာဘော်", "အယ်ဒီတာအာဘော်", "အာဘော်"), "weak": ()},

    # ── The three offices ──
    # **The office must be in the headline or in the opening of the story** —
    # not merely somewhere in the body. The first version counted any two
    # mentions, and the owner's own test caught what that costs: asked
    # *"ဒီနေ့ နိုင်ငံတော်သမ္မတ သတင်း ဘာရှိလဲ"* on 2026-10-01, the president
    # section answered with *"တတိယအကြိမ် ပြည်ထောင်စုလွှတ်တော် … ပထမနေ့ကျင်းပ"* —
    # a **parliament** story, in which the president appears only as the issuer
    # of an order, 2,203 characters into a 6,324-character body.
    #
    # Measured over the corpus, the two rules are not close:
    #
    #   president        headline 72 · first sentence 44 · anywhere x2 22
    #   vice-president   headline 16 · first sentence  4 · anywhere x2  3
    #   union minister   headline 36 · first sentence 23 · anywhere x2 36
    #
    # and the "anywhere x2" rows beyond the first sentence are **one** article
    # for the president — the parliament story above. Sampling the first-
    # sentence rows shows what the rule buys: *"နိုင်ငံတော်သမ္မတ ဦးမင်းအောင်လှိုင်
    # အား…"*, *"နိုင်ငံတော်သမ္မတ၏ ဗီယက်နမ် တရားဝင်ခရီးစဉ်"*, *"နိုင်ငံတော်သမ္မတ
    # ဦးဆောင်သည့် … ညှိနှိုင်းအစည်းအဝေး"* — every one is about the office.
    # A Burmese news lede names the principal actor in its first sentence, which
    # is the paper's own statement of what the story is about.
    {"slug": "president", "scope": "lede",
     "strong": ("နိုင်ငံတော်သမ္မတ",), "weak": ()},
    {"slug": "vice_president", "scope": "lede",
     "strong": ("ဒုတိယသမ္မတ",), "weak": ()},
    # The union form only. Bare `ဝန်ကြီး` is a prefix of `ဝန်ကြီးဌာန`
    # (ministry) and `ဝန်ကြီးချုပ်` (chief minister), which is the trap
    # `core/entities.py` documents — a plain substring test on the short form
    # would file every ministry mention under "union ministers".
    {"slug": "union_minister", "scope": "lede",
     "strong": ("ပြည်ထောင်စုဝန်ကြီး",), "weak": ()},

    # ── The feature article ──
    # `ဆောင်းပါး` is both the section word and the paper's own label for a
    # signed feature, so it counts in the headline and once in the body.
    {"slug": "article", "scope": "body",
     "strong": ("ဆောင်းပါး",), "weak": ("ဆောင်းပါးရှင်",)},

    # ── Natural disaster ──
    # Above the remaining topics because it is event-driven and time-critical:
    # a flood story is filed as a flood story.
    {"slug": "disaster", "scope": "body",
     "strong": ("သဘာဝဘေး", "မုန်တိုင်း", "ရေကြီး", "ရေဘေး", "ရေလွှမ်း",
                "မြေငလျင်", "ငလျင်", "ရေတိုက်စား", "မီးလောင်"),
     "weak": ("ကယ်ဆယ်ရေး", "ထောက်ပံ့")},

    # ── The topics ──
    {"slug": "education", "scope": "body",
     "strong": ("ပညာရေး",), "weak": ("တက္ကသိုလ်", "ကျောင်းသား", "ကျောင်းအုပ်",
                                    "ပညာသင်ကြား", "စာမေးပွဲ")},
    {"slug": "health", "scope": "body",
     "strong": ("ကျန်းမာရေး",), "weak": ("ဆေးရုံ", "ဆေးဝါး", "ကုသရေး",
                                      "ကာကွယ်ဆေး", "ရောဂါ")},
    {"slug": "economy", "scope": "body",
     "strong": ("စီးပွားရေး",), "weak": ("ကုန်သွယ်ရေး", "ရင်းနှီးမြှုပ်နှံ", "ဘဏ်",
                                      "ငွေကြေး", "အခွန်", "ပို့ကုန်", "သွင်းကုန်")},
    {"slug": "politics", "scope": "body",
     "strong": ("နိုင်ငံရေး",), "weak": ("ရွေးကောက်ပွဲ", "နိုင်ငံရေးပါတီ")},
    # Last of the topics: `လူမှုရေး` is the vaguest of the eleven and would
    # otherwise swallow stories that belong to a sharper section.
    {"slug": "social", "scope": "body",
     "strong": ("လူမှုရေး",), "weak": ("လူမှုကူညီရေး", "ပရဟိတ", "ဒုက္ခသည်")},
)

# How much of the body counts as "the opening": its first sentence, capped at
# roughly one paragraph. Measured 2026-10-01 — the median readable body in this
# corpus is 735 characters, so 400 is the opening paragraph and not a fraction
# of the story. The cap is what stops a body whose `။` was lost by the OCR
# (the pipeline glues whole headlines into one run) from being treated as one
# endless lede and swallowing the article.
_LEDE_MAX = 400
_SENTENCE_END = "။"

# The rules that are decided **across the headline and the body together**,
# before any other rule sees the headline. See `classify` for why.
_OFFICE_SLUGS = ("editorial", "president", "vice_president", "union_minister")

# ── Matching ─────────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def _pack(text: str) -> str:
    """Whitespace removed.

    **Whitespace is not a separator to trust in this corpus.** The paper and
    the extraction both vary it — `နိုင်ငံတော် သမ္မတ` and `နိုင်ငံတော်သမ္မတ`
    are one office written two ways, and `core/entities.py` carries both
    spellings as separate measured entries for exactly this reason. Packing the
    text makes one test cover both, so a rule never has to list a spacing
    variant. It is safe here because every test is a membership test on a
    distinctive multi-syllable phrase, never a boundary-sensitive one.
    """
    return _WS.sub("", text or "")


def _forms(word: str) -> tuple[str, ...]:
    """The word in both encodings, packed.

    The database mixes Unicode and Zawgyi — measured 2026-09-29 by
    `core/reporter_client._like_clause`, which already expands every search
    term the same way. A Unicode-only section rule would miss the Zawgyi rows
    silently, which is the one failure this index must not have.
    """
    try:
        from core.zawgyi import variants
        out = variants(word)
    except Exception:                                       # noqa: BLE001
        out = [word]
    return tuple(_pack(v) for v in out if v)


# Pre-expanded so the per-article loop does no conversion at all: 7,500
# articles x ~40 words would otherwise re-run the Zawgyi regex a quarter of a
# million times.
_RULES_PACKED: tuple[dict, ...] = tuple(
    {
        "slug": r["slug"],
        "scope": r["scope"],
        "strong": tuple(f for w in r["strong"] for f in _forms(w)),
        "weak": tuple(f for w in r["weak"] for f in _forms(w)),
    }
    for r in _RULES
)
_PACKED_BY_SLUG = {r["slug"]: r for r in _RULES_PACKED}
_STRONG_RULES = tuple(_PACKED_BY_SLUG[s] for s in _OFFICE_SLUGS)
_TOPIC_RULES = tuple(r for r in _RULES_PACKED if r["slug"] not in _OFFICE_SLUGS)


def _matches(rule: dict, packed: str) -> bool:
    """True when a strong or weak form of `rule` occurs in `packed`."""
    if any(f in packed for f in rule["strong"]):
        return True
    return any(f in packed for f in rule["weak"])


def _lede(body: str) -> str:
    """The opening of the body — its first sentence, capped.

    A Burmese news story names its principal actor in the first sentence, so
    this is where an office has to appear to be *the subject* rather than a
    passing reference. The cap matters: a body whose first `။` is 2,500
    characters in would otherwise hand the whole article to the office rules,
    which is the defect this exists to prevent.
    """
    if not body:
        return ""
    cut = body.find(_SENTENCE_END)
    if cut < 0 or cut > _LEDE_MAX:
        return body[:_LEDE_MAX]
    return body[:cut]


# ── The classifier ───────────────────────────────────────────────────────────

def classify(article: dict) -> tuple[str, str]:
    """(section label, why). `OTHER` when nothing matches.

    The second element is a short machine-readable reason — `"strong"`,
    `"headline"`, `"body"` or `""` — kept so a check can assert *which pass*
    decided an article, not merely that a label came out. A section that fired
    for the wrong reason looks identical to a correct one in the label alone.

    **Precedence is ordered by strength of evidence, not by topic.**

        1. `strong` — the editorial's printed marker, and the three offices
           named in the headline or in the **opening of the story**. These are
           decided **across both fields at once**, before any other rule sees
           the headline.
        2. `headline` — every other section, on the headline alone.
        3. `body` — every other section, on its own section word in the body.

    Pass 1 runs across both fields because of a defect measured 2026-09-30: a
    story headlined *"ဒဂုံတက္ကသိုလ် ဘွဲ့နှင်းသဘင် အခမ်းအနား ကျင်းပ"* that names
    `နိုင်ငံတော်သမ္မတ` twice in the body was filed under **education**, because
    the headline pass matched the topical word `တက္ကသိုလ်` (university) and
    returned before the office rule was ever consulted. The office sections are
    the owner's first three and the ones he gave an example of; a single
    topical noun in a headline must not outrank the office a story is about.

    Pass 2 then keeps the headline decisive for everything else, because a
    headline is the paper's own statement of what a story is about.
    """
    head = _pack(article.get("headline") or "")
    body = _pack(article.get("body_text") or article.get("summary") or "")
    lede = _lede(body)

    # Pass 1 — the printed label and the offices, across headline and body.
    # `scope` decides how much of the body counts: `"lede"` for the offices,
    # which must be the subject; `"body"` for the printed editorial marker and
    # a signed feature, which are labels rather than subjects.
    for rule in _STRONG_RULES:
        if head and _matches(rule, head):
            return LABEL_BY_SLUG[rule["slug"]], "strong"
        if rule["scope"] == "lede":
            if lede and _matches(rule, lede):
                return LABEL_BY_SLUG[rule["slug"]], "strong"
        elif body and _matches(rule, body):
            return LABEL_BY_SLUG[rule["slug"]], "strong"

    # Pass 2 — the headline decides the rest. Both the section's own word and
    # its topical vocabulary count here, because a headline is short and every
    # word in it is a choice.
    if head:
        for rule in _TOPIC_RULES:
            if _matches(rule, head):
                return LABEL_BY_SLUG[rule["slug"]], "headline"

    # Pass 3 — the body, and only the section's own word.
    for rule in _TOPIC_RULES:
        if body and _matches(rule, body):
            return LABEL_BY_SLUG[rule["slug"]], "body"

    return OTHER, ""


def section_of(article: dict) -> str:
    """The section **already stored** on this row, or "" when it has none.

    A stored value counts only when it is one of this module's labels. The
    legacy `'General'` and the abandoned English labels are not sections — they
    mean "never indexed" — and treating them as answers would make the reader
    report an empty section as a real one.
    """
    stored = str(article.get("article_type") or article.get("section") or "").strip()
    return stored if stored in LABELS else ""


def resolve_section(name: str) -> str:
    """What the user said → the stored section label, or "" when unknown.

    **An unknown name never degrades to "everything".** Measured 2026-09-30 on
    the prices side of this project: `kind="rice"` was not in `_PRICE_KINDS`,
    the filter was silently dropped, and a rice-price question came back with
    fire-balloon festival dates. The same shape of bug here would answer
    "today's Sports news" with the whole newspaper. So "" means *not a section
    this index has*, and the caller must say so.
    """
    text = _pack(name).lower()
    if not text:
        return ""
    # An exact label always wins, so the stored form is always accepted.
    for label in LABELS:
        if _pack(label) == text:
            return label
    for alias, slug in _SECTION_ALIASES:
        if _pack(alias).lower() in text:
            return LABEL_BY_SLUG.get(slug, "")
    return ""


def slugs() -> list[str]:
    """Every slug, for the tool's error message."""
    return [slug for slug, _label in SECTIONS]


def labels() -> list[str]:
    """Every stored label including `OTHER`."""
    return list(LABELS)


# ── The query vocabulary ─────────────────────────────────────────────────────
#
# What the owner says when he wants a section. `resolve_section` reads the
# **section name**; this is for the router in `main.py`, which has to tell a
# section question from an ordinary news question *before* the model is
# involved. It is deliberately a separate, narrower list: `ဝန်ကြီး` alone is
# not here, because "which ministers are in today's paper" is a `people`
# question and must keep going to `reporter_news`.
ROUTING_WORDS: tuple[str, ...] = (
    "နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ", "ပြည်ထောင်စုဝန်ကြီး",
    "ဆောင်းပါး", "အယ်ဒီတာအာဘော်", "အယ်ဒီတာ့အာဘော်",
    "နိုင်ငံရေး", "စီးပွားရေး", "လူမှုရေး", "ပညာရေး", "ကျန်းမာရေး",
    "သဘာဝဘေး",
)
