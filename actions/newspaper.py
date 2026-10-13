"""Download the Myanmar state newspapers by date, and summarise their main news.

WHAT THIS IS FOR
    "၂၀၂၆ ခုနှစ် စက်တင်ဘာ ၁၂ ရက်နေ့ သတင်းစာကို ဒေါင်းလော့ဆွဲပေးပါ" then
    "မြန်မာ့အလင်းသတင်းစာကို အဓိကသတင်းတွေပဲ အနှစ်ချုပ်ပေးပါ".
    Two steps, and the two steps have very different costs — see LATENCY below.

WHERE THE FILES COME FROM
    https://www.mdn.gov.mm/newspaper/public/?published_date=<D>-<M>-<YYYY>
    lists that day's editions as <div class="newspaper <slug>"> blocks, each with
    a cover image, the date, and two links: /ebooks/read/<id> and
    /ebooks/download/<id>. The download link answers application/pdf with
    Content-Disposition naming the file, e.g. myanmaalinn_06_04_2024.pdf.

    THE DATE IS D-M-YYYY, NOT THE AMERICAN M-D-YYYY. Measured 2026-09-27:
    ?published_date=25-4-2024 returns 25 April 2024; ?published_date=4-25-2024
    returns an empty page. A date built in the wrong order does not error — it
    silently answers "no newspapers that day", which reads as "the archive is
    missing" rather than "the URL is wrong".

WHY THE TEXT IS READ AS AN IMAGE AND NOT EXTRACTED
    These PDFs have a text layer and it is useless. Measured on the 6 April 2024
    မြန်မာ့အလင်း (32 pages, 16.8 MB):

        pdfplumber  ->  (cid:2)(cid:3)(cid:4)(cid:5)...
        PyMuPDF     ->  '\\x02\\x03\\x04\\x05\\x06...'   (raw glyph ids)
        pypdf       ->  /g194/g196/g201...

    All three are non-blank, so any `if text.strip():` gate accepts them. The
    cause is in the fonts: the Burmese faces (MMAL4Uni, MMAL3Uni) carry **no
    /ToUnicode at all**, and the two PyidaungsuBook faces carry a CMap that maps
    only a couple of dozen Latin glyphs (<5e>->H, <5f>->S, <60>->D) for the
    English words on the page. There is nothing to map Burmese through.

    So this module never calls a text extractor. The page is rendered and read.
    That is not a fallback here, it is the only reader that works. (This is the
    same defect the `pdf-text-layer-forensics` skill documents for moi.gov.mm,
    which serves the same papers.)

    Resolution matters and was measured: 72 dpi JPEG (0.1 MB) is enough to
    recognise the paper, 100 dpi (0.19 MB) reads the headlines, and a 110 dpi
    PNG (0.95 MB) timed out on every model in the ladder. 130 dpi was slower
    again with no better answer — for the summary. The setting is now 150 dpi
    JPEG (0.49 MB), because of a different failure: see _PAGE_DPI.

WHY tier=FAST AND NOT tier=SMART
    Measured 2026-09-27, same 100 dpi image, same prompt:
        FAST   -> 24.1 s, real Burmese headlines
        SMART  -> timed out on all three models (live, 3.8-flash, 3.5-flash-lite)
    SMART tries the Live API first, which is built for a continuous
    conversation, not a one-shot image. FAST is the right ladder for this.

LATENCY, STATED HONESTLY
    Measured 2026-09-27 on the 16.8 MB edition, over this machine's proxy:
    **download 106 s, reading one page 34 s.** Both are far larger than they
    look, which is why the two jobs are separate actions and why the tool
    description tells the model to say it is working before it calls. A
    two-minute silence with no warning reads as a hang, and the user hangs up.

    The download streams in 256 KB chunks. A single `read()` of the whole body
    raised IncompleteRead(14530688 read, 3067868 more expected) on the first
    attempt — the connection drops partway and the un-chunked call loses
    everything. Chunked reads survive it, and a Range header resumes a partial
    file rather than starting the 17 MB again.

WHAT THIS DELIBERATELY DOES NOT DO
    It does not summarise from memory, and it does not fill gaps. The prompt
    asks for what is printed and nothing else, because the only thing worse
    than "I could not read the page" is a confident summary of a page that was
    never read.
"""
import io
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from core.timefmt import MMT, burmese_date, now_mmt, to_burmese_digits

