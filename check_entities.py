"""Isolated checks for core/entities.py — no network, no Supabase.

Why this file exists: `check_agent.py` mixes these assertions in with live
Supabase calls and takes ~2.5 minutes because of them. When the entity
extractor was being fixed the network portion drowned the signal, and one
real regression (a mangled honorific splitting one person into two) nearly
shipped because the run was too slow to iterate on. This file keeps the
pure-text checks separate and fast.

Run: python check_entities.py
"""
import sys
import time

from core import entities as E

_fails = []
_passes = 0


def ok(label: str, got, want) -> None:
    global _passes
    if got == want:
        _passes += 1
        print(f"  OK    {label}")
    else:
        _fails.append(label)
        print(f"  FAIL  {label}  got {got!r} want {want!r}")


def _art(body: str, paper: str = "ကြေးမုံ", page: int = 1) -> dict:
    return {"body_text": body, "summary": body,
            "newspaper_name": paper, "page_no": page}


print("\n── One person, two offices ──")
# The same official, two titles, in one article. He is ONE person.
TWO_TITLES = _art(
    "ပြည်ထောင်စုဝန်ကြီး ဦးတင်ဦးလွင်သည် ယနေ့ နေပြည်တော်တွင် "
    "ဒုတိယဝန်ကြီး ဦးတင်ဦးလွင် နှင့် တွေ့ဆုံခဲ့သည်။"
)
ppl = E.people_in([TWO_TITLES])
ok("one person two titles = 1", len(ppl), 1)
if ppl:
    ok("both titles kept", sorted(ppl[0]["titles"]),
       sorted(["ပြည်ထောင်စုဝန်ကြီး", "ဒုတိယဝန်ကြီး"]))
    ok("honorific stays", ppl[0]["honorific"], "ဦး")
    ok("strongest title reported", ppl[0]["title"], "ပြည်ထောင်စုဝန်ကြီး")

print("\n── A plain name with an honorific ──")
# `name` is the BARE name and `honorific` is separate — the action layer rejoins
# them as f"{honorific}{name}" when it speaks. Assert the contract the rest of
# the code actually depends on, not a joined string nothing produces.
one = E.find_titled_people("ဝန်ကြီး ဦးအေးကျော် သည် ရန်ကုန်သို့ သွားသည်။")
ok("simple name found", len(one), 1)
if one:
    ok("bare name", one[0]["name"], "အေးကျော်")
    ok("simple honorific", one[0]["honorific"], "ဦး")
    ok("as spoken", one[0]["honorific"] + one[0]["name"], "ဦးအေးကျော်")
    ok("simple title", one[0]["title"], "ဝန်ကြီး")

print("\n── The mangled honorific ──")
# Measured 2026-09-30: the OCR of one edition rendered ဒေါက်တာ as ဒေက်တာ in
# part of the paper and correctly in another. Keyed on the raw string the same
# person was listed twice, and a user asking "how many ministers" would count
# two. The extractor repairs the prefix and keys on the normalised form.
MANGLE = [
    _art("ပြည်ထောင်စုဝန်ကြီး ဒေါက်တာအေးထွန်း သည် နေပြည်တော်တွင် ရှိသည်။"),
    _art("ပြည်ထောင်စုဝန်ကြီး ဒေက်တာအေးထွန်း သည် မန္တလေးသို့ သွားသည်။"),
]
mp = E.people_in(MANGLE)
ok("mangled honorific normalised", len(mp), 1)
if mp:
    ok("normalised honorific", mp[0]["honorific"], "ဒေါက်တာ")
    ok("merged count", mp[0]["count"], 2)

print("\n── Nothing that is not a person ──")
NEG = [
    ("ministry not a person",
     "စိုက်ပျိုးရေးဝန်ကြီးဌာန မှ ထုတ်ပြန်သည်။", 0),
    ("delegation not a person",
     "ဝန်ကြီး နှင့်အဖွဲ့ နေပြည်တော်သို့ ရောက်သည်။", 0),
    ("plural not a person",
     "ဝန်ကြီး များ က အစည်းအဝေး တက်သည်။", 0),
    ("no title no person",
     "ဦးအေးကျော် သည် ရန်ကုန်သို့ သွားသည်။", 0),
]
for label, body, want in NEG:
    ok(label, len(E.find_titled_people(body)), want)

