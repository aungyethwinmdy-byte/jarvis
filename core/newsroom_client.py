"""Read-only bridge from JARVIS to the AI Newsroom database.

    E:\\AI_NEWSROOM   (collector + analyzer + auto_runner)   -- writes -->
        Supabase: news_articles / news_reports / system_run_logs
    E:\\Mark-LIV-main (JARVIS)                               <-- reads  --

WHY JARVIS DOES NOT COLLECT OR ANALYSE ANYTHING ITSELF
    The newsroom already owns that work. Its auto_runner wakes every hour,
    scrapes PPIB, BBC Burmese, The Irrawaddy and DVB Burmese, runs each article
    through an
    LLM into a "Format A" editorial report with cross-source correlation and a
    neutrality pass, and stores the result. Duplicating any of it here would
    mean two collectors racing, two sets of credentials, and two answers to
    "what's new" that disagree with each other.

    So this module does exactly one thing: it reads the finished reports and
    turns them into something JARVIS can say out loud. One writer, one reader,
    one source of truth.

WHY NOTHING HERE EVER RAISES
    This is a voice assistant, so a failure has to be audible-safe. A database
    that is slow, empty, or missing its credentials must degrade to "no news
    yet" — never to an exception, because the two ways that reaches the user
    are a spoken apology or dead silence, and both are worse than a slightly
    less complete answer. Every public function returns a value, or an empty
    result plus a reason string that the caller can choose to ignore.

WHY THERE IS A CACHE AND A BOUNDED BUDGET
    The user asks the same question twice ("what's new?" then "any news?"), and
    every cache miss is a network round trip that is heard as a pause before
    the assistant starts talking. Parsed results are cached for a short window,
    keyed on the request that produced them. Failures are never cached: a
    transient timeout must not pin "no news" for the next two minutes.

    The retry budget is bounded for the same reason it is in
    actions/weather_report.py — the timeout is the budget for the whole call,
    not per attempt, or a slow database becomes a long silence.

WHY THE SPOKEN TEXT HAS NO ASCII DIGITS
    core/timefmt.py already established this: spoken Burmese numerals are
    ၀-၉, and handing the model "3" leaves it to convert, which it does
    unreliably. Reports arrive from an LLM that writes ASCII digits freely, so
    every string this module hands to the voice path is run through
    timefmt.to_burmese_digits() and stripped of emoji and HTML first.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime, time as _time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from core import timefmt

# ── Tunables ─────────────────────────────────────────────────────────────────

DEFAULT_ENV_PATH = Path(r"E:\AI_NEWSROOM\.env")
REQUEST_TIMEOUT = 8.0     # per PostgREST call, seconds
RETRY_ATTEMPTS = 2        # one retry: a second failure is a real failure
RETRY_DELAY = 0.8
CACHE_TTL = 90.0          # seconds; long enough for a repeated question
SEARCH_CACHE_TTL = 30.0      # shorter TTL for keyword searches — new articles arrive often

MYANMAR_TZ = timezone(timedelta(hours=6, minutes=30))

_lock = threading.Lock()
_client: Any = None
_client_error: str = ""
_client_tried = False
_cache: dict[str, tuple[float, Any]] = {}


# ── Configuration ────────────────────────────────────────────────────────────

def env_path() -> Path:
    """Where the newsroom's credentials live.

    Read through config_manager so the path can be changed without editing
    code, but with a fallback so this module still imports (and still reports
    a clean "unavailable") if the config layer is not importable yet.
    """
    import os
    override = os.environ.get("JARVIS_NEWSROOM_ENV")
    if override:
        return Path(override).expanduser()
    try:
        from memory.config_manager import get_newsroom_env_path
        p = get_newsroom_env_path()
        if p:
            return Path(p).expanduser()
    except Exception:
        pass
    return DEFAULT_ENV_PATH


def _read_env() -> dict[str, str]:
    """Parse the newsroom .env without touching os.environ.

    dotenv_values() rather than load_dotenv() on purpose: loading it would
    inject the newsroom's ROUTER_API_KEY and TELEGRAM_BOT_TOKEN into JARVIS's
    process environment, where they are invisible and can leak into any
    subprocess JARVIS starts.
    """
    path = env_path()
    if not path.exists():
        return {}
    try:
        from dotenv import dotenv_values
        return {k: (v or "") for k, v in dotenv_values(str(path)).items() if k}
    except Exception:
        pass

    # Minimal fallback parser, so a missing python-dotenv is not fatal.
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip().strip('"').strip("'")
    except Exception:
        return {}
    return out


def _credentials() -> tuple[str, str]:
    env = _read_env()
    url = (env.get("SUPABASE_URL") or "").strip()
    key = (env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_KEY") or "").strip()
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
                # Bounded, because this call sits between the user finishing a
                # question and hearing the first word of the answer.
                options=ClientOptions(postgrest_client_timeout=REQUEST_TIMEOUT),
            )
        except Exception as e:
            _client_error = f"{type(e).__name__}: {e}"
            _client = None
        return _client


def available() -> tuple[bool, str]:
    """(usable, reason-if-not). Cheap: reuses the already-built client."""
    if _get_client() is not None:
        return True, "ok"
    return False, _client_error or "newsroom database unreachable"


# ── Query plumbing ───────────────────────────────────────────────────────────

def _run(fn: Callable[[], Any], label: str) -> Any:
    """Run one query with a single retry. Raises only after both attempts fail."""
    last: Optional[Exception] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[Newsroom] {label} attempt {attempt}/{RETRY_ATTEMPTS} failed: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    raise last  # type: ignore[misc]


def _safe(fn: Callable[[], Any], default: Any, label: str) -> Any:
    """_run() with the exception swallowed — the voice path must not see it.

    If the error looks like an expired JWT / auth failure the client is reset
    so the next call rebuilds it from the credentials file, without needing a
    process restart.
    """
    if _get_client() is None:
        return default
    try:
        return _run(fn, label)
    except Exception as e:
        msg = str(e).lower()
        if any(tok in msg for tok in ("jwt", "expired", "401", "unauthorized", "invalid api key")):
            print(f"[Newsroom] {label}: auth error — resetting client: {e}")
            global _client, _client_error, _client_tried
            with _lock:
                _client = None
                _client_error = ""
                _client_tried = False
        else:
            print(f"[Newsroom] {label} gave up: {type(e).__name__}: {e}")
        return default


def _cached(key: str, produce: Callable[[], Any], default: Any,
            ttl: float | None = None) -> Any:
    """Short-lived cache. Only successful, non-empty results are stored.

    A FAILURE DEGRADES HERE; IT DOES NOT RAISE. `_run()` retries and then
    raises, and every public reader in this module goes through this function,
    so this is the single point that keeps a Supabase stall off the voice path.
    Measured 2026-09-27: an `httpcore.ConnectTimeout` in `recent_reports`
    propagated out of daily_briefing and the tool crashed, when the only thing
    that had happened was that the network blinked.

    The empty shape is already what every caller handles — `available()` gates
    the tools, and `_newsroom_briefing()` falls back to the world wires when the
    newsroom returns nothing. Returning the default is therefore not a silent
    failure: the answer gets thinner, and the reason is printed.
    """
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
    effective_ttl = ttl if ttl is not None else CACHE_TTL
    if hit and (now - hit[0]) < effective_ttl:
        return hit[1]

    try:
        value = produce()
    except Exception as e:
        print(f"[Newsroom] {key} gave up: {type(e).__name__}: {e}")
        return default

    if value:                      # never cache a failure or an empty result
        with _lock:
            _cache[key] = (now, value)
    return value if value is not None else default


def clear_cache(prefix: str | None = None) -> None:
    """Drop the cache — used by the watcher after it has consumed new reports.

    Pass `prefix` to clear only keys that start with that string (e.g. 'search:'
    or 'reportsearch:'). Omit to clear everything.
    """
    with _lock:
        if prefix is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k.startswith(prefix)]:
                del _cache[key]


def reset_client() -> None:
    """Force the next call to _get_client() to rebuild the Supabase client.

    Call this when the connection appears stale (e.g. after a long sleep or
    an authentication error). The old client is discarded immediately; the new
    one is built lazily on the next query.
    """
    global _client, _client_error, _client_tried
    with _lock:
        _client = None
        _client_error = ""
        _client_tried = False
    clear_cache()


# ── Time helpers ─────────────────────────────────────────────────────────────

def _as_mmt(value: Any) -> Optional[datetime]:
    """Any Supabase timestamp -> an aware MMT datetime, or None.

    Supabase returns ISO strings like '2026-09-27T01:17:23.095154+00:00'.
    Rendered for the user in MMT, never UTC: between 00:00 and 06:30 MMT the
    two differ by a whole day, and the newsroom's own published_at values are
    already written in +06:30.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(raw[:26], fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MYANMAR_TZ)


def _ago_label(dt: Optional[datetime]) -> str:
    """'၁၅ မိနစ်က' / '၂ နာရီက' / 'မနေ့က' — how long ago, in Burmese."""
    if dt is None:
        return ""
    mins = int((timefmt.now_mmt() - dt).total_seconds() // 60)
    if mins < 0:
        mins = 0
    if mins < 1:
        return "ခုလေးတင်"
    if mins < 60:
        return f"{timefmt.to_burmese_digits(mins)} မိနစ်က"
    hours = mins // 60
    if hours < 24:
        return f"{timefmt.to_burmese_digits(hours)} နာရီက"
    days = hours // 24
    if days == 1:
        return "မနေ့က"
    return f"{timefmt.to_burmese_digits(days)} ရက်က"


# ── Text helpers ─────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U0001F1E6-\U0001F1FF"
    "\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u20E3" "]"
)
# The analyzer writes its bullet lists with •. A TTS engine either skips it or
# reads it as "bullet", so list markers are stripped from the front of each
# line. A bare '-' or '*' only counts when a space follows, so "-5 degrees"
# survives while "- item" does not.
_BULLET_RE = re.compile(r"^(?:[\u2022\u25AA\u25CF\u25E6\u2023\u2043\u00B7]+|[-*]\s+)\s*")
_WS_RE = re.compile(r"[ \t]+")
_ILIKE_SPECIAL = re.compile(r"[\\%_()|,]")


