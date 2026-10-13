# actions/web_search.py
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from core import timefmt

_QUOTA_COOLDOWN_SEC = 900
_quota_blocked_until = 0.0
_quota_lock = threading.Lock()

_SCRAPE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_REQUEST_TIMEOUT = 8.0
_TAG_CLEANER = re.compile(r"<[^>]+>")
_HEADLINE_MIN = 20
_GENERAL_SEARCH_LIMIT = 8
_SEARCH_TIMEOUT = 10.0

# ── ၁။ သတင်းဌာနများ REGISTRY (သီးသန့်ခွဲထုတ်ယူရန်နှင့် Briefing အတွက်) ───────────
OUTLET_REGISTRY = {
    "bbc_burmese": {
        "name": "BBC Burmese (ဘီဘီစီ မြန်မာပိုင်း)",
        "aliases": ("bbc burmese", "ဘီဘီစီမြန်မာ", "ဘီဘီစီ", "bbc"),
        "type": "rss",
        "target": "https://feeds.bbci.co.uk/burmese/rss.xml",
        "scope": "myanmar",
    },
    "bbc_world": {
        "name": "BBC News (World)",
        "aliases": ("bbc world", "bbc news world", "ဘီဘီစီကမ္ဘာ့သတင်း", "ဘီဘီစီ အင်္ဂလိပ်"),
        "type": "google",
        "target": "site:bbc.com/news",
        "scope": "world",
    },
    "irrawaddy": {
        "name": "The Irrawaddy (ဧရာဝတီ)",
        "aliases": ("irrawaddy", "ဧရာဝတီ", "ဧရာဝတီသတင်း"),
        "type": "rss",
        "target": "https://burma.irrawaddy.com/feed",
        "scope": "myanmar",
    },
    "dvb": {
        "name": "DVB (ဒီဗွီဘီ)",
        "aliases": ("dvb", "ဒီဗွီဘီ", "ဒီမိုကရက်တစ်မြန်မာ့အသံ"),
        "type": "rss",
        "target": "https://burmese.dvb.no/feed",
        "scope": "myanmar",
    },
    "rfa": {
        "name": "RFA Burmese (လွတ်လပ်တဲ့အာရှအသံ)",
        "aliases": ("rfa", "အာရ်အက်ဖ်အေ", "လွတ်လပ်တဲ့အာရှအသံ"),
        "type": "rss",
        "target": "https://www.rfa.org/burmese/rss2.xml",
        "scope": "myanmar",
    },
    "gnlm": {
        "name": "Global New Light of Myanmar",
        "aliases": ("gnlm", "global new light", "မြန်မာ့အလင်း"),
        "type": "rss",
        "target": "https://www.gnlm.com.mm/feed",
        "scope": "myanmar",
    },
    "reuters": {
        "name": "Reuters (ရိုက်တာ)",
        "aliases": ("reuters", "ရိုက်တာ"),
        "type": "google",
        "target": "site:reuters.com",
        "scope": "world",
    },
    "ap": {
        "name": "Associated Press (AP)",
        "aliases": ("associated press", "ap news", "apnews", "အေပီ", "ap"),
        "type": "google",
        "target": "site:apnews.com",
        "scope": "world",
    },
    "ppib": {
        "name": "သမ္မတရုံး သတင်းနှင့် ပြန်ကြားရေးဗျူရို (PPIB)",
        "aliases": ("ppib", "သမ္မတရုံး", "ပြန်ကြားရေးဗျူရို", "နိုင်ငံတော်သမ္မတရုံး"),
        "type": "scrape",
        "target": "https://www.ppib.gov.mm/",
        "scope": "myanmar",
    },
    "moi": {
        "name": "ပြန်ကြားရေးဝန်ကြီးဌာန (MOI)",
        "aliases": ("moi", "ပြန်ကြားရေးဝန်ကြီးဌာန", "ပြန်ကြားရေး"),
        "type": "scrape",
        "target": "https://www.moi.gov.mm/index.php/president-news",
        "scope": "myanmar",
    },
}

