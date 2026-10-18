# Cell 4: Server + tunnel — JARVIS က ဒီ URL ကို ခေါ်သုံးပါမယ်
import os, re, subprocess, sys, time, urllib.request

# အရင် run ထားတဲ့ server/tunnel ရှိရင် အရင်ပိတ် (Run all ကို နှစ်ခါ run ရင်
# port 5000 မလွတ်လို့ ဒုတိယ server က မတက်နိုင်ပါ)
subprocess.run("pkill -f tts_server.py", shell=True)
subprocess.run("pkill -f cloudflared", shell=True)
time.sleep(1)

SERVER_CODE = r'''
import hashlib
import os
import time

from flask import Flask, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

REF_WAV       = """__REF_WAV__"""
REF_TEXT_FILE = """__REF_TEXT_FILE__"""
OUT_WAV       = """__OUT_WAV__"""
LOG_PATH      = """__LOG_PATH__"""
EXPOSE_LOG    = __EXPOSE_LOG__


# ---- the model: lazy, because the first /speak pays the download ------------
_tts = None


def get_tts():
    global _tts
    if _tts is None:
        from f5_myanmar_tts import MyanmarTTS
        _tts = MyanmarTTS()
    return _tts


_device_cache = {}


def _device():
    """Which device the model will speak on: seconds a line, or minutes a line.

    Measured 2026-10-18 on a CPU-only runtime: 741.7 seconds for 24 characters,
    against a cloudflare tunnel that cuts requests at about a hundred. The
    difference is not a matter of degree, it is usable against unusable, so the
    health route says it rather than leaving it to be inferred from timings.
    """
    if _tts is not None:
        return str(getattr(_tts, "device", "?"))
    if "value" not in _device_cache:
        try:
            import torch
            _device_cache["value"] = ("cuda: " + torch.cuda.get_device_name(0)
                                      if torch.cuda.is_available() else "cpu")
        except Exception as e:  # noqa: BLE001
            _device_cache["value"] = f"unknown ({type(e).__name__})"
    return _device_cache["value"]


def _ref_text():
    if os.path.exists(REF_TEXT_FILE):
        try:
            t = open(REF_TEXT_FILE, encoding="utf-8").read().strip()
            if t:
                return t
        except OSError:
            pass
    return ""


def _ref_state():
    """What the reference is right now, so the client can keep it in sync.

    The clip and its transcript are a pair: the transcript of one recording
    spoken over a different recording makes F5 produce fluent Burmese nonsense,
    which no error message would say. So the client compares the clip it has
    with the one here (sha1) and puts both back when they differ.
    """
    has_wav = os.path.exists(REF_WAV)
    digest = ""
    if has_wav:
        with open(REF_WAV, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()[:12]
    return dict(ref=has_wav, ref_text=_ref_text(), ref_sha1=digest)


@app.route("/speak", methods=["POST"])
def speak():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return {"error": "empty text"}, 400

    t0 = time.time()
    tts = get_tts()
    ref_text = _ref_text()
    if os.path.exists(REF_WAV) and ref_text:
        tts.speak(text, output_file=OUT_WAV, ref_audio=REF_WAV, ref_text=ref_text)
        used = "cloned reference"
    else:
        # No reference from the client yet: the library's own sample and its own
        # transcript are a matched pair, so the words still come out Burmese —
        # just not in her voice.
        tts.speak(text, output_file=OUT_WAV)
        used = "model's own reference"

    print(f"[speak] {len(text)} chars -> {os.path.getsize(OUT_WAV)} bytes "
          f"in {time.time() - t0:.1f}s ({used}, {_device()})", flush=True)
    return send_file(OUT_WAV, mimetype="audio/wav")


@app.route("/ref", methods=["GET", "POST"])
def ref():
    if request.method == "GET":
        if not os.path.exists(REF_WAV):
            return {"error": "no reference audio on the server yet"}, 404
        return send_file(REF_WAV, mimetype="audio/wav")

    body = request.get_data()
    if len(body) < 4000:
        return {"error": f"too small to be a reference clip ({len(body)} bytes)"}, 400
    with open(REF_WAV, "wb") as f:
        f.write(body)
    print(f"[ref] reference audio replaced: {len(body)} bytes", flush=True)
    return dict(status="ok", bytes=len(body))


@app.route("/reftext", methods=["GET", "POST"])
def reftext():
    if request.method == "GET":
        return {"text": _ref_text()}

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return {"error": "empty text"}, 400
    with open(REF_TEXT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[reftext] reference transcript set ({len(text)} chars)", flush=True)
    return {"status": "ok", "text": text}


@app.route("/log", methods=["GET"])
def log():
    if not EXPOSE_LOG:
        return {"error": "logging is off (EXPOSE_LOG = False in cell 3)"}, 403
    try:
        n = max(1, min(400, int(request.args.get("n", "40"))))
    except (TypeError, ValueError):
        n = 40
    if not os.path.exists(LOG_PATH):
        return {"error": f"{LOG_PATH} does not exist"}, 404
    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return {"lines": len(lines), "tail": "".join(lines[-n:])}


@app.route("/warm", methods=["GET", "POST"])
def warm():
    """Load the model with no tunnel in the way.

    The notebook calls this over localhost before it starts the tunnel, because
    a Cloudflare quick tunnel cuts any request that takes longer than about a
    hundred seconds and the first load of this model is minutes. It is a
    convenience, not a dependency: /speak loads the model itself too.
    """
    t0 = time.time()
    get_tts()
    elapsed = time.time() - t0
    print(f"[warm] model ready in {elapsed:.1f}s on {_device()}", flush=True)
    return {"status": "ok", "seconds": round(elapsed, 1), "device": _device()}


@app.route("/", methods=["GET"])
def health():
    return dict(status="ok", service="f5-myanmar-tts",
                model="f5-myanmar-tts v2 (Burmese, 24 kHz)",
                device=_device(), **_ref_state())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
'''

