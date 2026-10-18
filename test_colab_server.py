"""Run the notebook's server code here, against a stub model.

The server JARVIS talks to only exists inside Colab, where testing it costs a
model download and minutes of silence, and where a mistake arrives as a client
timeout with the traceback on the far side of a tunnel. The code is a string in
cell 4, so it can be extracted and run on this machine in a second.

What this checks is the contract, not the model: which reference /speak hands
over and when it insists on having both halves of the pair, what /ref and
/reftext accept and refuse, and what the health route promises the client.
f5_myanmar_tts is replaced by a stub that records what it was asked to say —
it is the one part that cannot run here.

    py test_colab_server.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import tempfile
import types
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
CELL = HERE / "voice" / "notebook_src" / "c4.py"

FAILED: list[str] = []
CALLS: list[dict] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
  mark = "[OK ]" if ok else "[FAIL]"
  print(f"  {mark} {label}" + (f" — {detail}" if detail else ""))
  if not ok:
    FAILED.append(label)
  return ok


def wav_bytes(seconds: float = 0.25, rate: int = 24000) -> bytes:
  buf = io.BytesIO()
  with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(b"\x00\x00" * int(rate * seconds))
  return buf.getvalue()


class StubMyanmarTTS:
  """Records what the server asked for instead of speaking."""

  def __init__(self, *a, **kw):
    self.device = "cuda: stub"

  def speak(self, text, output_file=None, ref_audio=None, ref_text=None, **kw):
    CALLS.append({"text": text, "ref_audio": ref_audio, "ref_text": ref_text})
    with open(output_file, "wb") as f:
      f.write(wav_bytes())


def load_server(tmp: Path):
  src = CELL.read_text(encoding="utf-8")
  m = re.search(r"SERVER_CODE = r'''(.*?)'''", src, re.S)
  if not m:
    raise SystemExit("cell 4 no longer contains an r'''SERVER_CODE''' block")
  # Forward slashes: these paths land inside plain ("") Python strings in the
  # server code, where a Windows path's \U is read as a unicode escape. Colab
  # has no backslashes anywhere, so this only ever matters here.
  t = str(tmp).replace("\\", "/")
  code = (m.group(1)
          .replace("__REF_WAV__", f"{t}/ref.wav")
          .replace("__REF_TEXT_FILE__", f"{t}/ref_text.txt")
          .replace("__OUT_WAV__", f"{t}/_out.wav")
          .replace("__LOG_PATH__", f"{t}/server.log")
          .replace("__EXPOSE_LOG__", "True"))

  stub = types.ModuleType("f5_myanmar_tts")
  stub.MyanmarTTS = StubMyanmarTTS
  sys.modules["f5_myanmar_tts"] = stub

  globals_: dict = {"__name__": "tts_server_under_test"}
  exec(compile(code, "tts_server.py", "exec"), globals_)
  return globals_["app"]


def named_wav(data: bytes) -> str:
  try:
    with wave.open(io.BytesIO(data), "rb") as w:
      return (f"{w.getframerate()} Hz, {w.getnchannels()} ch, "
              f"{w.getsampwidth() * 8} bit, "
              f"{w.getnframes() / max(w.getframerate(), 1):.2f}s")
  except Exception as e:  # noqa: BLE001
    return f"not a WAV ({type(e).__name__})"


def main() -> int:
  try:
    import flask  # noqa: F401
    import flask_cors  # noqa: F401
  except ImportError as e:
    print(f"  [SKIP] flask/flask-cors are not installed here ({e})")
    return 0

  tmp = Path(tempfile.mkdtemp(prefix="colab_server_test_"))
  app = load_server(tmp)
  c = app.test_client()

  print("=" * 74)
  print("COLAB SERVER CODE  (cell 4, run here with a stub model)")
  print("=" * 74)
  print(f"  from {CELL}")
  print(f"  temp {tmp}")
  print()

  r = c.get("/")
  info = json.loads(r.data)
  check("GET / answers", r.status_code == 200)
  check("GET / names a Burmese model", "f5" in info.get("model", ""),
        str(info.get("model")))
  check("GET / reports a device", bool(info.get("device")),
        str(info.get("device")))
  check("GET / starts with no reference clip", info.get("ref") is False)
  check("GET / starts with no transcript", info.get("ref_text") == "")
  check("GET / starts with no clip sha1", info.get("ref_sha1") == "")

  r = c.post("/speak", json={"text": "မင်္ဂလာပါ"})
  check("POST /speak answers 200", r.status_code == 200)
  check("POST /speak returns 24 kHz mono 16-bit", named_wav(r.data),
        named_wav(r.data))
  check("with no pair, the model's own reference is used",
        CALLS[-1]["ref_audio"] is None and CALLS[-1]["ref_text"] is None)

  r = c.post("/speak", json={"text": "   "})
  check("POST /speak refuses empty text", r.status_code == 400)

  r = c.post("/ref", data=b"too short to be a recording")
  check("POST /ref refuses a body too small to be a clip", r.status_code == 400)

  clip = wav_bytes(1.0)
  r = c.post("/ref", data=clip)
  check("POST /ref accepts a clip", r.status_code == 200)
  r = c.post("/reftext", json={"text": "ဟိုဟာ ဈေးဝယ်ဝယ်ရမှာလား"})
  check("POST /reftext accepts a transcript", r.status_code == 200)
  r = c.post("/reftext", json={"text": "  "})
  check("POST /reftext refuses an empty transcript", r.status_code == 400)

  info = json.loads(c.get("/").data)
  check("GET / reports the clip it holds",
        info.get("ref_sha1") == hashlib.sha1(clip).hexdigest()[:12],
        str(info.get("ref_sha1")))
  check("GET / reports the transcript",
        info.get("ref_text") == "ဟိုဟာ ဈေးဝယ်ဝယ်ရမှာလား")
  check("GET /ref returns the clip byte for byte", c.get("/ref").data == clip)

  CALLS.clear()
  r = c.post("/speak", json={"text": "မင်္ဂလာပါ ကိုသွင်"})
  check("POST /speak answers 200 with a pair in place", r.status_code == 200)
  check("... and hands over both halves of the pair",
        CALLS[-1]["ref_audio"] == (str(tmp).replace("\\", "/") + "/ref.wav")
        and CALLS[-1]["ref_text"] == "ဟိုဟာ ဈေးဝယ်ဝယ်ရမှာလား")

  # Half a pair is worse than no pair: the transcript of a different recording
  # still produces fluent Burmese, in the wrong rhythm, saying words nobody
  # said. The server must not use a clip it has no words for.
  (tmp / "ref_text.txt").unlink()
  CALLS.clear()
  r = c.post("/speak", json={"text": "မင်္ဂလာပါ"})
  check("a clip whose transcript is gone is not used as a reference",
        CALLS[-1]["ref_audio"] is None)

  (tmp / "server.log").write_text("first line\n[speak] 3 chars -> wav\n",
                                  encoding="utf-8")
  body = json.loads(c.get("/log?n=5").data)
  check("GET /log returns the tail of the log", "[speak]" in body.get("tail", ""))

  r = c.post("/warm")
  check("POST /warm loads the model", r.status_code == 200
        and bool(json.loads(r.data).get("device")),
        str(json.loads(r.data)))

  print()
  if FAILED:
    print(f"{len(FAILED)} failed: " + "; ".join(FAILED))
    return 1
  print("the server contract holds")
  return 0


if __name__ == "__main__":
  sys.exit(main())
