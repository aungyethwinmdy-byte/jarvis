"""Fish Audio TTS — the cloud half of the assistant's cloned voice.

WHY THIS EXISTS
    JARVIS speaks with a Gemini prebuilt voice, and the Live API takes a prebuilt
    name and nothing else — there is no field for a custom or cloned voice, so a
    cloned voice cannot be routed through the session at all. It needs a second
    way out. This is the synthesiser for that second path: text in, audio out,
    over Fish Audio's HTTP API. `core/custom_voice.py` owns everything around it
    (the registry, the cache, and handing the audio to the player).

WHY IT ASKS FOR WAV AT 24 kHz
    The reply has to reach `main.py`'s existing audio queue, which the Live API
    fills with raw 16-bit mono PCM at 24 kHz, and which is played, viseme-mapped
    and echo-guarded on that assumption. Fish can be asked for exactly that
    (`wav` supports 8/16/24/32/44.1 kHz, 16-bit mono), so nothing here has to
    decode MP3 or resample — the bytes arrive in the shape the player already
    expects. Requesting MP3 would mean a decoder plus a resampler between the
    API and the speaker, which is more code and one more thing to go wrong.

WHAT A FAILURE LOOKS LIKE
    `synthesize()` raises `FishAudioError` with the reason in it — the HTTP
    status and the API's own message when there is one. The caller decides what
    to do; `core/custom_voice.py` catches it and lets the reply fall back to the
    audio the Live session already generated, so a Fish outage costs the user
    her voice, not the answer.

ONE FAILURE THAT IS HANDLED HERE INSTEAD
    API credit is bought separately from platform credit, so a key can be
    perfectly valid and still have no credit behind it — every paid model then
    answers HTTP 402. Rather than let the feature die on a billing detail, a 402
    is retried once on the free model. Measured 2026-09-28: s2.1-pro and s2-pro
    both refuse on this account while s2.1-pro-free answers normally. The
    substitution is logged, because it is a change of model.

THE FAILURE THIS MODULE CANNOT HANDLE: BURMESE
    MEASURED 2026-09-28, and it is the reason the assistant's Burmese voice is
    not served from here. Fish Audio returns 200, well-formed 24 kHz audio, and
    a plausible duration for Burmese text — and says something else entirely:

        in   您好，请问有什么可以帮助您的吗？   ->  exact, word for word
        in   Good morning sir, today it will rain in Yangon.
                                            ->  exact, word for word
        in   မင်္ဂလာပါ ဆရာ။ ဒီနေ့ ရန်ကုန်မှာ မိုးရွာမယ်။
                                            ->  "mandoni nato salije manni marma
                                                 meba mapaliye mapitai"

    Burmese-*sounding* phonetics, no words. It is not the voice model: the same
    happens on community voices tagged `languages: ['my']`, and the model this
    install was pointed at (`Daw Aye Thant`, `fa9aed2744a944d0b6dbf054fce628de`)
    is tagged `zh` and has a Chinese reference sample. It is not the token cap
    either — that was tested with and without. The S2 family simply does not
    pronounce Burmese, whatever its language tags suggest.

    So this module is correct and complete, and it is the wrong engine for a
    Burmese assistant. A Burmese-capable engine is required — `f5-myanmar-tts`
    is trained on 794.5 h of Burmese — and `test_fish_tts.py` §5 will say so the
    moment the voice cannot say what it was given. Nothing in the response tells
    you otherwise, which is why that check exists.
"""
from __future__ import annotations

import io
import json
import re
import wave

TTS_URL = "https://api.fish.audio/v1/tts"

# What the assistant's playback path needs. See the module docstring.
FORMAT      = "wav"
SAMPLE_RATE = 24000

DEFAULT_TIMEOUT = 30.0

# Fish's own default is "normal" (best quality). This voice is used for
# conversation, where waiting is the thing people notice, so it is asked for
# "balanced" unless the settings say otherwise.
DEFAULT_LATENCY = "balanced"

# The free developer tier. Used automatically when the account has no API
# credit — see `_post`.
FREE_MODEL = "s2.1-pro-free"

