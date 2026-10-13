"""Live test: the owner's question, through the REAL JARVIS decision path.

    py probe_moi_live.py
    py probe_moi_live.py "မနေ့က ဒုတိယသမ္မတ သတင်းတွေရှိလား"

WHY THIS IS NOT A HANDLER TEST

    `check_moi.py` proves the tool behaves. It says nothing about whether the
    MODEL picks it, fills its parameters, or speaks the answer. Measured
    2026-10-01: four defects survived 430/430 handler checks and were only found
    by running a real turn.

    So this probe drives the **real** objects:

        JarvisLive._build_config()   the real system prompt + every tool declaration
        JarvisLive._execute_tool()   the real dispatcher, including _news_route

    **The question is passed with no section and no `days`** — the model has to
    choose both. A live test that fills in an optional argument the model may not
    fill is not the owner's test.

THE PROBE TRAPS THIS AVOIDS (each was a real false conclusion)

    * **A 1007 on a turn can mean "wrong input transport", not "not entitled".**
      Measured here: `send_client_content` is accepted by the SDK — no exception
      at send time — and the server then closes with
      `1007 Request contains an invalid argument` during receive. The first
      version of this probe reported "the model made no tool call at all" for a
      model that answers over `send_realtime_input`. So the transports are tried
      in turn, each on a fresh session, and the failure is reported as a
      transport verdict rather than as a model verdict.
    * **Do not break on the first `turn_complete`.** An earlier probe reported
      "the model said nothing after the tool call"; it had stopped before the
      model spoke. The same question with a drain-until-idle loop produced
      610,562 bytes of audio. Drain for >= 30 s of silence AND a hard wall-clock
      cap, and print the byte count next to the transcript so "nothing was said"
      and "we stopped listening" cannot be confused.
    * **`output_transcription` is on `msg.server_content`, not on the message.**
    * **A `toolCall` pauses the turn until it is answered.** A probe that logs the
      call without replying observes no audio at all.
    * **A 1-byte reply is not a reply** — a minimum byte count is required.
    * **A receive-loop exception must be printed.** Swallowing it turns "the loop
      died" into "the model was silent", which is the same defect one level down.
"""
from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, r"E:\Mark-LIV-main")

QUESTION = (sys.argv[1] if len(sys.argv) > 1
            else "မနေ့က ဒုတိယသမ္မတ သတင်းတွေရှိလား")

IDLE_DRAIN_S = 30.0      # silence before we conclude the turn is over
HARD_CAP_S = 180.0       # never sit here forever
MIN_AUDIO_BYTES = 4800   # ~100 ms at 24 kHz mono int16 — "not a 2-byte priming blip"
# `send_realtime_input` first: it is the transport the newer Live models accept.
TRANSPORTS = ("send_realtime_input", "send_client_content")


class _FakeUI:
    muted = False

    def write_log(self, message):
        print(f"    [UI] {message}")

    def set_state(self, state):
        pass

    def show_content(self, label, body):
        print(f"    [UI content] {label}: {str(body)[:200]}")

    def get_plugins(self):
        return []

    def get_plugin_settings(self):
        return {}


def _build_app():
    """The real JarvisLive, with the real prompt and the real dispatcher."""
    from main import JarvisLive

    ui = _FakeUI()
    try:
        app = JarvisLive(ui)                      # the real __init__
        print("  app built with the real __init__")
        return app
    except Exception as e:                        # noqa: BLE001
        print(f"  real __init__ failed ({type(e).__name__}: {e}); "
              f"falling back to __new__ + real registries")
        from pathlib import Path
        from core.action_loader import discover_actions
        from core.plugin_loader import discover_plugins
        app = JarvisLive.__new__(JarvisLive)
        app.ui = ui
        app._asst_name = "JARVIS"
        app.session = None
        app._turn_done_event = None
        app._session_log = []
        app._tool_call_history = []
        app._rejected_fields = set()
        app._tuned_live = False
        app._resume_handle = None
        app._action_registry = discover_actions(Path(r"E:\Mark-LIV-main\actions"))
        app._plugin_registry = discover_plugins(Path(r"E:\Mark-LIV-main\plugins"),
                                               logger=lambda *_: None)
        return app


