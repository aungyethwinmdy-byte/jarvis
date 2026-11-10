"""Acceptance test on PC: Verify JARVIS answers 3 voice questions using jarvis_knowledge.md
and web_search strictly per rules.

1. "ကာကွယ်ရေးဝန်ကြီးက ဘယ်သူလဲ" (Must answer from KB: ဗိုလ်ချုပ်ကြီး ရာပြည့်)
2. "နိုင်ငံခြားရေးဝန်ကြီးဌာန ဝန်ကြီးက ဘယ်သူလဲ" (Must answer from KB: ဦးတင်မောင်ဆွေ)
3. A question not in KB: "ပြင်သစ်နိုင်ငံရဲ့ လက်ရှိ သမ္မတက ဘယ်သူလဲ" (Must call web_search before answering)

All three tested with full voice audio generation and speaker playback.
"""
from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path
import numpy as np
import sounddevice as sd

sys.path.insert(0, r"E:\Mark-LIV-main")
import main as M
from memory.config_manager import get_gemini_key
from google import genai
from google.genai import types
from core import outcome

SAMPLE_RATE = 24000
IDLE_DRAIN_S = 15.0
HARD_CAP_S = 90.0
MIN_AUDIO_BYTES = 4800


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
    ui = _FakeUI()
    try:
        app = M.JarvisLive(ui)
        return app
    except Exception as e:
        print(f"  real __init__ failed ({e}); falling back to __new__")
        from core.action_loader import discover_actions
        from core.plugin_loader import discover_plugins

        app = M.JarvisLive.__new__(M.JarvisLive)
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
        app._plugin_registry = discover_plugins(
            Path(r"E:\Mark-LIV-main\plugins"), logger=lambda *_: None
        )
        return app


