"""moi.gov.mm documents — answer *name* questions about six known PDF pages.

The six URLs (general-pdf/74153, 13696, 74156, node/2800, 74158, 81694) are
HTML wrappers: the <title> holds the document's Burmese name, and the body
embeds a Google Docs viewer pointing at the real PDF under
``sites/default/files/general-pdf/...``. A user asking *any* title — ဥပဒေ,
သတင်းထုတ်ပြန်ချက်, a commission's full name — wants the document behind
that title, so the whole flow is: fetch wrapper → pull title + embedded
PDF URL → download PDF → pdfplumber → match the asked name → hand the
content to the model.

Nothing here trusts glyph order: pdfplumber on these PDFs returns readable
Burmese with scrambled line order, which is fine — a name lookup does not
care which line came first.
"""
from __future__ import annotations

import io
import re
import urllib.request

_TIMEOUT = 25
_MAX_PDF_BYTES = 25 * 1024 * 1024

# (url, note) — note reminds the reader what each wrapper is for.
_DOCUMENT_URLS: tuple[tuple[str, str], ...] = (
    ("https://www.moi.gov.mm/general-pdf/74153", ""),
    ("https://www.moi.gov.mm/general-pdf/13696", ""),
    ("https://www.moi.gov.mm/general-pdf/74156", ""),
    ("https://www.moi.gov.mm/node/2800",         "ပြည်ထောင်စုဝန်ကြီး/ဒုတိယဝန်ကြီး စာရင်း (3-10-2026)"),
    ("https://www.moi.gov.mm/general-pdf/74158", ""),
    ("https://www.moi.gov.mm/general-pdf/81694", ""),
)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
# The wrapper embeds the real PDF through a Google Docs viewer iframe:
#   <iframe id="pdf_reader" src="//docs.google.com/viewer?embedded=true&amp;
#   url=http%3A%2F%2Fwww.moi.gov.mm%2Fsites%2Fdefault%2Ffiles%2Fgeneral-pdf%2F...">
# Protocol-relative `//`, `&amp;`, and a percent-encoded `url=` — the encoded
# PDF path is itself double-encoded (Burmese filename → %25E1…), so `unquote`
# once after parsing the query is not enough: parse_qs already decodes one
# layer, leaving %E1…, which needs a second unquote before download.
_VIEWER_SRC_RE = re.compile(
    r"<iframe[^>]*\bid=[\"']pdf_reader[\"'][^>]*>", re.I)
_QUERY_URL_RE = re.compile(r"[?&]url=([^&\"'>\s]+)")
_DIRECT_RE = re.compile(
    r"https?://[^\s\"'<>]*sites/default/files/general-pdf/[^\s\"'<>]+", re.I)



def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _pdf_url(wrapper_html: str) -> str | None:
    # Prefer the direct file link when the wrapper carries one; otherwise
    # decode the pdf_reader iframe's viewer `url=` (double-encoded, see above).
    m = _DIRECT_RE.search(wrapper_html)
    if m:
        return m.group(0)
    m = _VIEWER_SRC_RE.search(wrapper_html)
    if not m:
        return None
    from urllib.parse import unquote, quote
    q = _QUERY_URL_RE.search(m.group(0).replace("&amp;", "&"))
    if not q:
        return None
    inner = unquote(unquote(q.group(1)))
    if inner.startswith("//"):
        inner = "https:" + inner
    if not inner:
        return None
    # The decoded URL holds a Burmese filename with spaces — urllib refuses
    # control characters, so re-encode the path (keep scheme and slashes).
    return quote(inner, safe=":/")


def _title_of(wrapper_html: str) -> str:
    m = _TITLE_RE.search(wrapper_html)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return re.sub(r"\s*[|·]\s*Ministry of Information.*$", "", t, flags=re.I)


_CACHE: dict[str, dict] = {}


def _load_documents() -> list[dict]:
    """Fetch every wrapper once per process; cached afterwards."""
    if _CACHE.get("docs") is not None:
        return _CACHE["docs"]

    docs: list[dict] = []
    for url, note in _DOCUMENT_URLS:
        entry: dict = {"url": url, "title": "", "pdf_url": "",
                       "text": "", "note": note, "error": ""}
        try:
            html = _fetch(url).decode("utf-8", errors="replace")
            entry["title"] = _title_of(html)
            entry["pdf_url"] = _pdf_url(html) or ""
        except Exception as e:                                  # noqa: BLE001
            entry["error"] = f"wrapper fetch failed: {e}"
        if entry["pdf_url"] and not entry["error"]:
            try:
                raw = _fetch(entry["pdf_url"])
                if len(raw) > _MAX_PDF_BYTES:
                    raise ValueError(f"PDF too large ({len(raw)} bytes)")
                import pdfplumber
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    entry["text"] = "\n".join(
                        (page.extract_text() or "") for page in pdf.pages)
            except Exception as e:                              # noqa: BLE001
                entry["error"] = f"pdf extract failed: {e}"
        docs.append(entry)

    _CACHE["docs"] = docs
    return docs