async def run_turn(client, app, model, cfg, transport: str) -> dict:
    """One attempt on a fresh session. Never raises — returns what happened."""
    r = {"transport": transport, "audio": 0, "out": [], "in": [], "tools": [],
         "results": [], "turns": 0, "msgs": 0, "kinds": [], "error": ""}
    t0 = time.time()
    try:
        async with client.aio.live.connect(model=model, config=cfg) as session:
            r["connect_s"] = time.time() - t0
            if transport == "send_client_content":
                await session.send_client_content(
                    turns={"parts": [{"text": QUESTION}]}, turn_complete=True)
            else:
                await session.send_realtime_input(text=QUESTION)
            r["sent_s"] = time.time() - t0

            last = time.time()
            # `busy` is a list so the closure can mutate it. It exists because the
            # drain loop counts silence, and a tool call IS silence on the wire:
            # measured 2026-10-01, `moi_news` spent ~20 s walking pages, the drain
            # loop called that "30 s idle", and it cancelled the pump mid-tool —
            # reporting "no spoken reply" for a turn that had not finished.
            busy = [False]

            async def pump():
                nonlocal last
                async for msg in session.receive():
                    last = time.time()
                    r["msgs"] += 1
                    sc = getattr(msg, "server_content", None)
                    kind = type(msg).__name__
                    if sc is not None:
                        if getattr(sc, "turn_complete", False):
                            kind += "+turn_complete"
                        if getattr(sc, "interrupted", False):
                            kind += "+interrupted"
                    if getattr(msg, "tool_call", None):
                        kind += "+tool_call"
                    if getattr(msg, "data", None):
                        kind += "+audio"
                    if len(r["kinds"]) < 25:
                        r["kinds"].append(kind)
                    if sc is not None:
                        it = getattr(sc, "input_transcription", None)
                        if it and getattr(it, "text", None):
                            r["in"].append(it.text)
                        ot = getattr(sc, "output_transcription", None)
                        if ot and getattr(ot, "text", None):
                            r["out"].append(ot.text)
                        if getattr(sc, "turn_complete", False):
                            r["turns"] += 1
                            # deliberately do NOT break
                    tc = getattr(msg, "tool_call", None)
                    if tc and getattr(tc, "function_calls", None):
                        for fc in tc.function_calls:
                            r["tools"].append(f"{fc.name} {dict(fc.args or {})}")
                            print(f"  >> TOOL CALL: {fc.name} {dict(fc.args or {})}")
                            busy[0] = True
                            t_tool = time.time()
                            try:
                                resp = await app._execute_tool(fc)
                            finally:
                                busy[0] = False
                                last = time.time()
                            r["tool_s"] = round(time.time() - t_tool, 1)
                            print(f"  << result ({r['tool_s']}s): {str(resp.response)[:500]}")
                            r["results"].append(f"{fc.name}: {str(resp.response)[:900]}")
                            await session.send_tool_response(function_responses=[resp])
                    if getattr(msg, "data", None):
                        r["audio"] += len(msg.data)

            task = asyncio.create_task(pump())
            while True:
                await asyncio.sleep(0.5)
                if task.done():
                    break
                # A tool call in flight is not silence — see `busy` above.
                if not busy[0] and time.time() - last > IDLE_DRAIN_S:
                    print(f"  idle {IDLE_DRAIN_S:.0f}s — draining complete")
                    break
                if time.time() - t0 > HARD_CAP_S:
                    print(f"  hard cap {HARD_CAP_S:.0f}s reached")
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:                              # noqa: BLE001
                r["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:                                      # noqa: BLE001
        r["error"] = f"{type(e).__name__}: {e}"
    r["elapsed"] = time.time() - t0
    return r


async def main() -> int:
    from google import genai
    from memory.config_manager import get_gemini_key
    import main as M

    print("=" * 78)
    print("LIVE TEST — the real decision path, no microphone")
    print("=" * 78)
    print(f"  question : {QUESTION}")
    print(f"  model    : {M.LIVE_MODEL}")
    print()

    key = get_gemini_key()
    if not key:
        print("  no gemini_api_key in config/api_keys.json — cannot run")
        return 2

    print("BUILD")
    app = _build_app()
    cfg = app._build_config()
    # Read the DECLARATIONS, not `str(cfg)` — a string search over the config
    # reported `moi_news declared: False` for a tool that was loaded and declared.
    names: list[str] = []
    for t in (getattr(cfg, "tools", None) or []):
        for fd in (getattr(t, "function_declarations", None) or []):
            names.append(getattr(fd, "name", "") or "")
    print(f"  config built: {len(names)} tool declarations")
    print(f"  moi_news declared: {'moi_news' in names}")
    if "moi_news" not in names:
        print(f"  declared: {sorted(names)}")
    print()

    client = genai.Client(api_key=key)

    best = None
    for transport in TRANSPORTS:
        print(f"--- transport: {transport} ---")
        r = await run_turn(client, app, M.LIVE_MODEL, cfg, transport)
        print(f"  msgs={r['msgs']} turns={r['turns']} tools={len(r['tools'])} "
              f"audio={r['audio']:,} elapsed={r['elapsed']:.1f}s")
        if r["error"]:
            print(f"  error: {r['error']}")
        if r["kinds"]:
            print(f"  frames: {r['kinds']}")
        if r["audio"] >= MIN_AUDIO_BYTES:
            best = r
            print("  -> produced a spoken reply; stopping here")
            break
        if r["error"] and "1007" in r["error"]:
            print("  -> 1007 is a transport verdict for this model, trying the next")
        print()

    if best is None:
        print("=" * 78)
        print("NO TRANSPORT PRODUCED A REPLY")
        print("=" * 78)
        print("  This is reported as a transport/session result, NOT as a model")
        print("  verdict, and NOT as a tool-choice result: no turn completed, so")
        print("  nothing about the model's routing was measured.")
        return 1

    r = best
    print()
    print("=" * 78)
    print("WHAT HAPPENED")
    print("=" * 78)
    print(f"  transport      : {r['transport']}")
    print(f"  heard (input)  : {''.join(r['in'])!r}")
    print(f"  tool calls     : {len(r['tools'])}")
    for t in r["tools"]:
        print(f"      {t}")
    print(f"  turn_complete  : {r['turns']}")
    print(f"  audio bytes    : {r['audio']:,}   (>= {MIN_AUDIO_BYTES} required)")
    print(f"  elapsed        : {r['elapsed']:.1f}s")
    print()
    print("  TOOL RESULT")
    for x in r["results"]:
        print("   ", x.replace("\n", "\n     ")[:1200])
    print()
    print("  SPOKEN (output transcription)")
    print("   ", "".join(r["out"]).replace("\n", "\n     ")[:1500])
    print()

    print("VERDICT")
    verdict = []
    if not r["tools"]:
        verdict.append("FAIL: the model made no tool call at all")
    else:
        first = r["tools"][0]
        if "moi_news" not in first:
            verdict.append(f"FAIL: it chose {first.split()[0]}, not moi_news")
        else:
            verdict.append("OK: it chose moi_news")
        if "'section'" not in first and '"section"' not in first:
            verdict.append(f"NOTE: no section in the call: {first}")
        else:
            verdict.append("OK: it named the section")
        if "days" in first or "date" in first:
            verdict.append("OK: it filled a time window")
        else:
            verdict.append("NOTE: no days/date — the window came from the tool default")
    verdict.append(f"OK: it spoke ({r['audio']:,} bytes)"
                   if r["audio"] >= MIN_AUDIO_BYTES
                   else f"FAIL: only {r['audio']} bytes of audio")
    for v in verdict:
        print("   ", v)
    return 0 if all(v.startswith("OK") or v.startswith("NOTE") for v in verdict) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