# ── keeping a runaway in check ───────────────────────────────────────────────
# MEASURED 2026-09-28, and this is the reason these numbers exist: with Fish's
# own default of 1024 tokens for max_new_tokens, this voice model sometimes
# spends the whole budget. The same four-second sentence came back as 4.55 s,
# 15.28 s and 47.55 s across three runs — and 47.55 s is exactly 1024 tokens at
# ~21.5 tokens per second of audio. Temperature and repetition penalty made no
# difference; sizing the cap from the text did, and capped runs came back
# 3.7-7.3 s instead of up to 47 s.
#
# These are estimates and only ever used to size a cap and to spot a runaway.
# They never trim audio: a reply that is longer than expected is still played in
# full if it is the shortest one the model would give.
SEC_PER_SYLLABLE  = 0.35
TAIL_SECONDS      = 0.6
TOKENS_PER_SECOND = 21.5
MAX_LENGTH_FACTOR = 2.5
RUNAWAY_RETRIES   = 2


def expected_seconds(text: str) -> float:
    """Roughly how long `text` takes to say.

    Burmese is counted in syllables the way `f5-myanmar-tts` does — a consonant
    that is not part of a stacked pair, because Burmese script marks vowels
    around the consonant rather than as separate letters. Anything else falls
    back to characters, which is crude but only ever sizes a cap: measuring
    Chinese or English in Burmese syllables made every line look over-long and
    triggered retries that could never help.
    """
    text = text or ""
    syllables = len(re.findall(r"[\u1000-\u1021](?!\u103a)", text))
    if syllables:
        return max(0.8, syllables * SEC_PER_SYLLABLE + TAIL_SECONDS)

    cjk = len(re.findall(r"[\u3000-\u9fff\uff00-\uffef]", text))
    other = len(re.sub(r"\s", "", text)) - cjk
    return max(0.8, cjk * 0.20 + other * 0.06 + TAIL_SECONDS)


def _token_cap(text: str) -> int:
    """A ceiling on generated audio tokens, sized from the text."""
    return max(64, int(expected_seconds(text) * MAX_LENGTH_FACTOR * TOKENS_PER_SECOND))


class FishAudioError(RuntimeError):
    """Anything that stopped Fish Audio from answering, carrying the reason."""


# Set once a 402 has told us this account has no API credit. Remembering it
# turns the free-tier fallback from a retry on every line into one wasted
# request per run — the same reasoning as core/gemini.py's quota cooldown.
_free_only = False


def _api_key() -> str:
    try:
        from memory.config_manager import get_fish_api_key
    except Exception as e:                                  # noqa: BLE001
        raise FishAudioError(f"cannot read the settings: {e}") from e
    key = (get_fish_api_key() or "").strip()
    if not key:
        raise FishAudioError(
            "no Fish Audio API key is configured — add fish_api_key to "
            "config/api_keys.json (test_fish_tts.py can do it for you)")
    return key


def _settings() -> dict:
    """Model header and latency, from settings, with working defaults."""
    model, latency = "", DEFAULT_LATENCY
    try:
        from memory.config_manager import get_fish_latency, get_fish_model
        model   = (get_fish_model() or "").strip()
        latency = (get_fish_latency() or DEFAULT_LATENCY).strip() or DEFAULT_LATENCY
    except Exception:                                       # noqa: BLE001
        pass
    if latency not in ("low", "normal", "balanced"):
        latency = DEFAULT_LATENCY
    return {"model": model, "latency": latency}


