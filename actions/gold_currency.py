"""
Action: gold_currency — official MMK exchange rates and the live world gold price.

Replaces the retired `reporter_prices` action (its figures-source path remains
reachable through `reporter_news` only). This action fetches two live sources,
both verified 2026-10:

  * Central Bank of Myanmar official reference rates — https://forex.cbm.gov.mm/api/latest
  * World gold spot (XAU) in USD                      — https://api.gold-api.com/price/XAU

goldprice.org returns 403 and api.metals.live fails its TLS handshake, so
neither is used as a source.

The Myanmar gold price per tical (ကျပ်သား) is derived from the world price:

    MMK per tical = world_gold_usd × usd_rate × 0.525

…where 0.525 is the troy-ounce content of one tical (1/1.90476), and usd_rate
is either the CBM official rate or the street market estimate
(`MARKET_USD_MMK`, maintained here — the CBM endpoint publishes an official
reference only, not the free-market rate gold shops actually trade on).

Two output shapes:
    run({})                                -> rates + gold + tical prices
    run({"amount":100, "from":"THB"})      -> 100 THB → MMK (both rates)

Handler signature follows the whole codebase (see actions/weather_report.py):
    fn(parameters, player=None, session_memory=None) -> str

Numbers are rendered in the established Burmese-digit style
(this module's _num helper): grouped with commas, digits translated.
"""
from __future__ import annotations

import json
import time
import urllib.request

from core.timefmt import now_mmt

CBM_URL = "https://forex.cbm.gov.mm/api/latest"
GOLD_URL = "https://api.gold-api.com/price/XAU"
TIMEOUT = 8.0

# One tical (ကျပ်သား) of gold is 0.525 troy ounce (≈ 1 / 1.90476).
TICAL_OZ = 0.525

# CBM publishes an official reference rate; street gold shops price against the
# free-market rate, which is maintained here. Measured ≈ 4500 in the 2026-10
# draft. Adjust as reality drifts.
MARKET_USD_MMK = 4500.0

SUPPORTED = ("USD", "EUR", "SGD", "THB", "CNY")
CURRENCY_NAMES = {
    "USD": "ဒေါ်လာ",
    "EUR": "ယူရို",
    "SGD": "စင်ကာပူ ဒေါ်လာ",
    "THB": "ထိုင်း ဘတ်",
    "CNY": "တရုတ် ယွမ်",
    "MMK": "မြန်မာ ကျပ်",
}

_MM_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def _bd(text: str) -> str:
    """Latin digits → Burmese digits (grouping commas are preserved)."""
    return str(text or "").translate(_MM_DIGITS)


def _num(value: float, decimals: int = 0) -> str:
    """12500.0 → ၁၂,၅၀၀. Groups and translates like every other JARVIS price."""
    if decimals:
        return _bd(f"{value:,.{decimals}f}")
    return _bd(f"{round(value):,}")


