"""Does the moi.gov.mm reader behave? — offline, no network.

    py check_moi.py

WHAT THIS COVERS — every defect found on 2026-10-01 while building the
"answer every state-news question from the website, by section" system:

    the card layouts   `/other-news` and `/news` serve `/index.php/news/N` and
                       `class="card-text text-justify"`; requiring `href="/news/N"`
                       and exactly `class="card-text"` matched **0 of 20 cards**,
                       so the section was answered as "not found" while it held
                       news dated that day
    layout B           `/articles` and `/perspective` use `news-wrapper`, with
                       `/article/N` on one and `/news/N` on the other
    group numbering    layout A captures the href as groups 1–2, layout B as the
                       named group `url` — reading `group(2)` for both hands
                       layout B's *date* back as the article id
    the balanced div   `<div class="X">(.*?)</div>` stops at the first nested
                       close, which read a 7,282-character article as 44 chars
    the section label  `/other-news` is ပြည်တွင်းသတင်း, not အခြားသတင်း
    alias order        `အမျိုးသားလွှတ်တော်` must resolve before the bare
                       `လွှတ်တော်`, or an amyotha question reads the combined
                       hluttaw list; `ဒုတိယသမ္မတ` before `သမ္မတ`
    the digit trap     `"၈၈၆၇၃".isdigit()` is True, so a Burmese-digit id built
                       `/news/၈၈၆၇၃` — the tool must refuse it
    four answers       found / `မရှိပါ` (limitation) / `မတွေ့ပါ` (finding) /
                       `မချိတ်နိုင်ပါ` (failure) are four different sentences

WHY IT IS A SCRIPT AND NOT A NOTE

    Each of these was a real fault found by reading the site. A fault that is
    fixed but not checked is a fault that comes back — and two of them (the
    `NameError` in the story branch, the group-numbering bug) were only found on
    a second pass, after the first version looked correct.
"""
import ast
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, r"E:\Mark-LIV-main")

FAILURES: list[str] = []


def _head(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, wanted {want!r}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}"
          + ("" if ok else f"   got {got!r}, wanted {want!r}"))


# ── the real markup, copied out of the live pages on 2026-10-01 ───────────────
CARD_A_PLAIN = """<a href="/news/88750" hreflang="en"><img src="/x.jpg" alt="" /></a>
</div><div class="col-md-8"><div class="card-body">
<div class="card-title news-title"><h2><a href="/news/88750">HEAD A</a></h2></div>
<p class="my-3"><i class="fa fa-clock-o"></i> Oct 01, 2026</p>
<p class="card-text">SUM A</p></div></div>"""

# `/other-news` and `/news`: an /index.php prefix and an extra class token.
CARD_A_INDEX = """<a href="/index.php/news/88749" hreflang="en"><img src="/y.jpg" alt="" /></a>
</div><div class="col-md-8"><div class="card-body">
<div class="card-title news-title"><h2><a href="/index.php/news/88749">HEAD B</a></h2></div>
<p class="my-3"><i class="fa fa-clock-o"></i> Oct 01, 2026</p>
<p class="card-text text-justify">SUM B</p></div></div>"""

# `/articles`: news-wrapper, the date BEFORE the title, link /article/N.
CARD_B_ARTICLE = """<div class="news-wrapper"> <i class="fa fa-clock-o"></i> Oct 01, 2026
<div class="news-title"><h2><a href="/index.php/article/88747" hreflang="en">HEAD C</a></h2></div>
<div class="row news-container">
<div class="col-xs-4 news-image-wrapper"><div class="news-image"><img src="/z.jpg" /></div></div>
<div class="col-xs-8 news-content"><div class="">SUM C</div></div>
</div></div>"""

# `/perspective`: the same layout but the link is /news/N.
CARD_B_NEWS = """<div class="news-wrapper"> <i class="fa fa-clock-o"></i> Oct 01, 2026
<div class="news-title"><h2><a href="/news/88728" hreflang="en">HEAD D</a></h2></div>
<div class="row news-container">
<div class="col-xs-4 news-image-wrapper"><div class="news-image"><img src="/w.jpg" /></div></div>
<div class="col-xs-8 news-content"><div class="">SUM D</div></div>
</div></div>"""


