"""
Action: maps_navigator — Google Maps directions, travel estimates, and places search.

Provides two primary capabilities:
  1. get_directions(origin, destination, mode='driving')
     Calculates travel distance (km), estimated duration, and route summary.
     Supports modes: driving, walking, transit.
  2. find_places(query, location=None)
     Searches for nearby places, restaurants, hospitals, hotels, or cafes,
     returning names, addresses, and ratings.

API Support & Fallback:
  - If GOOGLE_MAPS_API_KEY is configured (environment variable or config/api_keys.json),
    uses official Google Maps Directions and Places APIs.
  - If no API key is present or on API failure, provides an automatic, free fallback
    using OpenStreetMap (Nominatim for geocoding/places and OSRM for routing).
  - Works completely out-of-the-box without requiring an API key.

Output:
  - Formatted in clean, natural Burmese tailored for Gemini 3.8 Live voice reading
    and JARVIS HUD text display.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

try:
    from core.timefmt import to_burmese_digits
except ImportError:
    _DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")
    def to_burmese_digits(value: Any) -> str:
        return str(value).translate(_DIGITS)

# ── Configuration & Endpoints ────────────────────────────────────────────────
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1"
GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

USER_AGENT = "MarkLIV-Jarvis-Assistant/1.0 (contact: jarvis@local)"
HTTP_TIMEOUT = 9.0

# Memory cache for geocoded locations: query -> (lat, lon, display_name)
_GEO_CACHE: Dict[str, Tuple[float, float, str]] = {}
_LAST_NOMINATIM_CALL = 0.0

_MODE_NAMES_MM = {
    "driving": "မော်တော်ကားဖြင့်",
    "walking": "လမ်းလျှောက် / ခြေလျင်ဖြင့်",
    "transit": "အများသုံးသယ်ယူပို့ဆောင်ရေး (ဘတ်စ်ကား) ဖြင့်",
}


def _get_api_key() -> Optional[str]:
    """Retrieve Google Maps API key from environment or config/api_keys.json."""
    # 1. Environment variable
    env_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if env_key:
        return env_key

    # 2. config/api_keys.json
    try:
        from memory.config_manager import load_api_keys
        cfg = load_api_keys()
        k = cfg.get("google_maps_api_key") or cfg.get("GOOGLE_MAPS_API_KEY")
        if k and isinstance(k, str) and k.strip():
            return k.strip()
    except Exception:
        pass

    return None


def _get_user_home_location() -> str:
    """Retrieve saved home location from user memory, defaulting to Naypyidaw."""
    try:
        from memory.memory_manager import load_memory
        mem = load_memory()
        # 1. location.home_address
        home = mem.get("location", {}).get("home_address", {}).get("value")
        if home and str(home).strip():
            return str(home).strip()
        # 2. user_facts.location
        loc = mem.get("user_facts", {}).get("location", {}).get("value")
        if loc and str(loc).strip():
            return str(loc).strip()
        # 3. identity.location
        ident = mem.get("identity", {}).get("location", {}).get("value")
        if ident and str(ident).strip():
            return str(ident).strip()
    except Exception:
        pass
    return "Naypyidaw"


def _resolve_location_alias(loc: Optional[str]) -> str:
    """Resolves 'home', 'အိမ်', 'ငါ့အိမ်', etc., to the user's saved home location."""
    if not loc or not str(loc).strip():
        return _get_user_home_location()
    cleaned = str(loc).strip()
    c_lower = cleaned.lower()
    if c_lower in ("home", "my home", "house", "my house"):
        return _get_user_home_location()
    for kw in ("ငါ့အိမ်", "ဆရာ့အိမ်", "ကျွန်တော့်အိမ်", "အိမ်"):
        if kw in cleaned:
            return _get_user_home_location()
    return cleaned


# Ways a user says "where I am right now" without naming a place. Kept explicit
# rather than a bare "ဒီ" because that syllable occurs inside ordinary names.
_HERE_HINTS = (
    "ဒီနေရာ", "ဒီကနေ", "ဒီက", "လက်ရှိနေရာ", "လက်ရှိတည်နေရာ",
    "ငါ့နေရာ", "ဆရာ့နေရာ", "ငါရောက်နေတဲ့", "ရောက်နေတဲ့နေရာ",
    "here", "my location", "current location", "current position",
)


def _resolve_origin_for_directions(origin: Optional[str]) -> str:
    """The starting point for a directions request.

    When the user means 'from here' — an omitted origin, or one that only names
    their own position — this must be the LIVE device location, not the saved
    home. That is the whole point of the question: the distance from where they
    are right now, which changes each time they move. The saved location is used
    only when the device cannot supply coordinates.
    """
    t = (origin or "").strip()
    low = t.lower()
    if (not t) or any(h in t or h in low for h in _HERE_HINTS):
        coords = _get_device_coordinates()
        if coords:
            return f"{coords[0]},{coords[1]}"
        return _get_user_home_location()
    return _resolve_location_alias(t)


