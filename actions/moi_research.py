"""The MOI research engine — the owner's hybrid system, 2026-10-03.

    *"User asks → MOI website crawl → 1000 pages → Gemini … အစား background
    crawler နေ့တိုင်း 11:30 AM … New articles only → Extract → Database. …
    ပြီးရင် JARVIS က Database Search → Relevant articles → Gemini → Answer …
    Database မှာ မတွေ့ရင် → Live MOI Search → MOI Website → Fetch article →
    Answer."*

WHAT THIS IS, IN ONE LINE

    `moi_research` answers a **keyword / name / place / number** question about
    the MOI site from a **local index first** (`core/moi_index.py`), and falls
    back to the **live site** (`core/moi_client.py`) when the index has nothing.
    It also owns the daily crawl that keeps that index current.

HOW IT DIFFERS FROM `moi_news` — and why both exist

    | question | tool | source |
    |---|---|---|
    | "what is in the president section today / yesterday" | `moi_news` | live, always current |
    | "news about the gold price", "articles mentioning ဦးမင်းအောင်လှိုင်", "the numbers in this story" | **`moi_research`** | the **index first**, live as fallback |

    `moi_news` is deliberately left alone: a *section + today* question must stay
    live, because that is the one question a cache can answer wrongly. This tool
    is for everything a **search** answers, and a search is where an index earns
    its keep — one query over thousands of articles instead of twenty requests per
    section.

THE HONESTY RULES THIS TOOL FOLLOWS

    * **Every answer says which source it came from.** "index (crawled 2026-10-03
      11:30)" or "live moi.gov.mm". The owner can then weigh it.
    * **The index falling empty is not the site being empty.** When the index has
      no hit the tool says so and *then* searches the live site; only if the live
      site also has nothing does it say `မတွေ့ပါ`.
    * **A crawl that could not reach the site is not "nothing new".** `update`
      reports `မချိတ်နိုင်ပါ`, never a clean "0 new".
    * **The result names the sentence the model must speak.** The project learned
      this the expensive way: a tool said `မရှိပါ`, the model said `မတွေ့ပါ`, and a
      limitation was spoken as a finding.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Running this file as a SCRIPT (Task Scheduler, or `python actions/moi_research.py
# --scheduled`) puts `actions/` on sys.path, not the project root, so
# `from core import ...` would fail with ModuleNotFoundError. The root is added
# **before** those imports, and only in that case, so being imported as a tool by
# `core/action_loader.py` is unaffected.
if __name__ == "__main__":
    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in sys.path:
        sys.path.insert(0, _root)

from config import is_windows                     # noqa: E402
from core import moi_client as mc                 # noqa: E402
from core import moi_index as ix                  # noqa: E402
from core.timefmt import now_mmt, to_burmese_digits  # noqa: E402

# The scheduled task. Named so the owner can find it in Task Scheduler, and
# distinct from `JARVIS_GameUpdater` so neither deletes the other.
TASK_NAME = "JARVIS_MOI_Crawler"
DEFAULT_HOUR, DEFAULT_MINUTE = 11, 30
# The path used in the scheduled task's command line. Resolved at import so a
# relative invocation still registers an absolute path — Task Scheduler runs the
# job with a different working directory.
_SCRIPT = str(Path(__file__).resolve())
# The site's own politeness pause sits between article fetches in `crawl`; the
# scheduled run is unattended, so nothing here is tuned for voice latency.
_NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32" else {}
)

_MONTHS = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်", "ဇူလိုင်",
           "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ", "ဒီဇင်ဘာ")


def _mmd(stamp: str) -> str:
    """`2026-10-03` → `3 အောက်တိုဘာ 2026`. Anything else is returned as-is.

    A date the index could not read is shown raw rather than guessed — the
    project's rule that a wrong date is worse than a missing one.
    """
    try:
        y, m, d = str(stamp).split("-")
        return f"{int(d)} {_MONTHS[int(m)]} {y}"
    except (ValueError, IndexError):
        return str(stamp or "")


def _source_line(row: dict) -> str:
    """Where this row came from: the site, the section, the date, the link.

    `mc.BASE` already carries the scheme and host (`https://www.moi.gov.mm`),
    so only the path is appended — printing the site name *and* the BASE made
    `moi.gov.mmhttps://www.moi.gov.mm/news/…` (seen live 2026-10-03).
    """
    url = str(row.get("url", "")).strip()
    if url.startswith("http"):
        link = url
    else:
        link = f"{mc.BASE}/{url.lstrip('/')}" if url else mc.BASE
    bits = [f"**ရင်းမြစ်**: {link}"]
    if row.get("section_label"):
        bits.append(f"**ကဏ္ဍ**: {row['section_label']}")
    if row.get("published_date"):
        bits.append(f"**ရက်စွဲ**: {_mmd(row['published_date'])}")
    return " · ".join(bits)


def _hit_line(row: dict) -> str:
    """One search hit: its date and its headline."""
    stamp = _mmd(row["published_date"]) if row.get("published_date") else "ရက်စွဲမပါ"
    return f"  • {stamp} — {row.get('title','').strip()[:110]}"


def _people_text(items: list) -> str:
    """`people` rendered the way the article printed the name — rank included."""
    out = []
    for p in items:
        if isinstance(p, dict):
            label = f"{p.get('title','')} {p.get('honorific','')}{p.get('name','')}".strip()
        else:
            label = str(p)
        if label and label not in out:
            out.append(label)
    return "၊ ".join(out)


# ── Scheduling (the owner's "background crawler, 11:30 AM") ───────────────────


def _schtasks_args(hour: int, minute: int) -> list[str]:
    """The exact `schtasks` argv for the daily crawl.

    A **pure function** so `check_moi_index.py` can assert the command it would
    run — 11:30, the right script, `--scheduled` — without creating a real
    scheduled task on the machine running the test. The `TR` value is quoted
    because both paths may contain spaces.
    """
    return ["schtasks", "/Create", "/TN", TASK_NAME,
            "/TR", f'"{sys.executable}" "{_SCRIPT}" --scheduled',
            "/SC", "DAILY", "/ST", f"{hour:02d}:{minute:02d}", "/F"]


def schedule_crawl(hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE) -> str:
    """Create (or replace) the daily crawl task. Returns what happened."""
    if not is_windows():
        return ("⏰ အလိုအလျောက် ရှာဖွေမှုကို Windows Task Scheduler အတွက်သာ "
                "သတ်မှတ်ပေးလို့ ရပါတယ်။ ဒီစက်မှာ "
                f"`{sys.executable} {_SCRIPT} --scheduled` ကို cron/launchd နဲ့ "
                "ချိန်ပေးပါ။")
    # Replaced, not added: two tasks with the same name at different times is how
    # a "daily" job ends up running twice a day. `/F` overwrites.
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                   capture_output=True, **_NO_WINDOW)
    res = subprocess.run(_schtasks_args(hour, minute),
                         capture_output=True, text=True, **_NO_WINDOW)
    if res.returncode == 0:
        return (f"⏰ MOI ရှာဖွေမှုကို နေ့တိုင်း {hour:02d}:{minute:02d} မှာ "
                f"အလိုအလျောက် run အောင် သတ်မှတ်ပြီးပါပြီ ({TASK_NAME})။")
    return f"⚠️ အလိုအလျောက် သတ်မှတ်လို့ မရပါ — {res.stderr.strip() or res.stdout.strip()}"


def _int(value, default: int, low: int, high: int) -> int:
    """A parameter as an int inside `[low, high]`. Bad input → `default`.

    The voice path must never raise on a parameter, and a clamped value is safe
    where a rejected one would cost the whole answer.
    """
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def _search_lines(rep: dict, source: str, limit: int) -> list[str]:
    """A search report as spoken lines, naming the source and any caveat."""
    out = [f"**{source}** — {to_burmese_digits(rep['total'])} ခု တွေ့ပါတယ်။"]
    if rep.get("matched") and rep.get("term"):
        # The project's measured rule: a whole-question query matches nothing,
        # and the answer must say which shorter term did the work.
        out.append(f"ℹ️ \"{rep['term']}\" အပြည့်အစုံ မတွေ့လို့ "
                   f"\"{rep['matched']}\" နဲ့ ရှာထားပါတယ်။")
    for row in (rep.get("hits") or [])[:limit]:
        out.append(_hit_line(row))
    if rep.get("undated_skipped"):
        out.append(f"ℹ️ ရက်စွဲမပါတဲ့ သတင်း "
                   f"{to_burmese_digits(rep['undated_skipped'])} ခုကို ရက်စွဲစစ်လို့ "
                   f"ချန်ထားပါတယ် — ဒါက 'သတင်းမရှိဘူး' လို့ မဆိုလိုပါ။")
    return out


def _do_search(p: dict) -> str:
    """index first, live site as the fallback — the owner's own diagram."""
    query = str(p.get("query") or "").strip()
    mention = str(p.get("mention") or "").strip()
    section = str(p.get("section") or "").strip()
    date = str(p.get("date") or "").strip()
    kind = str(p.get("kind") or "people").strip().lower()
    limit = _int(p.get("limit"), 8, 1, 20)
    days = _int(p.get("days"), 0, 0, 60)
    if not (query or mention):
        return "ဘာကို ရှာရမလဲ ပြောပါ — သတင်းခေါင်းစဉ်ထဲက စကားလုံး ဒါမှမဟုတ် လူအမည် ပေးပါ။"

    if mention:
        rep = ix.by_entity(kind, mention, section=section, days=days, limit=limit)
        source = f"📇 MOI index — {kind} \"{mention}\""
        if rep.get("error"):
            return "⚠️ `kind` က people / organizations / locations သုံးမျိုးထဲက ဖြစ်ရပါမယ်။"
    else:
        rep = ix.search(query, section=section, date=date, days=days, limit=limit)
        source = "📇 MOI index"

    if rep["total"]:
        lines = _search_lines(rep, source, limit)
        lines.append("")
        lines.append("ℹ️ အပြည့်အစုံ ဖတ်ချင်ရင် `action='story'` နဲ့ လင့်ကို ခေါ်ပါ။ "
                     "ဒီအဖြေက သိမ်းထားတဲ့ MOI index ထဲကပါ — "
                     "ရင်းမြစ်နဲ့ ရက်စွဲကို ဖတ်ပြပါ။")
        return "\n".join(lines)

    # ── the index had nothing: go live, and say which of the two it was ──────
    # But `days`/`section` can also be why the index found nothing — a filter the
    # caller guessed (measured 2026-10-03: `days=2` over a section whose newest
    # crawl-day item was 4 days old, `section='ဒုတိယသမ္မတ'` vs the stored label
    # `ဒုတိယသမ္မတသတင်းများ`). Before leaving the index, retry once with the same
    # term and no date filter, and say so — the live site returns headlines with
    # no dates, which is a worse answer than a dated one.
    if not rep["total"] and (days or date):
        rep = ix.search(query, section=section, limit=limit) if not mention \
            else ix.by_entity(kind, mention, section=section, limit=limit)
        if rep["total"]:
            lines = _search_lines(rep, source, limit)
            newest = max((h.get("published_date", "") for h in rep.get("hits", [])),
                         default="")
            lines.append("")
            lines.append(f"ℹ️ `days/date` filter နဲ့ မတွေ့လို့ filter မပါ ရှာထားပါတယ်"
                         + (f" — index ထဲက အသစ်ဆုံး {_mmd(newest)}" if newest else ""))
            return "\n".join(lines)
    ok, reason = mc.available()
    if not ok:
        return (f"📇 MOI index မှာ မတွေ့ပါ။ ⚠️ moi.gov.mm ကိုလည်း "
                f"**မချိတ်နိုင်ပါ** — {reason}\n"
                f"ℹ️ ဒါက `မတွေ့ပါ` မဟုတ်ပါ — ဆိုက်ကို မချိတ်နိုင်တာပါ။ "
                f"`action='update'` နဲ့ index ကို ပြန်ဆွဲပြီး ပြန်မေးပါ။")
    live = mc.search_site(mention or query, pages=2, limit=max(limit, 12))
    # The site's search matches the whole phrase, so a multi-word query can
    # return only results that share every word — and miss the news. Measured
    # 2026-10-05: "လာအို ခရီးစဉ်" returns two ဆောင်းပါး while the trip news
    # itself sits under the bare token "လာအို". Re-run the query's own tokens
    # and merge, deduped by url — phrase results stay first, the news the
    # phrase search hid comes in behind them.
    toks = sorted({t for t in (mention or query).split() if len(t) > 2},
                  key=len, reverse=True)
    if len(toks) > 1:
        merged, seen = list(live), {r.get("url", "") for r in live}
        for tok in toks:
            for row in mc.search_site(tok, pages=1, limit=max(limit, 12)):
                u = row.get("url", "")
                if u and u not in seen:
                    seen.add(u)
                    merged.append(row)
        live = merged
    if not live:
        # A one-word query that found nothing is really nothing (same term,
        # already searched above) — but try any longer leftover tokens anyway.
        for tok in toks:
            live = mc.search_site(tok, pages=1, limit=max(limit, 12))
            if live:
                query = tok
                break
    if live:
        lines = [f"📇 MOI index မှာ မတွေ့ပါ — **🌐 live moi.gov.mm** မှ "
                 f"{to_burmese_digits(len(live))} ခု တွေ့ပါတယ်။"]
        for row in live[:limit]:
            lines.append(f"  • {row.get('headline','')[:110]}")
        lines.append("")
        lines.append("ℹ️ ဒီအဖြေက live ဆိုက်ကပါ — ရက်စွဲမပါပါ။ "
                     "အပြည့်အစုံအတွက် `action='story'` ခေါ်ပါ။")
        return "\n".join(lines)

    if not ix.count():
        return ("📇 MOI index လွတ်နေပါတယ် (တစ်ခါမှ မဆွဲရသေးပါ)၊ live ဆိုက်မှာလည်း "
                f"\"{mention or query}\" နဲ့ ပတ်သက်တာ **မတွေ့ပါ**။\n"
                "ℹ️ `action='update'` ခေါ်ပြီး index ကို အရင်ဆွဲထားပါ။")
    return (f"📇 MOI index ထဲမှာရော 🌐 live moi.gov.mm မှာပါ "
            f"\"{mention or query}\" နဲ့ ပတ်သက်တာ **မတွေ့ပါ**။")


