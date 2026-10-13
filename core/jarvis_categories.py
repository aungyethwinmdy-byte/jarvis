"""The owner's 16 categories for JARVIS — the taxonomy that replaces the 11 sections.

WHY THIS EXISTS

    The owner's spec, 2026-10-01, defines a `categorized_news` table in the
    `jarvis` project (yrzvwsqafmftbrfwimsf) with **fifteen** categories, and he
    asked for a sixteenth — `အခြား` — because 69% of the readable corpus
    (advertisements, announcements, sport, regional notices) matches none of the
    fifteen.

    His list, verbatim, is `SECTIONS` below. It differs from the eleven sections
    in `core/news_sections.py` in four ways, and each difference is a real
    change of behaviour rather than a rename:

      * the two vice-presidents are **separate categories, by name** — he does
        not want one "vice-presidents" bucket;
      * **three** parliament categories instead of none;
      * `သဘာဝဘေးအန္တရာယ်သတင်းများ`, `ဆောင်းပါးများ`, `အယ်ဒီတာ့အာဘော်` are
        spelled as he wrote them;
      * there is no implicit "everything else" — he asked for it explicitly.

    **The mechanism is not re-implemented here.** Packing, the Zawgyi variants,
    the lede window and the keyword test are imported from `news_sections.py`,
    so there is one implementation of how an article is read and one place where
    a taxonomy is defined. When the migration to `categorized_news` lands, the
    eleven-section tables in `news_sections.py` are what gets deleted — this
    module is the surviving definition.
"""
from __future__ import annotations

from core.news_sections import _forms, _lede, _matches, _pack

# ── The categories ───────────────────────────────────────────────────────────
#
# The stored string is the Burmese name, exactly as the owner wrote it. It is
# stored rather than a slug because the database is Burmese throughout and a
# translated category name is the same mistake as a translated search term.

SECTIONS: tuple[tuple[str, str], ...] = (
    ("president",       "နိုင်ငံတော်သမ္မတ"),
    ("vp_nyio_saw",     "ဒုတိယသမ္မတဦးညိုစော"),
    ("vp_nan_nini_aye", "ဒုတိယသမ္မတဒေါ်နန်းနီနီအေး"),
    ("union_minister",  "ပြည်ထောင်စုဝန်ကြီးများ"),
    ("amyotha",         "အမျိုးသားလွှတ်တော်"),
    ("pyithu",          "ပြည်သူ့လွှတ်တော်"),
    ("pyidaungsu",      "ပြည်ထောင်စုလွှတ်တော်"),
    ("politics",        "နိုင်ငံရေး"),
    ("economy",         "စီးပွားရေး"),
    ("social",          "လူမှုရေး"),
    ("education",       "ပညာရေး"),
    ("health",          "ကျန်းမာရေး"),
    ("disaster",        "သဘာဝဘေးအန္တရာယ်သတင်းများ"),
    ("article",         "ဆောင်းပါးများ"),
    ("editorial",       "အယ်ဒီတာ့အာဘော်"),
)

# The sixteenth, which the owner added so that no article is forced into a
# category it does not belong to.
OTHER = "အခြား"

LABELS: tuple[str, ...] = tuple(label for _slug, label in SECTIONS) + (OTHER,)
LABEL_BY_SLUG: dict[str, str] = dict(SECTIONS)
SLUG_BY_LABEL: dict[str, str] = {label: slug for slug, label in SECTIONS}

