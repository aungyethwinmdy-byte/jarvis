"""Colab F5-Myanmar-TTS Client for JARVIS (Optimized).

THE TUNNEL DIES — THAT IS THE NORMAL CASE, NOT A FAULT
    This voice is served by a Colab notebook behind a Cloudflare *quick* tunnel,
    and a quick tunnel belongs to one Colab session. Close the notebook, lose the
    runtime, or let Colab time it out, and `COLAB_URL` below points at a hostname
    that no longer answers: measured 2026-10-18, a request to the old URL hangs
    until the timeout and then fails, while everything in this project still
    looks correctly wired.

    So the URL is a per-session value, not a setting. When the voice goes quiet,
    start the notebook, copy the URL the tunnel cell prints
    (`https://<words>.trycloudflare.com`, from the F5-Myanmar-TTS server
    notebook), paste it over the line below, and restart the assistant. Nothing
    else has to change.

        py test_colab_tts.py     ask the endpoint to speak, and listen to it

THE FIRST CALL IS SLOW, AND THAT LOOKS LIKE A DEAD TUNNEL
    The notebook loads the F5 checkpoint lazily inside the first `/speak`
    request. Measured 2026-10-18, that first call ran past 8 minutes: a healthy
    tunnel and an idle GPU, with nothing coming back. A 30s or 120s ceiling
    cannot tell that apart from a tunnel that is gone — both are silence — so the
    two are separated here instead of guessed at:

      * `health()` asks `GET /`, which the notebook answers without touching the
        model. Milliseconds, whatever state the GPU is in. A dead tunnel fails
        here, fast, and the reply falls back to a prebuilt voice instead of
        hanging;
      * `probe()` then waits up to COLD_TIMEOUT for the real thing, because the
        first `POST /speak` after the notebook starts is legitimately minutes.

    For the same reason, **warm the voice up before restarting the assistant**:

        py test_colab_tts.py

    That first call pays the checkpoint load, and the greeting that follows is
    quick. Skipping it costs the first reply only, which arrives in the fallback
    voice.

THE CONTRACT THE NOTEBOOK HAS TO KEEP
    One route: `POST {COLAB_URL}/speak` with `{"text": "…"}`, answering a WAV of
    16-bit mono 24 kHz PCM, plus `GET /` for the health answer above. The rate is
    not cosmetic — main.py's player runs at RECEIVE_SAMPLE_RATE (24 kHz) and the
    WAV header is discarded here, so a server answering 22.05 kHz would play back
    flat, sounding like a bad clone rather than like a wrong setting. `probe()`
    reports the rate it got.
"""
from __future__ import annotations

import io
import re
import time
import wave
import requests

COLAB_URL = "https://hospital-pee-candidate-sectors.trycloudflare.com"

# One warm line. F5 renders a sentence in a few seconds once the checkpoint is in
# memory; this is the ceiling that turns a stuck server into the fallback voice.
COLAB_TIMEOUT = 120

# `GET /`. The notebook's health route does not touch the model, so this is the
# one question that is always fast — and therefore the only cheap way to tell
# "nothing is behind this URL" from "the GPU is busy".
HEALTH_TIMEOUT = 10

# The first `POST /speak` of a Colab session downloads and loads the checkpoint.
COLD_TIMEOUT = 600


def _clean_text(text: str) -> str:
  """စနစ် tag များ၊ ကွင်းစကွင်းပိတ်များနှင့် emoji များကို ဖယ်ရှားပေးခြင်း။"""
  # Emoji များကို ဖယ်ရှားခြင်း
  text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
  # [JARVIS], [The Irrawaddy] စသည့် စနစ် tag များကို ဖယ်ရှားခြင်း
  text = re.sub(r"\[.*?\]", "", text)
  # အထူးသင်္ကေတများကို ရှင်းထုတ်ခြင်း
  text = re.sub(r"[→📤⚡✓•<>{}|\\]", " ", text)
  text = re.sub(r"\s+", " ", text).strip()
  return text


