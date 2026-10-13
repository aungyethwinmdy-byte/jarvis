"""Voice entry point for the Burmese learning layer.

WHAT THE USER SAYS, AND WHAT IT DOES

    "မင်း 'မြန်မာ့အလင်း' လို့ ပြောတာ မှားတယ်"     → speech: try respellings
    "မင်း ငါပြောတာ 'ဆီဈေး' ကို 'ဆီဈေး' လို့ ကြားတယ်"  → wrong: record a correction
    "မြန်မာစာ ဘယ်လောက် သင်ပြီးလဲ"                → stats

THE TRIAL LOOP FOR PRONUNCIATION

    Nothing is stored until the user picks. `try` returns candidates and the
    assistant speaks each one; the user says which sounded right, and only then
    is it recorded. Storing a guess would change what he hears without him
    agreeing to it — and a wrong pronunciation is worse than a known-bad one,
    because he stops noticing it.

WHY IT ONLY LEARNS ON A CORRECTION

    Every utterance is logged so a correction can be made against it, but the
    log never becomes a rule. Learning passively would mean the assistant
    learning its own errors, and this file changes what the user hears — see
    `core/burmese_learning.py` for the full reasoning.
"""
from __future__ import annotations

from core.burmese_learning import (
    corrections,
    forget,
    heard_log,
    pronunciations,
    record_correction,
    record_pronunciation,
    stats,
    suggest_respellings,
)
from core.timefmt import to_burmese_digits


def burmese_learning(parameters: dict = None, player=None, session_memory=None,
                     **_) -> str:
    """Voice entry point.

    **The signature is `(parameters, ...)` and that is not cosmetic.**
    `core/action_loader.py` calls a handler as `fn(parameters=parameters, ...)`,
    so a handler written as `fn(action="stats", **_)` swallows the action and
    always reports the stats. Measured 2026-09-29 in a live session. See
    `actions/reporter_news.py` for the full note.
    """
    p = parameters or {}
    action = p.get("action", "")
    heard = p.get("heard", "")
    meant = p.get("meant", "")
    word = p.get("word", "")
    say_as = p.get("say_as", "")
    key = p.get("key", "")

    act = str(action or "stats").strip().lower()

    # ── he heard it wrong ────────────────────────────────────────────────────
    if act in ("wrong", "misheard", "correction"):
        if not heard or not meant:
            recent = heard_log(5)
            out = ["မှားကြားတာ မှတ်ဖို့ — ကြားတာနဲ့ ဆိုလိုတာ ၂ ခုလုံး လိုပါတယ်။", ""]
            if recent:
                out.append("မကြာသေးက ကြားခဲ့တာ (ဒီထဲက တစ်ခု ဖြစ်နိုင်တယ်):")
                for t in recent:
                    out.append(f"  • {t[:70]}")
            out.append("")
            out.append("ဥပမာ — 'မင်း ငါပြောတာ မြန်မာ့အလင်း ကို "
                       "မန်းမာအလင်း လို့ ကြားတယ်'")
            return "\n".join(out)
        return record_correction(heard, meant)

    # ── it says it wrong ─────────────────────────────────────────────────────
    if act in ("speech", "pronounce", "say"):
        if not word:
            known = pronunciations()
            if not known:
                return ("ဘယ်စကားလုံး ရွတ်တာ မှားလဲ ပြောပါ — "
                        "ဥပမာ 'မြန်မာ့အလင်း လို့ ရွတ်တာ မှားတယ်'")
            out = ["ရွတ်ဆိုပုံ မှတ်ထားတာ:", ""]
            for w, s in list(known.items())[:10]:
                out.append(f"  • {w} → {s}")
            return "\n".join(out)
        if say_as:
            return record_pronunciation(word, say_as)
        # No replacement given — offer candidates to listen to.
        options = suggest_respellings(word)
        if not options:
            return (f"'{word}' အတွက် ရွတ်ဆိုပုံ အဆိုပြုချက် မထုတ်နိုင်ပါ။\n"
                    f"ကိုယ်တိုင် ပြောပါ — 'ဒါကို ဒီလိုရွတ်' ဆိုပြီး "
                    f"ရွတ်ဆိုပုံ ရေးပါ။")
        out = [f"'{word}' အတွက် စမ်းကြည့်စရာ {to_burmese_digits(len(options))} မျိုး:", ""]
        for i, o in enumerate(options, 1):
            out.append(f"  {to_burmese_digits(i)}။ {o}")
        out.append("")
        out.append("တစ်ခုချင်း ရွတ်ပြမယ်။ ဘယ်ဟာ မှန်လဲ ပြောပါ — "
                   "ဥပမာ 'နံပါတ် ၂ မှန်တယ်'။")
        return "\n".join(out)

    # ── what has been learned ────────────────────────────────────────────────
    if act in ("stats", "status", "learned"):
        s = stats()
        out = ["မြန်မာစာ သင်ယူမှု အခြေအနေ:", "",
               f"  ကြားခဲ့တာ မှတ်ထားတာ : {to_burmese_digits(s['heard'])} ခု",
               f"  မှားကြားတာ ပြင်ထားတာ : {to_burmese_digits(s['corrections'])} ခု",
               f"  ရွတ်ဆိုပုံ မှတ်ထားတာ : {to_burmese_digits(s['pronunciations'])} ခု",
               "", f"  ဖိုင်: {s['store']}"]
        if not s["corrections"] and not s["pronunciations"]:
            out += ["", "⚠️ ဘာမှ မသင်ရသေးပါ — မှားတာ တစ်ခု ပြောပြမှ မှတ်မယ်။",
                    "မှားကြားရင် — 'မင်း X ကို Y လို့ ကြားတယ်'",
                    "ရွတ်မှားရင် — 'X လို့ ရွတ်တာ မှားတယ်'"]
        return "\n".join(out)

    # ── recent utterances, for finding the one that was misheard ─────────────
    if act in ("recent", "heard", "log"):
        rows = heard_log(15)
        if not rows:
            return "သိမ်းထားတဲ့ စကား မရှိသေးပါ။"
        out = ["မကြာသေးက ကြားခဲ့တာ (အနောက်ဆုံး):", ""]
        for t in rows:
            out.append(f"  • {t[:70]}")
        out.append("")
        out.append("တစ်ခု မှားနေရင် — 'မင်း X ကို Y လို့ ကြားတယ်'")
        return "\n".join(out)

    # ── remove a rule ────────────────────────────────────────────────────────
    if act in ("forget", "undo", "remove"):
        if not key:
            return "ဘာကို ဖျက်ရမလဲ ပြောပါ (စကားလုံး)။"
        kind = "pronunciation" if key in pronunciations() else "correction"
        return forget(kind, key)

    return f"Unknown burmese_learning action: '{action}'."


