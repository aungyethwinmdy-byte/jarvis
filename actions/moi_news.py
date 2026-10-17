"""State news, live from `moi.gov.mm` — the owner's system, 2026-10-01.

    *"JARVIS should search this website and answer me. Supabase is no longer in
    the middle. … If I say 'search the database', you search Supabase."*

And then, the same day, the ask this file is shaped around:

    *"Every news question I ask JARVIS should be searched on this website by
    section and answered back to me. … If I ask today's State President news,
    you go to /president-news and look. If there is news, show it. If there is
    none, reply that there is no president news today."*

So the split is now:

    `moi_news`   (this tool)   state news — live, always current
    `news_section` /           the database copies, for the topics the site has
    `reporter_news`            no section for, and for "search the database"

**Search goes index first, live as fallback (2026-10-13):** a keyword `search`
reads the local crawl index (`core/moi_index.py`) first — same site, crawled,
1–2 s, carries `published_date` (so `date`/`days` filters actually work; the
site's own search returns no dates and the old code silently emptied the list
when a date filter was applied, measured 2026-10-03), and covers the whole
archive. The live site search + section walk is the fallback when the index has
nothing. Section *listing* ("what is in the president section today") stays
live — that is the one question a cache can answer wrongly.

**`jarvis_news` and `core/jarvis_client.py` were REMOVED on 2026-10-01** — the
owner's instruction, *"jarvis news ကိုဖျက်လိုက်"*. It held a migrated copy of the
state papers, and the one thing it carried that the site does not — ပညာရေး ·
ကျန်းမာရေး · စီးပွားရေး · လူမှုရေး · သဘာဝဘေး — is already indexed by
`news_section` in the reporter project, so nothing was lost. Copies are kept at
`backup/removed-2026-10-01/`.

**A state-news question never touches Supabase**, which means it can never be
answered from a stale copy and never inherits a PDF's defects. Everything the
PDF pipeline needed — the glyph gate, the Zawgyi conversion, the vision
chunking, the section classifier — was there to reconstruct what this site
serves directly: clean Unicode, the publisher's own section, and a date.

WHAT IT IS CAREFUL ABOUT

    * **Four answers, not two.** The owner's "if there is none, say so" needs
      three *different* "none"s, because they mean different things:

        found        — here it is
        `မရှိပါ`      — the section has news, but not in this window (a limitation)
        `မတွေ့ပါ`     — the section is there and empty (a finding)
        `မချိတ်နိုင်ပါ` — the site could not be reached (a failure)

      A timeout spoken as "there is no such news" tells a journalist a story was
      never covered, on the strength of a socket. The three sentences are never
      merged, and **the first sentence is the one the model speaks** — so when
      the answer is a limitation, the limitation comes first and the pointer
      second.
    * **A dead section is not an empty section.** `/amyotha-hluttaw-news` — the
      spelling in the site's own navigation — returns 0 bytes while
      `/amyotha-htuttaw-news` returns 20 cards. `section_exists()` tells the two
      apart, so a wrong slug names the real sections instead of claiming there
      is no news.
    * **The site does not serve every article's body.** Measured 2026-10-01:
      `/news/88750` has an empty body — the headline *is* the content — while
      `/news/88603` has 9,023 characters. When the body is missing the answer says
      so and gives the headline and the link, rather than showing the page's
      chrome as if it were the story.
    * **It says where the answer came from.** The section, the date and the
      source are stated so the owner can check it.
"""
from __future__ import annotations

import re
from datetime import timedelta

from core import moi_client as mc
from core import moi_index as ix
from core.timefmt import now_mmt, to_burmese_digits

_MONTHS = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
           "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ",
           "ဒီဇင်ဘာ")
_DISPLAY_MAX = 20
# How deep `search` walks each section — **the fallback only**. Unbounded, ten
# sections × 20 pages is ~200 requests and the voice turn times out (measured
# 2026-10-01). It is now the fallback because it cannot reach the archive: at 4
# pages the president section only goes back ~6 weeks.
_SEARCH_PAGES = 4
# How deep a **section-scoped** search walks that one section. One section is
# cheap to walk where ten are not, and it carries the date the site search lacks.
# Measured 2026-10-03: the president's China trip is written 'နိုင်ငံတော်အဆင့်
# ချစ်ကြည်ရေးခရီးစဉ်', which a natural query does not match — the section walk is
# what reaches it.
_SECTION_SEARCH_PAGES = 20
# How many pages of the site's OWN search to read. 10 results a page and it is
# relevance-ranked, so two pages is the useful part of any answer — and unlike
# the walk it reaches the whole archive in one request per page.
_SITE_SEARCH_PAGES = 2
_NOT_FOUND = "ဖော်ပြပါ အကြောင်းအရာအတွက် သတင်းအချက်အလက် ရှာမတွေ့ပါခင်ဗျာ။"
# The site search reaches the whole archive; what it does NOT carry is a date, so
# the answer says so rather than leaving a blank where a date would be.
_SEARCH_SCOPE = ("ℹ️ moi.gov.mm ရဲ့ ကိုယ်ပိုင် ရှာဖွေမှု (archive တစ်ခုလုံး) နဲ့ "
                 "ရှာထားတာပါ။ ဒီစာရင်းမှာ ရက်စွဲ မပါပါ — သတင်းတစ်ခုရဲ့ ရက်စွဲနဲ့ "
                 "အပြည့်အစုံကို 'story' နဲ့ ကြည့်ပါ။")
