"""Health of the news-watching pipeline, read aloud.

WHY THIS TOOL EXISTS AT ALL
    The newsroom runs unattended: an hourly collector, an analyzer, and a
    scheduler that are all invisible from the JARVIS window. When the news
    stops arriving there is no way to tell from outside whether the collector
    died, the analyzer is backed up, or nothing simply happened — which is the
    same "a switch that is off looks identical to broken code" trap this
    project has hit before with the greeting.

    So the pipeline reports its own state: how much is collected, how much is
    analysed, how much is stuck, and when the last cycle ran. If JARVIS says
    "no news yet", this is the tool that says why.
"""
from actions._newsroom_common import show
from core import newsroom_client as nr


def newsroom_status(parameters, player=None, session_memory=None) -> str:
    ok, reason = nr.available()
    if not ok:
        return f"သတင်းစောင့်ကြည့်စနစ်၏ ဒေတာဘေ့စ်ကို မချိတ်ဆက်နိုင်ပါ။ အကြောင်းရင်း: {reason}"

    text = nr.format_status(nr.pipeline_status())
    show(player, "NEWSROOM STATUS", text)
    print("[Newsroom] status requested")
    return text


TOOL = {
    "name": "newsroom_status",
    "description": (
        "Health report for the AI Newsroom news-watching pipeline, AND the list "
        "of news outlets it actually reads. Reports how many articles have been "
        "collected, how many are analysed, how many are still queued or failed, "
        "when the collector last ran, and then names every outlet in the archive "
        "with its article count and its newest item. Use this when the user asks "
        "which news outlets are being followed — 'ဘယ်သတင်းဌာနတွေ ရှိလဲ', "
        "'သတင်းဌာန ဘယ်နှစ်ခုလဲ', 'which sources do you read' — or whether the "
        "watcher is working, why there is no news, or how many articles are "
        "stored — 'သတင်းစောင့်ကြည့်စနစ် အလုပ်လုပ်နေလား', 'ဘာလို့ သတင်းမရတာလဲ'. "
        "Do NOT use this to answer what the news actually is."
    ),
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": newsroom_status,
}
