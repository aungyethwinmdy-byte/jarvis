"""Checks for the section index (ကဏ္ဍ) — offline, plus `--live` for the database.

Run:  python check_sections.py           (offline, no network, <1s)
      python check_sections.py --live    (also reads the database)

WHY EVERY CHECK HERE EXISTS

    Each one is a defect that was **measured**, not imagined. The three that
    matter most:

    1. `resolve_section("ဒုတိယသမ္မတ")` returned `နိုင်ငံတော်သမ္မတ` in the first
       version — `သမ္မတ` is a substring of `ဒုတိယသမ္မတ`, so the shorter alias
       matched first. A question about a vice-president would have been answered
       from the president's section.
    2. An unknown section name must return `""`, never fall back to
       "everything". The prices side of this project already paid for that bug
       (`kind="rice"` → the filter was dropped → a rice-price question answered
       with fire-balloon festival dates).
    3. A single passing mention of an office is not a story about the office.
       Measured over 6,722 readable articles: `နိုင်ငံတော်သမ္မတ` is in 72
       headlines but 140 bodies, so counting any mention nearly doubles the
       section and files education and transport stories under the President.
"""
from __future__ import annotations

import sys

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, wanted {want!r}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}"
          + ("" if ok else f"   got {got!r}, wanted {want!r}"))


