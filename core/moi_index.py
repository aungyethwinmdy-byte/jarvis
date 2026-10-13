"""A local index of `moi.gov.mm` articles — the fast half of the research engine.

WHY THIS EXISTS (owner's ask, 2026-10-03)

    *"MOI website ကို မေးတိုင်း live website တစ်ခုလုံး crawl မလုပ်သင့်ပါဘူး … background crawler
    နေ့တိုင်း … MOI Crawler → New articles only → Extract → Database … ပြီးရင် JARVIS က Database
    Search → Relevant articles → Gemini → Answer … Database မှာ မတွေ့ရင် → Live MOI Search."*

    So the live reader (`core/moi_client.py`) is unchanged and still the source of
    truth. This module is a **cache with an honest label**, not a replacement:
    every answer built from it says so, and the live site is consulted for
    anything the index cannot answer.

    **This does not overturn the 2026-10-01 rule** ("state news comes from the
    website, live; never reach for the DB first"). That rule is about not
    answering a *current* question from a *stale copy*. Here the copy is stamped
    with the date it was taken, a freshness report is part of `status()`, and a
    "today / is there anything new" question goes live. The distinction is
    stated in `actions/moi_research.py`, which is the only caller.

WHAT IS STORED, AND WHY EACH COLUMN CAN BE TRUSTED

    The table is the owner's own list — `id, title, url, section,
    published_date, author, content, summary, people, organizations, locations,
    numbers, keywords, created_at` — plus the columns the index needs to work
    (`section_label`, `category`, `search_text`, `updated_at`).

    * **`content` is the article's own body**, read by `moi_client.article()`.
      Empty is a legal value and is **stored as empty, never invented**: measured
      2026-10-01, `/news/88750` has no body because the headline is the story.
    * **`people` / `organizations` come from `core/entities.py`** — the same
      measured extractors the paper pipeline uses — so a name here is a name the
      article actually printed, with its rank. This file invents no person.
    * **`locations` come from a glossary**, matched the way `ministries_in`
      matches: a fixed list, so a malformed stretch of text cannot produce a
      place that does not exist (`LOCATIONS`).
    * **`numbers` are the digit runs the article printed**, each with the phrase
      around it, so "ရွှေဈေး ၃,၅၀၀,၀၀၀ ကျပ်" is answerable without the model
      re-reading the page.
    * **`keywords` are the article's most frequent words** after a stop list —
      a ranking aid, explicitly *not* an interpretation.

    An extraction is a claim about the text, so this module keeps the text too
    and every formatter shows the source. Nothing here is a summary.

HOW "NEW ARTICLES ONLY" IS DECIDED

    `crawl()` asks `moi_client.list_section()` for the newest cards (they arrive
    newest-first) and fetches the body **only for an id it does not already
    hold**. That is the owner's "new articles only", and it is what keeps the
    daily run short: after the first pass, a day's addition is a handful of
    bodies rather than the whole archive. `new_cards()` is the pure decision,
    kept separate so `check_moi_index.py` can test it without a network.

FAILURE IS A RESULT, NOT AN EXCEPTION

    `crawl()` returns a report and never raises. A section that could not be
    reached is reported as unreachable — it is **not** reported as having no new
    articles, because those are different facts and the second one is how a
    silent "nothing new today" gets spoken over a dead socket.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import timedelta
from pathlib import Path

from core import entities as ent
from core import moi_client as mc
from core.timefmt import now_mmt, to_burmese_digits

# `memory/` is where this project already keeps its state (`long_term.json`,
# `newsroom_watch_state.json`). The index is state, not a data file the user
# manages, so it lives beside them rather than in a new folder.
_ROOT = Path(__file__).resolve().parent.parent
DB_PATH: Path = _ROOT / "memory" / "moi_articles.db"
TABLE = "moi_articles"
META_TABLE = "moi_index_meta"

# The owner's column list, in his order, then the index's own working columns.
# A test asserts this exact set, because a column that quietly disappears is a
# fact that quietly stops being stored.
SPEC_COLUMNS: tuple[str, ...] = (
    "id", "title", "url", "section", "published_date", "author", "content",
    "summary", "people", "organizations", "locations", "numbers", "keywords",
    "created_at",
)
EXTRA_COLUMNS: tuple[str, ...] = (
    "section_label", "category", "search_text", "updated_at",
)
COLUMNS: tuple[str, ...] = SPEC_COLUMNS + EXTRA_COLUMNS

# Multi-valued columns are JSON text; this is the set `upsert` serialises.
_LIST_COLUMNS = ("people", "organizations", "locations", "numbers", "keywords")

_LOCK = threading.Lock()          # one writer at a time; SQLite is single-writer

# How deep the crawler walks each section. Two pages (~40 cards) cover several
# weeks of the slow sections (president-news posts 1–2 a day), **but not the fast
# ones**: /other-news grows ~40 cards a day, so a 2-page walk reaches barely one
# day back. Measured 2026-10-05 — the Vietnam-trip story `/news/88673`
# (published 2026-10-02) sits on `/other-news?page=5`, and the 2-page daily
# crawl never saw it, so the index had no row for a story the site lists.
# Six pages keep every fast section covered for ~4–5 days; `MAX_FETCH_PER_RUN`
# and the body fetches bound the real work — see `crawl()`'s note on why the
# scan must not shortcut on known cards.
CRAWL_PAGES = 6
# The first pass has no "known" row to stop at, so the walk is bounded by the
# number of bodies it will fetch rather than by the page count.
MAX_FETCH_PER_RUN = 400
# A first crawl has no known frontier to stop at, so the initial fill could
# otherwise launch MAX_FETCH_PER_RUN heavy network requests. The card's
# metadata (headline / url / section / entities) is still stored; only the body
# text fetch is capped so the first crawl finishes in minutes.
_FIRST_CRAWL_BODY_CAP = 60
# The site's own politeness pause, reused so the crawler is not the rude client.
_PAUSE = getattr(mc, "_PAUSE", 0.3)


def _norm(text) -> str:
    """Whitespace removed and lower-cased — the comparison form.

    Borrowed from `moi_client`'s matching, and for the same measured reason: the
    site writes `နိုင်ငံတော် သမ္မတ` and `နိုင်ငံတော်သမ္မတ`, and a raw substring
    test matches one and not the other.
    """
    return re.sub(r"\s+", "", str(text or "")).lower()


def _db_path() -> Path:
    """Where the database lives, overridable for tests.

    An environment override rather than a module-global the test mutates, so the
    suite can run against a temp file and leave nothing behind.
    """
    override = os.environ.get("MOI_INDEX_DB")
    return Path(override) if override else DB_PATH


def _connect() -> sqlite3.Connection:
    """A connection to the index, with the schema ensured.

    The schema is created here rather than only in `init()`, so a first call
    from an action cannot run against a table that does not exist yet — which
    would come back as an empty result and be spoken as "no such news". That is
    the same defect class this project keeps finding: a missing source and an
    empty source must not look alike.
    """
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # WAL lets the crawler write while a voice turn reads; without it a long
    # crawl blocks every question asked during it.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    """Create the table and its indexes if they are not there. Idempotent."""
    cols = ", ".join(f'"{c}" TEXT' for c in COLUMNS if c != "id")
    con.execute(f'CREATE TABLE IF NOT EXISTS "{TABLE}" ("id" TEXT PRIMARY KEY, {cols})')
    con.execute(f'CREATE TABLE IF NOT EXISTS "{META_TABLE}" '
                f'("key" TEXT PRIMARY KEY, "value" TEXT)')
    # The two questions the index is asked most: "what is newest" and "the news
    # in this section". Without the indexes both are full scans as the table
    # grows — measured 2026-10-01, `list_section` returned 301 cards for the
    # president section alone, and a full scan per question would undo the point
    # of the index.
    con.execute(f'CREATE INDEX IF NOT EXISTS "ix_moi_date" ON "{TABLE}"("published_date")')
    con.execute(f'CREATE INDEX IF NOT EXISTS "ix_moi_section" ON "{TABLE}"("section")')
    con.commit()


def init() -> str:
    """Create the database if it is missing. Returns the path, for reporting."""
    with _LOCK:
        con = _connect()
        con.close()
    return str(_db_path())


def set_meta(key: str, value: str) -> None:
    """Record one fact about the index itself (last run, last result)."""
    with _LOCK:
        con = _connect()
        con.execute(f'INSERT INTO "{META_TABLE}"("key","value") VALUES(?,?) '
                    f'ON CONFLICT("key") DO UPDATE SET "value"=excluded."value"',
                    (str(key), str(value)))
        con.commit()
        con.close()


def meta(key: str, default: str = "") -> str:
    """One recorded fact, or `default` when it was never written."""
    con = _connect()
    try:
        row = con.execute(f'SELECT "value" FROM "{META_TABLE}" WHERE "key"=?',
                          (str(key),)).fetchone()
    finally:
        con.close()
    return row["value"] if row else default


def last_run() -> str:
    """When the crawler last completed, ISO, or "" if it never has.

    `""` is the honest answer for "never run" and the caller says that rather
    than printing a blank where a date belongs.
    """
    return meta("last_run", "")


def reset() -> None:
    """Drop every row and the run record. For the checks, and for a rebuild.

    Deliberately explicit rather than a side effect of a failed crawl: the
    owner's data should only ever go when someone asks for it to go.
    """
    with _LOCK:
        con = _connect()
        con.execute(f'DELETE FROM "{TABLE}"')
        con.execute(f'DELETE FROM "{META_TABLE}"')
        con.commit()
        con.close()


# ── Extraction ────────────────────────────────────────────────────────────────
#
# A glossary, matched the way `entities.ministries_in` matches: the text is
# searched for **known** places rather than parsed for them, so a malformed
# stretch of Burmese cannot produce a place that does not exist. Every entry
# here is a name the state papers print. It is deliberately separate from
# `entities._COUNTRIES` (a private list tuned for *person* extraction) so a
# change to one cannot silently change the other.
LOCATIONS: tuple[str, ...] = (
    # Regions and states, spelled as the papers spell them.
    "ရန်ကုန်တိုင်းဒေသကြီး", "မန္တလေးတိုင်းဒေသကြီး", "စစ်ကိုင်းတိုင်းဒေသကြီး",
    "ပဲခူးတိုင်းဒေသကြီး", "မကွေးတိုင်းဒေသကြီး", "ဧရာဝတီတိုင်းဒေသကြီး",
    "တနင်္သာရီတိုင်းဒေသကြီး", "ကချင်ပြည်နယ်", "ကယားပြည်နယ်", "ကရင်ပြည်နယ်",
    "ချင်းပြည်နယ်", "မွန်ပြည်နယ်", "ရခိုင်ပြည်နယ်", "ရှမ်းပြည်နယ်",
    # The cities the president's and ministers' tours report.
    "နေပြည်တော်", "ရန်ကုန်", "မန္တလေး", "မော်လမြိုင်", "စစ်ကိုင်း", "တောင်ကြီး",
    "မြစ်ကြီးနား", "လားရှိုး", "မုံရွာ", "မကွေး", "ပြည်", "ပုသိမ်", "မိတ္ထီလာ",
    "ဗန်းမော်", "လွိုင်ကော်", "ဟားခါး", "စစ်တွေ", "ကျိုင်းတုံ", "မူဆယ်",
    "တာချီလိတ်", "ကော့သောင်း", "ဘားအံ", "သထုံ", "မအူပင်", "ဟင်္သာတ",
    "ပျဉ်းမနား", "ရမည်းသင်း", "ရွှေဘို", "ကသာ", "ဖားကန့်", "မောင်းတော်",
    # Countries a state visit names.
    "ဗီယက်နမ်", "ကမ္ဘောဒီးယား", "လာအို", "ထိုင်း", "တရုတ်", "အိန္ဒိယ",
    "ဘင်္ဂလားဒေ့ရှ်", "ဂျပန်", "ကိုရီးယား", "ရုရှား", "အမေရိကန်",
    "အင်ဒိုနီးရှား", "မလေးရှား", "စင်္ကာပူ", "ဖိလစ်ပိုင်", "နီပေါ",
    "သီရိလင်္ကာ", "ပါကစ္စတန်", "ဩစတြေးလျ",
)

# Non-ministry bodies the papers name often enough to be worth indexing. Kept
# out of `organizations`-via-ministries because they are not ministries, and
# listing them as such would overstate what the article said.
BODIES: tuple[str, ...] = (
    "ကုလသမဂ္ဂ", "အာဆီယံ", "မြန်မာနိုင်ငံတော်ဗဟိုဘဏ်", "ကြက်ခြေနီအသင်း",
    "ပြည်ထောင်စုလွှတ်တော်", "ပြည်သူ့လွှတ်တော်", "အမျိုးသားလွှတ်တော်",
    "ကမ္ဘာ့ကျန်းမာရေးအဖွဲ့", "မြန်မာနိုင်ငံ အမျိုးသားဘဏ်",
)

# **The shortened ministry names the papers actually print.** A glossary on both
# sides, and deliberately *not* a pattern: `entities.ministries_in` matches the
# full name only, so a sentence naming the abbreviated ministry returned **0
# organisations** (measured 2026-10-03). A regex ending in `ဝန်ကြီးဌာန` was tried
# and rejected — it starts at the earliest position in the sentence, so
# `'အစီရင်ခံစာအရ ကုန်သွယ်ရေးဝန်ကြီးဌာန'` matched as one "organisation", with the
# clause in front of it attached. A fixed list cannot invent an organisation.
MINISTRY_SHORT: tuple[str, ...] = (
    "ပညာရေးဝန်ကြီးဌာန", "ကျန်းမာရေးဝန်ကြီးဌာန", "ကုန်သွယ်ရေးဝန်ကြီးဌာန",
    "လူမှုဝန်ထမ်းဝန်ကြီးဌာန", "စီးပွားရေးဝန်ကြီးဌာန", "ဘဏ္ဍာရေးဝန်ကြီးဌာန",
    "လယ်ယာစိုက်ပျိုးရေးဝန်ကြီးဌာန", "ကာကွယ်ရေးဝန်ကြီးဌာန",
    "နယ်စပ်ရေးဝန်ကြီးဌာန", "တည်ဆောက်ရေးဝန်ကြီးဌာန",
    "သယ်ယူပို့ဆောင်ရေးဝန်ကြီးဌာန", "ပို့ဆောင်ရေးနှင့် ဆက်သွယ်ရေးဝန်ကြီးဌာန",
    "စွမ်းအင်ဝန်ကြီးဌာန", "သာသနာရေးဝန်ကြီးဌာန", "အလုပ်သမားဝန်ကြီးဌာန",
    "ပြည်ထဲရေးဝန်ကြီးဌာန", "နိုင်ငံခြားရေးဝန်ကြီးဌာန", "စက်မှုလက်မှုဝန်ကြီးဌာန",
    "သယံဇာတဝန်ကြီးဌာန", "ရေကြောင်းနှင့် ဆိပ်ကမ်းဝန်ကြီးဌာန",
    "မွေးမြူရေးနှင့် ကုသရေးဝန်ကြီးဌာန", "ငါးလုပ်ငန်းဝန်ကြီးဌာန",
    "ဟိုတယ်နှင့် ခရီးသွားရေးဝန်ကြီးဌာန", "အမျိုးသမီးရေးရာဝန်ကြီးဌာန",
    "အားကစားနှင့် လူငယ်ရေးရာဝန်ကြီးဌာန", "ကျန်းမာရေးနှင့် အားကစားဝန်ကြီးဌာန",
)

# Words that would otherwise top every keyword list. Particles, function words
# and the handful of verbs a Burmese news sentence cannot avoid.
_STOPWORDS = frozenset("""
သည် ကို က ၏ ၌ မှာ တွင် နှင့် နှင့်အတူ များ တို့ ဖြစ် ဖြစ်သည် ခဲ့ ခဲ့သည် မည် ပါ
ရန် အတွက် နေသည် ရှိ ရှိသည် လည်း မိမိ အဖြစ် ထို ဤ ဒီ ၍ လျှင် သော သည့် အား
နေ ပြု ကြ ကြသည် ဟု ဟူသည် အတွင်း အပြင် နောက် ရှေ့ အထိ စသည် အနေဖြင့် အရ
မြန်မာ နိုင်ငံ သတင်း သတင်းများ ရက်နေ့ ရက် နေ့ ခု ဦး ဒေါ် ဒေါက်တာ
the and for with from that this was were has have are its their his her
""".split())

# A digit run, ASCII or Burmese, optionally carrying thousands separators and a
# decimal point. The lookbehind keeps a run from starting inside a word, so
# `မောင်းတော်၃` is not read as the number ၃ belonging to nothing.
_NUM_RE = re.compile(r"(?<![\u1000-\u109f0-9\u1040-\u1049])"
                     r"([0-9\u1040-\u1049][0-9\u1040-\u1049,.]*)")
_MAX_NUMBERS = 40
_MAX_KEYWORDS = 15

# A short place name must **stand alone**. Measured 2026-10-03: `ပြည်` (the
# city) matched inside `ပြည်ထောင်စုဝန်ကြီး`, so a ministry became a location —
# a false place, which is worse than a missing one. A name of 5 characters or
# less therefore has to be a whole token, or a token followed by one of these
# grammar particles. Longer names (`ရန်ကုန်တိုင်းဒေသကြီး`) cannot collide like
# this and are matched by substring as before.
_PLACE_PARTICLES: tuple[str, ...] = (
    "မှာ", "တွင်", "၌", "မှ", "သည်", "တို့", "နှင့်", "ရဲ့", "ကို", "က",
)
_STANDALONE_MAX = 5
_SPLIT_TOKEN = re.compile(r"[\s၊။.,;:()\"'“”/\\-]+")


def locations_in(text: str) -> list[str]:
    """The known places named in `text`, longest spelling first, no duplicates."""
    if not text:
        return []
    flat = _norm(text)
    tokens = [_norm(t) for t in _SPLIT_TOKEN.split(text) if t]
    out: list[str] = []
    seen: list[str] = []
    for name in sorted(LOCATIONS, key=len, reverse=True):
        k = _norm(name)
        if k not in flat:
            continue
        if any(k == s or k in s for s in seen):
            continue
        if len(k) <= _STANDALONE_MAX and not any(
                t == k or (t.startswith(k) and t[len(k):] in _PLACE_PARTICLES)
                for t in tokens):
            continue
        out.append(name)
        seen.append(k)
    return out


def numbers_in(text: str) -> list[dict]:
    """Every digit run in `text`, with the phrase it sat in.

    The context is kept because a number without its phrase is not an answer —
    `၃,၅၀၀,၀၀၀` is the gold price, the rice price or a budget depending on the
    words around it, and the model cannot recover them from the digits alone.
    `value` is normalised to Burmese digits so the spoken answer matches the
    paper, whichever digits the page used.
    """
    if not text:
        return []
    out: list[dict] = []
    seen: set[tuple] = set()
    for m in _NUM_RE.finditer(text):
        value = to_burmese_digits(m.group(1).rstrip(".,"))
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        context = re.sub(r"\s+", " ", text[start:end]).strip()
        key = (value, context)
        if not value or key in seen:
            continue
        seen.add(key)
        out.append({"value": value, "context": context})
        if len(out) >= _MAX_NUMBERS:
            break
    return out


def keywords_in(text: str) -> list[str]:
    """The article's most frequent words, most-frequent first.

    Tokens are whole Burmese runs (>= 2 codepoints) and Latin words (>= 3
    letters); particles are dropped by `_STOPWORDS`. This is a ranking aid for
    search, and it is explicitly *not* a summary of the article — the tool that
    answers says so.
    """
    if not text:
        return []
    tally: dict[str, int] = {}
    for tok in re.findall(r"[\u1000-\u109f]{2,}", text):
        if tok in _STOPWORDS:
            continue
        tally[tok] = tally.get(tok, 0) + 1
    for tok in re.findall(r"[A-Za-z]{3,}", text):
        low = tok.lower()
        if low not in _STOPWORDS:
            tally[tok] = tally.get(tok, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, n in ranked[: _MAX_KEYWORDS] if n > 1 or len(w) > 3]


def _display(person: dict) -> str:
    """How a `people` entry is printed: its rank, then the honorific + name.

    Built as `honorific + name` (no space between them) because that is how the
    paper prints them and therefore what a name search must match — `ဦး` +
    `အောင်ကြိမ်` is `ဦးအောင်ကြိမ်`, not `ဦး အောင်ကြိမ်`.
    """
    title = str(person.get("title") or "").strip()
    rest = f"{person.get('honorific','')}{person.get('name','')}".strip()
    return f"{title} {rest}".strip() if title else rest


def organizations_in(text: str) -> list[str]:
    """The organisations `text` names — ministries and the few standing bodies.

    **Two matchers, because the papers abbreviate.** `entities.ministries_in`
    matches the glossary's full name, so it misses the shortened form the papers
    print far more often (`ကုန်သွယ်ရေးဝန်ကြီးဌာန` for `ကုန်သွယ်ရေးနှင့် ကူးသန်းရောင်း
    ဝယ်ရေးဝန်ကြီးဌာန`) — measured 2026-10-03, a sentence naming the abbreviated
    ministry returned **0 organisations**. `MINISTRY_SHORT` covers those printed
    forms; both lists are fixed, so a malformed run of text cannot produce an
    organisation that does not exist.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        key = _norm(name)
        if key and key not in seen:
            seen.add(key)
            out.append(name)

    for name in ent.ministries_in(text):
        add(name)
    flat = _norm(text)
    for name in MINISTRY_SHORT:
        if _norm(name) in flat:
            add(name)
    for name in BODIES:
        if _norm(name) in flat:
            add(name)
    return out


