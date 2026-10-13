"""အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ အမည်စာရင်း — offline.

The owner pasted the full member list (from moi.gov.mm/general-pdf/74156).
This module keeps the names as plain data so JARVIS can answer instantly,
offline, with certainty — no live PDF fetch needed.

Matching uses the consonant-skeleton trick (base consonants U+1000–U+1021,
same as actions/moi_ministries.py) so Burmese combine-mark scramble cannot
hide a name — ask by person name or by position, both work.
"""
from __future__ import annotations

import re

# (name, position) in the official list order.
_COUNCIL: list[tuple[str, str]] = [
    ("ဦးမင်းအောင်လှိုင်", "နိုင်ငံတော်သမ္မတ"),
    ("ဦးညိုစော", "ဒုတိယသမ္မတ"),
    ("ဒေါ်နန်းနီနီအေး", "ဒုတိယသမ္မတ"),
    ("ဦးခင်ရီ", "ဥက္ကဋ္ဌ၊ ပြည်သူ့လွှတ်တော်"),
    ("ဦးအောင်လင်းဒွေး", "ဥက္ကဋ္ဌ၊ အမျိုးသားလွှတ်တော်"),
    ("ဗိုလ်ချုပ်ကြီး ရဲဝင်းဦး", "တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်"),
    ("ဗိုလ်ချုပ်ကြီး ကျော်စွာလင်း", "ဒုတိယတပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်"),
    ("ဗိုလ်ချုပ်ကြီး ရာပြည့်", "ပြည်ထောင်စုဝန်ကြီး၊ ကာကွယ်ရေးဝန်ကြီးဌာန"),
    ("ဗိုလ်ချုပ်ကြီး ကိုကိုဦး", "ပြည်ထောင်စုဝန်ကြီး၊ ပြည်ထဲရေးဝန်ကြီးဌာန"),
    ("ဦးတင်မောင်ဆွေ", "ပြည်ထောင်စုဝန်ကြီး၊ နိုင်ငံခြားရေးဝန်ကြီးဌာန"),
    ("ဒုတိယဗိုလ်ချုပ်ကြီး ဖုန်းမြတ်", "ပြည်ထောင်စုဝန်ကြီး၊ နယ်စပ်ရေးရာဝန်ကြီးဌာန"),
]

_COUNCIL_NAME = "အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ"

# ASCII digits → Burmese digits, so roster numbering reads ၁။ … ၁၁။ like
# the official list.
_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def _key(s: str) -> str:
    """Consonant skeleton of a Burmese string — base consonants only."""
    return "".join(
        ch for ch in (s or "")
        if "\u1000" <= ch <= "\u1021" or ch.isascii() and ch.isalnum()
    )


def _matches(asked: str, name: str) -> bool:
    """True when the asked string names this person/position, ignoring spaces."""
    squash = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    a, t = squash(asked), squash(name)
    if a and t and (a in t or t in a):
        return True
    ka, kt = _key(asked), _key(name)
    return bool(ka) and bool(kt) and (ka in kt or kt in ka)


def _is_council_query(asked: str) -> bool:
    """True when the question is about the council itself, not one member."""
    skeleton = _key(asked)
    # 'ကာကွယ်ရေး' + 'လုံခြုံရေး' + 'ကောင်စီ' skeletons appear together only
    # when the whole council is asked for.
    return ("ကကယယ" in skeleton and "လုံခြုံရေး" in asked) or "ကောင်စီ" in asked


def moi_council(parameters: dict = None, **_) -> str:
    """Answer questions about the အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ.

    Ask by member name → exact position. Ask by the council name → full
    roster. The signature is `(parameters, ...)` because core/action_loader.py
    calls a handler as `fn(parameters=parameters, ...)` — a handler that
    swallows the dict in `**_` runs on defaults.
    """
    p = parameters or {}
    asked = str(p.get("name") or p.get("query") or "").strip()
    if not asked:
        return ("ဘယ်သူရဲ့ ရာထူးလဲ ပြောပါ — ဥပမာ ဦးမင်းအောင်လှိုင်၊ ဗိုလ်ချုပ်ကြီး ထွန်းအောင် — "
                f"သို့မဟုတ် '{_COUNCIL_NAME} အဖွဲ့ဝင် စာရင်း' လို့ မေးပါ။")

    # Whole-council question → full roster.
    if _is_council_query(asked):
        lines = [f"**{_COUNCIL_NAME} အမည်စာရင်း (moi.gov.mm/general-pdf/74156)**"]
        for i, (name, pos) in enumerate(_COUNCIL, start=1):
            lines.append(f"{str(i).translate(_DIGITS)}။ {name} - {pos}")
        lines.append("ℹ️ လိုကယ်ဒေတာမှ ဖြေထားတာပါ — moi.gov.mm မှ ရယူထားသည်။")
        return "\n".join(lines)

    # Member-name question → exact position(s).
    hits = [(name, pos) for name, pos in _COUNCIL if _matches(asked, name)]
    if hits:
        out = []
        for name, pos in hits:
            out.append(f"{name} သည် {_COUNCIL_NAME} အဖွဲ့ဝင် — **{pos}** ဖြစ်သည်။")
        return "\n".join(out)

    # Position question (e.g. 'ဒုတိယသမ္မတ ဘယ်သူလဲ').
    pos_hits = [(name, pos) for name, pos in _COUNCIL if _matches(asked, pos)]
    if pos_hits:
        names = "၊ ".join(n for n, _ in pos_hits)
        return f"{asked} — {names} (အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ အဖွဲ့ဝင်)။"

    return (f"⚠️ '{asked}' ကို အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ စာရင်းထဲ "
            f"မတွေ့ပါ။ အဖွဲ့ဝင် နာမည် သို့မဟုတ် ရာထူးဖြင့် မေးပါ။")


TOOL = {
    "name": "moi_council",
    "description": (
        "Answer questions about Myanmar's အမျိုးသားကာကွယ်ရေးနှင့် "
        "လုံခြုံရေးကောင်စီ (National Defence and Security Council) roster. "
        "Use when the user asks a member's position by name (e.g. "
        "'ဦးမင်းအောင်လှိုင် ဘယ်ရာထူးလဲ'), who holds a position (e.g. "
        "'ဒုတိယသမ္မတ ဘယ်သူလဲ'), or the full council member list "
        "('ကောင်စီ အဖွဲ့ဝင် စာရင်းပြပါ'). Offline, from a local list; "
        "no website fetch. Not for ministries (moi_ministries), documents "
        "(moi_documents), or news (moi_news)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": (
                    "The member name, position, or council name the user "
                    "asked about, in Burmese."
                ),
            },
        },
        "required": ["name"],
    },
    "handler": moi_council,
}