def _safe_query(q: str) -> str:
    """Escape characters that have special meaning in PostgREST ilike/or filters.

    PostgREST parses the .or_() string itself before handing it to Postgres,
    so unescaped '(', ')', ',' and '|' break the filter even though Postgres
    would handle them fine inside a quoted literal. Backslash-escaping is the
    documented PostgREST approach; the Postgres ilike wildcards '%' and '_' are
    also escaped so a user query that contains them is treated as a literal.
    """
    return _ILIKE_SPECIAL.sub(lambda m: "\\" + m.group(), q)


# A query the user typed may be several words ("လေးမျက်နှာ ရေဘေး"). Burmese
# writes most words joined, so whitespace marks phrase-sized units — the keyword
# the user means is normally the whole unit, not the letters inside it.
_TERM_SPLIT = re.compile(r"[\s\u200b]+")
_MAX_SEARCH_TERMS = 5


def _terms(query: str) -> list[str]:
    """The whitespace-separated search terms, in the order the user wrote them."""
    return [t for t in _TERM_SPLIT.split(str(query or "").strip())
            if len(t) >= 2][:_MAX_SEARCH_TERMS]


def _like_any(terms: list[str], columns: tuple[str, ...]) -> str:
    """A PostgREST filter that matches EVERY term in ANY of `columns`.

    A multi-word query used to be matched as one literal substring that included
    the space, so `%လေးမျက်နှာ ရေဘေး%` found nothing unless an article happened to
    write the two words adjacently. Measured on the live database 2026-10-17:
    that query returned 0 hits while `လေးမျက်နှာ` alone returned 4 and `ရေဘေး`
    alone returned 8 — and the story the user was asking about carried both.
    Terms are OR-ed within a column pair and AND-ed across terms, so the words
    may sit anywhere on the page, which is what "search for this topic" means.
    A one-word query produces exactly the filter this function replaced.
    """
    if len(terms) == 1:
        pattern = f"%{_safe_query(terms[0])}%"
        return ",".join(f"{c}.ilike.{pattern}" for c in columns)
    groups = []
    for term in terms:
        pattern = f"%{_safe_query(term)}%"
        groups.append("or(" + ",".join(f"{c}.ilike.{pattern}" for c in columns) + ")")
    return "and(" + ",".join(groups) + ")"


def clean_for_speech(text: Any) -> str:
    """Telegram-HTML report -> plain Burmese that is safe to read aloud.

    Strips HTML tags (the analyzer writes <b>…</b>), drops emoji and list
    markers (the TTS engine either skips them or reads their names, both
    wrong), collapses the whitespace they leave behind, and converts ASCII
    digits to Burmese numerals — the same rule core/timefmt.py applies to the
    greeting.
    """
    out = _TAG_RE.sub("", str(text or ""))
    out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    out = out.replace("&quot;", '"').replace("&#39;", "'")
    out = _EMOJI_RE.sub(" ", out)
    lines = []
    for ln in out.splitlines():
        ln = _BULLET_RE.sub("", ln.strip())
        lines.append(_WS_RE.sub(" ", ln).strip())
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return timefmt.to_burmese_digits(out)


# The analyzer's Format A template puts a fixed emoji marker before each
# section. Extracting on those markers is how a 3,500-character report becomes
# two spoken sentences without a second LLM round trip.
_SECTION_SUMMARY = ("တစ်မိနစ် အနှစ်ချုပ်",)
_SECTION_STOP = ("ဂဏန်းက ဘာပြောနေသလဲ", "ဒါ မင်းနဲ့ ဘာဆိုင်လဲ", "သတင်းဌာန၏ တင်ပြပုံ",
                 "အခြားသတင်းဌာနများနှင့်", "ဆက်လက် စောင့်ကြည့်ရမည့်အချက်")


def extract_summary(full_report: Any) -> tuple[str, list[str]]:
    """(headline, bullet points) pulled out of a Format A report.

    Returns ("", []) for anything that does not look like one, so callers fall
    back to the raw text rather than inventing structure.
    """
    raw = str(full_report or "")
    if not raw.strip():
        return "", []

    lines = [ln.strip() for ln in raw.splitlines()]
    headline = ""
    for ln in lines:
        plain = clean_for_speech(_TAG_RE.sub("", ln))
        if not plain:
            continue
        # The first non-empty line is "📱 <b>headline</b> (သတင်းဌာန: X)".
        plain = re.sub(r"^[^\w\u1000-\u109F]+", "", plain).strip()
        plain = re.sub(r"\s*\(သတင်းဌာန.*?\)\s*$", "", plain).strip()
        if plain:
            headline = plain
            break

    bullets: list[str] = []
    started = False
    for ln in lines:
        plain = clean_for_speech(_TAG_RE.sub("", ln))
        if not plain:
            continue
        if any(marker in plain for marker in _SECTION_SUMMARY):
            started = True
            continue
        if not started:
            continue
        if any(marker in plain for marker in _SECTION_STOP):
            break
        stripped = re.sub(r"^[•\-*\s]+", "", plain).strip()
        if stripped:
            bullets.append(stripped)
        if len(bullets) >= 3:
            break

    return headline, bullets


# ── Reads ────────────────────────────────────────────────────────────────────

def recent_reports(hours: int = 36, limit: int = 10) -> list[dict]:
    """Analysed articles from the last `hours`, newest first.

    Joins news_reports to news_articles by article_id, because the report row
    carries the written analysis while the article row carries the source and
    the headline the user recognises.
    """
    def produce() -> list[dict]:
        sb = _get_client()
        if sb is None:
            return []
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        reports = _run(
            lambda: sb.table("news_reports")
            .select("id,article_id,report_type,target_date,full_report,created_at")
            .eq("report_type", "single_editorial")
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(limit)
            .execute(),
            "recent_reports",
        )
        rows = reports.data or []
        if not rows:
            return []

        ids = [r["article_id"] for r in rows if r.get("article_id")]
        articles: dict[str, dict] = {}
        if ids:
            arts = _run(
                lambda: sb.table("news_articles")
                .select("id,source_id,source_name,source_type,title,url,published_at")
                .in_("id", ids)
                .execute(),
                "recent_reports/articles",
            )
            articles = {a["id"]: a for a in (arts.data or [])}

        out = []
        for r in rows:
            a = articles.get(r.get("article_id")) or {}
            headline, bullets = extract_summary(r.get("full_report"))
            out.append({
                "report_id": r.get("id"),
                # Carried through so a later "that story" resolves to an exact
                # row instead of a text search: the user points at something
                # they just heard, and a search is a guess where an id is not.
                "article_id": a.get("id"),
                "source_id": a.get("source_id") or "",
                "source": a.get("source_name") or "Unknown",
                "source_type": a.get("source_type") or "",
                "title": a.get("title") or headline,
                "headline": headline,
                "bullets": bullets,
                "url": a.get("url") or "",
                "published": _as_mmt(a.get("published_at")),
                "created": _as_mmt(r.get("created_at")),
                "full_report": r.get("full_report") or "",
            })
        return out

    return _cached(f"recent:{hours}:{limit}", produce, []) or []


def latest_digest() -> Optional[dict]:
    """The newest daily digest report, or None."""
    def produce() -> Optional[dict]:
        sb = _get_client()
        if sb is None:
            return None
        res = _run(
            lambda: sb.table("news_reports")
            .select("id,report_type,target_date,full_report,created_at,summary_points")
            .eq("report_type", "daily_digest")
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            "latest_digest",
        )
        rows = res.data or []
        if not rows:
            return None
        r = rows[0]
        return {
            "report_id": r.get("id"),
            "target_date": r.get("target_date"),
            "created": _as_mmt(r.get("created_at")),
            "full_report": r.get("full_report") or "",
            "summary_points": r.get("summary_points") or {},
        }

    return _cached("latest_digest", produce, None)


def search_articles(query: str, days: int = 120, limit: int = 8) -> list[dict]:
    """Full-text-ish search over collected articles.

    The query is passed through EXACTLY as the user said it. It is not
    translated and not normalised: the sources are Burmese, so a Burmese
    question translated into English matches nothing — the newsroom's own
    notes record a Burmese question about Myanmar's president coming back as a
    Colombian earthquake for precisely that reason.
    """
    q = str(query or "").strip()
    if len(q) < 2:
        return []
    terms = _terms(q)
    if not terms:
        return []

    def produce() -> list[dict]:
        sb = _get_client()
        if sb is None:
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        # Every term, against title or content — see _like_any().
        res = _run(
            lambda: sb.table("news_articles")
            .select("id,source_id,source_name,source_type,title,url,published_at,status")
            .gte("published_at", since)
            .or_(_like_any(terms, ("title", "content")))
            .order("published_at", desc=True)
            .limit(limit)
            .execute(),
            "search_articles",
        )
        out = []
        for a in (res.data or []):
            out.append({
                "article_id": a.get("id"),
                "source_id": a.get("source_id") or "",
                "source": a.get("source_name") or "Unknown",
                "source_type": a.get("source_type") or "",
                "title": a.get("title") or "",
                "url": a.get("url") or "",
                "status": a.get("status") or "",
                "published": _as_mmt(a.get("published_at")),
            })
        return out

    return _cached(f"search:{q}:{days}:{limit}", produce, [], ttl=SEARCH_CACHE_TTL) or []


