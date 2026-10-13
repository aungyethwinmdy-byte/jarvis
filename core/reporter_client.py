"""Read-only bridge to the my_reporter newsroom — the second Supabase project.

WHY THERE ARE TWO BRIDGES

    JARVIS already reads one newsroom (`core/newsroom_client.py`): PPIB, BBC
    Burmese and The Irrawaddy, out of `yrzvwsqafmftbrfwimsf`. The my_reporter
    pipeline at `E:\\test\\my_reporter-main` runs a **different Supabase project**
    — verified 2026-09-29, different URL and a different service key — and reads
    the two state newspapers, Myanma Alinn and The Mirror, plus everything their
    Page-2 tables contain.

    They are complementary, not duplicates. JARVIS has PPIB and not the state
    papers; my_reporter has the state papers and not PPIB. This module adds the
    second without touching the first.

WHAT IT IS FOR

    `newspaper_numbers` is the reason this exists. It is not a fuel-and-gold
    table — measured 2026-09-29 it holds 376 rows of **every figure the state
    papers printed**, each with its section, unit, context and publication date:

        section     359  စီးပွားရေး      16  စက်သုံးဆီ      1  ရွှေဈေး
        units       63 ကျပ်   38 ရက်   30 ဧက   20 လ   10 ဦး

    and 81 of them are prices — the gold reference price, the dollar, yuan and
    baht rates, and retail 92 Ron in Yangon **and in Naypyidaw**. Newest row
    2026-09-28.

    A language model cannot know any of that, and guessing a fuel price is worse
    than saying nothing. Reading it from the table is the whole point.

SAME DISCIPLINE AS THE OTHER BRIDGE
    - Credentials come from the reporter's own `.env` via `dotenv_values`, never
      `load_dotenv` — loading it would push this project's keys into the
      process environment where any later import could read them.
    - Every public reader goes through `_cached()`, which returns the caller's
      default on a Supabase stall. The answer gets thinner, never an apology.
    - Bounded timeouts, because these calls sit between the user finishing a
      sentence and hearing the first word back.
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from typing import Any, Callable, Optional

# ── Tunables ─────────────────────────────────────────────────────────────────

REQUEST_TIMEOUT = 6.0
RETRY_ATTEMPTS = 2
RETRY_DELAY = 0.6
CACHE_TTL = 180.0          # prices move daily, not per second

MAX_ROWS = 25              # nothing caps the server side; the model's context is

_lock = threading.Lock()
_client: Any = None
_client_error: str = ""
_client_tried = False
_cache: dict[str, tuple[float, Any]] = {}


# ── Credentials ──────────────────────────────────────────────────────────────

def env_path():
    """The reporter's .env — configured, with a sensible default."""
    from pathlib import Path
    try:
        from memory.config_manager import get_reporter_env_path
        p = get_reporter_env_path()
    except Exception:                                       # noqa: BLE001
        p = r"E:\test\my_reporter-main\.env"
    return Path(p)


def _read_env() -> dict[str, str]:
    """Parse the .env without loading it into the process environment."""
    path = env_path()
    try:
        from dotenv import dotenv_values
        return {k: (v or "") for k, v in dotenv_values(str(path)).items() if k}
    except ImportError:
        pass
    except Exception as e:                                  # noqa: BLE001
        print(f"[Reporter] could not read {path}: {type(e).__name__}: {e}")
        return {}

    # Minimal fallback so a missing python-dotenv is not fatal.
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:                                       # noqa: BLE001
        pass
    return out


def _credentials() -> tuple[str, str]:
    """my_reporter names its key SUPABASE_SERVICE_ROLE_KEY, not _SERVICE_KEY."""
    env = _read_env()
    url = (env.get("SUPABASE_URL") or "").strip()
    key = (env.get("SUPABASE_SERVICE_ROLE_KEY")
           or env.get("SUPABASE_SERVICE_KEY")
           or env.get("SUPABASE_KEY") or "").strip()
    return url, key


# ── Client ───────────────────────────────────────────────────────────────────

def _get_client() -> Any:
    """The Supabase client, or None. Built once; the reason is kept for status."""
    global _client, _client_error, _client_tried
    with _lock:
        if _client is not None or _client_tried:
            return _client
        _client_tried = True

        url, key = _credentials()
        if not url or not key:
            _client_error = f"credentials not found in {env_path()}"
            return None
        try:
            from supabase import ClientOptions, create_client
            _client = create_client(
                url, key,
                options=ClientOptions(postgrest_client_timeout=REQUEST_TIMEOUT),
            )
        except Exception as e:                              # noqa: BLE001
            _client_error = f"{type(e).__name__}: {e}"
            _client = None
        return _client


def available() -> tuple[bool, str]:
    """(usable, reason-if-not). Cheap: reuses the already-built client."""
    if _get_client() is not None:
        return True, "ok"
    return False, _client_error or "reporter database unreachable"


def reset() -> None:
    """Drop the cached client and cache (tests, or after credentials change)."""
    global _client, _client_error, _client_tried
    with _lock:
        _client = None
        _client_error = ""
        _client_tried = False
        _cache.clear()


# ── Query plumbing ───────────────────────────────────────────────────────────

def _run(fn: Callable[[], Any], label: str) -> Any:
    """Run one query with a single retry. Raises only after both attempts fail."""
    last: Optional[Exception] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:                              # noqa: BLE001
            last = e
            print(f"[Reporter] {label} attempt {attempt}/{RETRY_ATTEMPTS} failed: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    raise last  # type: ignore[misc]


def _cached(key: str, produce: Callable[[], Any], default: Any) -> Any:
    """Short-lived cache; only a successful, non-empty result is stored.

    A failure must not be cached — otherwise one Supabase stall makes the tool
    answer "nothing found" for the next three minutes.
    """
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]

    if _get_client() is None:
        return default
    try:
        value = _run(produce, key)
    except Exception as e:                                  # noqa: BLE001
        print(f"[Reporter] {key} gave up: {type(e).__name__}: {e}")
        return default

    if value:
        _cache[key] = (time.time(), value)
    return value if value else default


# ── The numbers ──────────────────────────────────────────────────────────────

# The table is keyed by Burmese section names, so the kinds are Burmese too —
# translating a query before it reaches the database is the one thing this
# project never does.
_PRICE_KINDS = {
    "fuel": "စက်သုံးဆီ",
    "gold": "ရွှေဈေး",
    "economy": "စီးပွားရေး",
}


def latest_numbers(kind: str = "", limit: int = MAX_ROWS) -> list[dict]:
    """The most recent rows of `newspaper_numbers`, newest first.

    `kind` is one of fuel / gold / economy, or empty for everything. Rows carry
    `publication_date`, `context`, `value`, `unit` and `source_text` — enough to
    answer with a figure *and* say which day's paper it came from, which is the
    difference between a fact and a guess.

    **An unknown kind does not fall back to "everything".** Measured
    2026-09-30: the model sent `kind="rice"`, which is not in `_PRICE_KINDS`,
    so `section` resolved to `""` and the filter was **silently dropped** — the
    tool answered *"ဒီနေ့ ဆန်ဈေးနှုန်း အခြေအနေဘယ်လိုရှိလဲ"* with fire-balloon
    festival dates and a financial year. The caller must be able to tell "I do
    not know that kind" from "that kind has no rows", so `kind_known()` exists
    and the action asks it before trusting an empty result.
    """
    section = _PRICE_KINDS.get((kind or "").strip().lower(), "")
    limit = max(1, min(int(limit or MAX_ROWS), MAX_ROWS))

    def produce() -> list[dict]:
        q = (_get_client().table("newspaper_numbers")
             .select("publication_date,section,headline,value,original_value,"
                     "unit,context,source_text")
             .order("publication_date", desc=True))
        if section:
            q = q.eq("section", section)
        return q.limit(limit).execute().data or []

    return _cached(f"numbers:{section or 'all'}:{limit}", produce, [])


