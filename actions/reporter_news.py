"""Search the two state newspapers — မြန်မာ့အလင်း and ကြေးမုံ.

THE WORKFLOW THIS SERVES

    "ပညာရေးအကြောင်း သတင်းရှိလား"
        → search: how many, and over which dates
    "စက်တင်ဘာ ၁၅ ရက်က သတင်း ပြောပြပါ"
        → day: that date's articles
    "ဒီသတင်းနဲ့ ပတ်သက်ပြီး အရင်က ရှိခဲ့ဖူးလား"
        → timeline: the same keyword, oldest first

THE RULE THAT MATTERS MOST

    The database covers **September 2026 only** — measured 2026-09-29: 7,073 of
    7,090 rows are this month, and there is nothing at all from 2025 or from
    January to July 2026.

    So an empty result has two possible meanings and they are not the same:

        "အရင် မရှိခဲ့ဘူး"        a claim about the world
        "ဒီကာလအတွင်း မတွေ့ပါ"     a claim about this database

    For a journalist the first is a finding and the second is a limitation.
    Saying the first on the strength of four weeks of data would mean reporting
    that something was never covered. **Every answer here states the window.**

TWO OTHER THINGS IT REFUSES TO DO

    - It does not read out glyph noise. 646 rows (9%) are `/g167/g136/g3/...`
      from a PDF whose text layer failed; they match keyword searches and would
      be spoken as news. They are detected and skipped.
    - It does not use `fn_search_news`. Measured: that RPC returns `similarity=1`
      for every row and includes articles that do not contain the search term at
      all — three of five for `ပညာရေး`. A substring match cannot produce that
      false positive, which is exactly what "is there news about X" needs.
"""
from __future__ import annotations

import re

from core.entities import ministries_across, people_in
from core.reporter_client import (
    all_articles_matching,
    all_articles_on,
    articles_on,
    available,
    content_rows,
    coverage,
    date_range_for,
    days_for,
    editions_with_content,
    paper_counts,
    papers_with_content,
    readable_only,
    search_count,
    timeline,
)
from core.timefmt import to_burmese_digits

# The sentences that keep a failed read, an unreadable paper and an empty
# result apart — and the date/paper helpers — are shared with the section tool,
# so they live in `_reporter_common` and are imported here. They were defined in
# this file until 2026-09-30, when `actions/news_section.py` needed the same
# three-sentence rule; copying it would have created a second definition of what
# a limitation sounds like, which is the defect class this project already has a
# rule against. Re-importing keeps `reporter_news._window_line` working, which
# `check_agent.py` relies on.
from actions._reporter_common import (                      # noqa: F401
    _article_line,
    _date,
    _date_or_newest,
    _elsewhere_people,
    _elsewhere_search,
    _hollow_papers,
    _infer_paper,
    _newest_edition,
    _other_paper,
    _paper_scope,
    _read_failed,
    _short_date,
    _unreachable,
    _window_line,
)

# The furniture of a newspaper question: the day words, the paper names, the
# act of asking, and the word "news" itself. `_extract_topic` strips these to
# find out whether a real topic word is left.
#
# Every entry is measured from a question the owner actually asked — these are
# not a guess at Burmese grammar. Longer phrases come first in the tuple so
# `သတင်းစာမှာ` is removed before `သတင်း`, which is what stops the leftover `စာမှာ`
# from being read as a topic.
_TOPIC_FURNITURE = (
    # "in today's newspaper" / "in the paper of that day". Longest first: the
    # paper names are inside these, and removing the whole phrase first is what
    # keeps the remainder from reading as a topic.
    "ဒီနေ့ကြေးမုံသတင်းစာမှာ", "ဒီနေ့ကြေးမုံသတင်းစာထဲ",
    "ဒီနေ့မြန်မာ့အလင်းသတင်းစာမှာ", "ဒီနေ့မြန်မာ့အလင်းသတင်းစာထဲ",
    "ဒီနေ့သတင်းစာမှာ", "ဒီနေ့သတင်းစာထဲ",
    "သတင်းစာမှာ", "သတင်းစာထဲ", "သတင်းစာ",
    # the day word
    "ဒီနေ့", "ယနေ့", "မနေ့က",
    # the paper names themselves — a paper name is not a topic
    "မြန်မာ့အလင်း", "ကြေးမုံ",
    # the act of asking. `ပါသလဲ` is the form the owner actually uses; `ပါသလား`
    # is the other. Both are here — measured 2026-09-30, leaving one out put it
    # in the topic string and the narrowing searched for a question.
    "ဘယ်သူတွေရဲ့", "ဘယ်သူတွေ", "ဘယ်သူ့", "ဘယ်သူ", "ဘယ်ဝန်ကြီး",
    "သတင်းတွေပါလဲ", "သတင်းတွေပါသလဲ", "သတင်းပါလဲ", "သတင်းပါသလဲ",
    "သတင်းတွေ", "သတင်း",
    "ရှိလား", "ပါသလား", "ပါသလဲ", "ပါလား", "ပါလဲ",
    "ပြောပြ", "ဖော်ပြ", "အကြောင်း", "ရဲ့", "မှာ", "ထဲ", "တွေ", "လား",
)

