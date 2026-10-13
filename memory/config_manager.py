import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}


def get_file_access_roots() -> list[str]:
    """Folders outside the home directory that JARVIS is allowed to touch.

    Empty by default, which is the safe state: JARVIS is confined to the home
    directory unless the user says otherwise. See `actions/file_controller.py`
    `_extra_roots()` for what reads this and why the boundary is widened from
    the settings file rather than from code.
    """
    raw = load_api_keys().get("file_access_roots")
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    return []


def save_file_access_roots(roots: list[str]) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["file_access_roots"] = [str(r).strip() for r in roots if str(r).strip()]
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Assistant voice ──────────────────────────────────────────────────────────
# Gemini Live prebuilt voices. Names are proper nouns — identical in every
# language, so this list is safe to show verbatim in any locale.
AVAILABLE_VOICES = ["Charon", "Puck", "Kore", "Fenrir", "Aoede"]
DEFAULT_VOICE    = "Charon"

# What the Live API is handed while a *cloned* voice is selected.
#
# A cloned voice cannot be sent to the Live API at all — it takes a prebuilt
# name and nothing else — so when one is chosen the session is opened with this
# instead and the reply is re-spoken locally by core/custom_voice.py. Kore is
# female, which makes the degradation a change of timbre rather than a change of
# who is speaking if the local engine is unavailable.
CUSTOM_VOICE_FALLBACK = "Kore"


def _custom_voice_registry() -> dict:
    """The cloned voices on disk, or {} — imported lazily because
    core/custom_voice.py reads settings back out of this module."""
    try:
        from core.custom_voice import load_voices
        return load_voices()
    except Exception:
        return {}


def is_custom_voice_name(voice_name: str) -> bool:
    """True when `voice_name` names a registered cloned voice that may be used.

    A voice the registry marks `disabled` is not one of these: it is registered
    so the check scripts can still see it, but the assistant must fall back to a
    prebuilt voice rather than speak in a voice that is known not to work.
    """
    v = str(voice_name or "").strip()
    if not v:
        return False
    entry = _custom_voice_registry().get(v)
    if entry is None:
        return False
    return not bool(entry.get("disabled"))


def voice_choices() -> list[tuple[str, str]]:
    """(value, label) for the picker — prebuilt voices first, then cloned ones.

    The value is what gets stored and what main.py branches on; the label is
    only ever drawn. Keeping them apart is what lets a cloned voice be called
    "ဒေါ်အေးသန့်" while its id stays ASCII. Disabled entries are left out
    entirely — the picker should not offer a voice that cannot speak.
    """
    out = [(v, v) for v in AVAILABLE_VOICES]
    for vid, entry in _custom_voice_registry().items():
        if entry.get("disabled"):
            continue
        out.append((vid, str(entry.get("label") or vid)))
    return out


def get_voice() -> str:
    """The selected voice: a prebuilt name, or the id of a cloned voice.

    Unrecognised values still collapse to the default — a bad value must never
    reach the API — but a *registered* cloned voice is now a valid answer, which
    is the whole point of the second output path.
    """
    v = str(load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE).strip()
    if v in AVAILABLE_VOICES or is_custom_voice_name(v):
        return v
    return DEFAULT_VOICE


def get_prebuilt_voice() -> str:
    """What to hand the Live API's PrebuiltVoiceConfig.

    `get_voice()` may legitimately return a cloned voice id, and the Live API
    would refuse it, so this is the one place that translates a cloned choice
    into the prebuilt name the session can actually be opened with.
    """
    v = get_voice()
    return v if v in AVAILABLE_VOICES else CUSTOM_VOICE_FALLBACK


# ── Fish Audio (the cloned voice) ────────────────────────────────────────────
# The cloned voice is synthesised by Fish Audio rather than by the Live API, so
# it needs credentials of its own. The key is a secret and lives here with the
# others; the reference id is not a secret but is kept beside it because the two
# are always changed together.
DEFAULT_FISH_REFERENCE_ID = "fa9aed2744a944d0b6dbf054fce628de"


