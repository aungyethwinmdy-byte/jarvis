"""Does the cloned voice actually speak? — the Colab F5 tunnel, end to end.

    py test_colab_tts.py                    synthesise a Burmese line and play it
    py test_colab_tts.py --save sample.wav  also write the audio out to listen to
    py test_colab_tts.py --no-play          synthesise without touching the speaker
    py test_colab_tts.py --no-verify        skip the read-back check
    py test_colab_tts.py --text "…"         say something else
    py test_colab_tts.py --voice <id>       use a different entry from voice/voices.json
    py test_colab_tts.py --clear-cache      forget every line already rendered

WHY THIS IS NOT test_fish_tts.py WITH ANOTHER URL
    Two things are true of this engine and neither is true of Fish Audio, and
    both of them fail quietly:

      * the endpoint is a Cloudflare **quick** tunnel, which belongs to one Colab
        session. When the notebook stops, the URL stops answering — and nothing
        about that shows up on its own: the URL is a string, importing it cannot
        raise, the config layer still resolves the voice, and the assistant still
        starts. It fails at the first synthesized reply, and even then the reply
        arrives, in the prebuilt fallback voice. The one visible symptom is the
        wrong voice. So section 1 asks the endpoint directly, and that question is
        the reason to run this at all;

      * F5-Myanmar-TTS is a Burmese model, so the read-back check that
        test_fish_tts.py exists for — catching a voice that renders Burmese as
        Burmese-*sounding* word salad — is a confirmation here rather than a
        rescue. It is still run: "it returned bytes" is not evidence, and this
        project has been bitten by exactly that difference.

WHAT A PASS MEANS
    The endpoint answers with 16-bit mono 24 kHz PCM, the config layer resolves
    the voice without collapsing it to a prebuilt one, and the assistant's own
    synthesis path — not just the client — returns audio for a real Burmese line.
    Start the assistant afterwards and the greeting should be in her voice.

RUN THIS BEFORE THE ASSISTANT, NOT AFTER
    The notebook loads the F5 checkpoint lazily, inside the session's first
    /speak request, and that has taken minutes. This script is that request.
    Paying it here means the assistant's own first reply is quick; skipping it
    means the greeting arrives in the fallback voice instead.

THE CACHE CAN LIE TO YOU, SO SECTION 1 IGNORES IT
    Rendered lines are kept in voice/cache keyed by text. A line rendered before
    the tunnel died still plays, from disk, with no tunnel involved — so a
    correct-sounding reply is not a working endpoint. `health()` and `probe()`
    both go straight to the URL, which is why they are asked first and asked
    separately.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import custom_voice                                  # noqa: E402
from memory import config_manager as cfg                       # noqa: E402
from voice import colab_tts                                    # noqa: E402

# The helpers are shared rather than copied: this asks the same questions about
# format, playback and intelligibility, and a second copy of them would be a
# second thing to keep in step.
try:
    from test_fish_tts import _head, _ok, _overlap, play, read_back, write_wav
except Exception as e:                                          # noqa: BLE001
    print(f"the shared helpers could not be imported from test_fish_tts: {e}")
    raise SystemExit(2)

# The greeting's own opening, because that is the line the owner will hear first
# and the place the voice was most recently wrong: it names him (ကိုသွင်) and the
# assistant (ဂျာဗစ်), which are precisely the two words a voice gets to mispronounce.
DEFAULT_TEXT = "မင်္ဂလာပါ ကိုသွင် ကျွန်တော် ဂျာဗစ် ပါ။ ဒီနေ့ ကိုသွင် ဘာသိချင်လဲ။"


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--voice", default="", help="voice id from voice/voices.json")
    ap.add_argument("--save", default="", help="write the audio here as a WAV")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the read-back that checks the words came out")
    ap.add_argument("--clear-cache", action="store_true")
    args = ap.parse_args()

    passed = True

    _head("1. THE TUNNEL")
    print(f"  {colab_tts.describe()}")

    # Two questions, because they have different answers and one of them is
    # cheap. The health route says whether anything is behind the URL at all;
    # only /speak can say whether the voice works, and its first call is minutes
    # long by design. Asking only the second one made a cold-but-healthy server
    # look like a dead tunnel — measured 2026-10-18.
    live, why = colab_tts.health()
    passed &= _ok("something is answering behind the URL", live, why)
    if not live:
        print()
        print("  The Colab notebook is not answering. That is expected whenever")
        print("  the runtime has stopped, and it is the whole failure this script")
        print("  exists to name: start the notebook, copy the trycloudflare URL")
        print("  its tunnel cell prints, paste it into COLAB_URL in")
        print("  voice/colab_tts.py, and run this again.")
        return 1

    print()
    print("  Now a real synthesis request. This is the session's first, so the")
    print("  notebook loads the F5 checkpoint inside it: minutes of silence is")
    print(f"  the expected shape, not a fault. Waiting up to "
          f"{colab_tts.COLD_TIMEOUT}s...")
    t0 = time.time()
    ok, detail = colab_tts.probe()
    passed &= _ok("the endpoint synthesised a line", ok, detail)
    if not ok:
        print()
        print("  The health route answered, so the tunnel is up and the notebook")
        print("  is running — the fault is inside /speak. The traceback went into")
        print("  the Colab server's pipe, where no window shows it. Read the time")
        print("  above: a 500 back in under a second never reached the checkpoint")
        print("  load, which points at the two things that fail before it — the")
        print("  reference WAV, which every new runtime wipes")
        print("  (/content/ref_aye_thant.wav; upload voice/ref_aye_thant.wav")
        print("  under that name, it is already named correctly on the Desktop) —")
        print("  or f5-tts itself. Minutes instead means the model came up.")
        return 1
    print(f"  the checkpoint is loaded now — that first line took "
          f"{time.time() - t0:.0f}s, and the assistant's replies take seconds")

    _head("2. THE SETTINGS AND THE REGISTRY")
    voices = custom_voice.load_voices()
    for vid, entry in voices.items():
        state = "enabled" if custom_voice.is_enabled(entry) else "DISABLED"
        print(f"  {vid:18} {entry.get('label')}  "
              f"engine={entry.get('engine') or 'fish'}  {state}")
    passed &= _ok("a cloned voice is registered", bool(voices))

    voice_id = args.voice or next(iter(voices), "")
    if not voice_id or voice_id not in voices:
        print(f"  no such voice: {voice_id!r}")
        return 1
    entry = voices[voice_id]
    print(f"  using: {voice_id}  (engine "
          f"{str(entry.get('engine') or 'fish').strip().lower()})")

    selected = cfg.get_voice()
    print(f"  voice_name in the settings   {selected!r}")
    print(f"  get_prebuilt_voice()         {cfg.get_prebuilt_voice()!r}"
          f"  (the Live API's fallback voice)")
    passed &= _ok("the settings select this cloned voice", selected == voice_id,
                  f"the assistant would never use it — set voice_name to "
                  f"{voice_id!r}" if selected != voice_id else "")

    if args.voice:
        # Named on purpose, which is how a disabled entry gets diagnosed, so the
        # readiness gate must not stop it.
        print(f"  testing {voice_id!r} explicitly — the readiness gate is skipped")
    else:
        problem = custom_voice.problem()
        passed &= _ok("the cloned voice is ready to use", not problem, problem)
        if not passed:
            return 1

    if args.clear_cache:
        _head("3. CACHE")
        print(f"  cleared {custom_voice.clear_cache()} rendered line(s)")

    _head("4. THE ASSISTANT'S OWN PATH")
    print(f"  text: {args.text}")
    if args.clear_cache:
        took_note = "  (cache cleared above, so this one is a real request)"
    else:
        took_note = "  (may be served from voice/cache — section 1 was the real ask)"
    t0 = time.time()
    try:
        pcm = custom_voice.synthesize_pcm(args.text, voice_id)
    except Exception as e:                                      # noqa: BLE001
        pcm = None
        print(f"  {type(e).__name__}: {e}")
    took = time.time() - t0

    if pcm is None:
        _ok("custom_voice.synthesize_pcm() returned audio", False,
            "the client answered in section 1, so the fault is above it")
        return 1

    seconds = len(pcm) / 2 / custom_voice.SAMPLE_RATE
    print(f"  got        {len(pcm)} bytes — {seconds:.2f}s of audio")
    print(f"  took       {took:.2f}s")
    print(took_note)
    passed &= _ok("the assistant's synthesis path returned audio", seconds > 0.2)
    passed &= _ok("the audio is at the rate the player runs at",
                  custom_voice.SAMPLE_RATE == 24000,
                  f"custom_voice.SAMPLE_RATE = {custom_voice.SAMPLE_RATE} Hz")

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
                          "it returned audio, but not these words — the "
                          "transcription above is what it really said")
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
        print("  the Colab tunnel is answering and the assistant will speak in")
        print("  this voice. Start the assistant: the console should print")
        print("  [Voice] အသံ — … (Colab F5) at connect time.")
        print()
        print("  Remember this URL dies with the Colab session — every restart of")
        print("  the notebook means a new URL in voice/colab_tts.py.")
    else:
        print("  something above failed — the assistant will fall back to a")
        print("  prebuilt voice rather than lose the reply.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