def _resolve(url: str, term: str) -> str:
    """The article path the caller meant: an explicit url, a search's best hit,
    or a bare numeric id.

    **`term.isdigit()` is not the test for a numeric id** — it is True for ၀-၉ too,
    so a Burmese-digit id would build `/news/၈၈၆၇၃`. `re.fullmatch(r"[0-9]+")` is
    the honest one, the same rule `moi_news` uses.
    """
    path = (url or "").strip()
    if not path and term:
        hits = ix.search(term, limit=1).get("hits") or []
        if hits:
            path = hits[0].get("url", "")
    if not path and re.fullmatch(r"[0-9]+", term or ""):
        path = f"/news/{term}"
    if path and not path.startswith("/"):
        path = "/" + path.lstrip("/")
    return path


def _do_story(p: dict) -> str:
    """The full article — from the index when it holds the body, else live."""
    path = _resolve(str(p.get("url") or ""), str(p.get("query") or ""))
    if not path:
        return ("ဘယ်သတင်းလဲ ပြောပါ — လင့်၊ သတင်းအမှတ် (ဥပမာ '88673') "
                "ဒါမှမဟုတ် ခေါင်းစဉ်ထဲက စကားလုံး ပေးပါ။")

    row = ix.get(path)
    if row and row.get("content"):
        head = "📇 **ရင်းမြစ်**: MOI index (crawl လုပ်ထားတဲ့ မိတ္တူ)"
    else:
        body = mc.article(path)
        if not body:
            # The four-state contract from `moi_client.article_state`: a failed
            # read must never be spoken as an empty source.
            state = mc.article_state(path)
            if state == "missing":
                return (f"⚠️ {mc.BASE}{path} မှာ သတင်းမရှိပါ — လင့်က မှားနေနိုင်ပါတယ်။")
            if state == "empty":
                return (f"ℹ️ {mc.BASE}{path} မှာ သတင်းကိုယ်ထည် မပါပါ — "
                        f"ဝက်ဘ်ဆိုဒ်က ဒီသတင်းအတွက် စာသား မပေးထားပါ။\n"
                        f"လင့်: {mc.BASE}{path}")
            return (f"⚠️ {mc.BASE}{path} ရဲ့ စာသားကို ဖတ်လို့ မရပါ — စာမျက်နှာကတော့ "
                    f"ရှိပါတယ်။ ဒါက 'သတင်းမရှိဘူး' လို့ မဆိုလိုပါ။\nလင့်: {mc.BASE}{path}")
        # One fetch of the page gives the body, the date and the author
        # (`moi_client.article_page`); `make_row` extracts the rest from the body,
        # so nothing is fetched twice.
        row = ix.make_row({"id": path, "url": path}, content=body,
                          date=mc.article_date(path))
        head = "🌐 **ရင်းမြစ်**: live moi.gov.mm\n" + _source_line(row)
        return f"{head}\n\n{_story_body(row, body, path)}"

    head += "\n" + _source_line(row)
    return f"{head}\n\n{_story_body(row, row.get('content', ''), path)}"


