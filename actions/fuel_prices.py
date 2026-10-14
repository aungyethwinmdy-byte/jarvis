"""Action: fuel_prices — Myanmar + world fuel prices, asked and answered.

Two sources, in order — the owner's rule is that the freshest honest answer wins:

  1. **The newsroom DB first.** The PPRD (Petroleum Products Regulatory
     Department) weekly price announcement arrives as a news article, so the
     newest "စက်သုံးဆီ" article (last 21 days) is fetched and the per-grade
     prices are extracted from its text. This is the official weekly cap and
     the freshest source available.
  2. **GlobalPetrolPrices.com as fallback.** Weekly Myanmar retail series
     (gasoline-95 + diesel, MMK/litre) plus the world average. The update date
     is always shown — a price without its date is how a stale figure gets
     quoted as today's.

Handler signature follows the whole codebase (see actions/weather_report.py):
    fn(parameters, player=None, session_memory=None) -> str

Numbers are rendered in the established Burmese-digit style, grouped with
commas. The voice path never raises: every failure becomes a sentence.
"""
from __future__ import annotations

import re
import urllib.request

# ── display ──────────────────────────────────────────────────────────────────

_BD = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def _bd(value) -> str:
    """1,234,567 -> ၁,၂၃၄,၅၆၇. The spoken path reads Burmese digits."""
    text = f"{value:,}" if isinstance(value, (int, float)) else str(value)
    return text.translate(_BD)


def _to_ascii(text: str) -> str:
    """Burmese digits -> ASCII, for parsing. A wrong date is worse than none,
    but a wrong *price* is worse still — so parsing always works on ASCII."""
    return str(text or "").translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789"))


# ── fetching ─────────────────────────────────────────────────────────────────

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
_FETCH_TIMEOUT = 20.0


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


# ── source 1: the newsroom DB (PPRD weekly announcement as an article) ───────

# grade -> pattern. After _to_ascii() the Burmese digits are ASCII, so one
# pattern covers both scripts. `(?<!\d)` keeps "92" from matching "1992".
_GRADES = (
    ("92", r"(?<!\d)92(?!\d)"),
    ("95", r"(?<!\d)95(?!\d)"),
    ("premium_diesel", r"premium|ပရီမီယ"),
    ("diesel", r"diesel|ဒီဇယ်"),
)
_GRADE_LABEL = {
    "92": "92 Octane",
    "95": "95 Octane",
    "diesel": "ဒီဇယ်",
    "premium_diesel": "ပရီမီယမ်ဒီဇယ်",
}
_QUERIES = ("စက်သုံးဆီဈေး", "စက်သုံးဆီ", "လောင်စာဆီဈေး")


def _extract_prices(text: str) -> dict:
    """grade -> kyat/litre, from announcement prose.

    Takes the first plausible number (500–30,000) within ~60 chars after the
    grade mention. "diesel" inside "premium diesel" is skipped so the two
    grades do not report each other's price.
    """
    t = _to_ascii(text)
    found: dict[str, int] = {}
    for key, pat in _GRADES:
        for m in re.finditer(pat, t, flags=re.I):
            if key == "diesel":
                before = t[max(0, m.start() - 14):m.start()].lower()
                if "premium" in before or "ပရီမီယံ" in before:
                    continue
            num = re.search(r"(\d[\d,]*)", t[m.end():m.end() + 60])
            if not num:
                continue
            val = int(num.group(1).replace(",", ""))
            if 500 <= val <= 30000:
                found[key] = val
                break
    return found


def _newsroom_latest() -> dict | None:
    """Newest PPRD-style fuel article with extractable prices, or None."""
    try:
        from core import newsroom_client as nr
    except Exception:
        return None
    try:
        ok, _ = nr.available()
    except Exception:
        return None
    if not ok:
        return None
    for q in _QUERIES:
        try:
            hits = nr.search_articles(q, days=21, limit=5)
        except Exception:
            continue
        for h in hits or []:
            url = (h.get("url") or "").strip()
            if not url:
                continue
            try:
                prices = _extract_prices(_strip_html(_fetch(url)))
            except Exception:
                continue
            if prices:
                return {
                    "prices": prices,
                    "source": h.get("source") or "",
                    "title": h.get("title") or "",
                    "published": h.get("published") or "",
                    "url": url,
                }
    return None


def _fmt_date(value) -> str:
    """A datetime, ISO string or '' -> '၁၃ အောက်တိုဘာ ၂၀၂၆' or ''."""
    try:
        if hasattr(value, "year"):
            y, m, d = value.year, value.month, value.day
        else:
            m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
            if not m2:
                return ""
            y, m, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        months = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
                  "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ",
                  "ဒီဇင်ဘာ")
        return f"{_bd(d)} {months[m]} {_bd(y)}"
    except Exception:
        return ""


