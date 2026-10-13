"""The union ministries and their minister / deputy ministers — offline.

The owner pasted the full list (from moi.gov.mm/node/2800). This module
keeps the names as plain data so JARVIS can answer instantly, offline,
with certainty — no live PDF fetch needed.

A ministry is matched by consonant-skeleton (base consonants U+1000–U+1021),
the same trick as actions/moi_documents.py, so Burmese combine-mark
scramble cannot hide a name.
"""
from __future__ import annotations

import re

_MINISTRIES: list[dict] = [
    {
        "name": "နိုင်ငံတော်သမ္မတရုံး",
        "union_minister": ["ဦးခင်မောင်ရီ"],
        "deputy_ministers": ["ဦးခင်လတ်", "ဒေါက်တာ ခိုင်ခိုင်စိုး"],
    },
    {
        "name": "နိုင်ငံတော်သမ္မတရုံးဝန်ကြီးဌာန",
        "union_minister": ["ဦးတင်အောင်စန်း"],
        "deputy_ministers": ["ဦးထင်ကျော်သူ"],
    },
    {
        "name": "ပို့ဆောင်ရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးမြထွန်းဦး"],
        "deputy_ministers": ["ဦးအောင်မြိုင်", "ဦးထွန်းလူ"],
    },
    {
        "name": "ဒီဂျစ်တယ်ဖွံ့ဖြိုးတိုးတက်ရေးနှင့် ဆက်သွယ်ရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးမြထွန်းဦး"],
        "deputy_ministers": ["ဦးမင်းဇေယျာလှိုင်", "ဦးသက်ဝင်းအောင်"],
    },
    {
        "name": "ကာကွယ်ရေးဝန်ကြီးဌာန",
        "union_minister": ["ဗိုလ်ချုပ်ကြီး ရာပြည့်"],
        "deputy_ministers": ["ဗိုလ်ချုပ် အောင်မျိုးသန့်"],
    },
    {
        "name": "ပြည်ထဲရေးဝန်ကြီးဌာန",
        "union_minister": ["ဗိုလ်ချုပ်ကြီး ကိုကိုဦး"],
        "deputy_ministers": ["ဗိုလ်ချုပ် မင်းသူ"],
    },
    {
        "name": "နိုင်ငံခြားရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးတင်မောင်ဆွေ"],
        "deputy_ministers": ["ဦးနိုင်မင်းကျော်", "ဦးကိုကိုကျော်"],
    },
    {
        "name": "အမျိုးသားစီမံကိန်း၊ ရင်းနှီးမြှုပ်နှံမှုနှင့် ဘဏ္ဍာရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးအောင်ကျော်ဟိုး"],
        "deputy_ministers": ["ဦးဟန်ဝင်းအောင်", "ဦးသန့်စင်လွင်"],
    },
    {
        "name": "ဘဏ္ဍာရေးနှင့်အခွန်ဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ ကံဇော်"],
        "deputy_ministers": ["ဦးကျော်ထင်", "ဒေါ်သန်းသန်းလင်း"],
    },
    {
        "name": "နယ်စပ်ရေးရာဝန်ကြီးဌာန",
        "union_minister": ["ဒုတိယဗိုလ်ချုပ်ကြီး ဖုန်းမြတ်"],
        "deputy_ministers": ["ဗိုလ်ချုပ် ကျော်စွာဦး"],
    },
    {
        "name": "တိုင်းရင်းသားလူမျိုးများရေးရာဝန်ကြီးဌာန",
        "union_minister": ["ဦးသန်းမောင်"],
        "deputy_ministers": ["ဦးစိုင်းထွန်းညို"],
    },
    {
        "name": "ဥပဒေရေးရာဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ သီတာဦး"],
        "deputy_ministers": ["ဒေါက်တာ ထိန်လင်းဦး"],
    },
    {
        "name": "ပညာရေးဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ ချောချောစိန်"],
        "deputy_ministers": ["ဦးနေမျိုးလှိုင်"],
    },
    {
        "name": "သိပ္ပံနှင့်နည်းပညာဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ မျိုးသိန်းကျော်"],
        "deputy_ministers": ["ဒေါက်တာ နေခြည်လဲ့လဲ့သိန်း"],
    },
    {
        "name": "ကျန်းမာရေးဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ စိုးဝင်း"],
        "deputy_ministers": ["ဒေါက်တာ တင်ထွန်း"],
    },
    {
        "name": "အမျိုးသမီးရေးရာဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ သက်သက်ဇင်"],
        "deputy_ministers": ["ဒေါက်တာနေသွယ်ကြည်"],
    },
    {
        "name": "ပြန်ကြားရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးထိန်လင်း"],
        "deputy_ministers": ["ဦးရဲတင့်"],
    },
    {
        "name": "သာသနာရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးတင်ဦးလွင်"],
        "deputy_ministers": ["ဦးလင်းအောင်"],
    },
    {
        "name": "စိုက်ပျိုးရေး၊ မွေးမြူရေးနှင့် ဆည်မြောင်းဝန်ကြီးဌာန",
        "union_minister": ["ဦးမင်းနောင်"],
        "deputy_ministers": ["ဦးဗိုလ်ဗိုလ်ကျော်", "ဒေါက်တာ ရဲထွန်းဝင်း", "ဒေါက်တာ ရဲတင့်ထွန်း"],
    },
    {
        "name": "သမဝါယမနှင့်ကျေးလက်ဖွံ့ဖြိုးရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးမျိုးဇော်သိမ်း"],
        "deputy_ministers": ["ဦးသိုက်စိုး"],
    },
    {
        "name": "သယံဇာတနှင့်သဘာဝပတ်ဝန်းကျင်ထိန်းသိမ်းရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးဆန်းဦး"],
        "deputy_ministers": ["ဦးခင်လတ်ကြီး", "ဒေါက်တာ သောင်းနိုင်ဦး"],
    },
    {
        "name": "လျှပ်စစ်နှင့်စွမ်းအင်ဝန်ကြီးဌာန",
        "union_minister": ["ဦးကိုကိုလွင်"],
        "deputy_ministers": ["ဦးအေးကျော်", "ဦးကျော်နိုင်ဝင်း"],
    },
    {
        "name": "စက်မှုနှင့် အသေးစား၊ အငယ်စား၊ အလတ်စား စီးပွားရေးလုပ်ငန်းများ ဖွံ့ဖြိုးတိုးတက်ရေးဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ ချာလီသန်း"],
        "deputy_ministers": ["ဦးသွင်အောင်", "ဒေါက်တာ အောင်ဇေယျ"],
    },
    {
        "name": "လူဝင်မှုကြီးကြပ်ရေးနှင့်ပြည်သူ့အင်အားဝန်ကြီးဌာန",
        "union_minister": ["ဦးမြင့်ကြိုင်"],
        "deputy_ministers": ["ဦးလင်းဇော်ထွန်း", "ဦးရဲထွန်းဦး"],
    },
    {
        "name": "အလုပ်သမားဝန်ကြီးဌာန",
        "union_minister": ["ဦးမောင်မြင့်"],
        "deputy_ministers": ["ဦးမျိုးအောင်"],
    },
    {
        "name": "စီးပွားရေးနှင့်ကူးသန်းရောင်းဝယ်ရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးထွန်းအုံ"],
        "deputy_ministers": ["ဦးမင်းမင်း", "ဦးဝင်းမြင့်ခိုင်"],
    },
    {
        "name": "အားကစားရေးရာဝန်ကြီးဌာန",
        "union_minister": ["ဦးရဲမြင့်ထွန်း"],
        "deputy_ministers": ["ဦးမျိုးကျော်သူ"],
    },
    {
        "name": "လူငယ်ရေးရာဝန်ကြီးဌာန",
        "union_minister": ["ဒေါက်တာ မောင်သင်း"],
        "deputy_ministers": ["ဦးစစ်နိုင်"],
    },
    {
        "name": "ဆောက်လုပ်ရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးမျိုးသန့်"],
        "deputy_ministers": ["ဦးမျိုးမြင့်", "ဒေါက်တာသောင်းနိုင်"],
    },
    {
        "name": "လူမှုဝန်ထမ်း၊ ကယ်ဆယ်ရေးနှင့် ပြန်လည်နေရာချထားရေးဝန်ကြီးဌာန",
        "union_minister": [],
        "deputy_ministers": ["ဒေါက်တာ သန်းစိုး", "ဒေါက်တာ သန့်ဇော်လွင်"],
    },
    {
        "name": "ယဉ်ကျေးမှု၊ ဟိုတယ်နှင့်ခရီးသွားလာရေးဝန်ကြီးဌာန",
        "union_minister": ["ဦးခင်မောင်စိုး"],
        "deputy_ministers": ["ဦးအေးထွန်း", "ဦးဖြိုးဇော်စိုး"],
    },
]


