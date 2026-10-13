"""Learning Burmese from how the user actually speaks — and how JARVIS mangles it.

TWO PROBLEMS, TWO MECHANISMS

    1. **It mishears him.** The model transcribes his speech and sometimes gets a
       word wrong. These errors are *systematic* — the same word is misheard the
       same way every time — which means a substitution table fixes them
       permanently. `fix_heard()` runs on every transcript before the model sees
       it.

    2. **It mispronounces.** A prebuilt voice reading Burmese gets some words
       wrong ("အသံတွေ ဝဲနေတယ်"). `fix_for_speech()` rewrites text on its way to
       the voice.

WHAT THIS CANNOT DO

    It cannot retrain the recogniser or the voice. Both are Google's models and
    are not fine-tunable from here. What it can do is put a correction layer in
    front of each — which is how pronunciation and transcription are fixed in
    practice everywhere, and which is honest about where the boundary is.

WHY IT LEARNS ONLY FROM CORRECTIONS, NOT FROM EVERYTHING

    Learning passively from every utterance would mean the assistant learning its
    own mistakes. `memory/memory_manager.py` already carries a `source: user |
    model` field for exactly this reason — the model's inference must not be fed
    back as a fact the user stated. The same rule applies here, and more sharply:
    **a wrong entry in this file changes what the user hears, silently.**

    So nothing is learned unless the user says it is wrong. `heard_log()`
    records what was heard so a correction can be made against it, but the log
    alone never becomes a rule.

STORAGE

    `memory/burmese_learning.jsonl` — one JSON object per line, append-only.
    Deliberately NOT the prompt-injected memory: a few hundred pronunciation
    entries would crowd out the system prompt, and these are looked up by
    exact key rather than recalled by relevance.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_STORE = _BASE / "memory" / "burmese_learning.jsonl"
_LOCK = threading.Lock()

# How many recent utterances to keep. Enough to find the one that was misheard,
# small enough that the file stays readable by hand.
_HEARD_KEEP = 200

# Burmese syllable boundaries: an initial consonant, optional stacked consonant,
# optional medials, any vowels and tones, and an optional **final consonant
# closed by asat**.
#
# Two corrections were needed, both found by printing the output:
#   1. The first version listed the combining marks by hand and **left out `်`
#      (asat, U+103A)** — so `မြန်မာ့အလင်း` produced nothing at all, because its
#      second syllable ends in one. The class now takes the whole range.
#   2. It then split `မြန်မာ` as `မြ · န် · မာ`, treating the asat as the start
#      of a syllable instead of the end of one. `မြန်` is one syllable — a
#      Burmese syllable may close on a consonant — and a wrong split sounds
#      worse than no split at all, which is the opposite of the point.
# Used only to offer a *suggestion* — never applied without the user picking it.
_SYLLABLE = re.compile(
    r"[က-အ](?:္[က-အ])?[ျြွှ]?[\u102b-\u1038]*"
    r"(?:[က-အ]်[\u102b-\u1038]*)?"   # a final consonant, then any tone on it
)


def _read() -> list[dict]:
    if not _STORE.exists():
        return []
    out: list[dict] = []
    try:
        for line in _STORE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _append(record: dict) -> None:
    record.setdefault("when", datetime.now().isoformat(timespec="seconds"))
    with _LOCK:
        try:
            _STORE.parent.mkdir(parents=True, exist_ok=True)
            with _STORE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"[Burmese] could not write {_STORE}: {exc}")


def _rewrite(records: list[dict]) -> None:
    """Replace the file. Used only to compact the heard log."""
    with _LOCK:
        try:
            _STORE.parent.mkdir(parents=True, exist_ok=True)
            with _STORE.open("w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"[Burmese] could not rewrite {_STORE}: {exc}")


# ── 1. What the model heard ──────────────────────────────────────────────────

def log_heard(text: str) -> None:
    """Record one utterance as transcribed. Never becomes a rule by itself."""
    text = (text or "").strip()
    if len(text) < 2:
        return
    _append({"kind": "heard", "text": text, "at": time.time()})

    # Compact occasionally so the file does not grow without limit. Kept in the
    # same append-only shape so a crash mid-rewrite loses only the oldest lines.
    records = _read()
    heard = [r for r in records if r.get("kind") == "heard"]
    if len(heard) > _HEARD_KEEP:
        keep = set(id(r) for r in heard[-_HEARD_KEEP:])
        _rewrite([r for r in records
                  if r.get("kind") != "heard" or id(r) in keep])


def heard_log(limit: int = 15) -> list[str]:
    """The most recent transcriptions, newest last."""
    return [r.get("text", "") for r in _read()
            if r.get("kind") == "heard"][-limit:]


# ── 2. Mishearing: heard → what he actually said ─────────────────────────────

# A correction is a re-hearing, not a disagreement — see `record_correction`.
# Measured as the share of `heard` that survives in `meant`: real corrections
# 0.77–1.00, a factual disagreement 0.36, an ordinary reply 0.44.
_CORRECTION_MIN_RATIO = 0.65


def record_correction(heard: str, meant: str, note: str = "") -> str:
    """Learn that `heard` is a mishearing of `meant`.

    Both are required and must differ — a correction that maps a word to itself
    is a no-op that would silently sit in the table looking like knowledge.

    **And `meant` must actually be a re-hearing of `heard`.** A correction is a
    *speech* repair; it says "the same sentence, heard wrong". It is not a place
    to record a disagreement about facts, and treating one as the other is not a
    cosmetic error — it **rewrites the question permanently**.

    Measured 2026-09-30, in a live voice session: JARVIS answered *"no
    president or vice-president is named today"* (correct — the 2026-09-30
    edition names neither). The owner replied *"ပါတယ်လေ ဒုတိယသမ္မတ ဦးညိုစော
    သတင်း"* — **"there IS, the vice-president ဦးညိုစော's news"**, a claim about
    the newspaper. The model read that as a mishearing and stored

        heard: နိုင်ငံတော်သမ္မတနဲ့ ဒုတိယတွေရဲ့ သတင်းတွေပါလား
        meant: ပါတယ်လေ ဒုတိယသမ္မတ ဦးညိုစော သတင်း

    From then on every *"နိုင်ငံတော်သမ္မတနဲ့ ဒုတိယတွေရဲ့ သတင်းတွေပါလား"* is
    silently replaced by a sentence about one vice-president, and the question can
    never be asked again. **One wrong entry here changes what the user hears,
    forever** — the module docstring's own warning, realised.

    The two are told apart by **how much of `heard` survives in `meant`** — a
    re-hearing keeps the utterance, a disagreement replaces it. Measured, as the
    share of `heard` that still appears in `meant`:

        ဆီဈေး            → စက်သုံးဆီဈေး          1.00   (a word, extended)
        မန်းမာအလင်း မှာ သတင်း → မြန်မာ့အလင်း မှာ သတင်း   0.95
        ကြေးမံုသတင်းစာ      → ကြေးမုံသတင်းစာ        0.93
        ဒုတိယသမ္မတ ဦးညိမ်းဇော် → ဒုတိယသမ္မတ ဦးညိုစော   0.77
        the disagreement above                          0.36
        an ordinary reply                               0.44

    **Whole-string similarity is the wrong measure** — it rejected the legitimate
    `ဆီဈေး → စက်သုံးဆီဈေး` at 0.63 because the replacement is twice as long. What
    matters is not that the two strings look alike but that the one the user
    *said* is still there.
    """
    heard = (heard or "").strip()
    meant = (meant or "").strip()
    if not heard or not meant:
        return "စကားလုံး ၂ ခုလုံး လိုပါတယ် — ကြားတာနဲ့ ဆိုလိုတာ။"
    if heard == meant:
        return "နှစ်ခု တူတူဖြစ်နေတယ် — မှတ်စရာ မရှိဘူး။"
    _sm = SequenceMatcher(None, heard, meant)
    _kept = sum(b.size for b in _sm.get_matching_blocks()) / max(1, len(heard))
    if _kept < _CORRECTION_MIN_RATIO:
        return ("ဒါ နားမှားတာ မဟုတ်ဘူးလို့ ထင်ပါတယ် — ကြားတာနဲ့ "
                "ဆိုလိုတာ စကားလုံး အများကြီး ကွာနေတယ်။\n"
                "နားမှားတာ ဆိုတာ ကိုယ်ကြားတာနဲ့ ဆိုလိုတာ တူတူပဲ ဖြစ်ပြီး "
                "အသံထွက် ကွာတာပါ။\n"
                "အဖြေ မှားတာဆိုရင် ဒါ မှတ်စရာ မဟုတ်ပါ — မေးခွန်းကို "
                "ပြန်ပြောပေးပါ။")
    _append({"kind": "correction", "heard": heard, "meant": meant, "note": note})
    return f"မှတ်ပြီ — '{heard}' ကို '{meant}' လို့ နားလည်မယ်။"


def corrections() -> dict[str, str]:
    """The learned substitutions, later entries winning."""
    out: dict[str, str] = {}
    for r in _read():
        if r.get("kind") == "correction":
            out[r.get("heard", "")] = r.get("meant", "")
    return {k: v for k, v in out.items() if k and v}


def _apply_once(text: str, table: dict[str, str]) -> str:
    """Replace every key in ONE left-to-right pass, longest alternative first.

    NOT a loop of `str.replace`. The first version applied the rules in sequence
    and the output of one became the input of the next: with `ဆီ → စက်သုံးဆီ` and
    `ဆီဈေး → စက်သုံးဆီဈေး` both learned, `ဆီဈေး` became `စက်သုံးဆီဈေး` and then the
    shorter rule fired again on the result, giving **`စက်သုံးစက်သုံးဆီဈေး`**.
    A single pass with an alternation cannot do that — each position in the
    original text is replaced once, and a replacement is never re-scanned.
    Found by a check, not by reading.
    """
    if not table or not text:
        return text
    pattern = "|".join(re.escape(k) for k in sorted(table, key=len, reverse=True))
    return re.sub(pattern, lambda m: table[m.group(0)], text)


def fix_heard(text: str) -> str:
    """Apply the learned corrections to a transcript."""
    return _apply_once(text or "", corrections())


def fix_for_speech(text: str) -> str:
    """Apply the learned pronunciation rewrites on the way to the voice."""
    return _apply_once(text or "", pronunciations())


# ── 3. Mispronunciation: what to say instead ─────────────────────────────────

def record_pronunciation(word: str, say_as: str, note: str = "") -> str:
    """Learn that `word` should be written `say_as` on its way to the voice."""
    word = (word or "").strip()
    say_as = (say_as or "").strip()
    if not word or not say_as:
        return "စကားလုံးနဲ့ ရွတ်ဆိုပုံ ၂ ခုလုံး လိုပါတယ်။"
    _append({"kind": "pronunciation", "word": word, "say_as": say_as, "note": note})
    return f"မှတ်ပြီ — '{word}' ကို '{say_as}' လို့ ရွတ်မယ်။"


def pronunciations() -> dict[str, str]:
    out: dict[str, str] = {}
    for r in _read():
        if r.get("kind") == "pronunciation":
            out[r.get("word", "")] = r.get("say_as", "")
    return {k: v for k, v in out.items() if k and v}


def suggest_respellings(word: str, limit: int = 3) -> list[str]:
    """Candidate rewrites to try out loud, best guess first.

    A suggestion is only ever *spoken for the user to judge* — nothing is stored
    until he picks one. Guessing a pronunciation and storing it would change
    what he hears without him agreeing to it.
    """
    word = (word or "").strip()
    if not word:
        return []

    out: list[str] = []

    # Syllables separated by a thin space. The commonest cause of a slurred
    # word is the voice running syllables together; giving it a boundary is
    # the cheapest fix and often the only one needed.
    #
    # Burmese syllable segmentation is genuinely hard and this is a coarse
    # approximation — which is why nothing is stored until the user listens and
    # picks. When it produces nothing usable the tool says so and asks him to
    # supply the respelling himself rather than inventing one.
    sylls = _SYLLABLE.findall(word)
    if len(sylls) >= 2 and "".join(sylls) == word:
        out.append("\u2009".join(sylls))
        out.append(" ".join(sylls))
        # Zero-width separators — some engines respect them where a real space
        # would change the spacing of the rendered sentence.
        out.append("\u200b".join(sylls))

    # The word with a trailing asat — changes how the final syllable closes,
    # which is where several Burmese words go wrong.
    if word and not word.endswith("်"):
        out.append(word + "်")

    seen: list[str] = []
    for s in out:
        if s and s != word and s not in seen:
            seen.append(s)
    return seen[:limit]


# ── 4. What has been learned ─────────────────────────────────────────────────

def stats() -> dict:
    records = _read()
    return {
        "heard": sum(1 for r in records if r.get("kind") == "heard"),
        "corrections": len(corrections()),
        "pronunciations": len(pronunciations()),
        "store": str(_STORE),
    }


def forget(kind: str, key: str) -> str:
    """Remove one learned rule. `kind` is 'correction' or 'pronunciation'."""
    field = "heard" if kind == "correction" else "word"
    records = _read()
    kept = [r for r in records
            if not (r.get("kind") == kind and r.get(field) == key)]
    removed = len(records) - len(kept)
    if not removed:
        return f"'{key}' မတွေ့ပါ။"
    _rewrite(kept)
    return f"ဖျက်ပြီ — '{key}' ({removed} ခု)။"
