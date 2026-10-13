"""Read any web page as clean Markdown — the reader other tools borrow.

WHY THIS EXISTS

    The assistant already searches (`web_search` → DDG) and lists headlines
    (`newsroom_*`, `moi_news`). What it could not do is READ the page a search
    returns: `_scrape_listing()` strips tags and keeps a flat text wall, and
    `browser_control`'s `get_text` returns the first 4000 characters of
    `inner_text("body")` — navigation, cookie banners, sidebars and all.

    This tool is the reader: fetch a URL, strip the page down to its main
    content, and return it as Markdown the model can quote from directly —
    headings kept, boilerplate gone, character budget enforced.

TWO ENGINES

    1. LOCAL (default, no account, no key)
       requests + BeautifulSoup. `readability-lxml` is used when installed for
       main-content extraction; without it, a scoring heuristic picks the
       densest text container and the rest of the page is dropped.

    2. FIRECRAWL (optional, key-gated)
       api.firecrawl.dev renders JavaScript and defeats bot-blocking before
       converting. Enabled only when config/api_keys.json carries
       "firecrawl_api_key". There is a free tier (500 credits); every scraped
       page costs 1 credit. When the key is absent the tool NEVER calls it and
       never mentions it — the owner decides whether to buy in.

FALLBACK LADDER

    local → firecrawl (if key) → playwright browser (already installed).
    JS pages fail locally; a Firecrawl key answers them; without a key the
    last resort is the real Chromium the assistant already drives.
    Within `local`, the fetch ladder is urllib → requests → curl_cffi
    (Chrome TLS fingerprint + DoH re-resolution) — see _fetch_local.

HONESTY

    A paywalled, blocked or empty page is reported as exactly that — the tool
    never pads an answer with navigation chrome and calls it content.
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 15.0
# The model quotes this into a spoken answer; 6000 chars ≈ a full-page read
# without swallowing the context window. `max_chars` can raise it, not lower.
_DEFAULT_CHARS = 6000
_MAX_CHARS = 20000

_FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# Elements that are chrome in every layout — dropped before scoring, so a
# cookie wall or a sidebar never wins the "densest container" contest.
_KILL_SELECTORS = (
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "iframe", "svg", "button", "select", "textarea",
    "[role=navigation]", "[role=banner]", "[role=complementary]",
    "[aria-hidden=true]", ".cookie", ".cookies", ".consent", ".newsletter",
    ".sidebar", ".advert", ".ad", ".social-share", ".related", ".comments",
    "#sidebar", "#nav", "#footer", "#header", "#cookie",
)


# ── key lookup ───────────────────────────────────────────────────────────────
def _firecrawl_key() -> str:
    """The Firecrawl key, or '' — absence is a normal state, not an error."""
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return str(json.load(f).get("firecrawl_api_key") or "")
    except Exception:                                       # noqa: BLE001
        return ""


# ── local engine ─────────────────────────────────────────────────────────────
def _html_to_markdown(soup) -> str:
    """A small, dependency-free HTML→Markdown converter for what survives.

    Handles headings, bold/italic, links, list items, paragraphs and block
    quotes. Everything else degrades to its text, which is the right default:
    the model reads prose, not layout.
    """
    def inline(node) -> str:
        out = []
        for child in node.children:
            name = getattr(child, "name", None)
            if name in ("strong", "b"):
                t = inline(child).strip()
                out.append(f"**{t}**" if t else "")
            elif name in ("em", "i"):
                t = inline(child).strip()
                out.append(f"*{t}*" if t else "")
            elif name == "a":
                href = child.get("href") or ""
                t = inline(child).strip()
                # Links kept only when they carry text — bare anchors are noise
                if t and href.startswith(("http://", "https://", "/")):
                    out.append(f"[{t}]({href})")
                elif t:
                    out.append(t)
            elif name == "br":
                out.append("\n")
            elif name is None:
                out.append(str(child))
            else:
                out.append(inline(child))
        return "".join(out)

    def block(node, depth: int = 0) -> list[str]:
        name = node.name
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            t = inline(node).strip()
            return [f"\n{'#' * level} {t}\n"] if t else []
        if name == "p":
            t = inline(node).strip()
            return [f"\n{t}\n"] if t else []
        if name == "ul":
            lines = [f"- {inline(li).strip().replace(chr(10), ' ')}"
                     for li in node.find_all("li", recursive=False)]
            return lines + [""]
        if name == "ol":
            lines = [f"{i}. {inline(li).strip().replace(chr(10), ' ')}"
                     for i, li in enumerate(node.find_all("li", recursive=False), 1)]
            return lines + [""]
        if name == "blockquote":
            t = inline(node).strip()
            return [f"\n> {t}\n"] if t else []
        if name == "table":
            return [f"\n{_table_to_md(node)}\n"]
        if name == "hr":
            return ["\n---\n"]
        # Container (div/section/article/…): recurse into children
        parts: list[str] = []
        for ch in node.find_all(recursive=False):
            parts.extend(block(ch))
        return parts

    lines: list[str] = []
    for top in soup.children:
        if getattr(top, "name", None):
            lines.extend(block(top))
        elif str(top).strip():
            lines.append(str(top).strip())
    # Collapse the blank-line storms the recursion leaves behind
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def _table_to_md(table) -> str:
    """A table → pipe rows. Not fancy; readable by both model and human."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    cols = rows[0].count("|") - 1
    rows.insert(1, "|" + "---|" * cols)
    return "\n".join(rows)