def _key(s: str) -> str:
    """Consonant skeleton of a Burmese string — base consonants only."""
    return "".join(
        ch for ch in (s or "")
        if "\u1000" <= ch <= "\u1021" or ch.isascii() and ch.isalnum()
    )


def _matches(asked: str, name: str) -> bool:
    """True when the asked string names this ministry, ignoring spaces."""
    squash = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    a, t = squash(asked), squash(name)
    if a and t and (a in t or t in a):
        return True
    ka, kt = _key(asked), _key(name)
    return bool(ka) and bool(kt) and (ka in kt or kt in ka)


def _fmt_names(names: list[str]) -> str:
    if not names:
        return "မရှိပါ"
    if len(names) == 1:
        return names[0]
    return "၊ ".join(names[:-1]) + " နှင့် " + names[-1]


def moi_ministries(parameters: dict = None, **_) -> str:
    """Answer who runs a named union ministry. Offline, from local data.

    The signature is `(parameters, ...)` because core/action_loader.py calls
    a handler as `fn(parameters=parameters, ...)` — a handler that swallows
    the dict in `**_` runs on defaults.
    """
    p = parameters or {}
    asked = str(p.get("name") or p.get("ministry") or p.get("query") or "").strip()
    if not asked:
        return "ဘယ်ဝန်ကြီးဌာနလဲ ပြောပါ — ဥပမာ ဆောက်လုပ်ရေးဝန်ကြီးဌာန ဝန်ကြီး နာမည် ပြောပါ။"

    # ၁။ ပုဂ္ဂိုလ်အမည်ဖြင့် ရှာဖွေမေးမြန်းမှု (Person reverse search)
    person_hits: list[str] = []
    tokens = [t for t in re.split(r"\s+", asked) if t]
    for m in _MINISTRIES:
        # ပြည်ထောင်စုဝန်ကြီး အမည် တိုက်စစ်ခြင်း
        for minister in m["union_minister"]:
            if _matches(asked, minister) or any(_matches(t, minister) for t in tokens if len(_key(t)) >= 4):
                person_hits.append(f"• **{minister}** — ပြည်ထောင်စုဝန်ကြီး ({m['name']})")
        # ဒုတိယဝန်ကြီး အမည် တိုက်စစ်ခြင်း
        for deputy in m["deputy_ministers"]:
            if _matches(asked, deputy) or any(_matches(t, deputy) for t in tokens if len(_key(t)) >= 4):
                person_hits.append(f"• **{deputy}** — ဒုတိယဝန်ကြီး ({m['name']})")

    if person_hits:
        return "\n".join(person_hits).strip()

    # ၂။ ဝန်ကြီးဌာန အမည်ဖြင့် ရှာဖွေခြင်း
    hits = [m for m in _MINISTRIES if _matches(asked, m["name"])]
    if not hits:
        return (f"⚠️ '{asked}' နှင့် ကိုက်ညီသော ဝန်ကြီးဌာန သို့မဟုတ် ပုဂ္ဂိုလ် စာရင်းထဲ မတွေ့ပါ။ "
                f"ဝန်ကြီးဌာန သို့မဟုတ် ပုဂ္ဂိုလ်အမည် အတိအကျဖြင့် မေးပါ။")

    out: list[str] = []
    for m in hits[:3]:
        out.append(
            f"**{m['name']}**\n"
            f"• ပြည်ထောင်စုဝန်ကြီး: {_fmt_names(m['union_minister'])}\n"
            f"• ဒုတိယဝန်ကြီး: {_fmt_names(m['deputy_ministers'])}"
        )
    return "\n\n".join(out).strip()


TOOL = {
    "name": "moi_ministries",
    "description": (
        "Answer who runs one of the union ministries of Myanmar by its "
        "Burmese name or person name — the union minister and the deputy ministers. Use when "
        "the user names a ministry and asks for the minister (e.g. 'ဆောက်လုပ်ရေးဝန်ကြီးဌာန ဝန်ကြီးနဲ့ ဒုတိယဝန်ကြီး'), "
        "or asks about a person's ministerial post (e.g. 'ဒေါက်တာ ချောချောစိန် ဘာဝန်ကြီးလဲ'). "
        "Offline, from a local list; no website fetch. Not for news or "
        "documents (moi_news / moi_documents)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": "The ministry or person name asked about, in Burmese.",
            },
        },
        "required": ["name"],
    },
    "handler": moi_ministries,
}