def kind_known(kind: str) -> bool:
    """Is `kind` one of the sections this table is keyed by?

    Empty is known (it means "everything"). Anything else that is not in
    `_PRICE_KINDS` is **not** a filter this client can apply — the caller must
    say so rather than receive an unfiltered list that looks like an answer.
    """
    k = (kind or "").strip().lower()
    return (not k) or k in _PRICE_KINDS


def kinds() -> list[str]:
    """The kinds `latest_numbers` accepts, for the action's error message."""
    return sorted(_PRICE_KINDS)


# The alias table itself lives next to `price_trend` (search `_PRICE_ALIASES`),
# where the fuel gap was first measured. These two helpers are what every
# numbers reader goes through, so all of them agree on what a term means.
def _price_terms(term: str) -> list[str]:
    """`term` plus any measured alias of it, deduplicated, order preserved.

    `price_trend` collects its own terms the same way — keep the two in step.
    """
    out = [term]
    for key, aliases in _PRICE_ALIASES.items():
        if key in term:
            for a in aliases:
                if a not in out:
                    out.append(a)
    return out


def _price_clause(term: str, *columns: str) -> str:
    """The PostgREST OR clause for a price keyword, over named columns.

    Each column is matched for the term **and** for each alias, so `ဆန်ဈေး`
    reaches the `ပေါ်ဆန်းဆန်` row while a term that already matches is
    unchanged. This is the numbers-side counterpart of `_like_clause`.
    """
    parts: list[str] = []
    for t in _price_terms(term):
        for col in columns:
            parts.append(f"{col}.ilike.%{t}%")
    return ",".join(parts) or f"{columns[0]}.ilike.%{term}%"


def search_numbers(query: str, limit: int = 10, prices_only: bool = False) -> list[dict]:
    """Find figures whose context or headline mentions `query`.

    Sent to the database **untranslated** — the state papers are in Burmese and
    a translated keyword matches nothing. Measured 2026-09-29: the live rows use
    `ရွှေရည်ညွှန်းဈေးနှုန်း`, `ရန်ကုန် 92 Ron လက်လီဈေးနှုန်း`,
    `အမေရိကန်ဒေါ်လာ ငွေလဲလှယ်နှုန်း`.

    **But the word the reader says is not always the word the paper prints** —
    see `_PRICE_ALIASES`; `_price_clause` bridges it, as `_NEWS_ALIASES` does
    for the articles.

    `prices_only` keeps only currency rows. It exists because the alias is a
    **broad** word: measured 2026-09-30, `ဆန်ဈေး` expands to `ဆန်`, which is
    inside the whole page-2 table — the answer came back headed *"8 figures"*
    with one rice price and seven palm-oil / egg / ration rows. The unit is the
    test (`_is_price`), exactly as it is for `price_trend`.
    """
    term = str(query or "").strip()
    if not term:
        return []
    # PostgREST filter syntax treats , ( ) and % as structural; a term carrying
    # one is spliced into the or_() clause and breaks the query.
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")
    limit = max(1, min(int(limit or 10), MAX_ROWS))

    clause = _price_clause(term, "context", "headline")
    # **A broad alias must not be matched against `headline`.** Measured
    # 2026-09-30: `ဆန်` against both columns returned 18 rows — palm oil, eggs
    # and quotas with no rice in them — because `headline` is the story the
    # table sits under, not the row's own label. Against `context` alone it
    # returns exactly the 6 rice rows. The same trap `price_trend` avoids.
    if prices_only:
        clause = _price_clause(term, "context")

    def produce() -> list[dict]:
        # A broad alias needs a bigger fetch to filter down from, or the price
        # rows would be crowded out by the quantities.
        fetch = max(limit, 60) if prices_only else limit
        rows = (_get_client().table("newspaper_numbers")
                .select("publication_date,section,headline,value,unit,context,source_text")
                .or_(clause)
                .order("publication_date", desc=True)
                .limit(fetch).execute().data or [])
        if prices_only:
            rows = [r for r in rows if _is_price(r)]
        return rows[:limit]

    return _cached(f"searchnum:{term}:{limit}:{int(bool(prices_only))}", produce, [])


# ── The state papers ─────────────────────────────────────────────────────────

def search_articles(query: str, limit: int = 8) -> list[dict]:
    """Search the state papers (Myanma Alinn, The Mirror) by keyword."""
    term = str(query or "").strip()
    if not term:
        return []
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")
    limit = max(1, min(int(limit or 8), MAX_ROWS))

    def produce() -> list[dict]:
        return (_get_client().table("articles")
                .select("issue_date,newspaper_name,page_no,headline,summary")
                .or_(f"headline.ilike.%{term}%,body_text.ilike.%{term}%")
                .order("issue_date", desc=True)
                .limit(limit).execute().data or [])

    return _cached(f"arts:{term}:{limit}", produce, [])


def outlet_names() -> list[str]:
    """Which papers this database actually holds — asked, not assumed."""
    def produce() -> list[str]:
        rows = (_get_client().table("articles")
                .select("newspaper_name").limit(500).execute().data or [])
        return sorted({(r.get("newspaper_name") or "").strip()
                       for r in rows if (r.get("newspaper_name") or "").strip()})

    return _cached("outlets", produce, [])


# ── Coverage: what period this database can actually answer for ──────────────
#
# THE MOST IMPORTANT FUNCTION HERE.
#
# Measured 2026-09-29: 7,090 articles, but 7,073 of them are September 2026 and
# there is **nothing at all from 2025 or January-July 2026**. Ten stray rows sit
# on 2024-08-31 — a test batch — which is exactly the kind of outlier that makes
# `MIN(issue_date)` lie about coverage.
#
# So "ဒီသတင်းနဲ့ ပတ်သက်ပြီး အရင်က ရှိခဲ့ဖူးလား" has two possible answers and
# they are not the same thing:
#
#     "အရင် မရှိခဲ့ဘူး"      — a claim about the world
#     "ဒီကာလအတွင်း မတွေ့ပါ"   — a claim about this database
#
# For a journalist the first is a finding and the second is a limitation.
# Confusing them means reporting "this was never covered" on the strength of
# four weeks of data. Every answer this module produces carries the window.

def coverage() -> dict:
    """The window this database can honestly answer for.

    NOT `MIN(issue_date)`. Measured 2026-09-29: the table's oldest row is
    2024-08-31, but that is a **10-row test batch on a single day** — the next
    real coverage is September 2026. Reporting MIN/MAX would tell the user
    "this database covers two years" when it covers four weeks, which is the
    same lie the window line exists to prevent.

    So coverage is defined as the span of days that actually carry a newspaper:
    the oldest and newest date with at least `_MIN_DAY_ROWS` articles. On this
    data that skips the 2024 batch and the 7-row August batch, and lands on
    September.
    """
    _MIN_DAY_ROWS = 20

    def produce() -> dict:
        c = _get_client()
        # Walk a bounded number of distinct dates from each end. Distinct
        # issue_dates are few (one per publishing day) and ordered, so this is
        # cheap and avoids a full scan of 7,000 rows.
        def scan(desc: bool) -> str:
            seen: list[str] = []
            offset = 0
            while offset < 3000:
                rows = (c.table("articles").select("issue_date")
                        .order("issue_date", desc=desc)
                        .limit(1000).execute().data or [])
                if not rows:
                    break
                for r in rows:
                    d = (r.get("issue_date") or "").strip()
                    if d and (not seen or seen[-1] != d):
                        seen.append(d)
                # Stop once the distinct-date list is long enough to be useful.
                if len(seen) >= 40:
                    break
                offset += 1000
            for d in seen:
                n = (c.table("articles").select("id", count="exact")
                     .eq("issue_date", d).limit(1).execute().count or 0)
                if n >= _MIN_DAY_ROWS:
                    return d
            return seen[0] if seen else ""

        return {"oldest": scan(desc=False), "newest": scan(desc=True)}

    return _cached("coverage", produce, {"oldest": "", "newest": ""})


