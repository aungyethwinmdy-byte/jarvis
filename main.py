import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen


import sys as _sys

for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(_sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────

# Patch websockets AttributeError: 'ClientConnection' object has no attribute 'recv_messages'
# which occurs on early handshake abort / TLS reset in Python 3.13/3.14.
try:
    import websockets.asyncio.connection as _ws_conn
    _orig_ws_cl = _ws_conn.Connection.connection_lost
    def _safe_ws_connection_lost(self, exc):
        if not hasattr(self, "recv_messages"):
            return
        return _orig_ws_cl(self, exc)
    _ws_conn.Connection.connection_lost = _safe_ws_connection_lost
except Exception:
    pass

import asyncio
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt, MEMORY_SOURCES,
    save_session_summary, pop_last_session,
    search_memory, set_trim_notifier,
)

from actions.screen_processor  import _capture_camera, _capture_screen
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from actions.weather_report    import fetch_weather, fetch_weather_brief
from actions.maps_navigator    import maps_navigator
from memory.config_manager     import (
    get_brief_enabled, get_media_resolution, get_proactive_audio_enabled,
    get_push_to_talk_enabled, get_thinking_enabled, get_turn_tuning, get_voice,
    get_prebuilt_voice, is_custom_voice_name,
    get_wake_word_enabled, save_wake_word_enabled, get_input_device, get_output_device,
)
from core.plugin_loader        import discover_plugins
from core                      import timefmt
from core                      import undo as undo_stack
from core                      import confirm as confirm_gate
from core                      import audio_devices
from core.action_loader        import discover_actions
from core.echo                 import EchoGuard
from core.newsroom_watch       import NewsroomWatcher, poll_interval_seconds
from core.viseme               import VisemeStream
from core.wake_word            import (
    WakeWordDetector, is_ready as wake_is_ready, install_and_download as wake_install,
)

WAKE_SLEEP_TIMEOUT = 120.0

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
KNOWLEDGE_PATH  = BASE_DIR / "jarvis_knowledge.md"
LIVE_MODEL      = "models/gemini-3.8-live"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000 
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

_LEVEL_FLOOR = 60.0
_LEVEL_FULL  = 2600.0


def _pcm_level(samples) -> float:
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


_TAIL_MARGIN = 0.20
_VIS_WIN = 1024
_VIS_HOP = 480
_FIRST_SOUND = CHUNK_SIZE / RECEIVE_SAMPLE_RATE
_CURSOR_SLACK = 0.15

# ── The greeting's weather budget — two numbers that must agree ───────────────
# _get_json() spends its FIRST attempt on the whole timeout and gives the retry
# whatever is left, floored at _RETRY_MIN_SLICE (3.0s). So fetch_weather_brief()
# costs up to `timeout + 3.4s` before it gives up. Waiting only `timeout` on the
# outside therefore ALWAYS abandons the retry — the one case the retry exists
# for. Measured 2026-09-27, the console showed exactly that:
#     [JARVIS] Startup weather unavailable: TimeoutError()
#     [JARVIS] Briefing phase 1 (greeting) sent.
#     [Weather] ⚠️ TimeoutError — retrying once     <- orphaned thread
# The greeting went out with no weather, and the retry's answer was thrown away
# because the awaiting task had already given up. The executor thread is not
# cancellable, so it also ran to completion for nothing.
#
# _WEATHER_ATTEMPT = 3.5 keeps the healthy path untouched: Open-Meteo answers in
# 1.6-3.3s, so the first attempt still lands on its own. Measured on a full
# stall (192.0.2.1, unroutable), 3.5s inner gives up after **7.0s**, so the wait
# is 7.5. The old pair (5.0 wait against an 8.4s worst case) never had a chance.
# The price is 2.5s of extra worst-case silence, paid only when the network is
# already failing.
#
# check_greeting.py measures this pair rather than trusting it — change either
# number and that check fails instead of the greeting silently losing the
# weather.
_WEATHER_ATTEMPT = 3.5
_WEATHER_WAIT    = 7.5


def _pcm_visemes(samples, sr: int = 24000):
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size < _VIS_WIN:
            return []
        win = np.hanning(_VIS_WIN).astype(np.float32)
        freqs = np.fft.rfftfreq(_VIS_WIN, 1.0 / sr)
        b_f1_lo = (freqs >= 150) & (freqs < 450)
        b_f1_hi = (freqs >= 450) & (freqs < 1100)
        b_f2_bk = (freqs >= 600) & (freqs < 1300)
        b_f2_fr = (freqs >= 1700) & (freqs < 3200)
        b_hiss = (freqs >= 3800) & (freqs < 8000)

        out = []
        for start in range(0, x.size, _VIS_HOP):
            level = _pcm_level(x[start:start + _VIS_HOP])
            seg = x[start:start + _VIS_WIN]
            if seg.size < _VIS_WIN:
                seg = np.concatenate([seg, np.zeros(_VIS_WIN - seg.size, dtype=np.float32)])
            if level <= 0.0:
                out.append((0.0, 0.0, 0.0))
                continue
            mag = np.abs(np.fft.rfft((seg - seg.mean()) * win))
            f1l, f1h = float(mag[b_f1_lo].sum()), float(mag[b_f1_hi].sum())
            f2b, f2f = float(mag[b_f2_bk].sum()), float(mag[b_f2_fr].sum())
            hiss = float(mag[b_hiss].sum())

            openness = f1h / (f1l + f1h + 1e-6)
            width = (f2f - f2b) / (f2f + f2b + 1e-6)
            width *= (1.0 - openness) ** 0.8
            h = hiss / (f1l + f1h + f2b + f2f + hiss + 1e-6)
            openness *= 1.0 - 0.65 * min(1.0, h * 2.5)
            out.append((level, float(min(1.0, max(0.0, openness))), float(min(1.0, max(-1.0, width)))))
        return out
    except Exception:
        return []


def _describe_tools(declarations) -> str:
    lines = []
    for d in declarations or ():
        try:
            name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
            desc = (d.get("description") if isinstance(d, dict) else getattr(d, "description", "")) or ""
        except Exception:
            continue
        if not name:
            continue
        desc = " ".join(str(desc).split())
        lines.append(f"- {name}: {desc[:150]}" if desc else f"- {name}")
    return "\n".join(lines)


def _describe_limits(has_vision: bool, has_mic: bool) -> str:
    out = [
        "- Anything not listed above is outside your reach. Say so in Burmese plainly and offer the nearest alternative.",
        "- You act on this machine only. You cannot reach the user's other devices without explicit tools.",
        "- You remember what is in the memory block and what has been said this session.",
    ]
    if has_vision:
        out.append("- Your sight is not continuous. You see nothing until you call a vision tool.")
    else:
        out.append("- You have no sight at all in this build.")
    if has_mic:
        out.append("- You hear nothing while the microphone is muted.")
    return "\n".join(out)


def _render_prompt(template: str, values: dict) -> str:
    out = template or ""
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS. Always reply politely, naturally and directly in Burmese (မြန်မာဘာသာ). "
            "Address the user as 'ဆရာ'. Never guess results — always call the appropriate tool."
        )


def _load_knowledge_base() -> str:
    """Load the JARVIS Knowledge Base for policy/government reference.

    The knowledge base contains Myanmar government policies, security facts,
    economic data, and other reference information from October 2026.
    It is loaded as READ-ONLY reference context, not as instructions to follow.
    """
    try:
        content = KNOWLEDGE_PATH.read_text(encoding="utf-8")
        return (
            f"[KNOWLEDGE BASE — READ-ONLY REFERENCE]\n"
            f"Use the information below as a factual reference when answering questions\n"
            f"about Myanmar governance, policy, security, economy, agriculture,\n"
            f"and other topics covered in this knowledge base.\n"
            f"If a question is not answered by this data, say so — do not guess.\n\n"
            f"{'─' * 60}\n\n"
            f"{content}\n\n"
            f"{'─' * 60}\n"
            f"[END KNOWLEDGE BASE]\n"
        )
    except Exception:
        return ""

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)
_REPEAT_MIN = 12


def _is_repeat_chunk(txt: str, buf: list) -> bool:
    if len(txt) < _REPEAT_MIN:
        return bool(buf) and txt == buf[-1]
    joined = " ".join(buf)
    return txt in joined


def _is_duplicate_reply(new: str, prev: str) -> bool:
    """True when `new` repeats `prev` rather than adding to it.

    THE OLD TEST WAS `new in prev`, AND IT DECIDES WHETHER THE ASSISTANT SPEAKS.
        `_speak_cloned` is gated on the same string, so a false positive here is
        not a tidy log — it is silence, with nothing to say why. A short reply
        that happens to sit inside a longer earlier one ("ဟုတ်ကဲ့" after any
        reply that contained it) was being thrown away.

    A repeat now has to be most of the previous reply, not merely part of it.
    A character-overlap ratio was tried first and rejected: Burmese reuses
    letters so heavily that two genuinely different sentences scored above 90%
    ("ဒီနေ့ သတင်းတွေ ပြောပြပါမယ်" against "မနေ့က သတင်းတွေ ပြောပြခဲ့ပါတယ်"), which
    would have thrown away new answers to fix a rarer problem.
    """
    new, prev = (new or "").strip(), (prev or "").strip()
    if not new or not prev or len(new) < _REPEAT_MIN:
        return False
    if new == prev:
        return True
    return new in prev and len(new) >= 0.8 * len(prev)


# ── The news route, enforced in code ─────────────────────────────────────────
#
# `actions/web_search.py`'s own description says "DO NOT USE THIS FOR A NEWS
# QUESTION ABOUT WHAT IS HAPPENING" and names the tool each phrasing belongs to.
# That is a sentence in a description, not a rule in code, and the model can
# ignore it — it did: a question about Myanmar's president came back as a
# Colombian earthquake, which is in this project's own notes. The description
# stays, because the model still has to choose well; this is the part that does
# not depend on it choosing well.
#
# DELIBERATELY NARROW. A news question is a news word AND a question marker, and
# a request for world news is left alone because that is precisely what
# web_search is for. An eager rule would send "where do I buy a newspaper" to
# the newsroom, which is worse than the problem it fixes. It only ever fires on
# web_search, so the newspaper tool and the world-news path are untouched.
_NEWS_WORDS     = ("သတင်း", "ဘာထူး", "news")
_QUESTION_MARKS = ("လား", "လဲ", "?", "any", "is there", "what")
_WORLD_MARKERS  = ("ကမ္ဘာ့", "ကမ္ဘာ", "နိုင်ငံတကာ", "world news", "international")
_TODAY_MARKERS  = ("ဒီနေ့", "today", "ဘာထူး")
# `သတင်းစာ` is a newspaper, and a newspaper is the newspaper tool's job. Without
# this, "where do I buy a newspaper" contains "သတင်း" and would be sent to the
# newsroom — a false positive worse than the miss this whole gate exists for.
_NOT_NEWS       = ("သတင်းစာ",)