def _format_duration_burmese(seconds: float) -> str:
    """Formats duration in seconds into natural Burmese time text."""
    total_mins = max(1, int(round(seconds / 60.0)))
    hours = total_mins // 60
    mins = total_mins % 60

    if hours > 0 and mins > 0:
        return f"{to_burmese_digits(hours)} နာရီ {to_burmese_digits(mins)} မိနစ်ခန့်"
    elif hours > 0:
        return f"{to_burmese_digits(hours)} နာရီခန့်"
    else:
        return f"{to_burmese_digits(mins)} မိနစ်ခန့်"


def _format_distance_burmese(km: float) -> str:
    """Formats distance in km with Burmese digits."""
    if km >= 10.0:
        val_str = str(int(round(km)))
    elif km >= 1.0:
        val_str = f"{km:.1f}"
    else:
        # Less than 1 km, show e.g. 500 meters or 0.8 km
        val_str = f"{km:.1f}"
    return to_burmese_digits(val_str)


def _clean_place_name(name: str) -> str:
    """Shortens a full display address to a recognizable place name."""
    if not name:
        return ""
    parts = [p.strip() for p in name.split(",") if p.strip()]
    if not parts:
        return name
    # Take first 1-2 parts for concise reading
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} ({parts[1]})"


# ── OpenStreetMap (Nominatim & OSRM) Fallback ─────────────────────────────────

def _geocode_nominatim(query: str) -> Optional[Tuple[float, float, str]]:
    """Geocode a place query to (lat, lon, display_name) using Nominatim."""
    global _LAST_NOMINATIM_CALL
    q_norm = query.strip().lower()
    if q_norm in _GEO_CACHE:
        return _GEO_CACHE[q_norm]

    # Rate limiting: wait at least 0.6s between Nominatim requests
    now = time.time()
    elapsed = now - _LAST_NOMINATIM_CALL
    if elapsed < 0.6:
        time.sleep(0.6 - elapsed)

    params = {
        "q": query.strip(),
        "format": "json",
        "limit": "1",
        "addressdetails": "1",
        "countrycodes": "mm",
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(2):
        try:
            _LAST_NOMINATIM_CALL = time.time()
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    display_name = item.get("display_name", query)
                    res = (lat, lon, display_name)
                    _GEO_CACHE[q_norm] = res
                    return res
                break
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
            break

    return None


def _geocode_any(query: str) -> Optional[Tuple[float, float, str]]:
    """Resolve a place string to (lat, lon, display) by any means available.

    Nominatim first — it is free and reads Burmese addresses — then Google
    Places Text Search, which is what resolves the nicknames the user actually
    types: 'Mara Vihara Buddha Park' is the real 'Maravijaya Buddha Statue', and
    Nominatim and the Routes geocoder refuse it while a Maps text search finds
    it. Without this a correctly-routed directions call still answered
    "ရှာမတွေ့ပါ".
    """
    q_norm = (query or "").strip().lower()
    if not q_norm:
        return None
    if q_norm in _GEO_CACHE:
        return _GEO_CACHE[q_norm]

    geo = _geocode_nominatim(query)
    if geo:
        return geo

    key = _get_api_key()
    if key:
        # Bias the text search to the user's own area. Without it a search for a
        # local nickname can match the same-named place on the other side of
        # Asia — "Mara Vihara Buddha Park" matched a vihara in Kuala Lumpur and
        # the route came back 2400 km long.
        loc_bias = _get_user_home_location() or "Myanmar"
        places = _places_google(query, loc_bias, key)
        if places:
            p = places[0]
            lat, lng = p.get("lat"), p.get("lng")
            if lat is not None and lng is not None:
                res = (float(lat), float(lng), p.get("address") or query)
                _GEO_CACHE[q_norm] = res
                return res
    return None


def _parse_coords(text: str) -> Optional[Tuple[float, float]]:
    """Parse 'lat,lng'.

    Directions endpoints arrive this way when the user means 'from here': the
    dispatcher resolves their live position to coordinates before calling in.
    """
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", text or "")
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)))


def _coords_or_geocode(text: str) -> Optional[Tuple[float, float, str]]:
    """(lat, lon, display) for an endpoint, accepting bare coordinates.

    For that same 'from here' case: the value is already resolved, so geocoding
    it must be skipped — Nominatim cannot find its own output, and the answer
    would be 'သွားရောက်မည့်နေရာ ရှာမတွေ့ပါ' for the user's own position.
    """
    c = _parse_coords(text)
    if c:
        return (c[0], c[1], text)
    return _geocode_any(text)


def _point_label(text: str) -> str:
    """Readable label for one end of a route.

    A 'from here' origin arrives as bare coordinates, which must not be read out
    as "19.749 (96.069)" — that is not an answer to "where am I". Reverse-geocode
    to the street address instead, and fall back to plain wording if that fails.
    Named places are passed through untouched.
    """
    c = _parse_coords(text)
    if not c:
        return text
    data = _reverse_geocode_nominatim(c[0], c[1])
    if data:
        addr = _format_address_from_data(data)
        if addr:
            return addr
    return "လက်ရှိတည်နေရာ"


