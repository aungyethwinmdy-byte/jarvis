"""What does JARVIS actually SAY at startup — and does he say what he was given?

    py probe_greeting_live.py

THE QUESTION THIS ANSWERS

    The owner reported on 2026-10-18 that the startup greeting addressed him as
    "ကိုစွင်" instead of "ကိုသွင်", and closed with "ရှင်" instead of "ခင်ဗျာ".
    There are three places that could have come from, and they need three
    different fixes:

        1. the text JARVIS is handed      main.py assembles it — we can read it
        2. the model rewriting that text   only a real session shows this
        3. the voice mispronouncing it     only an ear shows this

    `check_greeting.py` covers (1): it runs the real _send_startup_briefing()
    against a stub session and prints the exact string. It says nothing about
    (2) or (3), because nothing in a stub speaks.

    So this probe drives the real path end to end with no microphone and no Qt:

        _send_startup_briefing()  the real function, against a stub session, to
                                  capture the exact text it would have sent
        a real Live session       the same text, sent as the same kind of turn
        output_transcription      the server's transcription of the audio that
                                  came back — i.e. what a person would hear

    If the two differ, the model is paraphrasing and the fix is in the text or
    the prompt. If they are the same, the text is not the problem.

WHAT IT CANNOT DO

    It cannot hear. `output_transcription` is a string, and a string cannot tell
    you whether the voice rolled a သ into a စ. Nor is it a clean read of the
    audio: it loses a syllable now and then of its own accord, so the verdict is
    a similarity ratio rather than an equality. So it also writes the returned
    audio to `greeting_probe.wav` (24 kHz mono, the same PCM the speaker gets)
    — play that before concluding anything about pronunciation. That file is
    ignored by git, and overwritten on every run.
"""
from __future__ import annotations

import asyncio
import difflib
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, r"E:\Mark-LIV-main")

OUT_WAV = Path(r"E:\Mark-LIV-main\greeting_probe.wav")
SAMPLE_RATE = 24000          # main.RECEIVE_SAMPLE_RATE — the speaker's format

IDLE_DRAIN_S = 20.0          # silence before the turn is called over
HARD_CAP_S = 120.0
MIN_AUDIO_BYTES = 4800       # ~100 ms of 16-bit mono — "not a priming blip"


class _FakeUI:
    muted = False

    def write_log(self, message):
        print(f"    [UI] {message}")

    def set_state(self, state):
        pass

    def show_content(self, label, body):
        pass

    def get_plugins(self):
        return []

    def get_plugin_settings(self):
        return {}


class _CaptureSession:
    """Stands in for the Live session, so the greeting can be read back off it."""

    def __init__(self):
        self.sent = []

    async def send_client_content(self, turns=None, turn_complete=None):
        self.sent.append((turns or {}).get("role", "?") + ": "
                         + turns["parts"][0]["text"])


def _build_app():
    """The real JarvisLive, with the real prompt and the real tool declarations."""
    from main import JarvisLive

    ui = _FakeUI()
    try:
        app = JarvisLive(ui)                      # the real __init__
        print("  app built with the real __init__")
        app.session = _CaptureSession()
        app._session_log = []
        return app
    except Exception as e:                        # noqa: BLE001
        print(f"  real __init__ failed ({type(e).__name__}: {e}); "
              f"falling back to __new__ + real registries")
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


async def capture_greeting(app) -> str:
    """The exact text _send_startup_briefing() would send on connect."""
    cap = _CaptureSession()
    app.session = cap
    app._turn_done_event = None
    app._session_log = []
    await app._send_startup_briefing()
    for line in cap.sent:
        if line.startswith("user: "):
            return line[len("user: "):]
    return ""


