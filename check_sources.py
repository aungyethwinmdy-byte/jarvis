"""Probe every news source Mark-LIV knows about, and say plainly what each one did.

    py check_sources.py            # probe everything
    py check_sources.py --direct   # ignore HTTP(S)_PROXY for this run

WHY THIS EXISTS
    A source that returns nothing is indistinguishable from a source that was
    never there. Both produce an empty list and no exception, so the briefing
    quietly fills the gap with whatever else it found and looks healthy. This
    run makes the difference visible: every source is probed and reported as
    OK / BLOCKED / EMPTY / DEAD, with the status code or exception that decided
    it.

    That matters especially for outlets behind Cloudflare (The Irrawaddy answers
    403 to a plain GET, measured 2026-09-26), where the only working route is a
    Telegram channel mirror. A mirror pointed at a *user account* rather than a
    channel returns HTTP 200 with a "Telegram: Contact @name" title and zero
    messages — a successful-looking fetch that can never yield a headline.

    If you are behind a proxy that allowlists hosts, run this both ways:
    the pass/fail pattern is the proxy's opinion, not the site's.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA,
            "Accept-Language": "my-MM,my;q=0.9,en-US;q=0.8,en;q=0.7"}
_TIMEOUT = 15

# Mirrors first, direct second. The order is the recommendation: The Irrawaddy
# serves 403 to a plain GET, so its mirror is the working route and the direct
# feed is the fallback that will almost always lose.
SOURCES: list[tuple[str, str, str]] = [
    # (label, kind, url)
    ("BBC Burmese",      "rss",      "https://feeds.bbci.co.uk/burmese/rss.xml"),
    ("DVB",              "rss",      "https://burmese.dvb.no/feed"),
    ("RFA Burmese",      "rss",      "https://www.rfa.org/burmese/rss2.xml"),
    ("Irrawaddy (direct)", "rss",    "https://burma.irrawaddy.com/feed"),
    ("Irrawaddy (mirror)", "telegram", "https://t.me/s/theirrawaddy"),
    ("RFA (mirror)",     "telegram", "https://t.me/s/rfaburmese"),
    ("RFA (mirror, alt)", "telegram", "https://t.me/s/RFA_Burmese"),
    ("GNLM",             "rss",      "https://www.gnlm.com.mm/feed"),
    ("PPIB",             "scrape",   "https://www.ppib.gov.mm/"),
    ("MOI",              "scrape",   "https://www.moi.gov.mm/index.php/president-news"),
    ("Google News (world)", "google", "https://news.google.com/rss/search?q=world&hl=en-US&gl=US&ceid=US:en"),
]


def _opener(direct: bool):
    if direct:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _get(opener, url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=_HEADERS)
    with opener.open(req, timeout=_TIMEOUT) as resp:
        return resp.status, resp.read()


def _count_rss(body: bytes) -> int:
    root = ET.fromstring(body)
    items = root.findall(".//item")
    if items:
        return len(items)
    return len(root.findall(".//{http://www.w3.org/2005/Atom}entry"))


def probe(label: str, kind: str, url: str, opener) -> tuple[str, str]:
    """Returns (verdict, detail). Never raises."""
    try:
        status, body = _get(opener, url)
    except Exception as e:
        name = type(e).__name__
        detail = str(e)[:60]
        # A 4xx that reached the server is a *content* verdict, not a transport
        # one — 403 from Cloudflare means "this route is closed", not "offline".
        if "403" in detail:
            return "BLOCKED", f"403 Forbidden — Cloudflare; use the mirror"
        if "404" in detail:
            return "DEAD", f"404 Not Found — the URL moved"
        return "UNREACHABLE", f"{name}: {detail}"

    text = body.decode("utf-8", "replace")

    if kind == "rss" or kind == "google":
        try:
            n = _count_rss(body)
        except Exception as e:
            return "NOT-FEED", f"HTTP {status} but not parseable as RSS/Atom ({type(e).__name__})"
        if n == 0:
            return "EMPTY", f"HTTP {status}, feed parses but carries no items"
        return "OK", f"HTTP {status}, {n} items"

    if kind == "telegram":
        # A t.me/s/<name> URL can resolve to a user *contact* page. It answers
        # 200 with a "Telegram: Contact @name" title and no message blocks, so
        # it looks like a healthy fetch that simply had no news. RFA was
        # configured this way and contributed nothing for its whole life.
        title_m = re.search(r"<title>(.*?)</title>", text, re.S)
        title = title_m.group(1).strip() if title_m else ""
        if "contact" in title.lower():
            return "DEAD", (f"user contact page, not a channel — no preview to "
                            f"scrape ({title[:40]})")
        n = len(re.findall(r"tgme_widget_message\b", text))
        if n == 0:
            return "EMPTY", f"HTTP {status} but no message blocks (channel empty or markup changed)"
        return "OK", f"HTTP {status}, {n} messages"

    if kind == "scrape":
        links = len(re.findall(r"<a\s[^>]*href=", text, re.I))
        if links == 0:
            return "EMPTY", f"HTTP {status} but no links found"
        return "OK", f"HTTP {status}, {links} links ({len(body) // 1024} KB)"

    return "OK", f"HTTP {status}"


def main() -> None:
    direct = "--direct" in sys.argv
    proxy = {k: v for k, v in os.environ.items() if k.lower() in ("http_proxy", "https_proxy")}
    print("=" * 78)
    print(f"NEWS SOURCES   mode={'DIRECT (proxy ignored)' if direct else 'as-configured'}")
    if proxy:
        print(f"  proxy in env: {', '.join(f'{k}={v}' for k, v in proxy.items())}")
        print("  (an allowlisting proxy decides what succeeds below — run --direct to compare)")
    else:
        print("  proxy in env: none")
    print("=" * 78)

    opener = _opener(direct)
    tally: dict[str, int] = {}
    for label, kind, url in SOURCES:
        verdict, detail = probe(label, kind, url, opener)
        tally[verdict] = tally.get(verdict, 0) + 1
        print(f"  {verdict:<12}{label:<22}{detail}")

    print("-" * 78)
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    dead = [l for l, k, u in SOURCES if probe(l, k, u, opener)[0] in ("DEAD", "BLOCKED")]
    if dead:
        print()
        print("  routes that cannot work from here, and what to do:")
        for l in dead:
            print(f"    - {l}")
        print("    Cloudflare-blocked outlets need a Telegram channel mirror;")
        print("    a mirror that resolves to 'Contact @name' is a user account,")
        print("    not a channel, and will never yield a message.")


if __name__ == "__main__":
    main()