def main() -> int:
    from core import moi_client as mc
    from actions import moi_news as M

    # ── the sections ────────────────────────────────────────────────────────
    _head("the sections the site actually serves")
    check("eleven sections", len(mc.SECTIONS), 11)
    check("every entry is a 3-tuple", all(len(s) == 3 for s in mc.SECTIONS), True)
    slugs = [s for s, _l, _c in mc.SECTIONS]
    check("slugs are unique", len(set(slugs)), len(slugs))
    check("every label is non-empty", all(l.strip() for _s, l, _c in mc.SECTIONS), True)
    check("every slug is a bare path segment",
          all(re.fullmatch(r"[a-z0-9-]+", s) for s in slugs), True)
    check("other-news is ပြည်တွင်းသတင်း, not အခြားသတင်း",
          mc.SECTION_LABEL["other-news"], "ပြည်တွင်းသတင်း")
    for slug in ("articles", "perspective", "hluttaw-news", "news"):
        check(f"{slug} is present", slug in mc.SECTION_LABEL, True)
    check("the three hluttaw sections are all present",
          {"pyidaungsu-hluttaw-news", "pyithu-htuttaw-news",
           "amyotha-htuttaw-news"} <= set(slugs), True)
    check("layout B is exactly articles + perspective",
          mc._LAYOUT_B, frozenset({"articles", "perspective"}))

    # ── resolve_section, and the order that is load-bearing ─────────────────
    _head("resolve_section — the ordering is load-bearing")
    for said, want in (
        ("နိုင်ငံတော်သမ္မတ", "president-news"),
        ("ဒုတိယသမ္မတ", "vice-presidents-news"),
        ("ဒုတိယသမ္မတသတင်းများ", "vice-presidents-news"),
        ("ဆောင်းပါး", "articles"),
        ("အယ်ဒီတာ့အာဘော်", "perspective"),
        ("ပြည်တွင်းသတင်း", "other-news"),
        ("သတင်းများ", "news"),
        ("လွှတ်တော်သတင်း", "hluttaw-news"),
        # the bare alias must resolve to the COMBINED section...
        ("လွှတ်တော်", "hluttaw-news"),
        # ...but a named hluttaw must win over it
        ("အမျိုးသားလွှတ်တော်", "amyotha-htuttaw-news"),
        ("ပြည်သူ့လွှတ်တော်", "pyithu-htuttaw-news"),
        ("ပြည်ထောင်စုလွှတ်တော်", "pyidaungsu-hluttaw-news"),
        ("တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်", "commander-in-chief-news"),
        # a bare သမ္မတ must NOT steal the vice-president's question
        ("သမ္မတ", "president-news"),
        # whitespace is not significant
        ("နိုင်ငံတော် သမ္မတ", "president-news"),
        # not a section
        ("အားကစား", ""),
        ("", ""),
    ):
        check(f"{said!r} -> {want!r}", mc.resolve_section(said), want)

    # ── the card layouts ────────────────────────────────────────────────────
    _head("layout A — /other-news and /news were answered as empty")
    a = mc._cards(CARD_A_PLAIN, "president-news")
    check("plain /news/N + class=card-text parses", len(a), 1)
    check("  headline", a[0]["headline"] if a else "", "HEAD A")
    check("  id", a[0]["id"] if a else "", "88750")
    check("  date", a[0]["issue_date"] if a else "", "2026-10-01")

    b = mc._cards(CARD_A_INDEX, "other-news")
    check("/index.php prefix + card-text text-justify parses", len(b), 1)
    check("  id is the digits, not 'index'", b[0]["id"] if b else "", "88749")
    check("  the /index.php prefix is stripped from the link",
          b[0]["url"] if b else "", "/news/88749")
    check("  summary past the extra class token", b[0]["summary"] if b else "", "SUM B")

    _head("layout B — /articles and /perspective were invisible")
    c = mc._cards(CARD_B_ARTICLE, "articles")
    check("/article/N parses", len(c), 1)
    check("  id comes from the url, not group(2)", c[0]["id"] if c else "", "88747")
    check("  date before the title", c[0]["issue_date"] if c else "", "2026-10-01")
    check("  headline", c[0]["headline"] if c else "", "HEAD C")

    d = mc._cards(CARD_B_NEWS, "perspective")
    check("/news/N in the same layout parses", len(d), 1)
    check("  id", d[0]["id"] if d else "", "88728")

    check("a layout-B page is not read with layout A",
          len(mc._cards(CARD_B_ARTICLE, "president-news")), 0)

    # ── the balanced div ────────────────────────────────────────────────────
    _head("the article body needs a balanced div, not a lazy match")
    # Content AFTER a nested close is what a lazy match silently drops.
    trunc = ('<div class="post-body"><div class="a">PART ONE</div>'
             '<div class="b">PART TWO</div></div> tail')
    start = trunc.index('<div class="post-body">')
    check("_div_inner keeps everything",
          mc._text(mc._div_inner(trunc, start)), "PART ONE PART TWO")
    lazy = re.search(r'<div class="post-body">(.*?)</div>', trunc, re.S)
    check("the lazy match really does drop PART TWO",
          mc._text(lazy.group(1)) if lazy else "", "PART ONE")
    nested = ('<div class="post-body"> <div class="field">'
              '<p>REAL TEXT HERE</p></div> </div> tail')
    check("...and keeps a nested <p> whole",
          mc._text(mc._div_inner(nested, nested.index('<div class="post-body">'))),
          "REAL TEXT HERE")
    check("_div_inner on an empty div returns empty",
          mc._text(mc._div_inner('<div class="post-body"></div>', 0)), "")

    # ── _iso ────────────────────────────────────────────────────────────────
    _head("date parsing")
    check("Oct 01, 2026", mc._iso("Oct 01, 2026"), "2026-10-01")
    check("Sep 30, 2026", mc._iso("Sep 30, 2026"), "2026-09-30")
    check("a non-date is empty", mc._iso("not a date"), "")
    check("a bad month is empty", mc._iso("Xxx 01, 2026"), "")

    # ── the digit trap ──────────────────────────────────────────────────────
    _head("the Burmese-digit trap in the story branch")
    check('"၈၈၆၇၃".isdigit() is True — which is why isdigit is wrong',
          "၈၈၆၇၃".isdigit(), True)
    check("re.fullmatch(r'[0-9]+') refuses it",
          bool(re.fullmatch(r"[0-9]+", "၈၈၆၇၃")), False)
    check("...and accepts an ASCII id", bool(re.fullmatch(r"[0-9]+", "88673")), True)
    src = Path(r"E:\Mark-LIV-main\actions\moi_news.py").read_text(encoding="utf-8")
    # Read the syntax tree, not the text: a substring test finds the word inside
    # the comment that explains the trap — the same false positive the review
    # gate itself had to fix.
    isdigit_calls = [n.lineno for n in ast.walk(ast.parse(src))
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "isdigit"]
    check("the action no longer CALLS .isdigit()", isdigit_calls, [])
    check("the action imports re (the NameError that only a branch reached)",
          bool(re.search(r"^import re$", src, re.M)), True)

    # ── four answers, four sentences ────────────────────────────────────────
    _head("four answers, never merged")
    for name, sentence in (("finding", "မတွေ့ပါ"),
                           ("limitation", "မရှိပါ"),
                           ("failure", "မချိတ်နိုင်ပါ")):
        check(f"the {name} sentence is in the tool", sentence in src, True)
    check("the limitation is spoken FIRST in the not-in-window answer",
          src.index("သတင်း မရှိပါ") < src.index("အနီးစပ်ဆုံး"), True)
    check("the tool description warns against merging them",
          "မချိတ်နိုင်ပါ" in M.TOOL["description"], True)

    # ── the tool contract ───────────────────────────────────────────────────
    _head("the TOOL contract")
    check("name", M.TOOL["name"], "moi_news")
    check("parameters is OBJECT", M.TOOL["parameters"]["type"], "OBJECT")
    check("handler is callable", callable(M.TOOL["handler"]), True)
    props = M.TOOL["parameters"]["properties"]
    for p in ("action", "section", "query", "url", "date", "days", "limit"):
        check(f"parameter {p!r} is declared", p in props, True)
    check("`days` says it is for today/yesterday", "ဒီနေ့" in props["days"]["description"], True)
    # Measured 2026-10-03: a two-date question was answered correctly because the
    # model called the tool once per date. That was luck until it was written
    # down — `days=7` would have answered about a day the owner never asked about.
    check("`date` says to call once per day for several days",
          "once per day" in props["date"]["description"], True)
    check("...and warns against widening to a `days` window",
          "days` window" in props["date"]["description"], True)
    check("the handler takes `parameters` by name",
          "parameters" in M.moi_news.__code__.co_varnames, True)
    check("the description names the sections",
          "အယ်ဒီတာ့အာဘော်" in M.TOOL["description"], True)
    # Re-framed twice, 2026-10-01. The first version pinned the phrase
    # "instead of the database"; the second pinned "database is only". Both
    # broke on a rewrite that kept the rule. A description check cannot avoid
    # matching words, so match the ones that must survive ANY rewrite — the
    # source it names and the store it rejects — and leave the prose free.
    check("the description names the live source",
          "moi.gov.mm" in M.TOOL["description"], True)
    check("...and names the database it is not",
          "database" in M.TOOL["description"], True)

    # ── the search bound is honest ──────────────────────────────────────────
    _head("the search claim is bounded")
    check("the fallback walk's page cap is small", M._SEARCH_PAGES <= 6, True)
    check("the site-search page cap is small", M._SITE_SEARCH_PAGES <= 4, True)
    # Re-framed 2026-10-03, not relaxed. This pinned the OLD wording
    # ("စာမျက်နှာ … အထိ"), which described the page-walk. The RULE is that the
    # answer states the scope of whatever search produced it — and the site
    # search now reaches the whole archive, so its note says that instead.
    check("the site-search note names the source and its reach",
          "ကိုယ်ပိုင် ရှာဖွေမှု" in M._SEARCH_SCOPE and "archive" in M._SEARCH_SCOPE, True)
    check("...and warns the list carries no date",
          "ရက်စွဲ မပါ" in M._SEARCH_SCOPE, True)
    check("the fallback walk still states its own bound",
          "စာမျက်နှာ" in src and "အထိ" in src, True)

    # ── the routing surface, after the live run ─────────────────────────────
    _head("the state-news routing surface — the live run's two defects")
    desc = M.TOOL["description"]
    # Measured 2026-10-01, two live runs of the SAME question:
    #   run 1 — the description named the database tools as ones NOT to use, and
    #           the model chose `moi_news` correctly (then wasted a turn calling a
    #           misspelled `yarvis_news`).
    #   run 2 — those names were removed to stop that, and **`news_section` won
    #           the turn instead**, because its description names this exact
    #           question as its own case. That is the worse failure: it answers
    #           from the incomplete database copy.
    # So the fix is to KEEP the steering and name the real competitor. An earlier
    # version of this check asserted the opposite ("does not name jarvis_news")
    # and is what produced run 2.
    # `jarvis_news` was in this tuple until 2026-10-01, when the owner had it
    # removed. `news_section` is now the only database competitor for a
    # state-news question, and `reporter_news` the only other.
    for competitor in ("news_section", "reporter_news"):
        check(f"the description names {competitor} as NOT the tool",
              competitor in desc, True)
    check("it says the answer is final / do not double-check",
          "answer is final" in desc and "double-check" in desc, True)
    check("the not-in-window answer tells the model to stop looking",
          "ထပ်မခေါ်ပါနှင့်" in src, True)
    # Measured live 2026-10-01: with only "report what you got", the model said
    # "မတွေ့ရပါဘူး" (I did not find) where the tool had said "မရှိပါ" (there is
    # none) — the project's headline rule, drifting one layer below the product.
    # Naming the exact sentence fixed it on the next run.
    check("the answer names the exact sentence to speak",
          "မရှိပါ" in src and "မတွေ့ပါ" in src and "မပြောပါနှင့်" in src, True)

    _head("news_section must carry the same split")
    sec_src = Path(r"E:\Mark-LIV-main\actions\news_section.py").read_text(encoding="utf-8")
    check("news_section redirects state news to moi_news",
          "use `moi_news`" in sec_src, True)
    check("...and says why (the database copy is incomplete)",
          "database copy" in sec_src, True)

    # The `jarvis_news` "exist only here" checks were removed with the file on
    # 2026-10-01. Its one true claim — the five topics the site lacks — is now
    # asserted below against `news_section`, which is where those questions go.

    _head("jarvis_news is gone — the site serves what it held")
    # Removed 2026-10-01 on the owner's instruction. The one thing it carried that
    # the site does NOT is the five topics below, and `news_section` (the reporter
    # project, still present) already indexes exactly those — checked here so the
    # removal cannot quietly leave a gap.
    check("actions/jarvis_news.py is removed",
          Path(r"E:\Mark-LIV-main\actions\jarvis_news.py").exists(), False)
    check("core/jarvis_client.py is removed",
          Path(r"E:\Mark-LIV-main\core\jarvis_client.py").exists(), False)
    check("a copy is kept for recovery",
          Path(r"E:\Mark-LIV-main\backup\removed-2026-10-01\jarvis_news.py").exists(), True)
    sections_src = Path(r"E:\Mark-LIV-main\core\news_sections.py").read_text(encoding="utf-8")
    for topic in ("ပညာရေး", "ကျန်းမာရေး", "စီးပွားရေး", "လူမှုရေး", "သဘာဝဘေး"):
        check(f"news_section still covers {topic}", topic in sections_src, True)
    # AST, not a substring search: the first version looked for the text
    # "import jarvis_news" and **found its own pattern inside this file**, so it
    # reported a defect that did not exist. Same false positive the review gate
    # hit twice — a string test cannot tell code from the code that looks for it.
    def _imports_removed(path) -> bool:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            return False
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(
                    ("jarvis_news", "jarvis_client")):
                return True
            if isinstance(n, ast.Import):
                if any(a.name.endswith(("jarvis_news", "jarvis_client"))
                       for a in n.names):
                    return True
        return False

    _live = (list(Path(r"E:\Mark-LIV-main").glob("*.py"))
             + list(Path(r"E:\Mark-LIV-main\actions").glob("*.py"))
             + list(Path(r"E:\Mark-LIV-main\core").glob("*.py")))
    check("no live file imports the removed modules",
          [p.name for p in _live if _imports_removed(p)], [])

    _head("search must survive a whole-question query and a date filter")
    # Measured 2026-10-03, one live turn, TWO defects in one call:
    #   * the model passed the whole sentence 'နိုင်ငံတော်သမ္မတ အိန္ဒိယ ခရီးစဉ်' — a
    #     phrase match, so 0 results, while 'အိန္ဒိယ' alone gives 20;
    #   * it passed `days=30`, and the date filter dropped every site-search
    #     result because those carry no date and `"" >= floor` is False.
    # The owner was told there was no news about a trip the site covers in a
    # dozen articles. Both are now handled, and both are asserted here.
    check("a whole-question query falls back to its tokens",
          "for tok in sorted({t for t in re.split" in src, True)
    # Measured 2026-10-03: the model passed `query` with NO `action`, the default
    # was `list`, and the tool listed the section instead of searching — so the
    # answer said the India trip was not in the news.
    check("a `query` with no `action` means search, not list",
          'action = "search" if term else "list"' in src, True)
    check("the date filter is applied only to the walk, which has dates",
          'if used == "walk":' in src, True)
    check("...and the answer says when a date filter could not be applied",
          "ရက်နဲ့ စစ်လို့ မရပါ" in src, True)
    check("the site search is preferred over the walk",
          'used = "site"' in src and 'used = "walk"' in src, True)
    # A competitor that is not named will win — `news_search` was tried first in
    # that live run and is named nowhere in the description.
    for competitor in ("news_section", "reporter_news", "news_search"):
        check(f"the description names {competitor} as NOT the tool",
              competitor in M.TOOL["description"], True)
    check("`query` says not to pass the whole question",
          "whole question" in props["query"]["description"], True)
    check("...and gives a working example",
          "အိန္ဒိယ" in props["query"]["description"], True)

    _head("every body container the site uses is known")
    check("three containers are declared", len(mc._BODY_CONTAINERS), 3)
    check("post-body is one", any("post-body" in p for p in mc._BODY_CONTAINERS), True)
    check("schema:text is one",
          any("schema:text" in p for p in mc._BODY_CONTAINERS), True)
    check("the president-speech container is one",
          any("president-speech-body" in p for p in mc._BODY_CONTAINERS), True)
    # A failed read must not be spoken as an empty source.
    check("article_state exists", callable(getattr(mc, "article_state", None)), True)
    check("...and separates empty (the site) from unreadable (us)",
          "empty" in inspect.getsource(mc.article_state)
          and "unreadable" in inspect.getsource(mc.article_state), True)

    _head("an undeclared tool name must come back as a correction")
    try:
        import main as _main
        check("_closest_names exists", callable(getattr(_main, "_closest_names", None)), True)
        # The live case was `yarvis_news`; `jarvis_news` no longer exists, so the
        # example is now a dropped letter in a tool that does.
        near = _main._closest_names("news_secton", {"news_section", "moi_news",
                                                    "reporter_news", "news_search"})
        check("`news_secton` resolves to `news_section`", near[:1], ["news_section"])
        check("a wholly unknown name yields nothing to suggest",
              _main._closest_names("zzzzzzzz", {"news_section", "moi_news"}), [])
        check("the dispatcher no longer replies with a bare English string",
              'f"Unknown tool: {name}"' in
              Path(r"E:\Mark-LIV-main\main.py").read_text(encoding="utf-8"), False)
    except Exception as e:                                  # noqa: BLE001
        check(f"could not import main ({type(e).__name__})", False, True)

    # ── the early-stop bound (the fix for the turn that died) ────────────────
    _head("a dated question must not walk the whole archive")
    import inspect as _inspect
    sig = _inspect.signature(mc.list_section)
    check("list_section takes an `until` bound", "until" in sig.parameters, True)
    # Measured 2026-10-01: without the bound, one day's president news walked 20
    # pages / 301 cards / 48.7 s, and the live turn died before the model spoke.
    check("the action passes `until` to the walk",
          "until=until" in src, True)
    check("`until` is also the cache key (a bounded read is not the full read)",
          "list:{section}:{pages}:{until}" in Path(
              r"E:\Mark-LIV-main\core\moi_client.py").read_text(encoding="utf-8"), True)

    _head("the probe must not count a tool call as silence")
    probe = Path(r"E:\Mark-LIV-main\probe_moi_live.py").read_text(encoding="utf-8")
    # The first version let the idle timer run during `_execute_tool`, so a 20 s
    # tool call looked like 30 s of silence and the pump was cancelled mid-turn.
    check("the probe has a busy guard", "busy = [False]" in probe, True)
    check("...and the idle check respects it",
          "not busy[0] and time.time() - last > IDLE_DRAIN_S" in probe, True)
    check("...and `last` is nonlocal, so activity actually resets the timer",
          "nonlocal last" in probe, True)

    # ── the window ──────────────────────────────────────────────────────────
    _head("the today/yesterday window is Yangon time")
    check("days=1 floor is today", M._floor(1), M._today_mmt())
    check("days=2 floor is yesterday",
          M._floor(2) < M._floor(1), True)
    check("the floor is a real ISO date",
          bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", M._floor(1))), True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print("   -", f)
        return 1
    print("all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
