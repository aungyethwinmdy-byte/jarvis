"""ပြည်ထောင်စုအဆင့် ရုံး၊ အဖွဲ့အစည်းများ — offline.

The owner pasted the full list (from moi.gov.mm/general-pdf/13696): twelve
union-level bodies with their ဥက္ကဋ္ဌ / ဒုတိယဥက္ကဋ္ဌ. Names are kept as plain
data so JARVIS can answer instantly, offline, with certainty — no live PDF
fetch needed.

Matching uses the consonant-skeleton trick (base consonants U+1000–U+1021,
same as actions/moi_ministries.py and actions/moi_council.py) so Burmese
combine-mark scramble cannot hide a name — ask by organization, by person,
or for the whole list.
"""
from __future__ import annotations

import re

# (organization, ဥက္ကဋ္ဌ, [ဒုတိယဥက္ကဋ္ဌ, ...]) in the official list order.
_OFFICES: list[tuple[str, str, list[str]]] = [
    ("ပြည်သူ့လွှတ်တော်", "ဦးခင်ရီ", ["ဦးမောင်မောင်အုန်း"]),
    ("အမျိုးသားလွှတ်တော်", "ဦးအောင်လင်းဒွေး", ["Jeng Phang နော်တောင်"]),
    ("ပြည်ထောင်စုတရားလွှတ်တော်ချုပ်ရုံး", "ဦးသာဌေး", []),
    ("နိုင်ငံတော်ဖွဲ့စည်းပုံအခြေခံဥပဒေဆိုင်ရာခုံရုံး", "ဦးအောင်ဇော်သိန်း", []),
    ("ပြည်ထောင်စုရွေးကောက်ပွဲကော်မရှင်ရုံး", "ဦးသန်းစိုး", []),
    ("ပြည်ထောင်စုရှေ့နေချုပ်", "ဒေါက်တာသီတာဦး", ["ဒေါက်တာထိန်လင်းဦး"]),
    ("ပြည်ထောင်စုစာရင်းစစ်ချုပ်ရုံး", "ဒေါ်ခိုင်သက္ကာဦး", []),
    ("ပြည်ထောင်စုရာထူးဝန်အဖွဲ့", "ဦးတင်မောင်ဝင်း", []),
    ("နေပြည်တော်ကောင်စီ", "ဦးကံမြင့်သန်း", []),
    ("မြန်မာနိုင်ငံတော်ဗဟိုဘဏ်", "ဒေါ်သန်းသန်းဆွေ",
     ["ဦးဇော်မြင့်နိုင်", "ဦးသက်ထွန်းအောင်", "ဒေါက်တာနွယ်နွယ်"]),
    ("အဂတိလိုက်စားမှုတိုက်ဖျက်ရေးကော်မရှင်ရုံး", "ဦးစိုးသိန်း", []),
    ("မြန်မာနိုင်ငံ အမျိုးသားလူ့အခွင့်အရေး ကော်မရှင်ရုံး", "ဦးသန်းလင်းအုန်း", []),
]

_LIST_TITLE = "ပြည်ထောင်စုအဆင့် ရုံး၊ အဖွဲ့အစည်းများ"

# ASCII digits → Burmese digits, so list numbering reads ၁။ … ၁၂။ like the
# official list.
_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def _key(s: str) -> str:
    """Consonant skeleton of a Burmese string — base consonants only."""
    return "".join(
        ch for ch in (s or "")
        if "\u1000" <= ch <= "\u1021" or ch.isascii() and ch.isalnum()
    )


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _matches(asked: str, name: str) -> bool:
    """True when the asked string names this org/person, ignoring spaces."""
    a, t = _squash(asked), _squash(name)
    if a and t and (a in t or t in a):
        return True
    ka, kt = _key(asked), _key(name)
    return bool(ka) and bool(kt) and (ka in kt or kt in ka)


def _is_list_query(asked: str) -> bool:
    """True when the whole list, not one org/person, is asked for."""
    if _LIST_TITLE in asked or _key(_LIST_TITLE) in _key(asked):
        return True
    if "စာရင်း" in asked or "အဖွဲ့အစည်းများ" in asked:
        return True
    # "ပြည်ထောင်စုအဆင့် ရုံးအဖွဲ့" etc. — the category name, no member named
    return "ပြည်ထောင်စုအဆင့်" in asked