_BOTH_SCOPE = ("ℹ️ moi.gov.mm ရဲ့ ကိုယ်ပိုင် ရှာဖွေမှု + ကဏ္ဍ တစ်ခုလုံး နှစ်ခုလုံးနဲ့ "
               "ရှာထားတာပါ။ ရက်စွဲပါတဲ့ အပိုင်းက ကဏ္ဍမှ ဖတ်ထားတာပါ။")


def _date(value: str) -> str:
    try:
        y, m, d = str(value).split("-")
        return f"{to_burmese_digits(y)} {_MONTHS[int(m)]} {to_burmese_digits(int(d))} ရက်"
    except Exception:                                       # noqa: BLE001
        return str(value or "")


def _today_mmt() -> str:
    """Today in Yangon, as YYYY-MM-DD. The site dates are publication dates."""
    return now_mmt().date().isoformat()


def _floor(days: int) -> str:
    """The oldest date a window of `days` still includes, counting today as day 1."""
    return (now_mmt().date() - timedelta(days=max(1, days) - 1)).isoformat()


def _unreachable(why: str) -> str:
    return ("⚠️ moi.gov.mm ကို မချိတ်နိုင်ပါ — ကွန်ရက် ခဏ ပြတ်နေတာပါ။\n"
            "ဒါက 'သတင်း မရှိဘူး' လို့ မဆိုလိုပါ။ ခဏနေ ပြန်မေးပေးပါ။\n"
            f"({why})")


def _card(c: dict, body: str = "") -> str:
    """One article in the owner's shape, with the source named.

    The date line is **omitted when there is no date** rather than printed as
    `?` — the site's own search results carry no date, and a question mark where
    a date belongs reads as a missing answer.
    """
    head = (c.get("headline") or "").strip()
    where = c.get("section_label") or c.get("section") or "moi.gov.mm"
    stamp = c.get("issue_date")
    out = [f"**ရင်းမြစ်**: moi.gov.mm — {where}"
           + (f" (ရက်စွဲ: {stamp})" if stamp else ""),
           f"**ကဏ္ဍ**: {c.get('category') or where}",
           f"**ခေါင်းစဉ်**: {head}"]
    # A summary that is just the headline again says nothing — measured on
    # `/news/88750`, whose body is empty so its summary IS its headline.
    text = (body or c.get("summary") or "").strip()
    if text and text != head:
        out.append(f"**အနှစ်ချုပ်**: {text[:600]}{'…' if len(text) > 600 else ''}")
    out.append(f"**လင့်**: {mc.BASE}{c.get('url')}")
    return "\n".join(out)


def _index_card(r: dict) -> str:
    """One article from the local crawl index, in the same shape as `_card`.

    The index row carries `published_date` (YYYY-MM-DD), so unlike the site's
    own search results the date line is always printed — a date filter that
    silently emptied the live list (measured 2026-10-03) cannot do that here.
    """
    url = str(r.get("url") or "")
    link = url if url.startswith("http") else (f"{mc.BASE}{url}" if url else mc.BASE)
    head = str(r.get("title") or "").strip()
    where = r.get("section_label") or r.get("section") or "moi.gov.mm"
    stamp = str(r.get("published_date") or "").strip()
    out = [f"**ရင်းမြစ်**: moi.gov.mm (index) — {where}"
           + (f" (ရက်စွဲ: {_date(stamp)})" if stamp else ""),
           f"**ခေါင်းစဉ်**: {head}"]
    text = str(r.get("summary") or "").strip()
    if text and text != head:
        out.append(f"**အနှစ်ချုပ်**: {text[:600]}{'…' if len(text) > 600 else ''}")
    out.append(f"**လင့်**: {link}")
    return "\n".join(out)


def _section_missing(asked: str) -> str:
    known = "၊ ".join(label for _s, label, _c in mc.SECTIONS if _s != "news")
    return (f"'{asked}' ဆိုတဲ့ ကဏ္ဍ moi.gov.mm မှာ မရှိပါ။\n"
            f"ရှိတာက — {known} ။\n"
            f"(နိုင်ငံတော်သတင်း မဟုတ်ရင် 'database မှာ ရှာပါ' လို့ ပြောပါ။)")


# ── The spoken channel ────────────────────────────────────────────────────────
# `action='read'` is the same article as `story`, but written for the ear: the
# model reads the answer aloud, so the marks that belong to the screen — markdown
# bold, links, emoji, list bullets — would be either read out as themselves or
# skipped. The classes below are the same rules core/newsroom_client.py applies
# to its reports (emoji + bullet), because the spoken path needs the same shape
# everywhere; the markdown/link classes are this file's own, because its text
# is the site's and the tool's own `**`-labelled headers.
_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U0001F1E6-\U0001F1FF"
    "\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u20E3" "]"
)
# A bare '-' or '*' only counts when a space follows, so "-5 degrees" survives
# while "- item" does not; • and the other list dots are stripped outright.
_BULLET_RE = re.compile(r"^(?:[\u2022\u25AA\u25CF\u25E6\u2023\u2043\u00B7]+|[-*]\s+)\s*")
_MD_RE = re.compile(r"\*\*+|`+")            # markdown bold / code spans
_LINK_RE = re.compile(r"https?://\S+")