# `_MONTHS`, `_PAPER_NAMES`, `_date`, `_short_date`, `_window_line`,
# `_unreachable`, `_read_failed`, `_date_or_newest`, `_newest_edition`,
# `_paper_scope`, `_other_paper`, `_elsewhere_people`, `_elsewhere_search`,
# `_hollow_papers` and `_article_line` were defined here until 2026-09-30 and
# now live in `actions/_reporter_common.py`, because the section tool needs the
# same three-sentence rule. They are imported at the top of this file, so
# `reporter_news._window_line` still resolves.


def _extract_topic(term: str, rank_src_hint: str = "") -> str:
    """The **topic word** inside a question, or "" when there is not one.

    `term` is whatever the model put in `query`, which is usually the user's
    whole sentence. Using that whole sentence as a substring matches nothing;
    skipping the narrowing entirely brings back the old bug (a real topic word
    inside a sentence gets ignored and the general official list is returned).
    This digs the topic out.

    **Measured 2026-09-30** on *"ဒီနေ့ကြေးမုံသတင်းစာမှာ ပြည်ထောင်စုဝန်ကြီး
    ဘယ်သူတွေရဲ့ သတင်းတွေပါလဲ"*: the topic is the question, not a keyword — every
    word in it is grammar, a paper name, an office, or the word "news". The
    correct answer is therefore "" (no narrowing), and the rank branch answers
    it as the office question it is. So this returns "" more often than not,
    and **that is the safe direction**: with no topic the action falls back to
    the plain "who is named" answer, which is a truthful superset of the
    question rather than a confident miss.

    The words it strips are all measured from the owner's own phrasings. A
    Burmese phrase has no spaces to split on reliably, so it is stripped by
    removing the known furniture and asking whether a real noun is left.
    """
    text = (term or "").strip()
    if not text:
        return ""
    # **Whitespace is not a separator to trust.** The paper and the model both
    # write `ဒီနေ့ သတင်းစာထဲ` and `ဒီနေ့သတင်းစာထဲ`, and a phrase stripped with a
    # space left where the space was does not match the un-spaced form.
    # **But removing ALL spaces breaks the opposite way** — measured 2026-09-30:
    # `ရွှေဈေး` ("gold price") ends in the locative `မှာ`-lookalike `ဈေး`…  the
    # particle strip below is what actually eats a real topic, so it is applied
    # only to the phrase forms above, never to a short standalone word.
    packed = text.replace(" ", "")
    for junk in _TOPIC_FURNITURE:
        packed = packed.replace(junk.replace(" ", ""), " ")
    # The office words are handled by `rank`; leaving them here would make the
    # narrowing search for the office itself, which every relevant row contains.
    for off in ("နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ", "ပြည်ထောင်စုဝန်ကြီး",
                "ဒုတိယဝန်ကြီး", "ဝန်ကြီးချုပ်", "ဝန်ကြီး", "သမ္မတ"):
        packed = packed.replace(off, " ")
    # A **short input that survives intact is already a topic** — `ရွှေဈေး`,
    # `မုန်တိုင်း`, `ပညာရေး`. The furniture above only removes whole question
    # phrases, so anything short left untouched is the answer, and running the
    # particle strip on it would cut a real word down to nothing.
    if len(text) <= 24 and text == packed.replace(" ", ""):
        return text
    packed = packed.strip()
    # What is left must be a plausible content word: at least three syllables
    # (Burmese nouns are rarely shorter).
    if len(re.findall(r"[\u1000-\u1021]", packed)) < 3:
        return ""
    # A long remainder is a second sentence this function should not be trusted
    # to read — return "" and let the caller answer the plain question.
    if len(packed) > 24:
        return ""
    return packed





