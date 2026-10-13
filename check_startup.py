"""Can JARVIS be started? — everything except the window and the microphone.

    py check_startup.py

Run this before `py main.py`, and after any change to main.py, ui.py, the
config, or an action's module-level imports. It answers one question: is
anything about to stop the app from starting?

WHY THIS EXISTS SEPARATELY FROM check_greeting.py
    check_greeting.py proves the greeting *works*. This proves the app can
    *start*. They fail for different reasons and are worth telling apart:

      - a module-level import error kills the process before any window appears,
        which is how "JARVIS doesn't reply at all" happened once (a missing
        `psutil` in ui.py). Nothing is logged, because the logging never runs.
      - a tool that fails to register is skipped **in silence** by the action
        loader, so the assistant simply never offers it. "The file exists" and
        "the assistant can call it" are different facts.

    Neither is caught by reading the code, and both are caught here.

WHAT IT DOES NOT DO
    It does not open the Qt window, open the microphone, or connect to Gemini.
    Those are the parts that cannot be checked without actually running the
    app, so a pass here means "nothing will stop it starting", not "it works".
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Imported by main.py at module level. A failure in any of these stops the whole
# app dead, before a window or a log line — hence the explicit list rather than
# trusting `import main`, which stops at the first failure and reports only that.
REQUIRED_MODULES = (
    "main", "ui",
    "core.gemini", "core.action_loader", "core.plugin_loader", "core.timefmt",
    "core.tts", "core.stt", "core.wake_word", "core.audio_devices",
    "core.newsroom_client", "core.newsroom_watch",
    "actions.web_search", "actions.weather_report", "actions.daily_briefing",
    "actions.newsroom_search", "actions.newsroom_outlet", "actions.newsroom_digest",
    "actions.newsroom_status",
)

# Tools the assistant is useless without. `get_current_time` is declared inline
# in main.py rather than in actions/, so it is checked against the combined list.
REQUIRED_TOOLS = ("get_current_time", "daily_briefing", "weather_report", "web_search",
                  "newsroom_search", "newsroom_outlet_news", "newsroom_digest",
                  "newsroom_status")


def show_config() -> list[str]:
    """The settings that decide what happens at startup, and which of them
    silently switch behaviour off."""
    print("=" * 78)
    print("CONFIG  (config/api_keys.json)")
    problems: list[str] = []

    path = ROOT / "config" / "api_keys.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"  parses as JSON      : yes, {len(data)} key(s)")
        print(f"  keys                : {', '.join(sorted(data))}")
    except Exception as e:
        print(f"  parses as JSON      : FAILED — {e!r}")
        return ["config/api_keys.json does not parse"]

    from memory import config_manager as cm
    print(f"  is_configured()     : {cm.is_configured()}")
    if not cm.is_configured():
        problems.append("no Gemini API key — the app cannot connect")

    # These two are the switches that turn behaviour off without an error.
    brief = cm.get_brief_enabled()
    wake = cm.get_wake_word_enabled()
    print(f"  morning_brief_enabled : {brief}   <- gates the STARTUP GREETING")
    print(f"  wake_word_enabled     : {wake}")
    if not brief:
        print("      note: off, so nothing will be spoken at startup. The name")
        print("            says 'news' but the news is a tool now — this flag's")
        print("            only remaining effect is the greeting.")

    print(f"  assistant / user    : {cm.get_assistant_name()!r} / {cm.get_user_name()!r}")
    print(f"  voice               : {cm.get_voice()}")

    # The AI Newsroom bridge: where the news now comes from, and whether the
    # unprompted announcements are armed.
    print(f"  newsroom env        : {cm.get_newsroom_env_path()}")
    print(f"  newsroom watch      : {cm.get_newsroom_enabled()}   "
          f"<- speaks new news UNPROMPTED when true")
    print(f"  newsroom quiet hours: {cm.get_newsroom_quiet_hours()[0]:02d}:00-"
          f"{cm.get_newsroom_quiet_hours()[1]:02d}:00 MMT")

    # _news_settings() lives in actions/web_search.py, which is edited often and
    # has been shipped in a state where it was missing. A bare call here would
    # turn a missing function into a crash of this whole script — which is
    # precisely what it used to do.
    try:
        from actions import web_search as ws
        s = ws._news_settings()
        print(f"  briefing engines    : world={s['world_engine']}, "
              f"myanmar={s['myanmar_engine']}")
    except Exception as e:
        print(f"  briefing engines    : UNAVAILABLE — {type(e).__name__}: {e}")
        print("      note: daily_briefing will fall back to the AI Newsroom only.")
    return problems


def check_imports() -> list[str]:
    print("=" * 78)
    print("IMPORTS  (a module-level failure stops the app before it can log)")
    problems: list[str] = []
    for name in REQUIRED_MODULES:
        try:
            __import__(name)
            print(f"  OK    {name}")
        except Exception as e:
            print(f"  FAIL  {name} — {type(e).__name__}: {e}")
            problems.append(f"import {name} failed")
    return problems


def check_tools() -> list[str]:
    """The declarations the model is actually offered.

    Built the way main.py builds them — inline declarations, then the action
    registry, then plugins — because a tool present in one list and absent from
    the other is offered to nobody.
    """
    print("=" * 78)
    print("TOOLS  (a TOOL dict that fails validation is skipped in silence)")
    problems: list[str] = []

    import main as M
    from core.action_loader import discover_actions
    from core.plugin_loader import discover_plugins

    inline = [t["name"] for t in M.TOOL_DECLARATIONS]
    registry = discover_actions(ROOT / "actions")
    plugins = discover_plugins(ROOT / "plugins",
                               core_tool_names=set(inline) | registry.names())

    names = (inline
             + [d["name"] for d in registry.get_tool_declarations()]
             + [d["name"] for d in plugins.get_tool_declarations()])

    print(f"  inline in main.py   : {len(inline)}")
    print(f"  from actions/       : {len(registry.names())}")
    print(f"  from plugins/       : {len(plugins.get_tool_declarations())}")
    print(f"  TOTAL offered       : {len(names)}")

    collisions = sorted({n for n in names if names.count(n) > 1})
    print(f"  name collisions     : {', '.join(collisions) or 'none'}")
    if collisions:
        problems.append(f"duplicate tool name(s): {collisions}")

    for want in REQUIRED_TOOLS:
        ok = want in names
        print(f"    {'OK     ' if ok else 'MISSING'} {want}")
        if not ok:
            problems.append(f"tool {want} is not offered to the model")

    return problems


def main() -> int:
    problems = show_config() + check_imports() + check_tools()

    print("=" * 78)
    if problems:
        print("RESULT: NOT READY TO START")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("RESULT: ALL OK — nothing found that would stop it starting.")
    print()
    print("Start it with:   py main.py")
    print()
    print("Watch the console for, in order:")
    print("    Action discovery complete: 17 active.")
    print("    [JARVIS] Connecting...")
    print("    [JARVIS] Connected.")
    print("    [JARVIS] Briefing phase 1 (greeting) sent.")
    print()
    print("That last line means the greeting was handed to the model. If it is")
    print("missing, the greeting is gated off — check morning_brief_enabled.")
    print("Then ask 'ဒီနေ့ဘာထူးလဲ' and expect a [JARVIS] 🔧 daily_briefing line.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