# မေးခွန်းထဲမှ ဖယ်ထုတ်ရမည့် Filler / Command စကားလုံးများ
_FILLER_WORDS = frozenset((
    "သတင်း", "သတင်းများ", "သတင်းဌာန", "ဘာသတင်း", "ဘာသတင်းတွေ",
    "အသစ်", "အသစ်တက်လဲ", "အသစ်တွေ", "ဘာအသစ်ရှိလဲ", "အသစ်ရှိလား",
    "ဒီနေ့", "ယနေ့", "မနေ့က", "နောက်ဆုံး", "နောက်ဆုံးရ", "ဘာထူးလဲ",
    "ဘာရှိလဲ", "ပြောပြပါ", "ပြပါ", "ရှာပါ", "တင်ဆက်ပါ", "က", "မှာ",
    "news", "latest", "today", "headlines", "recent", "updates",
))

_SCRAPE_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SCRAPE_CACHE_TTL = 300.0
_SCRAPE_CACHE_LOCK = threading.Lock()
_SSL_INSECURE_HOSTS: set[str] = set()


def _clean_text(html_text: str) -> str:
    if not html_text:
        return ""
    text = _TAG_CLEANER.sub("", html_text)
    return " ".join(text.split())


def _parse_date(raw) -> float | None:
    if not raw:
        return None
    txt = str(raw).strip()
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(txt)
        except Exception:
            dt = None
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d %b %Y", "%B %d, %Y"):
                try:
                    dt = datetime.strptime(txt, fmt)
                    break
                except ValueError:
                    continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _date_label(raw) -> str:
    ts = _parse_date(raw)
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timefmt.MMT).strftime("%Y-%m-%d")


def _title_key(title: str) -> str:
    return re.sub(r"\s+", "", str(title or "")).lower()[:60]


# ── RSS / ATOM PARSER ────────────────────────────────────────────────────────
def _fetch_rss_feed(outlet_name: str, feed_url: str, limit: int = 8) -> list[dict]:
    items: list[dict] = []
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": _SCRAPE_UA})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            content = resp.read()

        root = ET.fromstring(content)

        # RSS 2.0
        channel_items = root.findall(".//item")
        if channel_items:
            for it in channel_items[:limit]:
                title = _clean_text(it.findtext("title") or "")
                link = (it.findtext("link") or "").strip()
                pub_date = (it.findtext("pubDate") or "").strip()
                desc = _clean_text(it.findtext("description") or "")

                if len(title) >= _HEADLINE_MIN:
                    items.append({
                        "title": title,
                        "snippet": desc[:140],
                        "url": link,
                        "source": outlet_name,
                        "date": pub_date,
                    })
            return items

        # Atom
        atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//atom:entry", atom_ns) or root.findall(".//entry")
        for entry in entries[:limit]:
            title_node = entry.find("atom:title", atom_ns) or entry.find("title")
            title = _clean_text(title_node.text if title_node is not None else "")

            link = ""
            for l in (entry.findall("atom:link", atom_ns) or entry.findall("link")):
                if l.get("rel") in ("alternate", None) and l.get("href"):
                    link = l.get("href")
                    break

            date_node = (
                entry.find("atom:published", atom_ns)
                or entry.find("published")
                or entry.find("atom:updated", atom_ns)
                or entry.find("updated")
            )
            pub_date = date_node.text.strip() if date_node is not None else ""

            if len(title) >= _HEADLINE_MIN:
                items.append({
                    "title": title,
                    "snippet": "",
                    "url": link,
                    "source": outlet_name,
                    "date": pub_date,
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ RSS fetch failed for {outlet_name}: {e}")

    return items


# ── GOOGLE NEWS RSS (WORLD NEWS / SPECIFIC OUTLET SEARCH) ─────────────────────
def _fetch_google_news(query: str, limit: int = 8) -> list[dict]:
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    )
    items = []
    # TWO ATTEMPTS INSIDE ONE BUDGET — the module had neither.
    # Measured 2026-09-27: these two wire queries answer in 2-4 s, and a first
    # attempt still came back `The read operation timed out` and the retry
    # answered immediately. The stall is transient, and with a single attempt
    # and no retry the whole world half went empty — so the user was told the
    # news could not be reached while the service was answering fine.
    #
    # The budget is for the CALL, not the attempt: the first attempt gets what
    # is left, the retry gets the remainder floored at 3 s, so the worst case is
    # `_REQUEST_TIMEOUT + 3` rather than a silent doubling of the wait.
    deadline = time.monotonic() + _REQUEST_TIMEOUT
    root = None
    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        budget = remaining if attempt == 1 else max(3.0, remaining)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _SCRAPE_UA})
            with urllib.request.urlopen(req, timeout=budget) as resp:
                root = ET.fromstring(resp.read())
            break
        except Exception as e:
            print(f"[WebSearch] ⚠️ Google News RSS {query!r} "
                  f"attempt {attempt}/2: {e}")
    if root is None:
        return items

    for it in root.findall(".//item")[:limit]:
        title = _clean_text(it.findtext("title") or "")
        src_el = it.find("source")
        src_name = (src_el.text or "").strip() if src_el is not None else "Google News"

        if src_name and title.endswith(f" - {src_name}"):
            title = title[: -(len(src_name) + 3)].strip()

        link = (it.findtext("link") or "").strip().split("?oc=")[0]
        pub_date = (it.findtext("pubDate") or "").strip()

        if len(title) >= _HEADLINE_MIN:
            items.append({
                "title": title,
                "snippet": "",
                "url": link,
                "source": src_name,
                "date": pub_date,
            })
    return items