async def run_voice_question(client, app, model, cfg, question: str, wav_path: Path) -> dict:
    r = {
        "question": question,
        "out": [],
        "pcm": bytearray(),
        "tools": [],
        "results": [],
        "error": "",
        "msgs": 0,
    }
    t0 = time.time()
    try:
        async with client.aio.live.connect(model=model, config=cfg) as session:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": question}]},
                turn_complete=True,
            )
            last = time.time()
            busy = [False]

            async def pump():
                nonlocal last
                try:
                    async for msg in session.receive():
                        last = time.time()
                        r["msgs"] += 1
                        if getattr(msg, "text", None):
                            print(f"    [MSG.TEXT]: {msg.text}")
                            r["out"].append(msg.text)
                        print(f"    [RAW MSG]: {msg}")

                        sc = getattr(msg, "server_content", None)
                        if sc is not None:
                            print(f"    [SC DETAILS]: waiting_for_input={getattr(sc, 'waiting_for_input', None)}, reason={getattr(sc, 'turn_complete_reason', None)}, model_turn={getattr(sc, 'model_turn', None)}")
                        if sc is not None:
                            mt = getattr(sc, "model_turn", None)
                            if mt:
                                for part in getattr(mt, "parts", []):
                                    if getattr(part, "text", None):
                                        print(f"    [MODEL_TURN TEXT]: {part.text}")
                                        r["out"].append(part.text)
                                    if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                                        print(f"    [MODEL_TURN AUDIO]: {len(part.inline_data.data)} bytes")
                                        r["pcm"].extend(part.inline_data.data)
                            ot = getattr(sc, "output_transcription", None)
                            if ot and getattr(ot, "text", None):
                                print(f"    [OUTPUT_TRANSCRIPTION]: {ot.text}")
                                r["out"].append(ot.text)
                            if getattr(sc, "turn_complete", False):
                                print("    [PUMP] server turn_complete received")

                        tc = getattr(msg, "tool_call", None)
                        if tc and getattr(tc, "function_calls", None):
                            for fc in tc.function_calls:
                                call_str = f"{fc.name} {dict(fc.args or {})}"
                                r["tools"].append(call_str)
                                print(f"    >> TOOL CALL: {call_str}")
                                busy[0] = True
                                t_tool = time.time()
                                try:
                                    resp = await app._execute_tool(fc)
                                finally:
                                    busy[0] = False
                                    last = time.time()
                                tool_s = round(time.time() - t_tool, 1)
                                resp_preview = str(resp.response)[:300]
                                print(f"    << TOOL RESULT ({tool_s}s): {resp_preview}")
                                r["results"].append(f"{fc.name}: {resp_preview}")
                                print("    [PUMP] sending tool response...")
                                clean_resp = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": outcome.unwrap(str(resp.response.get("result", "")))[:1500]}
                                )
                                await session.send_tool_response(function_responses=[clean_resp])
                                print("    [PUMP] tool response sent successfully; signaling turn_complete...")
                                try:
                                    await session.send_client_content(turn_complete=True)
                                except Exception as ce:
                                    print(f"    [PUMP turn_complete notice]: {ce}")
                                last = time.time()

                        if getattr(msg, "data", None):
                            r["pcm"].extend(msg.data)
                except Exception as pe:
                    print(f"    [PUMP EXCEPTION]: {type(pe).__name__}: {pe}")
                    r["error"] = f"pump error: {pe}"

            task = asyncio.create_task(pump())
            while True:
                await asyncio.sleep(0.4)
                if task.done():
                    break
                if not busy[0] and time.time() - last > IDLE_DRAIN_S:
                    break
                if time.time() - t0 > HARD_CAP_S:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                r["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"

    r["elapsed"] = time.time() - t0

    # Write WAV file
    if len(r["pcm"]) > 0:
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(bytes(r["pcm"]))

        # Play audio through speaker
        try:
            pcm_arr = np.frombuffer(bytes(r["pcm"]), dtype=np.int16)
            sd.play(pcm_arr, SAMPLE_RATE)
            sd.wait()
        except Exception as pe:
            print(f"    [Audio Playback Warning]: {pe}")

    return r


async def main() -> int:
    print("=" * 78)
    print("PC ACCEPTANCE TEST — 3 Voice Questions (Knowledge Base & Web Search)")
    print("=" * 78)

    key = get_gemini_key()
    if not key:
        print("FAIL: No gemini_api_key in config/api_keys.json")
        return 1

    app = _build_app()
    cfg = app._build_config()
    client = genai.Client(api_key=key)

    questions = [
        (
            1,
            "ကာကွယ်ရေးဝန်ကြီးက ဘယ်သူလဲ",
            "kb_q1_defence_minister.wav",
            lambda r: "ရာပြည့်" in "".join(r["out"]),
            "ဗိုလ်ချုပ်ကြီး ရာပြည့် (Knowledge Base တိုက်ရိုက်)",
        ),
        (
            2,
            "နိုင်ငံခြားရေးဝန်ကြီးဌာန ဝန်ကြီးက ဘယ်သူလဲ",
            "kb_q2_foreign_minister.wav",
            lambda r: "တင်မောင်ဆွေ" in "".join(r["out"]),
            "ဦးတင်မောင်ဆွေ (Knowledge Base တိုက်ရိုက်)",
        ),
        (
            3,
            "လက်ရှိ ကမ္ဘာ့လူဦးရေ ဘယ်လောက်ရှိလဲ",
            "kb_q3_world_population.wav",
            lambda r: any("web_search" in t for t in r["tools"]) and len(r["out"]) > 0,
            "World Population (KB ထဲမပါ၍ web_search ခေါ်ယူစစ်ဆေးပြီးမှ ဖြေကြားခြင်း)",
        ),
    ]

    all_passed = True
    for idx, q_text, wav_name, validator, expected_desc in questions:
        print("\n" + "-" * 78)
        print(f"TEST {idx}: {q_text}")
        print(f"EXPECTED: {expected_desc}")
        print("-" * 78)

        wav_path = Path(wav_name)
        res = await run_voice_question(client, app, M.LIVE_MODEL, cfg, q_text, wav_path)

        spoken_text = "".join(res["out"]).strip()
        audio_bytes = len(res["pcm"])
        print(f"  AUDIO BYTES : {audio_bytes:,} bytes (saved to {wav_name})")
        print(f"  TOOL CALLS  : {res['tools']}")
        print(f"  SPOKEN TEXT : {spoken_text}")
        print(f"  ELAPSED     : {res['elapsed']:.1f}s")
        if res["error"]:
            print(f"  ERROR       : {res['error']}")

        passed = audio_bytes >= MIN_AUDIO_BYTES and validator(res)
        print(f"  VERDICT     : {'PASSED [OK]' if passed else 'FAILED [X]'}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 78)
    print(f"OVERALL ACCEPTANCE RESULT: {'ALL 3 TESTS PASSED!' if all_passed else 'SOME TESTS FAILED'}")
    print("=" * 78)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