# …but the guard above is too broad, and it silenced a real question. Measured
# 2026-09-30: *"ဒီနေ့ သတင်းစာထဲ ဘယ်သူတွေ ပါလဲ"* — "who is in today's newspaper" —
# contains သတင်းစာ and was therefore treated as "where do I buy one" and sent
# nowhere. Asking **who or what the paper contains** is the opposite of asking
# where to buy it, so the content markers below win over `_NOT_NEWS`: when the
# question is about the paper's *contents*, it is a news question.
_CONTENT_WORDS  = ("ထဲ", "ပါသလား", "ပါလား", "ပါလဲ", "အကြောင်းအရာ", "ဘယ်သူ",
                   "ဘယ်ဝန်ကြီး", "ဖော်ပြ", "ပါဝင်", "inside", "contain")

# How many times the model may call the same tool with the same arguments before
# it is told to answer instead. Two is deliberate: the first call is the work,
# the second is a legitimate retry after a transient failure — the third means
# the model is not reading what it got back. See `_execute_tool`.
_MAX_IDENTICAL_CALLS = 2


def _tool_call_key(name: str, args: dict) -> tuple:
    """A stable identity for one tool call. Arguments are part of it.

    So `newspaper(မြန်မာ့အလင်း)` and `newspaper(ကြေးမုံ)` are two different
    calls and both run — only an *identical* repeat counts against the limit.
    Unserialisable arguments fall back to `str`, which is still stable enough
    to catch a loop.
    """
    try:
        return (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
    except Exception:                                       # noqa: BLE001
        return (name, str(args))


def _count_calls(history: list, key: tuple) -> int:
    """How many times `key` has already been recorded."""
    return history.count(key)

# ── Two newsrooms, and they are not interchangeable ──────────────────────────
#
# There are two databases behind this assistant and they hold different papers:
#
#   newsroom_*  — PPIB, BBC Burmese, The Irrawaddy   (yrzvwsqafmftbrfwimsf)
#   reporter_*  — မြန်မာ့အလင်း, ကြေးမုံ (the state papers)  (zdsxuxwonkovuesjepfa)
#
# Measured 2026-09-29 before this list existed: **"မြန်မာ့အလင်းမှာ ပညာရေး
# သတင်း ရှိလား" was routed to `newsroom_search`** — which reads the other
# database and does not contain မြန်မာ့အလင်း at all. The user would have been
# answered from the wrong papers, silently. Naming a paper is the strongest
# signal available about which database to read, so it is checked first.
_STATE_PAPERS   = ("မြန်မာ့အလင်း", "မြန်မာ့အလင်း", "ကြေးမုံ", "ကျေးမုံ",
                   "နိုင်ငံပိုင်သတင်းစာ", "state paper", "kyemon", "myanma alinn")
_INDEPENDENT    = ("ppib", "bbc", "ဘီဘီစီ", "irrawaddy", "ဧရာဝတီ", "independent")
# A price or a figure is `gold_currency`' job, and neither newsroom holds one.
_FIGURE_WORDS   = ("ဈေး", "ဈေးနှုန်း", "နှုန်း", "price", "rate", "ဘယ်လောက်")
# The state offices live on moi.gov.mm, not in the independent newsroom and not
# in the state *papers*. Measured 2026-10-03: \"ဒုတိယသမ္မတ သတင်း ရှာပေး\" fell
# through to `newsroom_search` — the wrong archive for the president's office.
# `သမ္မတ` alone matches both offices (ဒုတိယသမ္မတ contains it); a question that
# names a paper or a section is already routed above, and naming an independent
# outlet still wins below.
_STATE_OFFICES  = ("နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ", "သမ္မတ")

# ── A SECTION question is not a KEYWORD question ─────────────────────────────
#
# The owner's ask, 2026-09-30: *"ငါက ဂျာဗစ်ကိုမေးလိုက်ရင် … နိုင်ငံတော်သမ္မတ သတင်း
# ဒီနေ့ဘာရှိလဲလို့မေးရင် နိုင်ငံတော်သမ္မတ ကဏ္ဍကို သွားပြီး သိမ်းဆည်းထားတဲ့
# သတင်းကိုပြောပြရမယ်။"* The papers are indexed into sections, and that question
# reads a section — it is not a keyword sweep.
#
# **The two markers are both required, and that is the whole design.** A section
# word alone is not enough, and neither is a "what is in it" marker alone:
#
#   `ဒီနေ့ သတင်းစာထဲ ဒုတိယသမ္မတ ပါလား`            section word, no marker → NOT
#   `ဒီနေ့ နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ …ရှိလား`    section words, `ရှိလား`  → NOT
#   `သဘာဝဘေးသတင်းတွေ တက်လား`                      section word, no marker → NOT
#   `ဒီနေ့ နိုင်ငံတော်သမ္မတ သတင်း ဘာရှိလဲ`          section word + `ဘာရှိလဲ`  → YES
#
# The first three are `reporter_news` questions — "who is named", "is there
# any", "did it rise" — and all three are asserted by `check_agent.py`. `ရှိလား`
# is therefore **deliberately not** a marker: it asks *whether there is any*,
# which `reporter_news action='search'` answers with a count and a date range,
# while `ဘာရှိလဲ` / `ပြောပြ` / `ဖတ်ပြ` ask *what is in it*, which is the section.
#
# `သတင်းစာ` is removed before the test because it contains `သတင်း` — without
# that, "is there any news in today's newspaper about X" would read as a section
# question on the strength of the word "newspaper".
_SECTION_WORDS  = ("နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ", "ပြည်ထောင်စုဝန်ကြီး",
                   "ဆောင်းပါး", "အယ်ဒီတာအာဘော်", "အယ်ဒီတာ့အာဘော်",
                   "နိုင်ငံရေး", "စီးပွားရေး", "လူမှုရေး", "ပညာရေး",
                   "ကျန်းမာရေး", "သဘာဝဘေး")
_SECTION_ASK    = ("ကဏ္ဍ", "ဘာရှိလဲ", "ဘာတွေရှိလဲ", "ဘာရှိသလဲ", "ဘာတွေလဲ",
                   "ပြောပြ", "ဖတ်ပြ", "ပြပါ", "ဖော်ပြ", "what's in", "whats in")


def _is_section_question(query: str) -> bool:
    """True when the question names a section and asks what it holds."""
    q = (query or "").strip().lower()
    if not q:
        return False
    q = q.replace("သတင်းစာ", "")
    return (any(w in q for w in _SECTION_WORDS)
            and any(a in q for a in _SECTION_ASK))


def _news_route(query: str) -> str:
    """'' when this is not a news question, else the tool that should answer it."""
    q = (query or "").strip().lower()
    if not q:
        return ""
    # A **section** question leads, and it has to: it names a paper as often as
    # not ("ဒီနေ့ ကြေးမုံမှာ စီးပွားရေး သတင်း ပြောပြ"), and the paper branch below
    # would claim it for `reporter_news` — which would answer a *keyword* count
    # about the word `စီးပွားရေး` instead of reading the section. See
    # `_is_section_question` for the two markers this needs and the three
    # questions it deliberately leaves alone.
    if _is_section_question(q):
        return "news_section"
    # A named state paper wins over everything, including the `သတင်းစာ` guard:
    # "ကြေးမုံ သတင်းစာမှာ ဆီဈေး ဘယ်လောက်လဲ" is about that paper, not about
    # where to buy one.
    if any(w in q for w in _STATE_PAPERS):
        return "reporter_news"
    if any(w in q for w in _FIGURE_WORDS) and any(w in q for w in ("ဈေး", "နှုန်း", "price")):
        return "gold_currency"
    if any(w in q for w in _NOT_NEWS) and not any(w in q for w in _CONTENT_WORDS):
        return ""
    # A paper-content question reaches `reporter_news` even with no paper named.
    # Measured 2026-09-30: "ဒီနေ့ သတင်းစာထဲ ဘယ်ဝန်ကြီးတွေ ပါသလဲ" fell through to
    # the `ဒီနေ့` branch below and returned today's newsroom headlines — a
    # different question, answered confidently. `ထဲ` / `ပါသလား` mark the
    # question as *about a paper's contents*, and asking what the papers hold is
    # the state-paper tools' job whether or not the user named one.
    if any(w in q for w in _NOT_NEWS) and any(w in q for w in _CONTENT_WORDS):
        return "reporter_news"
    if not any(w in q for w in _NEWS_WORDS):
        return ""
    if any(w in q for w in _WORLD_MARKERS):
        return ""                      # world news is what web_search is for
    # A state-offices question (သမ္မတ / ဒုတိယသမ္မတ) belongs to moi.gov.mm —
    # see _STATE_OFFICES above for the measured miss this fixes. Placed before
    # _INDEPENDENT on purpose: an outlet name is checked first below only when
    # no office was named, and `သမ္မတ` is a substring of `ဒုတိယသမ္မတ` so one
    # member would be redundant — but all three are kept explicit for reading.
    #
    # It routes to `moi_news`, NOT `moi_research`. Measured 2026-10-04: the
    # owner's *"ဒုတိယသမ္မတ ဦးညိုစော သတင်းရှိလား"* reached moi_research and came
    # back from the saved index ("ဒီအဖြေက သိမ်းထားတဲ့ MOI index ထဲကပါ") — the
    # memory complaint — while the live vice-presidents-news section already held
    # the same story with its date. `moi_news` reads the section live and, when
    # today's window is empty, names the nearest article instead of stopping at
    # "မရှိပါ". A search that wants the whole archive still reaches `moi_research`
    # through the model, whose descriptions point archive/keyword questions there.
    if any(w in q for w in _STATE_OFFICES) and "ဘီဘီစီ" not in q and "bbc" not in q:
        return "moi_news"
    if any(w in q for w in _INDEPENDENT):
        return "newsroom_search"
    if not any(m in q for m in _QUESTION_MARKS):
        return ""
    if any(m in q for m in _TODAY_MARKERS):
        return "daily_briefing"
    # Neither paper named and no price asked. The question could belong to
    # either database — "ပညာရေးအကြောင်း သတင်းရှိလား" is answerable from both.
    # The newsroom keeps it, because it is the one the assistant has answered
    # from since before the state papers were reachable, but the tool
    # descriptions now say the other exists so the model can ask or look twice.
    return "newsroom_search"

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "system_status",
        "description": "Returns real-time system metrics: CPU, RAM, GPU, temperature. Use when user asks about computer performance.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "get_current_time",
        "description": (
            "Returns the exact current date and time in Myanmar Standard Time "
            "(UTC+6:30), already formatted in Burmese. Call this whenever the "
            "user asks the time or date, and before referring to 'today', "
            "'now', 'this morning' or how long ago something happened — the "
            "session may have been open for hours."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "screen_process",
        "description": "Captures screen or webcam to analyze. Call when user asks what is on screen or webcam.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' or 'camera'"},
                "text":  {"type": "STRING", "description": "Question in English"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": "Closes webcam view when asked.",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "manage_monitor",
        "description": "Manage background monitoring topics (add, remove, list).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "add | remove | list"},
                "topic": {"type": "STRING", "description": "Topic to monitor"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_jarvis",
        "description": "Shuts down the assistant when user says goodbye or tells it to stop.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "save_memory",
        "description": (
            "Save user personal facts silently to memory. Values must be in English. "
            "Set source='user' ONLY when the user stated the fact themselves; leave it "
            "out when you worked it out from context, because an inferred fact is "
            "labelled as yours and you must not later present it as something they said. "
            "Use category='lessons' for your OWN mistakes — 'I read this page wrong', "
            "'I asked for confirmation after starting the job' — so they are not repeated."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING"},
                "key":   {"type": "STRING"},
                "value": {"type": "STRING"},
                "source": {
                    "type": "STRING",
                    "enum": ["user", "model"],
                    "description": "'user' if they said it, 'model' if you inferred it.",
                },
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": "Look up remembered facts about the user from local storage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING"},
            },
            "required": [],
        },
    },
    {
        "name": "undo",
        "description": "Reverse last changes made by JARVIS.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
            },
            "required": [],
        },
    },
    {
        "name": "maps_navigator",
        "description": (
            "Google Maps navigation, places finder, and user current location. "
            "Call this whenever the user asks about their location ('ငါ့တည်နေရာ', "
            "'ငါဘယ်ရောက်နေလဲ', 'လက်ရှိရောက်နေတဲ့နေရာ', 'my location', 'where am I'), "
            "or wants to view/open their location on Google Maps ('google map နဲ့ ပြ', 'map ဖွင့်ပြ'), "
            "or asks for travel directions/duration between points (modes: driving, "
            "walking, transit), or searches for nearby places/hospitals/restaurants. "
            "Output is formatted in clean, natural Burmese with Google Maps links."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "enum": ["directions", "places", "current_location"],
                    "description": "Operation to perform: 'directions' to navigate, 'places' to search places, 'current_location' to get user's current or home location.",
                },
                "open_map": {
                    "type": "BOOLEAN",
                    "description": "Set to true to automatically open Google Maps in the web browser (e.g. user asks 'google map နဲ့ ပြ', 'map ပေါ်မှာ ပြ', 'ဖွင့်ပြ').",
                },
                "origin": {
                    "type": "STRING",
                    "description": "Starting location for directions (e.g. 'Yangon Central Railway Station', 'Sule Pagoda').",
                },
                "destination": {
                    "type": "STRING",
                    "description": "Destination location for directions (e.g. 'Shwedagon Pagoda', 'Mandalay Hill').",
                },
                "mode": {
                    "type": "STRING",
                    "enum": ["driving", "walking", "transit"],
                    "description": "Travel mode: 'driving' (default), 'walking', or 'transit'.",
                },
                "query": {
                    "type": "STRING",
                    "description": "Search term for places (e.g. 'restaurants', 'hospitals', 'hotels', 'coffee shops', 'Grand Hantha').",
                },
                "location": {
                    "type": "STRING",
                    "description": "City or area to search in (e.g. 'Yangon', 'Mandalay', 'Dagon').",
                },
            },
            "required": [],
        },
    },
]

