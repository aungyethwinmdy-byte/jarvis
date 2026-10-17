"""Read the state news **live** from `moi.gov.mm`. No database in the path.

WHY THIS REPLACES THE DATABASE FOR STATE NEWS

    The owner's instruction, 2026-10-01:

        *"JARVIS should search this website and answer me. Supabase is no longer
        in the middle. I will keep Supabase as a place to store the files and
        data I want to keep. If I say 'search the database', you search Supabase.
        The rest of the state news comes from this website."*

    So the two are now separate jobs:

        `moi_client` (this file)   state news — live, always current
        `reporter_client`          the database copies of the state papers

    **`core/jarvis_client.py` was removed 2026-10-01** on the owner's
    instruction; it read a migrated copy of the same papers.

    Nothing is copied between them. A state-news question never touches Supabase,
    which also means it can never answer from a stale copy.

WHAT THE SITE ACTUALLY SERVES — measured 2026-10-01, not assumed

    Eleven sections, each with the **publisher's own label** read out of the page's
    `<title>`, and each verified to return article cards:

        /president-news            နိုင်ငံတော်သမ္မတ
        /vice-presidents-news      ဒုတိယသမ္မတသတင်းများ
        /hluttaw-news              လွှတ်တော်သတင်း
        /pyidaungsu-hluttaw-news   ပြည်ထောင်စုလွှတ်တော်
        /pyithu-htuttaw-news       ပြည်သူ့လွှတ်တော်
        /amyotha-htuttaw-news      အမျိုးသားလွှတ်တော်
        /commander-in-chief-news   တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်သတင်း
        /other-news                ပြည်တွင်းသတင်း
        /articles                  ဆောင်းပါး
        /perspective               အယ်ဒီတာ့အာဘော်
        /news                      သတင်းများ

    Three corrections to what was previously believed, each measured:

    * **`/other-news` is ပြည်တွင်းသတင်း, not အခြားသတင်း.** The site's own title
      says so. The old label was a guess that survived into the tool description.
    * **The site DOES have ဆောင်းပါး and အယ်ဒီတာ့အာဘော် sections** (`/articles`,
      `/perspective`). An earlier note concluded it had no section for the topics;
      that was wrong for these two.
    * **`/amyotha-hluttaw-news` — the spelling in the site's own nav — is a dead
      link (0 bytes).** The working slug is `/amyotha-htuttaw-news`. Measured both.

THE THREE CARD LAYOUTS, AND WHY THE OLD PATTERN MISSED TWO SECTIONS

    The site renders article cards in **three different shapes**:

    A. `card mb-3 shadow` → `card-body` → `card-title` → `card-text`
       (the offices, the hluttaws, `/news`, `/other-news`)
    B. `news-page` → `news-wrapper` → `news-title` → `news-content`
       (`/articles`, `/perspective`) — the link is `/article/N` on one and
       `/news/N` on the other

    The old single pattern required `href="/news/N"` and exactly
    `class="card-text"`. Two measured consequences:

    * `/other-news` and `/news` serve their links as **`/index.php/news/N`**, and
      their summary as `class="card-text text-justify"`. The pattern matched
      **0 of 20 cards**, so `list_section("other-news")` returned `[]` — and the
      tool then told the owner there was no such news. **A section with news
      dated today was answered as "not found".**
    * `/articles` and `/perspective` use layout B entirely and were invisible.

THE NETWORK, WHICH IS THE ONE REAL HAZARD

    Measured 2026-10-01: the route to this site is sometimes fine and sometimes
    not, and when it is not, the working path is the machine's own VPN proxy
    (`127.0.0.1:10809`). Rather than require an environment variable to be set,
    the client **probes for a route once and remembers it** — direct first, then
    the common local proxy ports. A live reader that silently fails because a
    variable was not exported is worse than no reader.
"""
from __future__ import annotations

import html
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

