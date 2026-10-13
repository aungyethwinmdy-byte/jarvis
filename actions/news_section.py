"""Answer a question **from a section of the paper**, not from a keyword sweep.

THE OWNER'S ASK, 2026-09-30

    "ငါက ဂျာဗစ်ကိုမေးလိုက်ရင်လည်း ဥပမာ နိုင်ငံတော်သမ္မတ သတင်းဒီနေ့ဘာရှိလဲလို့မေးရင်
     နိုင်ငံတော်သမ္မတ ကဏ္ဍကို သွားပြီး သိမ်းဆည်းထားတဲ့ သတင်းကိုပြောပြရမယ်။"

    *"When I ask JARVIS 'what is today's State President news', it should go to
    the State President section and tell me the news stored there."*

    That is a different question from "is there news about X". A keyword search
    for `နိုင်ငံတော်သမ္မတ` returns every article that mentions the office,
    including ones where he is a passing reference; the section holds the ones
    the paper is actually about him. The classification is in
    `core/news_sections.py` — one definition, shared with the indexing pass.

THE THREE THINGS THIS FILE IS CAREFUL ABOUT

    1. **An unknown section never degrades to "everything".** Measured
       2026-09-30 on the prices side of this project: `kind="rice"` was not in
       `_PRICE_KINDS`, the filter was silently dropped, and a rice-price
       question came back with fire-balloon festival dates. Here the same shape
       of bug would answer "today's Sports news" with the whole newspaper, so
       `resolve_section` returns "" and the action **refuses and names the
       sections it does have**.

    2. **A failed read is not an empty section.** The three sentences
       `မတွေ့ပါ` / `မရှိပါ` / `မချိတ်နိုင်ပါ` are imported from
       `_reporter_common`, not re-written — see that module for why. When the
       paper the owner named could not be read, the answer **leads with that**
       and never says "no news in this section", because that would be a claim
       about the newspaper made on the strength of a failed socket.

    3. **A missing index is not a missing section.** `articles_by_section`
       classifies an un-indexed row on the spot, so a section question works
       the morning after a day the indexer has not run. `index` is what makes
       it cheap next time; it is not what makes it *correct*.
"""
from __future__ import annotations

from core.reporter_client import (
    articles_by_section,
    available,
    clear_section_cache,
    content_rows,
    coverage,
    section_tally,
    store_section,
    store_sections,
    stored_section_counts,
    unindexed_rows,
    _section_reader_rows,
)
from core.news_sections import (
    LABELS,
    OTHER,
    SECTIONS,
    classify,
    resolve_section,
)
from core.timefmt import to_burmese_digits

from actions._reporter_common import (
    _article_line,
    _date,
    _hollow_papers,
    _infer_paper,
    _newest_edition,
    _paper_scope,
    _read_failed,
    _unreachable,
    _window_line,
)

# How many articles a spoken answer lists. The section total is always spoken;
# this only bounds the list, so a 500-article section is described, not read
# out in full.
_DISPLAY_MAX = 25

# The indexing pass walks the table in pages of this size. 8 pages covers the
# 7,521 rows the database held on 2026-09-30 with room to grow; the loop stops
# early on the first **empty** page, so a larger corpus takes longer rather than
# being silently truncated.
_INDEX_PAGE = 1000
_MAX_INDEX_PAGES = 20

# The column's own default, and the only value that means "nothing to keep".
# Measured 2026-09-30: 7,572 of 7,745 rows carry it. See `_backup_overwrites`.
_DEFAULT_SECTION = "General"