def _story_body(row: dict, body: str, path: str) -> str:
    """The body, then the numbers the article printed, then where it came from."""
    out = [body[:2500]]
    nums = row.get("numbers") or []
    if nums:
        out.append("")
        out.append(f"**ဒီသတင်းပါ ကိန်းဂဏန်း** ({to_burmese_digits(len(nums))} ခု):")
        for n in nums[:12]:
            value = n.get("value", "") if isinstance(n, dict) else str(n)
            ctx = n.get("context", "") if isinstance(n, dict) else ""
            out.append(f"  • {value} — …{ctx}…")
    else:
        out.append("")
        out.append("ℹ️ ဒီသတင်းထဲမှာ ကိန်းဂဏန်း မတွေ့ပါ။")
    out.append("")
    out.append(f"🔗 {mc.BASE}{path}")
    return "\n".join(out)


def _do_numbers(p: dict) -> str:
    """Only the figures — the owner's *"ဒီသတင်းထဲက ကိန်းဂဏန်းတွေကို သီးသန့်ပြောပြ"*."""
    path = _resolve(str(p.get("url") or ""), str(p.get("query") or ""))
    row = ix.get(path) if path else None
    if row is None and not path:
        hits = ix.search(str(p.get("query") or ""), limit=1).get("hits") or []
        row = hits[0] if hits else None
    if row is None:
        return "⚠️ ဒီသတင်းကို index မှာ မတွေ့ပါ — အရင်ဆုံး `action='search'` နဲ့ ရှာပါ။"
    nums = row.get("numbers") or []
    if not nums:
        return (f"ℹ️ \"{row.get('title','')[:90]}\" ထဲမှာ ကိန်းဂဏန်း မတွေ့ပါ — "
                f"ဒါက သတင်းထဲ ကိန်းဂဏန်းမပါလို့ပါ။\n{_source_line(row)}")
    lines = [f"**{row.get('title','')[:90]}** — ကိန်းဂဏန်း "
             f"{to_burmese_digits(len(nums))} ခု:"]
    for n in nums[:20]:
        value = n.get("value", "") if isinstance(n, dict) else str(n)
        ctx = n.get("context", "") if isinstance(n, dict) else ""
        lines.append(f"  • {value} — …{ctx}…")
    lines.append(_source_line(row))
    return "\n".join(lines)