BASE = "https://www.moi.gov.mm"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; MarkLIV/1.0)"}
_TIMEOUT = 25
_PAUSE = 0.3            # polite to a government site
_CACHE_TTL = 900        # 15 minutes — a live reader, not a mirror

# Tried in order, once, and the first that answers is kept. `None` is a direct
# connection. Measured 2026-10-01: when the direct route to Cloudflare's ranges
# is blocked, `10809` is the machine's VPN and it works.
_ROUTES: tuple[str | None, ...] = (
    None, "http://127.0.0.1:10809", "http://127.0.0.1:7890", "http://127.0.0.1:8080",
)

_route: str | None = None
_route_tried = False
_cache: dict = {}
_lock = threading.Lock()

# The publisher's sections, with the publisher's own labels (read from each
# page's `<title>`, 2026-10-01). `""` as the category means "the section is not a
# category" — the VP section holds both officeholders and is split by name.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("president-news", "နိုင်ငံတော်သမ္မတ", "နိုင်ငံတော်သမ္မတ"),
    ("vice-presidents-news", "ဒုတိယသမ္မတသတင်းများ", ""),
    ("hluttaw-news", "လွှတ်တော်သတင်း", "လွှတ်တော်"),
    ("pyidaungsu-hluttaw-news", "ပြည်ထောင်စုလွှတ်တော်", "ပြည်ထောင်စုလွှတ်တော်"),
    ("pyithu-htuttaw-news", "ပြည်သူ့လွှတ်တော်", "ပြည်သူ့လွှတ်တော်"),
    ("amyotha-htuttaw-news", "အမျိုးသားလွှတ်တော်", "အမျိုးသားလွှတ်တော်"),
    ("commander-in-chief-news", "တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်သတင်း", "အခြား"),
    ("other-news", "ပြည်တွင်းသတင်း", "အခြား"),
    ("articles", "ဆောင်းပါး", "ဆောင်းပါး"),
    ("perspective", "အယ်ဒီတာ့အာဘော်", "အယ်ဒီတာ့အာဘော်"),
    ("news", "သတင်းများ", "အခြား"),
)
SECTION_LABEL = {slug: label for slug, label, _cat in SECTIONS}
SECTION_CATEGORY = {slug: cat for slug, _label, cat in SECTIONS}

# Sections rendered with layout B. Everything else uses layout A. Kept as a
# separate set rather than a fourth tuple field so the existing
# `for slug, label, cat in SECTIONS` unpacks keep working.
_LAYOUT_B = frozenset({"articles", "perspective"})

# `/news` is the superset of every other section, so searching it as well as the
# rest returns the same story twice.
_SUPERSET = "news"

# What the owner might call a section. **A longer alias is always tested before a
# shorter one it contains** — `ဒုတိယသမ္မတ` before `သမ္မတ`, and all three hluttaw
# names before the bare `လွှတ်တော်`, or a VP question reads the president's
# section and an amyotha question reads the combined hluttaw one.
_ALIASES: tuple[tuple[str, str], ...] = (
    ("ဒုတိယသမ္မတ", "vice-presidents-news"),
    ("ပြည်ထောင်စုလွှတ်တော်", "pyidaungsu-hluttaw-news"),
    ("အမျိုးသားလွှတ်တော်", "amyotha-htuttaw-news"),
    ("ပြည်သူ့လွှတ်တော်", "pyithu-htuttaw-news"),
    ("အယ်ဒီတာ့အာဘော်", "perspective"),
    ("ဆောင်းပါး", "articles"),
    ("ပြည်တွင်းသတင်း", "other-news"),
    ("နိုင်ငံတော်သမ္မတ", "president-news"),
    ("ကာကွယ်ရေးဦးစီးချုပ်", "commander-in-chief-news"),
    ("တပ်မတော်", "commander-in-chief-news"),
    ("လွှတ်တော်", "hluttaw-news"),         # must follow the three named hluttaws
    ("သမ္မတ", "president-news"),           # must follow နိုင်ငံတော်သမ္မတ / ဒုတိယသမ္မတ
)