def _backup_overwrites(entries: list[dict]) -> str:
    """Keep the stored values an indexing pass is about to replace. "" if none.

    The `article_type` column is not empty when the indexer first runs: 148 of
    7,510 rows carried ad-hoc English labels (`Business / Market Rates`,
    `Front Page / Diplomatic`) from an abandoned 2026-09-01..10 experiment.
    Nothing in either project reads them, and they were verified unused before
    the first write — but *verified unused* is a claim about code, and the
    values themselves are the only copy. Replacing them without keeping them
    would be the one irreversible step in this whole feature.

    The file **accumulates**: a second run appends what it found rather than
    starting again, so an early backup is never lost to a later one.
    """
    if not entries:
        return ""
    import json
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / ".workbuddy-ai" / "memory" / "section-overwrite-backup.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:                               # noqa: BLE001
                existing = []
        seen = {(e.get("id"), e.get("was")) for e in existing}
        for e in entries:
            if (e.get("id"), e.get("was")) not in seen:
                existing.append(e)
                seen.add((e.get("id"), e.get("was")))
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return str(path)
    except Exception as e:                                  # noqa: BLE001
        print(f"[Section] backup failed: {type(e).__name__}: {e}")
        return ""


def _section_menu() -> str:
    """The section names, for a refusal that is useful rather than a dead end."""
    return "၊ ".join(f"{label}" for _slug, label in SECTIONS)


def _scope_line(day: str, paper: str) -> str:
    """Which paper and which day the answer is about — always stated.

    A section answer with no scope is unfalsifiable: "there is no president
    news" means one thing about today's ကြေးမုံ and another about the whole
    database.
    """
    where = _date(day) if day else "နောက်ဆုံး ထုတ်ဝေမှု"
    return f"{where} — {paper or 'မြန်မာ့အလင်း/ကြေးမုံ'}"


def _tally_lines(tally: dict, exclude: str = "", limit: int = 12) -> list[str]:
    """The counts, biggest first, so the answer shows where the news went.

    The `OTHER` bucket is deliberately kept in view: 69% of the readable corpus
    falls outside the eleven sections (measured 2026-09-30 — the classified
    pages are the paper's own news pages, the rest is the classified-advert and
    regional-notice block, pages ~21-32). Hiding that would make the index look
    more complete than it is.
    """
    rows = [(k, v) for k, v in tally.items() if v and k != exclude]
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    return [f"  • {k} — {to_burmese_digits(v)} ခု" for k, v in rows[:limit]]


def _tally_line_str(tally: dict, limit: int = 12) -> str:
    """One line of counts, for the verification read-back."""
    rows = [(k, v) for k, v in tally.items() if v]
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    if not rows:
        return "ဗလာ"
    return "၊ ".join(f"{k} {to_burmese_digits(v)}" for k, v in rows[:limit])


