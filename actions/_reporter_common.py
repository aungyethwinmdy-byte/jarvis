"""Shared presentation helpers for the state-paper tools.

WHY THIS FILE EXISTS

    `actions/reporter_news.py` grew the sentences that keep a *failed* read, an
    *unreadable* paper and an *empty* result apart — the three-sentence rule
    this project has paid for twice (see `MEMORY.md`):

        မတွေ့ပါ          looked, and there is nothing        — a finding
        မရှိပါ            the paper is not in this window     — a limitation
        မချိတ်နိုင်ပါ       the lookup failed                   — not an answer

    The section tool (`actions/news_section.py`) has to obey exactly the same
    rule. Copying those sentences into it would create a second definition of
    "what a limitation sounds like", which is the defect class this project
    already has a rule against (*one rule, one definition*). So they live here
    once, and both tools import them.

    This mirrors `actions/_newsroom_common.py`, which is the same idea for the
    other database.

WHAT IS *NOT* HERE

    `_TOPIC_FURNITURE` / `_extract_topic` stay in `reporter_news.py`: they
    narrow a `people` question and nothing else uses them. Everything in this
    file is used by more than one tool.
"""
from __future__ import annotations

from core.entities import people_in
from core.reporter_client import (
    all_articles_on,
    content_rows,
    coverage,
    editions_with_content,
    paper_counts,
    papers_with_content,
)
from core.timefmt import to_burmese_digits

_MONTHS = ("", "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
           "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ",
           "ဒီဇင်ဘာ")

# The two state papers, in the spelling the database uses. `_infer_paper` reads
# a paper named **in the sentence** because the model does not reliably fill the
# `paper` parameter: measured 2026-09-30 the owner asked
# *"ဒီနေ့ကြေးမုံသတင်းစာမှာ ပြည်ထောင်စုဝန်ကြီး ဘယ်သူတွေရဲ့ သတင်းတွေပါလဲ"* and the
# action, called with no `paper`, read **both** papers and headed the answer
# `မြန်မာ့အလင်း/ကြေးမုံ` while every row it listed was ကြေးမုံ. The paper was named
# in the question; the answer should say so. It does not widen the search — it
# only lets the action acknowledge a scope the user already stated.
_PAPER_NAMES = ("မြန်မာ့အလင်း", "ကြေးမုံ")


def _infer_paper(paper: str, *texts: str) -> str:
    """The paper named in the question, when the tool was not told one.

    Only consulted when `paper` is empty, and only a *named* paper is ever
    returned — an unmentioned paper stays `""` so the search keeps both. The
    match is whitespace-free, for the same reason as everywhere else in this
    package: the pipeline and the model both vary the spacing.
    """
    if paper:
        return paper
    joined = "".join(t or "" for t in texts).replace(" ", "")
    for name in _PAPER_NAMES:
        if name in joined:
            return name
    return ""


def _date(value: str) -> str:
    """2026-09-15 → ၂၀၂၆ စက်တင်ဘာ ၁၅ ရက်"""
    try:
        y, m, d = str(value).split("-")
        return (f"{to_burmese_digits(y)} {_MONTHS[int(m)]} "
                f"{to_burmese_digits(int(d))} ရက်")
    except Exception:                                       # noqa: BLE001
        return str(value or "")


def _short_date(value: str) -> str:
    """2026-09-15 → စက်တင်ဘာ ၁၅"""
    try:
        _y, m, d = str(value).split("-")
        return f"{_MONTHS[int(m)]} {to_burmese_digits(int(d))}"
    except Exception:                                       # noqa: BLE001
        return str(value or "")


def _window_line() -> str:
    """The sentence that stops 'no data' being read as 'no news'."""
    cov = coverage()
    if not cov.get("oldest"):
        return "⚠️ ဒီ database မှာ ရက်စွဲ အချက်အလက် မရပါ။"
    return (f"📅 ဒီ database မှာ {_date(cov['oldest'])} ကနေ "
            f"{_date(cov['newest'])} အထိ ရှိတယ်။")


