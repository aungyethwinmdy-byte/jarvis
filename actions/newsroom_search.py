"""Search the AI Newsroom archive for a topic.

WHAT THIS ADDS OVER actions/today_briefing.py
    today_briefing answers "what's new today" from the newsroom's analysed
    reports — broad but shallow on any single subject.

    This reaches the part the briefing cannot: the archive. Every article PPIB,
    BBC Burmese, The Irrawaddy and DVB Burmese publish is collected hourly by
    AI Newsroom,
    analysed into a cross-source editorial report, and kept. So JARVIS can
    answer "has there been anything about X" from a curated, source-attributed
    store rather than from whatever a search engine feels like ranking today.

    (An older version of this docstring described daily_briefing as answering
    from the open web — DuckDuckGo and Google News RSS. That has been false
    since 2026-10-13: the briefing reads the newsroom DB only. Corrected.)

WHY THE QUERY IS NEVER TRANSLATED
    The newsroom's notes record a real bug: a Burmese question about Myanmar's
    president was translated to English before it reached the search layer and
    came back as a Colombian earthquake. The sources are Burmese, so an English
    query matches nothing. Whatever the user said is passed through unchanged.
"""
from actions._newsroom_common import show
from core import newsroom_client as nr


def newsroom_search(parameters, player=None, session_memory=None) -> str:
    params = parameters or {}
    query = params.get("query", "") or ""
    try:
        days = max(1, min(365, int(params.get("days", 120))))
    except (TypeError, ValueError):
        days = 120

    ok, reason = nr.available()
    if not ok:
        return f"သတင်းစောင့်ကြည့်စနစ်၏ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ အကြောင်းရင်း: {reason}"

    results = nr.search_articles(query, days=days, limit=8)
    text = nr.format_search(query, results)
    show(player, f"NEWSROOM SEARCH — {query[:40]}", text, items=results)
    print(f"[Newsroom] search {query!r} -> {len(results)} hit(s)")
    return text


TOOL = {
    "name": "newsroom_search",
    "description": (
        "Search the AI Newsroom archive — every article collected from PPIB, "
        "BBC Burmese, The Irrawaddy and DVB Burmese, analysed and stored — for a "
        "topic. Use "
        "this when the user asks whether there has been news about a specific "
        "subject, person, place or event: 'ဒီအကြောင်းအရာ သတင်းရှိလား', "
        "'ဘယ်လိုသတင်းတွေရှိလဲ', 'any news about X'. Pass the user's query "
        "EXACTLY as they said it — never translate it into English first, "
        "because the sources are Burmese and an English query matches nothing. "
        "For a general 'what's new today' question use daily_briefing instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "The topic to search for, in the user's own language, unchanged.",
            },
            "days": {
                "type": "INTEGER",
                "description": "How far back to look, in days. Default 120.",
            },
        },
        "required": ["query"],
    },
    "handler": newsroom_search,
}
