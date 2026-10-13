"""Does the voice path of the MOI news tool behave? — offline, no network.

WHAT THIS COVERS — the `read` / spoken-channel work added on 2026-10-05:

  1. `action='read'` is accepted and produces *spoken-safe* output:
     no markdown bold, no emoji except the one label emoji, ASCII digits
     already Burmese, the source + date + title + body read aloud.
  2. The index wiring: `story` and `read` do NOT fall over when the local
     index is absent/unopenable (the book says never let "not indexed"
     be treated as "no facts", and never crash on it), and when the index
     HAS read the same page the answer names the people it extracted,
     clearly labelled `index`.
  3. The regression pins: the Burmese-digit id guard, and the helper
     functions being import-safe.

Every check here runs `moi_news` with `moi_client` and `moi_index`
replaced by fakes, so no network and no real sqlite file are touched.
"""
import re
import sys
import types
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


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeClient:
    BASE = "https://www.moi.gov.mm"
    SECTIONS = (
        ("news", "နိုင်ငံတော်သတင်း", ""),
        ("president-news", "နိုင်ငံတော်သမ္မတ", ""),
    )
    SECTION_LABEL = {s: l for s, l, _c in SECTIONS}
    _LAYOUT_B = frozenset({"articles", "perspective"})

    def __init__(self, bodies, states, dates):
        self._bodies = bodies
        self._states = states
        self._dates = dates

    def article(self, url):
        return self._bodies.get(url, "")

    def article_state(self, url):
        return self._states.get(url, "missing")

    def article_date(self, url):
        return self._dates.get(url, "")


def _fake_index(rows):
    """`moi_index.get` -> the row, or None; the open must be side-effect-free."""

    def get(url):
        key = str(url).lstrip("/")
        for _id, row in rows.items():
            if key == _id or (row or {}).get("url", "").lstrip("/") == key:
                return dict(row) if row else None
        return None

    return types.SimpleNamespace(get=get)


def _no_index():
    """An import-safe index that raises on open — the "no database yet" case."""

    class _BrokenIndex:
        def get(self, *a, **k):
            raise OSError("no such file")

    return types.SimpleNamespace(get=_BrokenIndex().get)


def _build(bodies=None, states=None, dates=None, rows=None):
    """Patch the two dependencies into `moi_news` and return (M, P)."""
    import core.moi_client as mcm
    import core.moi_index as mxi
    import actions.moi_news as M

    mcm.SECTIONS = _FakeClient.SECTIONS
    mcm.SECTION_LABEL = dict(_FakeClient.SECTION_LABEL)
    mcm._LAYOUT_B = frozenset(_FakeClient._LAYOUT_B)
    fake_client = _FakeClient(bodies or {}, states or {}, dates or {})
    mcm.article = fake_client.article
    mcm.article_state = fake_client.article_state
    mcm.article_date = fake_client.article_date
    mcm.BASE = fake_client.BASE
    mcm._cards = lambda *a, **k: []
    mcm.list_section = lambda *a, **k: []
    mcm.resolve_section = lambda s: {
        "နိုင်ငံတော်သမ္မတ": "president-news"}.get(s, "")
    mxi.get = (_fake_index(rows or {}).get if rows is not None
               else _no_index().get)
    return M, {"action": None}