# What the owner may call a category. **A longer alias is always tested before a
# shorter one that it contains** — the measured defect from the eleven-section
# table, where `သမ္မတ` matched inside `ဒုတိယသမ္မတ` and a vice-president question
# read the president's section. Here `ဒုတိယသမ္မတ` maps to the two named
# categories only when a name is present, so it is deliberately absent.
_SECTION_ALIASES: tuple[tuple[str, str], ...] = (
    ("ဒုတိယသမ္မတဦးညိုစော", "vp_nyio_saw"),
    ("ဦးညိုစော", "vp_nyio_saw"),
    # The 2026-09-30 edition prints him as `ဦးညိမ်းစော` — the same office, the
    # same person, two spellings. Measured 2026-10-01: 13 articles name him, 9
    # of them under the second spelling, so recognising only one would split one
    # vice-president into two half-categories.
    ("ဦးညိမ်းစော", "vp_nyio_saw"),
    ("ဒုတိယသမ္မတဒေါ်နန်းနီနီအေး", "vp_nan_nini_aye"),
    ("ဒေါ်နန်းနီနီအေး", "vp_nan_nini_aye"),
    ("နိုင်ငံတော်သမ္မတ", "president"),
    ("ပြည်ထောင်စုဝန်ကြီးများ", "union_minister"),
    ("ပြည်ထောင်စုဝန်ကြီး", "union_minister"),
    ("ပြည်ထောင်စုလွှတ်တော်", "pyidaungsu"),
    ("အမျိုးသားလွှတ်တော်", "amyotha"),
    ("ပြည်သူ့လွှတ်တော်", "pyithu"),
    ("နိုင်ငံရေး", "politics"),
    ("စီးပွားရေး", "economy"),
    ("လူမှုရေး", "social"),
    ("ပညာရေး", "education"),
    ("ကျန်းမာရေး", "health"),
    ("သဘာဝဘေးအန္တရာယ်သတင်းများ", "disaster"),
    ("သဘာဝဘေး", "disaster"),
    ("ဆောင်းပါးများ", "article"),
    ("ဆောင်းပါး", "article"),
    ("အယ်ဒီတာ့အာဘော်", "editorial"),
    ("အယ်ဒီတာအာဘော်", "editorial"),
    ("အာဘော်", "editorial"),
    ("အခြား", ""),
)

# ── The rules ────────────────────────────────────────────────────────────────
#
# `scope` says where a strong word counts when it is not in the headline:
#   "lede" — the opening of the story only (who or what it is *about*)
#   "body" — anywhere in the body, once (a printed label)

_RULES: tuple[dict, ...] = (
    # ── The printed labels ──
    {"slug": "editorial", "scope": "body",
     "strong": ("အယ်ဒီတာ့အာဘော်", "အယ်ဒီတာအာဘော်", "အာဘော်"), "weak": ()},
    {"slug": "article", "scope": "body",
     "strong": ("ဆောင်းပါးများ", "ဆောင်းပါး"), "weak": ("ဆောင်းပါးရှင်",)},

    # ── The offices, by seniority ──
    # Headline or the opening of the story, never a passing mention — the rule
    # measured on the eleven-section table, where a parliament story in which
    # the president merely issued an order was filed under the president.
    {"slug": "president", "scope": "lede",
     "strong": ("နိုင်ငံတော်သမ္မတ",), "weak": ()},
    # **The two vice-presidents are separate categories and are matched by
    # NAME.** Measured 2026-10-01 over 7,193 readable articles: `ဦးညိုစော`
    # appears in 13 and `ဒေါ်နန်းနီနီအေး` in 9 — small categories, and the
    # office word alone would merge them, which is exactly what the owner asked
    # not to happen.
    {"slug": "vp_nyio_saw", "scope": "lede",
     "strong": ("ဦးညိုစော", "ဦးညိမ်းစော"), "weak": ()},
    {"slug": "vp_nan_nini_aye", "scope": "lede",
     "strong": ("ဒေါ်နန်းနီနီအေး",), "weak": ()},
    {"slug": "union_minister", "scope": "lede",
     "strong": ("ပြည်ထောင်စုဝန်ကြီး",), "weak": ()},

    # ── The three parliaments ──
    # **They overlap badly and that is the whole difficulty.** Measured
    # 2026-10-01: 108 articles contain both `အမျိုးသားလွှတ်တော်` and
    # `ပြည်သူ့လွှတ်တော်`, 73 contain both `ပြည်သူ့လွှတ်တော်` and
    # `ပြည်ထောင်စုလွှတ်တော်`, and 66 contain the other pair — so a plain
    # keyword count cannot separate them and would put one story in two
    # categories. Precedence is by the headline, then by the opening, and the
    # union assembly (both houses sitting together) is tested first because it
    # is the larger body.
    {"slug": "pyidaungsu", "scope": "lede",
     "strong": ("ပြည်ထောင်စုလွှတ်တော်",), "weak": ()},
    {"slug": "amyotha", "scope": "lede",
     "strong": ("အမျိုးသားလွှတ်တော်",), "weak": ()},
    {"slug": "pyithu", "scope": "lede",
     "strong": ("ပြည်သူ့လွှတ်တော်",), "weak": ()},

    # ── The topics ──
    {"slug": "disaster", "scope": "body",
     "strong": ("သဘာဝဘေး", "မုန်တိုင်း", "ရေကြီး", "ရေဘေး", "ရေလွှမ်း",
                "မြေငလျင်", "ငလျင်", "ရေတိုက်စား", "မီးလောင်"),
     "weak": ("ကယ်ဆယ်ရေး", "ထောက်ပံ့")},
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
    {"slug": "social", "scope": "body",
     "strong": ("လူမှုရေး",), "weak": ("လူမှုကူညီရေး", "ပရဟိတ", "ဒုက္ခသည်")},
)

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