def _pick_main(soup):
    """The main-content container, by score or by readability.

    readability-lxml (optional dep, not installed here) does this properly;
    the fallback scores candidates by paragraph text density — the same idea,
    cruder.
    """
    best, best_score = None, 0.0
    for cand in soup.find_all(["article", "main", "div", "section"]):
        paras = cand.find_all("p")
        if not paras:
            continue
        text_len = sum(len(p.get_text(" ", strip=True)) for p in paras)
        # Density beats volume: a page-long nav with one <p> scores low
        score = text_len * (len(paras) ** 0.5)
        if score > best_score:
            best, best_score = cand, score
    if best is not None:
        return best
    return soup.body or soup


def _fetch_local(url: str) -> tuple[str, str]:
    """Fetch and convert. urllib first, requests as a courtesy fallback.

    WHY NOT requests FIRST
        Measured 2026-10-04 on this machine: requests' TLS handshake is
        rejected by several Myanmar news hosts (`gnlm.com.mm`,
        `burma.irrawaddy.com`) with SSLEOFError, while the same URLs answer
        200 through urllib — a local proxy/AV interception quirk, not the
        sites'. The standard library is also already every module's first
        tool (`web_search`, `weather_report`, `flight_finder`), so it stays
        the primary and `requests` only gets a turn if urllib itself fails.

    2026-10-05 UPDATE — the mirror image appeared: on a MyanmarNet egress,
    urllib AND requests both die with SSL EOF for hosts as central as
    google.com and generativelanguage.googleapis.com (the ISP's DPI resets
    the Python-OpenSSL TLS fingerprint), while curl_cffi impersonating a
    real Chrome handshake answers 200 first try. So the ladder grew a third
    rung: `_fetch_curl_cffi`, which is also the antidote for ISP DNS
    poisoning (some hosts return empty NOERROR from the resolver; DoH
    re-resolution sees them again).

    Returns (markdown, note).
    """
    html = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:                                  # noqa: BLE001
        print(f"[WebScraper] urllib failed ({type(e).__name__}) — trying requests")
        try:
            import requests
            resp = requests.get(url, headers={"User-Agent": _UA},
                                timeout=_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            html = resp.text
        except Exception as e2:                             # noqa: BLE001
            print("[WebScraper] requests failed — trying curl_cffi (chrome TLS)")
            try:
                html = _fetch_curl_cffi(url)
            except Exception as e3:                         # noqa: BLE001
                raise RuntimeError(
                    f"urllib: {e} · requests: {e2} · curl_cffi: {e3}") from e3

    if not (html or "").strip():
        return "", "page returned no content"

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "").strip()
    for sel in _KILL_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    main = _pick_main(soup)
    md = _html_to_markdown(main)
    if len(md) < 200:
        return "", ("extracted text too short — page is likely JavaScript-"
                    "rendered, paywalled, or an empty shell")
    return md, f"local fetch · title: {title}"


# ── curl_cffi engine (real-browser TLS fingerprint) ──────────────────────────
# 2026-10-05, MyanmarNet egress: python's OpenSSL fingerprint (urllib and
# requests alike) is reset mid-handshake by ISP DPI for hosts as central as
# google.com, while curl_cffi impersonating Chrome answers 200 first try.
# Separately, the ISP resolver blanks some hosts entirely (NOERROR with no
# answer from 1.1.1.1 and 8.8.8.8 alike) — so the ladder re-resolves through
# DoH. libcurl's DoH expects RFC 8484 wireformat endpoints (…/dns-query),
# NOT JSON APIs like 8.8.8.8/resolve.
_CFFI_DOH_URLS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/dns-query",
)


def _fetch_curl_cffi(url: str) -> str:
    """curl_cffi with a Chrome TLS fingerprint, then DoH re-resolution.

    Optional dependency - if curl_cffi is not installed this raises and the
    ladder's error message says so plainly. Returns raw HTML; raises
    RuntimeError once every attempt has failed.
    """
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        raise RuntimeError("curl_cffi not installed (pip install curl_cffi)")

    attempts: list[dict] = [{"impersonate": "chrome"}]
    attempts += [{"impersonate": "chrome", "doh_url": d} for d in _CFFI_DOH_URLS]

    last: Exception | None = None
    for opts in attempts:
        try:
            with cffi.Session() as s:
                r = s.get(url, timeout=_TIMEOUT, allow_redirects=True, **opts)
            if 200 <= r.status_code < 300 and (r.text or "").strip():
                return r.text
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:                              # noqa: BLE001
            last = e
    raise RuntimeError(str(last))