def _row_from_article(a: dict) -> dict:
    """One `news_articles` row in the shape every story-level caller expects."""
    return {
        "article_id": a.get("id"),
        "source_id": a.get("source_id") or "",
        "source": a.get("source_name") or "Unknown",
        "source_type": a.get("source_type") or "",
        "title": a.get("title") or "",
        "url": a.get("url") or "",
        "status": a.get("status") or "",
        "published": _as_mmt(a.get("published_at")),
    }


def _articles_by_ids(sb: Any, ids: list[str]) -> list[dict]:
    """Fetch those article rows, newest first. `ids` may repeat or be empty."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return []
    res = _run(
        lambda: sb.table("news_articles")
        .select("id,source_id,source_name,source_type,title,url,published_at,status")
        .in_("id", ids)
        .execute(),
        "articles_by_ids",
    )
    rows = [_row_from_article(a) for a in (res.data or [])]
    rows.sort(key=lambda r: r.get("published") or datetime.min.replace(tzinfo=timezone.utc),
              reverse=True)
    return rows


def article_by_id(article_id: str) -> Optional[dict]:
    """One article by its id, or None. Used when the user's reference is exact."""
    if not _is_uuid(article_id):
        return None

    def produce() -> Optional[dict]:
        sb = _get_client()
        if sb is None:
            return None
        rows = _articles_by_ids(sb, [article_id])
        return rows[0] if rows else None

    return _cached(f"article:{article_id}", produce, None)


def search_reports(query: str, days: int = 30, limit: int = 8) -> list[dict]:
    """Find articles by searching the ANALYSED REPORT text, not the article.

    WHY THIS EXISTS — measured on the live database 2026-09-27
        The headline JARVIS reads out comes from the report, not from
        `news_articles.title`: the analyzer rewrites it. The four newest briefed
        headlines ALL missed search_articles() and ALL four hit here. So the
        story the user just heard is only findable through the report text, and
        without this, repeating a headline you heard a minute ago comes back as
        "I couldn't find it" — a silent, total failure of the feature that looks
        exactly like an empty archive.

    Only `single_editorial` rows are searched. A daily_digest has no
    `article_id`, and matching one would resolve to no article at all.
    """
    q = str(query or "").strip()
    if len(q) < 2:
        return []
    terms = _terms(q)
    if not terms:
        return []

    def produce() -> list[dict]:
        sb = _get_client()
        if sb is None:
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        def query_reports():
            # One ilike per term; chained ilikes AND themselves, so a
            # multi-word query matches the report that carries every word.
            qy = (sb.table("news_reports")
                  .select("article_id,created_at")
                  .eq("report_type", "single_editorial")
                  .gte("created_at", since))
            for term in terms:
                qy = qy.ilike("full_report", f"%{_safe_query(term)}%")
            return qy.order("created_at", desc=True).limit(limit).execute()

        res = _run(query_reports, "search_reports")
        ids = [r.get("article_id") for r in (res.data or [])]
        return _articles_by_ids(sb, ids)

    return _cached(f"reportsearch:{q}:{days}:{limit}", produce, [], ttl=SEARCH_CACHE_TTL) or []


# ── One outlet, one day ──────────────────────────────────────────────────────
# "BBC မှာ ဒီနေ့သတင်းတွေ ဘာထူးလဲ" — the user names an outlet and a day, and wants
# that outlet's news for that day. This is not a keyword search: the outlet is
# a source_id filter and the day is a date filter.

OUTLET_NAMES = {
    "ppib": "PPIB",
    "bbcburmese": "BBC Burmese",
    "irrawaddy": "The Irrawaddy",
    "dvb": "DVB Burmese",
}

# The user says the name in Burmese, in English, or as an abbreviation, so the
# match has to accept all of them. Longest alias first, and whitespace stripped
# from both sides — Burmese is written without word spaces, so "ဘီဘီစီ မြန်မာ"
# typed with a space must still match the alias "ဘီဘီစီမြန်မာ". Joining the Latin
# forms would be wrong, but they are matched on the lowercased text anyway.
OUTLET_ALIASES: dict[str, tuple[str, ...]] = {
    "ppib": ("ppib", "ပီပီအိုင်ဘီ", "ပီပီအိုင်", "သမ္မတရုံး", "ပြန်ကြားရေးဗျူရို",
             "နိုင်ငံပိုင်မီဒီယာ", "အစိုးရသတင်း", "state media"),
    "bbcburmese": ("bbc burmese", "bbcburmese", "bbc", "ဘီဘီစီမြန်မာ", "ဘီဘီစီ"),
    "irrawaddy": ("the irrawaddy", "irrawaddy", "ဧရာဝတီ", "ဒီအီရာဝတီ"),
    "dvb": ("dvb burmese", "dvbburmese", "dvb", "ဒီဗွီဘီ", "ဒီဗီဘီ"),
}


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_uuid(value: Any) -> bool:
    """Is this the shape of a `news_articles.id`?

    The ids are Postgres uuids, and PostgREST answers anything else with 22P02
    ("invalid input syntax for type uuid") — which raises out of the query
    rather than returning empty. Ids reach these functions from the model and
    from the offline checks, so the shape is checked before the round trip.
    """
    return bool(_UUID_RE.match(str(value or "").strip()))


def _squash(text: Any) -> str:
    """Lowercase and drop every whitespace character, for alias matching."""
    return re.sub(r"\s+", "", str(text or "").lower())


def resolve_outlet(text: Any) -> tuple[Optional[str], str]:
    """A spoken outlet name -> (source_id, display name), or (None, "").

    Returns None rather than guessing. A wrong outlet answers the wrong
    question confidently, which is worse than asking which one was meant.
    """
    t = _squash(text)
    if not t:
        return None, ""

    best: tuple[int, Optional[str]] = (0, None)
    for sid, aliases in OUTLET_ALIASES.items():
        for alias in aliases:
            a = _squash(alias)
            if a and a in t and len(a) > best[0]:
                best = (len(a), sid)
    if best[1]:
        return best[1], OUTLET_NAMES[best[1]]
    return None, ""


def _story_key(title: Any) -> str:
    """A coarse identity for a headline, for spotting the same story twice.

    The Irrawaddy's Telegram channel reposts a story under a slightly different
    caption, and the two arrive as separate articles with different content
    hashes, so nothing upstream collapses them. Read aloud they are the same
    sentence twice, and the "6 ပုဒ်" count is a lie. Compared on the first 50
    characters with whitespace and case removed, which is loose enough to catch
    a re-post and tight enough not to merge two different stories.
    """
    t = re.sub(r"\s+", "", str(title or "").lower()).rstrip("…")
    return t[:50]


def outlet_news(source_id: str, target_date: date, limit: int = 6) -> list[dict]:
    """One outlet's articles published on one **MMT** calendar day.

    WHY THE FILTER IS NOT DONE IN THE QUERY
        `published_at` is not stored consistently. The PPIB and The Irrawaddy
        collectors write a bare date ("2026-09-27"), which Supabase keeps as
        midnight **UTC**; the BBC collector writes the real UTC instant from
        Telegram's <time> tag. So a BBC story filed at 20:00 UTC on the 26th is
        02:30 MMT on the 27th — a different calendar day depending on which
        clock you ask. The user means the MMT day, so a wide UTC window is
        fetched and the MMT date is applied here, in Python, where the
        conversion is explicit.
    """
    def produce() -> list[dict]:
        sb = _get_client()
        if sb is None:
            return []

        start = datetime.combine(target_date - timedelta(days=1), _time.min,
                                 tzinfo=timezone.utc)
        end = datetime.combine(target_date + timedelta(days=2), _time.min,
                               tzinfo=timezone.utc)

        _PAGE = 80
        all_rows: list[tuple] = []
        offset = 0
        while True:
            res = _run(
                lambda o=offset: sb.table("news_articles")
                .select("id,source_id,source_name,title,url,published_at,status")
                .eq("source_id", source_id)
                .gte("published_at", start.isoformat())
                .lt("published_at", end.isoformat())
                .order("published_at", desc=True)
                .range(o, o + _PAGE - 1)
                .execute(),
                f"outlet_news/{offset}",
            )
            batch = res.data or []
            for a in batch:
                when = _as_mmt(a.get("published_at"))
                if when and when.date() == target_date:
                    all_rows.append((when, a))
            if len(batch) < _PAGE:
                break
            if len(all_rows) >= limit * 6:
                break
            offset += _PAGE

        rows = all_rows
        if not rows:
            return []

        rows.sort(key=lambda pair: pair[0], reverse=True)

        # Collapse re-posts BEFORE taking `limit`, so the number the user hears
        # is the number of stories, not the number of rows.
        seen: set[str] = set()
        picked: list[tuple[datetime, dict]] = []
        for when, a in rows:
            key = _story_key(a.get("title"))
            if key and key in seen:
                continue
            seen.add(key)
            picked.append((when, a))
            if len(picked) >= limit:
                break
        if not picked:
            return []

        ids = [a["id"] for _, a in picked]

        # Pull the analysed report for each, so the answer can carry the
        # one-minute summary rather than a bare headline.
        bullets: dict[str, list[str]] = {}
        heads: dict[str, str] = {}
        if ids:
            reps = _run(
                lambda: sb.table("news_reports")
                .select("article_id,full_report")
                .in_("article_id", ids)
                .eq("report_type", "single_editorial")
                .execute(),
                "outlet_news/reports",
            )
            for r in (reps.data or []):
                h, b = extract_summary(r.get("full_report"))
                bullets[r["article_id"]] = b
                heads[r["article_id"]] = h

        out = []
        for when, a in picked:
            title = a.get("title") or ""
            # Some PPIB posts carry an emoji as their entire title, and
            # clean_for_speech() strips emoji — so the item reads as blank while
            # still being counted. The analyser's headline is the fallback.
            # Measured 2026-09-27: PPIB's first article of the day was titled
            # with a single emoji, and the answer began at "2." with the count
            # one too high.
            if not clean_for_speech(title):
                title = heads.get(a.get("id")) or title
            out.append({
                "article_id": a.get("id"),
                "source": a.get("source_name") or OUTLET_NAMES.get(source_id, source_id),
                "title": title,
                "url": a.get("url") or "",
                "published": when,
                "bullets": bullets.get(a.get("id"), []),
            })
        return out

    return _cached(f"outlet:{source_id}:{target_date}:{limit}", produce, []) or []


