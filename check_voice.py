"""Is the cloned voice wired up correctly?

    py check_voice.py

WHY THIS EXISTS SEPARATELY FROM test_fish_tts.py
    test_fish_tts.py talks to Fish Audio and asks whether the voice can speak
    the language. This asks the questions that have nothing to do with the
    network, and they are the ones that fail silently:

      * the voice id collapses back to Charon somewhere in the config layer, so
        the assistant is handed a prebuilt voice and never says so;
      * the registry names a reference_id nobody configured;
      * the API key is missing, which reads as "the feature does not work"
        rather than as a credentials problem;
      * the rate this module delivers audio at drifts away from the rate
        main.py's player runs at — which does not fail, it just makes her sound
        like a different person.

    All of those are cheap to check and none of them need a request.

RUN THE OTHER ONE TOO
    Passing here means the plumbing is right. It says nothing about whether the
    words come out — see the docstring in test_fish_tts.py for why that is a
    separate question with a separate answer.
"""
import sys
from pathlib import Path

sys.path.insert(0, r"E:\Mark-LIV-main")

from core import custom_voice                                  # noqa: E402
from memory import config_manager as cfg                       # noqa: E402


def _head(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def _ok(label: str, good: bool, detail: str = "") -> bool:
    print(f"  [{'OK ' if good else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return good


def main() -> int:
    passed = True
    enabled: list[str] = []

    _head("1. THE REGISTRY")
    print(f"  file: {custom_voice.VOICES_FILE}")
    voices = custom_voice.load_voices()
    passed &= _ok("at least one cloned voice is registered", bool(voices))
    for vid, entry in voices.items():
        on = custom_voice.is_enabled(entry)
        if on:
            enabled.append(vid)
        print(f"\n  {vid}")
        print(f"    label         {entry.get('label') or '(none)'}")
        print(f"    engine        {entry.get('engine') or 'fish'}")
        print(f"    reference_id  {custom_voice.reference_id(entry) or '(none)'}")
        print(f"    state         {'enabled' if on else 'DISABLED'}")
        if not on:
            print(f"    reason        {entry.get('disabled_reason') or '(none given)'}")
        passed &= _ok(f"{vid}: has a reference_id",
                      bool(custom_voice.reference_id(entry)))

    if not enabled:
        # A disabled voice is a decision, not a fault. The assistant uses a
        # prebuilt voice and everything below is about the cloned path, so there
        # is nothing here to pass or fail.
        _head("VERDICT")
        print("  no cloned voice is enabled. The registry has entries, but every one")
        print("  is marked `disabled`, so the assistant speaks with a prebuilt voice.")
        print("  Read `disabled_reason` in voice/voices.json for what has to change.")
        return 0

    _head("2. SETTINGS")
    key = cfg.get_fish_api_key()
    print(f"  fish_api_key     {'…' + key[-4:] if key else '(not set)'}")
    print(f"  fish_reference_id {cfg.get_fish_reference_id()}")
    print(f"  fish_model        {cfg.get_fish_model() or '(default: s2.1-pro)'}")
    print(f"  fish_latency      {cfg.get_fish_latency()}")
    passed &= _ok("a Fish Audio API key is configured", bool(key),
                  "py test_fish_tts.py --key sk-fish-…")

    try:
        from voice import fish_tts
        print(f"\n  {fish_tts.describe()}")
    except Exception as e:                                      # noqa: BLE001
        passed &= _ok("the Fish Audio module imports", False, str(e))

    problem = custom_voice.problem()
    passed &= _ok("the cloned voice is usable", not problem, problem)

    _head("3. THE RATE AGREES WITH THE PLAYER")
    # main.py plays whatever arrives in audio_in_queue at RECEIVE_SAMPLE_RATE,
    # so a mismatch here is not an error — it is her speaking at the wrong
    # pitch, which sounds like a bad clone rather than a wrong constant.
    try:
        import main
        main_rate = main.RECEIVE_SAMPLE_RATE
    except Exception as e:                                      # noqa: BLE001
        main_rate = None
        print(f"  could not import main: {e}")
    print(f"  custom_voice.SAMPLE_RATE  {custom_voice.SAMPLE_RATE}")
    print(f"  main.RECEIVE_SAMPLE_RATE  {main_rate}")
    passed &= _ok("the two rates match", main_rate == custom_voice.SAMPLE_RATE)

    _head("4. CONFIG ROUND-TRIP  (the value is restored afterwards)")
    original = cfg.get_voice()
    print(f"  voice_name before: {original!r}")
    vid = enabled[0]
    cfg.save_voice(vid)
    stored = cfg.get_voice()
    print(f"  after save_voice({vid!r}): {stored!r}")
    passed &= _ok("a cloned voice survives the config layer", stored == vid,
                  "get_voice() collapsed it to a prebuilt voice"
                  if stored != vid else "")
    prebuilt = cfg.get_prebuilt_voice()
    print(f"  get_prebuilt_voice() -> {prebuilt!r}  (what the Live API is given)")
    passed &= _ok("the Live API is never handed a cloned id",
                  prebuilt in cfg.AVAILABLE_VOICES)
    cfg.save_voice(original)
    print(f"  voice_name restored: {cfg.get_voice()!r}")
    passed &= _ok("the original setting was restored",
                  cfg.get_voice() == original)

    _head("5. THE PICKER")
    choices = cfg.voice_choices()
    for value, label in choices:
        mark = "prebuilt" if value in cfg.AVAILABLE_VOICES else "CLONED "
        print(f"  [{mark}] {value:18} {label}")
    passed &= _ok("the cloned voice is offered in the picker",
                  any(v == vid for v, _ in choices))

    _head("VERDICT")
    if passed:
        print("  the plumbing is right. Whether the words come out is a different")
        print("  question — run:  py test_fish_tts.py")
    else:
        print("  something above failed — the cloned voice will not be used, and")
        print("  replies will arrive in the prebuilt voice instead.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
