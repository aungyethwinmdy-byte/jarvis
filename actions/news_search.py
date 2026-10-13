"""Search both newsrooms at once — and never blend them.

WHY THIS TOOL EXISTS

    There are two databases behind this assistant and they hold different papers:

        reporter_*  — မြန်မာ့အလင်း, ကြေးမုံ (the state papers)
        newsroom_*  — PPIB, BBC Burmese, The Irrawaddy

    When the user names a paper, `main.py::_news_route()` sends the question to
    the right one. But *"ပညာရေးအကြောင်း သတင်းရှိလား"* names nothing, and the
    honest answer is that **both** databases have news about it. Routing that to
    one of them silently answers from half the sources.

THE RULE

    **Results are never merged.** Every line carries the paper it came from, and
    the answer is grouped by source with a count and a date range each. For a
    journalist *which paper said it* is not decoration — it is the difference
    between "the state papers reported" and "the BBC reported", and an answer
    that blends them is worse than no answer.

    It also means the two can disagree and the answer still makes sense. The
    state papers and The Irrawaddy do not always say the same thing about the
    same event, and that is the point of having both.

WHAT IT DOES NOT DO

    - It does not translate the query. Both databases are Burmese; a translated
      keyword matches nothing.
    - It does not rank across sources. There is no shared scale between a
      Supabase full-text score and a substring match, so the two lists are
      reported side by side rather than interleaved.
    - It does not hide a database that is down. If one cannot be reached the
      answer says so, because "no results" and "could not look" are different.
"""
from __future__ import annotations

from core.reporter_client import (
    available as reporter_available,
    date_range_for,
    display_headline,
    readable_only,
    search_count,
    search_articles as state_search,
)
from core.timefmt import to_burmese_digits

_MONTHS = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
           "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ",
           "ဒီဇင်ဘာ")


def _d(value) -> str:
    """A date as Burmese — accepts 'YYYY-MM-DD' or a datetime."""
    text = str(value or "")
    try:
        y, m, day = text[:10].split("-")
        return (f"{to_burmese_digits(y)} {_MONTHS[int(m)]} "
                f"{to_burmese_digits(int(day))} ရက်")
    except Exception:                                       # noqa: BLE001
        return text


def _short(value) -> str:
    text = str(value or "")
    try:
        _y, m, day = text[:10].split("-")
        return f"{_MONTHS[int(m)]} {to_burmese_digits(int(day))}"
    except Exception:                                       # noqa: BLE001
        return text


def _state_section(query: str, limit: int, days: int = 0) -> tuple[str, int]:
    """The state papers half. Returns (rendered text, count)."""
    n = search_count(query, days=days)
    if n < 0:
        return "  ⚠️ မြန်မာ့အလင်း/ကြေးမုံ database ကို မချိတ်နိုင်ပါ။", 0
    if n == 0:
        return "  (မတွေ့ပါ)", 0

    rng = date_range_for(query, days=days)
    span = ""
    if rng.get("oldest"):
        span = f" — {_d(rng['oldest'])} ကနေ {_d(rng['newest'])} အထိ"

    rows = readable_only(state_search(query, limit))
    lines = [f"  သတင်း {to_burmese_digits(n)} ခု{span}"]
    for a in rows:
        paper = (a.get("newspaper_name") or "").strip()
        page = a.get("page_no")
        page_s = f" စာမျက်နှာ {to_burmese_digits(page)}" if page else ""
        lines.append(f"    • [{paper}{page_s}] {display_headline(a)}")
    if n > len(rows):
        lines.append(f"    … (ပထမ {to_burmese_digits(len(rows))} ခု ပြထားတယ်)")
    return "\n".join(lines), n


def _newsroom_section(query: str, limit: int) -> tuple[str, int]:
    """The PPIB / BBC / Irrawaddy half. Returns (rendered text, count)."""
    try:
        from core import newsroom_client as nc
        ok, _why = nc.available()
        if not ok:
            return "  ⚠️ PPIB/BBC/Irrawaddy database ကို မချိတ်နိုင်ပါ။", 0
        rows = nc.search_articles(query, days=400, limit=limit)
    except Exception as exc:                                # noqa: BLE001
        return f"  ⚠️ ရှာလို့ မရပါ ({type(exc).__name__})", 0

    if not rows:
        return "  (မတွေ့ပါ)", 0

    lines = [f"  သတင်း {to_burmese_digits(len(rows))} ခု"]
    for a in rows:
        src = (a.get("source") or "?").strip()
        when = _short(a.get("published"))
        lines.append(f"    • [{src}{(' · ' + when) if when else ''}] "
                     f"{(a.get('title') or '').strip()}")
    if len(rows) >= limit:
        lines.append(f"    … (ပထမ {to_burmese_digits(limit)} ခု ပြထားတယ်)")
    return "\n".join(lines), len(rows)