# ── Layout A: `card-body` (the offices, the hluttaws, /news, /other-news) ──────
# Two things the old pattern got wrong, both measured: `/other-news` and `/news`
# serve `href="/index.php/news/N"`, and their summary is
# `class="card-text text-justify"`. Requiring `href="/news/N"` and exactly
# `class="card-text"` matched 0 of 20 cards and the section was reported empty.
_CARD_A = re.compile(
    r'href="(?:/index\.php)?(/news/(\d+))"[^>]*>\s*<img.*?</a>\s*</div>\s*<div[^>]*>\s*'
    r'<div class="card-body">\s*<div class="card-title[^"]*"><h2><a[^>]*>(?P<head>.*?)</a>'
    r'</h2></div>\s*<p[^>]*>.*?</i>\s*(?P<date>[A-Za-z]{3}\s+\d{1,2},\s+\d{4})</p>'
    r'\s*<p class="card-text[^"]*">(?P<summary>.*?)</p>', re.S)

# ── Layout B: `news-wrapper` (/articles, /perspective) ───────────────────────
# The date comes BEFORE the title here, and the link is `/article/N` on
# `/articles` but `/news/N` on `/perspective` — so both are accepted.
_CARD_B = re.compile(
    r'<div class="news-wrapper">\s*<i[^>]*></i>\s*(?P<date>[A-Za-z]{3}\s+\d{1,2},\s+\d{4})'
    r'\s*<div class="news-title"><h2><a href="(?:/index\.php)?(?P<url>/(?:news|article)/\d+)"'
    r'[^>]*>(?P<head>.*?)</a></h2></div>'
    r'.*?<div class="[^"]*news-content[^"]*">\s*<div[^>]*>(?P<summary>.*?)</div>', re.S)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}


def _fetch(path: str, tries: int = 3) -> str:
    """GET a page, retrying and, if the route is unproven, probing for one.

    Returns `""` for a 404 — the page does not exist — and **raises** when the
    site cannot be reached at all. The two are different answers and the caller
    is expected to tell them apart.
    """
    global _route, _route_tried
    url = path if path.startswith("http") else BASE + path
    routes = (_route,) if _route_tried else _ROUTES
    last = None
    for attempt in range(tries):
        for candidate in routes:
            handlers = []
            if candidate:
                handlers.append(urllib.request.ProxyHandler(
                    {"http": candidate, "https": candidate}))
            else:
                # `None` means direct: an empty handler map defeats any proxy
                # the environment has set, which is the point of probing.
                handlers.append(urllib.request.ProxyHandler({}))
            opener = urllib.request.build_opener(*handlers)
            try:
                with opener.open(urllib.request.Request(url, headers=_UA),
                                 timeout=_TIMEOUT) as fh:
                    body = fh.read().decode("utf-8", "ignore")
                if not _route_tried or _route != candidate:
                    _route, _route_tried = candidate, True
                return body
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return ""
                last = e
                if candidate is None and e.code in (500, 502, 503, 504):
                    break
            except Exception as e:                          # noqa: BLE001
                last = e
        if _route_tried:
            _route_tried = False
            routes = _ROUTES
        time.sleep(1.5)
    raise last if last else RuntimeError("unreachable")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _div_inner(doc: str, start: int) -> str:
    """The inner HTML of the `<div>` whose opening tag begins at `start`.

    Balanced, so a nested `<div>` does not cut the body short. The obvious
    `<div class="X">(.*?)</div>` is non-greedy and stops at the **first** nested
    close, so everything after the first nested element is silently lost:
    measured on `<div class="post-body"><div>ONE</div><div>TWO</div></div>`, the
    lazy form returns `ONE` and drops `TWO`. On the live site the article body
    contains nested `<div>`s and `<p>`s, so the lazy form is not usable.
    """
    open_end = doc.find(">", start)
    if open_end < 0:
        return ""
    depth = 1
    rest = doc[open_end + 1:]
    for m in re.finditer(r"<div\b[^>]*>|</div\s*>", rest, re.I):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return rest[:m.start()]
        else:
            depth += 1
    return rest