def _head(title: str) -> None:
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def main() -> int:
    import main as M
    from core import news_sections as ns
    from actions import news_section as nsec

    _head("The eleven sections the owner asked for, and the other bucket")
    owner = ("နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတများ", "ပြည်ထောင်စုဝန်ကြီးများ",
             "ဆောင်းပါး", "နိုင်ငံရေး", "စီးပွားရေး", "လူမှုရေး", "ပညာရေး",
             "ကျန်းမာရေး", "သဘာဝဘေး", "အယ်ဒီတာအာဘော်")
    for label in owner:
        check(f"'{label}' is a section", label in ns.LABELS, True)
    check("the eleven are exactly the owner's list",
          tuple(l for _s, l in ns.SECTIONS), owner)
    # The paper contains sport, religion, advertisements and announcements, and
    # the owner's eleven do not cover them. A story forced into the nearest
    # section is a wrong index entry, so an "other" bucket has to exist.
    check("there is an 'other' bucket", ns.OTHER in ns.LABELS, True)
    check("'other' is not one of the eleven", ns.OTHER in owner, False)

    _head("resolve_section — what the user says becomes a stored label")
    for _slug, label in ns.SECTIONS:
        check(f"the exact label '{label}' resolves to itself",
              ns.resolve_section(label), label)
    # THE BUG. `သမ္မတ` is inside `ဒုတိယသမ္မတ`; the shorter alias was listed
    # first and won, so asking about a vice-president read the president.
    check("'ဒုဋိယသမ္မတ' resolves to the VICE-president, not the president",
          ns.resolve_section("ဒုတိယသမ္မတ"), "ဒုတိယသမ္မတများ")
    check("'ဒုတိယသမ္မတများ' resolves to the vice-presidents",
          ns.resolve_section("ဒုတိယသမ္မတများ"), "ဒုတိယသမ္မတများ")
    check("a bare 'သမ္မတ' is the president",
          ns.resolve_section("သမ္မတ"), "နိုင်ငံတော်သမ္မတ")
    check("'ဝန်ကြီး' is the union ministers",
          ns.resolve_section("ဝန်ကြီး"), "ပြည်ထောင်စုဝန်ကြီးများ")
    check("the whole question still resolves",
          ns.resolve_section("ဒီနေ့ စီးပွားရေး သတင်း ဘာရှိလဲ"), "စီးပွားရေး")
    check("'အာဘော်' alone is the editorial",
          ns.resolve_section("အာဘော်"), "အယ်ဒီတာအာဘော်")

    # An unknown section must NOT degrade to "everything" — see the docstring.
    for bad in ("အားကစား", "sports", "ကြော်ငြာ", "ဘာမှမဟုတ်"):
        check(f"'{bad}' is not a section", ns.resolve_section(bad), "")
    check("an empty name is not a section", ns.resolve_section(""), "")

    _head("classify — the headline decides, the body is the fallback")
    pres = {"headline": "နိုင်ငံတော်သမ္မတ ဦးမင်းအောင်လှိုင် ဗီယက်နမ်သို့ ထွက်ခွာ",
            "body_text": "နိုင်ငံတော်သမ္မတ ဦးမင်းအောင်လှိုင် ဗီယက်နမ်သို့ ထွက်ခွာသည်။"}
    check("a president headline is the president section",
          ns.classify(pres)[0], "နိုင်ငံတော်သမ္မတ")
    check("…and it was decided by the office pass, not a topic word",
          ns.classify(pres)[1], "strong")

    # THE SUBJECT RULE. A mention deep in the body is not a story about the
    # office. Measured 2026-10-01: the first version counted any two mentions,
    # and the owner's own test caught what that costs — asked "today's State
    # President news" it answered with a parliament story in which the
    # president appears only as the issuer of an order, 2,203 characters into
    # a 6,324-character body.
    passing = {"headline": "ဒဂုံတက္ကသိုလ် ဘွဲ့နှင်းသဘင် အခမ်းအနား ကျင်းပ",
               "body_text": "အခမ်းအနားကို ယနေ့ နံနက်ပိုင်းတွင် ကျင်းပသည်။ "
                            "ဘွဲ့ရ ကျောင်းသား ၁၂၀၀ ဦး တက်ရောက်သည်။ "
                            "အခမ်းအနားတွင် နိုင်ငံတော်သမ္မတ၏ မိန့်ခွန်းကို "
                            "ဖတ်ကြားခဲ့သည်။"}
    check("a mention past the opening is NOT the president section",
          ns.classify(passing)[0], "ပညာရေး")
    # **The regression that motivated the rule change.** A parliament headline,
    # the president named twice — but only in the middle of the body.
    misfile = {
        "headline": "တတိယအကြိမ် ပြည်ထောင်စုလွှတ်တော် တတိယပုံမှန်အစည်းအဝေး "
                    "ပထမနေ့ကျင်းပ",
        "body_text": "နေပြည်တော် စက်တင်ဘာ ၂၈။ " + ("လွှတ်တော် အစည်းအဝေး "
                    "ကျင်းပသည်။ " * 40) +
                     "ပြည်ထောင်စုဝန်ကြီး ဦးခင်မောင်ရီက ၂၀၂၆ ခုနှစ် ဩဂုတ်လ ၂၄ ရက်တွင် "
                     "နိုင်ငံတော်သမ္မတက ဥပဒေကဲ့သို့ အာဏာတည်သော အမိန့် "
                     "အမှတ် ၅/၂၀၂၆ ဖြင့် ထုတ်ပြန်ခဲ့သည်။ နိုင်ငံတော်သမ္မတ၏ "
                     "အမိန့်သည် အာဏာတည်သည်။"}
    check("an office named only deep in the body is NOT its section",
          ns.classify(misfile)[0] == "နိုင်ငံတော်သမ္မတ", False)
    # …and the office named in the opening IS — a Burmese lede names the
    # principal actor in its first sentence.
    lede = {"headline": "ရန်ကုန်တက္ကသိုလ် (လှိုင်နယ်မြေ) သို့ ရောက်ရှိပြီး "
                        "လှိုင်တက္ကသိုလ် ဆေးရုံကြီး ကြည့်ရှုစစ်ဆေး",
            "body_text": "ဆက်လက်၍ နိုင်ငံတော်သမ္မတနဲ့ အဖွဲ့ဝင်များသည် "
                         "ရန်ကုန်တက္ကသိုလ်(လှိုင်နယ်မြေ)သို့ ရောက်ရှိကြသည်။ "
                         "ထို့နောက် ဆေးရုံကြီးကို ကြည့်ရှုသည်။"}
    check("an office named in the opening IS its section",
          ns.classify(lede)[0], "နိုင်ငံတော်သမ္မတ")
    check("…and it was decided by the office pass", ns.classify(lede)[1], "strong")
    vp = {"headline": "ဒုတိယသမ္မတ ဦးညိုစော ရုရှားနိုင်ငံသို့ ထွက်ခွာ",
          "body_text": "ဒုတိယသမ္မတ ဦးညိုစော ရုရှားနိုင်ငံသို့ ထွက်ခွာသည်။"}
    check("a vice-president headline is the VP section",
          ns.classify(vp)[0], "ဒုတိယသမ္မတများ")

    um = {"headline": "ပြည်ထောင်စုဝန်ကြီး ဦးမင်းနောင် အာဆီယံ အစည်းအဝေး တက်ရောက်",
          "body_text": "ပြည်ထောင်စုဝန်ကြီး ဦးမင်းနောင် တက်ရောက်သည်။"}
    check("a union-minister headline is the union-minister section",
          ns.classify(um)[0], "ပြည်ထောင်စုဝန်ကြီးများ")

    # The editorial is found by its **printed marker**, not its subject — the
    # six editorials in the corpus are about education, transport, diplomacy,
    # air quality and the economy, so a subject test could never find one.
    ed = {"headline": "ရာသီဥတု ကောင်းမွန်စေရေး သန့်ရှင်းသော လေထု (အယ်ဒီတာ့အာဘော်)",
          "body_text": "လေထုညစ်ညမ်းမှု လျှော့ချရေး ဆောင်ရွက်ရမည်။"}
    check("the printed editorial marker wins over the subject",
          ns.classify(ed)[0], "အယ်ဒီတာအာဘော်")

    feat = {"headline": "ဗီယက်နမ်နိုင်ငံ၏ AI နည်းပညာ အသွင်ပြောင်းမှု (ဆောင်းပါး)",
            "body_text": "နည်းပညာ ပြောင်းလဲမှုအကြောင်း။"}
    check("a signed feature is the article section",
          ns.classify(feat)[0], "ဆောင်းပါး")

    dis = {"headline": "သံလွင်မြစ်ရေ စိုးရိမ်ရေမှတ်အထက် ကျော်လွန် ရေကြီးမှု သတိပေး",
           "body_text": "ရေကြီးမှု ဖြစ်ပွားနေသည်။"}
    check("a flood story is the disaster section",
          ns.classify(dis)[0], "သဘာဝဘေး")

    # `ဝန်ကြီးဌာန` (ministry) and `ဝန်ကြီးချုပ်` (chief minister) contain the
    # short office word — the trap `core/entities.py` documents. The union form
    # is the only one matched, so a ministry mention is not a minister.
    minis = {"headline": "စိုက်ပျိုးရေးဝန်ကြီးဌာန လယ်ယာစီမံကိန်း ဆောင်ရွက်",
             "body_text": "ဝန်ကြီးဌာနက ဆောင်ရွက်သည်။ ဝန်ကြီးဌာန ထုတ်ပြန်သည်။"}
    check("a ministry is not a union minister",
          ns.classify(minis)[0] == "ပြည်ထောင်စုဝန်ကြီးများ", False)

    other = {"headline": "ကြော်ငြာစာ - မန္တလေးမြို့ အောင်မြေသာစံမြို့နယ်",
             "body_text": "ကြော်ငြာစာ အသေးစိတ်။"}
    check("an advertisement is 'other'", ns.classify(other)[0], ns.OTHER)
    check("an empty row is 'other'", ns.classify({})[0], ns.OTHER)

    # Whitespace is not a separator to trust — the paper writes both forms.
    spaced = {"headline": "နိုင်ငံတော် သမ္မတ ဦးမင်းအောင်လှိုင် မိန့်ခွန်း ပြောကြား",
              "body_text": ""}
    check("the spaced office spelling is recognised",
          ns.classify(spaced)[0], "နိုင်ငံတော်သမ္မတ")

    _head("section_of — a legacy value is 'never indexed', not an answer")
    check("a stored label is returned",
          ns.section_of({"article_type": "စီးပွားရေး"}), "စီးပွားရေး")
    for legacy in ("General", "Sports", "Business / Market Rates", "ပြည်တွင်း", ""):
        check(f"'{legacy}' means not-indexed", ns.section_of({"article_type": legacy}), "")
    check("a missing column is not an answer", ns.section_of({}), "")

    _head("The route — a section question, and the three it must NOT claim")
    check("the owner's own example routes to the section tool",
          M._news_route("နိုင်ငံတော်သမ္မတ သတင်းဒီနေ့ဘာရှိလဲ"), "news_section")
    check("a named paper plus a section still routes to the section tool",
          M._news_route("ဒီနေ့ ကြေးမုံသတင်းစာမှာ စီးပွားရေး သတင်း ပြောပြ"),
          "news_section")
    check("a bare section name routes to the section tool",
          M._news_route("နိုင်ငံတော်သမ္မတ ကဏ္ဍမှာ ဘာရှိလဲ"), "news_section")
    # …and the three that belong to `reporter_news`, each one a measured case.
    check("'who is named' is still reporter_news",
          M._news_route("ဒီနေ့ သတင်းစာထဲ ဘယ်ဝန်ကြီးတွေ ပါသလဲ"), "reporter_news")
    check("'are there stories about the president and the VPs' is still reporter_news",
          M._news_route("ဒီနေ့ မြန်မာ့အလင်းသတင်းစာမှာ နိုင်ငံတော်သမ္မတ၊ "
                        "ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့ သတင်းတွေ ရှိလား"),
          "reporter_news")
    check("'did disaster news rise' is still newsroom_search",
          M._news_route("သဘာဝဘေးသတင်းတွေ တက်လား"), "newsroom_search")
    check("'is there any education news' is still newsroom_search",
          M._news_route("ပညာရေး သတင်း ရှိလား"), "newsroom_search")

    _head("The handler contract — the loader calls fn(parameters=..., ...)")
    import inspect
    sig = inspect.signature(nsec.news_section)
    check("news_section takes `parameters`",
          "parameters" in sig.parameters, True)
    check("…and does not swallow the dict in **_",
          sig.parameters["parameters"].default is None, True)
    # An unknown section must be refused by the tool, not silently widened.
    from core.action_loader import _call_handler
    out = _call_handler(nsec.news_section, {"section": "အားကစား"}, {})
    check("an unknown section is refused", "အားကစား" in out, True)
    check("…and the refusal names the real sections",
          "နိုင်ငံတော်သမ္မတ" in out and "အယ်ဒီတာအာဘော်" in out, True)
    check("the tool declares its parameters",
          sorted(nsec.TOOL["parameters"]["properties"]) ==
          ["action", "date", "days", "limit", "paper", "section"], True)

    _head("The loader discovers it, and it is not mistaken for a helper")
    from pathlib import Path
    from core.action_loader import discover_actions
    registry = discover_actions(Path(__file__).resolve().parent / "actions")
    names = set(getattr(registry, "names", lambda: [])()) or {
        getattr(r, "name", "") for r in getattr(registry, "records", [])}
    check("news_section is a discovered action", "news_section" in names, True)
    check("the other state-paper tools are still discovered",
          {"reporter_news", "gold_currency"} <= names, True)
    # A file starting with `_` is skipped by the loader, so `_reporter_common`
    # is a helper and never mistaken for an action that failed validation.
    check("_reporter_common is NOT an action", "_reporter_common" in names, False)

    if "--live" in sys.argv:
        _head("Live — the database (reads only unless action='index')")
        from core.reporter_client import (
            available, articles_by_section, section_tally, stored_section_counts)
        ok, reason = available()
        check("the reporter database is reachable", ok, True)
        if ok:
            stored = stored_section_counts()
            check("the section column is not all default",
                  any(k in ns.LABELS and v for k, v in stored.items()), True)
            tally = section_tally()
            check("a tally comes back for the newest edition",
                  isinstance(tally, dict) and sum(tally.values()) > 0, True)
            # Shape, not a number: the pipeline ingests while this runs, so any
            # exact count here would flake.
            rows = articles_by_section("နိုင်ငံတော်သမ္မတ", days=0, limit=3)
            check("the president section returns a list",
                  isinstance(rows, list), True)
            check("…and every row carries a headline",
                  all(isinstance(r.get("headline"), str) for r in rows), True)
            check("an unknown section returns nothing from the reader",
                  articles_by_section("အားကစား", limit=3), [])
            # The list and the header count must agree: both are spoken, and a
            # duplicate row would make the number the user hears wrong.
            _p = articles_by_section("နိုင်ငံတော်သမ္မတ", days=0, limit=25)
            _heads = [(r.get("headline") or "").replace(" ", "") for r in _p]
            check("a section list carries no duplicate story",
                  len(_heads) == len(set(_heads)), True)
            check("…and the tally counts stories, not rows",
                  tally.get("နိုင်ငံတော်သမ္မတ", 0) >= len(_p), True)
    else:
        print()
        print("  (skipped the live database checks — pass --live to run them)")

    _head("The helper split — every name moved out is still imported back")
    # `reporter_news.py` lost 15 helpers to `_reporter_common.py` on 2026-09-30.
    # The first version imported 11 of them, and the missing `_elsewhere_people`
    # only surfaced at run time, inside a `people` branch, as a NameError — the
    # module imported fine and every check that did not take that branch passed.
    #
    # So the test is not "does this module have unbound names" (every local
    # variable would fail that). It is the precise question: **is any name that
    # now lives in the shared module used here without being imported?**
    import ast

    def _module_names(path: str) -> set[str]:
        tree = ast.parse(open(path, encoding="utf-8").read())
        out: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                out.add(node.name)
            elif isinstance(node, ast.Assign):
                out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                out.add(node.target.id)
        return out

    _shared = _module_names("actions/_reporter_common.py")
    check("the shared module exports something to check", len(_shared) > 5, True)
    for mod_name in ("actions/reporter_news.py", "actions/news_section.py"):
        tree = ast.parse(open(mod_name, encoding="utf-8").read())
        imported: set[str] = set()
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {a.asname or a.name for a in node.names}
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
        orphaned = sorted((used & _shared) - imported)
        check(f"{mod_name} imports every shared helper it uses", orphaned, [])

    print()
    print("=" * 74)
    print("VERDICT")
    print("=" * 74)
    if FAILURES:
        print(f"  {len(FAILURES)} FAILED")
        for f in FAILURES:
            print(f"   ✗ {f}")
        return 1
    print("  all checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