def outlet_newest(source_id: str) -> Optional[dict]:
    """The outlet's most recent article, whatever day it is from.

    Only used to answer "nothing today" honestly — "nothing today, the newest
    is from yesterday" is a real answer; "no news found" is not.
    """
    def produce() -> Optional[dict]:
        sb = _get_client()
        if sb is None:
            return None
        res = _run(
            lambda: sb.table("news_articles")
            .select("title,published_at")
            .eq("source_id", source_id)
            .order("published_at", desc=True)
            .limit(1)
            .execute(),
            "outlet_newest",
        )
        rows = res.data or []
        if not rows:
            return None
        when = _as_mmt(rows[0].get("published_at"))
        return {"title": rows[0].get("title") or "", "published": when}

    return _cached(f"outlet_newest:{source_id}", produce, None)


def reports_since(moment: Optional[datetime], limit: int = 5) -> list[dict]:
    """Reports created after `moment`, oldest first — the watcher's feed.

    Returns [] when `moment` is None: the first run of a fresh install must
    seed the marker, not announce the entire backlog.
    """
    if moment is None:
        return []
    sb = _get_client()
    if sb is None:
        return []

    def fetch() -> list[dict]:
        res = _run(
            lambda: sb.table("news_reports")
            .select("id,article_id,report_type,created_at,full_report")
            .eq("report_type", "single_editorial")
            .gt("created_at", moment.astimezone(timezone.utc).isoformat())
            .order("created_at", desc=False)
            .limit(limit)
            .execute(),
            "reports_since",
        )
        rows = res.data or []
        if not rows:
            return []
        ids = [r["article_id"] for r in rows if r.get("article_id")]
        articles: dict[str, dict] = {}
        if ids:
            arts = _run(
                lambda: sb.table("news_articles")
                .select("id,source_name,source_type,title,url,published_at")
                .in_("id", ids)
                .execute(),
                "reports_since/articles",
            )
            articles = {a["id"]: a for a in (arts.data or [])}

        out = []
        for r in rows:
            a = articles.get(r.get("article_id")) or {}
            headline, bullets = extract_summary(r.get("full_report"))
            out.append({
                "report_id": r.get("id"),
                "source": a.get("source_name") or "Unknown",
                "source_type": a.get("source_type") or "",
                "title": a.get("title") or headline,
                "headline": headline,
                "bullets": bullets,
                "url": a.get("url") or "",
                "published": _as_mmt(a.get("published_at")),
                "created": _as_mmt(r.get("created_at")),
            })
        return out

    try:
        return fetch()
    except Exception as e:
        print(f"[Newsroom] reports_since failed: {type(e).__name__}: {e}")
        return []


def newest_marker() -> Optional[datetime]:
    """created_at of the newest report — the watcher's high-water mark."""
    sb = _get_client()
    if sb is None:
        return None
    try:
        res = _run(
            lambda: sb.table("news_reports")
            .select("created_at")
            .eq("report_type", "single_editorial")
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            "newest_marker",
        )
        rows = res.data or []
        return _as_mmt(rows[0].get("created_at")) if rows else None
    except Exception as e:
        print(f"[Newsroom] newest_marker failed: {type(e).__name__}: {e}")
        return None


def source_breakdown() -> list[dict]:
    """Every outlet that actually has articles in the archive, largest first.

    PostgREST cannot GROUP BY without a server-side function, so the rows are
    fetched and aggregated here. That is affordable: the whole table is a few
    hundred small rows, and the result is cached.

    This is the question "which outlets are we actually reading?" — and the
    answer is not the same as the newsroom's config/sources.yaml, which lists
    outlets whose collectors no longer exist. The database is the truth; the
    config file is a wish.
    """
    def produce() -> list[dict]:
        sb = _get_client()
        if sb is None:
            return []

        rows: list[dict] = []
        start, page = 0, 1000
        while True:
            res = _run(
                lambda s=start: sb.table("news_articles")
                .select("source_id,source_name,source_type,status,published_at")
                .order("id")
                .range(s, s + page - 1)
                .execute(),
                f"source_breakdown/{start}",
            )
            batch = res.data or []
            rows.extend(batch)
            if len(rows) > 50_000:
                print("[Newsroom] source_breakdown: row cap reached — truncating at 50,000")
                break
            if len(batch) < page:
                break
            start += page

        agg: dict[tuple, dict] = {}
        for a in rows:
            key = (a.get("source_id"), a.get("source_name"), a.get("source_type"))
            e = agg.setdefault(key, {"total": 0, "analyzed": 0, "failed": 0, "newest": None})
            e["total"] += 1
            if a.get("status") == "analyzed":
                e["analyzed"] += 1
            elif a.get("status") == "failed":
                e["failed"] += 1
            d = _as_mmt(a.get("published_at"))
            if d and (e["newest"] is None or d > e["newest"]):
                e["newest"] = d

        out = [{"source_id": k[0], "source_name": k[1], "source_type": k[2], **v}
               for k, v in agg.items()]
        out.sort(key=lambda x: -x["total"])
        return out

    return _cached("source_breakdown", produce, []) or []


def pipeline_status() -> dict:
    """Health of the newsroom pipeline, for "is the watcher even running?"."""
    def produce() -> dict:
        sb = _get_client()
        if sb is None:
            return {}

        counts: dict[str, int] = {}
        try:
            for status in ("pending", "processing", "analyzed", "failed", "archived"):
                res = _run(
                    lambda s=status: sb.table("news_articles")
                    .select("id", count="exact")
                    .eq("status", s)
                    .limit(1)
                    .execute(),
                    f"status/{status}",
                )
                counts[status] = res.count or 0
        except Exception as e:
            print(f"[Newsroom] status counts failed: {e}")

        last_run = None
        try:
            res = _run(
                lambda: sb.table("system_run_logs")
                .select("job_name,status,started_at,completed_at,duration_seconds,items_processed,tokens_used")
                .order("started_at", desc=True)
                .limit(1)
                .execute(),
                "last_run",
            )
            rows = res.data or []
            if rows:
                r = rows[0]
                last_run = {
                    "job": r.get("job_name"),
                    "status": r.get("status"),
                    "started": _as_mmt(r.get("started_at")),
                    "items": r.get("items_processed") or 0,
                }
        except Exception as e:
            print(f"[Newsroom] last run failed: {e}")

        marker = None
        try:
            res = _run(
                lambda: sb.table("news_reports")
                .select("created_at")
                .order("created_at", desc=True)
                .limit(1)
                .execute(),
                "status/newest",
            )
            rows = res.data or []
            marker = _as_mmt(rows[0].get("created_at")) if rows else None
        except Exception:
            pass

        return {"counts": counts, "last_run": last_run, "newest_report": marker,
                "sources": source_breakdown()}

    return _cached("pipeline_status", produce, {}) or {}


# ── Spoken formatting ────────────────────────────────────────────────────────

def briefing_items(reports: list[dict], max_items: int = 5) -> list[dict]:
    """The items format_briefing() will actually number, in that order.

    Kept separate from the formatter because this list is also what a later
    "the second one" resolves against. A reference list that does not match what
    was read out answers about the wrong story, and it does so silently.
    """
    return [r for r in (reports or []) if r.get("title") or r.get("headline")][:max_items]


def format_briefing(reports: list[dict], max_items: int = 5) -> str:
    """The newsroom's analysed reports as a short spoken Burmese briefing.

    Deliberately not the full report: those run to 3,500 characters of
    HTML and emoji, which is a wall of text to hear. Two sentences per item —
    the headline and the first summary bullet — is what a listener can hold.
    """
    items = briefing_items(reports, max_items)
    if not items:
        return ""

    sources = {r.get("source") for r in items if r.get("source")}
    newest = max((r.get("created") for r in items if r.get("created")), default=None)

    lines = [
        f"သတင်းဌာန {timefmt.to_burmese_digits(len(sources))} ခုမှ "
        f"သတင်း {timefmt.to_burmese_digits(len(items))} ပုဒ် ရရှိထားပါတယ်။"
    ]
    if newest:
        lines.append(f"အသစ်ဆုံးသတင်းက {_ago_label(newest)} ရောက်ထားတာပါ။")

    for idx, r in enumerate(items, 1):
        head = clean_for_speech(r.get("headline") or r.get("title") or "")
        if not head:
            continue
        lines.append("")
        lines.append(f"{timefmt.to_burmese_digits(idx)}။ [{r.get('source')}] {head}")
        bullets = r.get("bullets") or []
        if bullets:
            lines.append(f"   {clean_for_speech(bullets[0])}")
        when = _ago_label(r.get("published") or r.get("created"))
        if when:
            lines.append(f"   ({when} ဖော်ပြခဲ့သည်)")

    return "\n".join(lines)


def format_search(query: str, results: list[dict], max_items: int = 6) -> str:
    """Search hits as spoken Burmese, or an honest "nothing found"."""
    if not results:
        return (f"'{query}' နှင့် ပတ်သက်သော သတင်းကို လွန်ခဲ့သော ရက်ပိုင်းအတွင်း "
                f"ရှာမတွေ့ပါ။")

    items = results[:max_items]
    lines = [f"'{query}' နှင့် ပတ်သက်သော သတင်း "
             f"{timefmt.to_burmese_digits(len(items))} ပုဒ် တွေ့ရှိပါတယ်။"]
    for idx, r in enumerate(items, 1):
        title = clean_for_speech(r.get("title") or "")
        when = _ago_label(r.get("published"))
        stamp = f" ({when})" if when else ""
        lines.append(f"{timefmt.to_burmese_digits(idx)}။ [{r.get('source')}] {title}{stamp}")
    return "\n".join(lines)