def _iso(date_text: str) -> str:
    m = re.match(r"([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})", (date_text or "").strip())
    if not m or m.group(1) not in _MONTHS:
        return ""
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _cards(doc: str, section: str) -> list[dict]:
    """Every card on one list page, in whichever layout the section uses."""
    pattern = _CARD_B if section in _LAYOUT_B else _CARD_A
    out = []
    for m in pattern.finditer(doc):
        g = m.groupdict()
        # Layout A captures the href as groups 1–2; layout B captures it as the
        # named group `url` and has no unnamed groups at all. Reading `m.group(2)`
        # for both would hand layout B's *date* back as the article id.
        url = g.get("url") or (m.group(1) if m.groups() else "")
        idm = re.search(r"/(\d+)$", url or "")
        out.append({
            "id": idm.group(1) if idm else "",
            "url": url,
            "headline": _text(g.get("head") or ""),
            "issue_date": _iso(g.get("date", "")),
            "summary": _text(g.get("summary") or ""),
            "section": section,
            "section_label": SECTION_LABEL.get(section, section),
            "category": SECTION_CATEGORY.get(section, ""),
        })
    return out


def _cached(key, produce, default):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
    try:
        value = produce()
    except Exception as e:                                  # noqa: BLE001
        print(f"[MOI] {key} failed: {type(e).__name__}: {e}")
        return default
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def available() -> tuple[bool, str]:
    """(reachable, why not). Probes a few sections and remembers the route."""
    def produce():
        # More than one section is asked; the first that answers wins. Measured
        # 2026-10-17: /president-news answered 503 while /news, /other-news and
        # the hluttaw sections served 20 cards each. This probe's answer decides
        # whether MOI is offered at all, so one flaky section read as "the whole
        # site is down" and every MOI section was skipped from the briefing.
        # tries=1 keeps the fallback cheap — a 503 still costs about a second,
        # not the 25s read timeout. Returning (not raising) also lets the
        # negative be cached, so an outage is paid once per TTL, not per call.
        for probe in ("/news", "/other-news", "/president-news"):
            try:
                doc = _fetch(probe, tries=1)
            except Exception:
                continue
            if doc and "/news/" in doc:
                return True
        return False
    ok = _cached("probe", produce, False)
    if ok:
        return True, ""
    return False, (f"moi.gov.mm ကို မချိတ်နိုင်ပါ"
                   f"{f' (route: {_route})' if _route else ''}")


def route() -> str:
    """Which route answered — '' for direct, otherwise the proxy. For reporting."""
    return _route or "direct"


def list_section(section: str, pages: int = 20, until: str = "") -> list[dict]:
    """Every card in a section, newest first. `[]` when unreachable.

    **`until` stops the walk early.** Cards come newest-first, so once one is
    older than `until` the rest of that page and every later page are too.
    Measured 2026-10-01 in a live session: asked for one day's president news,
    the tool walked all 20 pages anyway (~20 s), the model was left waiting, and
    the turn died before it could speak. With `until` the same question is one or
    two pages. It is a *bound*, not a filter — the caller still filters, so a
    wrong `until` costs time rather than correctness.
    """
    def produce():
        out, seen = [], set()
        for page in range(pages):
            doc = _fetch(f"/{section}?page={page}")
            if not doc:
                break
            found = _cards(doc, section)
            if not found:
                break
            new, passed = 0, False
            for card in found:
                if card["id"] in seen:
                    continue
                seen.add(card["id"])
                new += 1
                out.append(card)
                if until and card["issue_date"] and card["issue_date"] < until:
                    passed = True
            if not new:
                break
            if passed:
                break
            time.sleep(_PAUSE)
        return out
    return _cached(f"list:{section}:{pages}:{until}", produce, [])