def health(timeout: int = HEALTH_TIMEOUT) -> tuple[bool, str]:
  """Ask `GET /` whether anything is behind this URL. Returns (ok, detail).

  The notebook's health route is served without loading the model, so this
  answers in milliseconds even while the GPU is still fetching the checkpoint —
  which is exactly what makes it usable as the cheap question that
  `synthesize_pcm()` asks before spending minutes on the expensive one.
  """
  t0 = time.time()
  try:
    resp = requests.get(COLAB_URL.rstrip("/") + "/", timeout=timeout)
    resp.raise_for_status()
    body = " ".join(resp.text.split())[:60]
    return True, f"{resp.status_code} {body} ({time.time() - t0:.1f}s)"
  except Exception as e:  # noqa: BLE001
    return False, f"{type(e).__name__}: {e}"


def synthesize_pcm(text: str) -> bytes | None:
  cleaned = _clean_text(text)
  if not cleaned:
    return None

  # Cheap question first. Without it, a tunnel that has gone quiet costs the
  # full COLAB_TIMEOUT of silence before the reply falls back to a prebuilt
  # voice; with it, the fallback lands in about HEALTH_TIMEOUT. A live server
  # answers this instantly whatever the GPU is doing, so nothing is lost.
  alive, why = health()
  if not alive:
    print(f"[ColabTTS] no answer from {COLAB_URL} — {why}")
    print("[ColabTTS] the Colab session has probably stopped; start the "
          "notebook and paste the new tunnel URL into voice/colab_tts.py")
    return None

  try:
    url = f"{COLAB_URL.rstrip('/')}/speak"
    resp = requests.post(url, json={"text": cleaned}, timeout=COLAB_TIMEOUT)
    resp.raise_for_status()

    # WAV မှ raw 16-bit mono 24kHz PCM ကို ထုတ်ယူခြင်း
    with wave.open(io.BytesIO(resp.content), "rb") as w:
      return w.readframes(w.getnframes())
  except Exception as e:
    print(f"[ColabTTS] {type(e).__name__}: {e}")
    print(f"[ColabTTS] endpoint: {COLAB_URL}")
    print(f"[ColabTTS] the health route answered but this did not — if this is "
          f"the first line spoken since the notebook started, the F5 checkpoint "
          f"is still loading (it has taken minutes). Run `py test_colab_tts.py` "
          f"once to warm it up")
    return None


def probe(text: str = "ဒေါ်အေးသန့် ပြောနေပါတယ်။", timeout: int = COLD_TIMEOUT) -> tuple[bool, str]:
  """Ask the endpoint to speak one short line. Returns (ok, detail).

  A real synthesis request rather than a health route: the notebook serves
  `/speak` and nothing else that matters, so a health route answering proves
  nothing about the route the assistant actually needs. The default ceiling is
  the cold one, because this is the first call of a session by definition — the
  checkpoint load, not the synthesis, is what a short timeout would kill.

  The detail reports the sample rate, because that is the one property of a
  working answer that can be wrong without anything failing.
  """
  cleaned = _clean_text(text) or text
  t0 = time.time()
  try:
    resp = requests.post(f"{COLAB_URL.rstrip('/')}/speak",
                         json={"text": cleaned}, timeout=timeout)
    resp.raise_for_status()
    with wave.open(io.BytesIO(resp.content), "rb") as w:
      frames = w.getnframes()
      rate = w.getframerate()
      channels = w.getnchannels()
      width = w.getsampwidth() * 8
  except Exception as e:  # noqa: BLE001
    return False, f"{type(e).__name__}: {e}"

  if not frames:
    return False, "answered, but with an empty WAV"
  seconds = frames / max(rate, 1)
  return True, (f"{seconds:.1f}s of audio — {rate} Hz, {channels} ch, {width}-bit, "
                f"returned in {time.time() - t0:.1f}s")


def describe() -> str:
  """One line naming the endpoint, for the check scripts."""
  return f"Colab F5-Myanmar-TTS → {COLAB_URL} (POST /speak, 16-bit mono 24 kHz)"