def _osrm_route(lat1: float, lon1: float, lat2: float, lon2: float, mode: str) -> Optional[Dict[str, Any]]:
    """Calculate driving/walking route between coordinates using OSRM."""
    profile = "foot" if mode == "walking" else "driving"
    coords = f"{lon1},{lat1};{lon2},{lat2}"
    url = f"{OSRM_ROUTE_URL}/{profile}/{coords}?overview=false&steps=true"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                routes = data.get("routes", [])
                if not routes:
                    return None

                route = routes[0]
                dist_meters = float(route.get("distance", 0.0))
                dur_seconds = float(route.get("duration", 0.0))
                dist_km = round(dist_meters / 1000.0, 1)

                # Realistic duration adjustment for walking and transit
                if mode == "walking":
                    # Standard walking speed 4.5 km/h ≈ 1.25 m/s
                    walking_time = dist_meters / 1.25
                    dur_seconds = max(dur_seconds, walking_time)
                elif mode == "transit":
                    # Public transit estimate (car time + bus stop/transfer factor)
                    dur_seconds = max(dur_seconds * 1.5, 600.0)

                # Extract street names from route steps
                streets: List[str] = []
                legs = route.get("legs", [])
                if legs:
                    for step in legs[0].get("steps", []):
                        name = (step.get("name") or "").strip()
                        if name and name not in streets:
                            streets.append(name)

                summary = "၊ ".join(streets[:4]) if streets else "အဓိကလမ်းမကြီးများ"

                return {
                    "distance_km": dist_km,
                    "duration_sec": dur_seconds,
                    "summary": summary,
                }
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
            break

    return None