def _for_speech(text: str) -> str:
    """MOI text -> plain Burmese that reads aloud like a news bulletin.

    Strips the marks that belong to the screen, collapses the whitespace they
    leave behind, and converts ASCII digits to Burmese numerals — the same
    rule core/timefmt.py established for the spoken path.
    """
    out = _MD_RE.sub("", str(text or ""))
    out = _LINK_RE.sub(" ", out)
    out = _EMOJI_RE.sub(" ", out)
    lines = []
    for ln in out.splitlines():
        ln = _BULLET_RE.sub("", ln.strip())
        lines.append(re.sub(r"[ \t]+", " ", ln).strip())
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return to_burmese_digits(out)


def _index_row(url: str) -> dict | None:
    """The article as the local index read it, or None when it has not.

    `ix.get` is distinct from `{}`: a missing row means "not indexed", so the
    live answer is returned as-is rather than padded with an empty claim.
    """
    try:
        return ix.get(url)
    except Exception:                                       # noqa: BLE001
        return None


def _people_text(items: list) -> str:
    """Names the way the article printed them — rank included."""
    out = []
    for p in items:
        if isinstance(p, dict):
            label = f"{p.get('title','')} {p.get('honorific','')}{p.get('name','')}".strip()
        else:
            label = str(p)
        if label and label not in out:
            out.append(label)
    return "၊ ".join(out)


def _facts_block(row: dict | None) -> str:
    """Names the index extracted from this article, or `""` when it has none.

    The index read the site this morning, so it carries structured facts
    (people, organisations, places) that the live page does not expose in one
    fetch — and the label is the honesty rule: an index answer is never passed
    off as a live one.
    """
    if not row:
        return ""
    bits = []
    people = _people_text(row.get("people") or [])
    if people:
        bits.append(f"လူ: {people}")
    orgs = "၊ ".join(str(o) for o in (row.get("organizations") or []))
    if orgs:
        bits.append(f"အဖွဲ့အစည်း: {orgs}")
    places = "၊ ".join(str(l) for l in (row.get("locations") or []))
    if places:
        bits.append(f"နေရာ: {places}")
    if not bits:
        return ""
    stamp = str(row.get("updated_at") or row.get("created_at") or "").strip()
    stamp = stamp[:16] if len(stamp) >= 16 else stamp or "မသိရပါ"
    return (f"📇 MOI index ထဲက extract (crawl: {stamp}) — ဒီသတင်းမှာ "
            f"ဖော်ပြထားတဲ့ အမည်များ:\n  • " + "\n  • ".join(bits))


def _for_speech_bulletin(url: str, stamp: str, row: dict | None, body: str) -> str:
    """The article as a spoken news bulletin: plain, digit-converted, facts in."""
    # The screen form keeps the full URL; the spoken form does not, because a
    # TTS voice reads "https://…" letter by letter while "moi.gov.mm" reads as
    # a source. The owner who wants the link still has it in the digest.
    head = "ရင်းမြစ်: moi.gov.mm"
    if stamp:
        head += f" — {_date(stamp)}"
    head = _for_speech(head)        # Burmese digits, one space per gap
    out = [head]
    title = str((row or {}).get("title") or "").strip()
    if title:
        out.append(f"ခေါင်းစဉ်: {title}")
    facts = _facts_block(row)
    if facts:
        out.append(_for_speech(facts))
    out.append("")
    out.append(_for_speech(body))
    return "\n".join(out)