print("\n── Ministries ──")
# The glossary holds the paper's full official spellings, not short forms:
# matching a fixed list is what stops the extractor inventing a ministry that
# does not exist. So this text must use a spelling the paper actually prints.
MIN = ("ဌာနနှစ်ခုဖြစ်သော စိုက်ပျိုးရေး၊ မွေးမြူရေးနှင့် ဆည်မြောင်းဝန်ကြီးဌာန "
       "နှင့် ပညာရေးဝန်ကြီးဌာန တို့မှ")
found = E.ministries_in(MIN)
ok("two ministries found", len(found), 2)
ok("agriculture present", any("စိုက်ပျိုးရေး" in m for m in found), True)
ok("education present", any("ပညာရေး" in m for m in found), True)

# A short form that is NOT in the glossary must not be reported. This is the
# guard against inventing a ministry, and it is why the test above uses the
# full spelling.
ok("short form not in glossary is not invented",
   E.ministries_in("စိုက်ပျိုးရေးဝန်ကြီးဌာန မှ ထုတ်ပြန်သည်။"), [])

# **Whitespace variant**: the paper writes `ဘဏ္ဍာရေး နှင့်` (space after ရေး)
# while the glossary holds `ဘဏ္ဍာရေးနှင့်`. Measured 2026-09-30: a raw
# substring lookup dropped this and 9 other mentions — 28% of the edition's
# ministry references — so the lookup now compares whitespace-free forms.
ok("space inside the name still matched",
   E.ministries_in("အဆိုနှင့်စပ်လျဉ်း၍ ဘဏ္ဍာရေး နှင့် အခွန်ဝန်ကြီးဌာန"),
   ["ဘဏ္ဍာရေးနှင့် အခွန်ဝန်ကြီးဌာန"])

# Two spellings of one ministry must tally as one, not two.
SPACED = "ဘဏ္ဍာရေး နှင့် အခွန်ဝန်ကြီးဌာန နှင့် ဘဏ္ဍာရေးနှင့် အခွန်ဝန်ကြီးဌာန တို့"
m2 = E.ministries_across([_art(SPACED), _art(SPACED)])
ok("two spellings collapse to one ministry", len(m2), 1)
if m2:
    ok("collapsed tally = 2", m2[0]["count"], 2)

# A ministry that does not exist must never be invented.
ok("unknown ministry not invented",
   E.ministries_in("စိတ်ကူးယဉ်ဝန်ကြီးဌာန မှ ထုတ်ပြန်သည်။"), [])

print("\n── Titles that contain other titles ──")
# `ပြည်ထောင်စုဝန်ကြီး` has `ဝန်ကြီး` inside it. Measured 2026-09-30: reading
# the short form out of the long one tallied one official three times and
# inflated `count`, the sort key for "most mentioned".
T = E.find_titled_people("ပြည်ထောင်စုဝန်ကြီး ဦးတင်ဦးလွင် ရောက်သည်။")
ok("nested short title not read out of long", [h["title"] for h in T],
   ["ပြည်ထောင်စုဝန်ကြီး"])
ok("spaced long form collapses",
   [h["title"] for h in E.find_titled_people("ပြည်ထောင်စု ဝန်ကြီး ဦးအောင် ရောက်သည်။")],
   ["ပြည်ထောင်စုဝန်ကြီး"])
ok("deputy not read as minister",
   [h["title"] for h in E.find_titled_people("ဒုတိယဝန်ကြီး ဦးအောင် ရောက်သည်။")],
   ["ဒုတိယဝန်ကြီး"])
ok("ministry yields no person",
   E.find_titled_people("ပြန်ကြားရေးဝန်ကြီးဌာန မှ ထုတ်ပြန်သည်။"), [])
ok("prime minister still read",
   [h["title"] for h in E.find_titled_people("ဝန်ကြီးချုပ် ဦးမြင့်ဆွေ ရောက်သည်။")],
   ["ဝန်ကြီးချုပ်"])