# ── Where things live ────────────────────────────────────────────────────────

_BASE = Path(__file__).resolve().parent.parent
_OUT_DIR = _BASE / "downloads" / "newspapers"   # downloads/ is already gitignored

_SITE = "https://www.mdn.gov.mm/newspaper/public"
_LIST = _SITE + "/?published_date={d}-{m}-{y}"
_DOWNLOAD = _SITE + "/ebooks/download/{id}"

# The slug is the CSS class on each block of the listing page, which is how the
# three editions are told apart — the visible name is an image, not text.
PAPERS: dict[str, str] = {
    "myanmaalinn": "မြန်မာ့အလင်း",
    "themirror": "ကြေးမုံ",
    "newlightmyanmar": "New Light of Myanmar",
}
_DEFAULT_PAPER = "myanmaalinn"

# Burmese spellings the user may actually say, mapped onto the slugs.
_ALIASES: dict[str, str] = {
    "မြန်မာ့အလင်း": "myanmaalinn",
    "မြန်မာ့အလင်းသတင်းစာ": "myanmaalinn",
    "ကြေးမုံ": "themirror",
    "ကြေးမုံသတင်းစာ": "themirror",
    "နယူးလိုက်": "newlightmyanmar",
    "new light": "newlightmyanmar",
    "new light of myanmar": "newlightmyanmar",
}

# ── Tunables, all measured (see the module docstring) ────────────────────────

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

_RETRY_ATTEMPTS = 3
_RETRY_MIN_SLICE = 5.0
_RETRY_DELAY = 0.8

_CHUNK = 262144            # 256 KB — see LATENCY
# 150 dpi, not 110. Measured 2026-09-28 on the same front page: 110 dpi is
# 294 KB / 910x1287 and 150 dpi is 490 KB / 1241x1755 — both far inside the
# limit that killed the 0.95 MB PNG — and the smaller the glyph, the more the
# extra pixels matter. Burmese stacks four or five codepoints into one syllable,
# so a name that differs from another by a single mark is a handful of pixels
# apart at 110 dpi.
_PAGE_DPI = 150
_JPEG_QUALITY = 80
_MAX_PAGES = 4             # a summary of more than the first few pages is not a summary

_TIMEOUT_LIST = 25.0
_TIMEOUT_PDF = 120.0

# One listing page per date is reused by the two actions in a session, and the
# same date is often asked for twice ("download it" then "summarise it").
_CACHE_TTL = 600.0
_CACHE: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, produce):
    """`produce()` once per key per _CACHE_TTL. Failures are never cached."""
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    value = produce()
    _CACHE[key] = (time.time(), value)
    return value


class _NewspaperError(Exception):
    """Internal only. The message is already a Burmese sentence fit to speak."""