def format_digest(digest: Optional[dict]) -> str:
    """The daily digest as spoken Burmese, with its own age stated up front.

    The digest is generated on a schedule, and a schedule can stop. The stored
    one may be from this morning or from three weeks ago, and read aloud with no
    date attached the second is indistinguishable from the first — the listener
    hears "today's summary" and believes it. So the age is always spoken.
    """
    if not digest or not digest.get("full_report"):
        return ""

    body = clean_for_speech(digest.get("full_report"))
    when = _ago_label(digest.get("created"))

    target: Optional[datetime] = None
    try:
        target = datetime.strptime(str(digest.get("target_date") or "")[:10], "%Y-%m-%d")
        target = target.replace(tzinfo=MYANMAR_TZ)
    except ValueError:
        target = None

    if target and when:
        header = (f"အောက်ပါသည် {timefmt.burmese_month_day(target)}အတွက် "
                  f"နေ့စဉ်သတင်းအနှစ်ချုပ် ဖြစ်ပြီး {when} ထုတ်ပြန်ခဲ့ခြင်း ဖြစ်ပါသည်။")
    elif when:
        header = f"နေ့စဉ်သတင်းအနှစ်ချုပ် — {when} ထုတ်ပြန်ခဲ့ခြင်း ဖြစ်ပါသည်။"
    else:
        header = ""

    return f"{header}\n\n{body}".strip() if header else body


def format_outlet_news(outlet_name: str, target_date: date,
                       items: list[dict], newest_any: Optional[dict] = None) -> str:
    """One outlet's news for one day, as spoken Burmese.

    When the day is empty this says so and names the outlet's most recent
    story instead. "No news found" would be a lie of omission: the outlet is
    publishing, just not on the day that was asked about, and a journalist
    needs to know which of the two it is.
    """
    today = timefmt.now_mmt().date()
    if target_date == today:
        day_label = "ဒီနေ့"
    elif target_date == today - timedelta(days=1):
        day_label = "မနေ့က"
    else:
        day_label = timefmt.burmese_month_day(
            datetime.combine(target_date, _time.min))

    stamp = timefmt.burmese_month_day(datetime.combine(target_date, _time.min))

    # Number and count what is actually SHOWN. An item whose headline cleans to
    # nothing used to be skipped inside the loop while `enumerate` and
    # len(items) carried on counting it — measured on PPIB 2026-09-27, whose
    # first article of the day is titled with a single emoji: the answer said
    # "သတင်း ၂ ပုဒ်" and then began at "၂။", with one story missing and the
    # count one too high. Both wrong, and neither visible without reading the
    # database.
    readable: list[tuple[str, dict]] = []
    for r in items:
        head = clean_for_speech(r.get("title") or "")
        if head:
            readable.append((head, r))

    if not readable:
        lines = [f"{outlet_name} မှာ {day_label} ({stamp}) "
                 f"သတင်းအသစ် မတက်သေးပါ။"]
        if newest_any and newest_any.get("published"):
            when = _ago_label(newest_any["published"])
            lines.append(f"အနီးဆုံး သတင်းကတော့ {when} တက်ထားတာပါ — "
                         f"{clean_for_speech(newest_any.get('title') or '')}")
        return "\n".join(lines)

    sources = {i.get("source") for i in items if i.get("source")}
    name = next(iter(sources)) if len(sources) == 1 else outlet_name
    lines = [f"{name} မှာ {day_label} ({stamp}) သတင်း "
             f"{timefmt.to_burmese_digits(len(readable))} ပုဒ် တက်လာပါတယ်။"]

    for idx, (head, r) in enumerate(readable, 1):
        when = r.get("published")
        clock = timefmt.burmese_clock(when) if when else ""
        lines.append("")
        lines.append(f"{timefmt.to_burmese_digits(idx)}။ {head}"
                     + (f"  ({clock})" if clock else ""))
        bullets = r.get("bullets") or []
        if bullets:
            lines.append(f"   {clean_for_speech(bullets[0])}")

    return "\n".join(lines)


# ── Story-level: summarise one, and find who else carried it ─────────────────

# Every heading the analyzer's Format A template can emit, across both the old
# 7-section prompt and the current 3-section one. Used to find where a section
# starts and, just as importantly, where it ends.
_SECTION_MARKERS = (
    "တစ်မိနစ် အနှစ်ချုပ်",
    "ဂဏန်းက ဘာပြောနေသလဲ",
    "ဒါ မင်းနဲ့ ဘာဆိုင်လဲ",
    "တင်ပြပုံ",
    "ဆက်စပ်နှိုင်းယှဉ်ချက်",
    "ဆက်လက် စောင့်ကြည့်ရမည့်",
)


def extract_section(full_report: Any, marker: str) -> list[str]:
    """The bullets under one named section of a Format A report.

    Stops at the NEXT section header rather than at a fixed list of headings, so
    it works for any section and not only the last one. Returns [] when the
    report has no such section — the older 7-section reports and the new
    3-section ones do not have the same headings.
    """
    started = False
    out: list[str] = []
    for ln in str(full_report or "").splitlines():
        plain = clean_for_speech(_TAG_RE.sub("", ln)).strip()
        if not plain:
            continue
        if any(m in plain for m in _SECTION_MARKERS):
            if started:
                break
            if marker in plain:
                started = True
            continue
        if started:
            stripped = re.sub(r"^[•\-*\s]+", "", plain).strip()
            if stripped:
                out.append(stripped)
    return out


def report_for(article_id: str) -> Optional[dict]:
    """One article's analysed report, split into headline / summary / comparison.

    A malformed id returns None rather than reaching the database. Postgres
    answers a non-uuid with 22P02 and the query raises, and the id arrives from
    whatever the model passed — the offline checks hand it "aaaa-bbbb". A bad
    id means "no report", which is the same answer as a missing one and must
    not become a crash on the voice path.
    """
    if not _is_uuid(article_id):
        return None

    def produce() -> Optional[dict]:
        sb = _get_client()
        if sb is None:
            return None
        res = _run(
            lambda: sb.table("news_reports")
            .select("full_report,created_at")
            .eq("article_id", article_id)
            .eq("report_type", "single_editorial")
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            "report_for",
        )
        rows = res.data or []
        if not rows:
            return None
        fr = rows[0].get("full_report") or ""
        headline, bullets = extract_summary(fr)
        return {
            "headline": headline,
            "bullets": bullets,
            "comparison": extract_section(fr, "ဆက်စပ်နှိုင်းယှဉ်ချက်"),
            "created": _as_mmt(rows[0].get("created_at")),
            "full_report": fr,
        }

    return _cached(f"report_for:{article_id}", produce, None)


def find_story(query: str, days: int = 30) -> Optional[dict]:
    """The single most likely article for a free-text description of a story.

    "အဲဒါ" has no id attached to it — the user is pointing at something they
    just heard, and the words they repeat are the only handle. There are three
    kinds of those, and they are not equally good:

      1. **The headline JARVIS read out.** It comes from the ANALYSED REPORT,
         which the analyzer rewrote, so it frequently is not the stored article
         title at all. Measured on the live database 2026-09-27: the four newest
         briefed headlines ALL missed the article search and ALL four were found
         in the report text. This is the path the feature lives or dies on.
      2. **A phrase from the article itself** ("ငွေဈေး", "မင်းအောင်လှိုင်") —
         searched against title and content.
      3. **A half-remembered headline.** Neither of the above matches a
         near-miss, so the longest distinctive phrase inside it is tried last.

    Tried in that order rather than by cost: a wrong story is worse than a
    slower answer, and in practice the first query hits.
    """
    q = str(query or "").strip()
    if len(q) < 2:
        return None

    for hits in (search_reports(q, days=days, limit=1),
                 search_articles(q, days=days, limit=1)):
        if hits:
            return hits[0]

    # Longest phrase first — in Burmese the long whitespace-separated units are
    # the proper nouns, which is exactly what another outlet would repeat.
    for token in _core_tokens(q):
        if token == q:
            continue  # already searched above — the cache handles it but skip the call
        for hits in (search_reports(token, days=days, limit=1),
                     search_articles(token, days=days, limit=1)):
            if hits:
                return hits[0]
    return None


_PARTICLES = ("၏", "ရဲ့", "အပေါ်", "အတွက်", "နှင့်", "တွင်", "မှာ", "ကို", "သည်",
              "များ", "တွေ", "က")

# Burmese is written with combining marks, so ONE syllable can be four or five
# codepoints. "လို့" — a colloquial particle — measures 4 characters and passed
# every length test, so it was treated as a distinctive phrase and helped match
# stories that had nothing in common. Counting base letters instead is what
# separates a word from a particle: "လို့" has one, "ဘန်ကောက်" has four.
_BURMESE_LETTER = re.compile(
    "[" "\u1000-\u1021" "\u1023-\u1027" "\u1029\u102A" "\u103F" "\u1040-\u1049"
    "A-Za-z0-9" "]"
)


def _weight(token: Any) -> int:
    """How many letters a token has, ignoring Burmese vowel/tone marks."""
    return len(_BURMESE_LETTER.findall(str(token or "")))


