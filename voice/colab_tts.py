"""Colab F5-Myanmar-TTS Client for JARVIS (Optimized).

WHY THIS TALKS TO THE SERVER WITH urllib3 AND NOT requests  (measured 2026-10-18)
    Six attempts each, against a host that never changes state:

        requests.get("https://www.cloudflare.com/")     0/6 answered
        urllib3.PoolManager(...).request("GET", ...)    6/6, median 1.5s
        curl.exe GET the same URL                       8/8, median 2.0s

    It is reproducible to the attempt and specific to Cloudflare-fronted hosts.
    The same six attempts against a Google-hosted endpoint answer requests
    normally, and the old tunnel answered curl while it hung requests. Both
    libraries sit on the same OpenSSL build and the same sockets — requests is
    urllib3 underneath — so the difference is something requests adds around
    urllib3 that could not be pinned down from outside. It does not matter for
    the decision: a voice that cannot complete a request is not a voice, and one
    transport was measured answering. `curl.exe` answers too, but shelling out
    per spoken line to move a WAV in and out of a temp file is a worse trade than
    two lines of urllib3.

    The timeout is per request rather than the pool default, and retries are off:
    with urllib3's default Retry, a stalled /speak would be attempted four times,
    turning a 120s ceiling into eight minutes of silence before the fallback.

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
    `POST {COLAB_URL}/speak` with `{"text": "…"}`, answering a WAV of 16-bit mono
    24 kHz PCM, plus `GET /` for the health answer above. The rate is not
    cosmetic — main.py's player runs at RECEIVE_SAMPLE_RATE (24 kHz) and the WAV
    header is discarded here, so a server answering 22.05 kHz would play back
    flat, sounding like a bad clone rather than like a wrong setting. `probe()`
    reports the rate it got.

    A v2 notebook also serves `GET/POST /ref` (the reference clip) and
    `POST /reftext`, which is how this client keeps the pair in place on a
    runtime that has just been wiped, and `GET /log`, which is how a traceback
    inside the server can be read at all. Older notebooks serve only the first
    two routes, and everything here still works against them: those three are
    used when they are there.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import ssl
import time
import wave
from pathlib import Path

import urllib3
from urllib3.util import Retry, Timeout

COLAB_URL = "https://serum-penguin-width-cyber.trycloudflare.com"

# One warm line. F5 renders a sentence in a few seconds once the checkpoint is in
# memory; this is the ceiling that turns a stuck server into the fallback voice.
COLAB_TIMEOUT = 120

# `GET /`. The notebook's health route does not touch the model, so this is the
# one question that is always fast — and therefore the only cheap way to tell
# "nothing is behind this URL" from "the GPU is busy".
HEALTH_TIMEOUT = 10

# The first `POST /speak` of a Colab session downloads and loads the checkpoint.
COLD_TIMEOUT = 600

CONNECT_TIMEOUT = 10

# The reference clip and its transcript, as they live on this machine — not in
# Colab. A Colab runtime wipes /content, and the notebook's server cannot reach
# back here to fetch anything, so the client is what keeps the pair in place:
# after every health answer it compares the clip the server is holding with this
# one and sends both if they differ.
#
# They are a pair, and that is the whole point of the sha1. F5 clones a voice by
# reading the transcript of the reference clip and lining the recording up with
# those words; the transcript of a *different* recording still produces fluent
# Burmese, in the wrong rhythm, saying words nobody said — measured on this
# setup, and nothing in the response says anything is wrong.
REF_WAV = Path(__file__).with_name("ref_aye_thant.wav")
REF_TXT = Path(__file__).with_name("ref_aye_thant.txt")

# ssl.create_default_context() is named explicitly. It is python's own context,
# with the system trust store, and it is the configuration that was measured
# answering (see the module docstring).
_POOL = urllib3.PoolManager(
    ssl_context=ssl.create_default_context(),
    retries=Retry(0),
    timeout=Timeout(connect=CONNECT_TIMEOUT, read=HEALTH_TIMEOUT),
)


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


def _speak_request(text: str, read_timeout: int):
  """One POST /speak. Raises whatever urllib3 raises; the callers catch it."""
  body = json.dumps({"text": text}).encode("utf-8")
  return _POOL.request(
    "POST", COLAB_URL.rstrip("/") + "/speak",
    body=body,
    headers={"Content-Type": "application/json"},
    timeout=Timeout(connect=CONNECT_TIMEOUT, read=read_timeout),
    retries=False,
  )


def server_info(timeout: int = HEALTH_TIMEOUT) -> tuple[bool, dict]:
  """`GET /` — what the server says about itself. Returns (ok, dict).

  The notebook answers this without touching the model, so it is the cheap
  question; the dict is also where the server reports whether it is holding a
  reference clip and which one, which is how the client knows whether to send
  its own before asking for something to be spoken.

  A notebook older than v2 answers `{"status": "ok", "service": ...}` and nothing
  else, and that has to keep working — the keys are looked up, never assumed.
  """
  try:
    resp = _POOL.request(
      "GET", COLAB_URL.rstrip("/") + "/",
      timeout=Timeout(connect=CONNECT_TIMEOUT, read=timeout),
      retries=False,
    )
    body = resp.data.decode("utf-8", "replace")
    status = resp.status
    resp.release_conn()
    if status != 200:
      return False, {"error": f"HTTP {status}: {body[:80]}"}
    try:
      return True, json.loads(body)
    except ValueError:
      return True, {"raw": body[:80]}
  except Exception as e:  # noqa: BLE001
    return False, {"error": f"{type(e).__name__}: {e}"}


def health(timeout: int = HEALTH_TIMEOUT) -> tuple[bool, str]:
  """Ask `GET /` whether anything is behind this URL. Returns (ok, detail).

  The same question as `server_info()`, with the answer left as one line for a
  console or a check script.
  """
  t0 = time.time()
  ok, info = server_info(timeout)
  if not ok:
    return False, str(info.get("error", "no answer"))
  ref = info.get("ref")
  refpart = "" if ref is None else f" ref={'yes' if ref else 'NO'}"
  return True, (f"200 {json.dumps(info, ensure_ascii=False)[:70]} "
                f"({time.time() - t0:.1f}s{refpart})")


def local_reference() -> tuple[bytes, str] | tuple[None, None]:
  """This machine's reference clip and its transcript, or (None, None).

  Both or neither: half a pair is not a slower voice, it is a wrong one.
  """
  try:
    wav = REF_WAV.read_bytes()
    text = REF_TXT.read_text(encoding="utf-8").strip()
  except (OSError, UnicodeDecodeError):
    return None, None
  return (wav, text) if text else (None, None)


def _post(path: str, body: bytes, content_type: str, read_timeout: int = 60):
  """One POST with a raw body. Raises what urllib3 raises; callers catch it."""
  return _POOL.request(
    "POST", COLAB_URL.rstrip("/") + path,
    body=body,
    headers={"Content-Type": content_type},
    timeout=Timeout(connect=CONNECT_TIMEOUT, read=read_timeout),
    retries=False,
  )


def ensure_reference(info: dict) -> str:
  """Put this machine's reference pair on the server. Returns one line for a log.

  Never raises, and never decides whether the voice works: on a server with no
  `/ref` route the line says so and the request goes ahead with whatever
  reference the server holds, which is the behaviour before this existed.
  """
  if "ref_sha1" not in info:
    return "server has no /ref route (notebook older than v2)"

  wav, text = local_reference()
  if wav is None:
    return (f"no {REF_WAV.name} + {REF_TXT.name} on this machine — the server's "
            f"own reference will be used (ref={info.get('ref')})")

  want = hashlib.sha1(wav).hexdigest()[:12]
  if info.get("ref_sha1") == want and info.get("ref_text") == text:
    return "the server already has this machine's reference"

  try:
    r = _post("/ref", wav, "application/octet-stream")
    audio_ok = r.status == 200
    r.release_conn()
    r = _post("/reftext", json.dumps({"text": text}).encode("utf-8"),
              "application/json")
    text_ok = r.status == 200
    r.release_conn()
  except Exception as e:  # noqa: BLE001
    return (f"could not send the reference ({type(e).__name__}: {e}) — the "
            f"server's own reference will be used")

  if audio_ok and text_ok:
    return (f"reference sent: {REF_WAV.name} ({len(wav)} bytes) + "
            f"{len(text)} characters of transcript")
  return f"the server refused the reference (audio={audio_ok}, text={text_ok})"


def synthesize_pcm(text: str) -> bytes | None:
  cleaned = _clean_text(text)
  if not cleaned:
    return None

  # Cheap question first. Without it, a tunnel that has gone quiet costs the
  # full COLAB_TIMEOUT of silence before the reply falls back to a prebuilt
  # voice; with it, the fallback lands in about HEALTH_TIMEOUT. A live server
  # answers this instantly whatever the GPU is doing, so nothing is lost.
  alive, info = server_info()
  if not alive:
    print(f"[ColabTTS] no answer from {COLAB_URL} — {info.get('error')}")
    print("[ColabTTS] the Colab session has probably stopped; start the "
          "notebook and paste the new tunnel URL into voice/colab_tts.py")
    return None

  note = ensure_reference(info)
  if not note.startswith(("the server already", "server has no /ref")):
    print(f"[ColabTTS] {note}")

  try:
    resp = _speak_request(cleaned, COLAB_TIMEOUT)
    if resp.status != 200:
      print(f"[ColabTTS] HTTP {resp.status} from /speak: "
            f"{resp.data[:200].decode('utf-8', 'replace')!r}")
      resp.release_conn()
      return None

    # WAV မှ raw 16-bit mono 24kHz PCM ကို ထုတ်ယူခြင်း
    data = resp.data
    resp.release_conn()
    with wave.open(io.BytesIO(data), "rb") as w:
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

  # The same preflight a real reply runs, and for the same reason it exists: a
  # probe that let the server fall back to the model's own reference would come
  # back with perfectly good Burmese in the wrong voice and pass. The reference
  # is what makes it her.
  alive, info = server_info()
  if not alive:
    return False, f"no answer from GET / — {info.get('error')}"
  note = ensure_reference(info)
  if not note.startswith(("the server already", "server has no /ref")):
    print(f"[ColabTTS] {note}")
  alive, info = server_info()
  ref_sha = info.get("ref_sha1", "") if alive else ""

  # Every failure below carries how long it took, on purpose. It is the one
  # piece of evidence that separates the two halves of a failed /speak: a 500
  # that arrives in under a second never reached the checkpoint load, so it is
  # the reference WAV or the model install, and waiting longer will not help;
  # one that takes minutes got the model up and failed afterwards, which is a
  # different fault in a different place.
  try:
    resp = _speak_request(cleaned, timeout)
    if resp.status != 200:
      detail = resp.data[:200].decode("utf-8", "replace")
      status = resp.status
      resp.release_conn()
      if status in (520, 522, 523, 524):
        return False, (f"HTTP {status} after {time.time() - t0:.1f}s — Cloudflare "
                       f"cut the tunnel at about a hundred seconds with the server "
                       f"still working; the model is loading, and the next request "
                       f"will find it loaded: {detail.strip()!r}")
      return False, (f"HTTP {status} after {time.time() - t0:.1f}s: "
                     f"{detail!r}")
    data = resp.data
    resp.release_conn()
    with wave.open(io.BytesIO(data), "rb") as w:
      frames = w.getnframes()
      rate = w.getframerate()
      channels = w.getnchannels()
      width = w.getsampwidth() * 8
  except Exception as e:  # noqa: BLE001
    return False, f"{type(e).__name__} after {time.time() - t0:.1f}s: {e}"

  if not frames:
    return False, "answered, but with an empty WAV"

  # Which reference the server actually read, said out loud. "It returned audio"
  # is true of a clone and of the model's own sample voice alike.
  wav_local, _ = local_reference()
  mine = hashlib.sha1(wav_local).hexdigest()[:12] if wav_local else ""
  if not ref_sha:
    refpart = "reference: none on the server"
  elif mine and ref_sha == mine:
    refpart = f"reference: {ref_sha} (this machine's clip)"
  else:
    refpart = (f"reference: {ref_sha} — NOT this machine's clip "
               f"({mine or 'none here'})")

  seconds = frames / max(rate, 1)
  return True, (f"{seconds:.1f}s of audio — {rate} Hz, {channels} ch, {width}-bit, "
                f"returned in {time.time() - t0:.1f}s, {refpart}")


def describe() -> str:
  """One line naming the endpoint, for the check scripts."""
  return f"Colab F5-Myanmar-TTS → {COLAB_URL} (POST /speak, 16-bit mono 24 kHz)"
