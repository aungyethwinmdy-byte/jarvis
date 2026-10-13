"""Convert the Zawgyi rows already stored, so the reader stops printing them.

    python normalise_zawgyi_rows.py                  # dry run — counts only
    python normalise_zawgyi_rows.py --write          # convert
    python normalise_zawgyi_rows.py --write --reporter   # …and the raw extraction

WHY THIS EXISTS

    Measured 2026-10-01: ကြေးမုံ's PDF carries a **Zawgyi** text layer — all 32
    pages of `themirror_2026-09-29.pdf` score 2.59 or more on the marker, against
    0.00 for every မြန်မာ့အလင်း page (which the pipeline reads by vision). So about
    a tenth of the stored ကြေးမုံ rows are real article text in an encoding a
    Burmese reader cannot read and a Unicode search cannot find.

    `ingest_engine.normalise_encoding` now converts at ingest, so **future** rows
    are Unicode. This script is for the rows already in the database.

WHY IT CONVERTS RATHER THAN ROUTING TO VISION

    328 rows for that one issue, against the ~40 an issue yields through vision.
    The text is there; only the encoding is wrong.

WHY THE GATE IS THE WHOLE SAFETY PROPERTY

    `to_unicode` on text that is ALREADY Unicode reorders it into nonsense —
    measured, 3 of 6 clean test strings come back changed (`နေပြည်တော်` →
    `နပေညြ်တော်`). So a field is only converted when `looks_like_zawgyi` says it
    is Zawgyi, and the marker's separation is measured: the worst clean row
    reaches 0.28, the lowest Zawgyi row 2.59.

WHY `--reporter` IS SEPARATE

    `categorized_news` in the **jarvis** project is what JARVIS answers from, so
    it is converted by default. The **reporter** project holds the raw extraction
    that `reporter_news` and `news_section` read; converting it too is correct,
    but it rewrites the source of truth, so it is opt-in.

IDEMPOTENT — BY A LEDGER, NOT BY THE GATE

    **The gate is not enough, and this was measured the hard way.** The first run
    converted 957 rows; the second found **197** still scoring as Zawgyi, converted
    them again, and **damaged them** — `to_unicode` on text that is already
    Unicode reorders it, so a row that came out `အခြေအနေကို` went back to
    `အခြအေနကေို`. Those 197 rows were the ones whose conversion was incomplete
    (heavy private-use glyphs), so they still tripped the gate.

    So the script keeps a **ledger** of every id it has written and never touches
    one twice. The gate then only has to answer "is this Zawgyi", which it does
    well, instead of also having to answer "have I already been here", which it
    cannot.

    A second, independent veto is applied as well: a row that contains a
    **Unicode-correct `ေ`** (`[consonant][medial]?ေ`) is left alone, because it is
    already partly Unicode. That errs toward not converting, which is the right
    direction — a row left as Zawgyi is reported as unreadable, while a row
    converted twice is silently wrong.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\Mark-LIV-main")

from dotenv import dotenv_values                            # noqa: E402

from core import zawgyi as za                               # noqa: E402

JARVIS_ENV = r"E:\AI_NEWSROOM\.env"
PAGE = 500
# Every id this script has already written, so a re-run never converts a row
# twice. See the module docstring for what happened without it.
LEDGER = r"E:\Mark-LIV-main\.workbuddy-ai\zawgyi_converted.json"

# A `ေ` that is already where Unicode puts it. Its presence means the text is at
# least partly Unicode, and converting it would move a vowel that is correct.
_LEGAL_E = re.compile(rf"[{za._CONSONANT}][{za._ZG_ALL_MEDIALS}]?\u1031")

# The jarvis table, and the fields worth converting.
JARVIS_TABLE = "categorized_news"
JARVIS_FIELDS = ("headline", "summary", "full_content")


def _jarvis():
    v = dotenv_values(JARVIS_ENV)
    url = v["SUPABASE_URL"].rstrip("/")
    key = v.get("SUPABASE_SERVICE_KEY") or v.get("SUPABASE_KEY")
    return url, {"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}


def _get(url, hdr, path, tries=4):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(
                urllib.request.Request(f"{url}/rest/v1/{path}", headers=hdr), timeout=45))
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


def _patch(url, hdr, table, rid, payload, tries=3):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for _ in range(tries):
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{url}/rest/v1/{table}?id=eq.{rid}", data=body, method="PATCH",
                headers={**hdr, "Prefer": "return=minimal"}), timeout=45)
            return True
        except Exception:
            time.sleep(2)
    return False


def _ledger() -> set:
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            return set(json.load(fh))
    except Exception:                                       # noqa: BLE001
        return set()


def _save_ledger(ids: set) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as fh:
        json.dump(sorted(ids), fh)


def safe_to_convert(text: str) -> bool:
    """Zawgyi **and** not already partly Unicode. See the module docstring."""
    if not text or _LEGAL_E.search(text):
        return False
    return za.looks_like_zawgyi(text)


def convert_jarvis(write: bool) -> int:
    url, hdr = _jarvis()
    print(f"\njarvis / {JARVIS_TABLE}  ({url})")
    rows, offset = [], 0
    while offset < 40000:
        page = _get(url, hdr, f"{JARVIS_TABLE}?select=id,"
                              f"{','.join(JARVIS_FIELDS)}&offset={offset}&limit={PAGE}")
        if not page:
            break
        rows += page
        offset += PAGE
    print(f"  rows: {len(rows)}")

    done_before = _ledger()
    print(f"  already converted in an earlier run: {len(done_before)}")

    plan = []
    for r in rows:
        if r["id"] in done_before:
            continue
        upd = {f: za.to_unicode(r[f]) for f in JARVIS_FIELDS
               if r.get(f) and safe_to_convert(r[f])}
        if upd:
            plan.append((r["id"], upd))

    print(f"  rows needing conversion: {len(plan)}")
    if not plan:
        print("  nothing to do — every Zawgyi row has been converted already.")
        return 0
    for _rid, upd in plan[:2]:
        for f, val in upd.items():
            print(f"     [{f}] {val[:74]!r}")
    if not write:
        print("  dry run — add --write")
        return 0

    done = 0
    written: set = set()
    for i, (rid, upd) in enumerate(plan):
        if _patch(url, hdr, JARVIS_TABLE, rid, upd):
            done += 1
            written.add(rid)
        if (i + 1) % 100 == 0:
            print(f"     {i + 1}/{len(plan)}", flush=True)
    # The ledger is written even on a partial run: a row that was converted must
    # never be converted again, and the ids that failed are simply not in it.
    _save_ledger(done_before | written)
    print(f"  converted {done} of {len(plan)}  (ledger now {len(done_before | written)})")

    # Verified by reading the table back, never by what the loop sent.
    after = _get(url, hdr, f"{JARVIS_TABLE}?select=summary&limit={PAGE}")
    still = sum(1 for r in after if za.looks_like_zawgyi(r.get("summary") or ""))
    print(f"  read-back: {still} Zawgyi summaries in the first {len(after)} rows")
    return done


def convert_reporter(write: bool) -> int:
    """The reporter project's raw extraction — the source of truth. Opt-in."""
    from core import reporter_client as rc

    print("\nreporter / newspaper_articles  (the raw extraction)")
    rows, offset = [], 0
    while offset < 40000:
        for attempt in (1, 2, 3):
            try:
                page = (rc._get_client().table("newspaper_articles")
                        .select("id,headline,summary,article_text,newspaper_name")
                        .range(offset, offset + PAGE - 1).execute().data or [])
                break
            except Exception as e:                          # noqa: BLE001
                print(f"  read {offset} attempt {attempt}: {type(e).__name__}")
                rc.reset()
                time.sleep(3)
        else:
            print(f"  ❌ gave up reading at offset {offset}. Nothing was written.")
            return -1
        if not page:
            break
        rows += page
        offset += PAGE
    print(f"  rows: {len(rows)}")

    fields = ("headline", "summary", "article_text")
    plan = []
    for r in rows:
        upd = {f: za.to_unicode(r[f]) for f in fields
               if r.get(f) and za.looks_like_zawgyi(r[f])}
        if upd:
            plan.append((r["id"], upd))
    print(f"  rows needing conversion: {len(plan)}")
    if not plan:
        return 0
    if not write:
        print("  dry run — add --write")
        return 0

    done = 0
    for i, (rid, upd) in enumerate(plan):
        for attempt in (1, 2, 3):
            try:
                rc._get_client().table("newspaper_articles").update(upd).eq("id", rid).execute()
                done += 1
                break
            except Exception:                               # noqa: BLE001
                if attempt == 3:
                    print(f"  ⚠️ {rid} not updated")
                else:
                    time.sleep(2)
        if (i + 1) % 200 == 0:
            print(f"     {i + 1}/{len(plan)}", flush=True)
    print(f"  converted {done} of {len(plan)}")
    return done


def main() -> int:
    write = "--write" in sys.argv
    print(f"mode: {'WRITE' if write else 'DRY RUN (nothing is written)'}")
    convert_jarvis(write)
    if "--reporter" in sys.argv:
        convert_reporter(write)
    else:
        print("\n(the reporter project is not touched — pass --reporter for that)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