def news_search(parameters: dict = None, player=None, session_memory=None,
                **_) -> str:
    """Search both newsrooms and report them separately.

    **The signature is `(parameters, ...)` and that is not cosmetic.**
    `core/action_loader.py` calls a handler as `fn(parameters=parameters, ...)`,
    so a handler written as `fn(query="", **_)` silently swallows the query and
    asks the user what to search for. Measured 2026-09-29 in a live session. See
    `actions/reporter_news.py` for the full note.

    `days` is the recency window — 2 when the user asked about *now*.
    """
    p = parameters or {}
    query = p.get("query", "")
    days = p.get("days", 0)
    limit = p.get("limit", 5)

    term = str(query or "").strip()
    if not term:
        return "ဘာအကြောင်း ရှာရမလဲ ပြောပါ။"

    try:
        limit = max(1, min(int(limit or 5), 10))
    except (TypeError, ValueError):
        limit = 5
    try:
        win = max(0, min(int(days or 0), 30))
    except (TypeError, ValueError):
        win = 0

    state_ok, _ = reporter_available()
    state_text, state_n = _state_section(term, limit, days=win)
    room_text, room_n = _newsroom_section(term, limit)

    scope = f" (လွန်ခဲ့တဲ့ {to_burmese_digits(win)} ရက်)" if win else ""
    out = [f"'{term}'{scope} — ရင်းမြစ် ၂ ခုလုံးမှာ ရှာတယ်:", ""]
    out.append("📰 မြန်မာ့အလင်း / ကြေးမုံ (နိုင်ငံပိုင်သတင်းစာ)")
    out.append(state_text)
    out.append("")
    out.append("📻 PPIB / BBC Burmese / The Irrawaddy")
    out.append(room_text)
    out.append("")

    total = state_n + room_n
    if total == 0:
        out.append("ရင်းမြစ် ၂ ခုလုံးမှာ မတွေ့ပါ။")
        if state_ok:
            out.append("⚠️ 'မရှိဘူး' လို့ မဆိုလိုပါ — ဒီ database တွေရဲ့ "
                       "ကာလအတွင်းမှာ မတွေ့တာပါ။")
    else:
        out.append(f"စုစုပေါင်း {to_burmese_digits(total)} ခု — "
                   f"နိုင်ငံပိုင် {to_burmese_digits(state_n)}၊ "
                   f"လွတ်လပ်တဲ့ {to_burmese_digits(room_n)}")
        out.append("")
        out.append("⚠️ ရင်းမြစ် ၂ ခုက မတူညီတဲ့ database တွေပါ — "
                   "ဘယ်သတင်းစာက ပြောလဲ ဆိုတာ အပေါ်မှာ ပြထားတယ်။")
    return "\n".join(out)


TOOL = {
    "name": "news_search",
    "description": (
        "Search BOTH news databases at once and report them separately: the "
        "state papers (မြန်မာ့အလင်း, ကြေးမုံ) and the independent outlets "
        "(PPIB, BBC Burmese, The Irrawaddy). "
        "Use when the user asks about a topic WITHOUT naming a paper — "
        "'ပညာရေးအကြောင်း သတင်းရှိလား', 'ဆီဈေး အကြောင်း ဘာရေးထားလဲ'. "
        "If the user NAMES a paper, use reporter_news or newsroom_search "
        "instead — this tool is for the unnamed case. "
        "Results are always labelled with their outlet; never merge them into "
        "one list. Pass the query in Burmese; do not translate it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Burmese keyword, e.g. 'ပညာရေး', 'ဆီဈေး'. Do not translate.",
            },
            "limit": {
                "type": "NUMBER",
                "description": "Max articles per database (default 5, max 10).",
            },
            "days": {
                "type": "NUMBER",
                "description": ("Recency window in days. Set 2 when the user says "
                                "လက်ရှိ / အခု / ဒီနေ့ / မနေ့ / now / current / "
                                "latest. Leave 0 when he names a date or month."),
            },
        },
        "required": ["query"],
    },
    "handler": news_search,
}