def _do_entities(p: dict) -> str:
    """Who and what an article names — people, organisations, places."""
    path = _resolve(str(p.get("url") or ""), str(p.get("query") or ""))
    row = ix.get(path) if path else None
    if row is None:
        hits = ix.search(str(p.get("query") or p.get("mention") or ""),
                         limit=1).get("hits") or []
        row = hits[0] if hits else None
    if row is None:
        return "⚠️ ဒီသတင်းကို index မှာ မတွေ့ပါ — အရင်ဆုံး `action='search'` နဲ့ ရှာပါ။"
    lines = [f"**{row.get('title','')[:90]}** ထဲမှာ ပါတဲ့ အမည်များ:"]
    people = _people_text(row.get("people") or [])
    lines.append(f"  • လူ: {people or 'မတွေ့ပါ'}")
    lines.append(f"  • အဖွဲ့အစည်း: {'၊ '.join(row.get('organizations') or []) or 'မတွေ့ပါ'}")
    lines.append(f"  • နေရာ: {'၊ '.join(row.get('locations') or []) or 'မတွေ့ပါ'}")
    lines.append("")
    lines.append("ℹ️ ဒါတွေက သတင်းထဲ စာသားအတိုင်း ဖော်ပြထားတဲ့ အမည်တွေပါ။")
    lines.append(_source_line(row))
    return "\n".join(lines)