def moi_news(parameters: dict = None, player=None, session_memory=None, **_) -> str:
    """Voice entry point.

    The signature is `(parameters, ...)` because `core/action_loader.py` calls a
    handler as `fn(parameters=parameters, ...)`. A handler written
    `fn(section="", **_)` swallows the whole argument dict in its own `**_` and
    runs on defaults — measured 2026-09-29, when six tools did exactly that and
    the log showed the arguments arriving and being discarded.
    """
    p = parameters or {}
    asked = str(p.get("section") or p.get("query") or "").strip()
    term = str(p.get("query") or "").strip()
    action = str(p.get("action") or "").strip().lower()
    if not action:
        # **A `query` means search.** Measured 2026-10-03: the model passed
        # `query='အိန္ဒိယ ခရီးစဉ်'` and **no `action`**, the default was `list`, and
        # the tool listed the president's section instead of searching — so the
        # answer said the India trip was not in the news, on a site that covers
        # it in a dozen articles. **A parameter that answers the question must
        # not then be ignored**, and the default must not throw it away.
        action = "search" if term else "list"
    date = str(p.get("date") or "").strip()
    try:
        limit = max(1, min(int(p.get("limit") or 8), _DISPLAY_MAX))
    except (TypeError, ValueError):
        limit = 8
    try:
        days = max(0, min(int(p.get("days") or 0), 365))
    except (TypeError, ValueError):
        days = 0

    ok, why = mc.available()
    if not ok:
        return _unreachable(why)

    # ── What the site carries ───────────────────────────────────────────────
    if action in ("sections", "categories", "index"):
        out = ["📚 moi.gov.mm မှာ ဒီကဏ္ဍတွေ ရှိတယ်:", ""]
        for slug, label, _cat in mc.SECTIONS:
            if slug == "news":          # the superset of every other section
                continue
            cards = mc.list_section(slug, pages=1)
            span = (f"  ({cards[-1]['issue_date']} … {cards[0]['issue_date']})"
                    if cards else "  (ဗလာ)")
            out.append(f"  • {label} — စာမျက်နှာ ၁ မှာ {to_burmese_digits(len(cards))} ခု{span}")
        out += ["", "ℹ️ ဒါက ဝက်ဘ်ဆိုဒ်ကနေ တိုက်ရိုက် ရှာတာပါ — database မှ မဟုတ်ပါ။"]
        return "\n".join(out)

    # ── One article in full ─────────────────────────────────────────────────
    # `read` is the spoken form of `story`: the same article, cleaned for the
    # ear (plain text, Burmese digits, no markdown/emoji), so the model reading
    # it aloud sounds like a news bulletin rather than an editor's screen.
    if action in ("story", "article", "full", "read"):
        spoken = action == "read"
        url = str(p.get("url") or "").strip()
        # `term.isdigit()` is True for ၀-၉ as well as 0-9, so a Burmese-digit id
        # would build `/news/၈၈၆၇၃`. `re.search(r"[0-9]")` is the honest test.
        if not url and term and re.fullmatch(r"[0-9]+", term):
            url = f"/news/{term}"
        if not url:
            return ("ဘယ်သတင်းလဲ ပြောပါ — လင့် ဒါမှမဟုတ် သတင်းအမှတ် "
                    "(ဥပမာ '88673') ပေးပါ။")
        if not url.startswith("/"):
            url = "/" + url.lstrip("/")
        body = mc.article(url)
        if not body:
            # **A failed read is not an empty source.** Measured 2026-10-03: a
            # `/president-speech/N` page whose text lived in a container we did
            # not know was reported as *"the site gives no text for this story"* —
            # a false claim about the publisher. `missing` and an empty body are
            # about the site; `unreadable` is about us.
            state = mc.article_state(url)
            if state == "missing":
                return (f"⚠️ {mc.BASE}{url} မှာ သတင်းမရှိပါ — လင့်က မှားနေနိုင်ပါတယ်။\n"
                        f"ℹ️ moi.gov.mm မှာ တိုက်ရိုက် စစ်ထားတာပါ။")
            if state == "empty":
                return (f"ℹ️ {mc.BASE}{url} မှာ သတင်းကိုယ်ထည် မပါပါ — "
                        f"ဝက်ဘ်ဆိုဒ်က ဒီသတင်းအတွက် စာသား မပေးထားပါ။\n"
                        f"ခေါင်းစဉ်နဲ့ လင့်ကိုတော့ ဖွင့်ကြည့်လို့ ရပါတယ်: {mc.BASE}{url}")
            return (f"⚠️ {mc.BASE}{url} ရဲ့ စာသားကို **ဖတ်လို့ မရပါ** — စာမျက်နှာကတော့ "
                    f"ရှိပါတယ်၊ ကျွန်မ စာသားကို ရှာမတွေ့တာပါ။\n"
                    f"ဒါက 'သတင်း မရှိဘူး' လို့ မဆိုလိုပါ။ ခေါင်းစဉ်နဲ့ လင့်ကိုတော့ "
                    f"ဖွင့်ကြည့်လို့ ရပါတယ်: {mc.BASE}{url}")
        # The search result list carries no date, so the article's own date is
        # read here — without it a summary built from search hits cannot say when
        # anything happened. The index's copy is read for the title and the
        # facts; a row that is not indexed simply contributes nothing.
        stamp = mc.article_date(url)
        row = _index_row(url)
        if spoken:
            return _for_speech_bulletin(url, stamp, row, body)
        head = f"**ရင်းမြစ်**: moi.gov.mm ({mc.BASE}{url})"
        if stamp:
            head += f"\n**ရက်စွဲ**: {_date(stamp)}"
        facts = _facts_block(row)
        if facts:
            return f"{head}\n\n{body[:2500]}\n\n{facts}"
        return f"{head}\n\n{body[:2500]}"

    # ── A term across the sections ──────────────────────────────────────────
    if action in ("search", "find") and term:
        slug = mc.resolve_section(asked) if asked != term else ""
        # ── The local index FIRST — same site, crawled, 1–2 s, dated, whole
        # archive. The live site search + section walk below is the fallback.
        # The index carries `published_date`, so `date`/`days` filters work
        # here — the site's own search returns no dates, and the old code
        # applied the filter to that dateless list and silently emptied every
        # result (measured 2026-10-03).
        idx_hits: list[dict] = []
        idx_note = ""
        try:
            rep = ix.search(term, section=slug, date=date, days=days,
                            limit=_DISPLAY_MAX)
            idx_hits = rep.get("hits") or []
        except Exception:                                   # noqa: BLE001
            idx_hits = []
        if not idx_hits and (date or days):
            # The filter may be why the index found nothing — retry once
            # without it and say so, rather than falling through to a dateless
            # live list. (Same honesty rule as moi_research.)
            try:
                rep = ix.search(term, section=slug, limit=_DISPLAY_MAX)
                if rep.get("hits"):
                    idx_hits = rep.get("hits") or []
                    idx_note = ("ℹ️ ရက်နဲ့ စစ်လို့ မတွေ့လို့ ရက်မပါ ရှာထားပါတယ် — "
                                "အောက်က ရက်စွဲတွေကို ကြည့်ပြီး ရွေးပါ။")
            except Exception:                               # noqa: BLE001
                pass
        if idx_hits:
            try:
                idx_when = ix.last_run() or ""
            except Exception:                               # noqa: BLE001
                idx_when = ""
            out = [f"'{term}' နဲ့ ကိုက်တဲ့ သတင်း "
                   f"{to_burmese_digits(len(idx_hits))} ခု (moi.gov.mm — index):", ""]
            for r in idx_hits[:limit]:
                out += [_index_card(r), ""]
            if idx_note:
                out.append(idx_note)
            out.append(f"ℹ️ MOI index ထဲက ရှာထားတာပါ"
                       + (f" (crawl: {idx_when[:16]})" if idx_when else "")
                       + " — ဒီစာရင်းမှာ ရက်စွဲ ပါပါတယ်။ "
                         "ဒီနေ့အသစ်ဆုံး သတင်း လိုချင်ရင် live မှာ ထပ်စစ်ခိုင်းပါ။")
            return "\n".join(out).rstrip()
        # ── The index had nothing: live site search + section walk (below). ──
        # **The site's own search first.** One request per page, relevance-ranked,
        # and it reaches the whole archive. Measured 2026-10-03: the page-walk was
        # bounded at 4 pages per section, so the president's trip to India
        # (2026-05-28 → 06-03) was unreachable and nine unrelated articles came
        # back instead — a silent wrong answer. The walk is kept as the fallback
        # because it carries a section and a date that the site search does not.
        hits = mc.search_site(term, pages=_SITE_SEARCH_PAGES, limit=_DISPLAY_MAX)
        used = "site"
        # **A whole-question query matches nothing.** The site search is a phrase
        # match and the model often passes the sentence. Measured 2026-10-03:
        # 'နိုင်ငံတော်သမ္မတ အိန္ဒိယ ခရီးစဉ်' returned 0 while 'အိန္ဒိယ' alone returned 20,
        # three of them the trip. Burmese separates phrases with spaces, so the
        # tokens are tried longest-first and the answer names the one that worked.
        if not hits:
            for tok in sorted({t for t in re.split(r"\s+", term) if len(t) > 2},
                              key=len, reverse=True):
                hits = mc.search_site(tok, pages=1, limit=_DISPLAY_MAX)
                if hits:
                    term = tok
                    break
        if not hits:
            hits = mc.search(term, sections=(slug,) if slug else (),
                             pages=_SEARCH_PAGES, limit=_DISPLAY_MAX)
            used = "walk"
        # **A named section is walked DEEPLY and merged in.** The site search is
        # relevance-ranked and does not carry dates; the walk carries both the
        # date and the section label, and one section is cheap to walk where ten
        # are not. Measured 2026-10-03: 'တရုတ် ခရီးစဉ်' returned **no** China-trip
        # news article in its top eight — the trip is written 'နိုင်ငံတော်အဆင့်
        # ချစ်ကြည်ရေးခရီးစဉ် (State Visit)' — while the president's section holds
        # **23** China articles. Merging is what finds the trip. Tokens are used,
        # not the whole phrase, for the same reason as the site search above.
        if slug:
            deep: list[dict] = []
            site_urls = {h["url"] for h in hits}
            deep_urls: set[str] = set()
            for tok in ([t for t in re.split(r"\s+", term) if len(t) > 2] or [term])[:2]:
                for card in mc.search(tok, sections=(slug,),
                                      pages=_SECTION_SEARCH_PAGES, limit=_DISPLAY_MAX):
                    if card["url"] in site_urls or card["url"] in deep_urls:
                        continue
                    deep_urls.add(card["url"])
                    deep.append(card)
            if deep:
                # **The dated, in-section hits go FIRST.** They are the ones that
                # answer a "summarise the trip" question, and appending them put
                # them past `limit` — measured 2026-10-03, the trip's news
                # articles were merged in and then cut off by `limit=8`.
                hits = deep + hits
                used = "both" if used == "site" else "walk"
        # **A date filter cannot be applied to a result that carries no date.**
        # The site-search list has none, and `"" >= floor` is False — so the
        # filter silently emptied every result. Measured 2026-10-03: the model
        # passed `days=30`, the search found 20 articles including the trip, and
        # **all 20 were dropped before the answer** — the owner was told there was
        # no news about a trip the site covers in a dozen articles. Applied only
        # to the walk, which does carry dates, and the answer says when it could
        # not be applied.
        date_filtered = False
        if used == "walk":
            if date:
                hits = [c for c in hits if c.get("issue_date") == date]
                date_filtered = True
            elif days:
                floor = _floor(days)
                hits = [c for c in hits if (c.get("issue_date") or "") >= floor]
                date_filtered = True
        where = mc.SECTION_LABEL.get(slug, slug) if slug else ""
        if not hits:
            if not mc.available()[0]:
                return _unreachable(why)
            scope = f"moi.gov.mm ရဲ့ '{where}' မှာ " if where else "moi.gov.mm မှာ "
            return (f"'{term}' နဲ့ ကိုက်တဲ့ သတင်း {scope}{_NOT_FOUND}\n"
                    f"ℹ️ ဝက်ဘ်ဆိုဒ်ရဲ့ ကိုယ်ပိုင် ရှာဖွေမှုနဲ့ ရှာထားတာပါ။")
        out = [f"'{term}' နဲ့ ကိုက်တဲ့ သတင်း {to_burmese_digits(len(hits))} ခု "
               f"(moi.gov.mm):", ""]
        for c in hits[:limit]:
            out += [_card(c), ""]
        if used == "site":
            out.append(_SEARCH_SCOPE)
            if (date or days) and not date_filtered:
                out.append(f"ℹ️ ရက်အလိုက် စစ်ဖို့ ပြောခဲ့ပေမယ့် ဒီရလဒ်စာရင်းမှာ ရက်စွဲ "
                           f"မပါလို့ ရက်နဲ့ စစ်လို့ မရပါ — ရက်စွဲကို 'story' နဲ့ ကြည့်ပါ။")
        elif used == "both":
            out.append(_BOTH_SCOPE)
        else:
            out.append(f"ℹ️ ကဏ္ဍ တစ်ခုချင်းရဲ့ နောက်ဆုံး စာမျက်နှာ "
                       f"{to_burmese_digits(_SECTION_SEARCH_PAGES)} အထိ ရှာထားတာပါ — "
                       f"အဟောင်းဆုံး သတင်းတွေ ပါမလာနိုင်ပါ။")
        return "\n".join(out).rstrip()

    # ── A section's latest ──────────────────────────────────────────────────
    slug = mc.resolve_section(asked) if asked else ""
    if asked and not slug:
        # A slug that does not exist and a section that is empty are different
        # answers. Only ask the site when we do not already recognise the name.
        return _section_missing(asked)

    slug = slug or "president-news"
    label = mc.SECTION_LABEL.get(slug, slug)

    # ── The window the owner asked about ────────────────────────────────────
    # Computed BEFORE the fetch, because it is also the bound that lets the walk
    # stop. Measured 2026-10-01 in a live session: "အောက်တိုဘာ ၂ ရက်နေ့က နိုင်ငံတော်သမ္မတ
    # သတင်းပြောပြပေးပါ" walked all 20 pages (~20 s) and the turn died before the
    # model spoke. `until` makes the same question one or two pages.
    if date:
        window, floor, until = date, "", date
    elif days:
        window = _today_mmt() if days == 1 else _floor(days)
        floor = until = _floor(days)
    else:
        window, floor, until = "", "", ""

    cards = mc.list_section(slug, pages=20, until=until)
    if not cards:
        if not mc.available()[0]:
            return _unreachable(why)
        if not mc.section_exists(slug):
            return _section_missing(asked or label)
        return f"{_NOT_FOUND}\nℹ️ moi.gov.mm မှာ တိုက်ရိုက် ရှာထားတာပါ။"

    if floor:
        in_window = [c for c in cards if (c.get("issue_date") or "") >= floor]
        if not in_window:
            # The limitation comes FIRST — it is the sentence the model speaks —
            # and the pointer second. `မရှိပါ`, never `မတွေ့ပါ`: the section has
            # news, it just has none in this window.
            newest = cards[0]
            return (f"📅 {'ဒီနေ့' if days == 1 else 'ဒီ ' + to_burmese_digits(days) + ' ရက်'} "
                    f"({_date(window)}) အတွက် '{label}' ကဏ္ဍမှာ **သတင်း မရှိပါ**။\n"
                    f"ℹ️ ဒီကဏ္ဍမှာ အနီးစပ်ဆုံး သတင်းက {_date(newest['issue_date'])} — "
                    f"\"{newest['headline']}\" ပါ။\n"
                    f"({mc.BASE}{newest['url']})\n"
                    f"ℹ️ moi.gov.mm ကနေ တိုက်ရိုက် စစ်ထားတာပါ — database မှ မဟုတ်ပါ။\n"
                    f"(ဒီမေးခွန်းအတွက် အခြား သတင်း tool ကို ထပ်မခေါ်ပါနှင့် — ဒါက အတည်ပြုပြီး "
                    f"အဖြေပါ။ အခုရတဲ့ အချက်အလက်ကို ပြန်ပြောပါ။\n"
                    f"ပြောတဲ့အခါ **'သတင်း မရှိပါ'** လို့ ပြောပါ — **'မတွေ့ပါ'** လို့ မပြောပါနှင့်။ "
                    f"ဒါက ရှာမတွေ့တာ မဟုတ်ဘဲ အဲဒီရက်တွေမှာ သတင်း မရှိတာပါ။)")
        cards = in_window
    elif date:
        cards = [c for c in cards if c.get("issue_date") == date]
        if not cards:
            return (f"📅 {_date(date)} ရက်နေ့အတွက် '{label}' ကဏ္ဍမှာ **သတင်း မရှိပါ**။\n"
                    f"ℹ️ moi.gov.mm ကနေ တိုက်ရိုက် စစ်ထားတာပါ။")

    head = (f"📚 moi.gov.mm — '{label}'"
            f"{' — ' + _date(window) if window else ''} — သတင်း "
            f"{to_burmese_digits(len(cards))} ခု:")
    out = [head, ""]
    for c in cards[:limit]:
        out += [_card(c), ""]
    if len(cards) > limit:
        out.append(f"  … (ပထမ {to_burmese_digits(limit)} ခု ပြထားတယ်)")
    if cards:
        out += ["", f"📅 ရက်စွဲ အကွာအဝေး — {cards[-1]['issue_date']} ကနေ "
                    f"{cards[0]['issue_date']} အထိ"]
    return "\n".join(out).rstrip()