def extract(title: str = "", summary: str = "", content: str = "") -> dict:
    """Everything the article states, pulled into the owner's five columns.

    **Entities are read from the body, not the headline** — the project's
    measured rule (`entities.people_in`): a headline names the subject, but it is
    the body that says who else was there. When there is no body (a legal and
    common case) the headline and summary stand in, because an article with no
    body would otherwise index as having no people at all, which is a claim about
    the article rather than about our read of it.
    """
    body = (content or "").strip()
    fallback = f"{title or ''} {summary or ''}".strip()
    entity_text = body or fallback

    people: list[dict] = []
    seen_people: set[tuple] = set()
    # `find_titled_people` reads `title + name` — the way a Burmese paper names a
    # person — so a name here carries the office it was printed under.
    for hit in ent.find_titled_people(entity_text):
        key = (hit.get("honorific", ""), hit.get("name", ""))
        if not key[1] or key in seen_people:
            continue
        seen_people.add(key)
        people.append({"title": hit.get("title", ""), "honorific": key[0],
                       "name": key[1]})

    organizations = organizations_in(entity_text)

    return {
        "people": people,
        "organizations": organizations,
        "locations": locations_in(entity_text),
        "numbers": numbers_in(entity_text),
        "keywords": keywords_in(entity_text),
    }


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _unjson(value, fallback):
    """A JSON column read back, or `fallback` when it is empty or corrupt.

    A corrupt cell must not raise on the voice path — the same rule the newsroom
    bridge follows: the answer gets thinner, never an apology.
    """
    try:
        return json.loads(value) if value else fallback
    except (ValueError, TypeError):
        return fallback