def _do_update(p: dict) -> str:
    """Run the crawl now. Slow and network-bound — the description says so."""
    rep = ix.crawl(fetch_bodies=True)
    if not rep["reachable"]:
        # **Never "0 new".** The site was unreachable; saying otherwise would be
        # a claim about the publisher made on the strength of a failed socket.
        return (f"⚠️ moi.gov.mm ကို **မချိတ်နိုင်ပါ** — {rep['reason']} လို့ "
                f"index ကို မဆွဲနိုင်သေးပါ။\n"
                f"ℹ️ ဒါက 'သတင်းအသစ် မရှိပါဘူး' လို့ မဆိုလိုပါ။ လိုင်း/VPN စစ်ပြီး "
                f"`action='update'` ကို ပြန်ခေါ်ပါ။")
    lines = [f"✅ MOI index update ပြီးပါပြီ — အသစ် "
             f"{to_burmese_digits(rep['new'])} ခု သိမ်းပြီး၊ index စုစုပေါင်း "
             f"{to_burmese_digits(rep['total'])} ခု။"]
    for _slug, entry in rep["sections"].items():
        if entry.get("new") or entry.get("errors"):
            lines.append(f"  • {entry['label']}: အသစ် "
                         f"{to_burmese_digits(entry['new'])} / "
                         f"ကတ် {to_burmese_digits(entry['cards'])}"
                         + (f" (မဖတ်နိုင်တာ "
                            f"{to_burmese_digits(entry['errors'])})" if entry["errors"] else ""))
    if rep["errors"]:
        lines.append(f"⚠️ မဖတ်နိုင်တဲ့ သတင်း "
                     f"{to_burmese_digits(len(rep['errors']))} ခု — ကျန်တဲ့သတင်း "
                     f"အားလုံး သိမ်းပြီးပါပြီ။")
    lines.append(f"🕐 {rep['finished']}")
    return "\n".join(lines)


