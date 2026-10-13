"""Read the state news straight off `moi.gov.mm` instead of out of the PDFs.

    python scrape_moi_sections.py                       # dry run, every section
    python scrape_moi_sections.py --section president-news
    python scrape_moi_sections.py --write               # insert into categorized_news

WHY THIS REPLACES THE PDF PIPELINE

    Measured 2026-10-01, and the owner asked the question that prompted it:
    *"wouldn't it be easier to search those sites directly?"* It is, by a wide
    margin, and the numbers are in `.workbuddy-ai/memory/2026-10-01.md` round 19.
    The short version:

        PDF                                     this
        ───                                     ────
        3–7 MB download                         GET /news/<id>
        glyph codes, or Zawgyi                  clean Unicode
        3 engines + ratio gate + Zawgyi gate     parse HTML
        + vision fallback + 6-page chunking
        category inferred                       category assigned by the publisher
        date guessed from the row               in the page
        partial body                            the whole article

    **Every defect fought through rounds 13–18 is a PDF defect** — the `/R###`
    glyph gate, the Zawgyi text layer, the vision chunking, the private-use
    glyphs. None of them exist here.

THE PUBLISHER'S SECTIONS ARE THE OWNER'S CATEGORIES

    The site's own navigation is the taxonomy he defined:

        /president-news            နိုင်ငံတော်သမ္မတ
        /vice-presidents-news      (split by name — see below)
        /pyidaungsu-hluttaw-news   ပြည်ထောင်စုလွှတ်တော်
        /pyithu-htuttaw-news       ပြည်သူ့လွှတ်တော်
        /amyotha-htuttaw-news      အမျိုးသားလွှတ်တော်
        /commander-in-chief-news   → အခြား
        /other-news                → အခြား

    Those are exactly the offices and the three parliaments — the categories that
    needed the delicate strength-of-evidence classifier — so where the site
    assigns one it is taken as **authoritative** and nothing is inferred.

    **The vice-presidents are the one place the site is coarser than the spec.**
    It has a single VP section; the owner wants the two officeholders apart, so
    those rows go through `jarvis_categories.classify`, which already separates
    them by name and already knows `ဦးညိုသျှော` is printed two ways.

WHAT THE SITE DOES NOT HAVE

    The topics — ပညာရေး / ကျန်းမာရေး / စီးပွားရေး / လူမှုရေး / သဘာဝဘေး / ဆောင်းပါး /
    အယ်ဒီတာ့အာဘော် — have no section, so those still need classifying. That is
    the same classifier as before, but run on clean text instead of on glyph
    codes, which is a far easier problem.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\Mark-LIV-main")

from dotenv import dotenv_values                            # noqa: E402

from core import jarvis_categories as JC                    # noqa: E402

BASE = "https://www.moi.gov.mm"
JARVIS_ENV = r"E:\AI_NEWSROOM\.env"
LEDGER = r"E:\Mark-LIV-main\.workbuddy-ai\moi_scraped.json"

# The publisher's section → the owner's category. `None` means "the section is
# not a category" — the parent `hluttaw-news` lists what its three children do.
SECTION_CATEGORY: dict[str, str | None] = {
    "president-news": "နိုင်ငံတော်သမ္မတ",
    "vice-presidents-news": "",            # classified by name
    "pyidaungsu-hluttaw-news": "ပြည်ထောင်စုလွှတ်တော်",
    "pyithu-htuttaw-news": "ပြည်သူ့လွှတ်တော်",
    "amyotha-htuttaw-news": "အမျိုးသားလွှတ်တော်",
    "hluttaw-news": None,
    "commander-in-chief-news": JC.OTHER,
    "other-news": JC.OTHER,
}
# The order matters only for reporting; the site lists newest first.
SECTION_ORDER = ("president-news", "vice-presidents-news", "pyidaungsu-hluttaw-news",
                 "pyithu-htuttaw-news", "amyotha-htuttaw-news",
                 "commander-in-chief-news", "other-news")

_UA = {"User-Agent": "Mozilla/5.0 (compatible; MarkLIV/1.0)"}
_PAUSE = 0.4          # be a polite guest — this is a government site
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}

# One card. Anchored on the h2 the site uses for the headline, so the image
# link above it and the summary below it cannot be mistaken for it.
_CARD = re.compile(
    r'href="(/news/(\d+))"[^>]*>\s*<img.*?</a>\s*</div>\s*<div[^>]*>\s*'
    r'<div class="card-body">\s*<div class="card-title[^"]*"><h2><a[^>]*>(?P<head>.*?)</a>'
    r'</h2></div>\s*<p[^>]*>.*?</i>\s*(?P<date>[A-Za-z]{3}\s+\d{1,2},\s+\d{4})</p>'
    r'\s*<p class="card-text">(?P<summary>.*?)</p>',
    re.S)


def _get(path: str, tries: int = 3) -> str:
    url = path if path.startswith("http") else BASE + path
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=45) as fh:
                return fh.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            if i == tries - 1:
                raise
        except Exception:                                   # noqa: BLE001
            if i == tries - 1:
                raise
        time.sleep(2)
    return ""


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _iso(date_text: str) -> str:
    """`Sep 30, 2026` → `2026-09-30`."""
    m = re.match(r"([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})", date_text.strip())
    if not m or m.group(1) not in _MONTHS:
        return ""
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def list_section(section: str, pages: int = 20) -> list[dict]:
    """Every card on a section's pages, newest first."""
    out, seen = [], set()
    for page in range(pages):
        doc = _get(f"/{section}?page={page}")
        if not doc:
            break
        found = list(_CARD.finditer(doc))
        if not found:
            break
        for m in found:
            aid = m.group(2)
            if aid in seen:
                continue
            seen.add(aid)
            out.append({
                "id": aid,
                "url": m.group(1),
                "headline": _text(m.group("head")),
                "issue_date": _iso(m.group("date")),
                "summary": _text(m.group("summary")),
            })
        time.sleep(_PAUSE)
    return out