def _core_tokens(title: Any, min_len: int = 4, limit: int = 6,
                 min_weight: int = 2) -> list[str]:
    """Distinctive words from a headline, for matching the same story elsewhere.

    Burmese is written without word spaces, but headlines DO separate phrases,
    so a whitespace split yields phrase-sized units. Trailing particles are
    trimmed, because the same name is "အိုဘားမား" in one outlet and "အိုဘားမား၏"
    in another and a substring test on the untrimmed form would miss it.
    Punctuation is stripped too: a truncated headline ends "…" and a clause ends
    "၊", and "ဆုံးဖြတ်ချက်…" would never appear in another outlet's text. Longest
    first — the long Burmese units are the proper nouns.

    min_weight is the fix for the particle problem above and is deliberately
    separate from min_len: a length floor written in characters cannot tell a
    four-codepoint particle from a four-letter word.
    """
    found = []
    for raw in re.split(r"[\s\u200b]+", str(title or "")):
        t = raw.strip().strip("…၊။.,!?\"'()[]{}")
        for p in _PARTICLES:
            if t.endswith(p) and len(t) - len(p) >= min_len:
                t = t[: -len(p)]
                break
        t = t.strip("…၊။.,!?\"'()[]{}")
        if (len(t) >= min_len and _weight(t) >= min_weight
                and not re.fullmatch(r"[၀-၉]+", t)):
            found.append(t)

    seen: set[str] = set()
    out: list[str] = []
    for t in sorted(found, key=len, reverse=True):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit]


def _overlap(tokens: list[str], text: Any) -> int:
    t = str(text or "")
    return sum(1 for tok in tokens if tok in t)


# A phrase that three or more of an outlet's own recent articles already share is
# not a fingerprint of one story.
_DISTINCTIVE_MAX_HITS = 2


def _distinctive(tokens: list[str], pool: list[str],
                 max_hits: int = _DISTINCTIVE_MAX_HITS) -> list[str]:
    """Keep only the tokens that are rare in that outlet's own output.

    WHY THIS IS NOT OPTIONAL — measured on the live database 2026-09-27
        With a plain "two shared phrases" bar, the very first scan produced a
        match that did not exist. The Bangkok flood story was reported as carried
        by The Irrawaddy, citing a story about a diplomat being summoned to
        Naypyidaw and another about a former general shooting himself. The shared
        phrases were "ထိုင်းနိုင်ငံ" (Thailand) and "ဘန်ကောက်" (Bangkok) — a
        country and a city, which is what every story from that country shares.
        Two phrases is only a strong bar when the phrases are specific, and
        geography is never specific.

    WHY AN ABSOLUTE CAP AND NOT A FRACTION
        Measured against the same window's Irrawaddy output, 60 articles:
        "ထိုင်းနိုင်ငံ" appeared in 11 and "ဘန်ကောက်" in 5. A fraction of the pool
        gets this wrong in both directions — 50% kept both, and 10% still kept
        "ဘန်ကောက်" at 5 hits, because 5/60 is under a tenth. What actually
        matters is not the share but whether the phrase identifies anything: a
        word in five different articles that week is not a fingerprint. Three is
        the cut, and the pool size only has to be large enough for the count to
        mean something.

    No gazetteer is needed: the pool IS the measurement, which is why this takes
    the candidate articles as an argument rather than a fixed list of place
    names. Dropping a token is safe — the worst case is a missed match, and a
    missed match is much better than a confident wrong one.
    """
    if not pool:
        return list(tokens)
    return [t for t in tokens if sum(1 for text in pool if t in text) <= max_hits]


def _score(tokens: list[str], distinctive: list[str], text: Any) -> tuple[int, int]:
    """(matches among the distinctive tokens, matches overall)."""
    return _overlap(distinctive, text), _overlap(tokens, text)


def _live_token_coverage(target: dict, window_days: int = 3,
                         min_score: int = 2, min_distinctive: int = 1,
                         per_outlet: int = 2) -> dict[str, list[dict]]:
    """Other outlets' articles that share headline phrases with `target`.

    THIS IS A FALLBACK, NOT THE ANSWER — see coverage_in_other_outlets().
    It is reached only for the reports that carry no cross-source section at
    all, which is the older Format A shape. On the reports that do carry one,
    this matcher was measured 2026-09-27 to be wrong in both directions:

      MISSED   The Irrawaddy's Bangkok flood story and BBC Burmese's are the
               same event. They score total=2, distinctive=0, because the only
               shared phrases are "ထိုင်းနိုင်ငံ" and "ဘန်ကောက်" and
               _distinctive() drops geography — correctly, since that is what
               every story from Thailand shares. 27 of the 30 newest briefed
               stories came back empty, the Bangkok flood among them.
      WRONG    46 cross-outlet pairs did clear both bars over the same week.
               Sampling them, about half are different stories that share an
               actor: a Chinese car company's EV battery story accepted as BBC
               coverage of a Bangkok train fire, on the shared words "ကုမ္ပဏီ"
               and "ထုတ်ပြ".

    The reason is structural, not a matter of tuning: Burmese outlets word the
    same event completely differently, so the true pair keeps no distinctive
    token while an unrelated pair keeps a generic one. `_distinctive`'s verdict
    also depends on the pool window, so one pair can match at 60 articles and
    miss at 120. Tightening or loosening the bar only moves which error you get.

    WHY TWO BARS AND NOT ONE
        A candidate has to clear `min_score` shared phrases AND at least
        `min_distinctive` of those has to survive _distinctive().

    WHY THE TARGET'S OWN OUTLET IS SKIPPED ON BOTH ID AND NAME
        `search_articles()` carries only the display name, and the name stored in
        the database is not always the name in OUTLET_NAMES, so the first version
        reported BBC Burmese as having covered a story BBC Burmese had written.
    """
    tokens = _core_tokens(target.get("title"))
    when = target.get("published")
    if not tokens or when is None:
        return {}

    target_source = target.get("source_id") or ""
    target_key = _outlet_key(target.get("source"))
    start = datetime.combine(when.date() - timedelta(days=window_days), _time.min,
                             tzinfo=timezone.utc)
    end = datetime.combine(when.date() + timedelta(days=window_days + 1), _time.min,
                           tzinfo=timezone.utc)

    def produce() -> dict[str, list[dict]]:
        sb = _get_client()
        if sb is None:
            return {}

        found: dict[str, list[dict]] = {}
        for sid, name in OUTLET_NAMES.items():
            if sid == target_source or _outlet_key(name) == target_key:
                continue
            try:
                res = _run(
                    lambda s=sid: sb.table("news_articles")
                    .select("id,source_name,title,content,url,published_at")
                    .eq("source_id", s)
                    .gte("published_at", start.isoformat())
                    .lt("published_at", end.isoformat())
                    .order("published_at", desc=True)
                    .limit(60)
                    .execute(),
                    f"coverage/{sid}",
                )
            except Exception as e:
                print(f"[Newsroom] coverage/{sid} failed: {e}")
                continue

            rows = res.data or []
            if not rows:
                continue

            # The outlet's own recent articles are the control group: a phrase
            # they all contain is not evidence that any one of them is this
            # story.
            pool = [f"{a.get('title') or ''} {a.get('content') or ''}" for a in rows]
            distinctive = _distinctive(tokens, pool)

            scored = []
            for a, text in zip(rows, pool):
                dist, total = _score(tokens, distinctive, text)
                if total >= min_score and dist >= min_distinctive:
                    scored.append((dist, total, _as_mmt(a.get("published_at")), a, text))
            if not scored:
                continue

            scored.sort(key=lambda x: (-x[0], -x[1],
                                       x[2] or datetime.min.replace(tzinfo=timezone.utc)))
            items = []
            for dist, total, pub, a, text in scored[:per_outlet]:
                rep = report_for(a["id"]) or {}
                items.append({
                    "article_id": a.get("id"),
                    "source": a.get("source_name") or name,
                    "title": a.get("title") or "",
                    "url": a.get("url") or "",
                    "published": pub,
                    "bullets": rep.get("bullets") or [],
                    "headline": rep.get("headline") or "",
                    "shared_terms": [t for t in distinctive if t in text],
                })
            found[name] = items
        return found

    # The key must identify the STORY. It used to be built from
    # `target["article_id"]`, which recent_reports() did not carry — so every
    # story shared the key "coverage:None:3", and within the 90 s cache window
    # the second question was answered with the first story's coverage. A
    # fallback on the title keeps the key story-specific even without an id.
    ident = target.get("article_id") or _story_key(target.get("title"))
    return _cached(f"coverage:{ident}:{window_days}", produce, {}) or {}


# ── the analyser's own comparison, read as the authority ─────────────────────

# NAMING AN OUTLET IS NOT THE SAME AS THE OUTLET COVERING THE STORY.
# The analyser names outlets most often when it is telling you they did NOT
# carry it — measured 2026-09-27 over 120 live reports:
#     "BBC Burmese၊ PPIB を 비롯한 အခြားသတင်းဌာနများတွင် ဤနေ့ ... သတင်းကို
#      တစ်ခုမဆို တွေ့ရှိလို့ မရပါ။"      <- names both, means neither
#     "BBC Burmese၊ PPIB စသည့် အခြားသတင်းဌာနများတွင် ... သတင်း မတွေ့ရှိသေးပါ။"
# A substring test on the outlet name therefore INVERTS the answer on exactly
# those reports. Each sentence is classified for polarity before it counts.

_COVERAGE_NEGATIVE = (
    "မတွေ့ရှိ", "တွေ့ရှိလို့ မရ", "မရှိသေး", "မရှိပါ", "မဖော်ပြ",
    "တစ်ခုမဆို", "ကိုသာ ဖော်ပြ", "သီးခြားဖော်ပြချက် မ", "မတွေ့ရ",
)
_COVERAGE_POSITIVE = (
    "၏ ဖော်ပြချက်", "၏ သတင်း", "၏ ရေးသားချက်", "၏ အစီရင်ခံ",
    "ရေးသားထား", "ဖော်ပြထားပါ", "ဖော်ပြထာ", "က ဖော်ပြ",
    "ပူးတွဲ ဖော်ပြ", "ကိုလည်း", "သတင်းထုတ်ထား", "ထုတ်ပြန်ထား",
)

