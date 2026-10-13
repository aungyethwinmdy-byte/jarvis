"""Does the JARVIS <-> AI Newsroom bridge actually work?

    py check_newsroom.py            offline: gates, formatting, tool registration
    py check_newsroom.py --live     also reads the real database

WHAT THIS COVERS
    core/newsroom_client.py   the read-only Supabase bridge
    core/newsroom_watch.py    the unprompted-announcement gates
    actions/newsroom_*.py     the three tools, and daily_briefing's fallback

WHY THE REGISTRATION SECTION IS THE POINT
    core/action_loader.py skips a file that fails to import **without raising**.
    So "the file exists" and "the assistant can call it" are different facts,
    and only running the real discover_actions() tells them apart. That is not
    a theoretical concern here: actions/daily_briefing.py was found in exactly
    that state — a module-level import of a function that no longer existed,
    which had silently deleted the briefing tool. Section 5 re-checks it.

WHY THE DIGIT CHECK IS NOT `isdigit()`
    str.isdigit() is True for the Burmese digits ၀-၉ as well as ASCII 0-9, so
    using it to find leftover ASCII digits reports success on text that is full
    of them. re.search(r"[0-9]") is the honest test.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

problems: list[str] = []


def _fail(msg: str) -> None:
    problems.append(msg)
    print(f"  FAIL  {msg}")


def _ok(msg: str) -> None:
    print(f"  ok    {msg}")


# ── 1. config ────────────────────────────────────────────────────────────────

def check_config() -> None:
    print("=" * 78)
    print("1. CONFIG  (the settings that decide whether anything is spoken)")

    from memory import config_manager as cm

    path = cm.get_newsroom_env_path()
    exists = Path(path).exists()
    print(f"  newsroom_env_path      : {path}")
    print(f"  ...exists              : {exists}")
    if not exists:
        _fail(f"newsroom .env not found at {path} — the bridge has no credentials")

    watch = cm.get_newsroom_enabled()
    print(f"  newsroom_watch_enabled : {watch}   <- gates UNPROMPTED announcements")
    if not watch:
        print("      note: off, so JARVIS will never speak the news on its own.")
        print("            On-demand tools (daily_briefing, newsroom_*) still work.")

    start, end = cm.get_newsroom_quiet_hours()
    print(f"  quiet hours (MMT)      : {start:02d}:00 - {end:02d}:00")
    print(f"  poll interval          : every {cm.get_newsroom_poll_minutes()} min")


# ── 2. bridge ────────────────────────────────────────────────────────────────

def check_bridge() -> None:
    print("=" * 78)
    print("2. BRIDGE  (must degrade, never raise — this is a voice path)")

    from core import newsroom_client as nr

    ok, reason = nr.available()
    print(f"  available()            : {ok}  ({reason})")

    # A missing env file must produce a clean False, not an exception.
    original = nr.env_path
    try:
        nr.env_path = lambda: Path(ROOT / "definitely_not_here.env")
        nr._client, nr._client_tried, nr._client_error = None, False, ""
        ok2, reason2 = nr.available()
        print(f"  with a bad env path    : available()={ok2} reason={reason2!r}")
        if ok2:
            _fail("available() returned True for a non-existent .env")
        if not reason2:
            _fail("available() gave no reason when unavailable")
        # Every public read must return its empty shape, not raise.
        for name, call, empty in (
            ("recent_reports", lambda: nr.recent_reports(), []),
            ("search_articles", lambda: nr.search_articles("test"), []),
            ("search_reports", lambda: nr.search_reports("test"), []),
            ("article_by_id", lambda: nr.article_by_id("nope"), None),
            ("latest_digest", nr.latest_digest, None),
            ("pipeline_status", nr.pipeline_status, {}),
            ("newest_marker", nr.newest_marker, None),
        ):
            got = call()
            if got != empty:
                _fail(f"{name}() returned {got!r} with no database, expected {empty!r}")
        _ok("all reads degrade to their empty shape")
    finally:
        nr.env_path = original
        nr._client, nr._client_tried, nr._client_error = None, False, ""


# ── 3. formatting ────────────────────────────────────────────────────────────

SAMPLE_REPORT = """📱 <b>သမ္မတရုံး ထုတ်ပြန်ချက် ထွက်ရှိ</b> (သတင်းဌာန: PPIB)
   • နိုင်ငံတော်သမ္မတရုံးမှ ယနေ့ ထုတ်ပြန်ချက် တစ်စောင် ထုတ်ပြန်ခဲ့သည်။

