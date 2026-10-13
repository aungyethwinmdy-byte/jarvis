"""Shared helpers for the newsroom actions.

The action loader is strictly one `TOOL` dict per file, so the newsroom tools
live in one file each. This module holds what they would otherwise copy — and
since it starts with "_", core/action_loader.py skips it, so it is loaded as a
helper and never mistaken for an action that failed validation.

WHAT "THAT STORY" MEANS
    Every newsroom tool that answers about a single story has to turn the user's
    words into one row. The user is pointing at something JARVIS just read out,
    so there is no id in the sentence — only a reference. Three kinds of
    reference arrive, and they are not equally reliable:

      index   "ဒုတိယသတင်း" / "the second one" — exact, because this module kept
              the list that was read out. Requires the answer to be the one
              still on screen, so it is checked first and never guessed.
      id      an article id, when the model has one.
      query   the headline, or a phrase from it. This is the common case and
              the only one that needs a search — see find_story() for why the
              headline is the hard one.

WHY THE LAST-SHOWN LIST EXISTS AT ALL
    `resolve_story` could have been text-only, and the model does usually pass
    the headline. But "the second one" has no text in it at all, and a user who
    has just heard five headlines will say exactly that. Without a record of
    what was displayed, that request is unanswerable and the tool has to ask a
    question the user has already answered.
"""
import re

# The items most recently put in front of the user, newest first, capped: this
# is a reference list, not an archive, and only the last answer can still be
# being pointed at.
_LAST_SHOWN: list[dict] = []
_LAST_LIMIT = 12

# Burmese digits are accepted in an index too, because the briefing numbers its
# items "၁။ ၂။" and a user reading them back says "၂".
_BURMESE_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")


def show(player, label: str, text: str, items: list[dict] | None = None) -> None:
    """Put the answer in the UI's content panel, and remember what was shown.

    Never fatal if the UI is absent — this is called on the voice path.
    """
    if items is not None:
        remember(items)
    if not player:
        return
    try:
        player.show_content(label, text)
    except Exception:
        pass


def remember(items: list[dict]) -> None:
    """Record the items just displayed, so a later "the second one" resolves."""
    global _LAST_SHOWN
    _LAST_SHOWN = [dict(i) for i in (items or [])][:_LAST_LIMIT]


def last_shown() -> list[dict]:
    """The items most recently displayed, in the order they were numbered."""
    return list(_LAST_SHOWN)


def _as_index(value) -> int | None:
    """A spoken item number -> a 1-based index, or None.

    re.fullmatch, not str.isdigit(): isdigit() is True for a dozen Unicode digit
    blocks including Burmese ၀-၉, so it would accept "၂" as an ASCII number and
    then int() it to the wrong value. The Burmese form is translated first.
    """
    if value is None:
        return None
    text = str(value).translate(_BURMESE_DIGITS).strip()
    if re.fullmatch(r"[0-9]+", text):
        n = int(text)
        if 1 <= n <= _LAST_LIMIT:
            return n
    return None


def _not_found(query: str) -> str:
    return (f"'{query}' ဆိုတဲ့ သတင်းကို သတင်းစောင့်ကြည့်စနစ်ရဲ့ ဒေတာဘေ့စ်မှာ "
            f"ရှာမတွေ့ပါ။ ခေါင်းစဉ်ကို နည်းနည်း ပိုပြီး ပြောပေးပါ၊ "
            f"သို့မဟုတ် 'ဒုတိယသတင်း' လို့ နံပါတ်နဲ့ ပြောပေးပါ။")


def resolve_story(parameters, days: int = 30):
    """The story the user is pointing at -> (article, note).

    Returns exactly one of:
        (article, "")      a resolved row, ready for report_for()/coverage
        (None, message)    an answer to speak instead — never a silent None

    `note` is a line the caller prepends, used when the reference was ambiguous
    and the story had to be chosen: saying which one was picked is the
    difference between a guess and a guess the user can correct.
    """
    from core import newsroom_client as nr

    params = parameters or {}
    shown = last_shown()

    # 1. An explicit number, or a bare number that arrived as the query.
    idx = _as_index(params.get("index")) or _as_index(params.get("query"))
    if idx:
        if not shown:
            # Nothing has been read out yet, so a number cannot refer to
            # anything. Said plainly rather than falling through to the generic
            # "which story?" prompt, which would read as though the number had
            # been understood and the list had been searched.
            return None, ("ဖော်ပြထားတဲ့ သတင်းစာရင်း မရှိသေးပါ။ "
                          "သတင်းခေါင်းစဉ်ကို ပြောပေးပါ၊ သို့မဟုတ် "
                          "သတင်းစာရင်း ပြခိုင်းပါ။")
        if idx <= len(shown):
            item = shown[idx - 1]
            if item.get("article_id"):
                art = nr.article_by_id(item["article_id"])
                if art:
                    return art, ""
            # No id carried, or the row is gone: fall back to the title we
            # spoke. The report headline is what the user heard, so it is also
            # what finds it — see find_story().
            art = nr.find_story(item.get("title") or item.get("headline") or "", days=days)
            if art:
                return art, ""
        return None, (f"ဖော်ပြထားတဲ့ သတင်း {len(shown)} ပုဒ်ထဲမှာ "
                      f"{idx} ခုမြောက်ဆိုတာ မရှိပါ။")

    # 2. An id, when the model was handed one.
    art_id = str(params.get("article_id") or "").strip()
    if art_id:
        art = nr.article_by_id(art_id)
        if art:
            return art, ""
        return None, _not_found(art_id)

    # 3. Free text — the headline, or a phrase from it.
    query = str(params.get("query") or params.get("story") or params.get("title") or "").strip()
    if query:
        art = nr.find_story(query, days=days)
        if art:
            return art, ""
        return None, _not_found(query)

    # 4. Nothing at all. The newest displayed story is the likeliest referent,
    #    and answering is better than asking — but the answer says which one it
    #    picked, so a wrong choice is visible instead of silent.
    if shown:
        item = shown[0]
        art = (nr.article_by_id(item["article_id"]) if item.get("article_id") else None) \
            or nr.find_story(item.get("title") or item.get("headline") or "", days=days)
        if art:
            return art, "ဖော်ပြထားတဲ့ သတင်းတွေထဲက အသစ်ဆုံးတစ်ပုဒ်ကို ဆိုလိုသည်ဟု ယူဆပါသည် —"

    return None, ("ဘယ်သတင်းအကြောင်း ပြောနေတာလဲ မသိပါ။ သတင်းခေါင်းစဉ်ကို "
                  "ပြောပေးပါ၊ သို့မဟုတ် 'ဒုတိယသတင်း' လို့ နံပါတ်နဲ့ ပြောပေးပါ။")