COVERED = "covered"
NOT_COVERED = "not-covered"
UNCLEAR = "unclear"

_BURMESE_TO_ASCII = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
_ISO_IN_TEXT = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _sentences(text: Any) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[။.!?])\s+|\n+", str(text or "")) if s.strip()]


def _mention_aliases(source_id: str) -> tuple[str, ...]:
    """The spellings of one outlet that turn up in a comparison section.

    The analyser writes the Latin display name ("BBC Burmese", "The Irrawaddy",
    "PPIB"), so those come first; the Burmese aliases are added for the reports
    that switch language. Bare "bbc" is deliberately left out — it matches
    inside "bbcburmese" and inside any URL.
    """
    name = OUTLET_NAMES.get(source_id, source_id)
    out = {name, name.replace("The ", "")}
    for alias in OUTLET_ALIASES.get(source_id, ()):
        if any("\u1000" <= ch <= "\u109f" for ch in alias):
            out.add(alias)
    return tuple(sorted(out, key=len, reverse=True))


def _verdict_for(text: str, source_id: str) -> tuple[str, str]:
    """(verdict, the sentence that decided it) for one outlet in one section."""
    aliases = _mention_aliases(source_id)
    for s in _sentences(text):
        if not any(a in s for a in aliases):
            continue
        neg = sum(1 for m in _COVERAGE_NEGATIVE if m in s)
        pos = sum(1 for m in _COVERAGE_POSITIVE if m in s)
        if pos > neg:
            return COVERED, s
        if neg > pos:
            return NOT_COVERED, s
        return UNCLEAR, s
    return "", ""


def _dates_in(text: Any) -> list[date]:
    """Every yyyy-mm-dd the section mentions, Burmese digits included.

    The analyser writes "BBC Burmese (၂၀၂၆-၀၉-၂၇) ၏ ဖော်ပြချက်အရ ...", and
    that date is the cheapest way to pick the RIGHT article out of the named
    outlet's output — much better than ranking by shared words, which is what
    failed in the first place.
    """
    plain = str(text or "").translate(_BURMESE_TO_ASCII)
    out: list[date] = []
    for y, m, d in _ISO_IN_TEXT.findall(plain):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return out


def report_coverage_verdicts(target: dict) -> tuple[dict[str, tuple[str, str]], str]:
    """What the analyser's own comparison section says about the OTHER outlets.

    -> ({outlet name: (verdict, evidence sentence)}, the whole section as text)

    Verdicts: COVERED / NOT_COVERED / UNCLEAR, and an outlet that is absent from
    the dict was never named. See coverage_in_other_outlets() for why this is
    read instead of matching headlines.
    """
    report = report_for((target or {}).get("article_id") or "")
    comparison = " ".join(report.get("comparison") or []) if report else ""
    if not comparison.strip():
        return {}, ""

    target_key = _outlet_key(target.get("source"))
    out: dict[str, tuple[str, str]] = {}
    for sid, name in OUTLET_NAMES.items():
        if sid == (target.get("source_id") or "") or _outlet_key(name) == target_key:
            continue
        verdict, evidence = _verdict_for(comparison, sid)
        if verdict:
            out[name] = (verdict, evidence)
    return out, comparison


def _articles_for_outlet(sb: Any, source_id: str, start: Any, end: Any,
                         limit: int = 60) -> list[dict]:
    def q():
        query = (sb.table("news_articles")
                 .select("id,source_id,source_name,title,content,url,published_at")
                 .eq("source_id", source_id))
        if start is not None:
            query = (query.gte("published_at", start.isoformat())
                     .lt("published_at", end.isoformat()))
        return query.order("published_at", desc=True).limit(limit).execute()

    res = _run(q, f"coverage_articles/{source_id}")
    return res.data or []


def coverage_in_other_outlets(target: dict, window_days: int = 3,
                              per_outlet: int = 1, **legacy) -> dict[str, list[dict]]:
    """Other outlets' articles that carried `target`'s story.

    THE ANALYSER'S OWN COMPARISON IS THE AUTHORITY, NOT A HEADLINE MATCH.
    Every Format A report carries a cross-source section the analyser wrote
    after reading the candidate articles, and that section is the only place
    the correlation exists — `news_reports` has no column for it (measured:
    id, article_id, report_type, target_date, summary_points, full_report,
    created_at; `summary_points.comparison_count` counts candidates offered,
    not outlets that carried it). Reading the prose is therefore not a
    shortcut around the data, it IS the data. _live_token_coverage() is what
    happens when the question is answered by matching headlines instead, and
    it was measured wrong in both directions.

    WHY A VERDICT IS NOT JUST "IS THE OUTLET NAMED"
        Because the analyser names outlets to say they did NOT carry it. Only
        a positively-attributed mention counts as coverage; the polarity
        markers and the two live examples are above. An UNCLEAR sentence is
        passed through to format_comparison() rather than resolved here, so
        the analyser's own words can be shown instead of a verdict invented
        from them. A confident wrong "yes" is the worst answer this can give.

    WHICH ARTICLE IS SHOWN FOR A COVERING OUTLET
        The section usually dates the article it read ("BBC Burmese
        (၂၀၂၆-၀၉-၂၇)"), so that date is matched first and shared words are
        only the tie-break. The headline shown is the article's own analysed
        headline, and the section's sentence is quoted alongside it.

    Reports with no cross-source section (the older Format A shape) fall back
    to the headline matcher, which is the best that can be done with them.
    """
    verdicts, comparison = report_coverage_verdicts(target)
    if not comparison.strip():
        return _live_token_coverage(target, window_days, per_outlet=per_outlet)

    covered = {name: ev for name, (v, ev) in verdicts.items() if v == COVERED}
    if not covered:
        return {}

    def produce() -> dict[str, list[dict]]:
        sb = _get_client()
        if sb is None:
            return {}
        when = target.get("published")
        start = end = None
        if when is not None:
            start = datetime.combine(when.date() - timedelta(days=window_days),
                                     _time.min, tzinfo=timezone.utc)
            end = datetime.combine(when.date() + timedelta(days=window_days + 1),
                                   _time.min, tzinfo=timezone.utc)

        tokens = _core_tokens(target.get("title"), limit=8)
        found: dict[str, list[dict]] = {}
        for name, evidence in covered.items():
            sid = next((s for s, n in OUTLET_NAMES.items() if n == name), None)
            if not sid:
                continue
            rows = _articles_for_outlet(sb, sid, start, end)
            if not rows:
                continue
            wanted = _dates_in(evidence)
            # The evidence sentence DESCRIBES the other outlet's article, so it
            # is a better key to which article it was than the target's own
            # headline. Measured 2026-09-27: ranking on the target's words alone
            # picked an unrelated Tanintharyi flood story for the Bangkok pair,
            # because both were published the same day and the date bonus
            # dominated a zero topical score.
            evidence_tokens = _core_tokens(evidence, limit=8)

            def rank(a, _wanted=wanted, _tokens=tokens, _ev=evidence_tokens):
                text = f"{a.get('title') or ''} {a.get('content') or ''}"
                topical = _overlap(_ev, text) + _overlap(_tokens, text)
                pub = _as_mmt(a.get("published_at"))
                dated = 1 if (pub and pub.date() in _wanted) else 0
                return (topical, dated)

            rows.sort(key=rank, reverse=True)

            items = []
            for a in rows[:per_outlet]:
                if rank(a)[0] < 1:
                    # Nothing in this article ties it to the story. Reporting
                    # the outlet as coverage is still right — the analyser said
                    # so and its sentence is quoted — but showing a headline we
                    # cannot tie to the story would be a fresh wrong answer.
                    continue
                rep = report_for(a.get("id")) or {}
                items.append({
                    "article_id": a.get("id"),
                    "source": a.get("source_name") or name,
                    "title": a.get("title") or "",
                    "url": a.get("url") or "",
                    "published": _as_mmt(a.get("published_at")),
                    "bullets": rep.get("bullets") or [],
                    "headline": rep.get("headline") or "",
                    "shared_terms": [],
                    "evidence": evidence,
                })
            if items:
                found[name] = items
        return found

    ident = target.get("article_id") or _story_key(target.get("title"))
    return _cached(f"coverage2:{ident}:{window_days}", produce, {}) or {}


def _outlet_key(name: Any) -> str:
    """One outlet, one key, however it is spelled.

    The database's `source_name` is not always the name in OUTLET_NAMES — a
    re-post arrives under a decorated caption — and this comparison is what keeps
    an outlet from being reported as another outlet to itself. Squashed and
    lowercased, so "BBC Burmese" and "BBC Burmese " are one outlet.
    """
    return re.sub(r"[\s\-_]+", "", re.sub(r"\(.*?\)", "", str(name or ""))).lower()


def format_story_summary(story: dict, report: Optional[dict]) -> str:
    """A short spoken summary of ONE story.

    Leads with the report's headline rather than the stored article title: the
    headline is what JARVIS read out, and therefore the only sentence the user
    recognises. The two differ often — the analyzer rewrites the headline — and
    opening with an unfamiliar sentence reads as "that is not the story I meant".
    """
    report = report or {}
    title = clean_for_speech(report.get("headline") or story.get("title") or "")
    source = story.get("source") or "Unknown"
    when = story.get("published")

    lines = [f"[{source}] {title}"]
    if when:
        lines.append(f"({timefmt.burmese_clock(when)} တွင် ဖော်ပြခဲ့သည်)")

    bullets = report.get("bullets") or []
    if bullets:
        lines.append("")
        lines.append("အနှစ်ချုပ် —")
        # Burmese numeral markers, not "•": this text is read aloud, and a TTS
        # engine either skips a bullet or says the word "bullet". format_status()
        # already settled on this marker for the same reason.
        for idx, b in enumerate(bullets[:3], 1):
            lines.append(f"{timefmt.to_burmese_digits(idx)}။ {clean_for_speech(b)}")
    else:
        lines.append("")
        lines.append("ဤသတင်းအတွက် သုံးသပ်ချက် အစီရင်ခံစာ မရှိသေးပါ။")

    return "\n".join(lines)