⏱️ <b>တစ်မိနစ် အနှစ်ချုပ်</b>
• 2026 ခုနှစ် စက်တင်ဘာ 27 ရက်နေ့တွင် ထုတ်ပြန်ခဲ့ခြင်း ဖြစ်သည်။
• အစည်းအဝေး 3 ခု ကျင်းပခဲ့သည်။

🎯 <b>ဒါ မင်းနဲ့ ဘာဆိုင်လဲ</b>
• စာဖတ်သူအတွက် သက်ရောက်မှု ရှိသည်။
"""


def check_formatting() -> None:
    print("=" * 78)
    print("3. FORMATTING  (what reaches the speaker, not the screen)")

    from core import newsroom_client as nr

    cleaned = nr.clean_for_speech(SAMPLE_REPORT)
    if "<" in cleaned or ">" in cleaned:
        _fail("clean_for_speech left HTML tags in the spoken text")
    else:
        _ok("HTML tags stripped")

    ascii_digits = re.findall(r"[0-9]", cleaned)
    if ascii_digits:
        _fail(f"clean_for_speech left ASCII digits in the spoken text: {set(ascii_digits)}")
    else:
        _ok("no ASCII digits (Burmese numerals only)")

    # Independent of the module's own regexes: the ranges are the point, so
    # writing them out again here means a wrong range in the module cannot make
    # its own test pass.
    EMOJI_RANGES = ((0x1F300, 0x1FAFF), (0x1F1E6, 0x1F1FF), (0x2190, 0x21FF),
                    (0x2300, 0x27BF), (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F), (0x20E3, 0x20E3))
    emoji = [c for c in cleaned if any(a <= ord(c) <= b for a, b in EMOJI_RANGES)]
    if emoji:
        _fail(f"emoji survived into the spoken text: {emoji[:6]}")
    else:
        _ok("emoji stripped")

    # List markers are not emoji but are just as unspeakable.
    # `ln[:1] in BULLETS` would also match the empty string — "" is a substring
    # of every string — so blank lines are excluded explicitly.
    BULLETS = "•▪●◦‣⁃·"
    leading = [ln for ln in cleaned.splitlines() if ln and ln[0] in BULLETS]
    if leading:
        _fail(f"list markers survived into the spoken text: {leading[:3]}")
    else:
        _ok("bullet markers stripped from the start of every line")

    # A minus sign that is part of a number must NOT be eaten as a bullet.
    # Note the digit is converted to ၅ on the way out, so compare the sign.
    if not nr.clean_for_speech("-5 ဒီဂရီ").startswith("-"):
        _fail("clean_for_speech ate a leading minus that belonged to a number")
    else:
        _ok("a leading minus attached to a number is preserved")

    headline, bullets = nr.extract_summary(SAMPLE_REPORT)
    print(f"  headline               : {headline!r}")
    print(f"  bullets                : {len(bullets)}")
    if not headline:
        _fail("extract_summary found no headline")
    if not bullets:
        _fail("extract_summary found no summary bullets")
    if any("ဒါ မင်းနဲ့ ဘာဆိုင်လဲ" in b for b in bullets):
        _fail("extract_summary ran past the summary section into the next one")

    # A non-report must not be turned into structure that is not there.
    if nr.extract_summary("just a plain sentence")[1]:
        _fail("extract_summary invented bullets for a plain string")
    else:
        _ok("plain text is not force-fitted into the report shape")

    # The briefing formatter must produce something and keep it digits-safe.
    text = nr.format_briefing([{
        "source": "PPIB", "title": "t", "headline": headline,
        "bullets": bullets, "created": None, "published": None,
    }])
    if not text:
        _fail("format_briefing produced nothing for a valid item")
    elif re.search(r"[0-9]", text):
        _fail("format_briefing emitted ASCII digits")
    else:
        _ok("format_briefing is digits-safe")

    # A digest must state its own age. Read aloud with no date attached, a
    # three-week-old digest is indistinguishable from this morning's.
    from datetime import timedelta
    from core.timefmt import now_mmt
    stale = nr.format_digest({
        "full_report": "<b>အနှစ်ချုပ်</b> အကြောင်းအရာ",
        "created": now_mmt() - timedelta(days=20),
        "target_date": "2026-09-07",
    })
    if not stale:
        _fail("format_digest produced nothing for a valid digest")
    elif "ရက်က" not in stale:
        _fail("format_digest did not state the age of a 20-day-old digest")
    elif re.search(r"[0-9]", stale):
        _fail("format_digest emitted ASCII digits")
    else:
        _ok("format_digest states its own age and is digits-safe")


# ── 3b. outlet + day ─────────────────────────────────────────────────────────

def check_outlet_tool() -> None:
    print("=" * 78)
    print("3b. OUTLET + DAY  ('BBC မှာ ဒီနေ့သတင်းတွေ ဘာထူးလဲ')")

    from core import newsroom_client as nr

    cases = [
        ("BBC", "bbcburmese"), ("bbc", "bbcburmese"), ("ဘီဘီစီ", "bbcburmese"),
        ("ဘီဘီစီ မြန်မာ", "bbcburmese"), ("BBC Burmese", "bbcburmese"),
        ("ဧရာဝတီ", "irrawaddy"), ("Irrawaddy", "irrawaddy"),
        ("The Irrawaddy", "irrawaddy"),
        ("PPIB", "ppib"), ("ppib", "ppib"), ("သမ္မတရုံး", "ppib"),
        ("နိုင်ငံပိုင်မီဒီယာ", "ppib"),
    ]
    bad = [(s, nr.resolve_outlet(s)[0], want) for s, want in cases
           if nr.resolve_outlet(s)[0] != want]
    if bad:
        for s, got, want in bad:
            _fail(f"resolve_outlet({s!r}) -> {got!r}, expected {want!r}")
    else:
        _ok(f"all {len(cases)} outlet spellings resolve (Burmese, English, alias)")

    # A wrong outlet is a confident wrong answer, so refusing beats guessing.
    guessed = [u for u in ("ရိုက်တာ", "Reuters", "Al Jazeera", "", "   ")
               if nr.resolve_outlet(u)[0] is not None]
    if guessed:
        _fail(f"resolve_outlet guessed an outlet for {guessed} — it must refuse")
    else:
        _ok("unmonitored outlets are refused, not guessed")

    # The Irrawaddy re-posts a story under a new caption; both rows land in the
    # database and would otherwise be read out twice with a count that is wrong.
    same = "သမ္မတ အိုဘားမား ကလည်း ဒေါ်အောင်ဆန်းစုကြည်ဟာ စကားကို ညင်သာစွာ ပြောဆိုတတ်"
    if nr._story_key(same) != nr._story_key(same + "…"):
        _fail("_story_key does not collapse a re-post differing by a trailing …")
    elif nr._story_key("ဘန်ကောက် ရေကြီးမှု") == nr._story_key("ရွှေဈေးဈေး မြင့်တက်"):
        _fail("_story_key merged two unrelated headlines")
    else:
        _ok("_story_key collapses a re-post and keeps different stories apart")

    # The numbering must count what is SHOWN. An item whose headline cleans to
    # nothing used to be skipped in the loop while `enumerate` and len(items)
    # carried on counting it, so the answer said "သတင်း ၂ ပုဒ်" and then began at
    # "၂။" — one story missing and the count one too high. Measured on PPIB
    # 2026-09-27, whose first article of that day is titled with one emoji.
    _items = [
        {"title": "🌾", "source": "PPIB", "published": None, "bullets": []},
        {"title": "ချမ်းမြေ့ဆရာတော်ဘုရားကြီး၏ အန္တိမအဂ္ဂိဈာပန", "source": "PPIB",
         "published": None, "bullets": []},
    ]
    from datetime import date as _d
    _txt = nr.format_outlet_news("PPIB", _d(2026, 9, 27), _items)
    # The header sentence also ends with "။", so match the numbered lines only.
    _body = [ln for ln in _txt.splitlines() if re.match(r"^[၀-၉]+။", ln.strip())]
    if len(_body) != 1 or not _body[0].startswith("၁။"):
        _fail(f"an unreadable item shifted the numbering: {_body!r}")
    elif "၁ ပုဒ်" not in _txt:
        _fail(f"the count still includes the unreadable item: {_txt.splitlines()[0]!r}")
    else:
        _ok("an unreadable item is not counted, and the numbering has no gap")

    # The tool must be callable and must not speak ASCII digits.
    try:
        from actions.newsroom_outlet import newsroom_outlet_news
        text = newsroom_outlet_news({"outlet": "BBC", "days_ago": 0})
    except Exception as e:
        _fail(f"newsroom_outlet_news raised: {type(e).__name__}: {e}")
        return
    if re.search(r"[0-9]", text):
        _fail("newsroom_outlet_news emitted ASCII digits")
    else:
        _ok("newsroom_outlet_news answers without ASCII digits")

    unknown = newsroom_outlet_news({"outlet": "ရိုက်တာ", "days_ago": 0})
    if "မဖော်ထုတ်နိုင်ပါ" not in unknown:
        _fail("an unmonitored outlet did not produce the honest refusal")
    else:
        _ok("an unmonitored outlet is refused with the three it does have")


# ── 3c. story resolution + coverage ──────────────────────────────────────────

# A fabricated pair for the formatter tests: one outlet that carried the story
# with an analysed report, and one feed match that has only a headline. The two
# are deliberately different shapes, because keeping them visibly different in
# the answer is the point.
FAKE_STORY = {
    "article_id": "aaaa-bbbb",
    "source_id": "bbcburmese",
    "source": "BBC Burmese",
    "title": "ဘန်ကောက်တွင် ရေကြီးမှု",
    "published": None,
}
FAKE_REPORT = {
    "headline": "ဘန်ကောက်တွင် ရေကြီးမှု အဆိုးဆုံးအခြေအနေ",
    "bullets": ["မြို့နယ် ၅၀ အရေးပေါ်ကြေညာ", "လမ်းပန်းဆက်သွယ်ရေး ရပ်တန့်"],
    "comparison": ["အခြားသတင်းဌာနများတွင် သီးခြားဖော်ပြချက် မတွေ့ရှိသေးပါ။"],
}
FAKE_COVERAGE = {
    "The Irrawaddy": [{
        "source": "The Irrawaddy", "title": "ဘန်ကောက်ရေဘေး", "url": "",
        "published": None, "bullets": ["ဒေသခံများ ဘေးလွတ်ရာသို့ ရွှေ့ပြောင်း"],
        "headline": "ဘန်ကောက်ရေဘေး ဒေသခံများ ရွှေ့ပြောင်း",
        "shared_terms": ["ဘန်ကောက်", "ရေဘေး"],
    }],
}


def check_story_matching() -> None:
    print("=" * 78)
    print("3c. STORY MATCHING  (a false 'yes' is the worst answer this can give)")

    from core import newsroom_client as nr
    from core.timefmt import now_mmt

    # A Burmese particle is four codepoints, so any length test written in
    # characters counts it as a word. Measured: "လို့" passed and helped match
    # two unrelated stories, because it appeared in both.
    cases = [("လို့", 1), ("ရဲ့", 1), ("ဘန်ကောက်", 4), ("ထိုင်းနိုင်ငံ", 5),
             ("Irrawaddy", 9)]
    bad = [(t, nr._weight(t), want) for t, want in cases if nr._weight(t) != want]
    if bad:
        for t, got, want in bad:
            _fail(f"_weight({t!r}) = {got}, expected {want}")
    else:
        _ok("particles weigh one letter and words weigh their consonants")

    if "လို့" in nr._core_tokens("အဆိုးဆုံးရေဘေးကိုကြုံနေရတယ် လို့ မြို့ခံတချိ"):
        _fail("_core_tokens kept a one-letter particle as a distinctive phrase")
    else:
        _ok("_core_tokens drops particles (min_weight, not min_len)")

    # The exact live false positive: a country name and a city name shared with
    # two unrelated stories. Both must be filtered out by the outlet's own pool.
    pool = [
        "ဘန်ကောက်တွင် စစ်လက်နက်များ သိုလှောင်ထားသူ ဗိုလ်ချုပ်ဟောင်း မိမိကိုယ်ကို ပစ်ခတ်",
        "ထိုင်းနိုင်ငံဆိုင်ရာ မြန်မာသံအမတ်ကြီး နေပြည်တော်မှ ခေါ်ယူစစ်ဆေးနေ",
        "ဘန်ကောက်တွင် မိုးကြီး၍ ရေကြီးမှုများကြောင့် စတိုးဆိုင်များ ပိတ်",
        "ထိုင်းနိုင်ငံ ဘန်ကောက်မှာ လေဖိအားနည်းရပ်ဝန်း ဖြစ်ပေါ်",
        "ဘန်ကောက် ရေနုတ်မြောင်းစနစ် ဒီဇိုင်းထက် ကျော်လွန်",
        "ထိုင်းနိုင်ငံတွင် မြန်မာလုပ်သားများ ငွေလွှဲစနစ်",
    ]
    target_tokens = ["ဘန်ကောက်", "ထိုင်းနိုင်ငံ", "အဆိုးဆုံးရေဘေးကိုကြုံနေရတယ်"]
    kept = nr._distinctive(target_tokens, pool)
    if "ဘန်ကောက်" in kept or "ထိုင်းနိုင်ငံ" in kept:
        _fail(f"_distinctive kept a place name shared by {len(pool)} articles: {kept}")
    else:
        _ok("_distinctive drops geography that the outlet's own articles share")
    if "အဆိုးဆုံးရေဘေးကိုကြုံနေရတယ်" not in kept:
        _fail("_distinctive dropped a phrase that appears nowhere else in the pool")
    else:
        _ok("_distinctive keeps a phrase unique to the story")

    # Two bars: a plain count, and a count of the tokens that survived.
    if nr._score(target_tokens, kept, "ဘန်ကောက်တွင် ရေကြီးမှု") != (0, 1):
        _fail("_score did not report (0 distinctive, 1 overall) for a geography-only match")
    else:
        _ok("_score separates 'shares a phrase' from 'shares a distinctive phrase'")

    # The cache key must identify the STORY. It was built from article_id, which
    # recent_reports() did not carry, so every story shared "coverage:None:3" and
    # the second question inside the 90 s window got the first story's answer.
    keys: list[str] = []
    real_cached = nr._cached
    nr._cached = lambda key, produce, default: (keys.append(key), default)[1]
    try:
        for title in ("ဘန်ကောက်တွင် ရေကြီးမှု", "ရွှေဈေးဈေး မြင့်တက်"):
            nr.coverage_in_other_outlets({"title": title, "published": now_mmt()}, 3)
    finally:
        nr._cached = real_cached
    if len(set(keys)) != 2:
        _fail(f"coverage cache keys are not story-specific: {keys}")
    elif any(":None:" in k for k in keys):
        _fail(f"coverage cache key fell back to None: {keys}")
    else:
        _ok("the coverage cache key is story-specific without an article id")

    # ── the analyser's comparison is the authority, and polarity decides ──
    # These are the live sentences that broke the first version, quoted from
    # real reports. A substring test on the outlet name calls all three of them
    # coverage; only the first is.
    _attributed = ("BBC Burmese (၂၀၂၆-၀၉-၂၇) ၏ ဖော်ပြချက်အရ ဘန်ကောက်မြို့တွင် "
                   "ဆယ်စုနှစ်တစ်ခုကျော်အတွင်း အဆိုးဆုံးရေဘေးကို ကြုံနေရသည်။")
    _denied = ("BBC Burmese၊ PPIB を 비롯한 အခြားသတင်းဌာနများတွင် ဤနေ့ "
               "ဤသတင်းကို တစ်ခုမဆို တွေ့ရှိလို့ မရပါ။")
    _checked = ("BBC Burmese၊ PPIB စသည့် အခြားသတင်းဌာနများတွင် "
                "ဤသတင်း မတွေ့ရှိသေးပါ။")

    if nr._verdict_for(_attributed, "bbcburmese")[0] != nr.COVERED:
        _fail("a positive attribution was not read as coverage")
    else:
        _ok("an attributed mention reads as coverage")

    for label, sentence in (("we could not find it", _denied),
                            ("not found yet", _checked)):
        verdict = nr._verdict_for(sentence, "bbcburmese")[0]
        if verdict == nr.COVERED:
            _fail(f"a '{label}' sentence was read as coverage — the analyser "
                  f"names outlets MOST OFTEN when denying them")
        else:
            _ok(f"a naming-but-denying sentence ('{label}') is not coverage")

    # The date the analyser puts beside an outlet is how the right article is
    # picked out of that outlet's output, so it has to survive Burmese digits.
    from datetime import date as _date
    if nr._dates_in("BBC Burmese (၂၀၂၆-၀၉-၂၇) ၏ ဖော်ပြချက်အရ") != [_date(2026, 9, 27)]:
        _fail("a Burmese-digit date was not read out of the comparison section")
    else:
        _ok("a Burmese-digit date in the section is parsed")

    # ── the two tools, with no database at all ──
    from pathlib import Path as _Path
    from actions.newsroom_compare import newsroom_compare_coverage
    from actions.newsroom_story import newsroom_story_summary
    from actions import _newsroom_common as common

    # An index with nothing displayed must say so rather than answer about a
    # story the user never saw.
    common.remember([])
    msg = newsroom_story_summary({"index": 2})
    if "မရှိသေးပါ" not in msg:
        _fail(f"an index with an empty reference list did not refuse: {msg[:60]!r}")
    else:
        _ok("an item number with nothing displayed is refused, not guessed")

    original = nr.env_path
    try:
        nr.env_path = lambda: _Path(ROOT / "definitely_not_here.env")
        nr._client, nr._client_tried, nr._client_error = None, False, ""
        for name, call in (("newsroom_story_summary", lambda: newsroom_story_summary({"index": 1})),
                           ("newsroom_compare_coverage", lambda: newsroom_compare_coverage({"index": 1}))):
            text = call()
            if "မချိတ်ဆက်နိုင်ပါ" not in text:
                _fail(f"{name} did not degrade cleanly with no database: {text[:60]!r}")
        _ok("both story tools degrade to a spoken message, never an exception")
    finally:
        nr.env_path = original
        nr._client, nr._client_tried, nr._client_error = None, False, ""
        common.remember([])

    # ── formatting, both branches ──
    summary = nr.format_story_summary(FAKE_STORY, FAKE_REPORT)
    if FAKE_REPORT["headline"] not in summary:
        _fail("format_story_summary did not lead with the report's headline")
    elif FAKE_STORY["title"] in summary and FAKE_REPORT["headline"] not in summary:
        _fail("format_story_summary led with the stored title instead of the headline")
    elif re.search(r"[0-9]", summary):
        _fail("format_story_summary emitted ASCII digits")
    else:
        _ok("format_story_summary leads with the headline and is digits-safe")

    none_found = nr.format_comparison(FAKE_STORY, {}, FAKE_REPORT)
    if "မတွေ့ရှိပါ" not in none_found:
        _fail("format_comparison did not say plainly that nobody else carried it")
    elif "ရှာဖွေခဲ့သည့်" not in none_found:
        _fail("format_comparison did not name which outlets were searched")
    elif re.search(r"[0-9]", none_found):
        _fail("format_comparison (empty) emitted ASCII digits")
    else:
        _ok("an empty result is honest and names the outlets that were searched")

    found = nr.format_comparison(FAKE_STORY, FAKE_COVERAGE, FAKE_REPORT)
    if "တွေ့ရပါတယ်" not in found:
        _fail("format_comparison did not report a match it was given")
    elif "The Irrawaddy" not in found:
        _fail("format_comparison dropped the outlet that carried the story")
    elif re.search(r"[0-9]", found):
        _fail("format_comparison (match) emitted ASCII digits")
    else:
        _ok("a match names the outlet, its headline and the shared phrases")

    # ── the scope is the newsroom's three outlets, and nothing else ──
    # An earlier version also read feeds from outside the newsroom — DVB, RFA,
    # Myanmar Now, Than Lwin Times — which come from a SEPARATE registry
    # (`config/api_keys.json → news_sources`, `actions/web_search.py →
    # OUTLET_REGISTRY`). Two outlet lists exist in this project and they are not
    # the same list. A comparison that blends them puts a headline word-match
    # beside an analysed report as though the two were the same evidence.
    names = nr.other_outlet_names(FAKE_STORY)
    keys_seen = [nr._outlet_key(n) for n in names]
    if len(keys_seen) != len(set(keys_seen)):
        _fail(f"other_outlet_names listed an outlet twice: {names}")
    elif "bbcburmese" in keys_seen:
        _fail("other_outlet_names listed the story's own outlet as an other outlet")
    elif set(keys_seen) != {"ppib", "theirrawaddy"}:
        _fail(f"other_outlet_names is not the newsroom's other two outlets: {names}")
    else:
        _ok(f"the searched list is exactly the newsroom's other two outlets ({len(names)})")

    stray = [n for n in names if any(
        s in n.upper() for s in ("DVB", "RFA", "GNLM", "MIZZIMA", "FRONTIER", "THAN LWIN"))]
    if stray:
        _fail(f"a non-newsroom outlet reached the comparison: {stray}")
    else:
        _ok("no outlet from the open-web registry leaks into the comparison")

    # The layer must be gone from the code, not merely unreferenced.
    import inspect
    client_src = inspect.getsource(nr)
    still_there = [gone for gone in ("coverage_on_the_web", "_WEB_OUTLET_IDS", "OUTLET_REGISTRY")
                   if gone in client_src]
    if still_there:
        _fail(f"core/newsroom_client.py still references the removed web layer: {still_there}")
    else:
        _ok("the open-web coverage layer is gone from core/newsroom_client.py")

    sig = inspect.signature(nr.format_comparison)
    if "web" in sig.parameters or "unreachable" in sig.parameters:
        _fail(f"format_comparison still accepts the removed layers: {sig}")
    else:
        _ok("format_comparison takes only the newsroom's own coverage")


# ── 4. gates ─────────────────────────────────────────────────────────────────


# ── 4. gates ─────────────────────────────────────────────────────────────────

def check_gates() -> None:
    print("=" * 78)
    print("4. GATES  (the reason this feature does not become annoying)")

    from datetime import datetime, timedelta
    from core import newsroom_watch as nw
    from core.timefmt import MMT

    def at(hour: int) -> datetime:
        return datetime(2026, 9, 27, hour, 0, tzinfo=MMT)

    # Default window 22:00-06:00 wraps midnight; a naive range check gets this
    # exactly backwards and would announce at 3am while staying silent at noon.
    cases = [(23, True), (3, True), (5, True), (6, False), (12, False), (21, False), (22, True)]
    bad = [h for h, want in cases if nw.in_quiet_hours(at(h)) != want]
    if bad:
        _fail(f"quiet-hours window wrong at hour(s) {bad} (expected 22:00-06:00)")
    else:
        _ok("quiet hours 22:00-06:00 wrap midnight correctly")

    # The switch must actually gate. Read it rather than assume it.
    watcher = nw.NewsroomWatcher(logger=lambda m: None)
    watcher._started_at = -1e9            # pretend the session is long running
    watcher._last_announced = -1e9
    ok, why = watcher.should_announce(awake=True, speaking=False,
                                      last_user_speech=-1e9, now=at(12))
    enabled = nw.enabled()
    print(f"  enabled()              : {enabled}")
    print(f"  should_announce(noon)  : {ok}  ({why})")
    if enabled and not ok:
        _fail(f"should_announce refused everything with the switch on: {why}")
    if not enabled and ok:
        _fail("should_announce allowed an announcement with the switch off")

    for label, kwargs, expect in (
        ("asleep",       dict(awake=False, speaking=False, last_user_speech=-1e9, now=at(12)), False),
        ("speaking",     dict(awake=True,  speaking=True,  last_user_speech=-1e9, now=at(12)), False),
        ("just spoke",   dict(awake=True,  speaking=False, last_user_speech=0.0,  now=at(12)), False),
        ("quiet hours",  dict(awake=True,  speaking=False, last_user_speech=-1e9, now=at(23)), False),
    ):
        got, _r = watcher.should_announce(**kwargs)
        if got != expect:
            _fail(f"gate '{label}' returned {got}, expected {expect}")

    # Startup grace: a freshly constructed watcher must refuse even with the
    # switch on and every other condition met.
    fresh = nw.NewsroomWatcher(logger=lambda m: None)
    fresh._last_announced = -1e9
    got, why = fresh.should_announce(awake=True, speaking=False,
                                     last_user_speech=-1e9, now=at(12))
    if got:
        _fail("a just-started session was allowed to announce (startup grace missing)")
    else:
        _ok(f"startup grace holds announcements for {nw.STARTUP_GRACE_SECONDS:.0f}s ({why})")

    # An unseeded watcher must seed, not announce the backlog.
    watcher2 = nw.NewsroomWatcher(logger=lambda m: None)
    watcher2._seeded = False
    watcher2._last_seen = None
    try:
        returned = watcher2.poll()
    except Exception as e:
        _fail(f"poll() raised on an unseeded watcher: {type(e).__name__}: {e}")
        return
    if returned:
        _fail(f"an unseeded poll returned {len(returned)} item(s) — it must seed instead")
    else:
        _ok("first poll seeds the marker and announces nothing")

    # Requeue must not allow a double announcement.
    item = {"report_id": "r1", "headline": "h"}
    w = nw.NewsroomWatcher(logger=lambda m: None)
    w.requeue([item])
    w.requeue([item])
    if len(w.take_pending()) != 1:
        _fail("requeue() allowed the same report to be buffered twice")
    else:
        _ok("requeue() deduplicates on report_id")


# ── 5. registration ──────────────────────────────────────────────────────────

def check_registration() -> None:
    print("=" * 78)
    print("5. REGISTRATION  (a TOOL that fails validation is skipped in silence)")

    from core.action_loader import discover_actions

    registry = discover_actions(ROOT / "actions", logger=lambda m: None)
    names = registry.names()
    print(f"  actions discovered     : {len(names)}")

    for want in ("daily_briefing", "newsroom_search", "newsroom_outlet_news",
                 "newsroom_digest", "newsroom_status", "newsroom_story_summary",
                 "newsroom_compare_coverage"):
        if want in names:
            _ok(f"tool '{want}' is offered to the model")
        else:
            _fail(f"tool '{want}' is NOT registered — the model can never call it")

    # The specific regression this guards against: daily_briefing must survive
    # actions/web_search.py losing the function it used to import at module level.
    import actions.daily_briefing as db
    if not callable(getattr(db, "daily_briefing", None)):
        _fail("actions.daily_briefing.daily_briefing is not callable")
    else:
        _ok("actions/daily_briefing.py imports cleanly (web path is now optional)")

    import actions.web_search as ws
    if not hasattr(ws, "_briefing"):
        print("      note: actions/web_search.py has no _briefing — the open-web")
        print("            fallback is unavailable, so daily_briefing will answer")
        print("            from the newsroom only. See backup/ for the original.")


# ── 6. live ──────────────────────────────────────────────────────────────────

def check_live() -> None:
    print("=" * 78)
    print("6. LIVE  (the real database)")

    from core import newsroom_client as nr

    ok, reason = nr.available()
    if not ok:
        _fail(f"cannot reach the database: {reason}")
        return
    _ok("connected")

    status = nr.pipeline_status()
    counts = status.get("counts") or {}
    print(f"  article counts         : {counts}")
    print(f"  last run               : {status.get('last_run')}")
    print(f"  newest report          : {status.get('newest_report')}")

    reports = nr.recent_reports(hours=36, limit=6)
    print(f"  reports in last 36h    : {len(reports)}")
    if not reports:
        print("      note: nothing in the last 36h — the briefing would fall back")
        print("            to the open web. Check the newsroom's auto_runner.")
    else:
        text = nr.format_briefing(reports)
        if re.search(r"[0-9]", text):
            _fail("the live briefing contains ASCII digits")
        else:
            _ok("live briefing is digits-safe")
        print("  ---- what JARVIS would say ----")
        for line in text.splitlines()[:14]:
            print(f"  | {line}")
        print("  -------------------------------")

    marker = nr.newest_marker()
    print(f"  watcher high-water mark: {marker}")
    if marker is None:
        _fail("newest_marker() returned None against a reachable database")

    # ── the regression this whole feature was built around ──
    # The headline JARVIS reads out comes from the ANALYSED REPORT, not from
    # news_articles.title — the analyzer rewrites it. So resolving a headline the
    # user repeats needs a report-text search. Measured before the fix: four of
    # four briefed headlines missed find_story() entirely, and repeating a
    # headline heard a minute earlier answered "not found".
    if reports:
        target = next((r for r in reports if r.get("article_id") and r.get("headline")), None)
        if not target:
            print("      note: no report carries both an article id and a headline")
        else:
            art = nr.find_story(target["headline"])
            if not art:
                _fail(f"find_story() could not resolve a headline it had just read out: "
                      f"{target['headline'][:45]!r}")
            elif art.get("article_id") != target["article_id"]:
                _fail(f"the spoken headline resolved to a DIFFERENT article: "
                      f"{target['headline'][:40]!r} -> {str(art.get('title'))[:40]!r}")
            else:
                _ok("a spoken headline resolves back to its own article")

            back = nr.article_by_id(target["article_id"])
            if not back or back.get("article_id") != target["article_id"]:
                _fail("article_by_id() did not round-trip")
            else:
                _ok("article_by_id() round-trips")

            # A later "the second one" resolves against this list, so it has to
            # be the list that was numbered — same length, same order.
            items = nr.briefing_items(reports)
            text = nr.format_briefing(reports)
            if len(items) > 5:
                _fail(f"briefing_items() returned {len(items)} for a five-item briefing")
            elif items and text:
                first = items[0].get("headline") or items[0].get("title") or ""
                if first and first not in text:
                    _fail("the first remembered item is not the first one read out")
                else:
                    _ok("the remembered reference list matches the numbered briefing")
            else:
                _ok("briefing_items() is empty because the briefing is empty")


def main() -> int:
    print("JARVIS <-> AI Newsroom bridge check")
    print()

    check_config()
    check_bridge()
    check_formatting()
    check_outlet_tool()
    check_story_matching()
    check_gates()
    check_registration()
    if "--live" in sys.argv:
        check_live()
    else:
        print("=" * 78)
        print("6. LIVE  (skipped — pass --live to read the real database)")

    print("=" * 78)
    if problems:
        print(f"RESULT: {len(problems)} PROBLEM(S)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("RESULT: ALL OK")
    if "--live" not in sys.argv:
        print("        (offline only — re-run with --live to test the database)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
