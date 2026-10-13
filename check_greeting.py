"""Check the JARVIS startup greeting before running the app.

    py check_greeting.py

Five sections:

  STATUS    whether the greeting is switched on at all, and where it comes from
  TIME      the Burmese date/time formatting, including the day-part boundaries
  WEATHER   a live fetch from Open-Meteo, plus the retry/cache/budget offline
  BUDGET    the greeting's wait against its own weather fetch's worst case —
            two constants in main.py that nothing else ties together
  BRIEFING  the real _send_startup_briefing(), run against a stub session, so
            the exact text JARVIS will speak is printed

The BRIEFING section matters most. Checking `import main` proves nothing about
it — the body only runs when the app connects, so a bad import or a bad guard
inside it passes an import test and then fails silently at startup. That is
precisely the shape of "the greeting doesn't come up", which has now happened
twice for two different reasons.
"""
import asyncio
import re
import sys
from datetime import datetime

sys.path.insert(0, r"E:\Mark-LIV-main")

from core import timefmt
from actions.weather_report import fetch_weather_brief, fetch_weather
from memory.config_manager import get_brief_enabled


def show_status() -> None:
    print("=" * 72)
    print("STATUS  (why the greeting might not appear at all)")
    print("=" * 72)
    enabled = get_brief_enabled()
    print(f"  morning_brief_enabled : {enabled}")
    if enabled:
        print("  -> the greeting will be spoken on connect")
    else:
        print("  -> *** NO GREETING WILL BE SPOKEN ***")
        print("     The greeting is gated behind this flag. It is also the")
        print("     MORNING BRIEF button in the UI, so switching the news off")
        print("     switches the greeting off with it.")
        print("     Fix: toggle MORNING BRIEF, or set the flag in")
        print("          config/api_keys.json")
    print("  (config file: config/api_keys.json)")


def show_time() -> None:
    now = timefmt.now_mmt()
    print("=" * 72)
    print("TIME")
    print("=" * 72)
    print("  machine now()   :", datetime.now())
    print("  MMT now         :", now, "| tz", now.tzinfo, "| offset", now.utcoffset())
    print("  month_day       :", timefmt.burmese_month_day(now))
    print("  burmese_date    :", timefmt.burmese_date(now))
    print("  burmese_clock   :", timefmt.burmese_clock(now))
    print("  describe        :", timefmt.describe())
    print("  machine_readable:", timefmt.machine_readable())

    print()
    print("CLOCK BOUNDARIES")
    for h in (0, 6, 11, 12, 13, 15, 16, 18, 19, 23):
        dt = now.replace(hour=h, minute=5)
        print(f"  {h:02d}:05 -> {timefmt.burmese_clock(dt)}")


def show_weather() -> None:
    print("=" * 72)
    print("WEATHER (live)")
    print("=" * 72)
    print("  brief        :", fetch_weather_brief("နေပြည်တော်"))
    print("  full         :", fetch_weather("နေပြည်တော်")[:200])
    print("  unknown city :", fetch_weather_brief("Zzzqqqnowhere"))
    print("  empty city   :", fetch_weather_brief(""))
    return show_weather_resilience()