def section_exists(section: str) -> bool:
    """Does the site serve this section at all?

    Measured 2026-10-01: `/amyotha-hluttaw-news` — the spelling in the site's own
    navigation — returns **0 bytes**, while `/amyotha-htuttaw-news` returns 20
    cards. A dead slug and an empty section are different answers, and only this
    tells them apart: otherwise the owner is told a section holds no news when
    the real answer is that the section is not there.
    """
    def produce():
        return bool(_fetch(f"/{section}", tries=2))
    return _cached(f"exists:{section}", produce, False)


# Every container the site puts an article's text in, tried in order. Each one
# was added because a real page returned nothing under the others — see
# `article()`. A module-level tuple rather than inline literals so `check_moi.py`
# can assert the set, and so the next page type has one obvious place to go.
_BODY_CONTAINERS: tuple[str, ...] = (
    r'<div class="post-body">',                                    # /news/N
    r'<div[^>]*property="schema:text"[^>]*>',                      # /article/N
    r'<div[^>]*field--name-field-president-speech-body[^>]*>',     # /president-speech/N
)


def _read_body(doc: str) -> tuple[str, bool]:
    """`(text, container_matched)`. The two are different facts.

    A container that matched but came back empty means **the publisher put
    nothing there** — `/news/88750` is such an article, the headline being the
    whole story. No container matching means **we could not read it**, which is
    about us, not about the site. Collapsing the two is how a read failure
    becomes a false claim about the publisher.
    """
    cut = re.sub(r"<script.*?</script>|<style.*?</style>", "", doc, flags=re.S)
    for pat in _BODY_CONTAINERS:
        m = re.search(pat, cut)
        if m:
            return _text(_div_inner(cut, m.start())), True
    return "", False


def article_page(url: str) -> dict:
    """One fetch of an article page → `{"state","text","date","author","matched"}`.

    WHY ONE FUNCTION AND NOT FOUR

        `article()`, `article_state()`, `article_meta()` and `article_date()` all
        read the **same page**, and each used to fetch it separately. The crawler
        in `core/moi_index.py` needs the text, the date *and* the author of every
        new article in one pass, so per-field fetches would have tripled the
        requests made to a government site. The four public readers are now thin
        views over this single cached fetch.

    THE THREE CONTAINERS, BECAUSE THE SITE USES THREE

        Each was found by a page that returned nothing under the others:

        `/news/N`              `post-body`
        `/article/N`           the `field--name-body` div carrying
                               `property="schema:text"` — **no `post-body` at all**
        `/president-speech/N`  `field--name-field-president-speech-body` —
                               **neither of the other two**, and all seven of its
                               `field--name-body` divs are site chrome (mobile-app
                               links, footer, copyright)

    Measured 2026-10-03: with only the first two, every `/president-speech/N` page
    read as empty — including the president's own address at the India Business
    Dialogue — and the tool told the owner the site had published no text for it.

    Three wrong answers came before the first of these and each returned something
    plausible: a `dd/mm/yyyy` anchor returned the latest-news *sidebar* for an
    article whose markup has no such date; `field--name-body` occurs **8 times** on
    a news page, seven of them site blocks; and `node__content` is empty.

    **Some articles genuinely have no body** — `/news/88750` (1 Oct) has an empty
    `field--name-body`, because the headline *is* the content. `state` is `empty`
    for those and `unreadable` when no known container matched, which the caller
    must tell apart because only one of them is a claim about the site.
    """
    def produce():
        try:
            doc = _fetch(url)
        except Exception:                                   # noqa: BLE001
            return {"state": "unreadable", "text": "", "matched": False,
                    "date": "", "author": ""}
        if not doc:
            return {"state": "missing", "text": "", "matched": False,
                    "date": "", "author": ""}
        text, matched = _read_body(doc)
        meta = _page_meta(doc)
        return {"state": ("ok" if text else "empty" if matched else "unreadable"),
                "text": text, "matched": matched, **meta}
    return _cached(f"page:{url}", produce,
                   {"state": "unreadable", "text": "", "matched": False,
                    "date": "", "author": ""})