# ── DIRECT HTML SCRAPING (PPIB / MOI) ─────────────────────────────────────────
def _scrape_listing(url: str, limit: int = 8) -> list[dict]:
    name = urlparse(url).netloc.replace("www.", "")

    with _SCRAPE_CACHE_LOCK:
        hit = _SCRAPE_CACHE.get(url)
        if hit and (time.monotonic() - hit[0]) < _SCRAPE_CACHE_TTL:
            return hit[1][:limit]

    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("[WebSearch] ⚠️ requests and beautifulsoup4 required")
        return []

    # SSL certificate verification ကို မပိတ်ပါ။ Certificate error ဖြစ်လျှင်
    # insecure fallback မလုပ်ဘဲ source တစ်ခုတည်းကို graceful failure လုပ်သည်။
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _SCRAPE_UA},
            timeout=10.0,
            verify=True,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[WebSearch] ⚠️ scrape failed for {name}: {e}")
        return []

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()

    for t in soup.find_all("time", datetime=True):
        parent = t.parent
        a = parent.find("a", href=True) if parent else None
        if a and len(a.get_text(strip=True)) >= _HEADLINE_MIN:
            t_txt = a.get_text(" ", strip=True)
            k = _title_key(t_txt)
            if k not in seen:
                seen.add(k)
                items.append({
                    "title": t_txt,
                    "snippet": "",
                    "url": urljoin(url, a["href"]),
                    "source": name,
                    "date": t["datetime"],
                })

    if not items:
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if len(text) >= _HEADLINE_MIN:
                k = _title_key(text)
                if k not in seen:
                    seen.add(k)
                    items.append({
                        "title": text,
                        "snippet": "",
                        "url": urljoin(url, a["href"]),
                        "source": name,
                        "date": "",
                    })

    if items:
        with _SCRAPE_CACHE_LOCK:
            _SCRAPE_CACHE[url] = (time.monotonic(), items)
    return items[:limit]


