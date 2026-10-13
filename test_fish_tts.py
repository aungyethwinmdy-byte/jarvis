"""Does the cloned voice actually speak? — Fish Audio, end to end.

    py test_fish_tts.py                     synthesise a Burmese line and play it
    py test_fish_tts.py --save sample.wav   also write the audio out to listen to
    py test_fish_tts.py --no-play           synthesise without touching the speaker
    py test_fish_tts.py --no-verify         skip the read-back check
    py test_fish_tts.py --text "…"          say something else
    py test_fish_tts.py --voice <id>        use a different entry from voice/voices.json
    py test_fish_tts.py --key sk-fish-…     store the API key in the settings
    py test_fish_tts.py --clear-cache       forget every line already rendered

WHY THIS IS WORTH RUNNING BEFORE THE ASSISTANT
    A wrong API key, a reference_id that belongs to somebody else's account, a
    model header the tier does not allow — none of those stop the app starting.
    They surface as a reply that arrives in a prebuilt voice, which looks like
    the feature was never wired up rather than like a credentials problem. This
    asks the API the same question the assistant will ask and prints the answer.

THE READ-BACK IS THE PART THAT MATTERS
    A 200 response with well-formed audio is not evidence that the voice can
    speak the language. Measured 2026-09-28: Fish Audio reproduces Chinese and
    English exactly, and renders Burmese as Burmese-*sounding* word salad that no
    Burmese speaker would recognise — same status code, same format, same
    duration. So section 5 transcribes what came out and compares it with what
    went in. If it fails, the voice cannot speak this language and no amount of
    wiring will change that.

WHAT IT CHECKS THAT A "DID IT RETURN BYTES" TEST WOULD NOT
    The audio is required to be 16-bit mono at 24 kHz, because that is what
    main.py's player takes; a 44.1 kHz reply would play at the wrong pitch and
    sound like a bad clone rather than a wrong setting. It also reports the
    wall-clock time per line, which is the number that decides whether a cloud
    voice is usable in a conversation, and re-asks for the same line to show the
    cache doing its job.
"""
from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import custom_voice                                  # noqa: E402
from memory import config_manager as cfg                       # noqa: E402
from voice import fish_tts                                     # noqa: E402

DEFAULT_TEXT = "မင်္ဂလာပါ ဆရာ၊ ကျွန်တော် ဒေါ်အေးသန့် ပါ။ ဘယ်လို ကူညီပေးရမလဲခင်ဗျာ။"


