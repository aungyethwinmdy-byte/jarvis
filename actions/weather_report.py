"""Current weather, as text the assistant can say out loud.

WHAT CHANGED AND WHY
    This used to open a Google search in the browser and return "Showing the
    weather for {city}, sir." The model never learned what the weather was, so
    it could not answer the question — it could only announce that a browser
    tab had appeared. Asked to open a conversation with the weather in
    Naypyidaw, that is useless: the greeting has to contain the weather, not a
    promise to display it.

    So the data is fetched and returned as a sentence. The browser is no longer
    opened, because answering and opening a tab are not the same act and doing
    both on every question is intrusive.

SOURCE
    Open-Meteo: no API key, no account, no quota to exhaust. Free geocoding
    comes from the same project, so a city the local table does not know is
    still resolvable.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from core.timefmt import to_burmese_digits

_FORECAST = "https://api.open-meteo.com/v1/forecast"
_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"

# Open-Meteo stalls occasionally rather than failing — measured 2026-09-26, the
# assistant told the user "နေပြည်တော် ရဲ့ ရာသီဥတု အချက်အလက် ယူလို့ မရပါ
# (TimeoutError)။" while the same request succeeded six times out of six
# moments later, in 1.6-3.3s. A single stall should not become a spoken
# apology, so every request is retried once on a fresh connection: a stall is
# almost always the connection, not the service.
#
# `timeout` stays the budget for the *whole* call, not per attempt — otherwise
# an 8s timeout would silently become 16s of silence in front of a spoken
# answer. The first attempt may use the whole budget; the retry gets whatever
# is left, with a floor so a fast failure (connection refused in 0.1s) still
# leaves a usable second try.
_RETRY_ATTEMPTS  = 2
_RETRY_MIN_SLICE = 3.0
_RETRY_DELAY     = 0.4

# Weather does not change inside five minutes, and both the startup greeting and
# any question asked soon after ask for the same city. Caching the parsed
# response means the second call costs nothing and cannot fail — which matters
# more than the latency: the greeting is the first thing the user hears.
_CACHE_TTL = 300.0
_CACHE: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, produce):
    """`produce()` once per key per _CACHE_TTL. Failures are never cached."""
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    value = produce()
    _CACHE[key] = (time.time(), value)
    return value


def _get_json(url: str, timeout: float) -> dict:
    """GET and parse, retrying once on anything transient.

    Retries transport failures and malformed JSON only. A 4xx would fail
    identically the second time, and retrying it would spend the budget to
    arrive at the same answer.
    """
    deadline = time.monotonic() + timeout
    last: Exception | None = None

    for attempt in range(_RETRY_ATTEMPTS):
        left = deadline - time.monotonic()
        budget = timeout if attempt == 0 else max(_RETRY_MIN_SLICE, left)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mark-LIV/JARVIS"})
            with urllib.request.urlopen(req, timeout=budget) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as e:
            # OSError covers TimeoutError, URLError, ConnectionError and a
            # refused/reset connection; ValueError covers json.JSONDecodeError.
            last = e
            if attempt + 1 < _RETRY_ATTEMPTS:
                print(f"[Weather] ⚠️ {type(e).__name__} — retrying once")
                time.sleep(_RETRY_DELAY)
    raise last if last else RuntimeError("request failed")

# Places asked for by name often enough to be worth not depending on a network
# round trip for. The greeting asks for Naypyidaw on every single start, and a
# greeting that stalls behind a geocoder is worse than one that knows the
# coordinates.
KNOWN_CITIES: dict[str, tuple[float, float, str]] = {
    "naypyidaw":  (19.7633, 96.0785, "နေပြည်တော်"),
    "nay pyi taw": (19.7633, 96.0785, "နေပြည်တော်"),
    "နေပြည်တော်":  (19.7633, 96.0785, "နေပြည်တော်"),
    "yangon":     (16.8661, 96.1951, "ရန်ကုန်"),
    "rangoon":    (16.8661, 96.1951, "ရန်ကုန်"),
    "ရန်ကုန်":     (16.8661, 96.1951, "ရန်ကုန်"),
    "mandalay":   (21.9588, 96.0891, "မန္တလေး"),
    "မန္တလေး":     (21.9588, 96.0891, "မန္တလေး"),
    "naypyitaw":  (19.7633, 96.0785, "နေပြည်တော်"),
}

# WMO weather codes, as Open-Meteo reports them.
_WMO: dict[int, str] = {
    0: "သာယာပြီး ကောင်းကင် ရှင်းနေသည်",
    1: "အများအားဖြင့် ရှင်းနေသည်",
    2: "တစ်ပိုင်းတစ်စ တိမ်ဖုံးနေသည်",
    3: "မိုးအုံ့နေသည်",
    45: "မြူဆိုင်းနေသည်",
    48: "မြူဆိုင်းပြီး နှင်းခဲကျနေသည်",
    51: "အလင်းရောင် လေပြေကျနေသည်",
    53: "လေပြေကျနေသည်",
    55: "လေပြေ သည်းသည်းကျနေသည်",
    56: "အေးခဲနေသော လေပြေ",
    57: "အေးခဲနေသော လေပြေ သည်းသည်း",
    61: "အလင်းရောင် မိုးရွာနေသည်",
    63: "မိုးအသင့်အတင့် ရွာနေသည်",
    65: "မိုးသည်းသည်း ရွာနေသည်",
    66: "အေးခဲနေသော မိုး",
    67: "အေးခဲနေသော မိုး သည်းသည်း",
    71: "အလင်းရောင် နှင်းကျနေသည်",
    73: "နှင်းအသင့်အတင့် ကျနေသည်",
    75: "နှင်းသည်းသည်း ကျနေသည်",
    77: "နှင်းခဲစေ့များ ကျနေသည်",
    80: "အလင်းရောင် မိုးရွာချနေသည်",
    81: "မိုးအသင့်အတင့် ရွာချနေသည်",
    82: "မိုးသည်းသည်း ရွာချနေသည်",
    85: "အလင်းရောင် နှင်းကျချနေသည်",
    86: "နှင်းသည်းသည်း ကျချနေသည်",
    95: "မိုးကြိုးမုန်တိုင်း ဖြစ်နိုင်သည်",
    96: "မိုးကြိုးမုန်တိုင်း မိုးသီးနှင့်အတူ",
    99: "မိုးကြိုးမုန်တိုင်း မိုးသီးသည်းသည်းနှင့်အတူ",
}


def _resolve(city: str, timeout: float) -> tuple[float, float, str] | None:
    """Coordinates and a display name for a city, or None."""
    key = city.strip().lower()
    if key in KNOWN_CITIES:
        return KNOWN_CITIES[key]

    query = urllib.parse.urlencode({"name": city, "count": 1, "language": "en"})
    try:
        data = _cached(("geocode", key),
                       lambda: _get_json(f"{_GEOCODE}?{query}", timeout))
    except Exception:
        return None
    results = data.get("results") or []
    if not results:
        return None
    top = results[0]
    return (float(top["latitude"]), float(top["longitude"]),
            top.get("name") or city)


class _WeatherError(Exception):
    """Internal only. The message is already a Burmese sentence fit to speak."""


def _observe(city: str, when: str, timeout: float):
    """Resolve and fetch. Returns (label, current, daily, day_index).

    Raises _WeatherError carrying a speakable sentence. The public functions
    catch it, so nothing that calls into this module ever sees an exception.
    """
    city = (city or "").strip()
    if not city:
        raise _WeatherError("ရာသီဥတု မေးရင် မြို့နာမည် လိုပါတယ်။")

    try:
        place = _resolve(city, timeout)
    except Exception as e:
        raise _WeatherError(
            f"{city} ရဲ့ တည်နေရာ ရှာလို့ မရပါ ({type(e).__name__})။") from e
    if place is None:
        raise _WeatherError(f"'{city}' ဆိုတဲ့ မြို့ကို ရှာမတွေ့ပါ။")

    lat, lon, label = place
    query = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,weather_code",
        "timezone": "Asia/Yangon",
        "forecast_days": 2,
    })

    try:
        # Cached on the coordinates, not the city name: "Naypyidaw",
        # "နေပြည်တော်" and "Nay Pyi Taw" all resolve to the same place, and the
        # greeting and a question asked a minute later should share one fetch.
        data = _cached(("forecast", round(lat, 3), round(lon, 3)),
                       lambda: _get_json(f"{_FORECAST}?{query}", timeout))
    except Exception as e:
        raise _WeatherError(
            f"{label} ရဲ့ ရာသီဥတု အချက်အလက် ယူလို့ မရပါ "
            f"({type(e).__name__})။") from e

    cur   = data.get("current") or {}
    daily = data.get("daily") or {}
    if not cur:
        raise _WeatherError(f"{label} ရဲ့ ရာသီဥတု အချက်အလက် မရပါ။")

    day  = 0 if "tomorrow" not in (when or "").lower() else 1
    days = daily.get("time") or []
    if day >= len(days):
        day = 0

    return label, cur, daily, day


def _day_value(daily: dict, key: str, idx: int):
    values = daily.get(key) or []
    return values[idx] if idx < len(values) else None


def fetch_weather_brief(city: str, timeout: float = 5.0) -> str:
    """One short phrase: the condition and the temperature.

    Used by the opening greeting, where the full report would be a paragraph
    dropped into the middle of a sentence. Says only what a person would say
    when asked how it looks outside.
    """
    try:
        label, cur, daily, day = _observe(city, "today", timeout)
    except _WeatherError as e:
        return str(e)

    condition = _WMO.get(cur.get("weather_code"), "အခြေအနေ မသိပါ")
    temp      = cur.get("temperature_2m")
    rain      = _day_value(daily, "precipitation_probability_max", day)

    parts = [condition]
    if temp is not None:
        # Spelled out rather than "°C", and in Burmese numerals to match the
        # rest of the sentence: this string is read aloud, and a bare "33" in
        # Burmese text invites the synthesiser to read it as English.
        parts.append(f"အပူချိန် {to_burmese_digits(round(temp))} ဒီဂရီစင်တီဂရိတ်")
    if rain is not None and rain >= 60:
        parts.append(f"မိုးရွာနိုင်ခြေ {to_burmese_digits(round(rain))} ရာခိုင်နှုန်း")
    return "၊ ".join(parts)


def fetch_weather(city: str, when: str = "today", timeout: float = 8.0) -> str:
    """A weather summary in Burmese, ready to be spoken. Never raises.

    On failure it returns a sentence saying so, because the caller is a voice
    assistant mid-sentence: an exception here would either drop the greeting or
    surface as silence, and both are worse than "couldn't reach the weather
    service".
    """
    try:
        label, cur, daily, day = _observe(city, when, timeout)
    except _WeatherError as e:
        return str(e)

    def _d(key, idx=day):
        return _day_value(daily, key, idx)

    temp      = cur.get("temperature_2m")
    feels     = cur.get("apparent_temperature")
    humidity  = cur.get("relative_humidity_2m")
    wind      = cur.get("wind_speed_10m")
    condition = _WMO.get(cur.get("weather_code"), "အခြေအနေ မသိပါ")
    hi, lo    = _d("temperature_2m_max"), _d("temperature_2m_min")
    rain      = _d("precipitation_probability_max")
    day_code  = _d("weather_code")

    parts = [f"{label} — အခုအချိန် {condition}။"]
    if temp is not None:
        line = f"အပူချိန် {round(temp)}°C"
        if feels is not None and abs(feels - temp) >= 2:
            line += f"၊ ခံစားရတာတော့ {round(feels)}°C"
        parts.append(line + "။")
    if humidity is not None:
        parts.append(f"စိုထိုင်းဆ {round(humidity)}%။")
    if wind is not None:
        parts.append(f"လေတိုက်နှုန်း တစ်နာရီ {round(wind)} ကီလိုမီတာ။")

    if hi is not None and lo is not None:
        label_day = "မနက်ဖြန်" if day == 1 else "ဒီနေ့"
        summary = f"{label_day} အမြင့်ဆုံး {round(hi)}°C၊ အနိမ့်ဆုံး {round(lo)}°C"
        if rain is not None:
            summary += f"၊ မိုးရွာနိုင်ခြေ {round(rain)}%"
        if day_code is not None and day_code != cur.get("weather_code"):
            summary += f"၊ {_WMO.get(day_code, '')}".rstrip("၊ ")
        parts.append(summary + "။")

    return " ".join(parts)


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    parameters = parameters or {}
    city = (parameters.get("city") or "").strip()
    when = (parameters.get("time") or "today").strip() or "today"

    if not city:
        # Falling back to the user's own city beats refusing: the question
        # "how's the weather" without a place almost always means "here".
        city = "နေပြည်တော်"

    text = fetch_weather(city, when)
    _log(text, player)

    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather {city} {when}",
                                           response=text)
        except Exception:
            pass
    return text


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "weather_report",
    "description": (
        "Current weather and today's forecast for a city. Returns real "
        "temperature, humidity, wind and rain chance, so it can be spoken. "
        "Use for any question about the weather. Defaults to Naypyidaw when no "
        "city is given."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "city": {
                "type": "STRING",
                "description": "City name, e.g. နေပြည်တော် or Naypyidaw"
            },
            "time": {
                "type": "STRING",
                "description": "'today' or 'tomorrow'"
            },
        },
        "required": ["city"],
    },
    "handler": weather_action,
}
