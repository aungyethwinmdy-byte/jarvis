"""Did other outlets carry that story — and how does their version differ?

THE SCOPE, STATED PLAINLY
    The newsroom collects three outlets: PPIB, BBC Burmese and The Irrawaddy. So
    "other outlets" means the other two, and that is what this searches —
    `coverage_in_other_outlets()` reads the same database the briefing does.

    An earlier version also read four live feeds from outside the newsroom (DVB,
    RFA, Myanmar Now, Than Lwin Times). It was removed on the user's instruction,
    and the reason is the design rather than the code: the newsroom is "one
    writer, one reader" and every article in it has been analysed, whereas a feed
    match is a headline matched on shared words. Listing the two together
    presented a word-match with the authority of an analysis. If wider coverage
    is wanted later it belongs in its own layer, clearly labelled, not folded
    into this answer.

    Those outlets are not part of the newsroom at all — they come from a separate
    registry (`config/api_keys.json → news_sources`, `actions/web_search.py →
    OUTLET_REGISTRY`). The two outlet lists are different lists; do not merge
    them by accident again.

WHY THIS IS NOT PART OF newsroom_search
    "Has there been anything about X" and "did anyone ELSE carry this specific
    story" are different questions with different failure modes. The first is a
    keyword search and a miss means nothing was written. The second compares one
    known story against other outlets, and a miss is a claim about those outlets
    that has to be scoped honestly — see format_comparison().
"""
from actions._newsroom_common import resolve_story, show
from core import newsroom_client as nr


def newsroom_compare_coverage(parameters, player=None, session_memory=None) -> str:
    params = parameters or {}
    try:
        window = max(1, min(7, int(params.get("window_days", 3))))
    except (TypeError, ValueError):
        window = 3

    ok, reason = nr.available()
    if not ok:
        return f"သတင်းစောင့်ကြည့်စနစ်၏ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ အကြောင်းရင်း: {reason}"

    story, note = resolve_story(parameters)
    if not story:
        return note

    report = nr.report_for(story["article_id"])
    coverage = nr.coverage_in_other_outlets(story, window_days=window)

    text = nr.format_comparison(story, coverage, report)
    if note:
        text = f"{note}\n\n{text}"

    show(player, f"NEWSROOM COMPARE — {story.get('source')}", text)
    print(f"[Newsroom] compare {story.get('article_id')} ({story.get('source')}) "
          f"-> {len(coverage)} of {len(nr.other_outlet_names(story))} other outlet(s) "
          f"carried it: {list(coverage)}")
    return text


TOOL = {
    "name": "newsroom_compare_coverage",
    "description": (
        "Check whether OTHER news outlets carried a specific story JARVIS has "
        "already read out, and show how their version compares — their headline, "
        "their framing, and what the reports share. Use this when the user asks "
        "whether a story is being reported elsewhere: 'ဒီသတင်း တခြားသတင်းဌာနတွေမှာ "
        "ဖော်ပြထားလား', 'တခြားဌာနတွေက ဘယ်လိုဖော်ပြလဲ', 'နှိုင်းယှဉ်ပြပါ', 'is this "
        "being reported elsewhere', 'how are other outlets covering this', "
        "'compare the coverage'. The newsroom monitors exactly three outlets — "
        "PPIB, BBC Burmese and The Irrawaddy — so the search covers the other two, "
        "and the answer names them. If none of them carried it, this says so "
        "plainly; report that faithfully and do not soften it into 'it might be "
        "elsewhere'. Pass the story's headline EXACTLY as it was read out in "
        "`query`, or its position in the list in `index` if the user referred to "
        "it by number."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": ("The headline of the story, in the user's own "
                                "language, copied from what was just read out. "
                                "Do not translate it."),
            },
            "index": {
                "type": "INTEGER",
                "description": ("The story's position in the list JARVIS last "
                                "read out: 1 = first, 2 = second."),
            },
            "window_days": {
                "type": "INTEGER",
                "description": ("How many days either side of the story's own "
                                "date to look. Default 3. Raise it only if the "
                                "user asks for a wider search."),
            },
        },
    },
    "handler": newsroom_compare_coverage,
}