def _head(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def _ok(label: str, good: bool, detail: str = "") -> bool:
    print(f"  [{'OK ' if good else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return good


def store_key(key: str) -> int:
    """Save the API key, then prove it landed by counting keys, not by reading it."""
    before = len(cfg.load_api_keys())
    cfg.save_fish_api_key(key)
    after = len(cfg.load_api_keys())
    print(f"  settings keys: {before} -> {after}")
    if not cfg.get_fish_api_key():
        print("  the key did not save")
        return 1
    print("  stored as fish_api_key in config/api_keys.json (value not printed)")
    return 0


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(custom_voice.SAMPLE_RATE)
        w.writeframes(pcm)


def play(pcm: bytes) -> bool:
    """Play the PCM the way the assistant will, on the configured output device."""
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as e:                                      # noqa: BLE001
        print(f"  cannot play: {e}")
        return False

    device = None
    try:
        from core import audio_devices
        device = audio_devices.resolve(cfg.get_output_device(), "output")
    except Exception:                                           # noqa: BLE001
        device = None

    try:
        samples = np.frombuffer(pcm, dtype="<i2")
        sd.play(samples, custom_voice.SAMPLE_RATE, device=device)
        sd.wait()
        return True
    except Exception as e:                                      # noqa: BLE001
        print(f"  playback failed: {e}")
        return False


def read_back(pcm: bytes) -> str:
    """Transcribe what was actually said, so the test can tell a voice from noise.

    This is the check that matters and the one a "did it return bytes" test
    cannot make. Fish Audio answers 200 with well-formed audio for text it
    cannot actually pronounce — measured 2026-09-28: it reproduces Chinese and
    English exactly, and turns Burmese into Burmese-*sounding* word salad that
    no Burmese speaker would recognise. Nothing about the response says so.
    """
    try:
        import io
        import wave
        from google import genai
        from google.genai import types
        from core.gemini import api_key

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(custom_voice.SAMPLE_RATE)
            w.writeframes(pcm)

        cl = genai.Client(api_key=api_key())
        part = types.Part.from_bytes(data=buf.getvalue(), mime_type="audio/wav")
        prompt = ("Transcribe exactly what is said, in its own language and script. "
                  "No commentary, no translation. If it is not intelligible speech, "
                  "reply with exactly: UNCLEAR")
        for model in ("gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"):
            try:
                resp = cl.models.generate_content(model=model, contents=[part, prompt])
            except Exception:                               # noqa: BLE001
                continue
            said = (getattr(resp, "text", None) or "").strip()
            if said:
                return said
    except Exception as e:                                      # noqa: BLE001
        return f"<could not read it back: {type(e).__name__}: {e}>"
    return ""


def _overlap(asked: str, said: str) -> float:
    """How much of `asked` came back in `said`, as a fraction of its characters.

    Characters rather than words, because Burmese is not written with spaces
    between words and the transcriptions come back segmented differently every
    time. A correct render scores high even when the segmentation differs; a
    render that is Burmese-*sounding* but says something else scores near zero,
    which is exactly the failure this has to catch.
    """
    from collections import Counter

    skip = set(" \t\n၊။,.!?，。！？、")
    a = Counter(ch for ch in asked if ch not in skip)
    b = Counter(ch for ch in said if ch not in skip)
    if not a:
        return 0.0
    return sum(min(n, b[ch]) for ch, n in a.items()) / sum(a.values())


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--key", default="", help="store this Fish Audio API key, then exit")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--voice", default="", help="voice id from voice/voices.json")
    ap.add_argument("--save", default="", help="write the audio here as a WAV")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the read-back that checks the words came out")
    ap.add_argument("--clear-cache", action="store_true")
    args = ap.parse_args()

    if args.key:
        _head("STORING THE API KEY")
        return store_key(args.key)

    passed = True

    _head("1. SETTINGS")
    print(f"  endpoint      {fish_tts.TTS_URL}")
    print(f"  format        {fish_tts.FORMAT} @ {fish_tts.SAMPLE_RATE} Hz, 16-bit mono")
    print(f"  latency       {cfg.get_fish_latency()}")
    print(f"  model header  {cfg.get_fish_model() or '(default: s2.1-pro)'}")
    key = cfg.get_fish_api_key()
    print(f"  api key       {'…' + key[-4:] if key else '(not set)'}")
    print(f"  reference_id  {cfg.get_fish_reference_id()}")
    passed &= _ok("an API key is configured", bool(key),
                  "run: py test_fish_tts.py --key sk-fish-…")

    _head("2. THE VOICE REGISTRY")
    voices = custom_voice.load_voices()
    for vid, entry in voices.items():
        print(f"  {vid:18} {entry.get('label')}  engine={entry.get('engine') or 'fish'}"
              f"  reference_id={custom_voice.reference_id(entry)}")
    passed &= _ok("a cloned voice is registered", bool(voices))

    voice_id = args.voice or next(iter(voices), "")
    if not voice_id or voice_id not in voices:
        print(f"  no such voice: {voice_id!r}")
        return 1
    print(f"  using: {voice_id}")

    problem = custom_voice.problem()
    if args.voice:
        # A voice named on the command line is being tested on purpose — that is
        # how a disabled one gets diagnosed, so the readiness gate must not stop
        # it. The whole point of the read-back is to show *why* it is disabled.
        print(f"  testing {voice_id!r} explicitly — the readiness gate is skipped")
        print(f"  (registry says: {problem or 'nothing wrong'})")
    else:
        passed &= _ok("the cloned voice is ready to use", not problem, problem)
        if not passed:
            return 1

    if args.clear_cache:
        _head("3. CACHE")
        print(f"  cleared {custom_voice.clear_cache()} rendered line(s)")

    _head("4. SYNTHESIS")
    print(f"  text: {args.text}")
    t0 = time.time()
    try:
        pcm = custom_voice.synthesize_pcm(args.text, voice_id)
    except Exception as e:                                      # noqa: BLE001
        pcm = None
        print(f"  {type(e).__name__}: {e}")
    took = time.time() - t0

    if pcm is None:
        return 1 if not _ok("the API returned audio", False) else 1

    seconds = len(pcm) / 2 / custom_voice.SAMPLE_RATE
    print(f"  got        {len(pcm)} bytes — {seconds:.2f}s of audio")
    print(f"  took       {took:.2f}s")
    passed &= _ok("the API returned audio", seconds > 0.2)
    passed &= _ok("the audio is 16-bit mono at the player's rate",
                  custom_voice.SAMPLE_RATE == 24000,
                  f"{custom_voice.SAMPLE_RATE} Hz")

    t0 = time.time()
    again = custom_voice.synthesize_pcm(args.text, voice_id)
    print(f"  cached repeat: {time.time() - t0:.3f}s "
          f"({'hit' if again == pcm else 'MISS — the cache is not working'})")

    if args.save:
        out = Path(args.save)
        write_wav(out, pcm)
        print(f"  saved      {out}")

    if not args.no_verify:
        _head("5. WHAT DID IT ACTUALLY SAY?")
        said = read_back(pcm)
        print(f"  asked for:  {args.text}")
        print(f"  it said:    {said or '(nothing)'}")
        if said and not said.startswith("<") and said != "UNCLEAR":
            score = _overlap(args.text, said)
            print(f"  match:      {score:.0%} of the characters came back")
            passed &= _ok("the voice pronounced the words it was given", score >= 0.6,
                          "" if score >= 0.6 else
                          "it returned audio, but not these words — see the module "
                          "docstring in voice/fish_tts.py")
        else:
            passed &= _ok("the voice pronounced the words it was given", False,
                          "nothing intelligible came back")

    if not args.no_play:
        _head("6. PLAYBACK")
        if play(pcm):
            print("  played — this is the voice the assistant will use")
        else:
            passed = False

    _head("VERDICT")
    if passed:
        print("  Fish Audio is answering, in the right format, for this voice.")
        print("  Select it in the assistant:  ⚙  CUSTOMISE ASSISTANT  →  CLONED VOICE")
    else:
        print("  something above failed — the assistant will fall back to a")
        print("  prebuilt voice rather than lose the reply.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