def get_fish_api_key() -> str:
    """The Fish Audio API key, or '' when it has not been set."""
    return str(load_api_keys().get("fish_api_key", "") or "").strip()


def save_fish_api_key(key: str) -> None:
    _patch_config(fish_api_key=str(key or "").strip())


def get_fish_reference_id() -> str:
    """The Fish Audio voice model id — which cloned voice to speak in."""
    v = str(load_api_keys().get("fish_reference_id", "") or "").strip()
    return v or DEFAULT_FISH_REFERENCE_ID


def save_fish_reference_id(reference_id: str) -> None:
    _patch_config(fish_reference_id=str(reference_id or "").strip())


def get_fish_model() -> str:
    """The `model` header to send, or '' to let Fish Audio choose.

    Fish Audio's free developer tier needs `s2.1-pro-free`; leaving this blank
    sends no header and the service falls back to its own default.
    """
    return str(load_api_keys().get("fish_model", "") or "").strip()


def save_fish_model(model: str) -> None:
    _patch_config(fish_model=str(model or "").strip())


FISH_LATENCIES = ("low", "balanced", "normal")


def get_fish_latency() -> str:
    """How hard to trade quality for speed. 'balanced' by default.

    This voice is used for conversation, and the thing people notice in a
    conversation is waiting — not the last few percent of audio quality.
    """
    v = str(load_api_keys().get("fish_latency", "") or "").strip().lower()
    return v if v in FISH_LATENCIES else "balanced"


def save_fish_latency(latency: str) -> None:
    v = str(latency or "").strip().lower()
    _patch_config(fish_latency=v if v in FISH_LATENCIES else "balanced")


def save_voice(voice_name: str) -> None:
    """Persist the chosen voice. Unknown names collapse to the default so a
    bad value can never reach the API and break the session."""
    v = (voice_name or "").strip()
    if v not in AVAILABLE_VOICES and not is_custom_voice_name(v):
        v = DEFAULT_VOICE
    _patch_config(voice_name=v)


def get_wake_word_enabled() -> bool:
    """Whether local wake-word gating is on (assistant sleeps until 'Hey Jarvis')."""
    return load_api_keys().get("wake_word_enabled", False)


def save_wake_word_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["wake_word_enabled"] = bool(enabled)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_push_to_talk_enabled() -> bool:
    """Hold-a-key-to-speak. When on, the mic is closed unless the chord is held."""
    return load_api_keys().get("push_to_talk_enabled", False)


def save_push_to_talk_enabled(enabled: bool) -> None:
    _save_flag("push_to_talk_enabled", enabled)


HUD_STYLES = ("face", "core")


def get_hud_style() -> str:
    """Which centrepiece the HUD draws: the animated head, or the reactor core.

    Taste, not capability — both render in the same software painter and cost
    about the same. Defaults to the head because that is what MARK LIV shipped
    with; anyone who preferred the older look can switch back in ⚙ and the
    choice survives a restart.
    """
    v = str(load_api_keys().get("hud_style", "face")).strip().lower()
    return v if v in HUD_STYLES else "face"


def save_hud_style(style: str) -> None:
    s = str(style or "").strip().lower()
    _save_flag("hud_style", s if s in HUD_STYLES else "face")


# ── Live-session tuning ──────────────────────────────────────────────────────
# Everything here is optional and has a working default, so an untouched
# config behaves exactly like a configured one. Each value is also a way out:
# if a future model dislikes one of these, set it back and nothing else changes.

def get_thinking_enabled() -> bool:
    """Whether the Live model may spend tokens thinking before it answers.

    Off by default. A voice assistant is judged on how fast it starts talking,
    and the reasoning that actually needs deliberation in this app is delegated
    to the planning tools, which run on a separate non-Live model.
    """
    return bool(load_api_keys().get("thinking_enabled", False))


def save_thinking_enabled(enabled: bool) -> None:
    _save_flag("thinking_enabled", enabled)