def _recent_floor(days: int) -> str:
    """The oldest date to include when the question is about *now*.

    `days=0` means no floor at all. Anything else is counted back from the
    newest date the database holds, NOT from the wall clock — the papers are
    loaded daily and the newest row may be today or yesterday, so counting from
    `date.today()` would silently return nothing on a morning when that day's
    paper has not arrived yet.

    Measured 2026-09-29: asked *"လက်ရှိဖြစ်ပေါ်နေတဲ့ မုန်တိုင်း"* the search went
    back to September 1 and answered with three weeks of history. **လက်ရှိ means
    now** — the user wanted the last day or two, and a three-week answer buries
    the thing he asked about.
    """
    if days <= 0:
        return ""
    def produce() -> str:
        rows = (_get_client().table("articles").select("issue_date")
                .order("issue_date", desc=True).limit(1).execute().data or [])
        newest = (rows[0].get("issue_date") if rows else "") or ""
        if not newest:
            return ""
        try:
            y, m, d = (int(x) for x in newest.split("-"))
            return (date(y, m, d) - timedelta(days=max(0, days - 1))).isoformat()
        except (TypeError, ValueError):
            return ""

    return _cached(f"floor:{days}", produce, "")


# Words a person says as one thing and the paper prints as several.
#
# Measured 2026-09-29: the user asked for `ကယ်ဆယ်ရေးထောက်ပံ့ရေး` to be searchable,
# and searching it returns **0** — the papers write `ကူညီကယ်ဆယ်ရေးနှင့်` and
# `ထောက်ပံ့` as separate words and never that exact compound.
#
# **`ကူညီ` is deliberately NOT in this table**, and that is the point of it being
# a measured list rather than a thesaurus. Counts without expansion:
#
#     ကယ်ဆယ်ရေး  74   ထောက်ပံ့ 106   ကူညီ 186
#
# `ကူညီ` is the largest and the least useful — it means "help" in any context,
# so it pulls in `လူမှုကူညီရေးအဖွဲ့` (a welfare association), `နည်းပညာ ကူညီပံ့ပိုးမှု`
# (technical support) and `PDF Game ဆော့ကစားခြင်း`. Expanding to it produced a
# result list about road paving and video games for a question about flood
# relief. **A term that matches a third of the corpus is not a synonym.**
#
# The two that remain are specific to relief work, and OR-ing them is the same
# shape as `_PRICE_ALIASES`: the gap was measured to lose a real answer, not
# guessed at. **The reported count is the union**, which is the honest number
# for "news about relief work".
_NEWS_ALIASES = {
    "ကယ်ဆယ်ရေး": ("ထောက်ပံ့",),
    "ထောက်ပံ့": ("ကယ်ဆယ်ရေး",),
    "ကူညီကယ်ဆယ်ရေး": ("ကယ်ဆယ်ရေး", "ထောက်ပံ့"),
}


def _expand(term: str) -> list[str]:
    """The term plus any measured aliases, deduplicated, order preserved."""
    out = [term]
    for key, aliases in _NEWS_ALIASES.items():
        if key in term:
            for a in aliases:
                if a not in out:
                    out.append(a)
    return out


def _like_clause(term: str) -> str:
    """The PostgREST OR clause for a keyword — in BOTH encodings.

    Measured 2026-09-29: the `articles` column mixes Zawgyi and Unicode, and a
    Unicode search misses the Zawgyi half entirely —

        ပြန်လည်  Unicode 641  |  ြပန်လည်  Zawgyi 118
        သတိပေး  Unicode  92  |  သတိေပး  Zawgyi  15

    So searching `ပြန်လည်` alone never finds 118 articles that contain it. Both
    forms are OR-ed, which is what makes those rows reachable. See
    `core/zawgyi.py` for why the conversion runs one way only.
    """
    from core.zawgyi import variants
    parts: list[str] = []
    for t in _expand(term):
        for v in variants(t):
            parts.append(f"headline.ilike.%{v}%,body_text.ilike.%{v}%")
    if not parts:
        parts = [f"headline.ilike.%{term}%,body_text.ilike.%{term}%"]
    return ",".join(parts)


def search_count(query: str, days: int = 0) -> int:
    """How many articles mention `query`. -1 when the count is unavailable.

    `days=0` searches the whole window; `days=2` limits it to the newest two
    days the database holds — which is what *"လက်ရှိ"* means.

    NOT routed through `_cached()`. That helper treats a falsy result as "no
    result" and returns its default — so a genuine count of **zero** came back
    as -1 and the tool said "ရေတွက်လို့ မရပါ" (could not count) instead of
    "မတွေ့ပါ" (nothing found). Zero is the single most important answer this
    function can give, and it was the one being swallowed. Measured 2026-09-29.
    """
    term = str(query or "").strip()
    if not term:
        return 0
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")

    if _get_client() is None:
        return -1
    try:
        q = (_get_client().table("articles")
             .select("id", count="exact").or_(_like_clause(term)))
        floor = _recent_floor(days)
        if floor:
            q = q.gte("issue_date", floor)
        r = q.limit(1).execute()
        return int(r.count or 0)
    except Exception as e:                                  # noqa: BLE001
        print(f"[Reporter] count:{term} failed: {type(e).__name__}: {e}")
        return -1


def date_range_for(query: str, days: int = 0) -> dict:
    """(oldest, newest) among the articles matching `query`."""
    term = str(query or "").strip()
    if not term:
        return {}
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")

    def produce() -> dict:
        c = _get_client()
        floor = _recent_floor(days)

        def edge(desc: bool):
            q = (c.table("articles").select("issue_date")
                 .or_(_like_clause(term)).order("issue_date", desc=desc))
            if floor:
                q = q.gte("issue_date", floor)
            return q.limit(1).execute().data or []

        old, new = edge(False), edge(True)
        return {"oldest": (old[0].get("issue_date") if old else "") or "",
                "newest": (new[0].get("issue_date") if new else "") or ""}

    return _cached(f"range:{term}:{days}", produce, {})


def articles_on(date: str, query: str = "", limit: int = 8,
                paper: str = "") -> list[dict]:
    """One day's articles, optionally narrowed by keyword and/or paper.

    `paper` matches `newspaper_name` as a substring, so `'မြန်မာ့အလင်း'` works and
    so does a shorter fragment. It exists because the two state papers are
    **not** equally complete in this database — measured 2026-09-30, on
    2026-09-29: ကြေးမုံ has 328 rows with a median body of 836 characters, and
    မြန်မာ့အလင်း has 29 rows whose bodies are 55-character page markers. A
    question that names one paper must be able to read only that paper, or a
    thin paper is answered from the fat one and the user is told the wrong
    paper said it.
    """
    day = str(date or "").strip()
    if not day:
        return []
    term = str(query or "").strip()
    if term and any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")
    paper = str(paper or "").strip()
    limit = max(1, min(int(limit or 8), MAX_ROWS))

    def produce() -> list[dict]:
        q = (_get_client().table("articles")
             .select("issue_date,newspaper_name,page_no,headline,body_text,summary")
             .eq("issue_date", day))
        if paper:
            q = q.ilike("newspaper_name", f"%{paper}%")
        if term:
            q = q.or_(_like_clause(term))
        return q.order("newspaper_name").limit(limit).execute().data or []

    return _cached(f"day:{day}:{term}:{paper}:{limit}", produce, [])