def _log(message: str, player=None) -> None:
    print(f"[Newspaper] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Transport ────────────────────────────────────────────────────────────────

def _open(url: str, timeout: float, extra: dict | None = None):
    headers = {"User-Agent": _UA, "Accept-Language": "my-MM,my;q=0.9,en;q=0.8"}
    headers.update(extra or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                  timeout=timeout)


def _get_bytes(url: str, timeout: float) -> bytes:
    """GET with a bounded retry, like every other outbound fetch in this project.

    `timeout` is the budget for the whole call, not per attempt: the first try
    may spend all of it, the retry gets what is left with a floor so a fast
    refusal still leaves a usable second try. Transport failures only — a 404
    would fail identically the second time.
    """
    deadline = time.monotonic() + timeout
    last: Exception | None = None

    for attempt in range(_RETRY_ATTEMPTS):
        left = deadline - time.monotonic()
        budget = timeout if attempt == 0 else max(_RETRY_MIN_SLICE, left)
        try:
            with _open(url, budget) as r:
                return r.read()
        except (OSError, ValueError) as e:
            last = e
            if attempt + 1 < _RETRY_ATTEMPTS:
                print(f"[Newspaper] ⚠️ {type(e).__name__} — retrying "
                      f"({attempt + 2}/{_RETRY_ATTEMPTS})")
                time.sleep(_RETRY_DELAY)
    raise last if last else RuntimeError("request failed")


def _download_pdf(url: str, dest: Path, timeout: float = _TIMEOUT_PDF) -> Path:
    """Stream a PDF to `dest`, resuming from whatever is already there.

    Reads in chunks and re-requests the remainder with a Range header on a
    dropped connection. A single read() of this body raised
    IncompleteRead(14530688, +3067868) — the whole 17 MB is lost to one blip,
    where a chunked read with resume loses nothing.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    total = None
    try:
        with _open(url, 20.0, {"Range": "bytes=0-0"}) as r:
            rng = r.headers.get("Content-Range") or ""
            if "/" in rng:
                total = int(rng.rsplit("/", 1)[-1])
    except Exception:
        pass   # no size known: fall back to "stop when the stream ends"

    deadline = time.monotonic() + timeout
    last: Exception | None = None

    for attempt in range(_RETRY_ATTEMPTS):
        have = dest.stat().st_size if dest.exists() else 0
        if total and have >= total:
            break
        if time.monotonic() > deadline:
            break

        extra = {"Range": f"bytes={have}-"} if have else None
        try:
            with _open(url, max(_RETRY_MIN_SLICE, deadline - time.monotonic()),
                       extra) as r, open(dest, "ab") as f:
                while True:
                    chunk = r.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    if time.monotonic() > deadline:
                        break
        except (OSError, ValueError) as e:
            last = e
            print(f"[Newspaper] ⚠️ download dropped at "
                  f"{dest.stat().st_size if dest.exists() else 0} bytes "
                  f"({type(e).__name__}) — resuming")
            time.sleep(_RETRY_DELAY)
            continue
        if total is None:
            break
        if dest.stat().st_size >= total:
            break

    have = dest.stat().st_size if dest.exists() else 0
    if have == 0:
        raise last or _NewspaperError("သတင်းစာ ဖိုင် ဒေါင်းလုပ် မရပါ။")
    if total and have < total:
        raise _NewspaperError(
            f"သတင်းစာ ဖိုင် ဒေါင်းလုပ် အပြည့်အစုံ မရပါ "
            f"({round(have / 1048576, 1)} MB / {round(total / 1048576, 1)} MB)။")
    if dest.read_bytes()[:5] != b"%PDF-":
        raise _NewspaperError("ဒေါင်းလုပ် ရလာတာ PDF ဖိုင် မဟုတ်ပါ။")
    return dest


# ── The listing page ─────────────────────────────────────────────────────────

# Each block looks like:
#   <div class="newspaper myanmaalinn radius"> ... <a href=".../read/9742">
#   ... <a href=".../download/9742"> ... <p class="whitetext news-date">06 April 2024</p>
_BLOCK_RE = re.compile(r'<div class="newspaper ([a-z]+)[^"]*"')
_DOWNLOAD_RE = re.compile(r'ebooks/download/(\d+)')


def _editions(day: date, timeout: float = _TIMEOUT_LIST) -> list[dict]:
    """Every edition the site has for `day`, in the order the page lists them.

    Raises _NewspaperError with a speakable sentence when the date is empty or
    unreachable — the caller is a voice assistant, and an exception here would
    become silence.
    """
    def produce():
        url = _LIST.format(d=day.day, m=day.month, y=day.year)   # D-M-YYYY, never M-D
        html = _get_bytes(url, timeout).decode("utf-8", "replace")
        out = []
        for m in _BLOCK_RE.finditer(html):
            slug = m.group(1)
            # The download link belongs to the block that starts here, so only
            # look as far as the next block header.
            nxt = html.find('<div class="newspaper ', m.end())
            window = html[m.end(): nxt if nxt != -1 else len(html)]
            dl = _DOWNLOAD_RE.search(window)
            if not dl:
                continue
            out.append({
                "slug": slug,
                "name": PAPERS.get(slug, slug),
                "id": dl.group(1),
                "url": _DOWNLOAD.format(id=dl.group(1)),
                "page": url,
            })
        return out

    try:
        editions = _cached(("list", day.isoformat()), produce)
    except Exception as e:
        raise _NewspaperError(
            f"သတင်းစာ စာမျက်နှာ ဖွင့်လို့ မရပါ ({type(e).__name__})။ "
            f"အင်တာနက် ချိတ်ဆက်မှုကို စစ်ဆေးပေးပါ။") from e

    if not editions:
        raise _NewspaperError(
            f"{burmese_date(datetime(day.year, day.month, day.day, tzinfo=MMT))} "
            f"အတွက် သတင်းစာ မတွေ့ပါ။ ရက်စွဲ မှန်မမှန် စစ်ဆေးပေးပါ။")
    return editions


def _pick(editions: list[dict], wanted: str) -> dict | None:
    """The edition the user named, or None if that paper is not in this list."""
    if not wanted:
        return None
    key = wanted.strip().lower()
    key = _ALIASES.get(wanted.strip(), key)
    for e in editions:
        if e["slug"] == key or e["name"].lower() == key:
            return e
    return None


# ── Date parsing ─────────────────────────────────────────────────────────────

def _parse_day(raw: str) -> date:
    """'2026-09-12' | '12-9-2026' | 'today' | 'yesterday' -> a date in MMT.

    Both orders are accepted because the two are used in different places: the
    user's own words arrive as ISO from the model, and the site's URL is
    D-M-YYYY. Guessing wrongly is silent — the wrong day simply has no papers.
    """
    text = (raw or "").strip()
    if not text or text.lower() in ("today", "now", "ဒီနေ့"):
        return now_mmt().date()
    if text.lower() in ("yesterday", "မနေ့က"):
        return (now_mmt() - timedelta(days=1)).date()

    text = text.replace("/", "-").replace(".", "-").replace(" ", "-")
    # Burmese digits, because the model sometimes passes the date back as written
    text = text.translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789"))
    parts = [p for p in text.split("-") if p != ""]
    if len(parts) == 3:
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            nums = []
        if nums:
            a, b, c = nums
            if a > 31:                      # YYYY-MM-DD
                return date(a, b, c)
            if c > 31:                      # D-M-YYYY  (or M-D-YYYY when day <= 12)
                year = 2000 + c if c < 100 else c
                # Ambiguous only when both are <= 12; the site's order wins.
                try:
                    return date(year, b, a)
                except ValueError:
                    return date(year, a, b)
    raise _NewspaperError(
        f"'{raw}' ဆိုတဲ့ ရက်စွဲကို နားမလည်ပါ။ ဥပမာ — ၂၀၂၆ စက်တင်ဘာ ၁၂၊ "
        f"ဒါမှမဟုတ် 12-9-2026 လို့ ပြောပါ။")



def newspaper_action(parameters: dict, player=None, session_memory=None) -> str:
    """One entry point for both jobs, because the loader takes one TOOL per file.

    `action` decides which; anything unrecognised is treated as a download,
    which is the harmless direction — a download that was not wanted costs
    bandwidth, a summary that was not wanted costs a wrong answer.
    """
    params = parameters or {}
    action = (params.get("action") or "download").strip().lower()
    wanted = (params.get("paper") or "").strip()

    try:
        day = _parse_day(params.get("date") or "today")
    except _NewspaperError as e:
        return str(e)

    try:
        if action == "list":
            editions = _editions(day)
            names = "၊ ".join(f"{e['name']}" for e in editions)
            label = burmese_date(datetime(day.year, day.month, day.day, tzinfo=MMT))
            return f"{label} အတွက် သတင်းစာ {to_burmese_digits(len(editions))} စောင် ရှိပါတယ် — {names}။"

        if action in ("summarize", "summarise", "summary"):
            # ── Answered from the database, not from the PDF ─────────────────
            #
            # The user's decision, 2026-09-29: *"ဒေါင်းလော့လုပ်တဲ့ သတင်းစာတွေက
            # ငါရဲ့ ကွန်ပြူတာမှာ သိမ်းဖို့သက်သက်လုပ်မယ်။ သတင်းရှာခိုင်းဖို့
            # မသုံးတော့ဘူး။ သတင်းနဲ့ပတ်သက်ပြီး ငါရှာခိုင်းရင် database ထဲကပဲ
            # သွားရှာရမယ်။"*
            #
            # So a PDF is now something to keep, and nothing to read. The
            # vision path that used to open the front page is gone from this
            # branch — it answered from one page of one day, and the database
            # holds every article of both papers with their dates and page
            # numbers.
            #
            # This redirects rather than refusing: the model asked for a
            # newspaper's news, and the database can answer that. A refusal
            # would cost the user a second round-trip to get the same thing.
            try:
                from actions.reporter_news import reporter_news
                # Called through the loader's own path. Calling it directly with
                # keywords would be a path the application never uses — and that
                # is exactly how four tools ended up ignoring their arguments
                # while every check passed. See `core/action_loader.py:120`.
                from core.action_loader import _call_handler
                text = _call_handler(
                    reporter_news,
                    {"action": "day", "date": day.isoformat(), "limit": 8},
                    {"player": player},
                )
            except Exception as e:                          # noqa: BLE001
                print(f"[Newspaper] database redirect failed: {type(e).__name__}: {e}")
                text = ("သတင်းစာ အနှစ်ချုပ်ကို database ကနေ ဖတ်ဖို့ ကြိုးစားတာ "
                        f"မအောင်မြင်ပါ ({type(e).__name__})။")
        else:
            text = _do_download(day, wanted, player)
    except _NewspaperError as e:
        text = str(e)
    except Exception as e:
        # The voice path must not raise. A network blink becomes a sentence.
        print(f"[Newspaper] unexpected: {type(e).__name__}: {e}")
        text = f"သတင်းစာ လုပ်ဆောင်မှု မအောင်မြင်ပါ ({type(e).__name__})။"

    if session_memory:
        try:
            session_memory.set_last_search(
                query=f"newspaper {action} {wanted} {day.isoformat()}", response=text)
        except Exception:
            pass
    return text


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
# ONE dict per file. A second one here and the loader registers NEITHER, silently.
TOOL = {
    "name": "newspaper",
    "description": (
        "Download a Myanmar state newspaper for a given date, and summarise its "
        "main news. Papers: မြန်မာ့အလင်း (myanmaalinn), ကြေးမုံ (themirror), "
        "New Light of Myanmar (newlightmyanmar). Source is the government "
        "archive mdn.gov.mm, so it only has state-run papers and only for the "
        "dates it has published.\n"
        "\n"
        "action='download' — fetch the PDF and save it. The file is NOT opened "
        "or shown; the user is told which day's paper arrived. Use this when "
        "the user asks to download or get a newspaper for a "
        "date: 'ဒီနေ့ သတင်းစာ ဒေါင်းလော့ဆွဲပါ', '၂၀၂၆ စက်တင်ဘာ ၁၂ ရက်နေ့ "
        "မြန်မာ့အလင်း ဒေါင်းလော့ဆွဲပေးပါ'. This takes ONE TO TWO MINUTES for a "
        "full edition, so tell the user you are downloading it before calling "
        "this — otherwise the wait sounds like a crash. Do NOT say you opened "
        "or displayed the file — you did not.\n"
        "\n"
        "**The downloaded PDF is for keeping, never for reading.** The user "
        "decided this on 2026-09-29: a saved newspaper is a file on his "
        "computer, and every question about news is answered from the "
        "database. Never open the PDF, never read it with vision, and never "
        "quote it. For news content use action='summarize' (below), or "
        "reporter_news / news_search for anything with a topic or a name in "
        "it.\n"
        "\n"
        "action='summarize' — ANSWERED FROM THE DATABASE, not from the PDF. It "
        "reads the articles stored for that date and speaks them. Use it when "
        "the user asks what the news is for a day, or to summarise a "
        "newspaper: 'မြန်မာ့အလင်း အဓိကသတင်း အနှစ်ချုပ်', 'ဒီနေ့ သတင်းစာထဲ "
        "ဘာတွေပါလဲ'. It is fast — no file is downloaded or opened.\n"
        "\n"
        "action='list' — say which papers exist for a date. Cheap; use it when "
        "the user asks what is available.\n"
        "\n"
        "The date is passed as YYYY-MM-DD, or 'today' / 'yesterday'. Do NOT "
        "answer a question about a newspaper's contents from memory — always "
        "call this and report what it returns."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'download' | 'summarize' | 'list'. Default 'download'.",
            },
            "date": {
                "type": "STRING",
                "description": ("The publication date as YYYY-MM-DD, or 'today' / "
                                "'yesterday'. Defaults to today."),
            },
            "paper": {
                "type": "STRING",
                "description": ("Which paper: 'မြန်မာ့အလင်း', 'ကြေးမုံ', "
                                "'newlightmyanmar'. Defaults to မြန်မာ့အလင်း. "
                                "For action='download', leaving it empty downloads "
                                "all of that day's papers."),
            },
        },
        "required": ["action"],
    },
    "handler": newspaper_action,
}
