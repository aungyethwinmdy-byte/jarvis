"""Action: today_briefing — "ဒီနေ့ ဘာထူးလဲ" အတွက် အစီအစဉ်တကျ သတင်းအကျဉ်းချုပ်။

The owner's rule, 2026-10-13, **updated 2026-10-17**: when asked "ဒီနေ့
ဘာထူးလဲ", the briefing covers **four outlets, about two stories each**:

    moi.gov.mm (live, the owner's own priority order):
        1. နိုင်ငံတော်သမ္မတ            (president-news)
        2. ဒုတိယသမ္မတသတင်းများ            (vice-presidents-news)
        3. လွှတ်တော်သတင်း                 (hluttaw-news — ဥက္ကဋ္ဌ/ဒုဥက္ကဋ္ဌများလည်း ဒီမှာပဲ)
        4. ပြည်ထောင်စုလွှတ်တော်       (pyidaungsu-hluttaw-news)
        5. ပြည်သူ့လွှတ်တော်             (pyithu-htuttaw-news)
        6. အမျိုးသားလွှတ်တော်         (amyotha-htuttaw-news)
        7. တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်သတင်း (commander-in-chief-news)
        8. ပြည်တွင်းသတင်း              (other-news)
        9. သတင်းများ                    (news)

    ပြီးမှ လွတ်လပ်သောမီဒီယာ (newsroom DB):
       10. BBC မြန်မာ
       11. ဧရာဝတီ (The Irrawaddy)
       12. ဒီဗွီဘီ (DVB Burmese)

WHY "TODAY ONLY" GOT A FALLBACK
    The 2026-10-13 rule was today's MMT calendar day only, and a section with
    no news was skipped silently. That produced a briefing the owner read as
    broken: asked on a quiet morning it named one outlet, and on a day MOI's
    office sections had not published it named none. The owner asked, on
    2026-10-17, for all four outlets to appear with about two stories each.
    So the rule is now: **today's stories win, and a source that published
    nothing today is not dropped** — it falls back to its newest story and the
    date is printed beside it, so a card from the 16th is never dressed up as
    today's. "ရှိရင် ပြောမယ်" still holds for *today*; it just no longer means
    silence from a quiet outlet.

A section that has published nothing at all still says so (မရှိပါ), never
"မတွေ့ပါ" — "there is no news" and "we could not find the news" are different
answers and only one of them is true here.

Handler signature follows the whole codebase (see actions/weather_report.py):
    fn(parameters, player=None, session_memory=None) -> str

The voice path never raises: every failure becomes a sentence.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from core.timefmt import now_mmt, to_burmese_digits

# The owner's priority order — not the site's, not alphabetical. The two
# general sections sit last: the office sections publish in bursts, while
# ပြည်တွင်းသတင်း (other-news) and သတင်းများ (news) are the ones that carry
# something most days, which is why the owner names "ပြည်တွင်းသတင်း" for MOI.
_PRIORITY_SECTIONS = (
    "president-news",
    "vice-presidents-news",
    "hluttaw-news",
    "pyidaungsu-hluttaw-news",
    "pyithu-htuttaw-news",
    "amyotha-htuttaw-news",
    "commander-in-chief-news",
    "other-news",
    "news",
)
# (newsroom source_id, spoken label)
_INDEPENDENT = (
    ("bbcburmese", "BBC မြန်မာ"),
    ("irrawaddy", "ဧရာဝတီ"),
    ("dvb", "ဒီဗွီဘီ"),
)
_PER_OUTLET = 2          # the owner's rule, 2026-10-17: about two per outlet
_LOOKBACK_DAYS = 7       # how far back to reach when an outlet is quiet today

_MONTHS = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
           "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ",
           "ဒီဇင်ဘာ")


def _today_label(today: date) -> str:
    return (f"{to_burmese_digits(today.day)} {_MONTHS[today.month]} "
            f"{to_burmese_digits(today.year)}")


def _short_day(day: date) -> str:
    return f"{to_burmese_digits(day.day)} {_MONTHS[day.month]}"


def _as_date(value) -> date | None:
    """Best-effort date from a datetime, date or ISO string; None if unknown."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _moi_news(today: date) -> list[dict]:
    """Up to _PER_OUTLET moi.gov.mm cards, each tagged with its section.

    Sections are asked in the owner's order and today's cards win. When no
    section published today, the newest card of each is offered instead so MOI
    still speaks; the card carries its date and the caller prints it.
    """
    from core import moi_client as mc
    try:
        ok, _ = mc.available()
    except Exception:
        ok = False
    if not ok:
        return []

    today_iso = today.isoformat()
    todays: list[dict] = []
    newest: list[tuple[date, dict]] = []
    seen: set[str] = set()
    for slug in _PRIORITY_SECTIONS:
        try:
            cards = mc.list_section(slug, pages=2, until=today_iso) or []
        except Exception:
            continue
        label = mc.SECTION_LABEL.get(slug, slug)
        for c in cards:
            cid = str(c.get("id") or "")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            when = _as_date((c.get("issue_date") or "")[:10])
            card = {**c, "_section": label, "_date": when}
            if when == today:
                todays.append(card)
            if when is not None:
                newest.append((when, card))
    if todays:
        return todays[:_PER_OUTLET]
    newest.sort(key=lambda pair: pair[0], reverse=True)
    return [card for _, card in newest[:_PER_OUTLET]]