def article(url: str) -> str:
    """An article's own text, or "" when the page carries none.

    A thin view over `article_page`, which documents the three containers and the
    `state` values. An unreachable page returns `""` here rather than raising, so
    a network fault can never crash a voice turn — the caller reads
    `article_state()` to say which of the four things happened.
    """
    return article_page(url)["text"]


def _page_meta(doc: str) -> dict:
    """`{"date","author"}` read out of an article page already in hand.

    Split out of `article_page` so the page is fetched **once**: the date and the
    author live in the same HTML as the body.

    The date appears in one of two shapes — measured 2026-10-03:

        `<span class="post-created">10/01/2026</span>`   **month first**
        `Submitted by moiuser4 on 31 May 2026`           `/president-speech/N`

    The first is MM/DD/YYYY, **not** the D-M-YYYY the newspaper URLs use, which is
    why it is parsed here rather than assumed.

    The author is best-effort and `""` is the honest common answer. Measured
    2026-10-03: a state news page carries **no byline field**; the only
    name-shaped string on it is Drupal's `Submitted by moiuser4`, a **machine
    account, not a journalist**. Storing `moiuser4` as the author of the
    president's news would be a fabricated attribution, so an account of that
    shape is refused and the column stays empty. A real `Submitted by` name or a
    `<meta name="author">` is kept.
    """
    date = ""
    m = re.search(r'class="post-created">\s*(\d{1,2})/(\d{1,2})/(\d{4})', doc)
    if m:
        date = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    else:
        m = re.search(
            r"Submitted by\s+\S+\s+on\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", doc)
        if m and m.group(2) in _MONTHS:
            date = f"{m.group(3)}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    author = ""
    m = re.search(r'<meta\s+name="author"\s+content="([^"]{1,80})"', doc)
    if m:
        author = _text(m.group(1))
    else:
        # A submission account (`moiuser4`, `ppibuser2`, …) is not a byline.
        m = re.search(r"Submitted by\s+([^\s<]{2,40})\s+on\s+", doc)
        if m and not re.fullmatch(r"[a-z]{2,12}user\d{1,4}", m.group(1)):
            author = m.group(1)
    return {"date": date, "author": author}


def article_state(url: str) -> str:
    """`"ok"` | `"missing"` | `"empty"` | `"unreadable"` — what happened.

    **A failed read is not an empty source.** `article()` returns `""` for three
    different situations, and the caller was collapsing them into one claim about
    the *website*. Measured 2026-10-03: a `/president-speech/N` page whose text
    lived in a container we did not know was reported as *"the site gives no text
    for this story"* — a false statement about the publisher, on a page holding
    20,975 characters of the president's own speech.

        ok          text was read
        missing     the page is not there (404)
        empty       the page is there, its container is there, and the publisher
                    put nothing in it — a claim about the SITE, and a fair one
        unreadable  the page is there and no known container matched — about US

    Only `missing` and `empty` justify a claim about the site. A thin view over
    `article_page`, so this costs no extra request.
    """
    return article_page(url)["state"]


# One result on `/search/node`. The site's own search — relevance-ranked, and
# it covers the WHOLE archive, which walking section pages cannot.
_SEARCH_ITEM = re.compile(
    r'<h3>\s*<a href="(?:https?://www\.moi\.gov\.mm)?(?P<url>/[^"]+)"[^>]*>'
    r'(?P<head>.*?)</a>\s*</h3>\s*<p>(?P<snippet>.*?)</p>', re.S)