def moi_union_offices(parameters: dict = None, **_) -> str:
    """Answer questions about the ပြည်ထောင်စုအဆင့် ရုံး/အဖွဲ့ list (13696).

    Ask by organization → chair + deputies. Ask by person → organization and
    position. Ask for the list → full 12-body roster. The signature is
    `(parameters, ...)` because core/action_loader.py calls a handler as
    `fn(parameters=parameters, ...)` — a handler that swallows the dict in
    `**_` runs on defaults.
    """
    p = parameters or {}
    asked = str(p.get("name") or p.get("query") or "").strip()
    if not asked:
        return ("ဘယ်ရုံး/အဖွဲ့အစည်းလဲ ပြောပါ — ဥပမာ ပြည်သူ့လွှတ်တော်၊ ဗဟိုဘဏ် — "
                f"သို့မဟုတ် '{_LIST_TITLE} စာရင်း' လို့ မေးပါ။")

    # Whole-list question → full roster.
    if _is_list_query(asked):
        lines = [f"**{_LIST_TITLE} (moi.gov.mm/general-pdf/13696)**"]
        for i, (org, chair, deputies) in enumerate(_OFFICES, start=1):
            num = str(i).translate(_DIGITS)
            lines.append(f"{num}။ {org}")
            lines.append(f"- ဥက္ကဋ္ဌ: {chair}")
            if deputies:
                lines.append(f"- ဒုတိယဥက္ကဋ္ဌ: {'၊ '.join(deputies)}")
        lines.append("ℹ️ လိုကယ်ဒေတာမှ ဖြေထားတာပါ — moi.gov.mm မှ ရယူထားသည်။")
        return "\n".join(lines)

    # Person question → organization + position (people checked first, longest
    # name first so a person is not swallowed by a shorter org match).
    person_hits: list[tuple[str, str, str]] = []
    for org, chair, deputies in _OFFICES:
        people = [(chair, "ဥက္ကဋ္ဌ")] + [(d, "ဒုတိယဥက္ကဋ္ဌ") for d in deputies]
        for person, title in sorted(people, key=lambda w: -len(_key(w[0]))):
            if _matches(asked, person):
                person_hits.append((person, title, org))
                break  # one role per org is enough
    if person_hits:
        return "\n".join(f"{person} သည် **{org}** ၏ {title} ဖြစ်သည်။"
                         for person, title, org in person_hits[:3])

    # Organization question → chair + deputies.
    org_hits = [(org, chair, deputies) for org, chair, deputies in _OFFICES
                if _matches(asked, org)]
    if org_hits:
        out = []
        for org, chair, deputies in org_hits[:3]:
            line = f"**{org}** — ဥက္ကဋ္ဌ: {chair}"
            if deputies:
                line += f"၊ ဒုတိယဥက္ကဋ္ဌ: {'၊ '.join(deputies)}"
            out.append(line + "။")
        return "\n".join(out)

    return (f"⚠️ '{asked}' ကို {_LIST_TITLE} စာရင်းထဲ မတွေ့ပါ။ "
            f"ရုံး/အဖွဲ့အစည်း အမည် သို့မဟုတ် လူနာမည်ဖြင့် မေးပါ။")


TOOL = {
    "name": "moi_union_offices",
    "description": (
        "Answer questions about Myanmar's twelve union-level offices and "
        "organizations (ပြည်ထောင်စုအဆင့် ရုံး၊ အဖွဲ့အစည်းများ — e.g. "
        "ပြည်သူ့လွှတ်တော်, အမျိုးသားလွှတ်တော်, တရားလွှတ်တော်ချုပ်, "
        "ဗဟိုဘဏ်, ကော်မရှင်များ) — their ဥက္ကဋ္ဌ and ဒုတိယဥက္ကဋ္ဌ. "
        "Use when the user asks who chairs an organization (e.g. 'ပြည်သူ့လွှတ်တော် "
        "ဥက္ကဋ္ဌ ဘယ်သူလဲ'), which organization a person leads (e.g. "
        "'ဦးခင်ရီ ဘယ်နေရာမှာ'), or the full list "
        "('ပြည်ထောင်စုအဆင့် ရုံးအဖွဲ့ စာရင်းပြပါ'). Offline, from a local "
        "list; no website fetch. Not for the NDSC council (moi_council), "
        "ministries (moi_ministries), documents (moi_documents), or news "
        "(moi_news)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": (
                    "The organization, person, or list name the user asked "
                    "about, in Burmese."
                ),
            },
        },
        "required": ["name"],
    },
    "handler": moi_union_offices,
}