def get_turn_tuning() -> dict:
    """How eagerly the server decides you have stopped speaking.

    OFF by default, and that default was earned. Cutting turns shorter looks
    like a free speed win and is not: proactive audio has to judge whether an
    utterance was even addressed to the assistant, and a turn clipped early
    gives it less to judge, so it stays quiet — and the reply to your first
    sentence only arrives once your second one has given it enough context.
    That reads as the assistant being a turn behind, which is far worse than
    the fraction of a second the tuning saves.

    Turn it on with "turn_tuning": {"enabled": true} if your own microphone and
    speaking pace suit it. `silence_ms` is the one that is felt: the pause the
    server sits through before accepting your turn is over.
    """
    cfg = load_api_keys().get("turn_tuning")
    cfg = cfg if isinstance(cfg, dict) else {}

    def _int(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(cfg.get(key, default))))
        except (TypeError, ValueError):
            return default

    return {
        "enabled":    bool(cfg.get("enabled", False)),
        "silence_ms": _int("silence_ms", 550, 200, 3000),
        "prefix_ms":  _int("prefix_ms", 150, 0, 1000),
        # "high" = quicker to decide speech has ended.
        "end_sensitivity":   str(cfg.get("end_sensitivity", "high")).lower(),
        "start_sensitivity": str(cfg.get("start_sensitivity", "default")).lower(),
    }


def save_turn_tuning(values: dict) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cur = data.get("turn_tuning")
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    data["turn_tuning"] = cur
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_proactive_audio_enabled() -> bool:
    """Whether the model gets to decide an utterance was not aimed at it and
    stay quiet.

    On by default — it is what stops the assistant answering the room. But it
    is also the first thing to switch off if replies ever seem to arrive a turn
    late: what looks like lag is usually the model having judged your previous
    sentence as not addressed to it, and only changing its mind once the next
    one arrives.
    """
    return bool(load_api_keys().get("proactive_audio", True))


def save_proactive_audio_enabled(enabled: bool) -> None:
    _save_flag("proactive_audio", enabled)


MEDIA_RESOLUTIONS = ("default", "low", "medium", "high")


def get_media_resolution() -> str:
    """How finely the model tokenises the screenshots and camera frames it is
    sent. 'medium' keeps on-screen text readable at a fraction of the tokens a
    full-resolution frame costs; 'low' is cheaper still but starts losing small
    text, which is most of what screen captures are for."""
    v = str(load_api_keys().get("media_resolution", "medium")).strip().lower()
    return v if v in MEDIA_RESOLUTIONS else "medium"


def save_media_resolution(value: str) -> None:
    v = str(value or "").strip().lower()
    _save_flag("media_resolution", v if v in MEDIA_RESOLUTIONS else "medium")