class _ReconnectSignal(Exception):
    def __init__(self, keep_context: bool = True):
        super().__init__()
        self.keep_context = keep_context


def _is_reconnect_signal(exc: BaseException) -> bool:
    if isinstance(exc, _ReconnectSignal):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_reconnect_signal(sub) for sub in exc.exceptions)
    return False


def _keep_context_of(exc: BaseException) -> bool:
    if isinstance(exc, _ReconnectSignal):
        return getattr(exc, "keep_context", True)
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            if _is_reconnect_signal(sub):
                return _keep_context_of(sub)
    return True


def _closest_names(name: str, known, limit: int = 3) -> list[str]:
    """The declared tool names closest to `name`, best match first.

    Measured 2026-10-01 in a live session: asked *"မနေ့က ဒုတိယသမ္မတ သတင်းတွေရှိလား"*,
    the model called `moi_news` correctly, then called **`yarvis_news`** — a
    misspelling of `jarvis_news`, a name it had only ever seen inside the
    `moi_news` description as a tool *not* to use. The dispatcher answered with
    the bare string `Unknown tool: yarvis_news`, which gives the model nothing it
    can act on, so it asked again with the same wrong name and burned a turn.

    Ranking by shared letters turns a dead end into a correction. `difflib` is
    stdlib and the cutoff is deliberately loose — a transposition or a dropped
    letter is the common case here, not a random name.
    """
    import difflib
    try:
        return difflib.get_close_matches(str(name), sorted(known), n=limit, cutoff=0.6)
    except Exception:                                       # noqa: BLE001
        return []