def timeline(query: str, limit: int = 10, days: int = 0) -> list[dict]:
    """Articles mentioning `query`, oldest first — for 'was this covered before'."""
    term = str(query or "").strip()
    if not term:
        return []
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")
    limit = max(1, min(int(limit or 10), MAX_ROWS))

    def produce() -> list[dict]:
        q = (_get_client().table("articles")
             .select("issue_date,newspaper_name,page_no,headline,body_text")
             .or_(_like_clause(term)))
        floor = _recent_floor(days)
        if floor:
            q = q.gte("issue_date", floor)
        return q.order("issue_date", desc=False).limit(limit).execute().data or []

    return _cached(f"timeline:{term}:{limit}:{days}", produce, [])


def days_for(query: str, limit: int = 40, days: int = 0) -> list[dict]:
    """Which days carry `query` — one row per day, with a count.

    For *"စက်တင်ဘာ ဘယ်နှစ်ရက်က ဦးမင်းအောင်လှိုင် သတင်းရှိလား"*. A flat list of 85
    articles answers a different question; the user wants to know which days,
    then pick one. `fn_get_daily_briefing` does not do this — it takes a date
    and returns everything, and takes no keyword at all.
    """
    term = str(query or "").strip()
    if not term:
        return []
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")

    def produce() -> list[dict]:
        q = (_get_client().table("articles")
             .select("issue_date,newspaper_name")
             .or_(_like_clause(term)))
        floor = _recent_floor(days)
        if floor:
            q = q.gte("issue_date", floor)
        rows = q.order("issue_date", desc=False).limit(4000).execute().data or []
        tally: dict[str, dict] = {}
        for r in rows:
            d = (r.get("issue_date") or "").strip()
            if not d:
                continue
            slot = tally.setdefault(d, {"date": d, "count": 0, "papers": set()})
            slot["count"] += 1
            paper = (r.get("newspaper_name") or "").strip()
            if paper:
                slot["papers"].add(paper)
        out = [{"date": v["date"], "count": v["count"],
                "papers": sorted(v["papers"])} for v in tally.values()]
        return out[-limit:]

    return _cached(f"days:{term}:{limit}:{days}", produce, [])


# ── Prices over time ─────────────────────────────────────────────────────────
#
# `newspaper_numbers` holds more than prices, and the difference matters.
# Measured 2026-09-29, a search for `ဆန်` returns three different kinds of row:
#
#     ပေါ်ဆန်းဆန်တစ်ပြည်ဈေးနှုန်း             3500 ကျပ်   ← a price
#     တစ်ဦးလျှင်ဝယ်ယူခွင့်ရှိသော ဆန်ပမာဏ        1 ပြည်     ← a ration
#     ရောင်းချပေးခဲ့သည့် ဆန်အိတ်ရေ             2 အိတ်     ← a count
#
# Only the first is comparable over time. **The unit is the test**: a row whose
# unit is a currency is a price, and everything else is a quantity that happens
# to share the keyword. Averaging a ration with a price would produce a number
# that means nothing, so only currency rows are eligible.

def _is_price(row: dict) -> bool:
    """True when the row's unit is a **currency** — the one thing that separates
    a price from a quantity.

    The forms the papers use: `ကျပ်` alone, `ကျပ်/လီတာ` (per litre),
    `ကျပ်/ပြည်`, `ကျပ်/ပိဿာ`, `ကျပ်/သား`, `ကျပ် တစ်ပိဿာ` (per viss).

    **The separator is load-bearing.** `ကျပ်သား` is a *weight* (kyattha) — it
    merely starts with the currency word, so a bare `startswith("ကျပ်")` counted
    *"the amount of palm oil one person may buy — ၅၀ ကျပ်သား"* and *"palm-oil
    ration per household"* as prices. Measured 2026-09-30: **4 such rows**, all
    quotas. A ration is not a price, and averaging it into a series produces a
    number that means nothing.

    A currency unit is therefore exactly `ကျပ်`, or `ကျပ်` followed by a
    separator (`/` or a space) and a per-unit noun — never a compound that
    merely begins with it. `သိန်းကျပ်` ("hundred thousand kyat") is likewise not
    a unit this test accepts: it labels a *value*, not a price.
    """
    unit = (row.get("unit") or "").strip()
    if unit.lower() in ("kyat", "mmk"):
        return True
    if unit == "ကျပ်":
        return True
    return unit.startswith("ကျပ်/") or unit.startswith("ကျပ် ")


# Grammatical / orthographic noise in a `context` — **never a semantic word.**
# The papers set the same headline with and without a space, with and without the
# possessive `၏`, with and without the conditional `လျှင်` ("per"), and with and
# without the verb phrase `ရောင်းချသည့်` ("that is sold"). None of those change
# *what is being priced*, so folding them lets one commodity be one series.
#
# Deliberately NOT here: `ရည်ညွှန်းဈေး` ("reference price") vs `ရောင်းချသည့်ဈေး`
# ("selling price") — plausibly different official numbers; `အခြေခံလက်ကား` (base
# wholesale) vs retail; `တစ်ပိဿာ` vs `တစ်ကျပ်သား` (different units). Folding any
# of those would merge two genuinely different figures, which is the one failure
# this table must never cause.
_PRICE_NOISE = (" ", "\u200b", "၏", "လျှင်", "ရောင်းချသည့်")


def _canon_price_key(context: str) -> str:
    """A commodity's name with only its spelling noise removed.

    Measured 2026-09-30: 63 distinct price contexts fold to 55, and **none of
    the folds puts two different values on one date** — the check
    `check_agent.py` now runs. Gold alone is written six ways
    (`စံချိန်မီရွှေ တစ်ကျပ်သား ဈေးနှုန်း`, `…ဈေးနှုန်း` with no space,
    `…တစ်ကျပ်သား၏ ဈေးနှုန်း`, …), so one series of seven days looked like six
    series of one and none of them could be compared.

    Folding is only ever applied where the data agrees with it — see
    `price_trend`, which falls back to the exact context if a fold would put two
    different values on one date.
    """
    text = str(context or "")
    for noise in _PRICE_NOISE:
        text = text.replace(noise, "")
    return text


def _number(value) -> Optional[float]:
    """The numeric value of a row, or None. Values arrive as strings and may be
    Burmese digits or carry separators."""
    text = str(value or "").strip()
    if not text:
        return None
    text = text.translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789"))
    text = text.replace(",", "").replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return None