print("\n── The two state offices ──")
# Measured 2026-09-30: the owner asked *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာမှာ နိုင်ငံတော်သမ္မတ၊
# ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့ သတင်းတွေ ရှိလား"* and this module returned `[]` for the
# president and both vice-presidents — only ministerial ranks were known, while
# `နိုင်ငံတော်သမ္မတ` occurs 139 times in the September database and
# `ဒုတိယသမ္မတ` 27. The names below are the real ones from those editions.
PRES = E.find_titled_people("နိုင်ငံတော်သမ္မတ ဦးမင်းအောင်လှိုင် သည် ရန်ကုန်သို့ ရောက်သည်။")
ok("president read", [h["title"] for h in PRES], ["နိုင်ငံတော်သမ္မတ"])
ok("president name", PRES[0]["name"] if PRES else "", "မင်းအောင်လှိုင်")
VP = E.find_titled_people("ဒုတိယသမ္မတ ဦးညိုစော၊ ပြည်ထောင်စုဝန်ကြီးများ တက်ရောက်ကြသည်။")
ok("vice-president read", [h["title"] for h in VP], ["ဒုတိယသမ္မတ"])
ok("vice-president name", VP[0]["name"] if VP else "", "ညိုစော")
ok("second vice-president read",
   [h["name"] for h in E.find_titled_people(
       "ဒုတိယသမ္မတ ဒေါ်နန်းနီနီအေးနှင့် အဖွဲ့သည် ရောက်ရှိကြသည်။")],
   ["နန်းနီနီအေး"])
# A vice-president is not the president. Without the guard the bare `သမ္မတ`
# entry read him out of his own rank, so one person was reported twice, once as
# the head of state.
ok("vice-president not also read as president",
   [h["title"] for h in E.find_titled_people("ဒုတိယသမ္မတ ဦးညိုစော ရောက်သည်။")],
   ["ဒုတိယသမ္မတ"])
# `သမ္မတနိုင်ငံ` is "republic", the trap `ဝန်ကြီးဌာန` plays for `ဝန်ကြီး`.
ok("republic yields no person",
   E.find_titled_people("တရုတ်ပြည်သူ့သမ္မတနိုင်ငံသံရုံးမှ ထုတ်ပြန်သည်။"), [])
# The President's Office is a body, not `title + name`.
ok("president's office yields no person",
   E.find_titled_people("နိုင်ငံတော်သမ္မတရုံးတော်၌ အစည်းအဝေး ကျင်းပသည်။"), [])
# A foreign head of state is not Myanmar's. The papers print both.
ok("foreign president not attributed",
   E.find_titled_people("အမေရိကန်သမ္မတ ဒေါ်နယ်ထရမ့်က ပြောသည်။"), [])
# …and a country named right after the rank is not a person's name.
ok("country after the rank is not a name",
   E.find_titled_people("နိုင်ငံတော်သမ္မတ ဗီယက်နမ်နှင့် ကမ္ဘောဒီးယားနိုင်ငံ ခရီးစဉ်"), [])
# Prose about the office, with no name in it.
ok("president's instruction is not a name",
   E.find_titled_people("နိုင်ငံတော်သမ္မတ လမ်းညွှန်ခဲ့သည့် အခြေခံသဘောတရားဖြင့်"), [])
# Both offices in one question — measured: "…နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ (၂) ဦး…"
# is one question about two offices and one `rank` cannot hold both.
TWO_OFFICE = [
    _art("နိုင်ငံတော်သမ္မတ ဦးမင်းအောင်လှိုင် ရောက်သည်။"),
    _art("ဒုတိယသမ္မတ ဦးညိုစော ရောက်သည်။"),
    _art("ဒုတိယသမ္မတ ဒေါ်နန်းနီနီအေး ရောက်သည်။"),
    _art("ပြည်ထောင်စုဝန်ကြီး ဦးတင်ဦးလွင် ရောက်သည်။"),
]
ok("one office returns only that office",
   len(E.people_in(TWO_OFFICE, 20, rank="နိုင်ငံတော်သမ္မတ")), 1)
