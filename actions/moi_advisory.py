"""ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ + တိုင်း/ပြည်နယ်လွှတ်တော် ဥက္ကဋ္ဌများ — offline.

The owner supplied the full lists (Myanmar_Government_Officials_List.docx,
citing moi.gov.mm sources, October 2026). This module keeps the names as
plain data so JARVIS can answer instantly, offline, with certainty — no
live PDF fetch needed.

Two rosters live here:

  1. ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ အဖွဲ့ဝင်များ        (_ADVISORY_COUNCIL)
  2. တိုင်းဒေသကြီး/ပြည်နယ် လွှတ်တော်ဥက္ကဋ္ဌနှင့် ဒု-ဥက္ကဋ္ဌ  (_HLUTTAW_CHAIRS)

Matching uses the consonant-skeleton trick (base consonants U+1000–U+1021,
same as actions/moi_council.py and actions/moi_ministries.py) so Burmese
combine-mark scramble cannot hide a name — ask by person name or by duty,
both work.
"""
from __future__ import annotations

import re

# (name, ကောင်စီတာဝန်) — ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ
_ADVISORY_COUNCIL: list[tuple[str, str]] = [
    ("ဦးစိုးဝင်း", "ဥက္ကဋ္ဌ"),
    ("ဦးမောင်မောင်အေး", "အတွင်းရေးမှူး"),
    ("ဦးသန်းဆွေ", "အဖွဲ့ဝင်"),
    ("ဦးကိုကိုလှိုင်", "အဖွဲ့ဝင်"),
    ("ဦးမိုးအောင်", "အဖွဲ့ဝင်"),
    ("ဒေါက်တာ ရင်ရင်နွယ်", "အဖွဲ့ဝင်"),
    ("ဒေါ်ချိုချိုကျော်ငြိမ်း", "အဖွဲ့ဝင်"),
    ("ဦးကိုကိုကြီး", "အဖွဲ့ဝင်"),
    ("မန်းငြိမ်းမောင်", "အဖွဲ့ဝင်"),
    ("ဒေါ်ဒွဲဘူ", "အဖွဲ့ဝင်"),
]

_COUNCIL_NAME = "ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ"

# (hluttaw, ဥက္ကဋ္ဌ, ဒုတိယဥက္ကဋ္ဌ) in the official list order.
_HLUTTAW_CHAIRS: list[tuple[str, str, str]] = [
    # ပြည်နယ်လွှတ်တော်များ (၇ ပြည်နယ်)
    ("ကချင်ပြည်နယ်လွှတ်တော်", "ဦးရာဝမ်ဂျုံး", "ဦးသိန်းထွန်းအေး"),
    ("ကယားပြည်နယ်လွှတ်တော်", "ဦးမော်ရယ်", "ဦးစိုးရယ်"),
    ("ကရင်ပြည်နယ်လွှတ်တော်", "ဦးစန်းကို", "ဦးအေးမင်းထွေး"),
    ("ချင်းပြည်နယ်လွှတ်တော်", "ဦးကောလ်လျန်ထန်း (ဦးကော်လျှံ)", "ဦးသန့်ဇင်ဦး"),
    ("မွန်ပြည်နယ်လွှတ်တော်", "ဦးသက်ထွေး", "ဦးမင်းအောင်မြင့်"),
    ("ရခိုင်ပြည်နယ်လွှတ်တော်", "ဒေါက်တာစန်းရွှေ", "ဒေါက်တာထင်လင်းဦး"),
    ("ရှမ်းပြည်နယ်လွှတ်တော်", "ဦးစိုင်းလုံးကျော်", "ဦးစိုင်းထွန်းစိန်"),
    # တိုင်းဒေသကြီးလွှတ်တော်များ (၇ တိုင်းဒေသကြီး)
    ("ရန်ကုန်တိုင်းဒေသကြီးလွှတ်တော်", "ဦးဌေးအောင်", "ဦးကျော်ကျော်စိုး"),
    ("မန္တလေးတိုင်းဒေသကြီးလွှတ်တော်", "ဦးအောင်ကျော်မိုး", "ဦးကျော်မြင့်"),
    ("စစ်ကိုင်းတိုင်းဒေသကြီးလွှတ်တော်", "ဦးတင့်လှိုင်မြင့်", "ဦးမျိုးသန့်"),
    ("တနင်္သာရီတိုင်းဒေသကြီးလွှတ်တော်", "ဦးမြတ်ကို", "ဦးခင်မောင်မြင့်"),
    ("ပဲခူးတိုင်းဒေသကြီးလွှတ်တော်", "ဦးအောင်ချိုဦး", "ဦးကျော်ဌေး"),
    ("မကွေးတိုင်းဒေသကြီးလွှတ်တော်", "ဒေါက်တာမောင်မောင်ဌေး", "ဦးခင်မောင်ညို"),
    ("ဧရာဝတီတိုင်းဒေသကြီးလွှတ်တော်", "ဦးသိန်းထွန်း", "ဦးသက်နိုင်ဦး"),
]

_LIST_TITLE = "တိုင်းဒေသကြီးနှင့် ပြည်နယ် လွှတ်တော်ဥက္ကဋ္ဌများနှင့် ဒုတိယဥက္ကဋ္ဌများ"

# ASCII digits → Burmese digits, so list numbering reads ၁။ … ၁၀။ like the
# official list.
_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def _key(s: str) -> str:
    """Consonant skeleton of a Burmese string — base consonants only."""
    return "".join(
        ch for ch in (s or "")
        if "\u1000" <= ch <= "\u1021" or ch.isascii() and ch.isalnum()
    )