def _key(card: dict) -> str:
    """The row's identity: the site's article id, or the url when it has none.

    The site's own search returns items whose id is not always parseable, and a
    row keyed on `""` would collide with the next one — so the url is the
    fallback and the primary key is never empty.
    """
    return str(card.get("id") or card.get("url") or "").strip()


def _search_text(row: dict) -> str:
    """The haystack one query runs against — every field the owner can ask about.

    Built from the **same** normalisation the query uses (`_norm`), so a
    whitespace variant never decides whether a hit is found.
    """
    people = " ".join(f"{p.get('honorific','')}{p.get('name','')}"
                      for p in row.get("people", []))
    numbers = " ".join(n.get("value", "") for n in row.get("numbers", []))
    return _norm(" ".join([
        row.get("title", ""), row.get("summary", ""), row.get("content", ""),
        " ".join(row.get("keywords", [])), people,
        " ".join(row.get("organizations", [])),
        " ".join(row.get("locations", [])), numbers,
    ]))


def make_row(card: dict, content: str = "", date: str = "", author: str = "") -> dict:
    """A card (and, when fetched, its body) turned into the owner's row.

    `date`/`author` are passed in rather than fetched here, because the crawler
    already has the article page open (`moi_client.article_page` returns all
    three at once) and fetching again for the metadata would double the requests
    to a government site.
    """
    title = (card.get("headline") or card.get("title") or "").strip()
    summary = (card.get("summary") or "").strip()
    row = {
        "id": _key(card),
        "url": (card.get("url") or "").strip(),
        "title": title,
        "section": (card.get("section") or "").strip(),
        "section_label": (card.get("section_label") or "").strip(),
        "category": (card.get("category") or "").strip(),
        "published_date": (date or card.get("issue_date") or "").strip(),
        "author": (author or "").strip(),
        "content": (content or "").strip(),
        "summary": summary,
        "created_at": now_mmt().isoformat(timespec="seconds"),
        "updated_at": now_mmt().isoformat(timespec="seconds"),
    }
    row.update(extract(title, summary, content))
    row["search_text"] = _search_text(row)
    return row