async def speak_it(client, app, model, cfg, text) -> dict:
    """Send `text` as the greeting would, and collect what comes back."""
    r = {"out": [], "pcm": bytearray(), "error": "", "msgs": 0, "kinds": []}
    t0 = time.time()
    try:
        async with client.aio.live.connect(model=model, config=cfg) as session:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True)
            last = time.time()

            async def pump():
                nonlocal last
                async for msg in session.receive():
                    last = time.time()
                    r["msgs"] += 1
                    if len(r["kinds"]) < 12:
                        r["kinds"].append(type(msg).__name__)
                    sc = getattr(msg, "server_content", None)
                    if sc is not None:
                        ot = getattr(sc, "output_transcription", None)
                        if ot and getattr(ot, "text", None):
                            r["out"].append(ot.text)
                    if getattr(msg, "data", None):
                        r["pcm"].extend(msg.data)

            task = asyncio.create_task(pump())
            while True:
                await asyncio.sleep(0.5)
                if task.done():
                    break
                # Do not break on the first turn_complete — the same trap
                # probe_moi_live.py documents. Drain until the wire goes quiet.
                if time.time() - last > IDLE_DRAIN_S:
                    break
                if time.time() - t0 > HARD_CAP_S:
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


def write_wav(pcm: bytes) -> bool:
    """The audio, so somebody can LISTEN to it. Returns True if written."""
    if not pcm:
        return False
    try:
        with wave.open(str(OUT_WAV), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        return True
    except Exception as e:                                      # noqa: BLE001
        print(f"  could not write {OUT_WAV}: {type(e).__name__}: {e}")
        return False


async def main() -> int:
    from google import genai
    from memory.config_manager import get_gemini_key
    import main as M

    print("=" * 78)
    print("GREETING PROBE — is the model reading the text, or rewriting it?")
    print("=" * 78)

    key = get_gemini_key()
    if not key:
        print("  no gemini_api_key in config/api_keys.json — cannot run")
        return 2

    print("BUILD")
    app = _build_app()
    sent = await capture_greeting(app)
    print()
    print("--- SENT (what JARVIS is told to say, verbatim) ---")
    print(sent)
    print()
    if not sent:
        print("  *** nothing was sent — the greeting is broken ***")
        return 1

    cfg = app._build_config()
    voice = (cfg.speech_config.voice_config.prebuilt_voice_config.voice_name)
    print(f"  voice  : {voice}")
    client = genai.Client(api_key=key)

    print()
    print("--- SPOKEN (the server's transcription of the audio it produced) ---")
    r = await speak_it(client, app, M.LIVE_MODEL, cfg, sent)
    said = "".join(r["out"]).strip()
    print(said or "(no transcription came back)")
    print()
    print(f"  msgs={r['msgs']} audio={len(r['pcm']):,} bytes "
          f"elapsed={r['elapsed']:.1f}s")
    if r["error"]:
        print(f"  error: {r['error']}")

    wrote = write_wav(bytes(r["pcm"]))
    if wrote:
        print(f"  audio written to {OUT_WAV}  <- listen to this before judging "
              f"pronunciation")

    print()
    print("--- VERDICT ---")
    print(f"  audio produced        : {len(r['pcm']) > MIN_AUDIO_BYTES}")
    print(f"  transcription present : {bool(said)}")
    for probe in ("ကိုသွင်", "ကိုစွင်", "ခင်ဗျာ", "ဗျာ", "ရှင်",
                  "ဂျာဗစ်", "JARVIS", "ကျွန်တော်", "ကျွန်မ"):
        print(f"  contains {probe!r:12}: {probe in said}")
    # Compared, not trusted: the transcriber drops syllables of its own accord
    # (measured here — "ဘာကူညီ" came back as "ာကူညီ" on one run and identically
    # on the next), so an exact match is not the test. A paraphrase moves 10-30%
    # of the sentence; a transcription glitch moves one word.
    target = sent.split("\n")[1] if "\n" in sent else sent
    ratio = difflib.SequenceMatcher(
        None, said.replace(" ", ""), target.replace(" ", "")).ratio()
    print(f"  similarity to the text sent : {ratio:.3f}")
    print(f"  read verbatim               : {ratio > 0.97}")
    if ratio <= 0.97:
        print("     -> read both strings above. A paraphrase means the text or")
        print("        the prompt needs the work; a dropped word is usually the")
        print("        transcriber. Play greeting_probe.wav to settle it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