class JarvisLive:
    def __init__(self, ui: JarvisUI):
        self.ui               = ui
        self._asst_name       = "JARVIS"
        self.session          = None
        self.audio_in_queue   = None
        self.out_queue        = None
        self._loop            = None
        self._is_speaking     = False
        self._speaking_lock   = threading.Lock()
        self._phone_active    = False
        self._pending_vision  = None
        self._vision_cam_active = False
        self._vision_close_pending = False
        self._vision_last_time = 0.0
        self._vision_busy      = False
        self._interrupted      = False
        self._visemes          = VisemeStream()
        self._last_out_logged  = ""
        self._ptt_enabled      = False
        self._ptt_held         = False
        self._ptt              = None
        self._out_level        = 0.0
        self._echo             = EchoGuard()
        self._out_latency      = 0.20
        self._tail_until       = 0.0
        self._play_cursor      = 0.0

        self.ui.on_push_to_talk   = self.set_push_to_talk
        self.ui.ptt_hold          = self._on_ptt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_voice_change   = self._on_voice_change
        self.ui.on_audio_device_change = self._on_audio_device_change
        self._reconnect_event: asyncio.Event | None = None
        self._reconnect_keep = True
        self._go_away_seen   = False
        self._expecting_go_away = False

        self._resume_handle: str | None = None
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard        = None
        self._briefing_sent    = False
        self._sys_monitor      = SystemMonitor()
        self._proactive        = ProactiveEngine()
        self._newsroom_watch   = NewsroomWatcher(logger=self.ui.write_log)
        self._last_user_speech = time.monotonic()
        self._session_log: list[str] = []

        self._enhanced_live = False
        self._tuned_live    = True

        # ── Cloned voice (the second audio path) ─────────────────────────────
        # Empty while a prebuilt voice is selected, in which case the Live audio
        # is played exactly as before. Non-empty while a cloned voice is
        # selected: the Live audio is then discarded and the reply is
        # synthesised locally — see _receive_audio and _cloned_worker.
        self._cloned_voice   = ""
        self._cloned_stop: threading.Event | None = None
        self._cloned_ready   = False     # the availability notice is logged once
        # The Live audio for the current turn is held here rather than played,
        # so it is still available if the cloned voice cannot be synthesised.
        self._cloned_fallback: list[bytes] = []

        _base_dir = Path(__file__).resolve().parent
        _inline_names = {t["name"] for t in TOOL_DECLARATIONS}

        self._action_registry = discover_actions(
            actions_dir=_base_dir / "actions",
            reserved_names=_inline_names,
            logger=lambda msg: print(f"[Actions] {msg}"),
        )

        _core_names = _inline_names | self._action_registry.names()
        self._plugin_registry = discover_plugins(
            plugins_dir=_base_dir / "plugins",
            core_tool_names=_core_names,
            logger=lambda msg: print(f"[Plugins] {msg}"),
            notify=lambda msg: self.ui.write_log(f"SYS: {msg}"),
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.get_plugin_settings = self._plugin_registry.settings_schemas
        self.ui.request_say = self.plugin_say

        self._wake_enabled     = get_wake_word_enabled()
        self._awake            = not self._wake_enabled
        self._wake_detector: WakeWordDetector | None = None
        self._wake_sleep_timeout = WAKE_SLEEP_TIMEOUT

        if get_push_to_talk_enabled():
            try:
                self.set_push_to_talk(True)
            except Exception as e:
                print(f"[JARVIS] ⚠ Push-to-talk unavailable: {e}")
        self.ui.wake_is_ready    = wake_is_ready
        self.ui.wake_get_state   = self._wake_state
        self.ui.on_wake_toggle   = self._ui_wake_toggle
        self.ui.on_wake_manual   = self._ui_wake_manual
        self.ui.on_wake_install  = self._ui_wake_install

    def _wake_state(self) -> dict:
        ready = bool(self._wake_detector and self._wake_detector.ready) or wake_is_ready()
        return {"enabled": self._wake_enabled, "awake": self._awake, "ready": ready}

    def _ensure_wake_detector(self) -> bool:
        if self._wake_detector is None:
            self._wake_detector = WakeWordDetector(
                on_detect=self._on_wake_detected,
                logger=lambda m: print(f"[Wake] {m}"),
                notify=lambda m: self.ui.write_log(f"SYS: {m}"),
            )
        if not self._wake_detector.ready:
            return self._wake_detector.start()
        return True

    def _on_wake_detected(self) -> None:
        self.wake(reason="wake word")

    def wake(self, reason: str = "wake word") -> None:
        if self._awake:
            return
        self._awake = True
        self._last_user_speech = time.monotonic()
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        self.ui.write_log(f"SYS: Awake — {reason}.")

    def sleep(self, reason: str = "timeout") -> None:
        if not self._awake:
            return
        self._awake = False
        self.set_speaking(False)
        self.ui.set_state("SLEEPING")
        self.ui.write_log(f"SYS: Sleeping — {reason}. Say 'Hey Jarvis' to wake me.")

    async def _run_sleep_watch(self) -> None:
        while True:
            await asyncio.sleep(5)
            if not self._wake_enabled or not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue
            if (time.monotonic() - self._last_user_speech) > self._wake_sleep_timeout:
                self.sleep(reason="no speech for 2 minutes")

    def _ui_wake_toggle(self, enable: bool) -> str:
        if enable:
            if not wake_is_ready():
                return "need_download"
            self._wake_enabled = True
            save_wake_word_enabled(True)
            self._ensure_wake_detector()
            self.sleep(reason="wake word enabled")
            return "enabled"
        else:
            self._wake_enabled = False
            save_wake_word_enabled(False)
            self.wake(reason="wake word disabled")
            return "disabled"

    def _ui_wake_manual(self) -> None:
        if not self._wake_enabled:
            return
        if self._awake:
            self.sleep(reason="you tapped sleep")
        else:
            self.wake(reason="you tapped wake")

    def _ui_wake_install(self) -> tuple[bool, str]:
        return wake_install(logger=lambda m: print(f"[Wake] {m}"),
                            notify=lambda m: self.ui.write_log(f"SYS: {m}"))

    def plugin_say(self, instruction: str) -> None:
        loop = getattr(self, "_loop", None)
        if not loop or not self.session:
            return

        async def _say():
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": instruction + " (ဒီအကြောင်းအရာကို မြန်မာဘာသာဖြင့်သာ ယဉ်ကျေးစွာ ပြောပြပါ)"}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[PluginSay] {e}")

        try:
            asyncio.run_coroutine_threadsafe(_say(), loop)
        except Exception as e:
            print(f"[PluginSay] {e}")

    def request_reconnect(self, keep_context: bool = True, reason: str = ""):
        loop = getattr(self, "_loop", None)
        ev   = self._reconnect_event
        self._reconnect_keep   = keep_context
        self._reconnect_reason = reason
        if loop and ev is not None:
            loop.call_soon_threadsafe(ev.set)

    def _on_voice_change(self):
        self.request_reconnect(keep_context=False, reason="new voice")

    # ── Cloned voice: the second audio path ──────────────────────────────────
    # The Live API speaks with a prebuilt voice and has no field for a cloned
    # one, so a cloned voice is not a setting the session can be given — it is a
    # different way of getting the words out. When one is selected the session
    # still runs normally (it must, or there would be no tool calls and no turn
    # detection), but its audio is thrown away and the reply text it transcribes
    # is re-spoken locally by the cloning engine.
    def _bind_voice_path(self) -> None:
        """Decide, once per connection, whether replies come from the Live API
        or from the cloned voice, and say so once if the cloned one is broken.

        There is nothing to load here: the cloned voice is synthesised by Fish
        Audio over HTTP, so it is ready the moment the key is. What is worth
        doing at connect time is failing loudly rather than silently — a missing
        key would otherwise only show up as a reply that arrives in the wrong
        voice, which is exactly the kind of fault this project has learned to
        check for rather than assume.
        """
        voice = get_voice()
        self._cloned_voice = voice if is_custom_voice_name(voice) else ""
        if not self._cloned_voice or self._cloned_ready:
            return
        self._cloned_ready = True
        try:
            from core import custom_voice
            entry = custom_voice.get_custom_voice(self._cloned_voice) or {}
            label = str(entry.get("label") or self._cloned_voice)
            why = custom_voice.problem()
            if why:
                self.ui.write_log(
                    f"SYS: cloned voice unavailable — {why}. "
                    f"Replies will use the prebuilt voice.")
            else:
                self.ui.write_log(f"SYS: အသံ — {label} (Fish Audio)")
        except Exception as e:                              # noqa: BLE001
            print(f"[CustomVoice] {e}")

    def _speak_cloned(self, text: str, fallback: bytes = b"") -> None:
        """Hand `text` to the cloning engine. Never blocks the receive loop.

        `fallback` is the audio the Live session generated for this same reply.
        It is only used if synthesis fails, so a Fish Audio outage costs the
        user her voice rather than the answer.
        """
        if self._cloned_stop is not None:
            self._cloned_stop.set()          # a new reply supersedes the last
        stop = threading.Event()
        self._cloned_stop = stop
        threading.Thread(target=self._cloned_worker, args=(text, stop, fallback),
                         daemon=True, name="cloned-voice").start()

    def _stop_cloned_playback(self) -> None:
        """Cut off a cloned reply, whether it is still being synthesised or
        already queued for the speaker.

        The Live API stops its own audio on a barge-in, but a cloned reply is
        local: it is either a synthesis still running or bytes already sitting
        in `audio_in_queue`, so both have to be cancelled here.
        """
        if self._cloned_stop is not None:
            self._cloned_stop.set()
        if not self._is_speaking:
            return
        self._cloned_fallback = []
        q = self.audio_in_queue
        if q is None:
            return
        while True:
            try:
                q.get_nowait()
            except Exception:                               # noqa: BLE001
                break
    def _cloned_worker(self, text: str, stop: threading.Event,
                       fallback: bytes = b"") -> None:
        """Synthesise off the event loop, then hand the audio to the player.

        The audio is pushed into `audio_in_queue` — the queue the Live audio
        normally arrives on — so it is played by the same loop, on the same
        output device, with the same visemes, echo guard and interrupt handling.
        The only new thing is where the sound came from.
        """
        try:
            from core import custom_voice
            pcm = custom_voice.synthesize_pcm(text, self._cloned_voice)
            if pcm is None:
                if not fallback:
                    return
                # Fish Audio could not be reached. The Live session had already
                # generated this reply in a prebuilt voice, so the user still
                # hears an answer — just not in her voice.
                self.ui.write_log("SYS: အသံ မရနိုင်ပါ — prebuilt voice ဖြင့် ဆက်ပြောပါမည်။")
                pcm = fallback

            loop = self._loop
            if loop is None or stop.is_set():
                return

            # 2400 bytes ~= 50 ms, the same slice size _receive_audio uses.
            for i in range(0, len(pcm), 2400):
                if stop.is_set():
                    return
                loop.call_soon_threadsafe(
                    self.audio_in_queue.put_nowait, pcm[i:i + 2400])

            # _play_audio only decides the assistant has stopped speaking when
            # the queue is empty AND the turn-done flag is set. That flag was
            # already consumed while this was still being synthesised, so it has
            # to be raised again here or the HUD would stay in SPEAKING forever.
            if self._turn_done_event is not None:
                loop.call_soon_threadsafe(self._turn_done_event.set)
        except Exception as e:                              # noqa: BLE001
            print(f"[CustomVoice] speak failed: {e}")

    def _on_audio_device_change(self):
        self.request_reconnect(keep_context=True, reason="audio device")

    async def _watch_reconnect(self):
        assert self._reconnect_event is not None
        await self._reconnect_event.wait()
        self._reconnect_event.clear()
        keep   = self._reconnect_keep
        reason = getattr(self, "_reconnect_reason", "") or "settings"
        self.ui.write_log(f"SYS: Applying {reason} — reconnecting...")
        raise _ReconnectSignal(keep_context=keep)

    async def _go_away_reconnect(self):
        """Leave the dying session on our own terms, not the server's.

        GoAway means the server will drop this websocket within roughly two
        minutes no matter what we do. Racing that deadline is what loses work:
        a tool response sent into a closed socket is a 1008, and the run loop
        then reconnects on the server's schedule with whatever the model was
        mid-way through simply gone. So: let the current turn finish speaking
        (capped — GoAway gives us ~2 min, this needs a couple of seconds), then
        raise the same reconnect the settings toggles use, with the context
        kept. Raised inside the TaskGroup it reaches run()'s reconnect-signal
        handler, which keeps the resumption handle and reconnects with
        zero backoff.
        """
        try:
            if self._turn_done_event is not None:
                try:
                    await asyncio.wait_for(self._turn_done_event.wait(), timeout=8.0)
                except asyncio.TimeoutError:
                    pass
            # The turn-done flag can be set while audio is still queued; do not
            # cut off a reply that is already on its way out of the speaker.
            for _ in range(80):                      # ≤ 8 s
                if not self._is_speaking and self.audio_in_queue.empty():
                    break
                await asyncio.sleep(0.1)
        except Exception as e:                       # noqa: BLE001
            print(f"[JARVIS] ⚠️ go_away graceful-exit wait failed: {e}")
        # Only this flag says the next drop is the *expected* one, so the
        # 1008/abnormal-closure handler stays quiet about it.
        self._expecting_go_away = True
        self.request_reconnect(keep_context=True, reason="session expiry (go_away)")


    def _make_remote_key(self):
        if self._dashboard is None:
            self.ui.write_log("SYS: Dashboard unavailable.")
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        # A VPN up means the address above is one the phone cannot reach, and
        # nothing about a QR code that never loads says so.
        try:
            from dashboard.server import vpn_warning
            note = vpn_warning()
        except Exception:
            note = ""
        return url, key, f"{url}/auto-login?key={key}", manual, note

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        if self._wake_enabled and not self._awake:
            self.ui.write_log("SYS: I'm asleep — say 'Hey Jarvis' or tap WAKE NOW first.")
            return

        # စာရိုက်ခိုင်းစေသည့်အခါ ယခင် interrupt အလံကို ရှင်းလင်းပေးခြင်း
        self._interrupted = False

        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text + " (မဖြစ်မနေ မြန်မာဘာသာဖြင့်သာ ပြန်လည်ဖြေကြားပါ)"}]},
                turn_complete=True
            ),
            self._loop
        )

    def _tail_active(self) -> bool:
        return time.monotonic() < self._tail_until

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self._tail_until = 0.0
        else:
            self._tail_until = time.monotonic() + self._out_latency + _TAIL_MARGIN
            self._out_level = 0.0
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def set_push_to_talk(self, enabled: bool) -> str:
        from core.hotkey import PushToTalk
        self._ptt_enabled = bool(enabled)
        self._ptt_held = False
        if not enabled:
            if self._ptt is not None:
                self._ptt.stop()
                self._ptt = None
            return "off"
        if self._ptt is None:
            self._ptt = PushToTalk(self._on_ptt)
        scope = self._ptt.start()
        try:
            self.ui.write_log(f"SYS: Push-to-talk on — hold {self._ptt.label}.")
        except Exception:
            pass
        return scope

    def _on_ptt(self, held: bool) -> None:
        self._ptt_held = held
        if held:
            if self._wake_enabled and not self._awake:
                self._awake = True
                self._last_user_speech = time.monotonic()
        try:
            self.ui.set_state("LISTENING" if held else "SLEEPING")
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        with self._speaking_lock:
            speaking = self._is_speaking

        # A cloned reply is a thread of its own writing straight to the speaker,
        # so it is not in the queue above and has to be told separately.
        if self._cloned_stop is not None:
            self._cloned_stop.set()

        q = self.audio_in_queue
        drained = 0
        if q:
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break

        self.set_speaking(False)
        self._visemes.reset()
        self._play_cursor = 0.0
        if self._turn_done_event:
            self._turn_done_event.clear()

        if speaking or drained > 0:
            self._interrupted = True
            self.ui.write_log("SYS: စကားဖြတ်တောက်ပြီး ပြန်လည်နားထောင်နေပါသည်...")
        else:
            self._interrupted = False

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        # Learned pronunciation rewrites go on here, at the last point before
        # the voice reads it. A word the user has said comes out slurred is
        # replaced with the spelling that sounds right — the voice itself
        # cannot be retrained, but what it is handed can be changed.
        try:
            from core.burmese_learning import fix_for_speech
            text = fix_for_speech(text)
        except Exception as _e:
            print(f"[Burmese] speech fix skipped: {_e}")
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"ဆရာ၊ {tool_name} လုပ်ဆောင်စဉ် အမှားအယွင်း ဖြစ်ပေါ်ခဲ့ပါသည်။ {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory, known_name=_user_name)
        sys_prompt = _load_system_prompt()
        knowledge_base = _load_knowledge_base()

        # The Burmese line is built here rather than left to the model: handed
        # "Saturday, September 26, 2026 — 11:59 AM" the model has to invent the
        # Burmese month, weekday and numerals, and that conversion is where the
        # wrong time came from. Give it the finished sentence instead.
        _now_mmt = timefmt.now_mmt()
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"လက်ရှိအချိန်: {timefmt.describe(_now_mmt)}\n"
            f"(ISO: {timefmt.machine_readable(_now_mmt)} — Myanmar Standard Time, UTC+6:30)\n"
            f"ရက်စွဲနှင့် အချိန်ကို ဤအတိုင်း တိုက်ရိုက်သုံးပါ။ "
            f"ပြောင်းလဲတွက်ချက်ခြင်း မပြုပါနှင့်။ "
            f"အချိန် ထပ်မံမေးလျှင် get_current_time tool ကို ခေါ်ပါ။\n\n"
        )

        _addr = (f"ADDRESS: အသုံးပြုသူကို '{_user_name}' ဟု ခေါ်ဆိုပါ။"
                 if _user_name
                 else 'ADDRESS: အသုံးပြုသူကို "ဆရာ" ဟု အလေးထား ယဉ်ကျေးစွာ ခေါ်ဆိုပါ။')
        
        identity_ctx = (
            f"[IDENTITY & LANGUAGE RULES]\n"
            f"သင်၏အမည်မှာ {self._asst_name} ဖြစ်သည်။ "
            f"ကိုယ့်ကိုယ်ကိုယ် အမြဲ {self._asst_name} ဟု သုံးနှုန်းပါ။\n"
            f"{_addr}\n"
            f"CRITICAL BURMESE LISTENING & SPEAKING DIRECTIVES:\n"
            f"1. THE USER ALWAYS SPEAKS IN BURMESE (မြန်မာစကား / မြန်မာဘာသာ)။ အသုံးပြုသူသည် မြန်မာလိုသာ အမြဲပြောနေခြင်းဖြစ်ပါသည်။\n"
            f"2. All incoming microphone audio MUST be recognized, interpreted, and understood as Burmese speech. Never transcribe or interpret user speech as Korean, Chinese, Spanish, Hindi, or other foreign languages.\n"
            f"3. DO NOT ASK BACK UNNECESSARILY: 'ဘာပြောလဲ မရှင်းလို့ ပြန်ပြောပါ' သို့မဟုတ် 'သဲသဲကွဲကွဲ မကြားလိုက်ရပါဘူး' ဟု ထပ်ခါတလဲလဲ ပြန်မမေးပါနှင့်။ အသံအနည်းငယ် မသဲကွဲလျှင်လည်း မြန်မာစကား အခြေအနေနှင့် ဆီလျော်အောင် ထိုးထွင်းနားလည်ပြီး ချက်ချင်း အဖြေထုတ်ပေးပါ သို့မဟုတ် သက်ဆိုင်ရာ Tool ကို တိုက်ရိုက် ခေါ်ယူပါ။\n"
            f"4. COMMON COLLOQUIAL PHRASES: အသုံးပြုသူက 'ပေါက်စေ့/ပေါက်စေး' ဟုပြောလျှင် 'ပေါက်ဈေး', 'တူလဲ' ဟုပြောလျှင် 'ထူးလဲ' (သတင်းဘာထူးလဲ), 'မိုးလေဝသ/ရာသီဥတု', 'လေးဖြူ/သီချင်းဖွင့်' ဟု သဘာဝကျကျ အဓိပ္ပာယ်ဖော်ယူပါ။\n"
            f"5. Always reply politely, naturally, concisely, and fluently in Burmese (မြန်မာဘာသာ). Never speak English unless explicitly asked to translate into English.\n"
            f"6. LOCATION & MAPS: When the user asks about their current location, address ('ငါ့တည်နေရာ', 'ငါ့လိပ်စာ', 'ငါဘယ်ရောက်နေလဲ', 'လက်ရှိနေရာ', 'ဘယ်နားမှာလဲ'), travel directions, or nearby places, ALWAYS call the 'maps_navigator' tool. If the user asks to see, open, or display the map ('google map နဲ့ ပြ', 'ထုတ်ပြ', 'ဖွင့်ပြ', 'မြေပုံပေါ်မှာ ပြ', 'show on map'), set open_map=True. Never claim that you don't have a tool for location.\n\n"
        )

        _all_decls = (TOOL_DECLARATIONS
                      + self._action_registry.get_tool_declarations()
                      + self._plugin_registry.get_tool_declarations())
        _names = {(d.get("name") if isinstance(d, dict) else getattr(d, "name", ""))
                  for d in _all_decls}
        sys_prompt = _render_prompt(sys_prompt, {
            # No "assistant_name": the template no longer names it. The name is
            # stated once, in identity_ctx, and the same fact in two places is
            # two places for it to disagree with itself.
            "platform": f"{_platform.system()} {_platform.release()}".strip(),
            "capabilities": _describe_tools(_all_decls),
            "limits": _describe_limits(
                has_vision="screen_process" in _names,
                has_mic=True,
            ),
        })

        parts = [time_ctx, identity_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)
        if knowledge_base:
            parts.append(knowledge_base)

        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": _all_decls}],
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        # A cloned voice is never sent here — the Live API takes
                        # a prebuilt name and nothing else, so a cloned choice
                        # arrives as CUSTOM_VOICE_FALLBACK and the reply is
                        # re-spoken locally instead (see _cloned_worker).
                        voice_name=get_prebuilt_voice()
                    )
                )
            ),
        )
        if self._tuned_live:
            cfg.update(self._tuning_config())

        return types.LiveConnectConfig(**cfg)

    def _tuning_config(self) -> dict:
        """Low-latency Turn-taking knobs ချိန်ညှိချက်များ"""
        out: dict = {}
        turn = get_turn_tuning()
        if turn.get("enabled", False):
            # စကားရပ်ပြီးသည်နှင့် ချက်ချင်းသိရှိပြီး အသံထွက်စေရန် silence_ms ကို လျှော့ချထားသည်
            detect = types.AutomaticActivityDetection(
                silence_duration_ms=int(turn.get("silence_ms", 300)),
                prefix_padding_ms=int(turn.get("prefix_ms", 100)),
            )
            end_sens = str(turn.get("end_sensitivity", "high")).upper()
            if end_sens == "HIGH":
                detect.end_of_speech_sensitivity = types.EndSensitivity.END_SENSITIVITY_HIGH
            elif end_sens == "LOW":
                detect.end_of_speech_sensitivity = types.EndSensitivity.END_SENSITIVITY_LOW

            start_sens = str(turn.get("start_sensitivity", "high")).upper()
            if start_sens == "HIGH":
                detect.start_of_speech_sensitivity = types.StartSensitivity.START_SENSITIVITY_HIGH
            elif start_sens == "LOW":
                detect.start_of_speech_sensitivity = types.StartSensitivity.START_SENSITIVITY_LOW

            out["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=detect
            )

        res = get_media_resolution()
        if res != "default":
            out["media_resolution"] = {
                "low":    types.MediaResolution.MEDIA_RESOLUTION_LOW,
                "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                "high":   types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            }[res]

        # Thinking latency မဖြစ်စေရန် thinking_budget ကို 0 ဖြင့် ပိတ်ထားသည်
        if not get_thinking_enabled():
            out["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        return out

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[JARVIS] 🔧 {name}  {args}")

        # ── Repeated-call guard ──────────────────────────────────────────────
        #
        # Measured 2026-09-29 from a live session log: asked about a storm, the
        # model called `newspaper` with the same arguments and got the same
        # 1309-character answer back, then called it again, then again — and
        # **never spoke**. The user saw the tool's output scroll past and no
        # answer, which reads as the assistant ignoring the question.
        #
        # There was no guard of any kind: whatever the model asked for, it got,
        # however many times it asked. Nothing here tries to work out *why* it
        # looped — that depends on the model and the day. What it does is stop
        # the loop being unbounded, and hand back an instruction the model can
        # act on: you already have the answer, say it.
        #
        # The key includes the arguments, so asking for မြန်မာ့အလင်း and then
        # ကြေးမုံ is two different calls and both run. Only an identical repeat
        # counts.
        try:
            _key = _tool_call_key(name, args)
        except Exception:                                   # noqa: BLE001
            _key = (name, str(args))
        _history = getattr(self, "_tool_call_history", None)
        if _history is None:
            _history = self._tool_call_history = []
        _seen = _count_calls(_history, _key)
        _history.append(_key)
        if len(_history) > 40:
            del _history[:-40]

        if _seen >= _MAX_IDENTICAL_CALLS:
            print(f"[JARVIS] 🛑 {name} already called {_seen}x with these "
                  f"arguments — asking the model to answer instead")
            self.ui.write_log(
                f"SYS: {name} ကို {_seen} ကြိမ် ထပ်ခေါ်နေသည် — အဖြေပြောရန် တောင်းဆိုလိုက်သည်")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": (
                    "You have already called this tool with these exact "
                    "arguments and received its result. Calling it again will "
                    "return the same thing. Stop calling tools and answer the "
                    "user now, out loud, using the result you already have. "
                    "If the result does not contain the answer, say so plainly."
                )},
            )

        self.ui.set_state("THINKING")

        # The news route, enforced — see _news_route above for why this lives
        # here rather than in the tool description the model reads.
        if name == "web_search":
            _redirect = _news_route(args.get("query") or args.get("topic") or "")
            if _redirect:
                print(f"[JARVIS] ↪️ news question → {_redirect}: "
                      f"{str(args.get('query') or '')[:60]!r}")
                self.ui.write_log(
                    f"SYS: သတင်းမေးခွန်း — {_redirect} သို့ လွှဲလိုက်သည်")
                name = _redirect
                if _redirect == "newsroom_search":
                    args = {"query": args.get("query", "")}
                elif _redirect == "news_section":
                    # The whole sentence goes in `section`: `resolve_section`
                    # matches an alias *inside* it, so "ဒီနေ့ စီးပွားရေး သတင်း
                    # ပြောပြ" resolves to `စီးပွားရေး` — and `_infer_paper` reads
                    # a paper named in the same sentence. Dropping the text
                    # would leave the tool with no section at all and make it
                    # refuse the very question it was routed for.
                    args = {"section": args.get("query", "")}
                else:
                    args = {}

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            # Provenance is decided here, not taken on trust: anything that is
            # not an explicit "the user said this" is recorded as the assistant's
            # own note, which is the safe direction to be wrong in.
            source   = str(args.get("source") or "model").strip().lower()
            if source not in MEMORY_SOURCES:
                source = "model"
            if key and value:
                update_memory({category: {key: {"value": value}}}, source=source)
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value} ({source})")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "recall_memory":
                result = search_memory(args.get("query", ""), limit=8)

            elif name == "undo":
                if str(args.get("action", "")).lower().strip() == "list":
                    items = undo_stack.history()
                    result = ("ပြန်ပြင်နိုင်သည့် အရာများ:\n"
                              + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                              ) if items else "ပြန်ပြင်စရာ အပြောင်းအလဲ မရှိသေးပါ။"
                else:
                    result = await loop.run_in_executor(None, undo_stack.undo_last)

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    result = "Vision is still busy."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = "[VISION_ACTIVE] Image captured. Describe what you see in Burmese directly."

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "get_current_time":
                # Read live, not from the session-start snapshot: a session that
                # has been open for two hours would otherwise still answer with
                # the time it opened.
                result = (f"{timefmt.describe()} "
                          f"(ISO {timefmt.machine_readable()})")

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("စောင့်ကြည့်နေသော ခေါင်းစဉ်များ: " + ", ".join(topics)) if topics else "စောင့်ကြည့်နေသော ခေါင်းစဉ်မရှိပါ။"
                else:
                    result = "Specify action (add/remove/list) and topic."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    await self._save_session_summary()
                    if self.session:
                        try:
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": "Say a polite goodbye in Burmese: 'ဟုတ်ကဲ့ပါ ဆရာ၊ နှုတ်ဆက်ပါတယ်ခင်ဗျာ။'"}]},
                                turn_complete=True,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(1.5)
                    import os as _os
                    _os._exit(0)
                asyncio.create_task(_do_shutdown())

            elif name == "maps_navigator":
                _ctx = {"player": self.ui, "speak": self.speak, "response": None, "session_memory": None}
                r = await loop.run_in_executor(None, lambda: maps_navigator(args, player=self.ui, speak=self.speak))
                result = r or "Done."
                if r:
                    self.ui.show_content("MAPS NAVIGATOR", r)

            elif self._action_registry.has(name):
                if name == "file_processor" and not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                _ctx = {"player": self.ui, "speak": self.speak, "response": None, "session_memory": None}
                r = await loop.run_in_executor(None, lambda: self._action_registry.run(name, args, _ctx))
                result = r or "Done."
                if (name == "web_search" and r
                        and not r.startswith("No results")
                        and not r.startswith("Search failed")):
                    _mode  = args.get("mode", "search")
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)

            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                else:
                    # A name that was never declared at all. Measured 2026-10-01
                    # in a live session: the model asked for `yarvis_news`, a
                    # misspelling of a tool the `moi_news` description had named as
                    # one NOT to use. The old reply was the bare English string
                    # `Unknown tool: yarvis_news` — it named no alternative, so the
                    # model retried the same wrong name and the turn was wasted.
                    # Hand back a correction it can act on, the same way the
                    # repeated-call guard above hands back "you already have the
                    # answer, say it".
                    _known = ({t["name"] for t in TOOL_DECLARATIONS}
                              | self._action_registry.names()
                              | self._plugin_registry.names())
                    _near = _closest_names(name, _known)
                    result = (
                        f"Unknown tool: {name}."
                        + (f" Did you mean {', '.join(_near)}?" if _near else "")
                        + " Call only a declared tool, or answer the user with"
                          " what you already have. Never invent a tool name."
                    )

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        _sched = (self._action_registry.scheduling(name) or self._plugin_registry.scheduling(name))
        _extra = {"scheduling": _sched} if _sched else {}
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result},
            **_extra
        )

    # ── Real-time Audio Stream Pipeline (Native Low Latency) ─────────────────
    async def _send_realtime(self):
        dead = False
        while True:
            msg = await self.out_queue.get()
            if dead or not self.session:
                continue
            try:
                await self.session.send_realtime_input(
                    audio=types.Blob(
                        data=msg["data"],
                        mime_type=msg.get("mime_type", f"audio/pcm;rate={SEND_SAMPLE_RATE}"),
                    )
                )
            except Exception as e:
                # The session is gone — a keepalive timeout or an abnormal
                # closure — and it is NOT coming back. run() tears this whole
                # TaskGroup down and builds a fresh session with a fresh sender.
                #
                # Printing per chunk turned one dead socket into a wall of
                # identical lines: measured 2026-09-27, ~120 of them, one for
                # every chunk already sitting in the queue, with the one error
                # that mattered buried at the top. Say it once, then drop the
                # backlog — after a reconnect that audio is seconds old and
                # worthless, and the mic keeps filling the queue meanwhile.
                dead = True
                print(f"[JARVIS] Audio send failed — session is gone "
                      f"({type(e).__name__}: {e}); dropping queued audio "
                      f"until reconnect")
                while True:
                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started (Native Multimodal Stream)")
        loop = asyncio.get_event_loop()

        def _offer_audio(data):
            """Queue one mic chunk, dropping the OLDEST when the queue is full.

            out_queue is bounded at 200 chunks so that a stalled API cannot
            grow memory without limit — but `put_nowait` raising QueueFull is
            the wrong answer to "the consumer is behind". It fires inside
            `call_soon_threadsafe`, where nothing can catch it, so asyncio
            prints one traceback per audio chunk. Measured 2026-09-27: several
            hundred `Exception in callback Queue.put_nowait()` lines while the
            session was down, burying the one error that actually mattered.

            For live audio only the NEWEST chunk is worth sending, so the
            oldest is dropped rather than the newest refused.
            """
            item = {"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"}
            try:
                self.out_queue.put_nowait(item)
                return
            except asyncio.QueueFull:
                pass
            try:
                self.out_queue.get_nowait()      # discard the stalest chunk
            except asyncio.QueueEmpty:
                pass
            try:
                self.out_queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

        def callback(indata, frames, time_info, status):
            if self._wake_enabled and not self._awake:
                det = self._wake_detector
                if det is not None:
                    det.feed(indata)
                return

            with self._speaking_lock:
                jarvis_speaking = self._is_speaking

            if jarvis_speaking:
                return

            if self._tail_active():
                try:
                    if not self._echo.is_user_speech(indata, SEND_SAMPLE_RATE, _pcm_level(indata)):
                        return
                    self._tail_until = 0.0
                except Exception:
                    return
            elif self._echo._hist:
                self._echo.reset()

            if self._ptt_enabled and not self._ptt_held:
                return

            if not self.ui.muted and not self._phone_active:
                data = indata.tobytes()
                loop.call_soon_threadsafe(_offer_audio, data)
                try:
                    self.ui.set_audio_level(_pcm_level(indata))
                except Exception:
                    pass

        try:
            def _open_mic(dev):
                return sd.InputStream(
                    samplerate=SEND_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                    device=dev,
                    callback=callback,
                )

            _mic_name = get_input_device()
            _mic_dev  = audio_devices.resolve(_mic_name, "input")
            if _mic_dev is not None:
                print(f"[JARVIS] 🎤 Input device: {_mic_name}")
            try:
                _mic_stream = _open_mic(_mic_dev)
            except Exception as _e:
                if _mic_dev is None:
                    raise
                print(f"[JARVIS] ⚠️ Mic fallback: {_e}")
                _mic_stream = _open_mic(None)

            with _mic_stream:
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _flush_pending_vision(self) -> bool:
        if not (self._pending_vision and self.session):
            return False

        import base64 as _b64
        img_b, mime_t, question, angle = self._pending_vision
        self._pending_vision = None
        b64 = _b64.b64encode(img_b).decode("ascii")
        src = ("[IMAGE SOURCE: WEBCAM]" if angle == "camera" else "[IMAGE SOURCE: SCREEN CAPTURE]")
        await self.session.send_client_content(
            turns={"role": "user", "parts": [
                {"inline_data": {"mime_type": mime_t, "data": b64}},
                {"text": f"{src}\n\n{question}\n\n(ဤပုံတွင် မြင်တွေ့ရသည်များကို မြန်မာလိုသာ ယဉ်ကျေးစွာ ရှင်းပြပါ)"},
            ]},
            turn_complete=True,
        )

        if self._vision_cam_active:
            self._vision_cam_active    = False
            self._vision_close_pending = True
        else:
            self._vision_busy = False
        return True

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    _sru = getattr(response, "session_resumption_update", None)
                    if _sru is not None:
                        if getattr(_sru, "resumable", False) and getattr(_sru, "new_handle", None):
                            self._resume_handle = _sru.new_handle

                    # GoAway: the server's polite warning, sent ~2 min before it
                    # kills the session at its 10-minute lifetime. Ignored, the
                    # close arrives as a 1008 mid-tool-call and whatever the
                    # model was doing is lost. Caught, we finish the turn that
                    # is playing and leave before the deadline with the
                    # resumption handle intact (main.py:1621-1622 above saves
                    # it continuously), so the reconnect keeps the conversation.
                    if getattr(response, "go_away", None) is not None and not self._go_away_seen:
                        self._go_away_seen = True
                        print("[JARVIS] ⏳ GoAway received — planning a graceful reconnect.")
                        asyncio.create_task(self._go_away_reconnect())


                    if response.data:
                        if self._cloned_voice:
                            # Held back, not played. A cloned voice cannot be
                            # sent to the Live API, so the reply is generated
                            # here and replaced by the same words spoken through
                            # Fish Audio (see _cloned_worker). Keeping the audio
                            # instead of dropping it costs a few hundred KB per
                            # turn and buys the fallback: if Fish Audio cannot be
                            # reached, the user still hears the answer. Asking
                            # for text instead is not an option — these Live
                            # models refuse response_modalities=["TEXT"] with a
                            # 1007, which is written up in core/gemini.py.
                            if not self._interrupted:
                                self._cloned_fallback.append(response.data)
                        elif self._interrupted:
                            pass
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        # Barge-in. The server stops generating, and both native
                        # audio and cloned replies are cut off immediately so the
                        # assistant does not keep talking over the user.
                        if getattr(sc, "interrupted", False):
                            self.interrupt()

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and not _is_repeat_chunk(txt, out_buf):
                                out_buf.append(txt)
                                self._visemes.feed_text(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                # What the model heard, recorded so a correction
                                # can be made against it. Recording is not
                                # learning — nothing here changes behaviour
                                # until the user says a word came out wrong.
                                try:
                                    from core.burmese_learning import (
                                        fix_heard, log_heard)
                                    log_heard(txt)
                                    # Learned mishearings are repaired before the
                                    # model sees the text. The errors are
                                    # systematic, so a table fixes them for good.
                                    txt = fix_heard(txt)
                                except Exception as _e:
                                    print(f"[Burmese] learning hook skipped: {_e}")
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()
                                # စကားပြောသံ အသစ်ရောက်လာပါက interrupt အလံကို အလိုအလျောက် ရှင်းလင်းပေးခြင်း
                                self._interrupted = False
                                # …and stop a cloned reply that is still playing,
                                # which the server cannot do for us.
                                if self._cloned_voice:
                                    self._stop_cloned_playback()

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                self._cloned_fallback = []
                                self._visemes.reset()
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self._last_out_logged = ""
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if _is_duplicate_reply(full_out, self._last_out_logged):
                                # Dropping a repeat is deliberate — but this is
                                # the one place where a *text* filter decides
                                # whether the assistant speaks at all, and it
                                # used to be completely invisible. A false
                                # positive here reads to the user as JARVIS
                                # ignoring them, with nothing in the log to say
                                # why.
                                print(f"[JARVIS] ↩️ reply dropped as a repeat of the "
                                      f"previous one: {full_out[:60]!r}")
                                full_out = ""
                            if full_out:
                                self._last_out_logged = full_out
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                if self._cloned_voice:
                                    self._speak_cloned(
                                        full_out, b"".join(self._cloned_fallback))
                            self._cloned_fallback = []
                            out_buf = []

                            if self._vision_close_pending:
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            # The id is logged because a missing one is the
                            # other way this loop can start: the API matches a
                            # response to its call by id, so an empty id means
                            # the model never sees the result and asks again.
                            print(f"[JARVIS] 📞 {fc.name}  id={fc.id!r}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(function_responses=fn_responses)
                        await self._flush_pending_vision()
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        _spk_name = get_output_device()
        _spk_dev  = audio_devices.resolve(_spk_name, "output")
        if _spk_dev is not None:
            print(f"[JARVIS] 🔊 Output device: {_spk_name}")

        def _open_spk(dev):
            st = sd.RawOutputStream(
                samplerate=RECEIVE_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=dev,
            )
            st.start()
            return st

        try:
            stream = _open_spk(_spk_dev)
        except Exception as _e:
            if _spk_dev is None:
                raise
            print(f"[JARVIS] ⚠️ Output device fallback: {_e}")
            stream = _open_spk(None)

        try:
            lat = float(getattr(stream, "latency", 0.0) or 0.0)
            if 0.0 < lat < 1.0:
                self._out_latency = lat
        except Exception:
            pass

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                self.set_speaking(True)

                # Buffer အရွယ်အစားကို 2400 bytes (~50ms) သို့ လျှော့ချထားသဖြင့် စကားသံ ချက်ချင်း စတင်ထွက်ပေါ်စေပါသည်
                batch = bytearray(chunk)
                while len(batch) < 2400:
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                try:
                    pcm = np.frombuffer(bytes(batch), dtype=np.int16)
                    hop = _VIS_HOP / RECEIVE_SAMPLE_RATE
                    frames = _pcm_visemes(pcm, sr=RECEIVE_SAMPLE_RATE)
                    now = time.time()
                    horizon = self._out_latency + _CURSOR_SLACK
                    if not (now <= self._play_cursor <= now + horizon):
                        self._play_cursor = now + _FIRST_SOUND
                    at = self._play_cursor
                    self._play_cursor += pcm.size / RECEIVE_SAMPLE_RATE
                    if frames:
                        frames = self._visemes.frames(frames, hop)
                        self.ui.push_visemes(frames, hop, at)
                        self._out_level = max(f[0] for f in frames)
                        self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE, self._out_level)
                    else:
                        lvl = _pcm_level(pcm)
                        self.ui.set_audio_level(lvl)
                        self._out_level = lvl
                        self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE, lvl)
                except Exception:
                    pass

                try:
                    await asyncio.to_thread(stream.write, bytes(batch))
                except (RuntimeError, asyncio.CancelledError):
                    break
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def _send_startup_briefing(self) -> None:
        try:
            memory = load_memory()
        except Exception as e:
            print(f"[Briefing] memory load failed: {e!r}")
            memory = {}
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        name = _val("name") or "ဆရာ"

        loop = asyncio.get_event_loop()
        # Only the weather is started here. The news used to be kicked off at
        # the same moment and read out as a second phase of the greeting; it is
        # now the daily_briefing tool, answered when asked. Starting it anyway
        # would be a wasted network round trip on every single launch.
        # The two budget constants live at module level so check_greeting.py can
        # assert their relationship by measurement — see _WEATHER_ATTEMPT.
        weather_future = loop.run_in_executor(
            None, fetch_weather_brief, "နေပြည်တော်", _WEATHER_ATTEMPT)

        await asyncio.sleep(0.3)
        if not self.session:
            return

        try:
            last = await asyncio.to_thread(pop_last_session)
        except Exception as e:
            # Not worth losing the greeting over: recalling the last
            # conversation is a nicety, the greeting is the point.
            print(f"[Briefing] last-session lookup failed: {e!r}")
            last = None
        session_clause = ""
        if last:
            try:
                _delta_str = timefmt.to_burmese_digits(_delta)
                _when  = "ယနေ့ မနက်ပိုင်းက" if _delta == 0 else ("မနေ့က" if _delta == 1 else f"လွန်ခဲ့သော {_delta_str} ရက်က")
            except Exception:
                _when = "ပြီးခဲ့သည့်တစ်ခေါက်က"
            session_clause = timefmt.to_burmese_digits(
                f" ထို့အပြင် {_when} ဆွေးနွေးခဲ့သည့် အကြောင်းအရာ ({last['summary']}) ကို မြန်မာလို အကျဉ်းလေး ထည့်ပြောပါ။"
            )

        # The greeting is assembled here and handed over as finished text, for
        # the same reason the time is: told to "greet the user and mention the
        # time and weather", the model paraphrases, and every paraphrase is a
        # chance to mis-state the hour or invent the forecast. Handed the exact
        # sentence, it only has to read it.
        now = timefmt.now_mmt()
        greeting = (
            f"မင်္ဂလာပါ {name}၊ ကျွန်တော် {self._asst_name} ပါ။ "
            f"ဘယ်လိုဝန်ဆောင်မှုမျိုးကို ဆောင်ရွက်ပေးရမလဲခင်ဗျာ။ "
            f"ဒီနေ့ကတော့ {timefmt.burmese_month_day(now)}ပါ။ "
            f"မြန်မာစံတော်ချိန် {timefmt.burmese_clock(now)} ရှိပါပြီ။"
        )

        # Bounded, because this sits between the user pressing start and hearing
        # anything at all. Naypyidaw is in the pre-resolved table so the usual
        # case is a single forecast request; on failure the sentence is simply
        # left out rather than replaced with an apology inside the greeting.
        weather = ""
        try:
            weather = await asyncio.wait_for(
                asyncio.wrap_future(weather_future), timeout=_WEATHER_WAIT) or ""
        except Exception as e:
            print(f"[JARVIS] Startup weather unavailable: {e!r}")
        if weather:
            greeting += (f" {name}နေထိုင်တဲ့ နေပြည်တော်ရဲ့ ရာသီဥတုကတော့ "
                         f"{weather} ဖြစ်နေပါပြီ။")

        p1 = (
            "အောက်ပါစာကို သဘာဝကျကျ၊ နွေးထွေးယဉ်ကျေးစွာ အသံထွက်ဖတ်ပါ။ "
            "စကားလုံး တစ်လုံးမှ မပြောင်းပါနှင့်၊ မထပ်ပါနှင့်၊ မဖြည့်ပါနှင့်။ "
            "ရှေ့ဆက် နိဒါန်း ဘာမှ မထည့်ပါနှင့်။\n"
            f"{greeting}{session_clause}\n"
            "Tool မခေါ်ပါနှင့်။ မြန်မာဘာသာဖြင့်သာ ပြောပါ။"
        )

        if self._turn_done_event:
            self._turn_done_event.clear()

        try:
            await self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": p1}]},
                turn_complete=True,
            )
        except Exception as e:
            # This task is created with create_task, so an exception here would
            # otherwise surface only as an asyncio "task exception was never
            # retrieved" warning whenever the object is collected — easily
            # missed, and the symptom is simply that nothing was said.
            print(f"[JARVIS] ❌ Greeting could not be sent: {type(e).__name__}: {e}")
            self.ui.write_log(f"ERR: နှုတ်ဆက်စကား ပို့လို့ မရပါ — {type(e).__name__}")
            return
        print("[JARVIS] Briefing phase 1 (greeting) sent.")

        # There is deliberately no news phase here any more.
        #
        # Phase 2 used to fetch the news in parallel with the greeting and read
        # the headlines out a few seconds later. The user asked for the news to
        # wait until it is asked for — every launch was becoming a broadcast,
        # whether or not anything was wanted — so it now lives in the
        # daily_briefing tool, which is reached by asking "ဒီနေ့ဘာထူးလဲ".
        #
        # The greeting itself is unchanged: mingalaba, the date, the time and
        # the weather, spoken as soon as JARVIS connects.

    async def _save_session_summary(self) -> None:
        log = self._session_log
        if len(log) < 3:
            return
        self._session_log = []

        convo = "\n".join(log[-40:])
        prompt = (
            "Summarize this conversation in 1-2 sentences in Burmese (မြန်မာဘာသာ). "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text in Burmese, nothing else:\n\n" + convo
        )
        try:
            from core import gemini
            summary = await asyncio.to_thread(
                gemini.text, prompt, gemini.SMART, None, 30_000,
            )
            if summary:
                save_session_summary(summary, "Burmese")
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    async def _run_system_monitor(self) -> None:
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session or not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": f"{alert}\n\nဤစက်ပိုင်းဆိုင်ရာ သတိပေးချက်ကို ဆရာ့ထံ မြန်မာလို အကျဉ်းချုပ် သဘာဝကျကျ အသိပေးပါ။"}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    async def _run_background_monitor(self) -> None:
        await asyncio.sleep(300)
        while True:
            if self.session and self._awake:
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                "ဤအချက်အလက်ကို ဆရာ့ထံ မြန်မာဘာသာဖြင့် သဘာဝကျကျ ၁ ကြောင်းတည်း အသိပေးပါ။"
                            )
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            print("[JARVIS] Monitor alert sent.")
                            await asyncio.sleep(6)
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)

    async def _run_proactive_mode(self) -> None:
        while True:
            await asyncio.sleep(60)
            if not self.session or not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue
            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()
            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                )
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": prompt + "\n\n(မဖြစ်မနေ မြန်မာဘာသာဖြင့်သာ ယဉ်ကျေးစွာ ပြောပါ)"}]},
                    turn_complete=True,
                )
                print("[JARVIS] Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    async def _run_newsroom_watch(self) -> None:
        """Speak newly analysed news, when core/newsroom_watch.py's gates allow.

        The gates — enabled, quiet hours, awake, idle, cooldown, startup grace
        — live in that module so this stays a loop and nothing about *when* to
        speak gets decided here. Two details matter:

          - the first poll only seeds the high-water mark, so a fresh install
            does not read out the entire archive on its first launch;
          - items found while a gate is shut are buffered, not dropped, so a
            headline that arrives overnight is still there in the morning.
        """
        await asyncio.sleep(30)      # let the session open and the greeting land
        while True:
            try:
                await asyncio.to_thread(self._newsroom_watch.poll)

                if self.session:
                    items = self._newsroom_watch.take_pending()
                    if items:
                        with self._speaking_lock:
                            speaking = self._is_speaking
                        ok, why = self._newsroom_watch.should_announce(
                            awake        = self._awake,
                            speaking     = speaking,
                            last_user_speech = self._last_user_speech,
                        )
                        prompt = self._newsroom_watch.build_prompt(items) if ok else ""
                        if prompt:
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": prompt}]},
                                turn_complete=True,
                            )
                            self._newsroom_watch.mark_announced()
                            self.ui.write_log(
                                f"SYS: သတင်းအသစ် {len(items)} ပုဒ် အသိပေးလိုက်ပါသည်။")
                            print(f"[NewsroomWatch] announced {len(items)} item(s).")
                        else:
                            # Held, not lost — put them back for the next poll.
                            self._newsroom_watch.requeue(items)
                            print(f"[NewsroomWatch] {len(items)} item(s) held — {why}")
            except Exception as e:
                print(f"[NewsroomWatch] ⚠️ {e}")
            await asyncio.sleep(poll_interval_seconds())

    async def _relay_phone_audio(self) -> None:
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                self._phone_active = False
                continue
            self._phone_active = True
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(self._dashboard._command_queue.get(), timeout=0.5)
                if not text:
                    continue
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    if self._wake_enabled and not self._awake:
                        self.wake(reason="remote command")
                    self._interrupted = False
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": text + " (မဖြစ်မနေ မြန်မာဘာသာဖြင့်သာ ပြန်လည်ဖြေကြားပါ)"}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._reconnect_event = asyncio.Event()

        confirm_gate.bind(
            show = self.ui.show_confirm,
            hide = self.ui.hide_confirm,
            log  = self.ui.write_log,
        )
        set_trim_notifier(self.ui.write_log)

        audio_devices.configure(SEND_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)
        audio_devices.prefetch()

        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            asyncio.create_task(self._process_dashboard_commands())
        except Exception:
            self._dashboard = None

        while True:
            try:
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                _resumed_with = self._resume_handle is not None
                self._bind_voice_path()
                config = self._build_config()

                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()

                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False
                    self._go_away_seen         = False
                    self._expecting_go_away    = False

                    print("[JARVIS] Connected.")
                    if _resumed_with:
                        self.ui.write_log("SYS: ပြန်လည်ချိတ်ဆက်ပြီးပါပြီ။")

                    if self._wake_enabled:
                        self._ensure_wake_detector()
                        self._awake = False
                        self.ui.set_state("SLEEPING")
                        self.ui.write_log("SYS: JARVIS အဆင်သင့်ရှိပါသည် — ခေတ္တအိပ်စက်နေပါသည်။ 'Hey Jarvis' ဟု ခေါ်ပါ။")
                    else:
                        self._awake = True
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: JARVIS အဆင်သင့်ရှိပါပြီ။ မင်္ဂလာပါ ဆရာ။")

                    self._reconnect_event.clear()
                    tg.create_task(self._watch_reconnect())
                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_background_monitor())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._run_newsroom_watch())
                    tg.create_task(self._run_sleep_watch())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    if not self._briefing_sent and self._awake:
                        if get_brief_enabled():
                            self._briefing_sent = True
                            tg.create_task(self._send_startup_briefing())
                        else:
                            # Say why, out loud. The greeting is gated behind the
                            # MORNING BRIEF toggle, so switching the news off also
                            # switches the greeting off — and until this line
                            # existed it did so without a word, which from the
                            # outside is indistinguishable from a broken greeting.
                            print("[JARVIS] Startup briefing OFF "
                                  "(morning_brief_enabled=false) — no greeting will "
                                  "be spoken. Toggle MORNING BRIEF in the UI, or "
                                  "set it in config/api_keys.json.")
                            self.ui.write_log(
                                "SYS: MORNING BRIEF ပိတ်ထားပါသည် — "
                                "နှုတ်ဆက်စကား ထွက်မည် မဟုတ်ပါ။")

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                if _is_reconnect_signal(e):
                    if not _keep_context_of(e):
                        self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                if _resumed_with and any(k in str(e).lower() for k in ("resum", "handle", "invalid_argument", "not_found")):
                    self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                err_str = str(e)
                is_abnormal = "1006" in err_str or "abnormal closure" in err_str.lower()
                is_net_err = (
                    isinstance(e, (ConnectionResetError, ConnectionRefusedError, TimeoutError, OSError))
                    or any(k in err_str for k in ("TimeoutError", "timed out", "getaddrinfo", "Cannot connect", "ConnectionResetError", "ConnectionRefusedError", "10054", "10060", "10061"))
                )

                if is_abnormal or is_net_err or getattr(self, "_expecting_go_away", False):
                    pass
                else:
                    print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                    traceback.print_exc()

                if self._tuned_live and any(k in err_str for k in ("INVALID_ARGUMENT", "Unknown name", "unexpected keyword", "realtime_input")):
                    self._tuned_live = False
                    continue

                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key မှားယွင်းနေပါသည် — ပြန်လည်စစ်ဆေးပေးပါ။")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    _conn_backoff = 3
                    continue

                if getattr(self, "_expecting_go_away", False):
                    # Our own go_away exit: reconnect at once, no backoff —
                    # the resumption handle keeps the conversation.
                    self._conn_backoff = 0
                    self.ui.write_log(
                        "SYS: Session သက်တမ်းကုန်သည့်အတွက် ပြန်ချိတ်ပါမည်။")
                elif is_net_err or is_abnormal:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(f"NET: ကွန်ရက် ချိတ်ဆက်မှု ပြတ်တောက်သွားပါသည် (VPN စစ်ဆေးပါ) — "
                                      f"{_conn_backoff}s အကြာ ပြန်ချိတ်ပါမည်။")
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                if len(self._session_log) >= 3:
                    asyncio.create_task(self._save_session_summary())

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