def upsert(rows: list[dict]) -> int:
    """Store `rows`, keyed on `id`. An existing row keeps its `created_at`.

    `created_at` is **when we first saw the article** and is not rewritten on a
    later pass — the crawl re-visits a card whenever the site updates it, and
    "first seen" is the fact that tells the owner how fresh the index is. The
    update time is kept separately in `updated_at`.
    """
    if not rows:
        return 0
    written = 0
    with _LOCK:
        con = _connect()
        try:
            hold = ", ".join(f'"{c}"' for c in COLUMNS)
            marks = ", ".join("?" for _ in COLUMNS)
            updates = ", ".join(f'"{c}"=excluded."{c}"'
                                for c in COLUMNS if c not in ("id", "created_at"))
            sql = (f'INSERT INTO "{TABLE}" ({hold}) VALUES ({marks}) '
                   f'ON CONFLICT("id") DO UPDATE SET {updates}')
            for row in rows:
                key = _key(row)
                if not key:
                    continue
                old = con.execute(f'SELECT "created_at" FROM "{TABLE}" WHERE "id"=?',
                                  (key,)).fetchone()
                row = dict(row)
                row["id"] = key
                if old and old["created_at"]:
                    row["created_at"] = old["created_at"]
                row["updated_at"] = now_mmt().isoformat(timespec="seconds")
                # The list columns are JSON **text** in SQLite. Binding a Python
                # list raises `ProgrammingError: type 'list' is not supported`,
                # which is the whole insert — so it is serialised here rather than
                # left to the caller, and a caller cannot half-write a row.
                con.execute(sql, [
                    _json(row.get(c, "")) if c in _LIST_COLUMNS else row.get(c, "")
                    for c in COLUMNS])
                written += 1
            con.commit()
        finally:
            con.close()
    return written


