"""
Cloned voices — the assistant's second audio output path.
Updated to support Colab F5-Myanmar-TTS alongside Fish Audio.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import threading

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

VOICES_FILE = _BASE / "voice" / "voices.json"
CACHE_DIR   = _BASE / "voice" / "cache"

# The rate the Live audio path plays at (24 kHz)
SAMPLE_RATE = 24000


# ── the registry ─────────────────────────────────────────────────────────────

_voices_cache: dict[str, dict] | None = None
_voices_lock = threading.Lock()


def load_voices() -> dict[str, dict]:
    """The cloned voices on disk, keyed by id."""
    global _voices_cache
    with _voices_lock:
        if _voices_cache is not None:
            return _voices_cache
        out: dict[str, dict] = {}
        try:
            raw = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
            for entry in raw.get("voices", []):
                vid = str(entry.get("id") or "").strip()
                if vid:
                    out[vid] = entry
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            print(f"[CustomVoice] registry unreadable: {e}")
        _voices_cache = out
        return out


def reload_voices() -> dict[str, dict]:
    """Forget the cached registry."""
    global _voices_cache
    with _voices_lock:
        _voices_cache = None
        return load_voices()


def get_custom_voice(voice_id: str) -> dict | None:
    """The entry for `voice_id`, or None if it is not a cloned voice."""
    if not voice_id:
        return None
    return load_voices().get(str(voice_id).strip())


def is_custom_voice(voice_id: str) -> bool:
    """Registered and enabled."""
    entry = get_custom_voice(voice_id)
    return entry is not None and is_enabled(entry)


def is_enabled(entry: dict) -> bool:
    """Whether this voice may be selected."""
    return not bool(entry.get("disabled"))


def reference_id(entry: dict) -> str:
    """Which voice the engine should speak in."""
    own = str(entry.get("reference_id") or "").strip()
    if own:
        return own
    try:
        from memory.config_manager import get_fish_reference_id
        return get_fish_reference_id()
    except Exception:  # noqa: BLE001
        return ""


def problem() -> str:
    """'' when the cloned voice looks usable, else the reason it does not."""
    voices = load_voices()
    if not voices:
        return f"no cloned voices registered in {VOICES_FILE}"

    usable = {k: v for k, v in voices.items() if is_enabled(v)}
    if not usable:
        why = next((str(v.get("disabled_reason") or "").strip()
                    for v in voices.values() if not is_enabled(v)), "")
        return f"every registered voice is disabled — {why or 'no reason given'}"

    for entry in usable.values():
        engine = str(entry.get("engine") or "fish").strip().lower()
        if engine not in ("fish", "colab"):
            return f"voice '{entry.get('id')}' names an unknown engine: {engine}"

        if engine == "fish":
            if not reference_id(entry):
                return f"voice '{entry.get('id')}' has no reference_id"
            try:
                from memory.config_manager import get_fish_api_key
                if not get_fish_api_key():
                    return "no Fish Audio API key is configured (fish_api_key)"
            except Exception as e:  # noqa: BLE001
                return f"cannot read the settings: {e}"

    return ""


# ── synthesis ────────────────────────────────────────────────────────────────

def _cache_path(voice_id: str, text: str, ref_id: str) -> Path:
    """Where the rendering of `text` in this voice is kept."""
    entry = get_custom_voice(voice_id) or {}
    engine = str(entry.get("engine") or "fish").strip().lower()
    
    if engine == "colab":
        settings = "colab_f5_24k"
    else:
        try:
            from voice import fish_tts
            settings = fish_tts.settings_fingerprint()
        except Exception:  # noqa: BLE001
            settings = "?"

    digest = hashlib.sha1(
        f"{voice_id}\x00{ref_id}\x00{settings}\x00{text}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{voice_id}_{digest[:16]}.pcm"


def synthesize_pcm(text: str, voice_id: str) -> bytes | None:
    """Render `text` in the cloned voice and return raw int16 mono PCM at 24 kHz."""
    text = (text or "").strip()
    entry = get_custom_voice(voice_id)
    if not text or entry is None:
        return None

    ref_id = reference_id(entry) or "colab_ref"

    cached = _cache_path(voice_id, text, ref_id)
    try:
        if cached.exists() and cached.stat().st_size > 0:
            return cached.read_bytes()
    except OSError:
        pass

    engine = str(entry.get("engine") or "fish").strip().lower()
    try:
        if engine == "colab":
            from voice import colab_tts
            pcm = colab_tts.synthesize_pcm(text)
        else:
            from voice import fish_tts
            pcm = fish_tts.synthesize_pcm(text, ref_id)
    except Exception as e:  # noqa: BLE001
        print(f"[CustomVoice] synthesis failed: {e}")
        return None

    if not pcm:
        print("[CustomVoice] synthesis returned no audio")
        return None

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(pcm)
    except Exception as e:  # noqa: BLE001
        print(f"[CustomVoice] could not cache the audio: {e}")

    return pcm


def clear_cache() -> int:
    """Delete every rendered line."""
    if not CACHE_DIR.exists():
        return 0
    try:
        count = sum(1 for p in CACHE_DIR.iterdir() if p.is_file())
    except OSError:
        return 0
    if not count:
        return 0
    import subprocess
    try:
        subprocess.run(
            ["node", "-e",
             "require('fs').rmSync(process.argv[1],{force:true,recursive:true})",
             str(CACHE_DIR)],
            check=True, timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[CustomVoice] could not clear the cache: {e}")
        return 0
    return count