def _key(s: str) -> str:
    """Consonant-skeleton of a Burmese string.

    pdfplumber text on these PDFs has scrambled combining marks (ြား can come
    out as ုံး), so exact substrings fail. Keep only base consonants
    (U+1000–U+1021) plus ASCII alphanumerics — drop every combining mark,
    spacing vowel sign, medial, tone, space, and digit-punctuation. Both
    'ပြန်ကြား' and its scrambled form reduce to the same skeleton.
    """
    return "".join(
        ch for ch in (s or "")
        if "\u1000" <= ch <= "\u1021" or ch.isascii() and ch.isalnum()
    )


def _matches(asked: str, title: str) -> bool:
    """Substring match on the name, ignoring whitespace differences."""
    squash = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    a, t = squash(asked), squash(title)
    if a and t and (a in t or t in a):
        return True
    # Glyph-order-proof fallback: compare consonant skeletons.
    ka, kt = _key(asked), _key(title)
    return bool(ka) and bool(kt) and (ka in kt or kt in ka)


def moi_documents(parameters: dict = None, **_) -> str:
    """Answer a name question about the six known moi.gov.mm documents.

    Returns the matched document's title, URL, and text so the model can
    answer in Burmese. The signature is `(parameters, ...)` because
    `core/action_loader.py` calls a handler as `fn(parameters=parameters, ...)`
    — a handler that swallows the dict in `**_` runs on defaults.
    """
    p = parameters or {}
    asked = str(p.get("name") or p.get("query") or "").strip()
    if not asked:
        return ("ဘယ်စာတမ်းလဲ ပြောပါ — အမည် (ဥပမာ ဥပဒေ၊ သတင်းထုတ်ပြန်ချက်) "
                "ဖြင့် မေးနိုင်ပါသည်။")

    docs = _load_documents()
    hits = [d for d in docs
            if _matches(asked, d["title"]) or (d["note"] and _matches(asked, d["note"]))]

    # Fallback: no title matched — maybe the user asked about the *content*
    # (e.g. "ပြန်ကြားရေးဝန်ကြီးဌာန ပြည်ထောင်စုဝန်ကြီး နာမည်"). pdfplumber's
    # scrambled glyph order breaks contiguous matching, so rank documents by
    # how many of the question's consonant-bigram pairs appear in their text.
    if not hits:
        ka = _key(asked)
        if len(ka) >= 3:
            ab = {ka[i:i + 2] for i in range(len(ka) - 1)}
            scored = []
            for d in docs:
                if d["error"] or not d["text"]:
                    continue
                tb = {_key(d["text"])[i:i + 2]
                      for i in range(len(_key(d["text"])) - 1)}
                if not tb:
                    continue
                score = sum(1 for g in ab if g in tb) / len(ab)
                scored.append((score, d))
            scored.sort(key=lambda t: -t[0])
            hits = [d for s, d in scored if s >= 0.4][:2]
            if hits:
                hits[0]["_score"] = scored[0][0]

    if not hits:
        titles = "\n".join(f"  • {d['title']}" for d in docs if d["title"])
        return (f"⚠️ '{asked}' နှင့် ကိုက်ညီသော စာတမ်း မတွေ့ပါ။\n"
                f"ရရှိနိုင်သော စာတမ်းများ:\n{titles}\n"
                f"ℹ️ moi.gov.mm မှ တိုက်ရိုက် စစ်ထားတာပါ။")

    out: list[str] = []
    for d in hits[:3]:
        out.append(f"📄 {d['title']}")
        if d.get("_score"):
            out.append(f"(စာသားထဲ ဆင်တူမှု {d['_score']:.0%})")
        if d["note"]:
            out.append(f"({d['note']})")
        if d["error"]:
            out.append(f"⚠️ ဖတ်ရှုမှု ချို့ယွင်းချက်: {d['error']}")
        elif d["text"].strip():
            out.append(d["text"].strip()[:8000])
        else:
            out.append("ℹ️ စာသား ထုတ်ယူ၍ မရပါ — PDF ကို တိုက်ရိုက် ဖွင့်ကြည့်ပါ: "
                       f"{d['pdf_url'] or d['url']}")
        out.append(f"🔗 {d['url']}")
        out.append("")
    return "\n".join(out).strip()


TOOL = {
    "name": "moi_documents",
    "description": (
        "Answer questions naming one of six known moi.gov.mm documents "
        "(ministry orders, announcements, union-minister lists) by its "
        "Burmese title. Use when the user asks about a document by name — "
        "e.g. ဥပဒေ, သတင်းထုတ်ပြန်ချက်, ပြည်ထောင်စုဝန်ကြီး စာရင်း — rather "
        "than searching the news. Not for news sections (moi_news) or "
        "open-ended research (moi_research)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": "The document name the user asked about, in Burmese.",
            },
        },
        "required": ["name"],
    },
    "handler": moi_documents,
}