def _public(row) -> dict:
    """A database row as a plain dict, JSON columns parsed back out."""
    out = {c: (row[c] if row[c] is not None else "") for c in COLUMNS}
    for c in _LIST_COLUMNS:
        out[c] = _unjson(out[c], [])
    return out


def get(url_or_id: str) -> dict | None:
    """One article by its id or its url. `None` when it is not indexed.

    `None` is deliberately distinct from `{}`: the caller must be able to say
    "not indexed" and go live, rather than showing an empty article.
    """
    key = str(url_or_id or "").strip()
    if not key:
        return None
    con = _connect()
    try:
        row = con.execute(f'SELECT * FROM "{TABLE}" WHERE "id"=? OR "url"=? '
                          f'LIMIT 1', (key, key)).fetchone()
    finally:
        con.close()
    return _public(row) if row else None


def count(section: str = "") -> int:
    """How many articles the index holds, optionally for one section."""
    slug = _section_filter(section)
    con = _connect()
    try:
        if slug:
            row = con.execute(f'SELECT COUNT(*) AS n FROM "{TABLE}" WHERE "section"=?',
                              (slug,)).fetchone()
        else:
            row = con.execute(f'SELECT COUNT(*) AS n FROM "{TABLE}"').fetchone()
    finally:
        con.close()
    return int(row["n"]) if row else 0