# ── GENERAL WEB SEARCH (DuckDuckGo HTML) ──────────────────────────────────────
def _unwrap_ddg(href: str) -> str:
    """A DuckDuckGo result link -> the page it actually points at.

    EVERY result on html.duckduckgo.com is wrapped:

        //duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FBangkok&rut=...

    which starts with "//" and not "http", so the "is this a real url" test in
    _fetch_web_search() rejected all ten results on the page and general search
    answered "no results found" for every query ever asked. Measured 2026-09-27:
    the page carried 10 `a.result__a` links and the function returned 0.

    Protocol-relative hrefs get a scheme, and the `uddg` parameter is the real
    destination. A link that is already absolute is passed through unchanged.
    """
    h = str(href or "").strip()
    if not h:
        return ""
    if h.startswith("//"):
        h = "https:" + h
    if "duckduckgo.com/l/" in h:
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(h).query)
            real = (query.get("uddg") or [""])[0]
            if real:
                return urllib.parse.unquote(real)
        except Exception:
            pass
    return h


def _fetch_web_search(query: str, limit: int = _GENERAL_SEARCH_LIMIT) -> list[dict]:
    """General web search. External search engine API key မလိုဘဲ DDG HTML ကိုသုံးသည်."""
    results: list[dict] = []
    if not query.strip():
        return results

    search_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({
        "q": query.strip(),
        "kl": "wt-wt",
    })

    try:
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": _SCRAPE_UA, "Accept-Language": "en-US,en;q=0.8"},
        )
        with urllib.request.urlopen(req, timeout=_SEARCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"[WebSearch] ⚠️ General search failed: {e}")
        return results
    except Exception as e:
        print(f"[WebSearch] ⚠️ General search unexpected error: {e}")
        return results

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[WebSearch] ⚠️ beautifulsoup4 required for general web search")
        return results

    soup = BeautifulSoup(html, "html.parser")
    seen_urls: set[str] = set()

    for item in soup.select(".result"):
        a = item.select_one("a.result__a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = _unwrap_ddg(a.get("href"))
        snippet_node = item.select_one(".result__snippet")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""

        if not title or not href or href in seen_urls:
            continue
        if not href.startswith(("http://", "https://")):
            continue

        seen_urls.add(href)
        results.append({
            "title": title,
            "snippet": snippet[:240],
            "url": href,
            "source": urlparse(href).netloc.replace("www.", ""),
            "date": "",
        })
        if len(results) >= limit:
            break

    return results


def _ddg_news(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo results for one topic — what the background topic monitor reads.

    WHY THIS NAME EXISTS AGAIN
        `actions/background_monitor.py::check_all()` does
        `from actions.web_search import _ddg_news` and nothing else from this
        module. When this file lost 69 of its 75 functions, the name went with
        them, so the import raised on every poll and main.py printed
        `[Monitor] ⚠️ Background check error: cannot import name '_ddg_news'`
        for the rest of the session — the monitor silently did nothing.

        It is a thin alias over `_fetch_web_search()`, which is the DDG
        fetcher that survived and already returns the shape `check_all()`
        reads (`title`, `url`, `source`). Nothing about routing or screening is
        restored by this — those stay gone on purpose.

    The results are ordinary web hits, not a news index: a topic whose top hit
    never changes (a Wikipedia page, an official site) will alert once and then
    stay quiet, which is the right behaviour for "tell me when something new
    appears" but not a substitute for the newsroom.
    """
    return _fetch_web_search(query, limit=max_results)


def _format_web_search_results(query: str, items: list[dict]) -> str:
    if not items:
        return f"'{query}' အတွက် web search result မတွေ့ရှိပါ။"

    lines = [f"[WEB SEARCH] {query}", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['title']}")
        if item.get("snippet"):
            lines.append(f"   {item['snippet']}")
        if item.get("source"):
            lines.append(f"   Source: {item['source']}")
        if item.get("url"):
            lines.append(f"   Link: {item['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── OUTLET DETECTION & DEDICATED FETCHING ─────────────────────────────────────
def _detect_outlet(query: str) -> tuple[dict | None, str]:
    """
    Query ထဲတွင် သတင်းဌာနအမည် ပါမပါ စစ်ဆေးပြီး သီးခြား outlet နှင့်
    ကျန်ရှိသော Subject ခေါင်းစဉ် (ရှိပါက) ကို ခွဲထုတ်ပေးသည်
    """
    q_lower = query.lower()

    # ရှည်လျားသော Alias များကို ဦးစားပေး ရှာဖွေနိုင်ရန် အလျားအလိုက် စီသည်
    matches = []
    for key, info in OUTLET_REGISTRY.items():
        for alias in info["aliases"]:
            alias_lower = alias.lower()
            if alias_lower.isascii():
                # Latin အမည်များအတွက် Boundary regex သုံးသည် (ဥပမာ- 'ap' မတော်တဆမငြိစေရန်)
                if re.search(rf"\b{re.escape(alias_lower)}\b", q_lower):
                    matches.append((len(alias_lower), key, info, alias_lower))
            else:
                if alias_lower in q_lower:
                    matches.append((len(alias_lower), key, info, alias_lower))

    if not matches:
        return None, query

    # အရှည်ဆုံး ကိုက်ညီသည့် Outlet ကို ရွေးချယ်သည်
    matches.sort(key=lambda x: x[0], reverse=True)
    _, _, best_outlet, matched_alias = matches[0]

    # Outlet အမည်နှင့် Filler စကားလုံးများကို query ထဲမှ ဖယ်ထုတ်ပြီး Subject သီးသန့် ယူသည်
    subject_raw = q_lower.replace(matched_alias, " ")
    tokens = subject_raw.split()
    clean_tokens = [w for w in tokens if w not in _FILLER_WORDS and len(w) > 1]
    subject = " ".join(clean_tokens).strip()

    return best_outlet, subject


def _fetch_single_outlet(outlet_info: dict, subject: str = "", limit: int = 6) -> list[dict]:
    """သတင်းဌာနတစ်ခုတည်းမှ သတင်းများကို တိုက်ရိုက်ဆွဲထုတ်သည်"""
    feed_type = outlet_info["type"]
    target = outlet_info["target"]
    name = outlet_info["name"]

    items: list[dict] = []

    if feed_type == "rss":
        items = _fetch_rss_feed(name, target, limit=limit * 2)
    elif feed_type == "google":
        search_q = f"{target} {subject}".strip() if subject else target
        items = _fetch_google_news(search_q, limit=limit)
    elif feed_type == "scrape":
        items = _scrape_listing(target, limit=limit * 2)

    # Subject ပါလာပါက token အလိုက် match လုပ်သည်။
    # Exact phrase မတွေ့ရုံနဲ့ result အားလုံးကို မပျောက်စေရန် fallback ထားသည်။
    if subject and items:
        subject_tokens = [t for t in re.split(r"\s+", subject.lower().strip()) if len(t) > 1]
        if subject_tokens:
            matched = []
            for it in items:
                haystack = (it.get("title", "") + " " + it.get("snippet", "")).lower()
                score = sum(1 for token in subject_tokens if token in haystack)
                if score:
                    it = dict(it)
                    it["_match_score"] = score
                    matched.append(it)
            if matched:
                items = sorted(matched, key=lambda x: x.get("_match_score", 0), reverse=True)

    # ရက်စွဲအလိုက် စီပြီး limit ဖြတ်သည်
    stamped = sorted(
        ((_parse_date(r.get("date")) or 0.0, r) for r in items),
        key=lambda x: x[0],
        reverse=True
    )
    return [r for _, r in stamped][:limit]


def _format_single_outlet_news(outlet_info: dict, items: list[dict], subject: str = "") -> str:
    """သတင်းဌာနတစ်ခုတည်းအတွက် သီးသန့် တင်ဆက်မှု ဖော်မတ်"""
    if not items:
        sub_txt = f" '{subject}' နှင့် ပတ်သက်သော" if subject else ""
        return f"{outlet_info['name']} တွင်{sub_txt} သတင်းအသစ် မတွေ့ရှိပါ။"

    today = timefmt.now_mmt().strftime("%Y-%m-%d")
    head = f"[{outlet_info['name']} မှ နောက်ဆုံးရသတင်းများ] (ယနေ့ရက်စွဲ: {today})"
    if subject:
        head += f" — ခေါင်းစဉ်: {subject}"

    lines = [head, ""]
    for i, r in enumerate(items, 1):
        when = _date_label(r.get("date"))
        stamp = f" ({when})" if when else ""
        lines.append(f"{i}. {r['title']}{stamp}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   Link: {r['url']}")
        lines.append("")

    lines.append(f"အထက်ပါ သတင်းများကို {outlet_info['name']} ၏ တိုက်ရိုက်ထုတ်လွှင့်ချက်မှ ထုတ်ယူတင်ပြထားပါသည်။")
    return "\n".join(lines).strip()


# ── THE WORLD HALF ───────────────────────────────────────────────────────────
# The newsroom (E:\AI_NEWSROOM) is Myanmar-only — PPIB, BBC Burmese and The
# Irrawaddy — so world news has always been this module's job. These are the two
# wires, and they are fetched through Google News RSS because that is the only
# route that answers from this machine. Measured 2026-09-27:
#
#   * Reuters retired its public RSS: feeds.reuters.com is dead, /rssFeed
#     answers 401, and /arc/outboundfeeds/rss/ answers 404. Its news sitemap
#     still works (50 urls) but the article pages return 401, so there is no
#     body text either.
#   * apnews.com answers 403 to every request — feed, hub and article alike.
#   * Google News RSS answers 200 for both, ~100 same-day items each, carrying
#     the headline, the outlet and the time. It does NOT carry article text, and
#     its link is a news.google.com redirect that does not decode to the real
#     url.
#
# That is why these two are read here and not collected by the newsroom: the
# newsroom's analyser writes a three-bullet summary from the article body and
# marks anything too short as `failed`, which is every headline-only row. A wire
# the newsroom cannot read is a wire it would only corrupt.
WORLD_QUERIES = (
    "site:reuters.com world",
    "site:apnews.com world news",
)

# The freshness promise the briefing makes about its own items. It used to be
# read by check_news.py; that script was retired to backup/check_news.py.unused
# on 2026-09-27 because the routing/screening layer it tested is not on any live
# path, so nothing reads this constant now — it is kept because the number is
# the promise, and the world half honours it.
DEFAULT_BRIEFING_FRESH_DAYS = 1


def _sort_items(items: list[dict], limit: int) -> list[dict]:
    """Newest first, one item per headline, capped.

    The dedup is on `_title_key`, not the url: Google News returns the same
    story under several near-identical headlines, and reading two of them out
    as two pieces of news is worse than reading one.
    """
    stamped = sorted(((_parse_date(r.get("date")) or 0.0, r) for r in items),
                     key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for _, r in stamped:
        k = _title_key(r.get("title"))
        if k and k in seen:
            continue
        seen.add(k)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _world_items(per_query: int = 3) -> list[dict]:
    """Reuters and AP headlines. Never raises — a failed wire returns nothing.

    One query failing must not empty the half: the two wires are independent,
    and on a bad network day one of them still answers.
    """
    out: list[dict] = []
    for q in WORLD_QUERIES:
        try:
            out.extend(_fetch_google_news(q, limit=per_query))
        except Exception as e:
            print(f"[WebSearch] ⚠️ world query failed ({q!r}): {e}")
    return out


def world_briefing(limit: int = 3) -> str:
    """The world half as spoken Burmese, or "" when nothing came back.

    Returns "" rather than an apology so the caller can decide what to say —
    daily_briefing appends this to the newsroom's answer and must not turn a
    thin world day into a sentence about the internet.
    """
    items = _sort_items(_world_items(), limit)
    if not items:
        return ""
    lines = [f"ကမ္ဘာ့သတင်း {timefmt.to_burmese_digits(len(items))} ပုဒ် —"]
    for i, r in enumerate(items, 1):
        when = _date_label(r.get("date"))
        src = r.get("source") or ""
        stamp = f"  ({when})" if when else ""
        lines.append(f"{timefmt.to_burmese_digits(i)}။ {r.get('title', '')}"
                     + (f" [{src}]" if src else "") + stamp)
    return "\n".join(lines)


# ── MAIN NEWS & BRIEFING HANDLER ─────────────────────────────────────────────
def _news(query: str) -> str:
    # ၁။ သီးခြား Outlet တစ်ခုခုကို မေးထားခြင်း ဟုတ်/မဟုတ် စစ်ဆေးခြင်း
    outlet_info, subject = _detect_outlet(query)
    if outlet_info:
        print(f"[WebSearch] 🎯 Specific outlet detected: {outlet_info['name']} (Subject: {subject!r})")
        try:
            items = _fetch_single_outlet(outlet_info, subject=subject, limit=6)
        except Exception as e:
            print(f"[WebSearch] ⚠️ Specific outlet failed: {e}")
            items = []
        return _format_single_outlet_news(outlet_info, items, subject=subject)

    # ၂။ သီးခြား Outlet မဟုတ်ပါက ပုံမှန် Daily Briefing ပုံစံဖြင့် ကမ္ဘာ/မြန်မာ ပေါင်းစပ်ထုတ်ယူခြင်း
    from concurrent.futures import ThreadPoolExecutor

    def _safe_call(label, fn):
        try:
            return fn()
        except Exception as e:
            print(f"[WebSearch] ⚠️ {label} failed: {e}")
            return []

    def _get_world():
        # One implementation of the world half, shared with world_briefing().
        # Two copies of "which wires, how many from each" drift apart, and then
        # the daily briefing and the world answer disagree about what the world
        # news is — while both sound confident.
        return _safe_call("world wires", lambda: _world_items())

    def _get_myanmar():
        results = []
        # Direct RSS သတင်းဌာနများ (Irrawaddy, DVB, RFA, BBC Burmese, GNLM)
        rss_targets = [info for info in OUTLET_REGISTRY.values() if info["type"] == "rss"]
        for info in rss_targets:
            results.extend(_safe_call(
                info["name"],
                lambda info=info: _fetch_rss_feed(info["name"], info["target"], limit=2),
            ))
        # PPIB Scrape
        results.extend(_safe_call(
            "PPIB",
            lambda: _scrape_listing("https://www.ppib.gov.mm/", limit=2),
        ))
        return results

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_world = pool.submit(_get_world)
        f_mm = pool.submit(_get_myanmar)
        world_raw = f_world.result()
        mm_raw = f_mm.result()

    # ရက်စွဲစီခြင်းနှင့် Formatting
    def _sort(lst, n):
        stamped = sorted(((_parse_date(r.get("date")) or 0.0, r) for r in lst), key=lambda x: x[0], reverse=True)
        seen = set()
        out = []
        for _, r in stamped:
            k = _title_key(r.get("title"))
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out[:n]

    world = _sort(world_raw, 2)
    myanmar = _sort(mm_raw, 3)

    today = timefmt.now_mmt().strftime("%Y-%m-%d")
    lines = [f"[DAILY BRIEFING] ယနေ့ရက်စွဲ: {today}", "", "=== ကမ္ဘာ့သတင်း ==="]
    for i, r in enumerate(world, 1):
        when = _date_label(r.get("date"))
        lines.append(f"{i}. {r['title']} [{r['source']}]{f' ({when})' if when else ''}")
    lines += ["", "=== မြန်မာနိုင်ငံသတင်း ==="]
    for i, r in enumerate(myanmar, 1):
        when = _date_label(r.get("date"))
        lines.append(f"{i}. {r['title']} [{r['source']}]{f' ({when})' if when else ''}")

    return "\n".join(lines).strip()


def web_search(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    query = params.get("query", "").strip()
    mode = params.get("mode", "search").lower().strip()

    if not query:
        return "ကျေးဇူးပြု၍ ရှာဖွေလိုသော အကြောင်းအရာကို ထည့်သွင်းပေးပါ။"

    print(f"[WebSearch] 🔍 mode={mode!r} query={query!r}")

    # မေးခွန်းထဲတွင် သတင်း သို့မဟုတ် သတင်းဌာန နာမည်ပါလာပါက mode='news' အဖြစ် အလိုအလျောက် သတ်မှတ်ခြင်း
    outlet_info, _ = _detect_outlet(query)
    if mode == "news" or outlet_info or any(w in query for w in ("သတင်း", "news", "ဘာထူးလဲ")):
        return _news(query)

    # အခြား ပုံမှန်ရှာဖွေမှုများအတွက်
    # THE GENERAL-SEARCH BRANCH WAS A PLACEHOLDER. It read
    #     return f"Search result for: {query}"
    # which is not a search: the model was handed the user's own words back and
    # no result, so an ordinary question got an answer that looked like a
    # citation of nothing. The fetcher and the formatter for this were both
    # still present and unused.
    try:
        items = _fetch_web_search(query, limit=_GENERAL_SEARCH_LIMIT)
    except Exception as e:
        print(f"[WebSearch] ⚠️ general search failed: {e}")
        items = []
    return _format_web_search_results(query, items)


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
# Without this dict the loader registers NOTHING: core/action_loader.py reads
# `module.TOOL`, and a module without one is skipped in silence. That is why
# check_startup.py reported `MISSING web_search` while the file sat there
# looking healthy, and why daily_briefing's open-web fallback could never load.
TOOL = {
    "name": "web_search",
    "description": (
        "Search the open web, and read the WORLD news wires. Two uses.\n"
        "\n"
        "1. WORLD NEWS — Reuters and Associated Press headlines. Use this for "
        "anything outside Myanmar: 'ကမ္ဘာ့သတင်း ပြောပါ', 'နိုင်ငံတကာသတင်း', "
        "'world news', 'what is happening in the world', 'ရိုက်တာ သတင်း'. The "
        "newsroom monitors Myanmar outlets only, so world news comes from here "
        "and nowhere else. These are HEADLINES with no article body — report "
        "what the headline says and do not invent detail it does not contain.\n"
        "\n"
        "2. GENERAL SEARCH — an ordinary web search, for a fact, a definition, "
        "a price, or anything that is not news: 'ဒါ ဘာလဲ', 'search for X'. "
        "Pass mode='search' (the default); use mode='news' for the wires.\n"
        "\n"
        "DO NOT USE THIS FOR A NEWS QUESTION ABOUT WHAT IS HAPPENING. The user "
        "wants news from their three monitored outlets only — PPIB, BBC "
        "Burmese and The Irrawaddy — so 'ဒီနေ့ဘာထူးလဲ' and 'သတင်းဘာရှိလဲ' "
        "belong to daily_briefing, and 'သဘာဝဘေးသတင်းတွေ တက်လား', "
        "'ဒီအကြောင်းအရာ သတင်းရှိလား', 'is there any news about X' belong to "
        "newsroom_search. Reach for this module only when the user asks for "
        "WORLD news by name — 'ကမ္ဘာ့သတင်း ပြောပါ', 'နိုင်ငံတကာသတင်း', "
        "'world news' — or when the question is not about news at all.\n"
        "\n"
        "For MYANMAR news prefer daily_briefing, newsroom_outlet_news or "
        "newsroom_search — those are analysed and carry a summary, whereas this "
        "returns a headline and a link."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "What to search for, in the user's own words.",
            },
            "mode": {
                "type": "STRING",
                "description": ("'news' to read the news wires, 'search' for an "
                                "ordinary web search. Default 'search'."),
            },
        },
        "required": ["query"],
    },
    "handler": web_search,
}