ok("two offices are both answered",
   len(E.people_in(TWO_OFFICE, 20,
                   rank="နိုင်ငံတော်သမ္မတ,ဒုတိယသမ္မတ")), 3)
# Sorted by count desc then name — all three are mentioned once here, so the
# order is the name order and the minister must not be in it at all.
ok("two offices still exclude the minister",
   sorted(p["name"] for p in E.people_in(
       TWO_OFFICE, 20, rank="နိုင်ငံတော်သမ္မတ,ဒုတိယသမ္မတ")),
   sorted(["ညိုစော", "မင်းအောင်လှိုင်", "နန်းနီနီအေး"]))
ok("a list rank works the same as a comma string",
   len(E.people_in(TWO_OFFICE, 20,
                   rank=["နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ"])), 3)
# The pipeline mangles a personal name the way it mangles an honorific.
# Measured 2026-09-30: the vice-president born `ဦးညိုစော` also appears as
# `ဦးညိမ်းဇော်` and `ဦးညိမ်းစော`, always in the `ဒုတိယသမ္မတ` slot; and once as
# `ဒေါ်နန်း` alone, where a line break split `ဒေါ်နန်းနီနီအေး`.
NAME_VARIANTS = [
    _art("ဒုတိယသမ္မတ ဦးညိုစော ရောက်သည်။"),
    _art("ဒုတိယသမ္မတ ဦးညိမ်းဇော် ရောက်သည်။"),
    _art("ဒုတိယသမ္မတ ဦးညိမ်းစော ရောက်သည်။"),
    _art("ဒုတိယသမ္မတ ဒေါ်နန်းနီနီအေး ရောက်သည်။"),
    _art("ဒုတိယသမ္မတ ဒေါ်နန်း နီနီအေး ရောက်သည်။"),
]
ok("three spellings of one person merge to one",
   len(E.people_in(NAME_VARIANTS, 20, rank="ဒုတိယသမ္မတ")), 2)
ok("…under the correct spelling",
   E.people_in(NAME_VARIANTS, 20,
               rank="ဒုတိယသမ္မတ")[0]["name"], "ညိုစော")
ok("…with all three mentions counted",
   E.people_in(NAME_VARIANTS, 20,
               rank="ဒုတိယသမ္မတ")[0]["count"], 3)
# A bare `သမ္မတ` must not be read as the president. Removed from `_TITLES`
# after a survey: every bare occurrence was `…သမ္မတနိုင်ငံ` (“republic”), a
# foreign head of state, or a vocative.
ok("a foreign president is not Myanmar's",
   E.find_titled_people("အမေရိကန်သမ္မတ ဒေါ်နယ်ထရမ့်က ပြောသည်။"), [])
ok("…nor is one with no country word at all",
   E.find_titled_people("သမ္မတ ပရာဘိုဝို ဆူဘီရန်တိုက ချမှတ်သည်။"), [])
ok("…but the long form still reads",
   [h["name"] for h in E.find_titled_people(
       "နိုင်ငံတော်သမ္မတ ဦးမင်းအောင်လှိုင် ရောက်သည်။")],
   ["မင်းအောင်လှိုင်"])

print("\n── Rank filtering — asking about one office ──")
# Measured 2026-09-30: "ပြည်ထောင်စုဝန်ကြီး ဘယ်သူတွေရဲ့ သတင်းပါလဲ" was answered
# with 12 names spanning three offices. A journalist asking about *union*
# ministers and receiving chief ministers and deputies has a different answer.
RANK_ARTS = [
    _art("ပြည်ထောင်စုဝန်ကြီး ဦးတင်ဦးလွင် ရောက်သည်။"),
    _art("ပြည်ထောင်စုဝန်ကြီး ဒေါက်တာစိုးဝင်း ရောက်သည်။"),
    _art("ဒုတိယဝန်ကြီး ဒေါက်တာအေးထွန်း ရောက်သည်။"),
    _art("ဒုတိယဝန်ကြီး ဦးမျိုးမြင့် ရောက်သည်။"),
    _art("ဝန်ကြီးချုပ် ဦးဇော်နိုင်ဦး ရောက်သည်။"),
]
ok("no rank given returns everyone", len(E.people_in(RANK_ARTS, 20)), 5)
ok("asking for union ministers returns only them",
   len(E.people_in(RANK_ARTS, 20, rank="ပြည်ထောင်စုဝန်ကြီး")), 2)
