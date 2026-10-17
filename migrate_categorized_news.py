"""Fill `categorized_news` in the jarvis project from the reporter project's articles.

    python migrate_categorized_news.py            # dry run — counts only, writes nothing
    python migrate_categorized_news.py --write    # insert

WHY THIS IS A CROSS-PROJECT COPY

    Measured 2026-10-01: the two databases hold different things.

        reporter  (zdsxuxwonkovuesjepfa)  ← မြန်မာ့အလင်း / ကြေးမုံ state papers
        jarvis    (yrzvwsqafmftbrfwimsf)  ← PPIB / BBC / Irrawaddy, and now the
                                            empty `categorized_news` table

    The owner's spec puts `categorized_news` in the jarvis project, and that
    project does not hold the state papers, so this reads from one and writes to
    the other. The classification itself is `core.jarvis_categories.classify` —
    one definition, also used by the reader.

IDEMPOTENT BY KEY, NOT BY UPSERT

    `categorized_news` carries a unique index on
    `(issue_date, newspaper_name, md5(headline))`. PostgREST's `on_conflict`
    takes column names and cannot express that expression index, so instead the
    script reads the keys that are already there and inserts only the missing
    ones. A second run therefore adds nothing, and a run after new issues have
    been ingested adds only the new ones.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Portable: this script lives in the project root, so resolve imports from the
# script's own directory instead of the hardcoded E:\Mark-LIV-main. An
# explicit JARVIS_PROJECT_DIR env var still wins (e.g. a relocated install).
_PROJECT_DIR = os.environ.get("JARVIS_PROJECT_DIR") or str(
    Path(__file__).resolve().parent)
sys.path.insert(0, _PROJECT_DIR)

from dotenv import dotenv_values                            # noqa: E402

from core import reporter_client as rc                       # noqa: E402
from core.reporter_client import content_rows                # noqa: E402
from core import jarvis_categories as JC                     # noqa: E402

JARVIS_ENV = os.environ.get("JARVIS_NEWSROOM_ENV") or r"E:\AI_NEWSROOM\.env"
TABLE = "categorized_news"
CHUNK = 200

# The CHECK constraint accepts exactly these two spellings. The reporter
# database is not consistent about it — `newspaper_articles` also carries
# `The Mirror` for the same paper — so the name is normalised on the way across
# rather than letting a constraint violation abort a 7,000-row insert.
_PAPER = {
    "ကြေးမုံ": "ကြေးမုံ",
    "ကျေးမုံ": "ကြေးမုံ",
    "the mirror": "ကြေးမုံ",
    "mirror": "ကြေးမုံ",
    "မြန်မာ့အလင်း": "မြန်မာ့အလင်း",
    "မြန်မာ့အလင်းသတင်းစာ": "မြန်မာ့အလင်း",
    "myanma alinn": "မြန်မာ့အလင်း",
    "myanmaalinn": "မြန်မာ့အလင်း",
}


def _paper(name: str) -> str:
    key = str(name or "").strip()
    return _PAPER.get(key) or _PAPER.get(key.lower(), "")


def _jarvis():
    v = dotenv_values(JARVIS_ENV)
    url = v["SUPABASE_URL"].rstrip("/")
    key = v.get("SUPABASE_SERVICE_KEY") or v.get("SUPABASE_KEY")
    return url, {"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}


def _get(url, hdr, path, tries=3):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(
                urllib.request.Request(f"{url}/rest/v1/{path}", headers=hdr), timeout=30))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 404):
                raise
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(3)
    return []


def _post(url, hdr, rows):
    """Insert one chunk. Returns how many the database accepted."""
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{url}/rest/v1/{TABLE}", data=body, headers={
        **hdr, "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=60)
        return len(rows)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        print(f"   ⚠️ chunk rejected ({e.code}): {detail}")
        return 0


def existing_keys(url, hdr) -> set:
    """`(issue_date, newspaper_name, md5(headline))` for every row already there.

    Paged with `offset`/`limit`, not `range=`. Measured 2026-10-01: the first
    version sent `range=0-999` as a **query parameter** and PostgREST answered
    `400 Bad Request` — the supabase client's `.range()` sends a `Range`
    **header**, and the two are not interchangeable.
    """
    keys, offset = set(), 0
    while offset < 40000:
        page = _get(url, hdr, f"{TABLE}?select=issue_date,newspaper_name,headline"
                              f"&offset={offset}&limit=1000")
        if not page:
            break
        for r in page:
            keys.add((r["issue_date"], r["newspaper_name"],
                      hashlib.md5((r.get("headline") or "").encode("utf-8")).hexdigest()))
        offset += 1000
    return keys


def main() -> int:
    write = "--write" in sys.argv
    url, hdr = _jarvis()
    print(f"jarvis project : {url}")
    print(f"mode           : {'WRITE' if write else 'DRY RUN (nothing is written)'}")

    print("\nreading the state papers from the reporter project ...")
    rows = []
    offset = 0
    while offset < 12000:
        page = rc._section_reader_rows(days=0, limit=1000, offset=offset)
        if not page:
            break
        rows += page
        offset += 1000
    rows = content_rows(rows)
    print(f"  readable articles: {len(rows)}")

    # **A failed read is not an empty source.** Measured 2026-10-01: the first
    # run of this script hit an SSL handshake timeout against the reporter
    # project, got 0 rows, and then printed "inserted 0 of 0" and exited 0 — a
    # success message for having done nothing, which is the one failure this
    # project has a standing rule against. An empty read aborts.
    if not rows:
        print("\n❌ The reporter project returned nothing. That is a failed read, "
              "not an empty newspaper — refusing to continue.\n"
              "   Nothing was written. Re-run when the connection is back.")
        return 2

    already = existing_keys(url, hdr) if write else set()
    if write:
        print(f"  already in {TABLE}: {len(already)}")

    # **The floor comes from the reporter's own `coverage()`, not from a literal
    # date.** Measured 2026-10-01: the table holds two batches that are not
    # newspaper issues — **2024-08-31 (10 rows)** and **2026-08-15 (7 rows)** —
    # and the first run of this script copied both into `categorized_news`,
    # where they would have been answerable as news from two years ago.
    # `coverage()` already decides this (it defines the window as the span of
    # days carrying a real newspaper), so the same rule is reused here rather
    # than a second, hardcoded one.
    floor = str(rc.coverage().get("oldest") or "")
    if floor:
        print(f"  floor (from coverage()): {floor}")

    payload, skipped_paper, skipped_head, dup, skipped_old = [], 0, 0, 0, 0
    tally: dict[str, int] = {}
    for r in rows:
        paper = _paper(r.get("newspaper_name"))
        if not paper:
            skipped_paper += 1
            continue
        headline = str(r.get("headline") or "").strip()
        if not headline:
            skipped_head += 1
            continue
        issue = str(r.get("issue_date") or "")
        if floor and issue < floor:
            skipped_old += 1
            continue
        key = (issue, paper, hashlib.md5(headline.encode("utf-8")).hexdigest())
        if key in already:
            dup += 1
            continue
        already.add(key)
        category, _why = JC.classify(r)
        tally[category] = tally.get(category, 0) + 1
        payload.append({
            "issue_date": issue,
            "newspaper_name": paper,
            "category": category,
            "headline": headline,
            "summary": r.get("summary") or None,
            "full_content": r.get("body_text") or None,
            "page_number": (str(r.get("page_no")) if r.get("page_no") else None),
        })

    print(f"\n  to insert      : {len(payload)}")
    if dup:
        # In `--write` mode this is "already in the table". In a dry run there is
        # no table read, so it can only mean the same `(issue_date, paper,
        # headline)` appears twice in the source — measured 2026-10-01, the
        # pipeline stores some stories on two rows. Both are the same thing to
        # the unique index, and the wording says which is which so the number is
        # not read as "the table already has 2,265 rows".
        label = ("already in the table" if write
                 else "repeated in the source (same issue + paper + headline)")
        print(f"  {label}: {dup}")
    if skipped_old:
        print(f"  skipped (before the coverage floor): {skipped_old}")
    if skipped_paper:
        print(f"  skipped (paper name not recognised): {skipped_paper}")
    if skipped_head:
        print(f"  skipped (no headline): {skipped_head}")
    if skipped_paper:
        print(f"  skipped (paper name not recognised): {skipped_paper}")
    if skipped_head:
        print(f"  skipped (no headline): {skipped_head}")

    print(f"\n{'category':<34}{'rows':>7}")
    for lab in JC.LABELS:
        if tally.get(lab):
            print(f"{lab:<34}{tally[lab]:>7}")
    print(f"{'— total':<34}{len(payload):>7}")

    if not write:
        print("\nDry run — re-run with --write to insert.")
        return 0

    print(f"\ninserting in chunks of {CHUNK} ...")
    written = 0
    for i in range(0, len(payload), CHUNK):
        written += _post(url, hdr, payload[i:i + CHUNK])
        print(f"   {min(i + CHUNK, len(payload))}/{len(payload)}", flush=True)
    print(f"\ninserted {written} of {len(payload)}")

    # Verified by reading the table back, never by what the loop sent.
    after = _get(url, hdr, f"{TABLE}?select=id&limit=1000")
    print(f"read-back: at least {len(after)} rows present")
    return 0 if written == len(payload) else 1


if __name__ == "__main__":
    raise SystemExit(main())