def _do_status(p: dict) -> str:
    """What the index holds and how fresh it is — including "never run"."""
    st = ix.status()
    lines = [f"📇 MOI index — သတင်း {to_burmese_digits(st['total'])} ခု"]
    if st["oldest"]:
        lines.append(f"  • ရက်စွဲ: {_mmd(st['oldest'])} → {_mmd(st['newest'])}")
    lines.append("  • နောက်ဆုံး crawl: "
                 + (st["last_run"] or "တစ်ခါမှ မ run ရသေးပါ"))
    if st["last_attempt_result"]:
        lines.append(f"  • နောက်ဆုံး ကြိုးစားမှု: {st['last_attempt_result']}")
    for entry in st["sections"][:12]:
        lines.append(f"  • {entry['label'] or entry['section']} — "
                     f"{to_burmese_digits(entry['count'])}")
    if not st["total"]:
        lines.append("ℹ️ index လွတ်နေပါတယ် — `action='update'` ခေါ်ပြီး "
                     "ဆွဲထားပါ။ မဆွဲခင် MOI မေးခွန်းတွေကို live ဆိုက်က "
                     "အဖြေပေးပါမယ်။")
    lines.append(f"  • DB: {st['db']}")
    return "\n".join(lines)


def moi_research(parameters: dict = None, player=None, session_memory=None,
                 **_) -> str:
    """Voice entry point.

    The signature is `(parameters, ...)` because `core/action_loader.py` calls a
    handler as `fn(parameters=parameters, ...)`. A handler written
    `fn(query="", **_)` swallows the whole argument dict and runs on defaults —
    six tools had this bug, and it was the costliest in the project.
    """
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    query = str(p.get("query") or "").strip()
    mention = str(p.get("mention") or "").strip()

    # **A `query` with no `action` means search.** Measured 2026-10-03: the
    # default was a list, the model passed only the query, and the tool listed
    # everything while throwing the question away — so the owner was told there
    # was no news about a trip the site covered in a dozen articles.
    if not action:
        action = "search" if (query or mention) else "status"

    try:
        if action in ("search", "find", "query"):
            text = _do_search(p)
        elif action in ("story", "article", "full", "read"):
            text = _do_story(p)
        elif action in ("numbers", "figures", "numbers_only"):
            text = _do_numbers(p)
        elif action in ("entities", "names", "who"):
            text = _do_entities(p)
        elif action in ("update", "crawl", "refresh"):
            text = _do_update(p)
        elif action in ("schedule", "install", "schedule_crawl"):
            text = schedule_crawl(_int(p.get("hour"), DEFAULT_HOUR, 0, 23),
                                  _int(p.get("minute"), DEFAULT_MINUTE, 0, 59))
        else:
            text = _do_status(p)
    except Exception as e:                                  # noqa: BLE001
        # The voice path must answer, never raise. The caller sees which
        # exception it was rather than an empty result that reads as "no news".
        text = f"⚠️ MOI research engine အလုပ် မလုပ်နိုင်ပါ — {type(e).__name__}: {e}"

    if session_memory:
        try:
            session_memory.set_last_search(
                query=f"moi_research {action} {query or mention}".strip(),
                response=text)
        except Exception:                                   # noqa: BLE001
            pass
    return text


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
# ONE dict per file. A second one here and the loader registers NEITHER, silently.
TOOL = {
    "name": "moi_research",
    "description": (
        "Search the MOI website (moi.gov.mm) archive **from a local index first**, "
        "and fall back to the **live site** when the index has nothing. This is the "
        "tool for a **keyword / topic / name / place / number** question about "
        "state news — where a stored index answers in 1–2 seconds and the site "
        "itself would need twenty requests.\n"
        "\n"
        "**Source of truth: `moi.gov.mm`.** The index is a crawl of the same site, "
        "and every answer says which one it used plus the crawl date, so the user "
        "can weigh it.\n"
        "\n"
        "action='search' (default when `query` is given) — index first, live site "
        "if the index misses. Use for: 'ရွှေဈေးနဲ့ပတ်သက်တဲ့သတင်းတွေ ရှာပေး', "
        "'မနေ့က နိုင်ငံတကာသတင်း ဘာတွေတင်ထားလဲ'. **Pass ONE or TWO words, never "
        "the whole question** — a phrase search matches nothing, and the tool then "
        "retries its own words and says which term worked. If a `days`/`date` "
        "filter is applied, the answer says how many undated articles it had to "
        "leave out.\n"
        "\n"
        "action='search' with `mention` + `kind` — an article that **names** a "
        "person, organisation or place (kind: 'people' | 'organizations' | "
        "'locations'). Use for: 'ဦးမင်းအောင်လှိုင်ကို mention လုပ်ထားတဲ့သတင်းတွေ "
        "ဒီတစ်ပတ်အတွင်း ရှာပေး'. This is a distinct-entity question — do NOT use "
        "a plain keyword search for it, which returns any article that repeats the "
        "word.\n"
        "\n"
        "action='story' — the full article text, from the index or live. Use for: "
        "'ဒီသတင်းကို အပြည့်အစုံ ဖတ်ပြပါ'. A search result list is not a document — "
        "its one-line snippet is too thin to summarise from, so **always call "
        "'story' on the relevant link before summarising an event**.\n"
        "\n"
        "action='numbers' — only the figures the article printed, each with the "
        "phrase around it. Use for: 'ဒီသတင်းထဲက ကိန်းဂဏန်းတွေကို သီးသန့်ပြောပြ'. "
        "action='entities' — the people, organisations and places an article names.\n"
        "\n"
        "action='status' (default when there is no query) — how many articles are "
        "indexed, the date range, and when the crawl last ran. Cheap.\n"
        "\n"
        "action='update' — crawl the site now and store what is new. **This takes "
        "SEVERAL MINUTES and it talks to the network.** Say you are updating first, "
        "then call it — a long silence with no warning reads as a crash. Normally "
        "unneeded: it runs by itself every day at 11:30 (Windows Task Scheduler "
        "task `JARVIS_MOI_Crawler`). If it reports the site was unreachable, **that "
        "is NOT 'there is no news'** — say so and try again later.\n"
        "\n"
        "action='schedule' — set or change the daily crawl time (`hour`/`minute`).\n"
        "\n"
        "NOT this tool: a section's **today / yesterday / latest** news — "
        "`moi_news` reads the live section and its date window, and must stay the "
        "answer to 'ဒီနေ့ နိုင်ငံတော်သမ္မတ သတင်းရှိလား'. The five topics the site "
        "has no section for (ပညာရေး · ကျန်းမာရေး · စီးပွားရေး · လူမှုရေး · "
        "သဘာဝဘေး) and 'search the database' — `news_section` / `reporter_news`. "
        "Fuel / gold prices — `gold_currency`. Myanmar and world news from "
        "independent outlets — `news_search` / `newsroom_search`.\n"
        "\n"
        "Four different 'not found' sentences, never merged: found; `မရှိပါ` = there "
        "is news but none in that window; `မတွေ့ပါ` = searched and found nothing; "
        "`မချိတ်နိုင်ပါ` = the site could not be reached, which is **not** the same "
        "as finding nothing. Never turn a failure or a limitation into 'there is "
        "no such news'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": ("search (default when `query` is given) | story | "
                                "numbers | entities | status | update | schedule."),
            },
            "query": {
                "type": "STRING",
                "description": ("One or two words in Burmese — the thing to find. "
                                "Do NOT pass the whole question: the search matches "
                                "phrases, so 'နိုင်ငံတော်သမ္မတ အိန္ဒိယ ခရီးစဉ်' finds "
                                "nothing while 'အိန္ဒိယ ခရီးစဉ်' finds the trip. "
                                "Do not translate."),
            },
            "mention": {
                "type": "STRING",
                "description": ("For a person/organisation/place that must be NAMED "
                                "in the article: pass the name here and set `kind`. "
                                "Example 'ဦးမင်းအောင်လှိုင်'. Do not translate."),
            },
            "kind": {
                "type": "STRING",
                "description": "people (default) | organizations | locations.",
            },
            "section": {
                "type": "STRING",
                "description": ("Optional narrow to one MOI section, in Burmese — "
                                "'နိုင်ငံတော်သမ္မတ', 'ဆောင်းပါး', 'ပြည်တွင်းသတင်း'. "
                                "Do not translate."),
            },
            "date": {
                "type": "STRING",
                "description": ("YYYY-MM-DD, one exact day. For two or more named "
                                "days call this tool once per day rather than "
                                "widening it to a `days` window."),
            },
            "days": {
                "type": "NUMBER",
                "description": ("How many days back from today (Yangon time): 1 = "
                                "today only, 2 = today and yesterday, 7 = the last "
                                "week. Use for 'ဒီနေ့' / 'မနေ့က' / 'ဒီတစ်ပတ်အတွင်း'."),
            },
            "limit": {
                "type": "NUMBER",
                "description": ("Max articles to show (default 8, max 20). Leave at "
                                "the default for a search — `limit=1` on a summary "
                                "question returns one unrelated article."),
            },
            "url": {
                "type": "STRING",
                "description": ("For action='story'/'numbers'/'entities': the "
                                "article path, e.g. '/news/88673'."),
            },
            "hour": {
                "type": "NUMBER",
                "description": "For action='schedule': hour, 0-23 (default 11).",
            },
            "minute": {
                "type": "NUMBER",
                "description": "For action='schedule': minute, 0-59 (default 30).",
            },
        },
        "required": [],
    },
    "handler": moi_research,
}