def tally() -> list[dict]:
    """Articles per section, its Burmese label, biggest first."""
    con = _connect()
    try:
        rows = con.execute(
            f'SELECT "section","section_label",COUNT(*) AS n FROM "{TABLE}" '
            f'GROUP BY "section" ORDER BY n DESC').fetchall()
    finally:
        con.close()
    return [{"section": r["section"] or "(no section)",
             "label": r["section_label"] or "",
             "count": int(r["n"])} for r in rows]


def date_range() -> tuple[str, str]:
    """`(oldest, newest)` published dates in the index, either possibly ""."""
    con = _connect()
    try:
        row = con.execute(f'SELECT MIN("published_date") AS a, MAX("published_date") AS b '
                          f'FROM "{TABLE}" WHERE "published_date" <> ""').fetchone()
    finally:
        con.close()
    return ((row["a"] or ""), (row["b"] or "")) if row else ("", "")


def known_ids() -> set[str]:
    """Every id the index already holds — the crawler's "new only" test."""
    con = _connect()
    try:
        rows = con.execute(f'SELECT "id" FROM "{TABLE}"').fetchall()
    finally:
        con.close()
    return {r["id"] for r in rows if r["id"]}


def _section_filter(section: str) -> str:
    """What the owner called a section → the stored slug, or the raw value.

    `moi_client.resolve_section` reads the Burmese label; a slug is accepted too
    (it is what the tool passes when it was told one directly).
    """
    s = (section or "").strip()
    if not s:
        return ""
    return mc.resolve_section(s) or s


def _like(needle: str) -> str:
    """A LIKE pattern for `needle`, with LIKE's own wildcards escaped.

    Unescaped, a query containing `%` would match everything — a silent
    over-answer, which is worse than a miss.
    """
    esc = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def _tokens(term: str) -> list[str]:
    """The query's own words, each normalised, longest first, de-duplicated."""
    toks = {_norm(t) for t in re.split(r"\s+", term or "") if len(_norm(t)) >= 2}
    return sorted(toks, key=len, reverse=True)


# `"search_text" LIKE ? ESCAPE '\'` — a quoted column and a single-quoted escape
# character. Written once so the two places that build it cannot drift apart.
_LIKE_CLAUSE = '"search_text" LIKE ? ESCAPE \'\\\''
_UNDATED_CLAUSE = "\"published_date\" = ''"


