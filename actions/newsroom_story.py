"""A short summary of ONE story the user has just heard.

WHY THIS IS NOT JUST REPEATING THE BRIEFING LINE
    The briefing gives one sentence per item — enough to decide whether a story
    is worth following, not enough to know what it says. Behind every item sits
    the analyzer's Format A report: a one-minute summary in three bullets, plus
    the framing note. This reaches that, so "ဒီသတင်းကို အကျဉ်းချုပ်ပြောပါ" gets an
    answer that is shorter than the report and longer than the headline.

WHY THE STORY IS RESOLVED RATHER THAN TRUSTED
    The user is pointing at something they heard a moment ago, so the sentence
    contains no id — only words from the headline. See
    actions/_newsroom_common.resolve_story for the three kinds of reference and
    why each is handled separately. The important one: the headline JARVIS spoke
    comes from the REPORT, not from `news_articles.title`, so resolving it needs
    a report-text search. Measured 2026-09-27 — the four newest briefed
    headlines all missed the article search.

WHY IT ANSWERS WITH THE HEADLINE FIRST
    The user recognises the sentence they heard, not the stored title. Opening
    with a title they have never heard reads as "that is not the story I meant",
    and the whole answer is then suspect.
"""
from actions._newsroom_common import resolve_story, show
from core import newsroom_client as nr


def newsroom_story_summary(parameters, player=None, session_memory=None) -> str:
    ok, reason = nr.available()
    if not ok:
        return f"သတင်းစောင့်ကြည့်စနစ်၏ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ အကြောင်းရင်း: {reason}"

    story, note = resolve_story(parameters)
    if not story:
        return note

    report = nr.report_for(story["article_id"])
    text = nr.format_story_summary(story, report)
    if note:
        text = f"{note}\n\n{text}"

    show(player, f"NEWSROOM — {story.get('source')}", text, items=None)
    print(f"[Newsroom] story summary {story.get('article_id')} "
          f"({story.get('source')}) -> {len(report.get('bullets') or []) if report else 0} bullet(s)")
    return text


TOOL = {
    "name": "newsroom_story_summary",
    "description": (
        "A short spoken summary of ONE specific news story that JARVIS has "
        "already read out — the analyser's one-minute summary, in three bullets. "
        "Use this whenever the user points at a single item from the news just "
        "displayed and asks to hear more about it: 'ဒီသတင်း အကျဉ်းချုပ်ပြောပါ', "
        "'ဒုတိယသတင်းကို ရှင်းပြပါ', 'အဲဒီသတင်းအကြောင်း ပြောပါ', 'summarise that "
        "one', 'tell me more about the second story'. Pass the story's headline "
        "EXACTLY as it was read out in `query` — that is the most reliable "
        "handle. If the user referred to it by position, pass `index` instead "
        "(1 for the first item of the list you just read, 2 for the second). "
        "For comparing outlets use newsroom_compare_coverage; for a whole "
        "day's news use daily_briefing."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": ("The headline of the story, in the user's own "
                                "language, copied from what was just read out. "
                                "Do not translate it and do not shorten it."),
            },
            "index": {
                "type": "INTEGER",
                "description": ("The story's position in the list JARVIS last "
                                "read out: 1 = first, 2 = second. Use this when "
                                "the user said a number instead of a headline."),
            },
        },
    },
    "handler": newsroom_story_summary,
}