def show_weather_resilience() -> int:
    """The retry, the cache and the budget — offline, by faking urlopen.

    These are the parts that only misbehave on a bad network day, which is
    exactly when nobody is watching the console. Measured 2026-09-26: the
    assistant said "ရာသီဥတု အချက်အလက် ယူလို့ မရပါ (TimeoutError)" for Naypyidaw
    while the same request succeeded 6/6 moments later in 1.6-3.3s. One stall
    had become a spoken apology, because nothing retried and nothing was
    cached.

    Returns the number of failed checks, so a regression here reaches RESULT
    and the exit code rather than only the console.
    """
    import time
    import urllib.error
    import urllib.request

    from actions import weather_report as w

    print()
    print("WEATHER RESILIENCE (offline)")
    print("-" * 72)

    # ── cache: the greeting and a question a minute later share one fetch ──
    w._CACHE.clear()
    t0 = time.time(); w.fetch_weather("Naypyidaw"); first = time.time() - t0
    t0 = time.time(); w.fetch_weather("နေပြည်တော်"); second = time.time() - t0
    t0 = time.time(); fetch_weather_brief("Nay Pyi Taw"); third = time.time() - t0
    ok_cache = second < 0.01 and third < 0.01 and len(w._CACHE) == 1
    print(f"  cache      : 1st {first:.2f}s, then {second:.3f}s / {third:.3f}s "
          f"for the same place spelled three ways -> {len(w._CACHE)} entry  "
          f"{'OK' if ok_cache else 'FAIL'}")
    print("               (one entry is the point: the key is the coordinates, "
          "not the spelling)")

    # ── retry: a transient failure must not reach the user ──
    real = urllib.request.urlopen
    calls = {"n": 0}

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("simulated connection reset")
        return real(req, timeout=timeout)

    w._CACHE.clear()
    urllib.request.urlopen = flaky
    try:
        t0 = time.time(); text = fetch_weather("Naypyidaw"); elapsed = time.time() - t0
    finally:
        urllib.request.urlopen = real
    ok_retry = calls["n"] == 2 and "ယူလို့ မရပါ" not in text
    print(f"  retry      : attempt 1 failed, attempt 2 succeeded in "
          f"{elapsed:.2f}s, {calls['n']} urlopen call(s)  "
          f"{'OK' if ok_retry else 'FAIL'}")

    # ── budget: a stall costs timeout + floor, it does not double ──
    # A full stall must not turn an 8s timeout into 16s of silence in front of
    # a spoken answer, so the retry gets the time left over with a floor.
    t0 = time.time()
    try:
        w._get_json("http://192.0.2.1/", timeout=2.0)   # TEST-NET-1, unroutable
        elapsed, ok_budget = time.time() - t0, False
    except Exception:
        elapsed = time.time() - t0
        ok_budget = 4.5 <= elapsed <= 6.5
    print(f"  budget     : 2.0s timeout + full stall -> gave up after "
          f"{elapsed:.2f}s (expect ~5.4s, not ~8s)  "
          f"{'OK' if ok_budget else 'FAIL'}")
    print("               worst case = timeout + 3.0 floor + 0.4 delay, so "
          "fetch_weather(8.0) tops out near 11s")
    return sum(1 for ok in (ok_cache, ok_retry, ok_budget) if not ok)