def search_site(term: str, pages: int = 2, limit: int = 20) -> list[dict]:
    """The site's OWN search, `/search/node?keys=`. `[]` when unreachable.

    **This replaced walking section pages, and the reason is measured.**
    2026-10-03, asked to summarise the president's trip to India: the page-walk
    search was bounded at 4 pages per section (round 24, for latency), so the
    president section only reached back to **2026-08-23** while the trip is
    **2026-05-28 → 06-03**. It returned nine articles and **not one of them was
    the trip** — a silent wrong answer, the worst kind. The same question against
    `/search/node?keys=` finds the trip's articles immediately, including
    `/president-speech/83411`, and paginates at 10 a page.

    So this is **one request per page instead of up to twenty per section**, it
    is relevance-ranked, and it reaches the whole archive. What it does NOT carry
    is a date — the result list has only a headline and a snippet — so
    `issue_date` is `""` here and the caller must not claim one. `article_date()`
    reads the real date off the article page.
    """
    def produce():
        out, seen = [], set()
        for page in range(max(1, pages)):
            doc = _fetch(f"/search/node?keys={quote(term)}&page={page}")
            if not doc:
                break
            found = list(_SEARCH_ITEM.finditer(doc))
            if not found:
                break
            new = 0
            for m in found:
                url = m.group("url")
                if url in seen:
                    continue
                seen.add(url)
                new += 1
                idm = re.search(r"/(\d+)$", url)
                out.append({
                    "id": idm.group(1) if idm else "",
                    "url": url,
                    "headline": _text(m.group("head")),
                    "issue_date": "",
                    "summary": _text(m.group("snippet")),
                    "section": "",
                    "section_label": "moi.gov.mm ရှာဖွေမှု",
                    "category": "",
                })
            if not new:
                break
            time.sleep(_PAUSE)
        return out[:limit]
    return _cached(f"site:{term}:{pages}:{limit}", produce, [])


def article_meta(url: str) -> dict:
    """`{"date": YYYY-MM-DD, "author": ...}` — what the article page states.

    A thin view over `article_page` (one cached fetch shared with `article`,
    `article_state` and `article_date`); the four states it can return and why
    the author is usually empty are documented at `_page_meta`. `core/moi_index.py`
    is the second caller — it stores a date and an author per indexed article.
    """
    page = article_page(url)
    return {"date": page.get("date", ""), "author": page.get("author", "")}


def article_date(url: str) -> str:
    """The article's own date as YYYY-MM-DD, or "".

    Delegates to `article_page`, so the page's date is parsed once — see
    `_page_meta` for the two shapes it appears in and why it is not guessed.
    """
    return article_page(url).get("date", "")


def resolve_section(name: str) -> str:
    """What the owner said → a section slug, or "" when it is not a section."""
    text = re.sub(r"\s+", "", name or "")
    if not text:
        return ""
    for slug, label, _cat in SECTIONS:
        if re.sub(r"\s+", "", label) == text or slug == name.strip():
            return slug
    for alias, slug in _ALIASES:
        if alias in text:
            return slug
    return ""


def search(term: str, sections: tuple[str, ...] = (), pages: int = 20,
           limit: int = 12) -> list[dict]:
    """Cards whose headline or summary contains `term`, newest first.

    The site has no search endpoint that returns what is needed here, so the
    sections are walked and filtered locally. Only the sections that could
    contain the term are walked when the caller narrows them.

    `/news` is the superset of the rest, so it is skipped by default — walking it
    as well as the others returns the same story twice. Hits are deduplicated on
    the article id for the same reason: one story is often filed under a section
    *and* under the combined hluttaw list.
    """
    wanted = sections or tuple(s for s, _l, _c in SECTIONS if s != _SUPERSET)
    needle = re.sub(r"\s+", "", term or "")
    if not needle:
        return []
    hits, seen = [], set()
    for slug in wanted:
        for card in list_section(slug, pages=pages):
            if card["id"] in seen:
                continue
            hay = re.sub(r"\s+", "", card["headline"] + " " + card["summary"])
            if needle in hay:
                seen.add(card["id"])
                hits.append(card)
    hits.sort(key=lambda c: c.get("issue_date") or "", reverse=True)
    return hits[:limit]


def reset() -> None:
    """Drop the cache and the remembered route. Used by the checks."""
    global _route, _route_tried
    with _lock:
        _cache.clear()
    _route, _route_tried = None, False
