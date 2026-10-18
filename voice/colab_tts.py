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
    (`https://<words>.trycloudflare.com`), paste it over the line below, and
    restart the assistant. Nothing else has to change.

        py test_colab_tts.py     ask this endpoint to speak, and listen to it

THE CONTRACT THE NOTEBOOK HAS TO KEEP
    One route: `POST {COLAB_URL}/speak` with `{"text": "…"}`, answering a WAV of
    16-bit mono 24 kHz PCM. The rate is not cosmetic — main.py's player runs at
    RECEIVE_SAMPLE_RATE (24 kHz) and the WAV header is thrown away here, so a
    server that answered 22.05 kHz would play back flat, sounding like a bad
    clone rather than like a wrong setting. `probe()` reports the rate it got.
"""
from __future__ import annotations

import io
import re
import time
import wave
import requests

COLAB_URL = "https://hospital-pee-candidate-sectors.trycloudflare.com"

# F5 on a free Colab GPU takes its time on a long line; the old 120s ceiling is
# kept. It is the *client's* patience, not the server's, so raising it only
# delays the fallback to the prebuilt voice.
COLAB_TIMEOUT = 120


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


def synthesize_pcm(text: str) -> bytes | None:
  cleaned = _clean_text(text)
  if not cleaned:
    return None

  try:
    url = f"{COLAB_URL.rstrip('/')}/speak"
    resp = requests.post(url, json={"text": cleaned}, timeout=COLAB_TIMEOUT)
    resp.raise_for_status()

    # WAV မှ raw 16-bit mono 24kHz PCM ကို ထုတ်ယူခြင်း
    with wave.open(io.BytesIO(resp.content), "rb") as w:
      return w.readframes(w.getnframes())
  except Exception as e:
    # The most likely cause by far is the tunnel having gone away with the
    # Colab session, and an error without the URL reads like a code fault.
    print(f"[ColabTTS] {type(e).__name__}: {e}")
    print(f"[ColabTTS] endpoint: {COLAB_URL}")
    print(f"[ColabTTS] if this is a timeout or a DNS failure, the Colab notebook "
          f"is not running — start it and paste the new tunnel URL into "
          f"voice/colab_tts.py")
    return None


def probe(text: str = "ဒေါ်အေးသန့် ပြောနေပါတယ်။", timeout: int = 30) -> tuple[bool, str]:
  """Ask the endpoint to speak one short line. Returns (ok, detail).

  A real synthesis request rather than a "health" route: the notebook serves
  `/speak` and nothing else, so a health route answering would prove nothing
  about the route the assistant actually needs. The detail reports the sample
  rate, because that is the one property of a working answer that can be wrong
  without anything failing.
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