def show_greeting_budget() -> int:
    """The greeting's wait must outlast its own weather fetch's worst case.

    Two numbers in main.py have to agree and nothing in the code makes them:

        _WEATHER_ATTEMPT  passed to fetch_weather_brief()
        _WEATHER_WAIT     how long asyncio.wait_for waits for the answer

    fetch_weather_brief()'s internal retry takes its second attempt out of what
    is left of that timeout, floored at _RETRY_MIN_SLICE — so the function costs
    up to `attempt + _RETRY_MIN_SLICE + _RETRY_DELAY` before it gives up. If the
    greeting waits only `attempt`, the retry can NEVER land.

    Measured 2026-09-27 the pair was 5.0 / 5.0: the greeting gave up at 5.0s and
    the executor thread ran on to 8.4s with an answer nobody would read. The
    console showed it plainly — "Startup weather unavailable" printed BEFORE the
    retry it was waiting for had even started.

    This does not compare the two constants; it runs the stall and times it, so
    the check fails on the behaviour rather than on the arithmetic.

    Returns the number of failed checks.
    """
    import time

    from actions import weather_report as w

    print()
    print("GREETING BUDGET (offline)")
    print("-" * 72)

    try:
        from main import _WEATHER_ATTEMPT, _WEATHER_WAIT
    except Exception as e:
        print(f"  budget     : cannot read the constants from main.py "
              f"({type(e).__name__}: {e})  FAIL")
        return 1

    t0 = time.time()
    try:
        w._get_json("http://192.0.2.1/", timeout=_WEATHER_ATTEMPT)  # unroutable
        elapsed, stalled = time.time() - t0, False
    except Exception:
        elapsed, stalled = time.time() - t0, True

    margin = _WEATHER_WAIT - elapsed
    ok = stalled and margin > 0
    print(f"  budget     : greeting's own fetch, {_WEATHER_ATTEMPT}s timeout, "
          f"full stall -> gave up after {elapsed:.2f}s; greeting waits "
          f"{_WEATHER_WAIT}s -> {margin:+.2f}s margin  {'OK' if ok else 'FAIL'}")

    floor = _WEATHER_ATTEMPT + w._RETRY_MIN_SLICE + w._RETRY_DELAY
    print(f"               worst case = _WEATHER_ATTEMPT + _RETRY_MIN_SLICE "
          f"({w._RETRY_MIN_SLICE}) + _RETRY_DELAY ({w._RETRY_DELAY}) = "
          f"{floor:.1f}s; the wait must exceed it or the retry never lands")
    if not ok:
        print("               *** on a stall the greeting drops the weather "
              "and the retry's answer is discarded ***")
    return 0 if ok else 1


class _FakeSession:
    def __init__(self):
        self.sent = []

    async def send_client_content(self, turns=None, turn_complete=None):
        self.sent.append(turns["parts"][0]["text"])


class _FakeUI:
    muted = False

    def write_log(self, message):
        print(f"    [UI] {message}")

    def set_state(self, state):
        pass

    def show_content(self, label, body):
        print(f"    [UI content] {label}")


async def _run_briefing() -> list[str]:
    from main import JarvisLive

    jl = JarvisLive.__new__(JarvisLive)   # skip __init__: it wires up Qt
    jl.ui = _FakeUI()
    jl.session = _FakeSession()
    jl._asst_name = "JARVIS"
    jl._turn_done_event = None
    jl._session_log = []
    await jl._send_startup_briefing()
    return jl.session.sent


def show_briefing() -> int:
    print("=" * 72)
    print("BRIEFING  (the real function, run against a stub session)")
    print("=" * 72)
    sent = asyncio.run(_run_briefing())

    if not sent:
        print("  *** NOTHING WAS SENT — the greeting is broken ***")
        return 1

    print(f"  messages sent: {len(sent)}")
    print()
    for i, text in enumerate(sent, 1):
        print(f"--- message {i} ---")
        print(text)
        print()

    body = sent[0]
    checks = [
        ("says mingalaba",       "မင်္ဂလာပါ" in body),
        ("addresses the user",   "ကိုသွင်" in body),
        ("names the assistant",  "JARVIS" in body),
        ("asks what to do",      "ဆောင်ရွက်ပေးရမလဲ" in body),
        ("gives the date",       "ရက်နေ့" in body),
        ("gives the time",       "မြန်မာစံတော်ချိန်" in body),
        ("gives the weather",    "ရာသီဥတု" in body),
        ("read-verbatim order",  "မပြောင်းပါနှင့်" in body),
        ("no tool call",         "Tool မခေါ်ပါနှင့်" in body),
        ("no ascii digits",      not re.search(r"[0-9]", body)),
    ]
    print("  CONTENT")
    failed = 0
    for label, ok in checks:
        print(f"    {'OK  ' if ok else 'FAIL'}  {label}")
        failed += 0 if ok else 1
    return failed


if __name__ == "__main__":
    show_status()
    show_time()
    failed  = show_weather()
    failed += show_greeting_budget()
    failed += show_briefing()
    print()
    print("RESULT:", "ALL OK" if not failed else f"{failed} CHECK(S) FAILED")
    sys.exit(1 if failed else 0)