def _outlet_news(source_id: str, today: date) -> list[dict]:
    """Up to _PER_OUTLET stories for one outlet — today's, or its newest.

    `outlet_news` already applies the MMT-day filter and its own dedup; walking
    back a few days is how a quiet outlet still contributes instead of
    vanishing from the briefing.
    """
    from core import newsroom_client as nr
    for back in range(_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=back)
        try:
            rows = nr.outlet_news(source_id, day, limit=_PER_OUTLET) or []
        except Exception:
            rows = []
        if rows:
            return rows
    return []


def _independent_news(today: date) -> list[tuple[str, list[dict]]]:
    """[(label, stories)] for BBC + ဧရာဝတီ + ဒီဗွီဘီ, skipping empties."""
    try:
        from core import newsroom_client as nr
        ok, _ = nr.available()
    except Exception:
        ok = False
    if not ok:
        return []
    out = []
    for source_id, label in _INDEPENDENT:
        rows = _outlet_news(source_id, today)
        if rows:
            out.append((label, rows))
    return out


def _moi_when(card: dict, today: date) -> str:
    """Section name always, plus the date when the card is not today's."""
    parts = []
    section = card.get("_section")
    if section:
        parts.append(section)
    when = card.get("_date")
    if when is not None and when != today:
        parts.append(_short_day(when))
    return " · ".join(parts)


def _row_when(row: dict, today: date) -> str:
    """The date to print for a newsroom story — '' when it is today's."""
    when = _as_date(row.get("published"))
    if when is None or when == today:
        return ""
    return _short_day(when)


def today_briefing(parameters: dict | None = None,
                   player=None, session_memory=None, **_) -> str:
    today = now_mmt().date()

    lines = [f"📅 ဒီနေ့ ({_today_label(today)}) သတင်း", ""]
    total = 0
    stale = False

    moi = _moi_news(today)
    if moi:
        lines.append(f"🏛️ **ပြည်တွင်းသတင်း (moi.gov.mm)** — "
                     f"{to_burmese_digits(len(moi))} ခု")
        for c in moi:
            head = (c.get("headline") or "").strip()
            if not head:
                continue
            when = _moi_when(c, today)
            lines.append(f"• {head}" + (f"  ({when})" if when else ""))
            if c.get("_date") != today:
                stale = True
            total += 1
        lines.append("")

    ind = _independent_news(today)
    if ind:
        lines.append("🌍 **လွတ်လပ်သောမီဒီယာ**")
        for label, rows in ind:
            lines.append(f"— {label} ({to_burmese_digits(len(rows))} ခု)")
            for r in rows:
                head = (r.get("title") or "").strip()
                if not head:
                    continue
                when = _row_when(r, today)
                lines.append(f"• {head}" + (f"  ({when})" if when else ""))
                if when:
                    stale = True
                total += 1
            lines.append("")

    if total == 0:
        return (f"📅 ဒီနေ့ ({_today_label(today)}) အတွက် သတင်း **မရှိပါ**။\n"
                f"ℹ️ moi.gov.mm၊ BBC၊ ဧရာဝတီ နဲ့ ဒီဗွီဘီ မှာ ဒီနေ့ထုတ် မတွေ့ပါ — "
                f"ဒါက ရှာမတွေ့တာ မဟုတ်ဘဲ ဒီနေ့ သတင်း မရှိတာပါ။")

    if stale:
        lines.append(f"ℹ️ စုစုပေါင်း {to_burmese_digits(total)} ပုဒ် — "
                     f"တချို့ဌာန ဒီနေ့ သတင်းမရှိလို့ နောက်ဆုံးရကို (ရက်စွဲပါ) "
                     f"ပြထားပါတယ်။")
    else:
        lines.append(f"ℹ️ စုစုပေါင်း {to_burmese_digits(total)} ပုဒ် — "
                     f"ဒီနေ့ ({_today_label(today)}) ထုတ်တွေသာ ပါတယ်။")
    return "\n".join(lines).rstrip()


def run(params: dict | None = None) -> str:
    """Direct call (tests, scripts)."""
    return today_briefing(params)


TOOL = {
    "name": "today_briefing",
    "description": (
        "**THE tool for 'ဒီနေ့ ဘာထူးလဲ' / 'ဒီနေ့သတင်း'.** A structured "
        "briefing of today's (MMT calendar day) news across **four outlets, "
        "about two stories each**: moi.gov.mm (its own priority order — "
        "နိုင်ငံတော်သမ္မတ → ဒုတိယသမ္မတ → လွှတ်တော်သတင်း → ပြည်ထောင်စုလွှတ်တော် → "
        "ပြည်သူ့လွှတ်တော် → အမျိုးသားလွှတ်တော် → တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ် → "
        "ပြည်တွင်းသတင်း → သတင်းများ), then BBC Burmese, The Irrawaddy and "
        "DVB Burmese from the newsroom DB. Today's stories are preferred; a "
        "source that published nothing today falls back to its newest story "
        "with its date printed, so it still appears and a card from yesterday "
        "is never read as today's. "
        "**Use this — not `daily_briefing`, not `web_search` — whenever the "
        "user asks what is new today.** `daily_briefing` (last 36h) is for "
        "'နောက်ဆုံးရ သတင်း' style questions without a day attached."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
    "handler": today_briefing,
}