def _format_newsroom(data: dict) -> str:
    lines = ["⛽ **စက်သုံးဆီဈေးနှုန်း**"]
    stamp = _fmt_date(data.get("published"))
    src = data.get("source") or "သတင်း"
    lines.append(f"📰 ရင်းမြစ်: {src}"
                 + (f" — {stamp}" if stamp else "")
                 + " (PPRD ကြေညာချက်)")
    lines.append("")
    for key in ("92", "95", "diesel", "premium_diesel"):
        if key in data["prices"]:
            lines.append(f"• {_GRADE_LABEL[key]} — {_bd(data['prices'][key])} ကျပ်/လီတာ")
    lines.append("")
    lines.append("ℹ️ ဒါက တရားဝင်တစ်ပတ်စာဈေးနှုန်းပါ — ဆိုင်အလိုက် အနည်းငယ် ကွာနိုင်ပါတယ်။")
    return "\n".join(lines)


# ── source 2: GlobalPetrolPrices.com (fallback, always with its date) ─────────

_GPP = "https://www.globalpetrolprices.com/Myanmar"


def _gpp_page(kind: str) -> dict | None:
    """kind: 'gasoline' | 'diesel' -> {'mmk', 'usd', 'date'} or None."""
    try:
        html = _fetch(f"{_GPP}/{kind}_prices/")
    except Exception:
        return None
    price = re.search(r"MMK ([\d,]+\.\d+) per liter", html)
    usd = re.search(r"or USD ([\d.]+) per liter", html)
    date = re.search(r"updated on (\d{2}-[A-Za-z]{3}-\d{4})", html)
    world = re.search(
        r"average price of " + kind + r" in the world is USD ([\d.]+) per liter",
        html, flags=re.I)
    if not price:
        return None
    return {
        "mmk": price.group(1),
        "usd": usd.group(1) if usd else "",
        "date": date.group(1) if date else "",
        "world_usd": world.group(1) if world else "",
    }


def _format_gpp(gas: dict, dsl: dict) -> str:
    stamp = gas.get("date") or dsl.get("date") or ""
    lines = ["⛽ **စက်သုံးဆီဈေးနှုန်း (မြန်မာ)**",
             f"🌐 ရင်းမြစ်: GlobalPetrolPrices"
             + (f" — {stamp} update" if stamp else ""),
             ""]
    if gas:
        lines.append(f"• ဓာတ်ဆီ (95 Octane) — {_bd(gas['mmk'])} ကျပ်/လီတာ"
                     + (f" (ကမ္ဘာ့ပျမ်းမျှ ${gas['world_usd']}/လီတာ)"
                        if gas.get("world_usd") else ""))
    if dsl:
        lines.append(f"• ဒီဇယ် — {_bd(dsl['mmk'])} ကျပ်/လီတာ"
                     + (f" (ကမ္ဘာ့ပျမ်းမျှ ${dsl['world_usd']}/လီတာ)"
                        if dsl.get("world_usd") else ""))
    lines += ["",
              "ℹ️ တစ်ပတ်တစ်ခါ update ဖြစ်တာမို့ ရက်စွဲကို ကြည့်ပါ — "
              "အလတ်ဆတ်ဆုံး တရားဝင်ဈေးက PPRD ကြေညာချက်ပါ။"]
    return "\n".join(lines)


# ── entry point ──────────────────────────────────────────────────────────────

def fuel_prices(parameters: dict | None = None,
                player=None, session_memory=None, **_) -> str:
    """Voice entry point. Newsroom first, GlobalPetrolPrices as fallback."""
    try:
        data = _newsroom_latest()
        if data:
            return _format_newsroom(data)
        gas, dsl = _gpp_page("gasoline"), _gpp_page("diesel")
        if gas or dsl:
            return _format_gpp(gas or {}, dsl or {})
        return ("⚠️ စက်သုံးဆီဈေး ရှာလို့ မရပါ — newsroom DB လည်း မချိတ်နိုင်သလို "
                "GlobalPetrolPrices ကိုလည်း ဖွင့်လို့ မရပါ။ ခဏနေ ပြန်မေးပေးပါ။")
    except Exception as e:                                  # noqa: BLE001
        print(f"[FuelPrices] unexpected: {type(e).__name__}: {e}")
        return "⚠️ စက်သုံးဆီဈေး ရှာတာ မအောင်မြင်ပါ။ ခဏနေ ပြန်မေးပေးပါ။"


def run(params: dict | None = None) -> str:
    """Direct call (tests, scripts)."""
    return fuel_prices(params)


TOOL = {
    "name": "fuel_prices",
    "description": (
        "Myanmar + world fuel prices, asked and answered. "
        "**Use this for any fuel-price question**: 'ဒီနေ့ ဆီဈေးဘယ်လောက်', "
        "'ဒီဇယ်ဈေး', '92 ဈေး', 'ကမ္ဘာ့ဆီဈေး'. "
        "\n"
        "Sources, in order: (1) the **newsroom DB** — the PPRD weekly price "
        "announcement arrives as a news article, so the newest fuel article "
        "(last 21 days) is read and the per-grade prices extracted; this is the "
        "official weekly cap and the freshest source. (2) **GlobalPetrolPrices** "
        "fallback — weekly Myanmar retail series (gasoline-95, diesel) plus the "
        "world average; the update date is always shown. "
        "\n"
        "The answer always names its source **and its date** — a price without "
        "a date is never quoted as today's. Prices are per litre in kyat, in "
        "Burmese digits for the spoken path."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
    "handler": fuel_prices,
}
