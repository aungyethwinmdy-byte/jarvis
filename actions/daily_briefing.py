"""Today's briefing — what is new — on request.

The user asks "ဒီနေ့ဘာထူးလဲ" and this answers.

WHERE THE NEWS COMES FROM — ONE SOURCE, DELIBERATELY
    The AI Newsroom (E:\\AI_NEWSROOM). Its collector runs hourly over PPIB, BBC
    Burmese and The Irrawaddy, and its analyzer turns each article into a
    cross-source editorial report. That store is the whole answer: curated,
    source-attributed, already analysed.

    There used to be a second source — the open web, via actions/web_search.py —
    used as a fallback when the newsroom was empty. It is gone, for two reasons.

    The first is the user's requirement, stated plainly: when they ask what news
    there is, they want what the three outlets put into Supabase, and only that.
    Folding Reuters and AP headlines into the same reply answers a question that
    was not asked, and leaves no way to tell at a glance which half a line came
    from. World news is still reachable — `web_search` reads the wires — but it
    is reached by ASKING for it ('ကမ္ဘာ့သတင်း ပြောပါ'), never by arriving
    uninvited inside the answer to a different question.

    The second is that the fallback had already stopped working: it imported
    `_briefing` from actions/web_search.py, that function was lost with the rest
    of the module, and the import raised every time. A dead fallback is worse
    than none — it reads like a safety net in the source while the answer it was
    supposed to guarantee can never arrive.

WHY THIS IS A TOOL AND NOT A STARTUP PUSH
    It used to be read out automatically on every launch, as phase 2 of the
    startup briefing. That makes every start a news broadcast, whether or not
    anything was wanted — and the user asked for it to wait until asked. The
    greeting (mingalaba, date, time, weather) still comes at startup; the news
    does not. Unprompted voice alerts, when they are wanted, are a separate
    opt-in feature with their own gates — see core/newsroom_watch.py.
"""
from actions._newsroom_common import show
from core import newsroom_client as nr

_LABEL = "DAILY BRIEFING"


def _newsroom_briefing() -> tuple[str, list[dict]]:
    """(the briefing text, the items it numbered).

    Both, not just the text: the numbered list is also what a later "the second
    one" resolves against, so the caller has to keep it. Returning only the text
    is what would make an item number unanswerable.
    """
    ok, reason = nr.available()
    if not ok:
        print(f"[Briefing] newsroom unavailable: {reason}")
        return "", []
    reports = nr.recent_reports(hours=36, limit=6)
    if not reports:
        return "", []
    return nr.format_briefing(reports), nr.briefing_items(reports)


def daily_briefing(parameters, player=None, session_memory=None) -> str:
    text, items = _newsroom_briefing()

    if not text:
        # The two empty results are different failures, only one of which is a
        # broken database. An unreachable Supabase is worth going to look at; a
        # newsroom that has simply not published a fresh report in the last 36
        # hours is a report about there being no report. `available()` tells
        # them apart, so the user hears the true one.
        ok, reason = nr.available()
        if not ok:
            text = (f"သတင်းစောင့်ကြည့်စနစ်၏ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ "
                    f"အကြောင်းရင်း: {reason}")
            source = "none"
        else:
            text = ("ပြီးခဲ့သော ၃၆ နာရီအတွင်း သတင်းသုံးသပ်ချက်အသစ် မတွေ့ရသေးပါ။ "
                    "ဒေတာဘေ့စ်က ချိတ်ဆက်မှုကောင်းနေပါတယ်။")
            source = "empty"
    else:
        source = "newsroom"

    print(f"[Briefing] source={source} — {text[:100]}")
    label = ("DAILY BRIEFING — AI Newsroom သုံးသပ်ချက်"
             if source == "newsroom" else _LABEL)
    show(player, label, text, items=items)
    return text


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "daily_briefing",
    "description": (
        "Today's news briefing from the three monitored outlets — PPIB, BBC "
        "Burmese and The Irrawaddy — read from the AI Newsroom database, each "
        "item with its source and publication time. Call this when the user "
        "asks what is new WITHOUT naming an outlet or a topic: 'ဒီနေ့ဘာထူးလဲ', "
        "'ဒီနေ့သတင်းပြောပါ', 'သတင်းဘာရှိလဲ', 'what's new today', 'morning "
        "brief', 'any news'. Never answer such a question from memory or from "
        "earlier in the conversation — call this and report what it returns.\n"
        "\n"
        "This is MYANMAR news only, from those three outlets. If the user asks "
        "for WORLD news by name ('ကမ္ဘာ့သတင်း ပြောပါ', 'world news'), use "
        "web_search instead. If the user names an outlet, use "
        "newsroom_outlet_news; for one specific topic or subject use "
        "newsroom_search; for the whole day merged into one report use "
        "newsroom_digest."
    ),
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": daily_briefing,
}