def reporter_news(parameters: dict = None, player=None, session_memory=None,
                  **_) -> str:
    """Voice entry point.

    **The signature is `(parameters, ...)` and that is not cosmetic.**
    `core/action_loader.py` calls a handler as `fn(parameters=parameters, ...)`,
    so a handler written as `fn(query="", days=0, **_)` silently swallows every
    argument in its own `**_` and runs on defaults. Measured 2026-09-29 in a
    live session: the log showed

        🔧 reporter_news  {'days': 2, 'query': 'မုန်တိုင်း ကယ်ဆယ်ရေး ထောက်ပံ့'}
        📤 reporter_news → ဘာအကြောင်း ရှာရမလဲ ပြောပါ။

    — the arguments arrived and were discarded, and the tool asked the user what
    to search for while holding the query. Every check passed because every
    check called the handler directly with keywords instead of through the
    loader. **Test through the path the application uses, not a convenient one.**

    `days` is the recency window and it exists because of a second measured miss.
    Asked *"လက်ရှိဖြစ်ပေါ်နေတဲ့ မုန်တိုင်းနဲ့ပတ်သက်ပြီး အစိုးရက ဘာတွေ လုပ်ပေးနေလဲ"*
    on 2026-09-29, the search went back to September 1 and answered with three
    weeks of history — **the user asked about now and got a month**. `days=2`
    limits every action to the newest two days the database holds.

    The floor counts back from the newest row, not from `date.today()`, so a
    morning when that day's paper has not arrived yet still returns yesterday's
    news instead of nothing.
    """
    p = parameters or {}
    action = p.get("action", "")
    query = p.get("query", "")
    date = p.get("date", "")
    limit = p.get("limit", 8)
    days = p.get("days", 0)
    paper = str(p.get("paper") or "").strip()
    # The paper is often named in the sentence, not in the parameter. See
    # `_infer_paper` — measured 2026-09-30, "ဒီနေ့ကြေးမုံသတင်းစာမှာ …" arrived
    # with no `paper` and the answer was headed with both paper names.
    paper = _infer_paper(paper, query, p.get("query") or "")

    ok, reason = available()
    if not ok:
        return f"မြန်မာ့အလင်း/ကြေးမုံ database ကို မချိတ်နိုင်ပါ — {reason}"

    act = str(action or "search").strip().lower()
    term = str(query or "").strip()
    date = str(date or "").strip()
    try:
        win = max(0, min(int(days or 0), 30))
    except (TypeError, ValueError):
        win = 0
    try:
        limit = max(1, min(int(limit or 8), 25))
    except (TypeError, ValueError):
        limit = 8

    # ── 1. "X အကြောင်း သတင်းရှိလား" ─────────────────────────────────────────
    if act in ("search", "count", "has"):
        if not term:
            return "ဘာအကြောင်း ရှာရမလဲ ပြောပါ။"
        n = search_count(term, days=win)
        if n < 0:
            # A failed count is not a count of zero. See _unreachable.
            return _unreachable()
        scope = (f" လွန်ခဲ့တဲ့ {to_burmese_digits(win)} ရက်အတွင်း"
                 if win else "")
        if n == 0:
            return (f"'{term}' နဲ့ ကိုက်တဲ့ သတင်း{scope} မတွေ့ပါ။\n\n"
                    f"{_window_line()}\n"
                    f"⚠️ 'အရင် မရှိခဲ့ဘူး' လို့ မဆိုလိုပါ — "
                    f"ဒီကာလအတွင်းမှာ မတွေ့တာပါ။")
        rng = date_range_for(term, days=win)
        out = [f"'{term}' နဲ့ ပတ်သက်တဲ့ သတင်း{scope} "
               f"{to_burmese_digits(n)} ခု တွေ့ပါတယ်။", ""]
        if rng.get("oldest"):
            out.append(f"ရက်စွဲ အကွာအဝေး — {_date(rng['oldest'])} ကနေ "
                       f"{_date(rng['newest'])} အထိ")
        out.append("")
        out.append("ဘယ်ရက်က သတင်း လိုချင်လဲ ပြောပါ — "
                   "ဥပမာ 'စက်တင်ဘာ ၁၅ ရက်က သတင်း ပြောပြပါ'။")
        return "\n".join(out)

    # ── 2. "ဒီရက်က သတင်း ပြောပြပါ" ──────────────────────────────────────────
    if act in ("day", "date", "on"):
        if not date:
            # **`days` is already an answer to "which day".** Measured in a live
            # session 2026-10-01: asked *"မနေ့က ဒုတိယသမ္မတတွေရဲ့ သတင်းရှိလား"*
            # the model called this action as
            # `{'action': 'day', 'query': 'ဒုတိယသမ္မတများ', 'days': 2}` — the
            # right question, the right window, no literal date — and the tool
            # answered **"ဘယ်ရက်လဲ ပြောပါ"**. The user had just said which day.
            #
            # That is the same defect family as a limitation spoken as a
            # finding, one step milder: **a question returned where the answer
            # was already available**. `people` and `ministries` have always
            # resolved a missing date from the window (`_date_or_newest`); the
            # `day` action was the only one that refused.
            #
            # The answer still states the day it used (`_date(date)` heads the
            # list), so nothing is hidden — and the refusal survives for the one
            # case that really has no day: no date **and** no window.
            if win:
                date = _newest_edition(win)
        if not date:
            return "ဘယ်ရက်လဲ ပြောပါ (ဥပမာ 2026-09-15)။"
        raw = articles_on(date, term, limit, paper=paper)
        rows = content_rows(raw)
        note = _paper_scope(date, paper)[1]

        if not rows:
            # Three distinct sentences — see _unreachable / _paper_scope above.
            if note:
                return note
            if _read_failed(date):
                return _unreachable()
            q = ('"' + term + '" နဲ့ ကိုက်တဲ့ ') if term else ''
            return (f"{_date(date)} ရက်နေ့အတွက် "
                    f"{q}"
                    f"သတင်း မတွေ့ပါ။\n\n{_window_line()}")
        q = ('"' + term + '" နဲ့ ကိုက်တဲ့ ') if term else ''
        out = [f"{_date(date)} — "
               f"{q}"
               f"သတင်း {to_burmese_digits(len(rows))} ခု:", ""]
        out += [_article_line(a) for a in rows]
        if len(raw) > len(rows):
            dropped = len(raw) - len(rows)
            out.append(f"  … (ဖတ်လို့မရတဲ့/စာမျက်နှာအမှတ်အသား {to_burmese_digits(dropped)} "
                       f"ခု ဖယ်ထားတယ်)")
        if note:
            out.append("")
            out.append(note)
        if len(rows) >= limit:
            out.append(f"  … (ပထမ {to_burmese_digits(limit)} ခု ပြထားတယ်)")
        return "\n".join(out)

    # ── 5. "ဘယ်ဝန်ကြီးတွေ ပါသလဲ" — WHO, not how many ────────────────────────
    #
    # The question that started this, 2026-09-30: *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာထဲ
    # ဘယ်ဝန်ကြီးတွေ ပါသလဲ"*. It has no keyword — "ဝန်ကြီး" alone matches 775
    # articles and counting them answers nothing. It is a distinct-entity
    # question: read the day (or the window) and list the people the paper
    # names. `core/entities.py` does the reading; this action decides the scope
    # and speaks them with the paper and page each came from.
    if act in ("people", "who", "ministers", "persons"):
        day = date or ""
        # The entity readers, not the spoken-list ones: a cap of 25 rows
        # truncates a "who is named today" answer (measured: 25 rows → 3 people,
        # 328 rows → 12). See `reporter_client._ENTITY_ROWS`.
        #
        # With no date given, read the **newest edition**, not an empty list.
        # Measured 2026-09-30: `all_articles_matching("", …)` returns nothing,
        # so the no-date branch — the ordinary case, since a user says "which
        # ministers are in today's paper" without naming a day — answered
        # "no news found" on an edition holding 12 named officials. The date
        # comes from the database, not the clock, so a morning before today's
        # paper loads still answers from the latest edition it has.
        if not day:
            day = _newest_edition(win)
        if day:
            raw = content_rows(all_articles_on(day, paper=paper))
        else:
            raw = []
        # A topic narrows the day, it does not replace it. Measured 2026-09-30:
        # "ဒီနေ့ သတင်းစာထဲ အာကာသယာဉ်မှူး ပါသလဲ" (is an astronaut mentioned
        # today) returned the *general* list of officials — a different
        # question, answered confidently. When a term is given, keep only rows
        # whose text contains it, so "not there" can be said plainly.
        #
        # **But a `query` is not always a term — often it is the sentence.**
        # Measured 2026-09-30: the model passes the user's whole question in
        # `query` (it is the only free-text slot the tool has), so
        # *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာမှာ နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့
        # သတင်းတွေ ရှိလား"* was used as a literal substring, matched nothing, and
        # the question about the president was answered "no story contains that
        # sentence" — true, useless, and it hid the rank branch below.
        #
        # **Skipping the narrowing wholesale was the first fix and it was too
        # blunt** — measured 2026-09-30 on *"ဒီနေ့ကြေးမုံသတင်းစာမှာ ပြည်ထောင်စုဝန်ကြီး
        # ဘယ်သူတွေရဲ့ သတင်းတွေပါလဲ"*: because the sentence test matched, a real
        # topic word (`အာကာသယာဉ်မှူး`, an astronaut) inside a sentence-shaped query
        # would again be ignored and the general list returned — exactly the bug
        # the narrowing exists to prevent. So the sentence is not skipped; a
        # **term is dug out of it** (below) and only the narrowing is applied to
        # that. Nothing is guessed at when no term can be found: the parameter
        # is dropped and the question is answered as a plain "who is named".
        _topic = _extract_topic(term, rank_src_hint=p.get("query") or "")
        # A named paper is `_paper_scope`'s job; this covers the unnamed case,
        # where the search covered both papers and one of them may be hollow.
        # Computed **before** the topic block, which returns early.
        _hollow = _hollow_papers(day) if not paper else ""
        if _topic and raw:
            _hit = [a for a in raw
                    if _topic in ((a.get("body_text") or "") + " "
                                  + (a.get("headline") or "") + " "
                                  + (a.get("summary") or ""))]
            if not _hit:
                _kind_e, _note_e = _paper_scope(day, paper) if day else ("", "")
                _scope = _date(day) if day else "ဒီကာလအတွင်း"
                # Same rule as the office branch below: when the paper could not
                # be read, "'X' is not in it" is a claim about the newspaper.
                if _kind_e in ("missing", "unreadable", "thin"):
                    return "\n".join([_note_e, "",
                                      _elsewhere_search(day, paper, _topic), "",
                                      _window_line()])
                _out = [f"{_scope} {paper or 'မြန်မာ့အလင်း/ကြေးမုံ'} သတင်း "
                        f"{to_burmese_digits(len(raw))} ခု ဖတ်ပြီးပါပြီ — "
                        f"'{_topic}' ပါတဲ့ သတင်း မတွေ့ပါ။"]
                if _note_e:
                    _out += ["", _note_e]
                if _hollow:
                    _out += ["", _hollow]
                _out += ["", _window_line()]
                return "\n".join(_out)
            raw = _hit
        # ── Which office did the user actually ask about? ──
        # Measured 2026-09-30: *"ပြည်ထောင်စုဝန်ကြီး ဘယ်သူတွေရဲ့ သတင်းပါလဲ"* was
        # answered with 12 names spanning three offices — a union minister, five
        # chief ministers and four deputies. The user asked about one office and
        # got three, which for a journalist is a different answer. A more
        # specific rank in the question wins over the generic `ဝန်ကြီး` inside it.
        #
        # **But a question can name two offices at once.** Measured 2026-09-30:
        # *"နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့ သတင်းတွေ ရှိလား"* asks about
        # the president **and** both vice-presidents, and the president is not a
        # vice-president — the first version kept only the first match and
        # answered about one office out of two. So every office named is
        # collected, most specific first, and they are passed together.
        #
        # The two state offices lead the tuple because they are the most senior:
        # with the old minister-only tuple this question matched no rank at all
        # and was answered as a generic "who is named" list — three ministers,
        # which is not what was asked.
        #
        # **This block sits above the `if not raw` return on purpose.** It used
        # to sit below it, which meant the pointer to the other paper (see the
        # note there) could not name the office that was asked about.
        _rank_src = f"{term} {p.get('query') or ''}"
        _OFFICES = ("နိုင်ငံတော်သမ္မတ", "ဒုတိယသမ္မတ", "ပြည်ထောင်စုဝန်ကြီး",
                    "ဒုတိယဝန်ကြီး", "ဝန်ကြီးချုပ်")
        _found: list[str] = []
        for _r in _OFFICES:
            # `သမ္မတ` alone means the president; `ဒုတိယသမ္မတ` contains it, so the
            # vice-president is matched by its own entry above and the bare form
            # is only consulted when the longer rank did not already match.
            if _r in _rank_src:
                _found.append(_r)
                continue
            if _r == "နိုင်ငံတော်သမ္မတ" and "သမ္မတ" in _rank_src:
                _found.append("နိုင်ငံတော်သမ္မတ")
        if not _found and "ဝန်ကြီး" in _rank_src:
            _found.append("ဝန်ကြီး")
        rank = ",".join(_found)

        _kind, note = _paper_scope(day, paper) if day else ("", "")

        if not raw:
            if note:
                # **The paper yielded no readable rows at all — and this branch
                # returned the warning ALONE.** Measured 2026-10-01:
                # `reporter_news(people, paper='မြန်မာ့အလင်း', date='2026-10-01')`
                # answered with the limitation and nothing else, while
                # `_elsewhere_people` — written for exactly this case — sat
                # unreachable below, in a branch that only runs when the paper
                # *did* yield rows. The owner's ask is "ဘက်စုံထောင့်စုံ": say
                # what could not be read **and** where it can be found. The
                # 2026-09-30 live session that motivated the pointer was exactly
                # this case, and the fix had landed one branch too low.
                _out = [note, ""]
                _elsewhere = _elsewhere_people(day, paper, rank)
                if _elsewhere:
                    _out += [_elsewhere, ""]
                _out.append(_window_line())
                return "\n".join(_out)
            if day and _read_failed(day):
                return _unreachable()
            scope = _date(day) if day else "ဒီကာလအတွင်း"
            return (f"{scope} {paper or 'သတင်းစာ'} မှာ "
                    f"'{term or 'ဝန်ကြီး'}' နဲ့ ကိုက်တဲ့ "
                    f"ဖတ်လို့ရတဲ့ သတင်း မတွေ့ပါ။\n\n{_window_line()}")

        # The office the question names is worked out **above** the `if not raw`
        # return, so that the pointer at the other paper can name the same
        # office. `rank` is already in scope here.

        people = people_in(raw, limit, rank=rank)
        if not people and not date and not raw:
            # A no-date question whose newest edition turned out to hold no
            # readable text: say that, name the edition that does, and ask.
            # Measured 2026-09-30, a half-ingested newest date gives 0 raw rows
            # and the old wording would have read "0 stories read — no officials
            # found", which sounds like a finding about the paper rather than
            # about the pipeline.
            _eds = editions_with_content(5)
            _latest = f"🗞️ နောက်ဆုံး အကြောင်းအရာ ပါတဲ့ ထုတ်ဝေမှု — {_date(_eds[0])}" \
                if _eds else ""
            return (f"⚠️ ဒီနေ့ ({_date(day)}) သတင်းစာ ထုတ်ဝေမှုကို database မှာ "
                    f"ရှိပေမယ့် ဖတ်လို့ရတဲ့ သတင်း စာသား မပါသေးပါ — "
                    f"ဒါက '{paper or 'သတင်းစာ'}' မှာ ပုဂ္ဂိုလ် မပါဘူးလို့ "
                    f"မဆိုလိုပါ။\n\n"
                    f"➡️ ဘယ်ရက်နေ့ သတင်းစာကို စစ်ပေးရမလဲ? "
                    f"(ဥပမာ 'ဧပြီ ၂၄ ရက် မြန်မာ့အလင်း')\n"
                    + (f"\n{_latest}\n" if _latest else "")
                    + f"\n{_window_line()}")
        where = f"{_date(day)}" if day else "ဒီကာလအတွင်း"
        who = paper or "မြန်မာ့အလင်း/ကြေးမုံ"
        # The generic fallback is only for the "who is named at all" question.
        # When the user named an office we say that office back, so a miss reads
        # as "no president named" rather than as a vague list failure. Two
        # offices are spoken as a list ("A၊ B"), not as a comma-glued token.
        _asked = "၊ ".join(o for o in (rank.split(",") if rank else []) if o) \
            or "ဝန်ကြီး"
        if not people:
            # **A limitation must not be spoken as a finding.** When the paper
            # the user named could not be read, "no such person" is a claim
            # about the newspaper, and it is false — the paper was never read.
            # Measured in a live voice session 2026-09-30: the owner asked about
            # ပြည်ထောင်စုဝန်ကြီး in မြန်မာ့အလင်း, the tool answered *"…လူပုဂ္ဂိုလ်
            # မတွေ့ပါ"* with the hollow-paper warning underneath, and the model
            # spoke the first line. So: lead with the limitation, and point at
            # the paper that does carry the answer instead of leaving nothing.
            if _kind in ("missing", "unreadable", "thin"):
                out = [note, ""]
                _elsewhere = _elsewhere_people(day, paper, rank)
                if _elsewhere:
                    out += [_elsewhere, ""]
                out.append(_window_line())
                return "\n".join(out)
            out = [f"{where} {who} သတင်း {to_burmese_digits(len(raw))} ခု "
                   f"ဖတ်ပြီးပါပြီ — ဒါပေမယ့် '{_asked}' ရာထူးနဲ့ "
                   f"အမည် တွဲပါတဲ့ လူပုဂ္ဂိုလ် မတွေ့ပါ။"]
            if note:
                out += ["", note]
            # No paper was named, so the search covered both — and if one of them
            # is unreadable, "I checked both papers" is not true. Measured in the
            # live session: the model said exactly that while မြန်မာ့အလင်း held
            # 1 readable row out of 23.
            if _hollow:
                out += ["", _hollow]
            out += ["", _window_line()]
            return "\n".join(out)
        out = [f"{where} {who} — '{_asked}' ရာထူးနဲ့ ဖော်ပြထားတဲ့ "
               f"ပုဂ္ဂိုလ် {to_burmese_digits(len(people))} ဦး", ""]
        for pp in people:
            titles = "၊ ".join(pp["titles"])
            src = ""
            if pp.get("paper"):
                src = f"  ← {pp['paper']}"
                if pp.get("page"):
                    src += f" စာမျက်နှာ {to_burmese_digits(pp['page'])}"
            out.append(f"  • {pp['honorific']}{pp['name']} — {titles} "
                       f"({to_burmese_digits(pp['count'])} ကြိမ်){src}")
        if note:
            out.append("")
            out.append(note)
        if _hollow:
            out.append("")
            out.append(_hollow)
        out.append("")
        out.append("⚠️ ဒါက သတင်းစာ ဖော်ပြထားတဲ့ ပုဂ္ဂိုလ်တွေပါ — "
                   "ပြည်ထောင်စု အစိုးရအဖွဲ့ စာရင်း အပြည့်အစုံ မဟုတ်ပါ။")
        return "\n".join(out)

    # ── 6. "ဘယ်ဝန်ကြီးဌာနတွေ ပါသလဲ" ───────────────────────────────────────
    if act in ("ministries", "departments"):
        day = date or ""
        # Newest edition when no date is given — same reason as `people` above.
        if not day:
            day = _newest_edition(win)
        if day:
            raw = content_rows(all_articles_on(day, paper=paper))
        else:
            raw = []
        _kind, note = _paper_scope(day, paper) if day else ("", "")
        _hollow = _hollow_papers(day) if not paper else ""
        if not raw:
            if note:
                return note
            if day and _read_failed(day):
                return _unreachable()
            scope = _date(day) if day else "ဒီကာလအတွင်း"
            return f"{scope} ဖတ်လို့ရတဲ့ သတင်း မတွေ့ပါ။\n\n{_window_line()}"
        mins = ministries_across(raw, limit)
        if not mins:
            # Same rule as `people`: an unreadable paper has no "not found".
            if _kind in ("missing", "unreadable", "thin"):
                return "\n".join([note, "", _window_line()])
            _miss = (f"{_date(day) if day else 'ဒီကာလအတွင်း'} သတင်း "
                     f"{to_burmese_digits(len(raw))} ခု ဖတ်ပြီးပါပြီ — "
                     f"ဝန်ကြီးဌာန အမည် မတွေ့ပါ။")
            if _hollow:
                return "\n".join([_miss, "", _hollow])
            return _miss
        out = [f"{_date(day) if day else 'ဒီကာလအတွင်း'} "
               f"{paper or 'မြန်မာ့အလင်း/ကြေးမုံ'} — "
               f"ဖော်ပြထားတဲ့ ဝန်ကြီးဌာန "
               f"{to_burmese_digits(len(mins))} ခု:", ""]
        for m in mins:
            out.append(f"  • {m['name']} "
                       f"({to_burmese_digits(m['count'])} ကြိမ်)")
        if note:
            out.append("")
            out.append(note)
        if _hollow:
            out.append("")
            out.append(_hollow)
        return "\n".join(out)

    # ── 4. "ဘယ်နှစ်ရက်က သတင်းရှိလား" — a name, or any keyword ──────────────
    if act in ("byday", "days", "whichday"):
        if not term:
            return "ဘယ်သူ/ဘာအကြောင်း ရှာရမလဲ ပြောပါ။"
        days_rows = days_for(term, 40, days=win)
        if not days_rows:
            if _read_failed(_date_or_newest(days=win)):
                return _unreachable()
            scope = (f" လွန်ခဲ့တဲ့ {to_burmese_digits(win)} ရက်အတွင်း"
                     if win else "")
            return (f"'{term}' နဲ့ ကိုက်တဲ့ သတင်း{scope} မတွေ့ပါ။\n\n"
                    f"{_window_line()}\n"
                    f"⚠️ 'အရင် မရှိခဲ့ဘူး' လို့ မဆိုလိုပါ — "
                    f"ဒီကာလအတွင်းမှာ မတွေ့တာပါ။")
        total = sum(d["count"] for d in days_rows)
        out = [f"'{term}' — သတင်း {to_burmese_digits(total)} ခု၊ "
               f"ရက် {to_burmese_digits(len(days_rows))} ရက်မှာ:", ""]
        for d in days_rows:
            papers = "၊ ".join(d.get("papers") or [])
            bar = "▇" * min(d["count"], 20)
            out.append(f"  {_short_date(d['date'])}  "
                       f"{to_burmese_digits(d['count']):>3} ခု  {bar}  {papers}")
        out.append("")
        out.append("ဘယ်ရက်က လိုချင်လဲ ပြောပါ — "
                   "'စက်တင်ဘာ ၁၃ ရက်က ပြောပြပါ'။")
        out.append(_window_line())
        return "\n".join(out)

    # ── 3. "အရင်က ရှိခဲ့ဖူးလား" ─────────────────────────────────────────────
    if act in ("timeline", "history", "before"):
        if not term:
            return "ဘာအကြောင်း ရှာရမလဲ ပြောပါ။"
        raw = timeline(term, limit, days=win)
        rows = content_rows(raw)
        if not rows:
            if _read_failed(_date_or_newest(days=win)):
                return _unreachable()
            return (f"'{term}' နဲ့ ပတ်သက်တဲ့ သတင်း မတွေ့ပါ။\n\n"
                    f"{_window_line()}\n"
                    f"⚠️ 'အရင် မရှိခဲ့ဘူး' လို့ မဆိုလိုပါ — "
                    f"ဒီကာလအတွင်းမှာ မတွေ့တာပါ။")
        out = [f"'{term}' — အစောဆုံး {_short_date(rows[0].get('issue_date'))} "
               f"ကတည်းက {to_burmese_digits(len(rows))} ခု တွေ့ပါတယ်:", ""]
        for a in rows:
            out.append(f"  {_short_date(a.get('issue_date'))} — "
                       f"{_article_line(a).strip().lstrip('• ')}")
        if len(rows) >= limit:
            out.append(f"  … (ပထမ {to_burmese_digits(limit)} ခု ပဲ ပြထားတယ်)")
        out.append("")
        out.append(_window_line())
        out.append("➡️ ဒီကာလထက် အရင် သတင်းတွေ ဒီ database မှာ မရှိပါ။")
        return "\n".join(out)

    return f"Unknown reporter_news action: '{action}'. Use: search | day | byday | timeline"