# ── Two ways an empty result is not the same ─────────────────────────────────
#
# Measured 2026-09-30: asked *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာထဲ ဘယ်ဝန်ကြီးတွေ ပါသလဲ"*
# the assistant answered "သတင်း မတွေ့ပါ" — nothing found. That was wrong twice
# over. The database reached for မြန်မာ့အလင်း holds **29 rows that day and none
# of them is news** (see `reporter_client.is_placeholder`), and on some runs the
# Supabase call timed out before it could look at all.
#
# Those are three different sentences and the tool must not merge them:
#
#     မတွေ့ပါ          looked, and there is nothing        — a finding
#     မရှိပါ            the paper is not in this window     — a limitation
#     မချိတ်နိုင်ပါ       the lookup failed                   — not an answer
#
# A timeout spoken as "no news" is the worst of the three: for a journalist it
# reports that something was never covered, on the strength of a failed socket.

def _unreachable() -> str:
    return ("⚠️ သတင်း database ကို မချိတ်နိုင်ပါ — အင်တာနက် သို့မဟုတ် "
            "database ချိတ်ဆက်မှု ခဏ ပြတ်နေတာပါ။\n"
            "ဒါက 'သတင်း မရှိဘူး' လို့ မဆိုလိုပါ။ ခဏနေ ပြန်မေးပေးပါ။")


def _read_failed(day: str) -> bool:
    """True when the lookup for `day` failed rather than found nothing.

    `paper_counts` returns {} only when the read did not complete, and a dict
    (possibly all-zero) when it did. That is the signal, and it exists because
    `articles_on` cannot give one: it returns [] for both a stall and an empty
    day, which is exactly how a socket timeout was being spoken as "no news".
    """
    return not paper_counts(str(day or "").strip())


def _date_or_newest(days: int = 0) -> str:
    """A date to probe reachability with when the caller has no specific day.

    The newest date the database holds, not the clock — the papers load daily
    and the newest row may be today or yesterday, so probing with
    `date.today()` would false-positive a failure on a morning when today's
    paper has not arrived.

    **Reachability and "which edition" are two different questions and this
    answers only the first.** It deliberately keeps `coverage()['newest']`,
    including a day that is still being ingested — `check_agent.py` uses it to
    learn whether the connection is up. The entity actions use
    `_newest_edition()` below, which is about content.
    """
    cov = coverage()
    return str(cov.get("newest") or "")


def _newest_edition(days: int = 0) -> str:
    """The newest issue date that actually carries news, for a no-date question.

    **Not `coverage()['newest']`.** Measured 2026-09-30: the newest date had
    advanced to a day whose ingestion was still running — 23 မြန်မာ့အလင်း page
    markers, 8 ကြေးမုံ rows, no rank+name pair anywhere in them. A no-date
    "who is named today" question read that day, found nobody, and answered
    *"no officials"* about an edition that had not finished loading. `coverage`
    cannot catch it: it only asks for 20 rows of any kind, so a half-ingested
    day qualifies.

    So ask instead which recent days hold readable news and take the newest of
    them. `days` bounds how far back the search may go — a question scoped to
    "now" must not silently answer from three weeks ago just because the last
    few days are thin. When nothing in that window has content, fall back to
    the plain newest date rather than returning "" and handing the caller an
    empty read.
    """
    win = max(1, int(days or 0) or 3)
    eds = editions_with_content(win)
    if not eds:
        return _date_or_newest(days)
    return eds[0]


