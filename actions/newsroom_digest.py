"""The AI Newsroom's consolidated daily summary, read aloud.

WHY THIS IS SEPARATE FROM daily_briefing
    daily_briefing is the "latest few items" answer — a quick scan. This is the
    whole day merged into one report: every PPIB, BBC Burmese, The Irrawaddy
    and DVB Burmese article of the day, correlated across sources and written up
    as a single
    Format B digest by the newsroom's analyzer (see daily_digest.py there).

    A journalist wants both, and they are different questions: "what just
    happened" and "what happened today, all of it".

WHY IT IS CLEANED BEFORE SPEAKING
    The digest is written as Telegram HTML with emoji section markers, sized
    for reading rather than listening. clean_for_speech() strips the tags and
    emoji and converts ASCII digits to Burmese numerals, which is what
    core/timefmt.py established the spoken path needs.
"""
from actions._newsroom_common import show
from core import newsroom_client as nr


def newsroom_digest(parameters, player=None, session_memory=None) -> str:
    ok, reason = nr.available()
    if not ok:
        return f"သတင်းစောင့်ကြည့်စနစ်၏ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ အကြောင်းရင်း: {reason}"

    digest = nr.latest_digest()
    if not digest or not digest.get("full_report"):
        return ("သတင်းစောင့်ကြည့်စနစ်မှာ နေ့စဉ်အနှစ်ချုပ် "
                "အစီရင်ခံစာ မထုတ်ရသေးပါ။")

    # format_digest, not clean_for_speech: the digest carries its own date, so
    # a stale one cannot be mistaken for today's.
    text = nr.format_digest(digest)
    show(player, f"NEWSROOM DAILY DIGEST — {digest.get('target_date') or ''}", text)
    print(f"[Newsroom] digest {digest.get('target_date')} -> {len(text)} chars")
    return text


TOOL = {
    "name": "newsroom_digest",
    "description": (
        "The AI Newsroom's consolidated daily summary: everything PPIB, BBC "
        "Burmese and The Irrawaddy published today, merged into one report. "
        "Use when the user wants the whole day's picture rather than the "
        "latest few items — 'ဒီနေ့ သတင်းအနှစ်ချုပ် ပြောပါ', "
        "'today's summary', 'ဒီနေ့ ဘာတွေဖြစ်ခဲ့လဲ အားလုံး'. "
        "For the newest few items only, use daily_briefing instead."
    ),
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": newsroom_digest,
}