TOOL = {
    "name": "burmese_learning",
    "description": (
        "Teach JARVIS Burmese by correcting it, and see what it has learned. "
        "Use when the user says it misheard him, or that a word is pronounced "
        "wrongly. "
        "Actions: "
        "'wrong' with `heard` and `meant` — 'မင်း X ကို Y လို့ ကြားတယ်'. Learns a "
        "permanent transcription fix. **Only for a MISHEARING** — the user "
        "telling you the words you heard were not the words he said. It is NOT "
        "for the user saying your ANSWER was wrong: that is a disagreement about "
        "facts, and recording it here would permanently replace his question "
        "with a different sentence, so he could never ask it again. If he "
        "disagrees with an answer, re-check the source and say what you find — "
        "do not call this action; "
        "'speech' with `word` — 'X လို့ ရွတ်တာ မှားတယ်'. Returns candidate "
        "respellings; SPEAK each one, then ask which sounded right and call this "
        "again with `say_as` set to the one he picked. NEVER store a guess; "
        "'stats' — how much has been learned; "
        "'recent' — the last things it heard, for finding a misheard word; "
        "'forget' with `key` — remove a learned rule. "
        "Only a correction the user states is ever learned. Do not record "
        "anything on your own initiative."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "wrong | speech | stats | recent | forget",
            },
            "heard": {"type": "STRING", "description": "What it transcribed (wrong)."},
            "meant": {"type": "STRING", "description": "What the user actually said."},
            "word": {"type": "STRING", "description": "The word pronounced wrongly."},
            "say_as": {
                "type": "STRING",
                "description": "The respelling the user chose after hearing the options.",
            },
            "key": {"type": "STRING", "description": "The word to forget."},
        },
        "required": [],
    },
    "handler": burmese_learning,
}