# ── firecrawl engine ─────────────────────────────────────────────────────────
def _fetch_firecrawl(url: str) -> tuple[str, str]:
    """Firecrawl scrape → markdown. Raises on failure — caller falls back."""
    key = _firecrawl_key()
    if not key:
        raise RuntimeError("no firecrawl_api_key configured")

    body = json.dumps({"url": url, "formats": ["markdown"]}).encode()
    req = urllib.request.Request(
        _FIRECRAWL_ENDPOINT, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    data = payload.get("data") or {}
    md = str(data.get("markdown") or "").strip()
    if not md:
        raise RuntimeError("firecrawl returned empty markdown")
    title = str(data.get("metadata", {}).get("title") or "").strip()
    return md, f"firecrawl · title: {title}"


# ── browser fallback ─────────────────────────────────────────────────────────
def _fetch_browser(url: str, max_chars: int) -> tuple[str, str]:
    """Last resort: the real Chromium the assistant already drives.

    Returns raw text, not Markdown — getting the words is the win here; the
    structure is what the local engine was for.
    """
    from actions.browser_control import _registry, _normalize_url

    sess = _registry.get(None)
    sess.run(sess.go_to(_normalize_url(url)))
    text = sess.run(sess.get_text())
    # get_text caps at 4000 internally; take what it gave
    if not text or text.startswith("Could not"):
        return "", "browser could not read the page"
    return text[:max_chars], "browser (JavaScript rendering)"


# ── the handler ──────────────────────────────────────────────────────────────
def web_scraper(parameters: dict, player=None, **_) -> str:
    params = parameters or {}
    url = str(params.get("url") or "").strip()
    try:
        max_chars = max(_DEFAULT_CHARS,
                        min(int(params.get("max_chars", _DEFAULT_CHARS) or _DEFAULT_CHARS),
                            _MAX_CHARS))
    except (TypeError, ValueError):
        max_chars = _DEFAULT_CHARS
    force_engine = str(params.get("engine", "auto")).lower().strip()

    if not url:
        return "URL ထည့်ပေးပါ၊ သခင်။ (ဥပမာ- https://example.com/article)"

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    print(f"[WebScraper] ▶️ {url} (engine={force_engine})")
    if player:
        player.write_log(f"[scraper] {url[:60]}")

    engines: list[str] = (
        ["browser"] if force_engine == "browser"
        else ["firecrawl"] if force_engine == "firecrawl"
        else ["local", "firecrawl", "browser"]
    )

    last_err = ""
    for engine in engines:
        try:
            if engine == "local":
                md, note = _fetch_local(url)
            elif engine == "firecrawl":
                md, note = _fetch_firecrawl(url)
            else:
                md, note = _fetch_browser(url, max_chars)
        except Exception as e:                              # noqa: BLE001
            last_err = f"{engine}: {e}"
            print(f"[WebScraper] ⚠️ {engine} failed: {e}")
            continue

        if not md:
            last_err = f"{engine}: {note}"
            continue

        text = md[:max_chars].rstrip()
        if len(md) > max_chars:
            text += f"\n\n… (အဆက်ရှိ — စုစုပေါင်း {len(md):,} စာလုံး)"
        header = f"[PAGE READ] {url}\n[{note}]\n\n"
        return header + text

    return (
        "ဤစာမျက်နှာကို ဖတ်လို့ မရပါ၊ သခင်။\n"
        f"အကြောင်းရင်း: {last_err or 'unknown'}\n"
        "JavaScript rendering လိုအပ်နေလျှင် Firecrawl API key ထည့်ပါ "
        "(config/api_keys.json → \"firecrawl_api_key\")။"
    )


# ── Tool declaration (auto-discovered by core/action_loader.py) ─────────────
TOOL = {
    "name": "web_scraper",
    "description": (
        "Read ANY web page and return it as clean Markdown text — for "
        "answering from an article body, not just a headline. Use when the "
        "user gives a URL ('ဒီလင့်က သတင်းကို ဖတ်ပြပါ') or when web_search / "
        "newsroom results returned only a headline and the user asks what the "
        "article says. Handles JavaScript-heavy and bot-blocked pages when a "
        "Firecrawl API key is configured (config/api_keys.json → "
        "'firecrawl_api_key'); otherwise uses local fetching, falling back to "
        "the real browser. Returns readable article text; does NOT open a "
        "browser window or take screenshots (use browser_control for that)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "url": {
                "type": "STRING",
                "description": "The web page URL to read",
            },
            "max_chars": {
                "type": "INTEGER",
                "description": ("Maximum characters to return "
                                "(default 6000, max 20000)"),
            },
            "engine": {
                "type": "STRING",
                "description": ("auto (default) | local | firecrawl | "
                                "browser — force a specific engine"),
            },
        },
        "required": ["url"],
    },
    "handler": web_scraper,
}