# ── Command line / Task Scheduler ────────────────────────────────────────────


def _scheduled_run() -> int:
    """The daily crawl, run unattended. **Prints and never raises.**

    Task Scheduler keeps stdout in the task's last-run result, so a failure has to
    be visible there: an unreachable site exits **2** and prints why, rather than
    exiting 0 with an empty index that reads as "nothing new today".
    """
    rep = ix.crawl(fetch_bodies=True)
    stamp = rep.get("finished") or rep.get("started") or ""
    if not rep.get("reachable"):
        print(f"[{stamp}] MOI crawl: UNREACHABLE — {rep.get('reason','')}",
              flush=True)
        return 2
    print(f"[{stamp}] MOI crawl: {rep['new']} new, {rep['total']} total", flush=True)
    if rep.get("errors"):
        print(f"[{stamp}] {len(rep['errors'])} unreadable: "
              f"{rep['errors'][:3]}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """`python actions/moi_research.py [--scheduled|--status|--update|--install-task]`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--scheduled" in argv:
        return _scheduled_run()
    if "--status" in argv:
        print(_do_status({}))
        return 0
    if "--update" in argv:
        print(_do_update({}))
        return 0
    if "--install-task" in argv:
        hour, minute = DEFAULT_HOUR, DEFAULT_MINUTE
        if "--at" in argv and argv.index("--at") + 1 < len(argv):
            try:
                raw = argv[argv.index("--at") + 1]
                hour, minute = int(raw.split(":")[0]), int(raw.split(":")[1])
            except (ValueError, IndexError):
                pass
        print(schedule_crawl(hour, minute))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())