def news_section(parameters: dict = None, player=None, session_memory=None,
                 **_) -> str:
    """Voice entry point.

    The signature is `(parameters, ...)` because `core/action_loader.py` calls
    a handler as `fn(parameters=parameters, ...)`. A handler written
    `fn(section="", **_)` swallows the whole argument dict in its own `**_` and
    runs on defaults — measured 2026-09-29 in a live session, where the log
    showed the arguments arriving and the tool then asking the user what to
    search for while holding the query. Six tools had this shape.
    """
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    asked = str(p.get("section") or p.get("query") or "").strip()
    date = str(p.get("date") or "").strip()
    # The paper is often named in the sentence rather than the parameter —
    # measured 2026-09-30: "ဒီနေ့ကြေးမုံသတင်းစာမှာ …" arrived with no `paper`
    # and the answer was headed with both paper names.
    paper = _infer_paper(str(p.get("paper") or "").strip(), asked)

    ok, reason = available()
    if not ok:
        return f"မြန်မာ့အလင်း/ကြေးမုံ database ကို မချိတ်နိုင်ပါ — {reason}"

    try:
        win = max(0, min(int(p.get("days") or 0), 30))
    except (TypeError, ValueError):
        win = 0
    try:
        limit = max(1, min(int(p.get("limit") or 8), _DISPLAY_MAX))
    except (TypeError, ValueError):
        limit = 8

    # ── The index itself: what sections exist, and how much is in each ───────
    if action in ("sections", "list_sections", "all"):
        # No date given means "the newest edition that carries news", not
        # `date.today()` — the papers load daily and today's may not have
        # arrived. See `_newest_edition`.
        day = date or _newest_edition(win)
        tally = section_tally(day=day, paper=paper)
        if not tally:
            return _unreachable()
        total = sum(tally.values())
        out = [f"📚 {_scope_line(day, paper)} — ဖတ်လို့ရတဲ့ သတင်း "
               f"{to_burmese_digits(total)} ခုကို ကဏ္ဍအလိုက် ခွဲထားတယ်:", ""]
        out += _tally_lines(tally, limit=len(LABELS))
        out.append("")
        out.append("⚠️ ဒါက သတင်းစာရဲ့ ကိုယ်ပိုင် စာမျက်နှာ ကဏ္ဍအမည် "
                   "မဟုတ်ပါ — JARVIS က အကြောင်းအရာအလိုက် ခွဲထားတာပါ။ "
                   f"'{OTHER}' က ကြော်ငြာ၊ ကြေညာစာ၊ အားကစား စတဲ့ "
                   "ကဏ္ဍ ၁၁ ခုနဲ့ မကိုက်တာတွေပါ။")
        out.append("")
        out.append(_window_line())
        return "\n".join(out)

    # ── Build / refresh the index ───────────────────────────────────────────
    if action in ("index", "build", "reindex", "rebuild"):
        # `rebuild` re-classifies **every** readable row; `index` only fills in
        # the rows that have never been classified. The difference matters
        # whenever a classification rule changes: after the office rule moved
        # from "named twice in the body" to "named in the opening" (2026-10-01)
        # every stored label was still the old rule's answer, and `index` would
        # have found nothing to do and reported success. A rebuild that changes
        # nothing is the only honest way to prove the new rule is in effect.
        full = action in ("rebuild",)
        # **Page to an empty page, not to a short one.** A short page is normal
        # — `content_rows` drops the glyph-noise and page-marker rows — so
        # stopping at the first short page would leave the tail of the table
        # unindexed while reporting success. See `reporter_client.unindexed_rows`.
        #
        # Ids are collected per section and written in bulk, not one row at a
        # time: 7,521 one-row updates is minutes of work and reads as a hang.
        scanned = 0
        overwritten: list[dict] = []
        by_id: dict[str, list[str]] = {label: [] for label in LABELS}
        for page in range(_MAX_INDEX_PAGES):
            rows = ((content_rows(_section_reader_rows(
                        days=0, limit=_INDEX_PAGE, offset=page * _INDEX_PAGE)))
                    if full
                    else unindexed_rows(days=0, offset=page * _INDEX_PAGE))
            if not rows:
                break
            scanned += len(rows)
            for r in rows:
                old = str(r.get("article_type") or "").strip()
                label, _why = classify(r)
                if full:
                    # Only rewrite what actually differs — a rebuild of an
                    # unchanged corpus must touch nothing.
                    if old == label:
                        continue
                    if old and old not in LABELS and old != _DEFAULT_SECTION:
                        overwritten.append({"id": r.get("id"),
                                            "issue_date": r.get("issue_date"),
                                            "was": old})
                elif old and old not in LABELS and old != _DEFAULT_SECTION:
                    # A value that is neither the plain default nor one of ours
                    # is real information about to be replaced — the abandoned
                    # 2026-09-01..10 experiment. It is kept, not discarded.
                    #
                    # `'General'` is excluded deliberately: it is the column's
                    # own default on 7,572 of 7,745 rows, so recording it would
                    # bury the ~148 values that are actually worth keeping in
                    # 7,500 lines of noise and call it a backup.
                    overwritten.append({"id": r.get("id"),
                                        "issue_date": r.get("issue_date"),
                                        "was": old})
                by_id[label].append(r.get("id"))

        if scanned == 0:
            # Nothing to look at. Distinguish that from a failed read — an empty
            # table and an unreachable database look the same from here.
            if not content_rows(_section_reader_rows(days=0, limit=200)):
                return _unreachable()
            tally = section_tally()
            return ("✅ အားလုံး ကဏ္ဍ ခွဲပြီးသားပါ။\n\n"
                    + "\n".join(_tally_lines(tally, limit=len(LABELS)))
                    + f"\n\n{_window_line()}")

        if full and not any(by_id.values()):
            # A rebuild that changes nothing is the proof that the stored index
            # already matches the current rules — say so instead of printing an
            # empty table.
            tally = section_tally()
            return ("✅ ပြန်ခွဲစရာ မရှိပါ — database က လက်ရှိ စည်းမျဉ်းနဲ့ "
                    "ကိုက်နေပြီးသား။\n\n"
                    + "\n".join(_tally_lines(tally, limit=len(LABELS)))
                    + f"\n\n{_window_line()}")

        by_section: dict[str, int] = {}
        failed = 0
        for label, ids in by_id.items():
            if not ids:
                continue
            got = store_sections(ids, label)
            if got:
                by_section[label] = got
            failed += len(ids) - got

        # The write must be visible to the very next read — without this the
        # index reports success and the next section question is answered from
        # the pre-write cache, which is a real write that looks like a no-op.
        clear_section_cache()

        # **Verify by counts, not by what we sent.** `store_sections` returns
        # the number of ids it asked the database to change, and a bulk update
        # against ids that do not exist still reports success — so "6,909
        # written" is a claim about this loop, not about the database. The line
        # below is read back out of the column the write went to, which is the
        # only form of verification this project accepts for a write.
        stored = stored_section_counts()
        still_default = stored.get(_DEFAULT_SECTION, 0)

        backup = _backup_overwrites(overwritten)
        written = sum(by_section.values())

        out = [f"✅ သတင်း {to_burmese_digits(written)} ခုကို ကဏ္ဍအလိုက် "
               f"ခွဲပြီး database မှာ သိမ်းလိုက်ပါပြီ:", ""]
        out += _tally_lines(by_section, limit=len(LABELS))
        out.append("")
        out.append(f"🔎 database ကနေ ပြန်ဖတ်စစ်ပြီး — "
                   f"{_tally_line_str(stored)}")
        if still_default:
            # These are not failures. A row whose text is glyph noise or a page
            # marker has nothing to classify, so it keeps the column default on
            # purpose — counting it as "not indexed" would make the pass look
            # permanently incomplete.
            out.append(f"ℹ️ 'ဖတ်လို့မရတဲ့/စာမျက်နှာ အမှတ်အသား' "
                       f"{to_burmese_digits(still_default)} ခုက ကဏ္ဍ မခွဲပါ — "
                       f"စာသား မရှိလို့ပါ။")
        if backup:
            out.append("")
            out.append(f"🗄️ အရင် တန်ဖိုး {to_burmese_digits(len(overwritten))} ခုကို "
                       f"backup ယူထားတယ် — {backup}")
        if failed:
            out.append("")
            out.append(f"⚠️ {to_burmese_digits(failed)} ခု သိမ်းလို့ မရပါ — "
                       f"ခဏနေ ပြန်လုပ်ပေးပါ။")
        out.append("")
        out.append(_window_line())
        return "\n".join(out)

    # ── The ordinary question: what is in this section ──────────────────────
    label = resolve_section(asked)
    if not label:
        return (f"'{asked or '?'}' ဆိုတဲ့ ကဏ္ဍ မရှိပါ။\n"
                f"ဒီ database မှာ ခွဲထားတဲ့ ကဏ္ဍတွေက — {_section_menu()} ။\n"
                f"➡️ ဥပမာ 'ဒီနေ့ နိုင်ငံတော်သမ္မတ သတင်း ဘာရှိလဲ' လို့ မေးပါ။")

    day = date or _newest_edition(win)
    rows = articles_by_section(label, day=day, paper=paper, limit=limit)
    tally = section_tally(day=day, paper=paper)
    kind, note = _paper_scope(day, paper) if day else ("", "")

    if not rows:
        # **The order here is the whole point.** A limitation first, never a
        # finding — see `_reporter_common._paper_scope`.
        if kind in ("missing", "unreadable", "thin"):
            return "\n".join([note, "", _window_line()])
        if not tally:
            return _unreachable()
        if day and _read_failed(day):
            return _unreachable()
        out = [f"{_scope_line(day, paper)} — '{label}' ကဏ္ဍမှာ "
               f"သတင်း မတွေ့ပါ။"]
        rest = _tally_lines(tally, exclude=label)
        if rest:
            out += ["", "အဲဒီထုတ်ဝေမှုမှာ ရှိတာက —"] + rest
        hollow = _hollow_papers(day) if not paper else ""
        if hollow:
            out += ["", hollow]
        out += ["", _window_line()]
        return "\n".join(out)

    total = tally.get(label, len(rows))
    out = [f"📚 {_scope_line(day, paper)} — '{label}' ကဏ္ဍမှာ "
           f"သတင်း {to_burmese_digits(total)} ခု:", ""]
    out += [_article_line(a) for a in rows]
    if total > len(rows):
        out.append(f"  … (ပထမ {to_burmese_digits(len(rows))} ခု ပြထားတယ်)")
    if note:
        out += ["", note]
    hollow = _hollow_papers(day) if not paper else ""
    if hollow:
        out += ["", hollow]
    out += ["", _window_line()]
    return "\n".join(out)