def search(term: str = "", section: str = "", date: str = "", days: int = 0,
           limit: int = 12) -> dict:
    """Search the index. **Returns a report, not a list.**

    The report is deliberate, because an honest "not found" has to say what was
    actually searched:

    * `matched` names the phrase that hit when the **full query found nothing** —
      the project's measured rule (2026-10-03): a whole-question query
      `'နိုင်ငံတော်သမ္မတ အိန္ဒိယ ခရီးစဉ်'` matches nothing while its words
      `'အိန္ဒိယ ခရီးစဉ်'` rank the trip first. The fallback tries the query's own
      words (all of them, so a two-word event stays an AND) and reports which it
      used.
    * `undated_skipped` counts rows a `date`/`days` filter dropped because they
      **carry no date** — the site's own search returns items with none, and a
      silent drop is how "there is no such news" gets said about an article we
      simply could not date.
    """
    needle = _norm(term)
    slug = _section_filter(section)
    floor = ""
    if not date and int(days or 0) > 0:
        floor = (now_mmt().date() - timedelta(days=max(0, int(days) - 1))).isoformat()

    where, args = [], []
    if slug:
        where.append('"section"=?')
        args.append(slug)
    if date:
        where.append('"published_date"=?')
        args.append(str(date).strip())
    elif floor:
        where.append('"published_date" >= ?')
        args.append(floor)

    con = _connect()
    try:
        def run(term_args: list[str]) -> list:
            sql = f'SELECT * FROM "{TABLE}"'
            w, a = list(where), list(args)
            for t in term_args:
                w.append(_LIKE_CLAUSE)
                a.append(_like(t))
            if w:
                sql += " WHERE " + " AND ".join(w)
            sql += ' ORDER BY "published_date" DESC, "id" DESC LIMIT ?'
            a.append(max(1, int(limit)))
            return con.execute(sql, a).fetchall()

        rows = run([needle] if needle else [])
        matched = ""
        if needle and not rows:
            toks = _tokens(term)
            if toks:
                rows = run(toks)
                matched = " ".join(toks) if rows else ""

        undated = 0
        if needle and (date or floor):
            # Same query, but on the rows the date filter had to leave out.
            w = [x for x in where if '"published_date"' not in x]
            a = [args[i] for i, x in enumerate(where) if '"published_date"' not in x]
            w += [_UNDATED_CLAUSE, _LIKE_CLAUSE]
            a.append(_like(needle))
            undated = con.execute(
                f'SELECT COUNT(*) AS n FROM "{TABLE}" WHERE ' + " AND ".join(w),
                a).fetchone()["n"]
    finally:
        con.close()

    return {
        "term": term or "",
        "matched": matched,
        "hits": [_public(r) for r in rows],
        "total": len(rows),
        "section": slug,
        "date": date or "",
        "days": int(days or 0),
        "undated_skipped": int(undated or 0),
    }


def by_entity(kind: str, name: str, section: str = "", days: int = 0,
              limit: int = 12) -> dict:
    """Articles that **name** a person, organisation or place.

    `kind` is one of `people` / `organizations` / `locations`, and the match runs
    against **only that column**, so asking for a person cannot be answered by an
    article that merely repeats the same word in its body. This is the tool behind
    the owner's *"ဦးမင်းအောင်လှိုင်ကို mention လုပ်ထားတဲ့ သတင်းတွေ ရှာပေး"* — a
    distinct-entity question a keyword sweep cannot answer.

    **The label match is done in Python, not in SQL**, and that is not an
    optimisation: `people` is stored as `[{"title":…, "honorific":"ဦး",
    "name":"အောင်ကြိမ်"}]`, so the printed form `ဦးအောင်ကြိမ်` is **never a contiguous
    substring of the cell** and `LIKE '%ဦးအောင်ကြိမ်%'` matches nothing — measured
    2026-10-03, a name search returned 0 rows for an article that named him.
    """
    col = str(kind or "").strip().lower()
    if col not in ("people", "organizations", "locations"):
        return {"kind": kind, "name": name, "matched": [], "hits": [],
                "total": 0, "undated_skipped": 0, "error": "bad kind"}
    needle = _norm(name)
    if not needle:
        return {"kind": col, "name": name, "matched": [], "hits": [], "total": 0,
                "undated_skipped": 0, "error": "no name"}

    slug = _section_filter(section)
    floor = ""
    if int(days or 0) > 0:
        floor = (now_mmt().date() - timedelta(days=max(0, int(days) - 1))).isoformat()

    where, args = [], []
    if slug:
        where.append('"section"=?')
        args.append(slug)
    if floor:
        where.append('"published_date" >= ?')
        args.append(floor)
    con = _connect()
    try:
        rows = con.execute(
            f'SELECT * FROM "{TABLE}"' +
            (" WHERE " + " AND ".join(where) if where else ""),
            args).fetchall()
    finally:
        con.close()

    hits: list[dict] = []
    names: list[str] = []
    seen: set[str] = set()
    for r in rows:
        items = _unjson(r[col], [])
        labels = [(_display(i) if isinstance(i, dict) else str(i)) for i in items]
        if not any(needle in _norm(label) for label in labels):
            continue
        hits.append(_public(r))
        for label in labels:
            if needle in _norm(label) and label not in seen:
                seen.add(label)
                names.append(label)
    hits.sort(key=lambda r: r.get("published_date") or "", reverse=True)
    return {"kind": col, "name": name, "matched": names,
            "hits": hits[:max(1, int(limit))], "total": len(hits),
            "undated_skipped": 0}


# ── Crawl ─────────────────────────────────────────────────────────────────────


def new_cards(cards: list[dict], known: set[str], stop_after_known: int = 0) -> list[dict]:
    """The cards the index does not already hold, order preserved.

    The pure half of "new articles only": `crawl()` fetches a body for exactly
    these and nothing else. Kept separate so `check_moi_index.py` can test the
    decision without touching a network.

    `stop_after_known` ends the scan after that many **consecutive** known cards.
    `list_section` returns cards newest-first, so a quiet day's first cards are
    all known and the walk stops at the top instead of reading 40 it has. `0`
    scans everything, which is what a test wants and a rebuild wants.
    """
    out: list[dict] = []
    seen: set[str] = set()
    streak = 0
    for card in cards or []:
        key = _key(card)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in known:
            streak += 1
            if stop_after_known and streak >= stop_after_known:
                break
            continue
        streak = 0
        out.append(card)
    return out