ok("asking for deputies returns only them",
   len(E.people_in(RANK_ARTS, 20, rank="ဒုတိယဝန်ကြီး")), 2)
ok("asking for chief ministers returns only them",
   len(E.people_in(RANK_ARTS, 20, rank="ဝန်ကြီးချုပ်")), 1)
# A rank nobody carries must be empty, not the whole list.
ok("asking for a rank nobody carries returns nothing",
   E.people_in(RANK_ARTS, 20, rank="ဘယ်သူမှမဟုတ်"), [])
# The filter matches on every title SEEN, not the reported one: this official
# is named both ways in one edition, so either question must find him.
BOTH = [_art("ဝန်ကြီးချုပ် ဦးအေးကျော် ရောက်သည်။ ဒုတိယဝန်ကြီး ဦးအေးကျော် ပြောသည်။")]
ok("a person named with two offices is found by either",
   len(E.people_in(BOTH, 20, rank="ဒုတိယဝန်ကြီး")), 1)
ok("…and by the other one too",
   len(E.people_in(BOTH, 20, rank="ဝန်ကြီးချုပ်")), 1)

print("\n── OCR-glued prose must not become a person ──")
# The pipeline glues a whole phrase into one un-spaced run, so guards written
# for a word with spaces around it never fire. Measured 2026-09-30 against the
# real 2026-09-30 ကြေးမုံ edition, on the owner's own question — each of these
# produced a "person" in his answer before the un-spaced forms were refused.
GLUED = [
    # 145 characters, no space: "…the Union Minister-led National Unity and
    # Peace Implementation Central Committee". Read as a person called
    # `ဦးဆောင်သည့်အမျိုးသားစည်းလုံးညီညွတ်ရေးနှင့်`.
    "ပြည်ထောင်စုဝန်ကြီး ဦးဆောင်သည့် အမျိုးသားစည်းလုံးညီညွတ်ရေးနှင့် "
    "ငြိမ်းချမ်းရေးဖော်ဆောင်မှု ဗဟိုကော်မတီ ကျင်းပသည်။",
    # "…the substitution and appointment of a union minister".
    "နိုင်ငံတော်သမတထံ မှ ပေးပို့ထားသော ပြည်ထောင်စု ဝန်ကြီး "
    "အစားထိုးခန့်အပ်ခြင်းနှင့် ဥပဒေကဲ့သို့ အာဏာတည်သော အမိန့် ဖတ်သည်။",
]
for _g in GLUED:
    ok(f"no person from glued prose: {_g[:14]}…",
       E.find_titled_people(_g), [])

print("\n── 'former' qualifies a rank, it is not a name ──")
# `မေလးရှားဝန်ကြီးချုပ်ဟောင်း` — "former Malaysian prime minister". The rank
# word is glued to the front, so the name regex saw only `ဟောင်း` and the
# owner's answer listed a prime minister by that name.
FORMER = _art("မေလးရှားဝန်ကြီးချုပ်ဟောင်း မဟာသီယာမိုဟာမက် ကွယ်လွန်သည်။")
_former = E.people_in([FORMER])
ok("'former X' yields no person called ဟောင်း",
   [p["name"] for p in _former if p["name"] == "ဟောင်း"], [])

