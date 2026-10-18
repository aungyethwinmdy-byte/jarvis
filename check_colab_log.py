"""Read the Colab server's log over the tunnel.

The v2 notebook keeps the server's stdout in /content/server.log and serves it
as `GET /log`, which is the difference between "the server answered 500" and
knowing what raised. Before that the traceback went into a pipe nothing read,
and the only copy died with the runtime — an afternoon went into that today.

    py check_colab_log.py              last 40 lines
    py check_colab_log.py --lines 200

Also prints what the server says about itself, including the sha1 of the
reference clip it is holding: `[OK ] reference clip matches` means the server is
cloning from this machine's recording of ဒေါ်အေးသန့်, not from its own sample.
"""
import argparse
import hashlib
import json
import sys

from urllib3.util import Timeout

from voice import colab_tts as colab


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--lines", type=int, default=40,
                  help="how many lines of the log to print (default 40)")
  args = ap.parse_args()

  print("=" * 74)
  print("COLAB SERVER LOG")
  print("=" * 74)
  print(f"  {colab.describe()}")

  alive, info = colab.server_info()
  if not alive:
    print(f"  [--]  no answer — {info.get('error')}")
    print()
    print("  The Colab session has probably stopped. Start the notebook and")
    print("  paste its new trycloudflare URL into voice/colab_tts.py.")
    return 1

  print(f"  [OK]  {json.dumps(info, ensure_ascii=False)}")

  # The reference clip is the one thing about a working answer that can be
  # wrong without anything failing, so it is named here out loud.
  ref_sha = info.get("ref_sha1")
  if ref_sha is None:
    print("  [--]  the server has no /ref route — notebook older than v2")
  else:
    wav, text = colab.local_reference()
    mine = hashlib.sha1(wav).hexdigest()[:12] if wav else ""
    if not ref_sha:
      print("  [!!]  the server holds no reference clip — it will speak in its "
            "own sample voice")
    elif mine and ref_sha == mine:
      print(f"  [OK]  reference clip matches ({ref_sha})")
    else:
      print(f"  [!!]  the server's reference clip is {ref_sha}, not this "
            f"machine's ({mine or 'none here'})")

  if not info.get("model"):
    print("  [!!]  the server does not name a model — this is a v1 notebook, "
          "which cannot speak Burmese")
  else:
    print(f"  [OK]  model: {info['model']}")

  print()
  print(f"  --- /content/server.log, last {args.lines} lines ---")
  try:
    r = colab._POOL.request(
      "GET", colab.COLAB_URL.rstrip("/") + f"/log?n={args.lines}",
      timeout=Timeout(connect=colab.CONNECT_TIMEOUT, read=60),
      retries=False,
    )
    if r.status != 200:
      print(f"  [--]  GET /log answered {r.status}: "
            f"{r.data[:120].decode('utf-8', 'replace')}")
      r.release_conn()
      return 0
    body = json.loads(r.data.decode("utf-8", "replace"))
    r.release_conn()
    print(f"  ({body.get('lines', 0)} lines in the file)")
    for line in (body.get("tail") or "").splitlines():
      print(f"  | {line}")
  except Exception as e:  # noqa: BLE001
    print(f"  [--]  could not read the log: {type(e).__name__}: {e}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