def _get_json(url: str, timeout: float = TIMEOUT) -> dict:
    """JSON at `url`, retried once. Raises on the second failure."""
    last: Exception | None = None
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (JARVIS action/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001 — network errors vary wildly
            last = exc
            if attempt == 0:
                time.sleep(0.4)
    raise RuntimeError(f"{url} — {type(last).__name__}: {last}")


def fetch_cbm_rates(timeout: float = TIMEOUT) -> dict[str, float]:
    """Official CBM reference rates keyed by 3-letter code; MMK == 1.0."""
    data = _get_json(CBM_URL, timeout)
    raw = data.get("rates") or {}
    rates: dict[str, float] = {}
    for code, value in raw.items():
        try:
            rates[str(code).upper()] = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return rates


def fetch_world_gold_usd(timeout: float = TIMEOUT) -> float | None:
    """XAU spot price in USD per troy ounce, or None when the feed is down."""
    try:
        data = _get_json(GOLD_URL, timeout)
    except RuntimeError:
        return None
    for key in ("price", "spotPrice"):
        if key in data:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    return None


def _report(rates: dict[str, float], gold: float | None, date_tag: str) -> str:
    """The spoken report: CBM rates, world gold, and the derived tical price."""
    lines = [f"ဗဟိုဘဏ် တရားဝင် ငွေလဲနှုန်း ({date_tag} မြန်မာစံတော်ချိန်):"]
    for code in ("USD", "EUR", "SGD", "THB", "CNY"):
        if code in rates:
            lines.append(
                f"• ၁ {CURRENCY_NAMES[code]} = {_num(rates[code])} ကျပ်"
            )
    lines.append("")

    if gold and gold > 0:
        lines.append(f"ကမ္ဘာ့ရွှေဈေး: ၁ အောင်စ = {_num(gold, 2)} ဒေါ်လာ (USD)")
        usd_rate = rates.get("USD", 0.0)
        if usd_rate > 0:
            tical_cbm = gold * usd_rate * TICAL_OZ
            lines.append(
                f"မြန်မာ့ရွှေဈေး: ၁ ကျပ်သား ≈ {_num(tical_cbm)} ကျပ် "
                f"(ဗဟိုဘဏ်နှုန်း {_num(usd_rate)})"
            )
        tical_mkt = gold * MARKET_USD_MMK * TICAL_OZ
        lines.append(
            f"ပြင်ပပေါက်ဈေး ခန့်မှန်း: ၁ ကျပ်သား ≈ {_num(tical_mkt)} ကျပ် "
            f"(ဒေါ်လာ {_num(MARKET_USD_MMK)})"
        )
    else:
        lines.append("ကမ္ဘာ့ရွှေဈေး အချက်အလက် ခေတ္တ မရရှိသေးပါ။")
    return "\n".join(lines)


def _convert(rates: dict[str, float], amount: float, frm: str, to_code: str) -> str:
    """A single amount conversion at the CBM rate (and at the market rate → MMK)."""
    usd_rate = rates.get("USD", 0.0)

    if frm == "MMK":
        if to_code == "MMK":
            return f"{_num(amount)} ကျပ် ကို ကျပ်နဲ့ ပြောင်းစရာ မလိုပါ။"
        to_rate = rates.get(to_code, 0.0)
        if to_code == "USD":
            result = amount / usd_rate if usd_rate else 0.0
        else:
            result = (amount / usd_rate) * to_rate if usd_rate else 0.0
        return (f"{_num(amount)} မြန်မာကျပ် → {_num(result, 2)} "
                f"{CURRENCY_NAMES.get(to_code, to_code)} "
                f"(ဗဟိုဘဏ်နှုန်း ၁ ဒေါ်လာ = {_num(usd_rate)} ကျပ်)")

    from_rate = rates.get(frm, 0.0)
    if from_rate <= 0:
        return f"'{frm}' နှုန်း မရပါ။ CBM rates ကို စစ်ပါ။"
    mmk = amount * from_rate

    if to_code == "MMK":
        lines = [
            f"{_num(amount, 2)} {CURRENCY_NAMES[frm]} → {_num(mmk)} ကျပ် "
            f"(ဗဟိုဘဏ်နှုန်း ၁ {frm} = {_num(from_rate)} ကျပ်)"
        ]
        if frm == "USD":
            mkt = amount * MARKET_USD_MMK
            lines.append(
                f"ပြင်ပပေါက်ဈေး ({_num(MARKET_USD_MMK)} ကျပ်) ဖြင့် "
                f"တွက်ပါက ≈ {_num(mkt)} ကျပ်"
            )
        return "\n".join(lines)

    # Convert through MMK: amount(from) → MMK → to.
    to_rate = rates.get(to_code, 0.0)
    if to_rate <= 0:
        return f"'{to_code}' နှုန်း မရပါ။ CBM rates ကို စစ်ပါ။"
    via = mmk / to_rate
    return (f"{_num(amount, 2)} {CURRENCY_NAMES[frm]} → {_num(via, 2)} "
            f"{CURRENCY_NAMES[to_code]} "
            f"(ဗဟိုဘဏ်နှုန်းဖြင့် ကျပ်ကြားခံ တွက်ချက်)")


def _log(message: str, player=None) -> None:
    print(f"[Gold/Currency] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


def _make_text() -> str:
    """The full report: CBM rates + world gold + derived tical price."""
    rates = fetch_cbm_rates()
    gold = fetch_world_gold_usd()
    return _report(rates, gold, _bd(now_mmt().strftime("%d/%m/%Y %H:%M")))


def gold_currency(parameters: dict | None = None,
                  player=None,
                  session_memory=None) -> str:
    """Action entry point: exchange rates + gold, or one amount conversion.

    Reads the parameters the way the loader passes them — as a plain dict —
    and refuses nothing silently: a missing amount falls back to the full
    report, an unknown code is answered with the supported list.
    """
    p = parameters or {}

    # ── currency conversion requested? ──────────────────────────────────────
    amount = p.get("amount")
    if amount not in (None, ""):
        try:
            amount_value = float(amount)
        except (TypeError, ValueError):
            return "ပမာဏ (amount) က နံပါတ် မဟုတ်ပါ — ဥပမာ 100 လိုမျိုး ထည့်ပါ။"
        if amount_value <= 0:
            return "ပမာဏ (amount) က ၀ ထက် ကြီးရပါမယ်။"

        frm = str(p.get("from") or "USD").upper()
        to_code = str(p.get("to") or "MMK").upper()

        known = set(SUPPORTED) | {"MMK"}
        if frm not in known:
            return (f"'{frm}' ငွေကြေး ကုဒ် မရှိပါ။ "
                    f"(ရှိတာ — {', '.join(sorted(known))} သာ။)")
        if to_code not in known:
            return (f"'{to_code}' ငွေကြေး ကုဒ် မရှိပါ။ "
                    f"(ရှိတာ — {', '.join(sorted(known))} သာ။)")

        try:
            rates = fetch_cbm_rates()
        except RuntimeError as exc:
            return f"ဗဟိုဘဏ် ငွေလဲနှုန်း ဆွဲယူလို့ မရပါ — {exc}"
        text = _convert(rates, amount_value, frm, to_code)
        _log(text, player)
        if session_memory:
            try:
                session_memory.set_last_search(
                    query=f"gold_currency {frm} {amount_value} → {to_code}",
                    response=text,
                )
            except Exception:
                pass
        return text

    # ── no amount → the spoken report ───────────────────────────────────────
    try:
        text = _make_text()
    except RuntimeError as exc:
        text = f"ဗဟိုဘဏ်/ရွှေဈေး အချက်အလက် ယူ၍ မရပါ — {exc}"
    _log(text, player)
    if session_memory:
        try:
            session_memory.set_last_search(query="gold_currency report",
                                           response=text)
        except Exception:
            pass
    return text


def run(params: dict | None = None) -> str:
    """Headless runner — `python -c "import actions.gold_currency as gc; print(gc.run())"`."""
    return gold_currency(params or {})


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "gold_currency",
    "description": (
        "Official Central Bank of Myanmar exchange rates (USD, EUR, SGD, THB, "
        "CNY in MMK) and the live world gold price, with the derived Myanmar "
        "gold price per tical (ကျပ်သား). Use for exchange-rate / 'ငွေလဲနှုန်း' "
        "or gold-price / 'ရွှေဈေး' questions, and for currency conversion like "
        "'100 USD in MMK'. Set 'amount' (plus optional 'from'/'to') to convert "
        "a single amount; omit it for the full report."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "amount": {
                "type": "NUMBER",
                "description": "Optional. Amount to convert, e.g. 100. "
                               "Omit for the full rates+gold report.",
            },
            "from": {
                "type": "STRING",
                "description": "3-letter code to convert FROM: "
                               "USD, EUR, SGD, THB, CNY, MMK. Default USD.",
            },
            "to": {
                "type": "STRING",
                "description": "3-letter code to convert TO. Default MMK.",
            },
        },
        "required": [],
    },
    "handler": gold_currency,
}