code = (SERVER_CODE
        .replace("__REF_WAV__", REF_WAV_PATH)
        .replace("__REF_TEXT_FILE__", REF_TEXT_FILE)
        .replace("__OUT_WAV__", "/content/_speak_out.wav")
        .replace("__LOG_PATH__", "/content/server.log")
        .replace("__EXPOSE_LOG__", "True" if EXPOSE_LOG else "False"))
with open("/content/tts_server.py", "w", encoding="utf-8") as f:
    f.write(code)
print("server code written -> /content/tts_server.py")

# Start the server with its output going to a LOG FILE rather than a pipe.
# v1 piped it and nothing ever read the pipe, so every traceback vanished into a
# buffer — that is where an afternoon went. A file can be read at any time, by
# cell (5) or by JARVIS over GET /log.
srv_log = open("/content/server.log", "w", encoding="utf-8")
srv = subprocess.Popen([sys.executable, "/content/tts_server.py"],
                       stdout=srv_log, stderr=subprocess.STDOUT, text=True)
time.sleep(5)
print("server started, pid:", srv.pid)

# Load the model BEFORE the tunnel exists. A Cloudflare quick tunnel cuts any
# request longer than about a hundred seconds, and the first load of this model
# is minutes — so through the tunnel the first /speak can never finish: JARVIS
# would get a 524 and speak the session's first reply in another voice. Called
# from here, over localhost, there is no cut at all, and the URL below is not
# printed until the model is up.
print("model ကို အရင် load လုပ်ပါမယ် — ပထမဆုံးဆိုရင် 674 MB download လို့ မိနစ်အနည်းငယ် ကြာပါမယ်...")
try:
    with urllib.request.urlopen("http://127.0.0.1:5000/warm", timeout=3600) as r:
        print("  ", r.read().decode("utf-8", "replace")[:200])
except Exception as e:
    print(f"  warm မအောင်မြင်ပါ: {type(e).__name__}: {e}")
    print("  (cell (5) က log ကို ကြည့်ပါ — /speak ပထမဆုံးခေါ်ချိန်မှာ ထပ်ကြိုးစားပါမယ်)")

# Tunnel
tun = subprocess.Popen(["/tmp/cloudflared", "tunnel", "--url", "http://127.0.0.1:5000"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
url = None
for _ in range(60):
    line = tun.stdout.readline()
    if not line:
        time.sleep(1)
        continue
    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
    if m:
        url = m.group(0)
        break

print()
if url:
    print("=" * 62)
    print("✅ ဒီ URL ကို JARVIS ဘက်က voice/colab_tts.py → COLAB_URL မှာ ထည့်ပါ")
    print()
    print("   " + url)
    print()
    print("=" * 62)
else:
    print("❌ tunnel URL မရပါ — /content/server.log ကို ကြည့်ပါ")
    for _ in range(20):
        l = tun.stdout.readline()
        if not l:
            break
        print(l, end="")