def synthesize(
    text: str,
    reference_id: str,
    *,
    api_key: str = "",
    model: str = "",
    latency: str = "",
    fmt: str = FORMAT,
    sample_rate: int = SAMPLE_RATE,
    normalize: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """Send `text` to Fish Audio in the voice `reference_id` and return the audio.

    Raises `FishAudioError` for every failure — a missing key, a refused
    request, a timeout, an empty body — because the caller has to be able to say
    what went wrong rather than just that nothing came back.
    """
    text = (text or "").strip()
    if not text:
        raise FishAudioError("nothing to say")
    if not reference_id:
        raise FishAudioError(
            "no reference_id — which Fish Audio voice should speak? "
            "(fish_reference_id in config, or reference_id in voice/voices.json)")

    cfg = _settings()
    key = api_key or _api_key()
    model = model or cfg["model"]
    if not model and _free_only:
        model = FREE_MODEL
    return _post(text, reference_id, key, model,
                 latency or cfg["latency"], fmt, sample_rate, normalize, timeout)


def _post(text: str, reference_id: str, key: str, model: str, latency: str,
          fmt: str, sample_rate: int, normalize: bool, timeout: float) -> bytes:
    """One request. Retries once on the free model when the account has no credit."""
    global _free_only
    payload = {
        "text": text,
        "reference_id": reference_id,
        "format": fmt,
        "sample_rate": sample_rate,
        "latency": latency,
        "normalize": normalize,
        "max_new_tokens": _token_cap(text),
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "audio/*",
    }
    if model:
        # s2.1-pro-free for the free developer tier; omitting it uses s2.1-pro.
        headers["model"] = model

    try:
        import requests
    except Exception as e:                                  # noqa: BLE001
        raise FishAudioError(f"requests is not installed: {e}") from e

    try:
        resp = requests.post(TTS_URL, json=payload, headers=headers, timeout=timeout)
    except Exception as e:                                  # noqa: BLE001
        raise FishAudioError(f"could not reach Fish Audio: "
                             f"{type(e).__name__}: {e}") from e

    if resp.status_code == 402 and model != FREE_MODEL:
        # API credit is bought separately from platform credit, so an account
        # with a working key can still have none of it and every paid model
        # answers 402. Measured 2026-09-28: s2.1-pro and s2-pro both refuse on
        # this account while s2.1-pro-free answers normally. One retry beats a
        # feature that is dead on arrival over a billing detail — and it is
        # logged, because it is a change of model, not a silent substitution.
        print(f"[fish-tts] {model or 's2.1-pro'} needs API credit — "
              f"retrying on {FREE_MODEL} (and using it from now on)")
        _free_only = True
        return _post(text, reference_id, key, FREE_MODEL, latency, fmt,
                     sample_rate, normalize, timeout)

    if resp.status_code != 200:
        detail = (resp.text or "").strip().replace("\n", " ")[:300]
        raise FishAudioError(f"Fish Audio refused the request "
                             f"(HTTP {resp.status_code}): {detail}")

    audio = resp.content
    if not audio:
        raise FishAudioError("Fish Audio returned an empty body")
    return audio


def pcm_from_wav(data: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """The WAV Fish returned, as raw int16 mono PCM at `sample_rate`.

    Checked rather than assumed: the player would happily play a 44.1 kHz file
    at 24 kHz and she would sound like a different person, which reads as a bad
    clone rather than a wrong setting.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
    except Exception as e:                                  # noqa: BLE001
        head = data[:16]
        raise FishAudioError(
            f"the reply is not a readable WAV ({e}); it starts with {head!r}") from e

    if rate != sample_rate:
        raise FishAudioError(f"asked for {sample_rate} Hz, got {rate} Hz")
    if width != 2 or channels != 1:
        raise FishAudioError(f"expected 16-bit mono, got {width * 8}-bit / {channels}ch")
    if not frames:
        raise FishAudioError("the WAV carried no audio")
    return frames


def synthesize_pcm(text: str, reference_id: str, **kwargs) -> bytes:
    """`synthesize`, reduced to the PCM the assistant's player takes.

    Re-asks when the model runs long. The token cap already bounds the damage,
    but a render that comes back well past what the words could take is the
    signature of the runaway described at the top of this file, and a second
    attempt usually lands normally. The shortest result is the one kept, so a
    retry can never make the reply worse than the first try.
    """
    rate = int(kwargs.get("sample_rate") or SAMPLE_RATE)
    want = expected_seconds(text)
    limit = want * MAX_LENGTH_FACTOR

    best: bytes | None = None
    for attempt in range(1 + RUNAWAY_RETRIES):
        pcm = pcm_from_wav(synthesize(text, reference_id, **kwargs), rate)
        got = len(pcm) / 2 / rate
        if got <= limit:
            return pcm
        if best is None or len(pcm) < len(best):
            best = pcm
        print(f"[fish-tts] {got:.1f}s of audio for about {want:.1f}s of text"
              f" — retrying ({attempt + 1} of {1 + RUNAWAY_RETRIES})")
    return best or b""


def settings_fingerprint() -> str:
    """A short string that changes whenever a *setting* changes.

    `core/custom_voice.py` puts this in its cache key, so correcting a setting
    does not keep replaying audio rendered under the old one — the same reason
    the voice's own reference id is in the key there.

    Deliberately excludes the free-tier flag: that is decided per run by whether
    the account has credit, so including it would make the key change under the
    caller's feet and every cached line would be re-synthesised on the second
    call.
    """
    cfg = _settings()
    return f"{cfg['model']}|{cfg['latency']}|{FORMAT}|{SAMPLE_RATE}"


def describe() -> str:
    """One line for a log or a check script: what this module is set up to do."""
    cfg = _settings()
    try:
        key = _api_key()
        key_state = f"key …{key[-4:]}"
    except FishAudioError as e:
        key_state = str(e)
    model = cfg["model"] or (FREE_MODEL if _free_only else "(default: s2.1-pro)")
    return (f"{TTS_URL}  format={FORMAT} sample_rate={SAMPLE_RATE} "
            f"latency={cfg['latency']} model={model}  {key_state}")