def _save_flag(key: str, value) -> None:
    """Read-modify-write one key without disturbing the rest of the config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = bool(value) if isinstance(value, bool) else value
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["morning_brief_enabled"] = enabled
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── AI Newsroom bridge ───────────────────────────────────────────────────────
# JARVIS reads the news AI Newsroom has already collected and analysed (see
# core/newsroom_client.py). These settings cover the one part that speaks
# without being asked, so they are separate from morning_brief_enabled — that
# switch gates the greeting, and conflating the two is how the news started
# being broadcast at every launch in the first place.

DEFAULT_NEWSROOM_ENV = r"E:\AI_NEWSROOM\.env"


def get_newsroom_enabled() -> bool:
    """Whether JARVIS speaks newly analysed news unprompted.

    Off by default. The newsroom's own auto_runner already pushes to Telegram,
    so a user who has not asked for voice alerts should not get a second
    channel they did not request — and this is the switch that decides it.
    """
    return bool(load_api_keys().get("newsroom_watch_enabled", False))


def save_newsroom_enabled(enabled: bool) -> None:
    _save_flag("newsroom_watch_enabled", bool(enabled))


def get_newsroom_env_path() -> str:
    """Path to the newsroom's .env, which holds the Supabase credentials.

    Stored as a path rather than copying the keys here so there is exactly one
    copy of the secret on disk. If AI Newsroom moves, one setting changes.
    """
    v = str(load_api_keys().get("newsroom_env_path", "") or "").strip()
    return v or DEFAULT_NEWSROOM_ENV


def save_newsroom_env_path(path: str) -> None:
    _save_flag("newsroom_env_path", str(path or "").strip())


# ── The second newsroom: my_reporter ─────────────────────────────────────────
#
# `E:\test\my_reporter-main` runs its own Supabase project and reads the two
# state newspapers (Myanma Alinn, The Mirror) plus the Page-2 fuel and gold
# table. It is a different database from the one above — verified 2026-09-29,
# different URL and different service key — so it needs its own path and its own
# credentials. Kept as a path for the same reason: one copy of each secret.

DEFAULT_REPORTER_ENV = r"E:\test\my_reporter-main\.env"


def get_reporter_env_path() -> str:
    """Path to the my_reporter .env, which holds its Supabase credentials."""
    v = str(load_api_keys().get("reporter_env_path", "") or "").strip()
    return v or DEFAULT_REPORTER_ENV


def save_reporter_env_path(path: str) -> None:
    _save_flag("reporter_env_path", str(path or "").strip())


def get_newsroom_poll_minutes() -> int:
    """How often the voice watcher checks for newly analysed reports.

    Fifteen minutes, not one: the newsroom itself only runs hourly, so a
    tighter poll would mostly re-ask a database that has not changed.
    """
    try:
        v = int(load_api_keys().get("newsroom_poll_minutes", 15))
    except (TypeError, ValueError):
        v = 15
    return max(2, min(120, v))


def save_newsroom_poll_minutes(minutes: int) -> None:
    try:
        v = max(2, min(120, int(minutes)))
    except (TypeError, ValueError):
        v = 15
    _save_flag("newsroom_poll_minutes", v)


def get_newsroom_quiet_hours() -> tuple[int, int]:
    """(start_hour, end_hour) in MMT during which nothing is spoken unprompted.

    Default 22:00–06:00. A voice assistant that announces a headline at 3am is
    not a feature. Wraps midnight, so start > end is normal and expected.
    """
    try:
        start = int(load_api_keys().get("newsroom_quiet_start", 22))
        end = int(load_api_keys().get("newsroom_quiet_end", 6))
    except (TypeError, ValueError):
        start, end = 22, 6
    return max(0, min(23, start)), max(0, min(23, end))


def save_newsroom_quiet_hours(start: int, end: int) -> None:
    _patch_config(newsroom_quiet_start=max(0, min(23, int(start))),
                  newsroom_quiet_end=max(0, min(23, int(end))))


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, and there is one place where a corrupt config file is
    handled instead of nine."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_google_maps_api_key() -> str:
    """The Google Maps API key, or '' when it has not been set."""
    k = load_api_keys().get("google_maps_api_key") or load_api_keys().get("GOOGLE_MAPS_API_KEY")
    return str(k or "").strip()


def save_google_maps_api_key(key: str) -> None:
    """Persist Google Maps API key to config/api_keys.json."""
    _patch_config(google_maps_api_key=str(key or "").strip())


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


# ── Per-plugin settings ("tokens" / connection details) ───────────────────────
# Generic store so a plugin can declare its own config fields (PLUGIN_SETTINGS)
# and the settings UI renders + persists them WITHOUT any core edit — keeping the
# drop-in model intact. Values live under plugin_config[<namespace>][<key>].
# A namespace defaults to the plugin name, but a suite of plugins (e.g. the
# several printer plugins) can share ONE namespace.
def get_plugin_config(namespace: str) -> dict:
    """All stored values for a namespace (empty dict if none set yet)."""
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    """A single value from a namespace, or `default` if unset."""
    return get_plugin_config(namespace).get(key, default)


def save_plugin_config(namespace: str, values: dict) -> None:
    """Merge `values` into a namespace's stored config (read-modify-write, like
    every other helper here). Only the provided keys are touched."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")