def _places_nominatim(query: str, location: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search places using OpenStreetMap Nominatim with extratags."""
    global _LAST_NOMINATIM_CALL
    now = time.time()
    elapsed = now - _LAST_NOMINATIM_CALL
    if elapsed < 0.6:
        time.sleep(0.6 - elapsed)

    search_text = f"{query} {location}".strip() if location and location.lower() not in query.lower() else query.strip()
    params = {
        "q": search_text,
        "format": "json",
        "limit": "5",
        "addressdetails": "1",
        "extratags": "1",
        "countrycodes": "mm",
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    results: List[Dict[str, Any]] = []
    try:
        _LAST_NOMINATIM_CALL = time.time()
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                for item in data:
                    name = item.get("name") or item.get("display_name", "").split(",")[0].strip()
                    addr = item.get("display_name", "").strip()
                    extra = item.get("extratags", {}) or {}
                    stars = extra.get("stars") or extra.get("rating")
                    phone = extra.get("phone") or extra.get("contact:phone")
                    website = extra.get("website") or extra.get("contact:website")

                    results.append({
                        "name": name,
                        "address": addr,
                        "rating": float(stars) if stars and str(stars).replace(".", "", 1).isdigit() else None,
                        "ratings_count": None,
                        "phone": phone,
                        "website": website,
                    })
    except Exception as e:
        print(f"[MapsNavigator] Nominatim places error: {e}")

    return results


# ── Google Maps API Implementation ────────────────────────────────────────────

def _routes_waypoint(text: str) -> Dict[str, Any]:
    """A Routes API waypoint: bare coordinates become latLng, anything else an address.

    The API will not geocode a "19.749,96.069" string as an address, so the
    'from here' origin has to be sent as a location or every directions request
    starting at the user's live position fails over to OSRM.
    """
    c = _parse_coords(text)
    if c:
        return {"location": {"latLng": {"latitude": c[0], "longitude": c[1]}}}
    return {"address": (text or "").strip()}


def _directions_google(origin: str, destination: str, mode: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Query official Google Routes API (computeRoutes)."""
    # Routes API travel modes: DRIVE, WALK, BICYCLE, TRANSIT, TWO_WHEELER
    g_mode = "DRIVE"
    if mode == "walking":
        g_mode = "WALK"
    elif mode == "transit":
        g_mode = "TRANSIT"

    body = json.dumps({
        "origin": _routes_waypoint(origin),
        "destination": _routes_waypoint(destination),
        "travelMode": g_mode,
        "languageCode": "my",
        "units": "METRIC",
    }).encode("utf-8")

    req = urllib.request.Request(
        GOOGLE_ROUTES_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.description,routes.legs",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            routes = data.get("routes", [])
            if routes:
                route = routes[0]
                dist_m = float(route.get("distanceMeters", 0))
                # duration comes as "123s" string
                dur_raw = route.get("duration", "0s")
                dur_s = float(str(dur_raw).rstrip("s")) if dur_raw else 0.0
                summary = route.get("description", "")

                start_addr = origin
                end_addr = destination
                legs = route.get("legs", [])
                if legs:
                    start_addr = legs[0].get("startLocation", {}).get("address", origin) or origin
                    end_addr = legs[-1].get("endLocation", {}).get("address", destination) or destination

                return {
                    "distance_km": round(dist_m / 1000.0, 1),
                    "duration_sec": dur_s,
                    "summary": summary or "အဓိကလမ်းကြောင်း",
                    "start_address": start_addr,
                    "end_address": end_addr,
                }
            # Check for error
            err = data.get("error", {})
            if err:
                print(f"[MapsNavigator] Routes API error: {err.get('message', data)}")
    except Exception as e:
        print(f"[MapsNavigator] Google Routes API error: {e}")

    return None


def _places_google(query: str, location: Optional[str], api_key: str) -> Optional[List[Dict[str, Any]]]:
    """Query official Google Places API (New) Text Search."""
    search_text = f"{query} in {location}".strip() if location and location.lower() not in query.lower() else query.strip()
    body = json.dumps({
        "textQuery": search_text,
        "languageCode": "my",
        "pageSize": 5,
    }).encode("utf-8")

    req = urllib.request.Request(
        GOOGLE_PLACES_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.currentOpeningHours,places.nationalPhoneNumber,places.websiteUri,places.location",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_places = data.get("places", [])
            if raw_places:
                places: List[Dict[str, Any]] = []
                for item in raw_places[:5]:
                    name_obj = item.get("displayName") or {}
                    name = name_obj.get("text", "") if isinstance(name_obj, dict) else str(name_obj)
                    addr = item.get("formattedAddress", "")
                    rating = item.get("rating")
                    count = item.get("userRatingCount")
                    phone = item.get("nationalPhoneNumber")
                    web = item.get("websiteUri")
                    open_now = None
                    hours = item.get("currentOpeningHours")
                    if isinstance(hours, dict):
                        open_now = hours.get("openNow")
                    loc = item.get("location") or {}

                    places.append({
                        "name": name,
                        "address": addr,
                        "rating": rating,
                        "ratings_count": count,
                        "phone": phone,
                        "website": web,
                        "open_now": open_now,
                        "lat": loc.get("latitude"),
                        "lng": loc.get("longitude"),
                    })
                return places
            err = data.get("error", {})
            if err:
                print(f"[MapsNavigator] Places API (New) error: {err.get('message', data)}")
    except Exception as e:
        print(f"[MapsNavigator] Google Places API error: {e}")

    return None


# ── Core Features ─────────────────────────────────────────────────────────────

def _maps_url_point(text: str) -> str:
    """One endpoint of a Google Maps directions link, as Google wants it.

    Google Maps' own geocoder resolves `lat,lng` reliably and Burmese addresses
    poorly: handing it the Burmese-format address that get_current_location()
    prints made the browser answer "Google Maps can't find 5 လမ်း၊ ..." even
    though the route itself had been computed. So resolve the text to
    coordinates first (cached, so the OSRM fallback below pays nothing extra)
    and fall back to the raw text only when geocoding fails.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if re.fullmatch(r"-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?", t):
        return t
    geo = _geocode_any(t)
    if geo:
        return f"{geo[0]},{geo[1]}"
    return t


def get_directions(origin: str, destination: str, mode: str = "driving", open_map: bool = False) -> str:
    """Calculates travel distance (km), estimated duration, and route summary.

    Supports modes: 'driving', 'walking', 'transit'.
    Uses Google Maps API if configured, otherwise falls back to OpenStreetMap/OSRM.
    Returns clean, natural Burmese text for speech synthesis and display.
    """
    orig_clean = _resolve_location_alias(origin)
    dest_clean = _resolve_location_alias(destination)

    if not orig_clean or not dest_clean:
        return "လမ်းကြောင်းရှာဖွေရန် စတင်မည့်နေရာနှင့် သွားရောက်မည့်နေရာ နှစ်ခုစလုံးကို ထည့်သွင်းပေးပါခင်ဗျာ။"

    # Normalize mode
    norm_mode = str(mode or "driving").strip().lower()
    if norm_mode in ("car", "drive"):
        norm_mode = "driving"
    elif norm_mode in ("walk", "foot", "on foot"):
        norm_mode = "walking"
    elif norm_mode in ("bus", "train", "transit_bus", "public"):
        norm_mode = "transit"
    if norm_mode not in ("driving", "walking", "transit"):
        norm_mode = "driving"

    mode_label = _MODE_NAMES_MM.get(norm_mode, "မော်တော်ကားဖြင့်")
    # Coordinates where possible, so the browser link actually resolves — see
    # _maps_url_point above for why a Burmese address must not go in raw.
    map_url = (f"https://www.google.com/maps/dir/?api=1"
               f"&origin={urllib.parse.quote(_maps_url_point(orig_clean))}"
               f"&destination={urllib.parse.quote(_maps_url_point(dest_clean))}"
               f"&travelmode={norm_mode}")
    opened_msg = ""
    if open_map:
        try:
            webbrowser.open(map_url)
            opened_msg = "\n🌐 Google Maps လမ်းကြောင်းကို Browser တွင် ဖွင့်ပြပေးလိုက်ပါပြီခင်ဗျာ။"
        except Exception as e:
            print(f"[MapsNavigator] Failed to open browser: {e}")

    # 1. Try Google Maps API if key is present
    api_key = _get_api_key()
    if api_key:
        g_res = _directions_google(orig_clean, dest_clean, norm_mode, api_key)
        if g_res and not g_res.get("not_found"):
            dist_km = g_res["distance_km"]
            dur_sec = g_res["duration_sec"]
            summary = g_res["summary"]
            dist_mm = _format_distance_burmese(dist_km)
            dur_mm = _format_duration_burmese(dur_sec)

            return (
                f"📍 {_point_label(orig_clean)} မှ {_point_label(dest_clean)} သို့ လမ်းကြောင်း အချက်အလက်:\n"
                f"• ခရီးအကွာအဝေး: {dist_mm} ကီလိုမီတာ\n"
                f"• ခန့်မှန်းကြာချိန်: {mode_label} {dur_mm}\n"
                f"• အဓိကလမ်းကြောင်း: {summary} မှတစ်ဆင့် သွားရောက်နိုင်ပါသည်။\n"
                f"• Google Maps လမ်းကြောင်းလင့်ခ်: {map_url}{opened_msg}"
            )
        elif g_res and g_res.get("not_found"):
            return f"'{orig_clean}' မှ '{dest_clean}' သို့ သွားရောက်နိုင်သည့် လမ်းကြောင်း ရှာမတွေ့ပါခင်ဗျာ။"

    # 2. Fallback: OpenStreetMap (Nominatim Geocoding + OSRM Routing)
    geo_start = _coords_or_geocode(orig_clean)
    if not geo_start:
        return f"စတင်မည့်နေရာ '{orig_clean}' ကို မြေပုံပေါ်တွင် ရှာမတွေ့ပါခင်ဗျာ။ တည်နေရာအမည်ကို စစ်ဆေးပေးပါ။"

    geo_end = _coords_or_geocode(dest_clean)
    if not geo_end:
        return f"သွားရောက်မည့်နေရာ '{dest_clean}' ကို မြေပုံပေါ်တွင် ရှာမတွေ့ပါခင်ဗျာ။ တည်နေရာအမည်ကို စစ်ဆေးပေးပါ။"

    lat1, lon1, start_full = geo_start
    lat2, lon2, end_full = geo_end

    route_info = _osrm_route(lat1, lon1, lat2, lon2, norm_mode)
    if not route_info:
        return f"'{orig_clean}' မှ '{dest_clean}' သို့ လမ်းကြောင်းတွက်ချက်မှု မအောင်မြင်ပါခင်ဗျာ။"

    dist_km = route_info["distance_km"]
    dur_sec = route_info["duration_sec"]
    summary = route_info["summary"]

    dist_mm = _format_distance_burmese(dist_km)
    dur_mm = _format_duration_burmese(dur_sec)

    orig_short = _clean_place_name(_point_label(orig_clean))
    dest_short = _clean_place_name(_point_label(dest_clean))

    action_word = "လမ်းလျှောက်သွားနိုင်ပါသည်" if norm_mode == "walking" else ("စီးနင်းနိုင်ပါသည်" if norm_mode == "transit" else "မောင်းနှင်နိုင်ပါသည်")

    return (
        f"📍 {orig_short} မှ {dest_short} သို့ လမ်းကြောင်း အချက်အလက်:\n"
        f"• ခရီးအကွာအဝေး: {dist_mm} ကီလိုမီတာ\n"
        f"• ခန့်မှန်းကြာချိန်: {mode_label} {dur_mm}\n"
        f"• အဓိကလမ်းကြောင်း: {summary} မှတစ်ဆင့် {action_word}။\n"
        f"• Google Maps လမ်းကြောင်းလင့်ခ်: {map_url}{opened_msg}"
    )


def find_places(query: str, location: Optional[str] = None, open_map: bool = False) -> str:
    """Searches for nearby places, restaurants, hospitals, hotels, or cafes.

    Returns names, addresses, and ratings in clean Burmese format, plus a Google
    Maps link for the search. Uses Google Places API if configured, otherwise
    falls back to OpenStreetMap Nominatim. When open_map is True the search is
    also opened in the default browser.
    """
    q_clean = (query or "").strip()
    raw_loc = (location or "").strip() if location else None
    if not raw_loc or any(k in q_clean for k in ("အနီး", "အနီးအနား", "nearby")):
        loc_clean = _get_user_home_location()
    else:
        loc_clean = _resolve_location_alias(raw_loc)

    if not q_clean:
        return "ရှာဖွေလိုသော နေရာ၊ ဆေးရုံ၊ ဟိုတယ် သို့မဟုတ် ဆိုင်အမျိုးအစားကို ဖော်ပြပေးပါခင်ဗျာ။"

    target_desc = f"{loc_clean} ရှိ {q_clean}" if loc_clean else q_clean

    # Built before the search so the "nothing found" reply can still hand the
    # link over — an empty result list is exactly when seeing the map helps.
    map_url = ("https://www.google.com/maps/search/?api=1&query="
               + urllib.parse.quote(f"{q_clean} {loc_clean}".strip()))
    opened_msg = ""
    if open_map:
        try:
            webbrowser.open(map_url)
            opened_msg = ("\n🌐 Google Maps မြေပုံပေါ်တွင် ရှာဖွေမှုကို Browser ဖြင့် "
                          "ဖွင့်ပြပေးလိုက်ပါပြီခင်ဗျာ။")
        except Exception as e:
            print(f"[MapsNavigator] Failed to open browser: {e}")

    places: List[Dict[str, Any]] = []

    # 1. Try Google Places API
    api_key = _get_api_key()
    if api_key:
        g_places = _places_google(q_clean, loc_clean, api_key)
        if g_places:
            places = g_places

    # 2. Fallback: Nominatim
    if not places:
        places = _places_nominatim(q_clean, loc_clean)

    if not places:
        return (f"'{target_desc}' အတွက် ရှာဖွေတွေ့ရှိသည့် နေရာမရှိသေးပါခင်ဗျာ။\n"
                f"🌐 Google Maps လင့်ခ်: {map_url}{opened_msg}")

    lines: List[str] = [f"📍 '{target_desc}' အတွက် တွေ့ရှိသော နေရာများ:"]
    for i, p in enumerate(places[:4], 1):
        num_mm = to_burmese_digits(i)
        name = p.get("name", "အမည်မသိနေရာ")
        addr = p.get("address", "").strip() or "လိပ်စာ မဖော်ပြထားပါ"
        rating = p.get("rating")
        count = p.get("ratings_count")

        rating_str = ""
        if rating is not None:
            r_mm = to_burmese_digits(f"{rating:.1f}")
            if count:
                c_mm = to_burmese_digits(count)
                rating_str = f"⭐ {r_mm} (သုံးသပ်ချက် {c_mm} ခု)"
            else:
                rating_str = f"⭐ {r_mm}"
        else:
            rating_str = "အဆင့်သတ်မှတ်ချက် မရှိသေးပါ"

        line = f"{num_mm}။ {name}\n   • လိပ်စာ: {addr}\n   • အဆင့်သတ်မှတ်ချက်: {rating_str}"
        if p.get("phone"):
            line += f"\n   • ဖုန်း: {p['phone']}"
        lines.append(line)

    lines.append(f"🌐 Google Maps လင့်ခ်: {map_url}")
    return "\n".join(lines) + opened_msg


_CACHED_DEVICE_COORDS: Optional[Tuple[float, float]] = None
_CACHED_DEVICE_TIME: float = 0.0


def _get_device_coordinates() -> Optional[Tuple[float, float]]:
    """Query Windows GeoCoordinateWatcher for device location (GPS/Wi-Fi). Cached for 5 minutes."""
    global _CACHED_DEVICE_COORDS, _CACHED_DEVICE_TIME
    now = time.time()
    if _CACHED_DEVICE_COORDS and (now - _CACHED_DEVICE_TIME < 300.0):
        return _CACHED_DEVICE_COORDS

    if sys.platform != "win32":
        return None

    # The GeoCoordinateWatcher is lazy: a first Start() can report "unknown" for
    # a second or two before Windows has a fix, which made the first "where am
    # I" of a session fall back to the stale saved location. Give it a longer
    # window and, if that still fails, try once more with a fresh watcher.
    ps = (
        "Add-Type -AssemblyName System.Device; "
        "$w = New-Object System.Device.Location.GeoCoordinateWatcher; "
        "$w.Start(); "
        "for ($i=0; $i -lt 20; $i++) { "
        "  if (-not $w.Position.Location.IsUnknown) { break }; "
        "  Start-Sleep -Milliseconds 200 "
        "}; "
        "$p = $w.Position.Location; "
        "if (-not $p.IsUnknown) { "
        "  Write-Output ($p.Latitude.ToString() + ',' + $p.Longitude.ToString()) "
        "}; "
        "$w.Stop()"
    )
    for attempt in range(2):
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=8.0,
            )
            out = r.stdout.strip()
            if out and "," in out:
                parts = out.split(",")
                coords = (float(parts[0]), float(parts[1]))
                _CACHED_DEVICE_COORDS = coords
                _CACHED_DEVICE_TIME = time.time()
                return coords
        except Exception as e:
            print(f"[MapsNavigator] Windows device location error: {e}")
        if attempt == 0:
            time.sleep(0.4)

    if _CACHED_DEVICE_COORDS:
        return _CACHED_DEVICE_COORDS

    return None


def _reverse_geocode_nominatim(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Reverse-geocode latitude and longitude into address components using Nominatim."""
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=my,en"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except Exception as e:
        print(f"[MapsNavigator] Reverse geocode error: {e}")
    return None


def _format_address_from_data(data: Dict[str, Any]) -> str:
    """Format Nominatim reverse-geocode data into clean, natural Burmese address."""
    addr = data.get("address", {})
    road = addr.get("road")
    quarter = addr.get("quarter") or addr.get("suburb") or addr.get("neighbourhood")
    muni = addr.get("municipality") or addr.get("county")
    city = addr.get("city") or addr.get("town") or addr.get("state")

    parts: List[str] = []
    if road:
        clean_road = str(road).strip()
        m = re.match(r"^(\d+)(st|nd|rd|th)?\s+street$", clean_road, re.I)
        if m:
            num = to_burmese_digits(m.group(1))
            parts.append(f"{num} လမ်း")
        else:
            parts.append(clean_road)
    if quarter:
        parts.append(quarter)
    if muni and muni not in parts:
        parts.append(muni)
    if city and city not in parts:
        parts.append(city)

    if parts:
        return "၊ ".join(parts)
    return data.get("display_name", "")


def get_current_location(open_map: bool = False) -> str:
    """Returns the user's current live location address and Google Maps link in natural Burmese.

    First tries Windows device location services (GPS / Wi-Fi). If available,
    reverse-geocodes to exact street and township address. Otherwise, falls back
    to saved memory.
    If open_map is True, opens Google Maps in the default web browser.
    """
    live_addr = ""
    coords = _get_device_coordinates()
    map_url = ""
    coords_text = ""

    if coords:
        lat, lon = coords
        coords_text = f"{lat:.5f}° N, {lon:.5f}° E"
        map_url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
        data = _reverse_geocode_nominatim(lat, lon)
        if data:
            live_addr = _format_address_from_data(data)

    mem_loc = _get_user_home_location()
    target_loc = live_addr or mem_loc

    if not map_url:
        map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(target_loc)}"

    if live_addr:
        # Cache or persist to memory so JARVIS remembers the precise address
        try:
            from memory.memory_manager import update_memory
            update_memory("location", "current_address", live_addr, source="device_gps")
            update_memory("location", "home_address", live_addr, source="device_gps")
        except Exception:
            pass

    opened_msg = ""
    if open_map:
        try:
            webbrowser.open(map_url)
            opened_msg = "\n🌐 Google Maps မြေပုံပေါ်တွင် ဆရာ့လက်ရှိတည်နေရာကို Browser ဖြင့် တိုက်ရိုက် ထုတ်ပြပေးလိုက်ပါပြီခင်ဗျာ။"
        except Exception as e:
            print(f"[MapsNavigator] Failed to open browser: {e}")

    if live_addr:
        return (
            f"📍 ဆရာ လက်ရှိရောက်ရှိနေသော တည်နေရာ အချက်အလက်:\n"
            f"• လိပ်စာ: {live_addr}\n"
            f"• GPS သြဒီနိတ်: {coords_text}\n"
            f"• Google Maps လင့်ခ်: {map_url}\n"
            f"• အခြေအနေ: စက်ပစ္စည်း၏ Live Location (GPS/Wi-Fi တည်နေရာ) ဖြင့် တိုက်ရိုက်ရယူထားပါသည်ခင်ဗျာ။{opened_msg}"
        )

    if coords:
        # A fix is a fix: the coordinates already answer "where am I", and
        # dropping them only because the address lookup failed sent the user
        # back to a stale saved location instead.
        return (
            f"📍 ဆရာ လက်ရှိရောက်ရှိနေသော တည်နေရာ အချက်အလက်:\n"
            f"• GPS သြဒီနိတ်: {coords_text}\n"
            f"• Google Maps လင့်ခ်: {map_url}\n"
            f"• အခြေအနေ: စက်ပစ္စည်း၏ Live Location (GPS/Wi-Fi) ဖြင့် တိုက်ရိုက်ရယူထားပါသည်။ လိပ်စာ အသေးစိတ်ကို ယခုအချိန် ဖော်ပြမနိုင်ပါ။{opened_msg}"
        )

    # Fallback to saved memory
    return (
        f"📍 ဆရာ့ရဲ့ လက်ရှိ သတ်မှတ်ထားသော တည်နေရာ အချက်အလက်:\n"
        f"• တည်နေရာ: {mem_loc}\n"
        f"• Google Maps လင့်ခ်: {map_url}\n"
        f"• အခြေအနေ: မှတ်ဉာဏ်ထဲတွင် '{mem_loc}' ဟု သိမ်းဆည်းမှတ်သားထားရှိပါသည်ခင်ဗျာ။{opened_msg}"
    )


# ── Action Handler & Tool Declaration ─────────────────────────────────────────

def maps_navigator(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs: Any,
) -> str:
    """Action entry point called by JARVIS dispatcher and action runner."""
    params = parameters or {}
    action = str(params.get("action") or "").strip().lower()
    origin = params.get("origin")
    destination = params.get("destination")
    mode = params.get("mode") or "driving"
    query = params.get("query")
    location = params.get("location")
    open_map = bool(params.get("open_map"))

    result: str = ""

    # Location request: if action is 'current_location' or asking about user location/address
    q_str = str(query or "").strip().lower()
    o_str = str(origin or "").strip().lower()

    # Detect user's intent to view/open map
    open_keywords = ("ဖွင့်", "ပြပါ", "ထုတ်ပြ", "ပြပေး", "ကြည့်", "မြေပုံ", "map", "open", "show", "view", "display")
    if any(k in q_str for k in open_keywords) or any(k in o_str for k in open_keywords):
        open_map = True

    loc_keywords = (
        "တည်နေရာ", "လိပ်စာ", "ဘယ်ရောက်", "ငါ့နေရာ", "လက်ရှိနေရာ", "ဘယ်နား", "ဘယ်နေရာ", "နေရပ်",
        "current location", "where am i", "my location", "my address", "address"
    )
    pure_map_q = any(k in q_str for k in ("google map", "မြေပုံ", "maps")) and not any(
        k in q_str for k in ("ဆိုင်", "စားသောက်", "ဟိုတယ်", "ဆေးရုံ", "ကျောင်း", "ဘုရား", "restaurant", "cafe", "hotel", "hospital", "atm", "bank")
    )
    is_loc_q = any(k in q_str for k in loc_keywords) or any(k in o_str for k in loc_keywords) or pure_map_q

    if action in ("current_location", "open_map", "show_map") or (is_loc_q and not destination):
        result = get_current_location(open_map=open_map)
    # Route request: if destination is provided or action is 'directions'
    elif destination or action == "directions" or (origin and destination):
        # "From here" resolves to the live position, not the saved home — see
        # _resolve_origin_for_directions.
        orig_val = _resolve_origin_for_directions(origin)
        dest_val = _resolve_location_alias(destination)
        result = get_directions(origin=orig_val, destination=dest_val, mode=str(mode), open_map=open_map)
    # Places request: if query is provided or action is 'places'
    elif query or action == "places":
        loc_val = location
        if not loc_val or any(k in str(query) for k in ("အနီး", "အနီးအနား", "nearby")):
            loc_val = _get_user_home_location()
        result = find_places(query=str(query or ""), location=_resolve_location_alias(loc_val), open_map=open_map)
    elif origin and not destination:
        # User only gave one location, assume searching for that place
        result = find_places(query=str(origin), location=None, open_map=open_map)
    else:
        # Default fallback: show current location with map
        result = get_current_location(open_map=open_map)

    # Log to UI if player is available
    if player and hasattr(player, "write_log"):
        try:
            player.write_log(f"MAPS: {result.splitlines()[0]}")
        except Exception:
            pass

    return result


def run(params: Optional[Dict[str, Any]] = None) -> str:
    """Headless runner for tools/jarvis_bridge.py or manual tests."""
    return maps_navigator(params or {})


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "maps_navigator",
    "description": (
        "Google Maps navigation, places finder, and user current location. "
        "Use action='directions' when the user asks how long a trip takes or how "
        "far a place is ('ခရီးသွားချိန်', 'ဘယ်လောက်ကြာလဲ', 'how long', 'how far', "
        "'distance') — it returns distance, duration and a route. Use "
        "action='places' to find/search a place, restaurant, hospital, hotel, "
        "bank or shop. Use action='current_location' for the user's own location "
        "or address ('ငါ့တည်နေရာ', 'where am I'). For directions, leave origin "
        "empty when the user means 'from here' — it defaults to their live "
        "location, so 'how far is X from here' works without them naming a "
        "starting point. Set open_map=True to also open Google Maps in the "
        "browser. Output is clean, natural Burmese with links."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["directions", "places", "current_location"],
                "description": "Operation: 'directions' = travel time, duration, distance or navigation between two points; 'places' = search for a place/restaurant/hospital/hotel; 'current_location' = the user's current or home location.",
            },
            "open_map": {
                "type": "BOOLEAN",
                "description": "Set to true to automatically open Google Maps in the web browser (e.g. user asks 'google map နဲ့ ပြ', 'map ပေါ်မှာ ပြ', 'ဖွင့်ပြ').",
            },
            "origin": {
                "type": "STRING",
                "description": "Starting location for directions (e.g. 'Yangon Central Railway Station', 'Sule Pagoda'). Omit this when the user means 'from here' / 'ဒီကနေ' — it then defaults to their live current location.",
            },
            "destination": {
                "type": "STRING",
                "description": "Destination location for directions (e.g. 'Shwedagon Pagoda', 'Mandalay Hill').",
            },
            "mode": {
                "type": "STRING",
                "enum": ["driving", "walking", "transit"],
                "description": "Travel mode: 'driving' (default), 'walking', or 'transit'.",
            },
            "query": {
                "type": "STRING",
                "description": "Search term for places (e.g. 'restaurants', 'hospitals', 'hotels', 'coffee shops', 'Grand Hantha').",
            },
            "location": {
                "type": "STRING",
                "description": "City or area to search in (e.g. 'Yangon', 'Mandalay', 'Dagon').",
            },
        },
        "required": [],
    },
    "handler": maps_navigator,
}