def other_outlet_names(target: dict) -> list[str]:
    """The other outlets a comparison actually checks.

    Three of them — and saying so out loud is the point. The newsroom collects
    four outlets, so "is this in the other papers?" can only ever mean "did the
    other three carry it". Naming them is what makes a "no" answer judgeable: the
    user can see the search covered three papers, not the news cycle, and decide
    whether that is enough for what they are doing.

    The source outlet is excluded — it is not "another outlet" to itself.
    """
    source_key = _outlet_key((target or {}).get("source"))
    names: list[str] = []
    seen: set[str] = {source_key}
    for name in OUTLET_NAMES.values():
        k = _outlet_key(name)
        if k not in seen:
            seen.add(k)
            names.append(name)
    return names


def format_comparison(story: dict, coverage: dict[str, list[dict]],
                      report: Optional[dict] = None) -> str:
    """Who else carried the story, and how their version compares.

    THE SCOPE IS PART OF THE ANSWER
        The newsroom holds four outlets, so "no other outlet has it" means "not
        PPIB, not BBC Burmese, not The Irrawaddy, not DVB Burmese" — a statement
        about four papers, never about the news cycle. The searched outlets are
        therefore always named, and the answer never claims more than it checked.

        An earlier version of this also read four live feeds from outside the
        newsroom and folded them into the same list. It was removed on the user's
        instruction, and the reason is worth keeping: those feeds are a
        different and much weaker source — a headline and a date, matched on
        shared words — so listing them beside an analysed report presented a
        headline match with the authority of an analysis. The newsroom's four
        outlets are the system; anything else is a second system with its own
        registry, and the two must not be blended into one answer.

    WHEN NOBODY ELSE CARRIED IT
        It says so, and quotes the analyser's own sentence — the analyser ran a
        ±2-day cross-source window when it wrote the report, so its note is the
        evidence for the "no". Only sentences that do NOT attribute the story to
        an outlet are quoted here. An earlier version quoted the section
        blindly, so a story the analyser had correlated with BBC Burmese was
        answered with "not found elsewhere" immediately followed by the sentence
        naming BBC Burmese — and with BBC Burmese in the searched-outlets list.
        That contradiction is what this rewrite removes.

    WHEN THE ANALYSER NAMED AN OUTLET WITHOUT A READABLE VERDICT
        Those sentences are listed separately, as unclear, rather than folded
        into either the "yes" or the "no". The user can read the analyser's own
        words and judge for themselves; inventing a verdict from them is what
        produced the confident wrong answers this replaced.
    """
    coverage = coverage or {}
    report = report or {}

    source = story.get("source") or "Unknown"
    head = clean_for_speech(report.get("headline") or story.get("title") or "")
    searched = other_outlet_names(story)
    verdicts, comparison = report_coverage_verdicts(story)

    if not coverage:
        lines = [
            f"စစ်ဆေးကြည့်တော့ {source} ဖော်ပြထားတဲ့ ဤသတင်းကို "
            f"အခြားသတင်းဌာနများမှာ ဖော်ပြထားတာ မတွေ့ရှိပါ။",
            "",
            f"မူရင်း — [{source}] {head}",
        ]

        denied = [ev for (v, ev) in verdicts.values() if v == NOT_COVERED]
        unclear = [ev for (v, ev) in verdicts.values() if v == UNCLEAR]

        if denied:
            lines.append("")
            lines.append("သုံးသပ်ချက် အစီရင်ခံစာတွင် ဤသို့ ရေးထားပါသည် —")
            for idx, n in enumerate(denied[:2], 1):
                lines.append(f"{timefmt.to_burmese_digits(idx)}။ {clean_for_speech(n)}")
        elif not comparison.strip():
            lines.append("")
            lines.append("ဤသတင်းအတွက် နှိုင်းယှဉ်ချက် အပိုင်း မပါသော "
                         "သုံးသပ်ချက် အစီရင်ခံစာ ဖြစ်နေပါသည်။ "
                         "ခေါင်းစဉ်အဆင့်သာ စစ်ဆေးနိုင်ခဲ့ပါသည်။")

        if unclear:
            lines.append("")
            lines.append("သေချာစွာ မပြောနိုင်သေးသည့် ဖော်ပြချက် —")
            for idx, n in enumerate(unclear[:2], 1):
                lines.append(f"{timefmt.to_burmese_digits(idx)}။ {clean_for_speech(n)}")

        if searched:
            lines.append("")
            lines.append("ရှာဖွေခဲ့သည့် သတင်းဌာနများ — " + "၊ ".join(searched))
        return "\n".join(lines)

    total = sum(len(v) for v in coverage.values())
    lines = [
        f"ဤသတင်းကို အခြားသတင်းဌာန {timefmt.to_burmese_digits(len(coverage))} ခုမှာ "
        f"ဖော်ပြထားတာ တွေ့ရပါတယ်။",
        "",
        f"မူရင်း — [{source}] {head}",
    ]

    for name in sorted(coverage):
        for it in coverage[name]:
            lines.append("")
            lines.append(f"[{name}] {clean_for_speech(it.get('headline') or it.get('title') or '')}")
            when = it.get("published")
            if when:
                lines.append(f"({timefmt.burmese_clock(when)} တွင် ဖော်ပြခဲ့သည်)")
            bullets = it.get("bullets") or []
            if bullets:
                lines.append(f"   {clean_for_speech(bullets[0])}")
            # The analyser's own sentence about this outlet — the evidence for
            # the match. It is quoted rather than paraphrased so the user can
            # check the reasoning, not just the conclusion.
            evidence = clean_for_speech(it.get("evidence") or "")
            if evidence:
                lines.append(f"   သုံးသပ်ချက်အစီရင်ခံစာတွင် — {evidence}")

    lines.append("")
    lines.append(f"စုစုပေါင်း သတင်း {timefmt.to_burmese_digits(total)} ပုဒ်နှင့် နှိုင်းယှဉ်ပြထားပါတယ်။")
    return "\n".join(lines)


def format_status(status: dict) -> str:
    """Pipeline health as spoken Burmese."""
    if not status:
        ok, reason = available()
        return ("သတင်းစောင့်ကြည့်စနစ်ရဲ့ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ "
                f"အကြောင်းရင်း: {reason}")

    counts = status.get("counts") or {}
    total = sum(counts.values())
    analyzed = counts.get("analyzed", 0)
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)

    lines = [
        f"သတင်းစောင့်ကြည့်စနစ်မှာ သတင်း စုစုပေါင်း "
        f"{timefmt.to_burmese_digits(total)} ပုဒ် ရှိပါတယ်။",
        f"သုံးသပ်ပြီးသား {timefmt.to_burmese_digits(analyzed)} ပုဒ်၊ "
        f"စောင့်ဆိုင်းနေတာ {timefmt.to_burmese_digits(pending)} ပုဒ်၊ "
        f"မအောင်မြင်တာ {timefmt.to_burmese_digits(failed)} ပုဒ် ရှိပါတယ်။",
    ]

    # Which outlets the archive actually contains. Burmese-numeral list markers,
    # not "•", because this text is read aloud.
    sources = status.get("sources") or []
    if sources:
        lines.append("")
        lines.append(f"သတင်းဌာန {timefmt.to_burmese_digits(len(sources))} ခုမှ "
                     f"သတင်းများ ရှိပါတယ် —")
        for idx, s in enumerate(sources, 1):
            newest = s.get("newest")
            tail = f"၊ အသစ်ဆုံး {_ago_label(newest)}" if newest else ""
            lines.append(
                f"{timefmt.to_burmese_digits(idx)}။ {s.get('source_name')} "
                f"({s.get('source_type')}) — "
                f"{timefmt.to_burmese_digits(s.get('total', 0))} ပုဒ်၊ "
                f"သုံးသပ်ပြီး {timefmt.to_burmese_digits(s.get('analyzed', 0))} ပုဒ်{tail}"
            )

    last = status.get("last_run") or {}
    if last.get("started"):
        lines.append(f"နောက်ဆုံး စက်ပတ်လည်မှု ({last.get('job')}) က "
                     f"{_ago_label(last['started'])} လည်ပတ်ခဲ့ပါတယ်။")

    newest = status.get("newest_report")
    if newest:
        lines.append(f"နောက်ဆုံး သုံးသပ်ချက် အစီရင်ခံစာက {_ago_label(newest)} ထွက်ရှိခဲ့ပါတယ်။")

    if pending > 0:
        lines.append("သုံးသပ်ရန် ကျန်ရှိနေသေးပါတယ်။")
    if failed > 0:
        lines.append("မအောင်မြင်တဲ့ သတင်းတွေကို စစ်ဆေးဖို့ လိုအပ်ပါတယ်။")

    return "\n".join(lines)


def format_new_items(items: list[dict], max_items: int = 3) -> str:
    """Newly analysed reports, as the line JARVIS is asked to speak unprompted."""
    if not items:
        return ""
    items = items[:max_items]
    lines = [f"သတင်းအသစ် {timefmt.to_burmese_digits(len(items))} ပုဒ် ရောက်လာပါတယ်။"]
    for r in items:
        head = clean_for_speech(r.get("headline") or r.get("title") or "")
        if not head:
            continue
        lines.append(f"[{r.get('source')}] {head}")
        bullets = r.get("bullets") or []
        if bullets:
            lines.append(f"{clean_for_speech(bullets[0])}")
    return "\n".join(lines)
