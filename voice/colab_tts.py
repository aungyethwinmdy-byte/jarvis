"""Colab F5-Myanmar-TTS Client for JARVIS (Optimized)."""

from __future__ import annotations

import io
import re
import wave
import requests

COLAB_URL = "https://hospital-pee-candidate-sectors.trycloudflare.com"


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
    # timeout ကို ၁၂၀ စက္ကန့်အထိ တိုးမြှင့်ထားပါသည်
    resp = requests.post(url, json={"text": cleaned}, timeout=120)
    resp.raise_for_status()

    # WAV မှ raw 16-bit mono 24kHz PCM ကို ထုတ်ယူခြင်း
    with wave.open(io.BytesIO(resp.content), "rb") as w:
      return w.readframes(w.getnframes())
  except Exception as e:
    print(f"[ColabTTS] Error: {e}")
    return None