TOOL = {
    "name": "news_section",
    "description": (
        "**For a state-news question, use `moi_news` — not this tool.** Since "
        "2026-10-01 state news (နိုင်ငံတော်သမ္မတ · ဒုတိယသမ္မတ · လွှတ်တော် · "
        "ပြည်ထောင်စုဝန်ကြီး · the Ministry of Information's own reporting) comes "
        "from `moi.gov.mm` **live**, and `moi_news` reads it. **This tool reads "
        "the database copy** of the state papers, and that copy is incomplete — "
        "measured 2026-10-01, မြန်မာ့အလင်း held **0 readable rows** for the day and "
        "a vice-president's story was invisible because its body could not be "
        "parsed. Use this tool only when the owner asks to search the database, "
        "or when `moi_news` cannot be reached. "
        "\n"
        "**It is also the tool for the topics the site has no section for** — "
        "ပညာရေး · ကျန်းမာရေး · စီးပွားရေး · လူမှုရေး · သဘာဝဘေး — which this index "
        "covers and `moi.gov.mm` does not. Those questions belong **here**, not "
        "with `moi_news`; asking the website for them returns nothing. "
        "\n"
        "Answer from a **section (ကဏ္ဍ) of the state papers** မြန်မာ့အလင်း / "
        "ကြေးမုံ — the paper's articles are indexed into sections in the "
        "database, and this tool reads a section rather than searching for a "
        "keyword. "
        "Use this whenever the question names **one of the eleven sections** and "
        "asks what it holds — **including the `ရှိလား` form**: "
        "'ဒီနေ့ နိုင်ငံတော်သမ္မတ သတင်း ဘာရှိလဲ', "
        "'မနေ့က ဒုတိယသမ္မတတွေရဲ့ သတင်းရှိလား', "
        "'စီးပွားရေး သတင်း ပြောပြ', 'အယ်ဒီတာအာဘော် ဖတ်ပြပါ'. "
        "**A word from the list below is never 'an arbitrary topic'** — if the "
        "user named a section, this is the tool, whatever else the sentence "
        "says. Measured 2026-10-01 in a live session: the owner asked "
        "*'မနေ့က ဒုတိယသမ္မတတွေရဲ့ သတင်းရှိလား'*, this tool was **not** called, "
        "and `reporter_news` answered with the president and no "
        "vice-president — because a vice-president's story that day had its "
        "name in the headline and a body this reader cannot parse, so only the "
        "section could see it. "
        "Do NOT use it for a topic that is **not** in the list below "
        "('မုန်တိုင်း ကယ်ဆယ်ရေး' is `reporter_news` action='search'), and do "
        "NOT use it for 'which ministers are named' (`reporter_news` "
        "action='people'). "
        "**One section per call**: a question naming two sections at once "
        "('နိုင်ငံတော်သမ္မတ၊ ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့ သတင်းတွေ ရှိလား') is "
        "`reporter_news` action='people' with both ranks in `query`. "
        "\n"
        "**The sections, exactly as the tool takes them:** "
        "နိုင်ငံတော်သမ္မတ (State President) · ဒုတိယသမ္မတများ (Vice Presidents) "
        "· ပြည်ထောင်စုဝန်ကြီးများ (Union Ministers) · ဆောင်းပါး (feature "
        "articles) · နိုင်ငံရေး (politics) · စီးပွားရေး (economy) · လူမှုရေး "
        "(social) · ပညာရေး (education) · ကျန်းမာရေး (health) · သဘာဝဘေး "
        "(natural disaster) · အယ်ဒီတာအာဘော် (editorial). "
        "Pass the section in `section`, in Burmese, exactly as listed — "
        "`သမ္မတ` and `ဝန်ကြီး` are understood too. **Never pass a section that "
        "is not in this list**: the tool refuses it and names the real ones "
        "rather than answering with the whole newspaper. "
        "\n"
        "Actions: "
        "'list' (default) — a section's articles for the day/window, newest "
        "first; "
        "'sections' — the index itself: how many articles each section holds, "
        "for the day or the window. Use it for 'ဘယ်ကဏ္ဍတွေ ရှိလဲ', 'what "
        "sections are there', or when the user asks what today's paper "
        "contains overall; "
        "'index' — classify the newly ingested articles and store their "
        "section in the database. Run it when the user asks to build or refresh "
        "the section index; it is idempotent and reports how many rows it "
        "wrote. "
        "'rebuild' — re-classify **every** article and rewrite the ones whose "
        "section changed. Use it only after a classification rule has been "
        "changed in code; `index` cannot see those rows because they are "
        "already classified, so it would report success while the stored "
        "labels were still the old rule's. "
        "\n"
        "**`days` — the recency window**, counted back from the newest paper in "
        "the database, not from the clock. Set `days=2` when the user says "
        "ဒီနေ့ / လက်ရှိ / အခု / မနေ့ / today / current. Leave 0 (the default) "
        "when he names a date or a month, or asks about the whole database. "
        "**`paper`** — 'မြန်မာ့အလင်း' or 'ကြေးမုံ', set ONLY when the user names "
        "a paper; leave it empty to read both. "
        "\n"
        "IMPORTANT: these are **JARVIS's own subject sections, not the paper's "
        "printed page headings** — say so if the user asks how the split was "
        "made. When a section is empty for a day, the tool says what that day "
        "*does* hold, so read that out rather than saying only 'nothing'. "
        "**When the tool says the database could not be reached, say that — it "
        "is not the same as finding nothing.**"
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list (default) | sections | index | rebuild",
            },
            "section": {
                "type": "STRING",
                "description": (
                    "The Burmese section name, e.g. 'နိုင်ငံတော်သမ္မတ', "
                    "'ဒုတိယသမ္မတများ', 'ပြည်ထောင်စုဝန်ကြီးများ', 'ဆောင်းပါး', "
                    "'နိုင်ငံရေး', 'စီးပွားရေး', 'လူမှုရေး', 'ပညာရေး', "
                    "'ကျန်းမာရေး', 'သဘာဝဘေး', 'အယ်ဒီတာအာဘော်'. Do not translate."),
            },
            "date": {
                "type": "STRING",
                "description": "YYYY-MM-DD. Leave empty for the newest edition.",
            },
            "paper": {
                "type": "STRING",
                "description": ("'မြန်မာ့အလင်း' or 'ကြေးမုံ' — set ONLY when the "
                                "user names a paper. Leave empty to read both."),
            },
            "limit": {
                "type": "NUMBER",
                "description": "Max articles to list (default 8, max 25).",
            },
            "days": {
                "type": "NUMBER",
                "description": ("Recency window in days, counted back from the "
                                "newest paper in the database. Set 2 when the "
                                "user says ဒီနေ့ / လက်ရှိ / အခု / မနေ့ / today / "
                                "current. Leave 0 (the default) when he names a "
                                "date or month, or asks about the whole "
                                "database."),
            },
        },
        "required": [],
    },
    "handler": news_section,
}