def price_trend(query: str) -> list[dict]:
    """Price rows grouped by commodity, each with its dated values.

    THE LIMIT THIS EXPOSES, measured 2026-09-29 and worth stating plainly:
    of the 73 price rows, **only four commodities appear on more than one date**
    — Octane 92, Octane 95, Diesel and Premium Diesel. Rice, egg, palm oil and
    gold each appear on exactly **one day**, so "how has this changed since
    yesterday" has no answer for them and must not be invented.

    Grouping is by the exact `context` string, because that is the only thing
    that says two rows are the same commodity. It works for the fuel grades —
    `Octane 92 ရည်ညွှန်းလက်ကားဈေး` is spelled identically every day. It does NOT
    work for palm oil, which the papers write four different ways
    (`စားအုန်းဆီ ရည်ညွှန်းဈေးနှုန်း`, `စားအုန်းဆီတစ်ပိဿာဈေးနှုန်း`, …) — so those
    rows each look like a series of one. Fuzzy-matching the contexts would
    guess at which strings mean the same thing, and a wrong guess here is a
    wrong price. Better to report one day than to compare two different things.

    Returns a list of {context, unit, points: [{date, value}], ...} oldest-first.
    """
    term = str(query or "").strip()
    if not term:
        return []
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")

    # The fuel grades are named in Latin and contain no Burmese word for fuel:
    # `Octane 92 ရည်ညွှန်းလက်ကားဈေး`. So a search for `ဆီ` — the word a person
    # actually uses — found cooking oil and missed every grade that can be
    # compared over time. The alias table closes that gap without touching how
    # anything is stored.
    terms = [term]
    for key, aliases in _PRICE_ALIASES.items():
        if key in term:
            terms.extend(aliases)
    terms = list(dict.fromkeys(terms))

    def produce() -> list[dict]:
        # `context` only — NOT the headline. Measured: the page-2 rows share one
        # headline listing every commodity, so matching the headline returned
        # the whole page for any keyword, which is how a search for `ဆန်` came
        # back with cooking oil and eggs.
        seen: list[dict] = []
        for t in terms:
            rows = (_get_client().table("newspaper_numbers")
                    .select("publication_date,context,value,unit")
                    .ilike("context", f"%{t}%")
                    .order("publication_date", desc=False)
                    .limit(400).execute().data or [])
            seen.extend(rows)

        # Only a currency unit is a price, and only a figure is a point.
        rows = []
        for r in seen:
            if not _is_price(r):
                continue
            value = _number(r.get("value"))
            if value is None:
                continue
            rows.append({
                "context": (r.get("context") or "").strip(),
                "unit": (r.get("unit") or "").strip(),
                "date": (r.get("publication_date") or ""),
                "value": value,
            })

        # Decide the grouping key. Normally the spelling-folded commodity name,
        # so the six ways the papers write gold are one series and can be
        # compared. **But a fold is only used where the data agrees with it:**
        # two spellings of one commodity must not carry different values on the
        # same date. If they ever do, they are not the same commodity (or the
        # extraction is wrong), and the exact context is kept instead. Guessing
        # which strings are equal is how a wrong price gets spoken, so the
        # fallback is per-key and automatic rather than a judgement call.
        #
        # The **unit is deliberately not part of the key**. Measured 2026-09-30:
        # palm oil's `စားအုန်းဆီအခြေခံလက်ကား ရည်ညွှန်းဈေးနှုန်း` is stored twice on
        # one date — once as `ကျပ် တစ်ပိဿာ` and once as bare `ကျပ်`, both ၇၁၇၉.
        # Same date, same figure, one fact; the extraction just caught the
        # per-unit suffix on one copy. Keying on the unit kept them apart and
        # cost palm oil a second comparable day. The same-date guard below is
        # what keeps this safe: units are only folded when they agree.
        _seen_vals: dict[str, dict] = {}
        for r in rows:
            canon = _canon_price_key(r["context"])
            _seen_vals.setdefault(canon, {}).setdefault(r["date"], set()).add(r["value"])
        unsafe = {c for c, bydate in _seen_vals.items()
                  if any(len(v) > 1 for v in bydate.values())}

        groups: dict = {}
        for r in rows:
            canon = _canon_price_key(r["context"])
            key = (r["context"], r["unit"]) if canon in unsafe else canon
            slot = groups.setdefault(key, {"context": r["context"],
                                           "canon": canon,
                                           "unit": r["unit"],
                                           "units": [],
                                           "spellings": [],
                                           "points": []})
            if r["unit"] not in slot["units"]:
                slot["units"].append(r["unit"])
            if r["context"] not in slot["spellings"]:
                slot["spellings"].append(r["context"])
            point = {"date": r["date"], "value": r["value"]}
            if point not in slot["points"]:
                slot["points"].append(point)

        # Name each group by its **most common exact spelling** — the folded key
        # has the spaces stripped and reads cramped aloud. Ties go to the longer
        # string, which is the one that kept its spaces. The unit is chosen the
        # same way, since a fold may have joined a bare `ကျပ်` with the more
        # specific `ကျပ် တစ်ပိဿာ` the paper also printed.
        for slot in groups.values():
            slot["context"] = max(
                slot["spellings"],
                key=lambda s: (sum(1 for r in rows if r["context"] == s), len(s)),
            )
            slot["unit"] = max(
                slot["units"],
                key=lambda u: (sum(1 for r in rows if r["unit"] == u), len(u)),
            )
        return list(groups.values())

    return _cached(f"trend:{'|'.join(terms)}", produce, [])


# What a person calls a thing vs what the paper prints. Only where the gap was
# measured to lose a real answer — not a general thesaurus.
#
# Fuel (2026-09-29): the paper writes the grade (`Octane 92`, `Diesel`), the
# reader says `ဆီဈေး` — a search for `ဆီဈေး` found none of the four live rows.
#
# Staples (2026-09-30): *"ဒီနေ့ ဆန်ဈေးနှုန်း အခြေအနေဘယ်လိုရှိလဲ"* —
#     ဆန်ဈေးနှုန်း → 0 rows   ဆန်ဈေး → 0 rows
#     ဆန်         → 18 rows  ပေါ်ဆန်းဆန် → the price row (၃,၅၀၀ ကျပ်)
# The paper names the **variety** (`ပေါ်ဆန်းဆန်`), never the generic `ဆန်ဈေး`.
# **The generic word is ADDED, not substituted** — `ဆန်` is inside all three
# live rows and `ဆန်ဈေး` inside none, so keeping both is what makes the row
# reachable without losing an exact match.
_PRICE_ALIASES = {
    "ဆီ": ("Octane", "Diesel"),
    "စက်သုံးဆီ": ("Octane", "Diesel"),
    "ဆီဈေး": ("Octane", "Diesel"),
    "လောင်စာ": ("Octane", "Diesel"),
    "ဆန်ဈေးနှုန်း": ("ဆန်", "ဆန်း"),
    "ဆန်ဈေး": ("ဆန်", "ဆန်း"),
    "ဆန်": ("ဆန်း",),
    "ကြက်ဥဈေး": ("ကြက်ဥ",),
    "ကြက်ဥ": (),
    "စားအုန်းဆီ": (),
    "ရွှေဈေးနှုန်း": ("ရွှေရည်ညွှန်းဈေးနှုန်း", "ရွှေ"),
    "ဒေါ်လာဈေးနှုန်း": ("ဒေါ်လာ",),
}


# A PDF whose text layer failed extracts as glyph indices — `/g167/g136/g3/...`.
# Measured 2026-09-29: **646 of 7,090 rows (9%)** are this. They are searchable
# garbage: a keyword search can match one and the assistant would read out
# slash-g-numbers as if it were news. Detected and skipped by name.
#
# **`/g\d+` alone was too narrow.** Measured 2026-10-01 against the source PDFs:
# pypdf emits glyph names in two spellings for the same paper — `/g167` for one
# embedded font and **`/R194`** for another (the two papers' fonts differ, and
# `ingest_engine` had the same hole, which is why 29 of 32 မြန်မာ့အလင်း pages
# were accepted as "text"). A row stored from an `/R###` page would have been
# read out as news. The general form is safe: measured **0 matches in 325,695
# characters** of the clean ကြေးမုံ issue, against 313,751 in the broken one.
import re as _re                                            # noqa: E402
_GLYPH_NOISE = _re.compile(r"/[A-Za-z]+\d+(?:/[A-Za-z]+\d+){3,}")


def is_unreadable(article: dict) -> bool:
    """True when this row's text is glyph indices, not Burmese."""
    text = (article.get("body_text") or article.get("summary") or "")
    return bool(_GLYPH_NOISE.search(text))


def readable_only(articles: list[dict]) -> list[dict]:
    """Drop the rows that would read out as slash-g-numbers."""
    return [a for a in articles if not is_unreadable(a)]


def content_rows(articles: list[dict]) -> list[dict]:
    """Rows that carry news text — neither glyph noise nor a page marker."""
    return [a for a in readable_only(articles) if not is_placeholder(a)]