def crawl(sections: tuple[str, ...] = (), pages: int = CRAWL_PAGES,
          max_fetch: int = MAX_FETCH_PER_RUN, fetch_bodies: bool = True,
          stop_after_known: int = 0) -> dict:
    """Walk the sections, store what is new, and return a report. **Never raises.**

    THE ONE RULE THAT MATTERS HERE

        A crawl that could not reach the site **does not report "nothing new"**.
        Those are different facts — one is about the site, one is about a socket —
        and merging them is how the assistant comes to say "there is no MOI news
        today" on a morning its own VPN was down. An unreachable crawl returns
        `reachable: False` with the reason, changes nothing in the table, and
        records the attempt. The next run picks up from where this one stopped,
        because nothing was written.

    FAILURE IS PER-ARTICLE

        One article that 404s or times out is recorded in `errors` and the crawl
        carries on. A single dead link in a section must not cost the day's news.

    `stop_after_known` defaults to **0 — scan every card the pages yielded.**
        A streak shortcut here is a silent-coverage killer: cards come
        newest-first, so any backlog older than a few known cards is dropped
        without a trace (measured 2026-10-05 — with the streak at 3, the
        2026-09-30 Vietnam-trip card on `/other-news?page=5` was never scanned
        even though the 6-page walk had already fetched it). The shortcut saves
        only a loop over already-fetched dicts, not a network request, and the
        real cost stays bounded by `max_fetch` and the body fetches. Pass a
        positive value only when you know the walk must be shallow.
    """
    started = now_mmt().isoformat(timespec="seconds")
    report = {
        "started": started, "finished": "", "reachable": False, "reason": "",
        "sections": {}, "new": 0, "stored": 0, "errors": [], "total": count(),
    }
    ok, reason = mc.available()
    report["reachable"] = bool(ok)
    report["reason"] = reason or ""
    if not ok:
        report["finished"] = started
        set_meta("last_attempt", started)
        set_meta("last_attempt_result", f"unreachable: {reason}")
        return report

    wanted = list(sections) or [s for s, _l, _c in mc.SECTIONS if s != mc._SUPERSET]
    known = known_ids()
    first_pass = not known                      # no frontier yet: initial fill
    body_fetches = 0
    rows: list[dict] = []
    for slug in wanted:
        entry = {"label": mc.SECTION_LABEL.get(slug, slug), "cards": 0,
                 "new": 0, "errors": 0}
        try:
            cards = mc.list_section(slug, pages=pages)
        except Exception as e:                              # noqa: BLE001
            entry["errors"] += 1
            report["errors"].append(f"{slug}: {type(e).__name__}: {e}")
            report["sections"][slug] = entry
            continue
        entry["cards"] = len(cards)
        for card in new_cards(cards, known, stop_after_known=stop_after_known):
            if len(rows) >= max_fetch:
                break
            content, date, author = "", card.get("issue_date", ""), ""
            if fetch_bodies and card.get("url"):
                # On the first crawl there is no known frontier, so cap the
                # body fetches: past the cap, store metadata only (no network).
                skip_body = first_pass and body_fetches >= _FIRST_CRAWL_BODY_CAP
                if not skip_body:
                    page = None
                    try:
                        page = mc.article_page(card["url"])
                        content = page.get("text", "")
                        date = date or page.get("date", "")
                        author = page.get("author", "")
                    except Exception as e:                  # noqa: BLE001
                        entry["errors"] += 1
                        report["errors"].append(
                            f"{card.get('url')}: {type(e).__name__}: {e}")
                    if page is not None:
                        body_fetches += 1
                    # The pause is politeness between network requests — never
                    # pay it for a card whose body we are not fetching.
                    time.sleep(_PAUSE)
            rows.append(make_row(card, content, date, author))
            known.add(_key(card))
            entry["new"] += 1
        report["sections"][slug] = entry

    report["new"] = len(rows)
    report["stored"] = upsert(rows)
    report["total"] = count()
    report["finished"] = now_mmt().isoformat(timespec="seconds")
    set_meta("last_run", report["finished"])
    set_meta("last_new", str(report["new"]))
    set_meta("last_total", str(report["total"]))
    set_meta("last_attempt", report["finished"])
    set_meta("last_attempt_result", f"ok: {report['new']} new")
    return report


def status() -> dict:
    """What the index holds and how fresh it is. **Never raises.**

    Every field is a fact the caller can speak: `oldest`/`newest` bound the
    coverage, `last_run` is when the crawler last completed, and
    `last_attempt_result` says whether the most recent attempt *reached* the
    site — so "the index has nothing after 1 Oct" can be read as "the site was
    unreachable since" rather than as "the site published nothing".
    """
    oldest, newest = date_range()
    return {
        "db": str(_db_path()),
        "total": count(),
        "sections": tally(),
        "oldest": oldest,
        "newest": newest,
        "last_run": last_run(),
        "last_new": meta("last_new", ""),
        "last_attempt": meta("last_attempt", ""),
        "last_attempt_result": meta("last_attempt_result", ""),
    }