TOOL = {
    "name": "reporter_news",
    "description": (
        "Search မြန်မာ့အလင်း and ကြေးမုံ (the state papers) for news. "
        "Actions: "
        "'search' — 'X အကြောင်း သတင်းရှိလား' → how many articles and over which "
        "dates. Do NOT list articles for this, just the count and the range; "
        "'byday' — 'ဦးမင်းအောင်လှိုင် သတင်း ဘယ်နှစ်ရက်က ရှိလား' → which days carry "
        "the keyword and how many each, so the user can pick a date. Works for "
        "a person's name, a ministry, or any topic; "
        "'day' — with a `date` (YYYY-MM-DD) and optionally a `query` → that day's "
        "articles. Use after 'search' or 'byday' when the user picks a date; "
        "'people' — **WHO is named, not how many.** 'ဒီနေ့ သတင်းစာထဲ ဘယ်ဝန်ကြီးတွေ "
        "ပါသလဲ', 'ဘယ်ပုဂ္ဂိုလ်တွေ ပါလဲ', 'who is mentioned' → reads the day (or "
        "the window) and lists every titled person the paper names, with the "
        "paper and page. Use this whenever the question asks **which people**, "
        "never 'search' — a keyword count cannot name anyone. It answers about "
        "the state offices too (နိုင်ငံတော်သမ္မတ, ဒုတိယသမ္မတ) as well as the "
        "ministerial ranks, and a question naming two offices at once "
        "('နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ ပါသလား') returns both. **Put the "
        "office words in `query` and leave it at that** — pass the rank "
        "('နိုင်ငံတော်သမ္မတ', 'ဒုတိယသမ္မတ', 'ပြည်ထောင်စုဝန်ကြီး', 'ဝန်ကြီး') or "
        "the user's own words; do not pad it with the rest of the sentence, "
        "which cannot match anything; "
        "'ministries' — 'ဘယ်ဝန်ကြီးဌာနတွေ ပါလဲ' → the union ministries the paper "
        "names, with how often; "
        "'timeline' — 'ဒီသတင်းနဲ့ ပတ်သက်ပြီး အရင်က ရှိခဲ့ဖူးလား' → the same "
        "keyword oldest-first. "
        "\n"
        "**`paper` — name it when the user names it.** 'မြန်မာ့အလင်း' or "
        "'ကြေးမုံ'. Leave it off when the user does not name one, so both are "
        "searched. This matters more than it looks: **the two papers are not "
        "equally complete in this database.** Measured 2026-09-30, on "
        "2026-09-29: ကြေးမုံ has 328 articles; မြန်မာ့အလင်း has 29 rows and "
        "**none of them is news** — they are page markers. When the user asks "
        "about a named paper, pass `paper` so the answer is about that paper "
        "and the tool can say plainly when that paper's text is not in the "
        "database. "
        "\n"
        "**`days` — THE RECENCY WINDOW, and getting it wrong is the mistake "
        "this tool has already made once.** Measured 2026-09-29: asked "
        "*'လက်ရှိဖြစ်ပေါ်နေတဲ့ မုန်တိုင်းနဲ့ပတ်သက်ပြီး အစိုးရက ဘာတွေ လုပ်ပေးနေလဲ'*, the "
        "search ran back to September 1 and answered with three weeks of "
        "history — **the user asked about now and got a month.** "
        "When the user says လက်ရှိ / အခု / ဒီနေ့ / မနေ့ / now / current / latest, "
        "set `days=2`. When he names a date or a month, or asks whether "
        "something was covered before, leave `days` at 0. The window counts "
        "back from the newest paper in the database, not from the clock, so it "
        "still works on a morning when today's paper has not arrived. "
        "\n"
        "**Two words that are not the same, and the storm question needs "
        "both.** Measured 2026-09-29: `မုန်တိုင်း` finds 38 articles but "
        "`ကယ်ဆယ်ရေး` finds 96 and `ထောက်ပံ့` finds 145 — **the government's "
        "relief and aid work is filed under ကယ်ဆယ်ရေးထောက်ပံ့ရေး, not under the "
        "storm's name.** So for 'what is being done about X', search "
        "`ကယ်ဆယ်ရေးထောက်ပံ့ရေး` (or `ကယ်ဆယ်ရေး`, `ထောက်ပံ့`, `ကူညီ`) as well as "
        "the event's own word; searching only the event's name misses most of "
        "the response. "
        "\n"
        "Names to expect: ဦးမင်းအောင်လှိုင် (နိုင်ငံတော်သမ္မတ), ဦးညိုစော "
        "နှင့် ဒေါ်နန်းနီနီအေး (ဒုတိယသမ္မတ နှစ်ဦး), "
        "ပြည်ထောင်စုဝန်ကြီး names. Pass the name or keyword in Burmese exactly "
        "as said; do not translate or transliterate it. "
        "IMPORTANT: this database covers **September 2026 only**. When nothing "
        "is found, say the search window found nothing — NEVER say the news "
        "never existed. **And when the tool says the database could not be "
        "reached, say that — it is not the same as finding nothing.**"
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": ("search (default) | day | byday | timeline | "
                                "people | ministries"),
            },
            "query": {
                "type": "STRING",
                "description": "Burmese keyword, e.g. 'ပညာရေး', 'ဆီဈေး'. Do not translate.",
            },
            "date": {
                "type": "STRING",
                "description": "YYYY-MM-DD, for action='day' / 'people' / 'ministries'.",
            },
            "paper": {
                "type": "STRING",
                "description": ("'မြန်မာ့အလင်း' or 'ကြေးမုံ' — set ONLY when the "
                                "user names a paper. Leave empty to search both."),
            },
            "limit": {
                "type": "NUMBER",
                "description": "Max articles/people to list (default 8, max 25).",
            },
            "days": {
                "type": "NUMBER",
                "description": ("Recency window in days, counted back from the "
                                "newest paper in the database. Set 2 when the "
                                "user says လက်ရှိ / အခု / ဒီနေ့ / မနေ့ / now / "
                                "current / latest. Leave 0 (the default) when he "
                                "names a date or month, or asks about history."),
            },
        },
        "required": [],
    },
    "handler": reporter_news,
}
