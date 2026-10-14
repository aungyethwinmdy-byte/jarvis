"""Action: today_briefing — "ဒီနေ့ ဘာထူးလဲ" အတွက် အစီအစဉ်တကျ သတင်းအကျဉ်းချုပ်။

The owner's rule, 2026-10-13: when asked "ဒီနေ့ ဘာထူးလဲ", the briefing is
**today's MMT calendar day only** (not a trailing 36-hour window), in this
priority order:

    moi.gov.mm (live, section by section, today only):
        1. နိုင်ငံတော်သမ္မတ            (president-news)
        2. ဒုတိယသမ္မတသတင်းများ            (vice-presidents-news)
        3. လွှတ်တော်သတင်း                 (hluttaw-news — ဥက္ကဋ္ဌ/ဒုဥက္ကဋ္ဌများလည်း ဒီမှာပဲ)
        4. ပြည်ထောင်စုလွှတ်တော်       (pyidaungsu-hluttaw-news)
        5. ပြည်သူ့လွှတ်တော်             (pyithu-htuttaw-news)
        6. အမျိုးသားလွှတ်တော်         (amyotha-htuttaw-news)
        7. တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်သတင်း (commander-in-chief-news)

    ပြီးမှ လွတ်လပ်သောမီဒီယာ (newsroom DB, today only):
        8. BBC မြန်မာ
        9. ဧရာဝတီ (The Irrawaddy)

A section with no news today is skipped silently — "ရှိရင် ပြောမယ်" is the
rule, so an empty section is not announced as an event. If nothing at all was
published today, the answer says exactly that (မရှိပါ), never "မတွေ့ပါ".

Handler signature follows the whole codebase (see actions/weather_report.py):
    fn(parameters, player=None, session_memory=None) -> str

The voice path never raises: every failure becomes a sentence.
"""
from __future__ import annotations

from datetime import date

from core.timefmt import now_mmt, to_burmese_digits

# The owner's priority order — not the site's, not alphabetical.
_PRIORITY_SECTIONS = (
    "president-news",
    "vice-presidents-news",
    "hluttaw-news",
    "pyidaungsu-hluttaw-news",
    "pyithu-htuttaw-news",
    "amyotha-htuttaw-news",
    "commander-in-chief-news",
)
# (newsroom source_id, spoken label)
_INDEPENDENT = (
    ("bbcburmese", "BBC မြန်မာ"),
    ("irrawaddy", "ဧရာဝတီ"),
)
_MAX_PER_SECTION = 4

_MONTHS = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
           "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ",
           "ဒီဇင်ဘာ")


def _today_label(today: date) -> str:
    return (f"{to_burmese_digits(today.day)} {_MONTHS[today.month]} "
            f"{to_burmese_digits(today.year)}")


def _moi_sections(today_iso: str) -> list[tuple[str, list[dict]]]:
    """[(label, today's cards)] in priority order, skipping empty sections."""
    from core import moi_client as mc
    try:
        ok, _ = mc.available()
    except Exception:
        return []
    if not ok:
        return []
    out = []
    for slug in _PRIORITY_SECTIONS:
        try:
            cards = mc.list_section(slug, pages=4, until=today_iso)
        except Exception:
            continue
        todays = [c for c in cards if (c.get("issue_date") or "") == today_iso]
        if todays:
            label = mc.SECTION_LABEL.get(slug, slug)
            out.append((label, todays))
    return out


def _independent_news(today: date) -> list[tuple[str, list[dict]]]:
    """[(label, today's articles)] for BBC + Irrawaddy, skipping empties."""
    try:
        from core import newsroom_client as nr
    except Exception:
        return []
    try:
        ok, _ = nr.available()
    except Exception:
        return []
    if not ok:
        return []
    out = []
    for source_id, label in _INDEPENDENT:
        try:
            rows = nr.outlet_news(source_id, today, limit=5) or []
        except Exception:
            continue
        if rows:
            out.append((label, rows))
    return out


def today_briefing(parameters: dict | None = None,
                   player=None, session_memory=None, **_) -> str:
    today = now_mmt().date()
    today_iso = today.isoformat()

    lines = [f"📅 ဒီနေ့ ({_today_label(today)}) သတင်း", ""]
    total = 0

    moi = _moi_sections(today_iso)
    for label, cards in moi:
        lines.append(f"🏛️ **{label}** — {to_burmese_digits(len(cards))} ခု")
        for c in cards[:_MAX_PER_SECTION]:
            head = (c.get("headline") or "").strip()
            if head:
                lines.append(f"• {head}")
                total += 1
        lines.append("")

    ind = _independent_news(today)
    if ind:
        lines.append("🌍 **လွတ်လပ်သောမီဒီယာ**")
        for label, rows in ind:
            lines.append(f"— {label} ({to_burmese_digits(len(rows))} ခု)")
            for r in rows[:_MAX_PER_SECTION]:
                head = (r.get("title") or "").strip()
                if head:
                    lines.append(f"• {head}")
                    total += 1
            lines.append("")

    if total == 0:
        return (f"📅 ဒီနေ့ ({_today_label(today)}) အတွက် သတင်း **မရှိပါ**။\n"
                f"ℹ️ moi.gov.mm ကဏ္ဍတွေနဲ့ BBC/ဧရာဝတီ မှာ ဒီနေ့ထုတ် မတွေ့ပါ — "
                f"ဒါက ရှာမတွေ့တာ မဟုတ်ဘဲ ဒီနေ့ သတင်း မရှိတာပါ။")

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
        "briefing of **today's (MMT calendar day) news only** — not a trailing "
        "36-hour window. Priority order, exactly as the owner asked: "
        "moi.gov.mm sections first (နိုင်ငံတော်သမ္မတ → ဒုတိယသမ္မတ → လွှတ်တော်သတင်း "
        "→ ပြည်ထောင်စုလွှတ်တော် → ပြည်သူ့လွှတ်တော် → အမျိုးသားလွှတ်တော် → "
        "တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်), then BBC Burmese and The Irrawaddy from "
        "the newsroom DB. Sections with no news today are skipped. "
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