def paper_counts(day: str) -> dict[str, int]:
    """How many rows each paper has for `day`. {} when the read failed.

    This is the function that turns "no news that day" into the truth, which is
    usually narrower: the day has news, *this paper* does not. An empty dict is
    deliberately distinct from a dict of zeroes — one is a failed lookup, the
    other is a real, empty day.
    """
    d = str(day or "").strip()
    if not d:
        return {}

    def produce() -> dict[str, int]:
        rows = (_get_client().table("articles")
                .select("newspaper_name").eq("issue_date", d)
                .limit(4000).execute().data or [])
        tally: dict[str, int] = {}
        for r in rows:
            name = (r.get("newspaper_name") or "").strip()
            if name:
                tally[name] = tally.get(name, 0) + 1
        # A day with rows that all carry an unknown name still counts as read.
        return tally or {"": 0}

    got = _cached(f"papers:{d}", produce, None)
    if got is None:
        return {}
    return got


def papers_with_content(day: str) -> dict[str, int]:
    """Which papers have *real* articles for `day`, and how many each.

    The distinction `paper_counts` cannot make on its own: မြန်မာ့အလင်း has 29
    rows on 2026-09-29 and **zero** of them are news. Returns {} on a failed
    read, like `paper_counts`.
    """
    d = str(day or "").strip()
    if not d:
        return {}

    def produce() -> dict[str, int]:
        rows = (_get_client().table("articles")
                .select("newspaper_name,headline,body_text,summary")
                .eq("issue_date", d).limit(4000).execute().data or [])
        tally: dict[str, int] = {}
        for r in rows:
            if is_unreadable(r) or is_placeholder(r):
                continue
            name = (r.get("newspaper_name") or "").strip()
            if name:
                tally[name] = tally.get(name, 0) + 1
        return tally or {"": 0}

    return _cached(f"paperscontent:{d}", produce, {})


# `articles_on` is capped at MAX_ROWS because it feeds a spoken list. A
# distinct-entity question is different: "which ministers appear today" needs to
# read **the whole day**, and a cap of 25 truncates the answer — measured
# 2026-09-30, reading 25 rows surfaced 3 people where the full 328 rows name 12.
# This is a deliberately separate reader with a much higher ceiling, used only
# by the entity actions, so the spoken-list tools keep their small bound.
_ENTITY_ROWS = 2000


def all_articles_on(date: str, paper: str = "") -> list[dict]:
    """Every row for `day` (optionally one paper), for entity extraction.

    Not for speaking — this returns page markers and glyph noise along with the
    real articles, and the caller filters with `content_rows`. Returns [] on a
    failed read, like everything else here; use `paper_counts` to tell the two
    apart.
    """
    day = str(date or "").strip()
    if not day:
        return []
    paper = str(paper or "").strip()

    def produce() -> list[dict]:
        q = (_get_client().table("articles")
             .select("issue_date,newspaper_name,page_no,headline,body_text,summary")
             .eq("issue_date", day))
        if paper:
            q = q.ilike("newspaper_name", f"%{paper}%")
        return q.limit(_ENTITY_ROWS).execute().data or []

    return _cached(f"allarts:{day}:{paper}", produce, [])


def editions_with_content(limit: int = 10) -> list[str]:
    """The newest issue dates that carry *real* articles, newest first.

    **A date is not a day until it has been read.** Measured 2026-09-30: the
    database's newest `issue_date` had advanced to 2026-09-30 while the
    ingestion was still running — at 10:1x that day held 23 မြန်မာ့အလင်း page
    markers and 8 ကြေးမုံ rows, and every one of the 8 was a market table,
    a weather bulletin or a single article about Malaysia. Asked "which
    officials are in today's paper" with no date, the entity actions read
    `coverage()['newest']` → 2026-09-30, found no rank+name pair at all, and
    would have answered *"no officials named"* about an edition that had not
    finished loading.

    `coverage()` cannot tell the caller this: it only requires 20 rows of any
    kind, so a half-ingested day passes. **This function asks the question that
    matters — does this day contain news text?** — and walks back until it
    finds a day that does, returning the days in order. It returns [] when the
    read fails, like everything else here; the caller must not treat [] as
    "no edition has news".
    """
    n = max(1, min(int(limit or 10), 30))

    def produce() -> list[str]:
        c = _get_client()
        # Distinct dates near the top, newest first. Bounded, like `coverage`:
        # distinct issue_dates are few and ordered, so this walks a few pages
        # of the newest rows rather than scanning the table.
        seen: list[str] = []
        offset = 0
        while offset < 2000 and len(seen) < n * 3:
            rows = (c.table("articles").select("issue_date")
                    .order("issue_date", desc=True)
                    .range(offset, offset + 999).execute().data or [])
            if not rows:
                break
            for r in rows:
                d = (r.get("issue_date") or "").strip()
                if d and d not in seen:
                    seen.append(d)
            offset += 1000
        out: list[str] = []
        for d in seen:
            # `papers_with_content` is the same read `_paper_scope` uses, so the
            # day chosen here is the day the paper-scope sentence is about —
            # one definition of "has content", not two.
            if sum(papers_with_content(d).values()):
                out.append(d)
                if len(out) >= n:
                    break
        return out

    return _cached(f"editions:{n}", produce, [])


def all_articles_matching(query: str, days: int = 0) -> list[dict]:
    """Every row whose text mentions `query`, for entity extraction.

    The entity counterpart of `timeline` — same filter, a much higher ceiling,
    and newest-first because "who is mentioned about X" is usually asked about
    now rather than about the first time it appeared.
    """
    term = str(query or "").strip()
    if not term:
        return []
    if any(ch in term for ch in ",()%"):
        term = "".join(ch for ch in term if ch not in ",()%")

    def produce() -> list[dict]:
        q = (_get_client().table("articles")
             .select("issue_date,newspaper_name,page_no,headline,body_text,summary")
             .or_(_like_clause(term)))
        floor = _recent_floor(days)
        if floor:
            q = q.gte("issue_date", floor)
        return q.order("issue_date", desc=True).limit(_ENTITY_ROWS).execute().data or []

    return _cached(f"allmatch:{term}:{days}", produce, [])


# A page-level row carries a headline that names the paper and the page rather
# than the story — "မြန်မာ့အလင်း သတင်းစာ (၂၀၂၆ ခုနှစ်၊ စက်တင်ဘာလ ၂၉ ရက်)". It is
# not junk: on page 2 that row **is** the fuel and gold table, which is what
# `newspaper_numbers` is built from. But read aloud it says nothing, so it is
# replaced with what the page actually contains.
_PAGE_HEADLINE = _re.compile(
    r"^\s*(မြန်မာ့အလင်း|ကြေးမုံ|ကျေးမုံ)?\s*သတင်းစာ\s*[\(\（]?\s*(စာမျက်နှာ|\d)")


# The page-level body opens with the paper's own boilerplate before it says
# anything: "မြန်မာ့အလင်း သတင်းစာ စာမျက်နှာ (၂) ပါ သတင်းအချက်အလက်များနှင့် …".
# Read aloud it is six words of nothing before the first fact, so it is cut.
_BOILERPLATE = _re.compile(
    r"^\s*.*?သတင်းစာ\s*[\(\（]?\s*စာမျက်နှာ\s*"
    r"[\(\（]?\s*[၀-၉0-9]+\s*[\)\）]?\s*"          # the page number, which the
    r"(ပါ\s*သတင်းအချက်အလက်များ(နှင့်|ကို|တွင်|အရ)?"   # first attempt forgot to eat
    r"|တွင်\s*ဖော်ပြထားသော\s*သတင်းအချက်အလက်များ(အရ)?)\s*")