def article_body(url: str) -> str:
    """The article's own text, or "" when the page carries none.

    **The container is `post-body`.** Two wrong answers came first, and both are
    worth recording because each returned *plausible* text:

      * anchoring on a `dd/mm/yyyy` and cutting before it — `/news/81370` has no
        such date in its markup, so the anchor never matched and the "body" came
        back as the **latest-news sidebar**: 1,280 characters of a different
        story. A wrong answer that reads like an answer.
      * `field--name-body` — it occurs **8 times** on that page, seven of them
        site blocks (the app download, the menu, the sidebar).

    `node__content` is empty on both pages tested, so it is not the container
    either.

    **Some articles have no body at all.** Measured 2026-10-01: `/news/88673`
    (30 Sep) returns 5,616 characters, while `/news/81370` (3 Apr) has an empty
    `post-body` — the site does not serve the text for every older item. This
    returns "" for those so the caller can skip them, rather than falling back to
    the page's chrome.

    The date is taken from the section card instead — it is on the list page for
    every article, which the article page cannot guarantee.
    """
    doc = _get(url)
    if not doc:
        return ""
    cut = re.sub(r"<script.*?</script>|<style.*?</style>", "", doc, flags=re.S)
    m = re.search(r'<div class="post-body">(.*?)</div>', cut, re.S)
    if not m:
        return ""
    return _text(m.group(1))


def _jarvis():
    v = dotenv_values(JARVIS_ENV)
    url = v["SUPABASE_URL"].rstrip("/")
    key = v.get("SUPABASE_SERVICE_KEY") or v.get("SUPABASE_KEY")
    return url, {"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}


def _existing(url, hdr) -> set:
    keys, off = set(), 0
    while off < 40000:
        try:
            page = json.load(urllib.request.urlopen(urllib.request.Request(
                f"{url}/rest/v1/categorized_news?select=headline&offset={off}&limit=1000",
                headers=hdr), timeout=45))
        except Exception:                                   # noqa: BLE001
            break
        if not page:
            break
        for r in page:
            keys.add((r.get("headline") or "").strip())
        off += 1000
    return keys


def _insert(url, hdr, rows) -> int:
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{url}/rest/v1/categorized_news", data=body,
            headers={**hdr, "Prefer": "return=minimal"}), timeout=60)
        return len(rows)
    except urllib.error.HTTPError as e:
        print(f"     ⚠️ {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
        return 0


def main() -> int:
    write = "--write" in sys.argv
    only = ""
    if "--section" in sys.argv:
        only = sys.argv[sys.argv.index("--section") + 1]
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    wanted = [only] if only else list(SECTION_ORDER)
    print(f"mode: {'WRITE' if write else 'DRY RUN'}  sections: {', '.join(wanted)}\n")

    url = hdr = None
    have: set = set()
    if write:
        url, hdr = _jarvis()
        have = _existing(url, hdr)
        print(f"already in categorized_news: {len(have)} headlines\n")

    total = fetched = inserted = empty_body = 0
    for section in wanted:
        if section not in SECTION_CATEGORY:
            print(f"?? unknown section {section} — known: {', '.join(SECTION_ORDER)}")
            continue
        cards = list_section(section, pages=3 if limit else 20)
        total += len(cards)
        print(f"── {section}: {len(cards)} cards")
        if not cards:
            continue
        print(f"   newest {cards[0]['issue_date']}  {cards[0]['headline'][:52]}")
        print(f"   oldest {cards[-1]['issue_date']}  {cards[-1]['headline'][:52]}")
        if not write:
            continue

        rows = []
        for card in cards:
            if card["headline"] in have:
                continue
            body = article_body(card["url"])
            if not body:
                # The site does not serve every older article's text. Recorded,
                # not invented — a headline with no body is still worth having,
                # but it is counted separately so the loss is visible.
                empty_body += 1
            fetched += 1
            # The publisher's own section is authoritative where it names one;
            # the vice-presidents have to be split by name, which the classifier
            # already does (and it knows the two spellings of ဦးညိုသျှော).
            category = SECTION_CATEGORY[section] or JC.classify(
                {"headline": card["headline"], "body_text": body})[0]
            rows.append({
                "issue_date": card["issue_date"],
                "newspaper_name": "မြန်မာ့အလင်း",
                "category": category,
                "headline": card["headline"],
                "summary": card["summary"] or None,
                "full_content": body or None,
                "page_number": None,
            })
            if len(rows) >= 100:
                inserted += _insert(url, hdr, rows)
                have.update(r["headline"] for r in rows)
                rows = []
                print(f"   …{fetched} fetched, {inserted} inserted", flush=True)
            time.sleep(_PAUSE)
        if rows:
            inserted += _insert(url, hdr, rows)
            have.update(r["headline"] for r in rows)

    print(f"\ntotal cards: {total}")
    if write:
        print(f"bodies fetched: {fetched}  (of which empty on the site: {empty_body})")
        print(f"inserted: {inserted}")
    else:
        print("\nDry run — add --write to fetch bodies and insert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