def _paper_scope(day: str, paper: str) -> tuple[str, str]:
    """(kind, sentence) for a named paper on a day.

    `kind` is `""` | `"missing"` | `"unreadable"` | `"thin"`. **The caller must
    branch on it, not just append the sentence.** Measured in a live voice
    session 2026-09-30 — the owner asked *"ဒီနေ့ မြန်မာ့အလင်းသတင်းစာထဲ
    ပြည်ထောင်စုဝန်ကြီးတွေရဲ့ သတင်းတွေ …ပါလား"*, the model passed
    `paper='မြန်မာ့အလင်း'` correctly, and the action answered

        သတင်း ၁ ခု ဖတ်ပြီးပါပြီ — ဒါပေမယ့် 'ပြည်ထောင်စုဝန်ကြီး' ရာထူးနဲ့
        အမည် တွဲပါတဲ့ လူပုဂ္ဂိုလ် **မတွေ့ပါ**။          ← a FINDING
        ⚠️ …ဖတ်လို့ရတဲ့ သတင်း ၁ ခု … အကြောင်းအရာ အများစု database မှာ မပါပါ။

    The second line is the truth and the first line contradicts it. The model
    then spoke *"သတင်းတွေ မတွေ့ရပါဘူး"* to the owner — so a journalist heard
    **"there is no union-minister news in မြန်မာ့အလင်း today"**, which is a claim
    about the newspaper, and it is false: the paper was never read.

    **A limitation must never be spoken as a finding.** When the paper could not
    be read there is nothing to report absent, so the caller leads with this
    sentence and drops the "not found" line entirely.
    """
    if not paper:
        return "", ""
    counts = paper_counts(day)
    if not counts:
        return "", ""                       # failed read: say nothing extra
    real = papers_with_content(day)

    named = [n for n in counts if paper in n]
    if not named:
        have = "၊ ".join(sorted(counts)) or "မရှိ"
        return "missing", (f"⚠️ {_date(day)} ရက်နေ့အတွက် '{paper}' ဒီ database မှာ "
                           f"မရှိပါ။ ရှိတာက — {have}။")

    rows = sum(counts[n] for n in named)
    real_rows = sum(real.get(n, 0) for n in named)
    if real_rows == 0:
        # The paper is in the database by name and carries no news. This is the
        # Myanma Alinn case, and saying "no news" would be a lie: the paper
        # published, the pipeline did not capture the text.
        return "unreadable", (
            f"⚠️ {_date(day)} ရက်နေ့ '{paper}' အတွက် "
            f"စာမျက်နှာ အမှတ်အသား {to_burmese_digits(rows)} ခု "
            f"ဒီ database မှာ ရှိပေမယ့် **သတင်းစာကို ဖတ်လို့ရတဲ့ "
            f"စာသား မပါပါ** — သတင်းစာ စာမျက်နှာတွေ ထည့်ထားပေမယ့် "
            f"အကြောင်းအရာ မထည့်ရသေးပါ။\n"
            f"➡️ ဒါက '{paper}' မှာ သတင်း မရှိဘူးလို့ မဆိုလိုပါ။ "
            f"database မှာ အကြောင်းအရာ မပါတာပါ။")
    if real_rows < rows:
        # Nearly all markers is the same warning as none: an answer drawn from 1
        # real row out of 29 is not an answer about that paper's edition.
        hollow = real_rows * 5 < rows
        icon = "⚠️" if hollow else "ℹ️"
        extra = ("\n➡️ ဒီသတင်းစာ အတွက် အကြောင်းအရာ အများစု database မှာ "
                 "မပါပါ — ရလဒ်က မပြည့်စုံပါ။" if hollow else "")
        return ("thin" if hollow else ""), (
            f"{icon} {_date(day)} ရက်နေ့ '{paper}' — "
            f"ဖတ်လို့ရတဲ့ သတင်း {to_burmese_digits(real_rows)} ခု "
            f"(စာမျက်နှာ အမှတ်အသား "
            f"{to_burmese_digits(rows - real_rows)} ခု မပါ)။{extra}")
    return "", ""


def _other_paper(paper: str) -> str:
    """The other state paper when exactly one was named, else ""."""
    others = [n for n in _PAPER_NAMES if n != paper]
    return others[0] if len(others) == 1 else ""