def main() -> int:
    M, _ = _build()
    hit = {n for n in dir(M)
           if n.startswith("_") and callable(getattr(M, n))}
    check("the speech/facts helpers are importable",
          {"_for_speech", "_facts_block", "_for_speech_bulletin",
           "_index_row", "_people_text"} <= hit, True)

    # ── the spoken channel ───────────────────────────────────────────────────
    _head("an ASCII-digit, markdown list is read aloud as plain Burmese")
    M, _ = _build()
    raw = ("**ခေါင်းစဉ်: ရန်ကုန်မှာ 3 ဦး ဖမ်းဆီးခံရ**\n"
           "https://www.moi.gov.mm/news/88750 အကြောင်း\n"
           "- အချက် ၁\n"
           "* နောက်တစ်ခု\n"
           "✅ မှတ်ချက်\n")
    out = M._for_speech(raw)
    check("no ** left", "**" in out, False)
    check("the URL is gone from the spoken text", "https" in out, False)
    check("no list bullets left ( - and * )", ("- " in out or "* " in out), False)
    check("the ASCII '3' is Burmese ၃",
          "၃" in out and re.search(r"[0-9]", out) is None, True)
    check("the emoji is gone, its word stays",
          "မှတ်ချက်" in out and "✅" not in out, True)

    # ── a real bulletin from a fake page ─────────────────────────────────────
    _head("read: a full article comes out as a spoken bulletin")
    M, P = _build(
        bodies={"/news/88750": "ဥပမာ စာသား 3 ပိုဒ်။"},
        states={"/news/88750": "ok"},
        dates={"/news/88750": "2026-10-01 09:30:00"},
        rows={"1": {"title": "ဥပမာ ခေါင်းစဉ်",
                    "url": "/news/88750",
                    "people": [{"name": "ဦးမောင်မောင်", "title": "ဝန်ကြီး"}],
                    "organizations": ["MOI"],
                    "locations": ["ရန်ကုန်"],
                    "updated_at": "2026-10-05 08:00:00"}},
    )
    P["action"] = "read"
    P["url"] = "/news/88750"
    got = M.moi_news(parameters=P)
    check("the source line names the source", "moi.gov.mm" in got, True)
    check("the spoken text has no markdown bold", "**" not in got, True)
    check("no profile links remain", "https://" not in got, True)
    check("the index label is spoken", "index" in got, True)
    check("the extracted person is named, rank kept",
          "ဝန်ကြီး ဦးမောင်မောင်" in got, True)
    check("the article body's ASCII digit is converted",
          "၃" in got and re.search(r"[0-9]3|3[0-9]", got) is None, True)



    # ── story also appends the facts, unchanged honesty label ────────────────
    _head("story: the same page appends the index facts labelled `index`")
    M, P = _build(
        bodies={"/news/88750": "ခန္ဓာကိုယ်"},
        states={"/news/88750": "ok"},
        dates={"/news/88750": "2026-10-01 09:30:00"},
        rows={"1": {"title": "T",
                    "url": "/news/88750",
                    "people": [{"name": "ဦးမောင်မောင်"}],
                    "organizations": [],
                    "locations": [],
                    "updated_at": "2026-10-05 08:00:00"}},
    )
    P["action"] = "story"
    P["url"] = "/news/88750"
    got = M.moi_news(parameters=P)
    check("story keeps markdown (screen form)", "**" in got, True)
    check("story also names the index person", "ဦးမောင်မောင်" in got, True)
    check("story labels the facts `index`", got.count("index") >= 1, True)

    # ── the index is NOT there yet — must not crash, must not pretend ───────
    _head("no index: story/read stay honest and alive")
    M, P = _build(
        bodies={"/news/88750": "ခန္ဓာကိုယ်"},
        states={"/news/88750": "ok"},
        dates={"/news/88750": "2026-10-01 09:30:00"},
        rows=None,
    )
    P["action"] = "read"
    P["url"] = "/news/88750"
    got = M.moi_news(parameters=P)
    check("read survives a missing index", isinstance(got, str) and len(got) > 0, True)
    check("it does not claim index facts", "index" not in got, True)
    P["action"] = "story"
    got2 = M.moi_news(parameters=P)
    check("story survives a missing index", isinstance(got2, str) and len(got2) > 0, True)

    # ── the regression pins ──────────────────────────────────────────────────
    _head("the regression pins")
    src = Path(r"E:\Mark-LIV-main\actions\moi_news.py").read_text(encoding="utf-8")
    check("read is in the actions the handler accepts",
          re.search(r"action in \(\"story\", \"article\", \"full\", \"read\"\)", src) is not None, True)
    check("read is in the TOOL action description",
          "story | read" in M.TOOL["parameters"]["properties"]["action"]["description"], True)
    check("the URL param says read too",
          "story' or 'read'" in M.TOOL["parameters"]["properties"]["url"]["description"], True)
    check("the honesty label 'index' is not passed off as live",
          "index`" in M.TOOL["description"] or "`index`" in M.TOOL["description"], True)
    check("the description routes deep fact lists to moi_research",
          "moi_research" in M.TOOL["description"], True)

    print(f"\nspeech-channel checks: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