# ── Placeholder rows: a page that exists but carries no news ─────────────────
#
# Measured 2026-09-30. Asked *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာထဲ ဘယ်ဝန်ကြီးတွေ ပါသလဲ"*,
# the assistant answered nothing, and the reason was not the network. On
# 2026-09-29 the database holds
#
#     ကြေးမုံ        328 rows   median body  836 chars
#     မြန်မာ့အလင်း    29 rows   median body   55 chars
#
# and every one of the 29 Myanma Alinn bodies is a single sentence —
# *"မြန်မာ့အလင်းသတင်းစာ စာမျက်နှာ (၁) ပါ သတင်းအချက်အလက်များ"* — the paper's name
# and the page number. The article text was never extracted for that paper;
# one row per page survived and its body is the masthead.
#
# So for that paper a `day` query returns 29 rows that **look** like a full
# newspaper and say nothing at all. Reading them aloud is worse than reading
# nothing, and counting them makes "29 articles" a lie. They are detected and
# reported as what they are: the paper is in the database by name, its content
# is not.

# The body is a page pointer: it names a page number and says
# "သတင်းအချက်အလက်များ" — "the information on page N". Measured 2026-09-30, all
# 24 real markers carry both, in every word order the pipeline produced:
#
#     မြန်မာ့အလင်းသတင်းစာ စာမျက်နှာ (၁) ပါ သတင်းအချက်အလက်များ
#     စက်တင်ဘာလ ၂၉ ရက်နေ့ထုတ် မြန်မာ့အလင်းသတင်းစာ စာမျက်နှာ (၂) ပါ …နှင့်
#     မြန်မာ့အလင်းသတင်းစာမှ … စာမျက်နှာ ၁၂ ပါ သတင်းအချက်အလက်များ။
#     မြန်မာ့အလင်းသတင်းစာ၏ ၂၀၂၆ ခုနှစ်၊ … စာမျက်နှာ ၉ ပါ သတင်းအချက်အလက်များနှင့်
#
# An earlier attempt also required the paper's name and the words "သတင်းစာ
# စာမျက်နှာ" to be adjacent. Both were wrong: the date sits between them in
# several real rows, so four markers survived it. The two features that are
# always present — and that a real news sentence does not carry — are the page
# pointer and the "သတင်းအချက်အလက်များ" stamp, and they are the whole test now.
_PAGE_POINTER = _re.compile(r"စာမျက်နှာ\s*[\(\（]?\s*[၀-၉0-9]")
_PLACEHOLDER_MARK = _re.compile(r"သတင်းအချက်အလက်များ")

# A genuine article is hundreds of characters; the measured markers run 55-130.
# The ceiling is deliberately loose because a very short real brief exists, and
# the two-part pattern above is what actually decides.
_PLACEHOLDER_MAX = 300


def is_placeholder(article: dict) -> bool:
    """True when this row is a page pointer, not news.

    Both of: the body is short, and it names a page number and says
    "သတင်းအချက်အလက်များ". Every measured marker carries both; a real news
    sentence carries neither, so a genuinely short brief is kept.
    """
    body = (article.get("body_text") or article.get("summary") or "").strip()
    if not body:
        return True
    if len(body) > _PLACEHOLDER_MAX:
        return False
    return bool(_PAGE_POINTER.search(body) and _PLACEHOLDER_MARK.search(body))


def display_headline(article: dict, width: int = 70) -> str:
    """A headline worth reading out, falling back to the page's content.

    Measured 2026-09-29: a `ဆီဈေး` search returned six state-paper rows whose
    headline was the page marker and nothing else. The user learns nothing from
    them, and the rows are the ones carrying the price table — so they are kept
    and described, not dropped. The paper's own boilerplate is cut for the same
    reason: it is the first thing read out and the last thing worth hearing.
    """
    head = (article.get("headline") or "").strip()
    if head and not _PAGE_HEADLINE.match(head):
        return head
    body = (article.get("body_text") or article.get("summary") or "").strip()
    body = _re.sub(r"\s+", " ", _BOILERPLATE.sub("", body)).strip()
    if body:
        page = article.get("page_no")
        # Burmese digits, like every other number this assistant speaks.
        from core.timefmt import to_burmese_digits
        lead = f"စာမျက်နှာ {to_burmese_digits(page)} — " if page else ""
        return f"{lead}{body[:width]}"
    return head


# ── Sections (ကဏ္ဍ) ──────────────────────────────────────────────────────────
#
# The owner's ask, 2026-09-30: index the paper into sections and answer
# "today's State President news?" from the section rather than from a keyword
# sweep. The classification itself lives in `core/news_sections.py` — one
# definition, used by both the writer here and the reader in the action.
#
# WHERE IT IS STORED — and the write path is not the read path
#
# `articles` is a **view**, and not an updatable one. Measured 2026-09-30, an
# update against it returns
#
#     cannot update view "articles" … Views that do not select from a single
#     table or view are not automatically updatable.
#
# so every write attempted through it failed while every read succeeded — the
# worst possible split, because the index reported "0 written" only after it had
# already claimed the work was done.
#
# The **base table is `newspaper_articles`**, and `articles` is a compatibility
# view over it that renames the columns:
#
#     newspaper_articles            articles (view)
#     ────────────────────────      ─────────────────────────
#     section                    →  article_type
#     publication_date           →  issue_date
#     page_number                →  page_no
#     article_text               →  body_text
#     subheadline                →  subhead
#
# Same 7,510 rows, same ids, same values — verified id for id. Writing
# `newspaper_articles.section` is therefore writing the section, and it is the
# **only** writable route: `newspaper_articles.section` accepts an update,
# `articles.article_type` does not exist as a writable column at all.
#
# The field is otherwise unused: 7,572 of 7,745 rows carry the literal default
# `'General'`, the rest are an abandoned 2026-09-01..10 experiment, and neither
# project contains any code that reads or writes it.

_SECTION_TABLE = "newspaper_articles"
_SECTION_FIELD = "section"


def _section_reader_rows(day: str = "", days: int = 0, paper: str = "",
                         limit: int = _ENTITY_ROWS,
                         offset: int = 0) -> list[dict]:
    """Rows carrying everything the classifier needs, newest first.

    A separate reader from `all_articles_on` because this one also asks for
    `article_type` — the stored section — which nothing else selects. Bounded
    by `_ENTITY_ROWS` for the same reason the entity readers are: a day of
    ကြေးမုံ is ~300 rows and a cap of 25 would answer about a twelfth of the
    paper while sounding complete.

    `offset` exists for the indexing pass, which has to walk the **whole**
    table. Without it the newest `_ENTITY_ROWS` rows were re-read on every
    round and the older rows could never be reached — the index would report
    "everything is indexed" while most of the corpus was not, because the rows
    it kept re-reading were the ones it had just written.
    """
    day = str(day or "").strip()
    paper = str(paper or "").strip()
    n = max(1, min(int(limit or _ENTITY_ROWS), _ENTITY_ROWS))
    off = max(0, int(offset or 0))

    def produce() -> list[dict]:
        q = (_get_client().table("articles")
             .select("id,issue_date,newspaper_name,page_no,headline,body_text,"
                     "summary,article_type"))
        if day:
            q = q.eq("issue_date", day)
        else:
            floor = _recent_floor(days)
            if floor:
                q = q.gte("issue_date", floor)
        if paper:
            q = q.ilike("newspaper_name", f"%{paper}%")
        q = q.order("issue_date", desc=True)
        return (q.range(off, off + n - 1).execute().data or [])

    return _cached(f"secrows:{day}:{days}:{paper}:{n}:{off}", produce, [])


