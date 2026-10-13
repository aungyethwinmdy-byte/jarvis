"""Does the MOI research engine behave? — offline, no network.

    py check_moi_index.py

WHAT THIS COVERS — every defect found while building the hybrid
"index first, live fallback" system on 2026-10-03, plus the ones that would
have shipped silently:

    the owner's table     `id, title, url, section, published_date, author,
                           content, summary, people, organizations, locations,
                           numbers, keywords, created_at` is asserted as an
                           exact set — a column that quietly disappears is a
                           fact that quietly stops being stored
    list columns          binding a Python list to a TEXT column raises
                           `ProgrammingError: type 'list' is not supported` and
                           fails the whole insert
    the name search       `people` is stored as separate `honorific` and `name`
                           fields, so the printed `ဦးအောင်ကြိမ်` is never a
                           contiguous substring of the cell and `LIKE` matched
                           nothing — a name search returned 0 for an article
                           that named him
    a false place         `ပြည်` (the city) matched inside `ပြည်ထောင်စုဝန်ကြီး`,
                           so a ministry became a location
    the abbreviations     the papers print `ကုန်သွယ်ရေးဝန်ကြီးဌာန`, the
                           glossary holds the long form — 0 organisations
    LIKE wildcards        an unescaped `%` in a query matches everything
    new-only              `new_cards` is the whole of "new articles only", and
                           `stop_after_known` is what keeps a quiet day cheap
    unreachable ≠ empty   a crawl that cannot reach the site must not report
                           "0 new" or clear anything
    the handler contract  called through `ActionRegistry.run`, the way the app
                           calls it — never as `fn(query=…)`
    the scheduled command `_schtasks_args` is pure so 11:30, the task name and
                           `--scheduled` can be asserted without creating a real
                           task on the machine running this

WHY IT IS A SCRIPT AND NOT A NOTE

    Each of these was found by running the thing or by reading SQLite's own
    error. A defect that is fixed but not checked is a defect that comes back,
    and two of them (the name search, the false place) were invisible until a
    real query returned the wrong number of rows.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, r"E:\Mark-LIV-main")

FAILURES: list[str] = []

# ── the sample article: chosen so every column has something to hold ─────────
TITLE = "နိုင်ငံတော်သမ္မတ မိန့်ခွန်းပြောကြား"
SUMMARY = "အခမ်းအနားတွင် နိုင်ငံတော်သမ္မတက မိန့်ခွန်းပြောကြားသည်။"
BODY = (
    "ရန်ကုန်တိုင်းဒေသကြီး မှာ ယနေ့ကျင်းပတဲ့ အခမ်းအနားမှာ "
    "နိုင်ငံတော်သမ္မတက မိန့်ခွန်းပြောကြားပါတယ်။\n"
    "ပြည်ထောင်စုဝန်ကြီး ဦးအောင်ကြိမ်နှင့် ဒုတိယဝန်ကြီး ဒေါ်စန္ဒာဝင်းတို့ "
    "တက်ရောက်ကြသည်။\n"
    "မန္တလေးတိုင်းဒေသကြီး တွင် ဆန်တစ်အိတ်ကို ၃,၅၀၀ ကျပ်နဲ့ ရောင်းချနေပါတယ်။\n"
    "ကျောင်းသား ၂၅၀၀ ဦး ပညာသင်ဆု ရရှိကြပါတယ်။\n"
    "ကုန်သွယ်ရေးဝန်ကြီးဌာန၏ အစီရင်ခံစာအရ ၂၀၂၆ ခုနှစ်တွင် "
    "စီးပွားရေး ၇.၅ ရာခိုင်နှုန်း တိုးတက်သည်။"
)

CARDS = {
    "president-news": [
        {"id": "101", "url": "/news/101", "headline": TITLE, "summary": SUMMARY,
         "section": "president-news", "section_label": "နိုင်ငံတော်သမ္မတ",
         "issue_date": "2026-10-02"},
        {"id": "103", "url": "/news/103", "headline": "သတင်း မဖတ်နိုင်သူ",
         "summary": "", "section": "president-news",
         "section_label": "နိုင်ငံတော်သမ္မတ", "issue_date": "2026-10-01"},
    ],
    "other-news": [
        {"id": "102", "url": "/news/102", "headline": "ဘဏ္ဍာရေးသတင်း",
         "summary": "ဘဏ္ဍာရေး", "section": "other-news",
         "section_label": "ပြည်တွင်းသတင်း", "issue_date": ""},
    ],
}

PAGES = {
    "/news/101": {"state": "ok", "text": BODY, "matched": True,
                  "date": "2026-10-02", "author": ""},
    "/news/102": {"state": "empty", "text": "", "matched": True,
                  "date": "", "author": ""},
}


def _head(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, wanted {want!r}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}"
          + ("" if ok else f"   got {got!r}, wanted {want!r}"))


def main() -> int:
    # A temp file, via the module's own env override — so nothing is written to
    # the real index and nothing is left behind.
    tmp = Path(tempfile.mkdtemp(prefix="moi_index_"))
    os.environ["MOI_INDEX_DB"] = str(tmp / "moi_articles.db")

    from core import action_loader as al
    from core import moi_client as mc
    from core import moi_index as mi
    from actions import moi_research as R

    _orig_available, _orig_list, _orig_page = (mc.available, mc.list_section,
                                               mc.article_page)
    _orig_site = mc.search_site
    orig_pause = mi._PAUSE
    mi._PAUSE = 0

    try:
        _schema_and_table(mi)
        _extraction(mi)
        _round_trip(mi)
        _search(mi)
        _entity_search(mi)
        _new_only(mi)
        _crawl(mi, mc, R)
        _the_tool(mi, mc, R, al)
    finally:
        mc.available, mc.list_section = _orig_available, _orig_list
        mc.article_page, mc.search_site = _orig_page, _orig_site
        mi._PAUSE = orig_pause
        os.environ.pop("MOI_INDEX_DB", None)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print("   -", f)
        return 1
    print("all checks passed.")
    return 0


# ── 1. the table is the owner's own ──────────────────────────────────────────


def _schema_and_table(mi) -> None:
    _head("the table is the owner's own column list")
    check("the thirteen columns he named, in order",
          list(mi.SPEC_COLUMNS)[:-1],
          ["id", "title", "url", "section", "published_date", "author", "content",
           "summary", "people", "organizations", "locations", "numbers",
           "keywords"])
    check("…plus `created_at`",
          mi.SPEC_COLUMNS[-1], "created_at")
    check("every named column is in the table's column set",
          set(mi.SPEC_COLUMNS) <= set(mi.COLUMNS), True)
    check("the index's working columns are declared, not implicit",
          set(mi.EXTRA_COLUMNS) <= set(mi.COLUMNS), True)
    check("the list columns are exactly the multi-valued ones",
          sorted(mi._LIST_COLUMNS),
          ["keywords", "locations", "numbers", "organizations", "people"])

    _head("the table exists with those columns")
    mi.init()
    con = mi._connect()
    try:
        cols = [r["name"] for r in con.execute(
            f'PRAGMA table_info("{mi.TABLE}")').fetchall()]
        pk = [r["name"] for r in con.execute(
            f'PRAGMA table_info("{mi.TABLE}")').fetchall() if r["pk"]]
        names = [r[0] for r in con.execute(
            f'SELECT name FROM sqlite_master WHERE type="table"').fetchall()]
    finally:
        con.close()
    check("every declared column exists", sorted(cols), sorted(mi.COLUMNS))
    check("`id` is the primary key", pk, ["id"])
    check("the meta table exists too", "moi_index_meta" in names, True)
    con = mi._connect()
    try:
        idx = [r["name"] for r in con.execute(
            f'PRAGMA index_list("{mi.TABLE}")').fetchall()]
    finally:
        con.close()
    check("…an index on published_date exists", "ix_moi_date" in idx, True)
    check("…and one on section", "ix_moi_section" in idx, True)


# ── 2. extraction ────────────────────────────────────────────────────────────


def _extraction(mi) -> None:
    _head("extraction pulls what the article actually states")
    ex = mi.extract(TITLE, SUMMARY, BODY)
    who = [f"{p.get('honorific','')}{p.get('name','')}" for p in ex["people"]]
    check("a titled person is found with his honorific",
          "ဦးအောင်ကြိမ်" in who, True)
    check("…and the deputy minister is kept separate",
          any("စန္ဒာဝင်း" in n for n in who), True)
    check("the abbreviated ministry IS recognised",
          "ကုန်သွယ်ရေးဝန်ကြီးဌာန" in ex["organizations"], True)
    check("the regions are named",
          "ရန်ကုန်တိုင်းဒေသကြီး" in ex["locations"]
          and "မန္တလေးတိုင်းဒေသကြီး" in ex["locations"], True)
    check("`ပြည်` does NOT become a place inside `ပြည်ထောင်စုဝန်ကြီး`",
          "ပြည်" in ex["locations"], False)
    values = [n["value"] for n in ex["numbers"]]
    check("the printed figures are kept, as Burmese digits",
          "၃,၅၀၀" in values and "၇.၅" in values, True)
    check("…each with the phrase it sat in",
          all(n.get("context") for n in ex["numbers"]), True)
    check("the rice price's context names rice",
          any("ဆန်" in n["context"] for n in ex["numbers"]), True)
    check("keywords are ranked and the particles are dropped",
          "သည်" not in ex["keywords"] and len(ex["keywords"]) > 0, True)

    _head("an article with no body does not read as having nobody")
    from_body = mi.extract(TITLE, SUMMARY, "")
    check("the headline+summary stand in for a missing body",
          from_body["keywords"] != [], True)
    check("…and a place in the headline is still found without a body",
          mi.extract("ရန်ကုန်တိုင်းဒေသကြီး တွင် သတင်း", "", "")["locations"],
          ["ရန်ကုန်တိုင်းဒေသကြီး"])
    nothing = mi.extract("", "", "")
    check("empty in → empty out (nothing is invented)",
          nothing, {"people": [], "organizations": [], "locations": [],
                    "numbers": [], "keywords": []})

    _head("a short place name must stand alone")
    check("`ပြည်တွင်းသတင်း` is not the city `ပြည်`",
          "ပြည်" in mi.locations_in("ပြည်တွင်းသတင်း သတင်း"), False)
    check("…but `ပြည်` on its own is",
          "ပြည်" in mi.locations_in("သတင်းစာကို ပြည်မှာ ထုတ်သည်"), True)
    check("…and `ပြည်မှာ` (with a particle) is too",
          "ပြည်" in mi.locations_in("ပြည်မှာ ကျင်းပသည်"), True)
    check("`မကွေးတိုင်းဒေသကြီး` matches the long form only",
          mi.locations_in("မကွေးတိုင်းဒေသကြီးတွင်"), ["မကွေးတိုင်းဒေသကြီး"])


# ── 3. storing and reading back ──────────────────────────────────────────────


def _round_trip(mi) -> None:
    _head("a card becomes the owner's row, and comes back intact")
    card = dict(CARDS["president-news"][0], id="90001", url="/news/90001")
    row = mi.make_row(card, content=BODY, date="2026-10-02")
    check("make_row fills every declared column", set(row) >= set(mi.COLUMNS), True)
    check("…and adds nothing outside them", set(row) - set(mi.COLUMNS), set())
    check("`created_at` is stamped", bool(row["created_at"]), True)
    check("`published_date` takes the caller's date over the card's",
          row["published_date"], "2026-10-02")
    check("search_text is one flat haystack — no spaces to disagree with",
          " " in row["search_text"], False)

    check("upsert stores it", mi.upsert([row]), 1)
    check("…one row", mi.count(), 1)
    check("get by id", mi.get("90001")["title"], TITLE)
    check("get by url", mi.get("/news/90001")["title"], TITLE)
    check("an unknown key is None, not {} — so the caller can go live",
          mi.get("/news/nope"), None)

    first_seen = mi.get("90001")["created_at"]
    row["content"] = BODY + " စာသားအသစ်"
    check("re-upserting replaces the row", mi.upsert([row]), 1)
    check("…and does not duplicate it", mi.count(), 1)
    check("…and keeps the original `created_at` (first seen)",
          mi.get("90001")["created_at"], first_seen)
    check("…while the body really is replaced",
          "စာသားအသစ်" in mi.get("90001")["content"], True)
    got = mi.get("90001")
    check("list columns read back as lists, not JSON text",
          all(isinstance(got[c], list) for c in mi._LIST_COLUMNS), True)
    check("…and a number keeps both its value and its phrase",
          sorted(got["numbers"][0]), ["context", "value"])

    # A second row with NO date: the site's own search returns items with none,
    # and a `days` filter that silently drops them is how "there is no such
    # news" gets said about an article we simply could not date.
    undated = mi.make_row({"id": "90002", "url": "/news/90002",
                           "headline": "ဆန် ဈေးနှုန်း", "summary": "",
                           "section": "other-news",
                           "section_label": "ပြည်တွင်းသတင်း",
                           "issue_date": ""})
    check("a card with no date stores an empty date", undated["published_date"], "")
    mi.upsert([undated])
    check("two rows now", mi.count(), 2)

    _head("status reports what it has — and never raises on an empty index")
    labels = {t["section"]: t["label"] for t in mi.tally()}
    counts = {t["section"]: t["count"] for t in mi.tally()}
    check("tally carries the publisher's own label",
          labels.get("president-news"), "နိုင်ငံတော်သမ္မတ")
    check("…and a count per section", counts.get("president-news"), 1)
    check("date_range bounds the coverage", mi.date_range(), ("2026-10-02", "2026-10-02"))
    check("known_ids is the crawler's memory of what it already has",
          {"90001", "90002"} <= mi.known_ids(), True)
    st = mi.status()
    check("status names the database", st["db"].endswith(".db"), True)
    check("status says the crawler has never run, as ''",
          st["last_run"], "")


# ── 4. search ────────────────────────────────────────────────────────────────


def _search(mi) -> None:
    _head("search answers from the index and says what it searched")
    rep = mi.search("ဆန်")
    check("a word finds every article that carries it (both rows do)",
          rep["total"], 2)
    check("the report carries the term that was used", rep["term"], "ဆန်")
    check("…and which term matched when the phrase did not need a retry",
          rep["matched"], "")

    whole = mi.search("နိုင်ငံတော်သမ္မတ ဆန် ရောင်း")
    check("a whole-question query still finds it", whole["total"], 1)
    check("…and NAMES the shorter term that worked (not silent) — longest first",
          whole["matched"], "နိုင်ငံတော်သမ္မတ ရောင်း ဆန်")

    check("a Burmese section name resolves to its slug",
          mi.search("ဆန်", section="နိုင်ငံတော်သမ္မတ")["total"], 1)
    check("…and the other section holds the other one",
          mi.search("ဆန်", section="ပြည်တွင်းသတင်း")["total"], 1)
    check("an exact date finds it",
          mi.search("ဆန်", date="2026-10-02")["total"], 1)
    check("…and a day it is not from does not",
          mi.search("ဆန်", date="2026-10-01")["total"], 0)

    # Today is Yangon-time; `days=1` means today only.
    recent = mi.search("ဆန်", days=1)
    check("`days=1` is today only, so an older article is out of the window",
          recent["total"], 0)
    check("…and the undated row is COUNTED as skipped, not silently dropped",
          recent["undated_skipped"], 1)
    # A `days` filter can only ever return DATED rows — that is the limitation,
    # and the report says it rather than hiding it.
    wide = mi.search("ဆန်", days=30)
    check("a wide window finds the dated article", wide["total"], 1)
    check("…and still reports the undated one it had to leave out",
          wide["undated_skipped"], 1)
    check("…while the unfiltered search sees both", mi.search("ဆန်")["total"], 2)

    _head("a LIKE wildcard in the query cannot over-match")
    check("`%` matches nothing rather than everything",
          mi.search("%")["total"], 0)
    check("`_` likewise", mi.search("_")["total"], 0)

    check("limit is respected",
          mi.search("ဆန်", limit=1)["total"], 1)
    hits = mi.search("ဆန်", limit=10)["hits"]
    check("…and the newest article comes first",
          hits[0]["published_date"] >= hits[1]["published_date"], True)


# ── 5. distinct-entity search ────────────────────────────────────────────────


def _entity_search(mi) -> None:
    _head("a name search finds articles that NAME the person")
    who = mi.by_entity("people", "ဦးအောင်ကြိမ်")
    check("a name in the people column is found", who["total"], 1)
    check("…reported as the printed name with his rank",
          who["matched"], ["ပြည်ထောင်စုဝန်ကြီး ဦးအောင်ကြိမ်"])
    check("the article behind it comes back", who["hits"][0]["id"], "90001")

    check("organisations answer from their own column",
          mi.by_entity("organizations", "ကုန်သွယ်ရေးဝန်ကြီးဌာန")["total"], 1)
    check("places from theirs",
          mi.by_entity("locations", "မန္တလေးတိုင်းဒေသကြီး")["total"], 1)

    _head("a body word is not a person")
    check("`ဆန်` is in the article and in nobody's name",
          mi.by_entity("people", "ဆန်")["total"], 0)
    check("a place name is not accepted as a person",
          mi.by_entity("people", "ရန်ကုန်တိုင်းဒေသကြီး")["total"], 0)
    check("a bad `kind` is refused, not silently dropped",
          mi.by_entity("parks", "x")["error"], "bad kind")
    check("an empty name is refused too",
          mi.by_entity("people", "")["error"], "no name")


# ── 6. "new articles only" ───────────────────────────────────────────────────


def _new_only(mi) -> None:
    _head("new articles only — the whole of the daily run's cost")
    cards = CARDS["president-news"]
    check("an article already held is not fetched again",
          [c["id"] for c in mi.new_cards(cards, {"101"})], ["103"])
    check("…and a quiet run stops at the top of the list instead of walking",
          [c["id"] for c in mi.new_cards(cards, {"101", "103"},
                                         stop_after_known=1)], [])
    check("duplicate cards are collapsed",
          [c["id"] for c in mi.new_cards([{"id": "1"}, {"id": "1"},
                                          {"id": "2"}], set())], ["1", "2"])
    check("a card with no id is skipped — a row keyed on '' would collide",
          [c.get("id") or c.get("url")
           for c in mi.new_cards([{"id": "", "url": ""}, {"id": "2"}], set())],
          ["2"])
    check("an empty section is not an error", mi.new_cards([], {"1"}), [])


# ── 7. the crawl ─────────────────────────────────────────────────────────────


def _crawl(mi, mc, R) -> None:
    _head("the crawl stores what is new and never claims more than it did")
    mi.reset()
    mc.available = lambda: (True, "")
    mc.list_section = lambda slug, pages=0, until="": [
        dict(c) for c in CARDS.get(slug, [])]

    def _page(url: str) -> dict:
        if url == "/news/103":                       # a link that will not read
            raise RuntimeError("boom")
        return dict(PAGES.get(url, {"state": "missing", "text": "",
                                    "matched": False, "date": "", "author": ""}))

    mc.article_page = _page
    try:
        rep = mi.crawl(sections=("president-news", "other-news"), pages=1)
    except Exception as e:                                   # noqa: BLE001
        check(f"crawl raised ({type(e).__name__}: {e})", False, True)
        traceback.print_exc()
        return
    check("crawl reports the site reachable", rep["reachable"], True)
    check("…stored three articles", rep["stored"], 3)
    check("…per-section counts, not just a total",
          rep["sections"]["president-news"]["new"], 2)
    check("…and the index really holds them", mi.count(), 3)
    check("a body is stored when it could be read",
          mi.get("101")["content"], BODY)
    check("…an empty body is stored EMPTY, not invented",
          mi.get("102")["content"], "")
    check("…and the crawl records what it could not read",
          len(rep["errors"]), 1)
    check("…while still storing that article's headline",
          mi.get("103")["title"], "သတင်း မဖတ်နိုင်သူ")
    check("the run is recorded", bool(mi.last_run()), True)

    _head("a second crawl fetches nothing — this is 'new articles only'")
    rep2 = mi.crawl(sections=("president-news", "other-news"), pages=1)
    check("…zero new articles", rep2["new"], 0)
    check("…and the index did not grow", mi.count(), 3)

    _head("unreachable is not 'nothing new'")
    before, last_run = mi.count(), mi.last_run()
    mc.available = lambda: (False, "no route")
    try:
        down = mi.crawl(sections=("president-news",), pages=1)
    except Exception as e:                                   # noqa: BLE001
        check(f"crawl raised while down ({type(e).__name__})", False, True)
        return
    check("crawl says the site was unreachable", down["reachable"], False)
    check("…with the reason attached", down["reason"], "no route")
    check("…and reports 0 new as a NUMBER it did not claim as news",
          down["new"], 0)
    check("…the index is untouched", mi.count(), before)
    check("…and the last successful run is unchanged", mi.last_run(), last_run)
    check("…while the failed attempt IS recorded",
          mi.meta("last_attempt_result").startswith("unreachable"), True)

    msg = R._do_update({})
    check("`update` says it could not connect",
          "မချိတ်နိုင်" in msg, True)
    check("…and never claims a count of new articles while down",
          "အသစ် ၀" in msg or "အသစ် 0" in msg, False)
    check("…and corrects the wrong reading out loud, not just by omission",
          "မဆိုလိုပါ" in msg, True)


# ── 8. the tool ──────────────────────────────────────────────────────────────


def _the_tool(mi, mc, R, al) -> None:
    import inspect as _inspect

    _head("the TOOL is a single, valid declaration")
    check("one TOOL dict", isinstance(R.TOOL, dict), True)
    check("named for what it is", R.TOOL["name"], "moi_research")
    check("exactly one `TOOL = {` in the file (a second registers NEITHER)",
          Path(r"E:\Mark-LIV-main\actions\moi_research.py")
          .read_text(encoding="utf-8").count("TOOL = {"), 1)
    check("the handler takes `parameters` (the project's costliest bug)",
          "parameters" in _inspect.signature(R.TOOL["handler"]).parameters, True)
    rec = al._validate(R, "moi_research.py")
    check("the loader accepts it", rec.valid, True)
    check("…with no error", rec.error, "")
    reg = al.ActionRegistry({R.TOOL["name"]: rec}, lambda _m: None)
    check("…and it is dispatchable", reg.has("moi_research"), True)

    _head("the description steers — and names every competitor")
    desc = R.TOOL["description"]
    check("it names its source", "moi.gov.mm" in desc, True)
    for rival in ("moi_news", "news_section", "reporter_news", "news_search"):
        check(f"…and names {rival} as NOT this tool", rival in desc, True)
    check("it says index-first then live",
          "index first" in desc and "live" in desc, True)
    check("it says a whole-question query is retried with its own words",
          "never" in desc and "whole question" in desc, True)
    check("…and that a search list is not enough to summarise from",
          "'story'" in desc and "before summarising" in desc, True)
    check("…and that `update` takes minutes before it is called",
          "SEVERAL MINUTES" in desc, True)
    check("…and it names the daily 11:30 schedule",
          "11:30" in desc, True)
    for sentence in ("မရှိပါ", "မတွေ့ပါ", "မချိတ်နိုင်ပါ"):
        check(f"the four-answer sentence `{sentence}` is spelled out",
              sentence in desc, True)

    props = R.TOOL["parameters"]["properties"]
    for key in ("action", "query", "mention", "kind", "section", "date", "days",
                "limit", "url", "hour", "minute"):
        check(f"`{key}` is declared", key in props, True)
    check("nothing is required, so a bare `query` works",
          R.TOOL["parameters"]["required"], [])

    _head("the defaults answer the question they were given")
    source = Path(r"E:\Mark-LIV-main\actions\moi_research.py").read_text(encoding="utf-8")
    check("a `query` with no `action` means search, not a list",
          'action = "search" if (query or mention) else "status"' in source, True)
    # AST, not a substring: `_resolve`'s own docstring explains why `.isdigit()`
    # is wrong, so a text search would report the warning as the defect — the
    # exact false positive `review_gate.py` hit twice before going AST-based.
    import ast
    tree = ast.parse(source)
    isdigit_calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "isdigit"]
    check("no `.isdigit()` call in this Burmese-handling file",
          len(isdigit_calls), 0)
    check("the script adds the project root before its core imports",
          "sys.path.insert" in source and "--scheduled" in source, True)

    _head("a numeric id is read as digits, not as Burmese digits")
    check("…an ASCII id becomes a real article path",
          R._resolve("", "88673"), "/news/88673")
    check("…and a Burmese-digit id does NOT",
          R._resolve("", "၈၈၆၇၃").startswith("/news/"), False)

    _head("the scheduled command is the one the owner asked for")
    args = R._schtasks_args(R.DEFAULT_HOUR, R.DEFAULT_MINUTE)
    joined = " ".join(args)
    check("schtasks", args[0], "schtasks")
    check("task name is findable in Task Scheduler",
          R.TASK_NAME, "JARVIS_MOI_Crawler")
    check("daily at 11:30", args[args.index("/ST") + 1], "11:30")
    check("…on a daily schedule",
          args[args.index("/SC") + 1], "DAILY")
    check("…running the scheduled mode", "--scheduled" in joined, True)
    check("…this script's absolute path", R._SCRIPT in joined, True)
    check("…the python that owns the project",
          sys.executable in joined, True)
    check("…and it never hands a string to a shell",
          any(str(a).lower().startswith("shell") for a in args), False)
    check("the default time really is 11:30",
          (R.DEFAULT_HOUR, R.DEFAULT_MINUTE), (11, 30))

    _head("through the dispatcher, the way the app calls it")
    mc.available = lambda: (True, "")
    mc.search_site = lambda *a, **k: []
    empty = reg.run("moi_research", parameters={"query": "မဖြစ်နိုင်သောစကားလုံး"})
    check("a miss is answered, not raised",
          bool(isinstance(empty, str) and empty), True)
    check("…and it says the index and the live site both had nothing",
          "မတွေ့ပါ" in empty, True)
    check("…without also claiming the site was unreachable",
          "မချိတ်နိုင်ပါ" in empty, False)
    status = reg.run("moi_research", parameters={})
    check("no arguments means status, not a crawl",
          "MOI index" in status, True)
    check("…and status never raises", isinstance(status, str), True)


if __name__ == "__main__":
    sys.exit(main())
