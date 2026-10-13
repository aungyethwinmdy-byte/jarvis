# test_web_scraper.py - self-test for the WebScraper SSL/DPI fix (curl_cffi rung)
#
# Usage:
#   py test_web_scraper.py           # quick: syntax + ladder + live fetch (no browser)
#   py test_web_scraper.py --full    # also exercises the irrawaddy graceful-failure
#                                    # chain (launches Chrome as last rung)
#
# Exit code 0 = all checks passed.

import sys
import time
import importlib.util
import py_compile

sys.stdout.reconfigure(encoding="utf-8")

SRC = "actions/web_scraper.py"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


# 1) syntax compiles
try:
    py_compile.compile(SRC, doraise=True)
    check("py_compile syntax", True)
except Exception as e:
    check("py_compile syntax", False, str(e)[:120])

# 2) regression guard: exactly one of each def + one TOOL dict (the
#    duplicate-handler bug and the duplicate-dict bug)
src = open(SRC, encoding="utf-8").read()
for fn in ("TOOL = {", "def web_scraper(", "def _fetch_local(", "def _fetch_curl_cffi("):
    n = src.count(fn)
    label = fn[:-2] if fn.endswith(" = {") else fn
    check(f"single '{label}'", n == 1, f"count={n}")

# load the module fresh from source
spec = importlib.util.spec_from_file_location("ws", SRC)
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)

# 3) direct curl_cffi fetch (the new rung, isolated)
t0 = time.time()
try:
    html = ws._fetch_curl_cffi("https://www.google.com/")
    check("curl_cffi direct fetch (google)",
          len(html) > 50000,
          f"{len(html)} bytes in {time.time() - t0:.1f}s")
except Exception as e:
    check("curl_cffi direct fetch (google)",
          False, f"{type(e).__name__}: {str(e)[:100]}")

# 4) full handler end-to-end
t0 = time.time()
try:
    out = ws.web_scraper({"url": "https://www.bbc.com/burmese"})
    check("handler E2E (BBC Burmese)",
          isinstance(out, str) and out.startswith("[PAGE READ]") and len(out) > 1000,
          f"{len(out)} chars in {time.time() - t0:.1f}s")
except Exception as e:
    check("handler E2E (BBC Burmese)",
          False, f"{type(e).__name__}: {str(e)[:100]}")

# 5) forced-DPI simulation: urllib AND requests die -> ladder must land on
#    curl_cffi and still fetch successfully
import urllib.request
import requests

real_urlopen, real_get = urllib.request.urlopen, requests.get


def _boom(*a, **k):
    raise OSError("SIMULATED ISP DPI RESET (SSL: UNEXPECTED_EOF_WHILE_READING)")


try:
    urllib.request.urlopen = _boom
    requests.get = _boom
    md, note = ws._fetch_local("https://www.bbc.com/burmese")
    check("forced-DPI ladder lands on curl_cffi",
          len(md) > 1000 and "local" in note,
          f"note={note[:60]!r}, {len(md)} chars")
except Exception as e:
    check("forced-DPI ladder lands on curl_cffi",
          False, f"{type(e).__name__}: {str(e)[:100]}")
finally:
    urllib.request.urlopen = real_urlopen
    requests.get = real_get

# 6) optional: graceful-failure chain on dead-DNS host (includes Chrome rung)
if "--full" in sys.argv:
    out = ws.web_scraper({"url": "https://burmese.irrawaddy.com/"})
    check("irrawaddy graceful chain (dead DNS)",
          isinstance(out, str) and len(out) > 0,
          out[:80].replace("\n", " "))

npass = sum(1 for ok in results if ok)
print(f"\n{npass}/{len(results)} checks passed"
      + ("  - ALL GOOD" if npass == len(results) else "  - see FAIL lines above"))
sys.exit(0 if npass == len(results) else 1)