def _section_of_row(row: dict, classify_on_read: bool = True) -> str:
    """The row's section — the stored one when there is one, else computed.

    **The fallback is the point.** The pipeline keeps ingesting, and a row that
    arrives after the last indexing run carries the default `'General'`. If the
    reader only trusted the stored value, a section question asked the morning
    after an un-indexed day would answer "nothing in this section" about a
    paper full of it — a limitation spoken as a finding, which is the defect
    this project has already paid for twice. So an un-indexed row is classified
    on the spot, and `store_section` is what makes that cheap next time.
    """
    from core.news_sections import OTHER, classify, section_of
    stored = section_of(row)
    if stored:
        return stored
    if not classify_on_read:
        return ""
    label, _why = classify(row)
    return label if label else OTHER


def _story_key(row: dict) -> str:
    """The identity of a story, for collapsing rows that carry the same one.

    The headline, whitespace-normalised — measured 2026-09-30: the pipeline
    stores the same story on two rows (identical headline and page), so a
    section answer for 2026-09-29 listed the president's university visit
    **twice**. A keyword search tolerates that; a spoken list does not, and a
    count that includes the duplicate is wrong in the one place the user cannot
    re-read it.

    One definition, used by both the list and the tally, so the number spoken
    and the number listed can never disagree.
    """
    return _re.sub(r"\s+", "", (row.get("headline") or "")).strip()


def articles_by_section(section: str, day: str = "", days: int = 0,
                        paper: str = "", limit: int = 8) -> list[dict]:
    """The readable articles in `section`, newest first, one row per story.

    Filters on the section **and** on `content_rows`, so a page marker or a
    glyph-noise row never reaches the answer: those rows are in every section
    by accident and say nothing. Duplicate rows of one story are collapsed —
    see `_story_key`.
    """
    from core.news_sections import LABELS
    want = str(section or "").strip()
    if want not in LABELS:
        return []
    n = max(1, min(int(limit or 8), MAX_ROWS))

    rows = content_rows(_section_reader_rows(day, days, paper))
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        if _section_of_row(r) != want:
            continue
        key = _story_key(r)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(r)
        if len(out) >= n:
            break
    return out


def section_tally(day: str = "", days: int = 0, paper: str = "") -> dict:
    """How many readable articles each section holds, in the same window.

    Counted over `content_rows` for the same reason `articles_by_section` is:
    the 646 glyph-noise rows and the မြန်မာ့အလင်း page markers would otherwise
    inflate whichever section their garbage happened to match.

    Returns a dict; `{}` means the read failed (use `paper_counts` to tell it
    from a real, empty result, as everywhere else here).
    """
    from core.news_sections import LABELS

    rows = content_rows(_section_reader_rows(day, days, paper))
    if not rows:
        return {}
    tally: dict[str, int] = {label: 0 for label in LABELS}
    # Counted per **story**, not per row, so the number spoken in the header and
    # the number listed underneath come from one definition — see `_story_key`.
    counted: dict[str, set[str]] = {}
    for r in rows:
        label = _section_of_row(r)
        key = _story_key(r)
        if key:
            bucket = counted.setdefault(label, set())
            if key in bucket:
                continue
            bucket.add(key)
        tally[label] = tally.get(label, 0) + 1
    return tally


def unindexed_rows(day: str = "", days: int = 0, offset: int = 0,
                   limit: int = 1000) -> list[dict]:
    """One page of readable rows whose stored section is not yet one of ours.

    What the indexing pass works on. A row is *unindexed* when its
    `article_type` is not one of `news_sections.LABELS` — which covers the
    literal `'General'` default and the abandoned English labels alike, since
    both mean "never indexed by this system".

    **Paged rather than capped.** The caller walks `offset` upward until a page
    comes back empty. A single capped read was the first version and it was
    silently wrong: it returned the newest 2,000 rows every time, so once those
    were written the pass reported "everything is indexed" with 5,500 rows
    still untouched. `content_rows` is applied per page, so a page can return
    fewer than `limit` rows without meaning the end — the caller must page to
    an **empty** page, not to a short one.
    """
    from core.news_sections import LABELS

    rows = content_rows(_section_reader_rows(day=day, days=days, limit=limit,
                                             offset=offset))
    return [r for r in rows
            if str(r.get("article_type") or "").strip() not in LABELS]


def stored_section_counts() -> dict:
    """How many rows the **database** holds per stored section value.

    Read straight from the column the write goes to — `newspaper_articles.section`,
    not the `articles` view — because a verification that reads a different
    relation from the one written is not a verification. Used to confirm a write
    by counts, which is this project's rule for any write: **verify by counts,
    never by sampling values.**
    """
    def produce() -> dict:
        tally: dict[str, int] = {}
        offset = 0
        while offset < 20000:
            rows = (_get_client().table(_SECTION_TABLE)
                    .select(_SECTION_FIELD)
                    .range(offset, offset + 999).execute().data or [])
            if not rows:
                break
            for r in rows:
                k = str(r.get(_SECTION_FIELD) or "")
                tally[k] = tally.get(k, 0) + 1
            offset += 1000
        return tally or {"": 0}

    return _cached("storedcounts", produce, {})


def store_section(article_id: str, section: str) -> bool:
    """Write one row's section. Never cached, and never raises.

    **Not routed through `_cached()`.** That helper exists to make a *read*
    degrade quietly; a write that is silently skipped is a lie about the state
    of the database, and the caller counts what it wrote.
    """
    from core.news_sections import LABELS
    aid = str(article_id or "").strip()
    if not aid or section not in LABELS:
        return False
    if _get_client() is None:
        return False
    try:
        (_get_client().table(_SECTION_TABLE)
         .update({_SECTION_FIELD: section}).eq("id", aid).execute())
        return True
    except Exception as e:                                  # noqa: BLE001
        print(f"[Reporter] store_section({aid}) failed: {type(e).__name__}: {e}")
        return False


# One `update … in (ids)` carries this many ids. The ids are UUIDs (36 chars),
# so a chunk is ~7.5 KB of URL — comfortably inside the request-line limit, and
# the first full index of 7,521 rows took **34 requests** this way against
# 7,521 one-row updates. Measured 2026-09-30: the per-row form was projected at
# several minutes, which is long enough that a user asking JARVIS to "build the
# index" would assume it had hung.
_SECTION_WRITE_CHUNK = 200


def store_sections(ids: list[str], section: str) -> int:
    """Write one section onto many rows. Returns how many ids were written.

    A failed chunk is **not** retried and not counted — the caller reports the
    shortfall rather than being told the whole write succeeded. The next
    `index` run picks the rows up again, because a row that was not written
    still carries a value that is not one of `news_sections.LABELS`.
    """
    from core.news_sections import LABELS
    if section not in LABELS or not ids:
        return 0
    if _get_client() is None:
        return 0
    clean = [str(i).strip() for i in ids if str(i or "").strip()]
    written = 0
    for start in range(0, len(clean), _SECTION_WRITE_CHUNK):
        chunk = clean[start:start + _SECTION_WRITE_CHUNK]
        try:
            (_get_client().table(_SECTION_TABLE)
             .update({_SECTION_FIELD: section}).in_("id", chunk).execute())
            written += len(chunk)
        except Exception as e:                              # noqa: BLE001
            print(f"[Reporter] store_sections({section}) chunk "
                  f"{start // _SECTION_WRITE_CHUNK} failed: "
                  f"{type(e).__name__}: {e}")
    return written


def clear_section_cache() -> None:
    """Drop the cached section reads after a write, so the next read sees it.

    Without this the index pass would report success and the very next section
    question would be answered from the pre-write cache — the write would be
    real and invisible, which is the hardest kind of bug to notice.
    """
    with _lock:
        for k in [k for k in _cache if k.startswith(("secrows:", "sectally:"))]:
            _cache.pop(k, None)