# The rules decided across the headline **and** the opening of the story, before
# any other rule sees the headline — the offices and the parliaments, which are
# the subject of a story rather than a label printed on it.
_SUBJECT_SLUGS = ("president", "vp_nyio_saw", "vp_nan_nini_aye", "union_minister",
                  "pyidaungsu", "amyotha", "pyithu")
_LABEL_SLUGS = ("editorial", "article")
_SUBJECT_RULES = tuple(_PACKED_BY_SLUG[s] for s in _SUBJECT_SLUGS)
_LABEL_RULES = tuple(_PACKED_BY_SLUG[s] for s in _LABEL_SLUGS)
_TOPIC_RULES = tuple(r for r in _RULES_PACKED
                     if r["slug"] not in _SUBJECT_SLUGS + _LABEL_SLUGS)


def classify(article: dict) -> tuple[str, str]:
    """(category, why). `OTHER` when nothing matches.

    Three passes, in order of how strong the evidence is:

        1. the two printed labels — the editorial marker and a signed feature;
        2. the offices and the parliaments, across the headline **and** the
           opening of the story;
        3. the topics, on the headline, then on the body.

    The `why` is kept so a check can assert *which pass* decided an article. A
    category that fired for the wrong reason is indistinguishable from a correct
    one in the label alone.
    """
    head = _pack(article.get("headline") or "")
    body = _pack(article.get("body_text") or article.get("summary") or "")
    lede = _lede(body)

    for rule in _LABEL_RULES:
        if body and _matches(rule, body):
            return LABEL_BY_SLUG[rule["slug"]], "label"

    for rule in _SUBJECT_RULES:
        if head and _matches(rule, head):
            return LABEL_BY_SLUG[rule["slug"]], "subject"
        if lede and _matches(rule, lede):
            return LABEL_BY_SLUG[rule["slug"]], "subject"

    if head:
        for rule in _TOPIC_RULES:
            if _matches(rule, head):
                return LABEL_BY_SLUG[rule["slug"]], "headline"

    for rule in _TOPIC_RULES:
        if body and _matches(rule, body):
            return LABEL_BY_SLUG[rule["slug"]], "body"

    return OTHER, ""


def section_of(article: dict) -> str:
    """The category already stored on this row, or "" when it has none.

    `category` is the spec's column name; `article_type` and `section` are the
    two names the reporter project uses for the same idea, so all three are
    accepted on the way in. A value that is not one of our labels — `'General'`
    and the abandoned English labels alike — means "never categorised".
    """
    for key in ("category", "article_type", "section"):
        stored = str(article.get(key) or "").strip()
        if stored in LABELS:
            return stored
    return ""


def resolve_section(name: str) -> str:
    """What the user said → the stored category, or "" when it is unknown.

    **An unknown name never degrades to "everything".** The eleven-section
    reader has the same rule and the same reason: a filter that is silently
    dropped answers "today's Sports news" with the whole newspaper.
    """
    text = _pack(name).lower()
    if not text:
        return ""
    for label in LABELS:
        if _pack(label) == text:
            return label
    for alias, slug in _SECTION_ALIASES:
        if _pack(alias).lower() in text:
            return LABEL_BY_SLUG.get(slug, "")
    return ""


def labels() -> list[str]:
    """Every stored label, including `အခြား`."""
    return list(LABELS)