TOOL = {
    "name": "moi_news",
    "description": (
        "**State news, live from `moi.gov.mm`.** This is THE tool for every "
        "state-news question — use it for anything about the state, the "
        "government, the parliaments or the Ministry of Information's own "
        "reporting. "
        "\n"
        "**State news, live from `moi.gov.mm` — this is THE tool for it.** Use it "
        "for anything about the state, the government, the parliaments, or the "
        "Ministry of Information's own reporting. "
        "\n"
        "**Never answer a state-news question from the database.** The owner's "
        "rule: state news comes from this website. So **`news_section`, "
        "`reporter_news` and `news_search` are NOT the tools for the president, a "
        "vice-president, a hluttaw, a ministry, or state news in general** — they "
        "read a copy. Measured 2026-10-03: a state-news question was sent to "
        "`reporter_news` and then `news_search` first, both answered "
        "*'မတွေ့ပါ'*, and the owner was told there was no news about a trip this "
        "site covers in a dozen articles. **Call this tool first for anything "
        "about the state** — the others are for the topics the site lacks and for "
        "'search the database'. "
        "Measured 2026-10-01: a vice-president's story was **invisible** to "
        "`news_section` (its body was unparseable, so only the headline carried "
        "the name) and that tool answered the same question with the president "
        "instead. "
        "\n"
        "**The one thing the site has no section for** — ပညာရေး · ကျန်းမာရေး · "
        "စီးပွားရေး · လူမှုရေး · သဘာဝဘေး, and fuel/gold prices — is **not here**: "
        "use `news_section` for those topics and `gold_currency` for the "
        "prices. "
        "\n"
        "**A keyword, name, place or number question is `moi_research`, not this "
        "tool.** This tool reads a **section inside its date window** — what is in "
        "the president section today, yesterday, this week. `moi_research` answers "
        "a **search**: 'ရွှေဈေးနဲ့ပတ်သက်တဲ့သတင်းတွေ ရှာပေး', 'ဦးမင်းအောင်လှိုင်ကို "
        "mention လုပ်ထားတဲ့သတင်းတွေ ဒီတစ်ပတ်အတွင်း', 'ဒီသတင်းထဲက ကိန်းဂဏန်းတွေ သီးသန့်ပြောပြ'. "
        "It searches a local index of the **same site** first (1–2 seconds) and "
        "falls back to this site live, so it is faster and it reaches the whole "
        "archive rather than the pages this walk can cover. **Both read "
        "`moi.gov.mm`; neither reads a copy.** "
        "\n"
        "**This tool's answer is final.** Once it has answered — **including when "
        "it says there is no news in that window** — report that and stop. Do not "
        "call another news tool afterwards to double-check a state-news question; "
        "a second source reads a copy, so it can only disagree with the live one. "
        "\n"
        "\n"
        "**The sections it can search** (`section`, in the owner's own words, "
        "never translated): နိုင်ငံတော်သမ္မတ · ဒုတိယသမ္မတ · လွှတ်တော်သတင်း · "
        "ပြည်ထောင်စုလွှတ်တော် · ပြည်သူ့လွှတ်တော် · အမျိုးသားလွှတ်တော် · "
        "တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ် · ပြည်တွင်းသတင်း · ဆောင်းပါး · "
        "အယ်ဒီတာ့အာဘော်. "
        "\n"
        "Actions: "
        "'list' (default) — a section's articles, newest first. "
        "'search' — a **term** across the sections, e.g. a country, a place or a "
        "person's name; use it for 'X အကြောင်း သတင်းရှိလား'. "
        "**`search` reads the local MOI index first** (the same site, crawled — "
        "1–2 s, dated, whole archive) and falls back to the live site search + "
        "section walk only when the index has nothing. The answer always says "
        "which source it used. "
        "**The result list carries only a one-line snippet** (index results also "
        "carry the date; live site-search results do not) — so for "
        "a question that asks for a summary ('အကျဉ်းချုပ် တင်ပြပါ', 'အသေးစိတ် ပြောပါ'), "
        "follow it with `action='story'` on the most relevant link and summarise "
        "from the article's own text. Measured 2026-10-03: a summary was spoken "
        "from a snippet alone and missed the article that was actually about the "
        "event. "
        "'sections' — what the site carries and how much. "
        "'story' — one article in full, by `url` or a numeric id. "
        "**Both `story` and `read` also answer 'ဒီသတင်းထဲမှာ ဘယ်သူတွေပါလဲ' in the "
        "same call** — when the local index has read the same page it appends the "
        "names it extracted (people, organisations, places), clearly labelled "
        "`index`. For a deeper fact list than that — 'ကိန်းဂဏန်းတွေ သီးသန့်', "
        "'authorities/entities only' — use `moi_research`'s `entities` and "
        "`numbers` actions. "
        "'read' — the **spoken** form of `story`: the same article, cleaned for "
        "the ear — no markdown, no emoji, ASCII digits already Burmese — so when "
        "the owner says 'သတင်းကို ဖတ်ပြ' / 'read it aloud', pass `action='read'` "
        "and read the answer straight out like a news bulletin. "
        "\n"
        "**When the owner asks about TODAY or a recent day** ('ဒီနေ့ … ရှိလား', "
        "'မနေ့က', 'ဒီအပတ်'), pass `days`: `days=1` is today, `days=2` is today and "
        "yesterday, `days=7` is the last week. Do not leave it empty for a "
        "today-question, and do not compute the date yourself — `days` is what "
        "the tool understands. "
        "\n"
        "**Do not translate the section name or the search term** — the site is "
        "Burmese and matches the exact wording. "
        "\n"
        "IMPORTANT — the answer has four shapes and they are not "
        "interchangeable. Read the tool's first line out as it is given: "
        "`မရှိပါ` = the section has news but none in that window; "
        "`မတွေ့ပါ` = the section is empty; "
        "`မချိတ်နိုင်ပါ` = the site could not be reached, which is **not** the "
        "same as finding nothing. Never turn a failure or a limitation into "
        "'there is no such news'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list (default) | search | sections | story | read",
            },
            "section": {
                "type": "STRING",
                "description": ("What the owner called the section, in Burmese — "
                                "'နိုင်ငံတော်သမ္မတ', 'ဒုတိယသမ္မတ', 'လွှတ်တော်သတင်း', "
                                "'ပြည်ထောင်စုလွှတ်တော်', 'ပြည်သူ့လွှတ်တော်', "
                                "'အမျိုးသားလွှတ်တော်', 'တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်', "
                                "'ပြည်တွင်းသတင်း', 'ဆောင်းပါး', 'အယ်ဒီတာ့အာဘော်'. "
                                "Do not translate."),
            },
            "query": {
                "type": "STRING",
                "description": ("For action='search': **one or two words** in "
                                "Burmese. Do NOT pass the whole question — the site "
                                "matches phrases, so 'နိုင်ငံတော်သမ္မတ အိန္ဒိယ ခရီးစဉ်' "
                                "finds nothing while 'အိန္ဒိယ ခရီးစဉ်' finds the trip. "
                                "**For an event, pass two words, not one:** measured "
                                "2026-10-03, 'အိန္ဒိယ ခရီးစဉ်' ranked the trip article "
                                "first while 'အိန္ဒိယ' alone ranked border-road stories "
                                "above it. Do not translate."),
            },
            "url": {
                "type": "STRING",
                "description": ("For action='story' or 'read': the article's path, "
                                "e.g. '/news/88673'."),
            },
            "date": {
                "type": "STRING",
                "description": ("YYYY-MM-DD, one exact day. Use `days` instead when "
                                "the owner says 'today' or 'yesterday'. **For two or "
                                "more named days, call this tool once per day** — do "
                                "NOT widen it to a `days` window, which would answer "
                                "about days the owner never asked about. Measured "
                                "2026-10-03: asked for 1 Oct *and* 27 Sep, two calls "
                                "gave 1 and 4 articles correctly; a `days=7` window "
                                "would have added 2 Oct as well."),
            },
            "days": {
                "type": "NUMBER",
                "description": ("How many days back from today (Yangon time) to "
                                "include: 1 = today only, 2 = today and yesterday, "
                                "7 = the last week. Use this for 'ဒီနေ့' / 'မနေ့က'."),
            },
            "limit": {
                "type": "NUMBER",
                "description": ("Max articles to show (default 8, max 20). **Leave "
                                "this at its default for a search** — measured "
                                "2026-10-03, `limit=1` on a trip-summary question "
                                "returned one unrelated article and the summary was "
                                "about the wrong thing."),
            },
        },
        "required": [],
    },
    "handler": moi_news,
}