def _elsewhere_people(day: str, paper: str, rank: str = "") -> str:
    """One line saying the OTHER paper does name these people, or "".

    Used **only** when the paper the user named could not be read. The honest
    answer to *"is there union-minister news in မြန်မာ့အလင်း today"* is "that
    paper is not readable here" — but stopping there leaves a journalist with
    nothing, when the same edition of the other paper carries the answer. The
    owner's whole ask is a *"ဘက်စုံထောင့်စုံ"* assistant: say what could not be
    read **and** say where it can be found.

    Never widens the answer — it is a pointer, not a result, and it is dropped
    when the other paper has nothing either.
    """
    other = _other_paper(paper)
    if not other or not day:
        return ""
    rows = content_rows(all_articles_on(day, paper=other))
    if not rows:
        return ""
    ppl = people_in(rows, limit=25, rank=rank)
    if not ppl:
        return ""
    names = "၊ ".join(f"{x['honorific']}{x['name']}" for x in ppl[:6])
    if len(ppl) > 6:
        names += f" … နောက် {to_burmese_digits(len(ppl) - 6)} ဦး"
    asked = "၊ ".join(o for o in (rank.split(",") if rank else []) if o) or "ဝန်ကြီး"
    return (f"ℹ️ ဒါပေမယ့် {_date(day)} '{other}' မှာ '{asked}' ရာထူးနဲ့ "
            f"{to_burmese_digits(len(ppl))} ဦး ပါတယ် — {names}။")


def _elsewhere_search(day: str, paper: str, term: str) -> str:
    """One line saying the OTHER paper does carry `term`, or "".

    The keyword counterpart of `_elsewhere_people`, used under the same rule:
    only when the named paper could not be read, so the answer is *"not here —
    but there"* rather than *"nothing"*.
    """
    other = _other_paper(paper)
    if not other or not day or not term:
        return ""
    rows = content_rows(all_articles_on(day, paper=other))
    if not rows:
        return ""
    hits = [a for a in rows
            if term in ((a.get("body_text") or "") + " "
                        + (a.get("headline") or "") + " "
                        + (a.get("summary") or ""))]
    if not hits:
        return ""
    return (f"ℹ️ ဒါပေမယ့် {_date(day)} '{other}' မှာ '{term}' ပါတဲ့ သတင်း "
            f"{to_burmese_digits(len(hits))} ခု ရှိပါတယ်။")


def _hollow_papers(day: str) -> str:
    """One sentence naming any paper on `day` that could not be read, or "".

    Used when **no paper was named**, so the search covered both. Measured in a
    live voice session 2026-09-30: JARVIS answered *"မြန်မာ့အလင်းနဲ့ ကြေးမုံ
    သတင်းစာနှစ်စောင်လုံးကို စစ်ဆေးကြည့်ပြီးပါပြီ"* — "I checked both papers" —
    while မြန်မာ့အလင်း held **1 readable row out of 23**. Half the search never
    happened, and the claim that it had is exactly the kind of confident
    overstatement this project exists to avoid.

    `_paper_scope` covers the named case; this covers the unnamed one, which had
    no such warning at all.
    """
    if not day:
        return ""
    counts = paper_counts(day)
    if not counts:
        return ""
    real = papers_with_content(day)
    bad = [(n, real.get(n, 0), t) for n, t in sorted(counts.items())
           if real.get(n, 0) * 5 < t]
    if not bad:
        return ""
    parts = "၊ ".join(
        f"'{n}' (ဖတ်လို့ရ {to_burmese_digits(r)}/{to_burmese_digits(t)})"
        for n, r, t in bad)
    return (f"⚠️ {_date(day)} ရက်နေ့ {parts} — အကြောင်းအရာ အများစု database မှာ "
            f"မပါပါ။ ဒီအဖြေက အဲဒီသတင်းစာအတွက် မပြည့်စုံပါ။")


def _article_line(a: dict) -> str:
    paper = (a.get("newspaper_name") or "").strip()
    page = a.get("page_no")
    head = (a.get("headline") or "").strip()
    page_s = f" စာမျက်နှာ {to_burmese_digits(page)}" if page else ""
    return f"  • [{paper}{page_s}] {head}"