print("\n── A space between honorific and name ──")
# The paper writes `ပြည်ထောင်စုဝန်ကြီး ဒေါက်တာ မောင်သင်းနှင့်`. The walk cut at
# the first whitespace, leaving the bare honorific `ဒေါက်တာ`, which
# `_is_name_shape` refuses — so the minister was MISSING from the answer.
# Measured 2026-09-30 on the owner's own ကြေးမုံ question: `ဒေါက်တာ မောင်သင်း`
# (page 7) is named as a union minister six times and was never listed.
_SPACED = _art("ပြည်ထောင်စုဝန်ကြီး ဒေါက်တာ မောင်သင်းနှင့် "
               "နေပြည်တော်ကောင်စီဥက္ကဋ္ဌ ဦးကံမြင့်သန်းတို့က အမှာစကား ပြောကြားသည်။")
_spaced = E.people_in([_SPACED])
ok("an honorific with a space before the name still reads",
   [(p["honorific"], p["name"]) for p in _spaced], [("ဒေါက်တာ", "မောင်သင်း")])
# The join must be the *honorific* that licenses it, not a general "names may
# contain spaces" rule: a spaced rank word must not fuse to the next word.
ok("…and the join does not fuse a rank to the word after it",
   E.find_titled_people("ပြည်ထောင်စုဝန်ကြီး သည် ယနေ့ ရောက်သည်။"), [])

print("\n── Ordering ──")
MANY = [_art("ဝန်ကြီး ဦးအေးကျော် ရောက်သည်။") for _ in range(3)]
MANY.append(_art("ဝန်ကြီး ဦးတင်ဦးလွင် ရောက်သည်။"))
ranked = E.people_in(MANY)
ok("most mentioned first", ranked[0]["name"] if ranked else "", "အေးကျော်")
ok("most mentioned count", ranked[0]["count"] if ranked else 0, 3)

print("\n── A rank followed by grammar is not a person ──")
# Measured 2026-10-01 over the whole corpus (6,896 readable articles, 150
# distinct extracted names) after the owner's vice-president question came back
# naming a person called `ထံမှ`. All four of these were listed as people.
_GRAMMAR = {
    # "appointed as a union minister **from** the State President"
    "ထံမှ": "နိုင်ငံတော်သမ္မတ ထံမှ ပြည်ထောင်စု ဝန်ကြီးအဖြစ် ခန့်အပ်လိုကြောင်း တင်ပြသည်။",
    # "the **wife of** the state chief minister"
    "၏ဇနီး": "ပြည်နယ်ဝန်ကြီးချုပ်၏ဇနီးက ချင်း ပြည်နယ်တရားလွှတ်တော် တရားသူကြီးအား ခန့်အပ်သည်။",
    # "**deputy-minister level**, fifth meeting"
    "အဆင့်": "ဒုတိယဝန်ကြီးအဆင့် ပဉ္စမအကြိမ် ညှိနှိုင်းအစည်းအဝေးသို့ တက်ရောက်သည်။",
}
for bad, sentence in _GRAMMAR.items():
    names = [h["name"] for h in E.find_titled_people(sentence)]
    ok(f"'{bad}' is not reported as a person", bad in names, False)

# …and the fourth is a **rank, not a name** — but refusing it alone would drop a
# real minister, so `ဗိုလ်မှူးကြီး` anchors as a title instead. Measured:
# `လုံခြုံရေးနှင့်နယ်စပ်ရေးရာဝန်ကြီး ဗိုလ်မှူးကြီး ညီလန်းချိုက` — the Bago
# minister, **Colonel** Nyi Lan Cho.
_COLONEL = _art("လုံခြုံရေးနှင့်နယ်စပ်ရေးရာဝန်ကြီး ဗိုလ်မှူးကြီး ညီလန်းချိုက "
                "အမှာစကား ပြောကြားသည်။")
_col = [(h["title"], h["name"]) for h in E.find_titled_people(_COLONEL["body_text"])]
ok("a military rank anchors the name after it, and is not itself a person",
   ("ဗိုလ်မှူးကြီး", "ညီလန်းချို") in _col, True)
ok("…and no person is called by the rank",
   [n for _t, n in _col if n == "ဗိုလ်မှူးကြီး"], [])

print(f"\n{'=' * 60}")
print(f"  {_passes} passed, {len(_fails)} failed")
if _fails:
    for f in _fails:
        print(f"    - {f}")
print(f"{'=' * 60}\n")
sys.exit(1 if _fails else 0)