def _matches(asked: str, name: str) -> bool:
    """True when the asked string names this person/role/body, ignoring spaces."""
    squash = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    a, t = squash(asked), squash(name)
    if a and t and (a in t or t in a):
        return True
    ka, kt = _key(asked), _key(name)
    return bool(ka) and bool(kt) and (ka in kt or kt in ka)


def _is_council_query(asked: str) -> bool:
    skeleton = _key(asked)
    return ("ကကယယ" in skeleton and "တိုငပင" in skeleton) or "အတိုင်ပင်ခံကောင်စီ" in asked


def _is_hluttaw_query(asked: str) -> bool:
    return "လွှတ်တော်" in asked and ("ဥက္ကဋ္ဌ" in asked or "စာရင်း" in asked)


def moi_advisory_council(parameters: dict = None, **_) -> str:
    """Answer questions about the ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ and the
    state/region hluttaw chairs & deputy chairs. Offline, from local data.

    The signature is `(parameters, ...)` because core/action_loader.py calls
    a handler as `fn(parameters=parameters, ...)` — a handler that swallows
    the dict in `**_` runs on defaults.
    """
    p = parameters or {}
    asked = str(p.get("name") or p.get("query") or "").strip()
    if not asked:
        return ("ဘယ်အဖွဲ့/လွှတ်တော် (သို့) နာမည်လဲ ပြောပါ — ဥပမာ "
                "ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ၊ ရန်ကုန်တိုင်းလွှတ်တော်၊ "
                "ဒါမှမဟုတ် ပုဂ္ဂိုလ်နာမည် တစ်ခု မေးနိုင်ပါသည်။")

    # ── ၁။ ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ ──
    council_matches = [
        (name, duty) for name, duty in _ADVISORY_COUNCIL
        if _matches(asked, name) or _matches(asked, duty)
    ]
    if council_matches or _is_council_query(asked) or _matches(asked, _COUNCIL_NAME):
        if _is_council_query(asked) or _matches(asked, _COUNCIL_NAME):
            lines = [f"**{_COUNCIL_NAME} အဖွဲ့ဝင်များစာရင်း**"]
            for i, (name, duty) in enumerate(_ADVISORY_COUNCIL, start=1):
                lines.append(f"{str(i).translate(_DIGITS)}။ {name} - {duty}")
            lines.append("ℹ️ လိုကယ်ဒေတာမှ ဖြေထားတာပါ — moi.gov.mm စာရင်းအရ ဖြစ်သည်။")
            return "\n".join(lines)
        out = []
        for name, duty in _ADVISORY_COUNCIL:
            if _matches(asked, name):
                out.append(f"{name} သည် {_COUNCIL_NAME} ၏ **{duty}** ဖြစ်သည်။")
        if out:
            return "\n".join(out)

    # ── လွှတ်တော် ဥက္ကဋ္ဌ/ဒုတိယဥက္ကဋ္ဌ မေးခွန်းများ ──
    person_hits = [
        (hl, chair, dep) for hl, chair, dep in _HLUTTAW_CHAIRS
        if _matches(asked, chair) or _matches(asked, dep)
    ]
    if person_hits:
        out = []
        for hl, chair, deputy in person_hits:
            if _matches(asked, chair):
                out.append(f"{chair} သည် **{hl}** ၏ ဥက္ကဋ္ဌ ဖြစ်သည်။")
            if deputy and _matches(asked, deputy):
                out.append(f"{deputy} သည် **{hl}** ၏ ဒုတိယဥက္ကဋ္ဌ ဖြစ်သည်။")
        return "\n".join(out[:3])

    hl_hits = [(hl, chair, deputy) for hl, chair, deputy in _HLUTTAW_CHAIRS
               if _matches(asked, hl)]
    if hl_hits:
        out = []
        for hl, chair, deputy in hl_hits[:3]:
            out.append(f"**{hl}** — ဥက္ကဋ္ဌ: {chair}၊ ဒုတိယဥက္ကဋ္ဌ: {deputy}။")
        return "\n".join(out)

    return (f"⚠️ '{asked}' ကို ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ နှင့် "
            f"တိုင်းဒေသကြီး/ပြည်နယ် လွှတ်တော်ဥက္ကဋ္ဌ စာရင်းများထဲ "
            f"မတွေ့ပါ။ ပုဂ္ဂိုလ်နာမည် သို့မဟုတ် အဖွဲ့အစည်းအမည်ဖြင့် မေးပါ။")


TOOL = {
    "name": "moi_advisory_council",
    "description": (
        "Answer questions about Myanmar's ပြည်ထောင်စုအတိုင်ပင်ခံကောင်စီ "
        "(Union Advisory Council) members and the တိုင်းဒေသကြီး/ပြည်နယ် "
        "လွှတ်တော် ဥက္ကဋ္ဌ / ဒုတိယဥက္ကဋ္ဌ rosters. Use when the user asks "
        "who chairs a state/region hluttaw (e.g. 'ရန်ကုန်တိုင်းလွှတ်တော် "
        "ဥက္ကဋ္ဌ ဘယ်သူလဲ'), who a person is on the advisory council "
        "(e.g. 'ဦးစိုးဝင်း ဘာတာဝန်လဲ'), or the full member list "
        "('အတိုင်ပင်ခံကောင်စီ အဖွဲ့ဝင် စာရင်းပြပါ'). Offline, from a "
        "local list; no website fetch. Not for the NDSC council "
        "(moi_council), ministries (moi_ministries), or news."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": (
                    "The person, organization, or hluttaw name the user "
                    "asked about, in Burmese."
                ),
            },
        },
        "required": ["name"],
    },
    "handler": moi_advisory_council,
}
