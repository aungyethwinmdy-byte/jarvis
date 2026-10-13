# memory/memory_manager.py
import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 380

MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
PROMPT_MAX_PER_CATEGORY = 6

# Who put a fact there. `user` = the user stated it; `model` = the assistant
# decided it was worth remembering. See _recursive_update for why it exists.
MEMORY_SOURCES = ("user", "model")
DEFAULT_SOURCE = "model"

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
        # Not facts about the user — facts about the assistant's own behaviour.
        # "I did this and it was wrong; do not do it again." Kept in the same
        # file and given the same provenance as everything else, because it is
        # re-injected into the prompt the same way and needs the same labelling.
        "lessons":       {},
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


_trim_notifier = None


def set_trim_notifier(fn) -> None:
    global _trim_notifier
    _trim_notifier = fn


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: မှတ်ဉာဏ် ပြည့်သွားပါသဖြင့် အဟောင်းဆုံး အချက်အလက် {len(dropped)} ခုကို ရှင်းထုတ်လိုက်ပါသည်။"
            )
        except Exception:
            pass
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict, source: str = "model") -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value, source):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            # `source` records HOW the fact was learned, and it is the only
            # defence against the assistant's own guess becoming a permanent
            # "fact". Everything here is re-injected into the system prompt on
            # every launch (format_memory_for_prompt), so an entry the model
            # invented is indistinguishable from something the user actually
            # said — unless it is labelled. Audit finding, 2026-09-28: all five
            # entries on disk had no provenance at all, and the only live writer
            # is the `save_memory` tool, which the model calls on its own.
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d"),
                        "source": source if source in MEMORY_SOURCES else "model"}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
            elif existing.get("source") != entry["source"]:
                # Same value, better provenance: a fact the user has now stated
                # themselves stops being merely the assistant's note.
                existing["source"] = entry["source"]
                changed = True
    return changed


def update_memory(memory_update: dict, source: str = "model") -> dict:
    """Write facts into long-term memory.

    `source` is `"model"` when the assistant decided to record something and
    `"user"` when the user stated it. It is not bookkeeping: the prompt tells the
    model which of its own memories it inferred, so it does not go on to treat a
    guess as something the user said.
    """
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update, source):
        save_memory(memory)
        print(f"[Memory] 💾 Saved ({source}): {list(memory_update.keys())}")
    return memory

def _entry_value(entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


# Shown beside a fact the assistant recorded on its own initiative. Everything
# in this file is re-injected into the system prompt on every launch, so without
# the marker the model cannot tell its own guess from something the user said —
# and it will repeat the guess back as their fact, confidently. Entries written
# before provenance existed carry no `source` and are not marked; the next time
# the user states one, update_memory re-labels it.
_SOURCE_MARK = "[assistant-recorded]"


def _source_mark(entry) -> str:
    if isinstance(entry, dict) and entry.get("source") == "model":
        return f" {_SOURCE_MARK}"
    return ""


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
    "lessons":       "Lessons — mistakes you made, so you do not repeat them",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def format_memory_for_prompt(memory: dict | None, known_name: str = "") -> str:
    """Render the memory block for the system prompt.

    `known_name` is the user's name as set in the settings. When it is given and
    the memory agrees, the `Name:` line is left out: the settings are the
    explicit answer to "what is this person called", and the identity block
    already states it, so repeating it here was the same fact in two places.
    When memory *disagrees*, the line is kept — a conflict the model can see is
    better than one it cannot.
    """
    if not memory:
        return ""

    core_lines: list[str] = []
    _known = (known_name or "").strip()

    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        val = _entry_value(identity.get(field))
        if not val:
            continue
        if field == "name" and _known and val.strip() == _known:
            continue
        if field == "language":
            core_lines.append(f"Preferred Language: Burmese (အသုံးပြုသူသည် မြန်မာဘာသာကိုသာ သုံးစွဲသည် — မဖြစ်မနေ မြန်မာလိုသာ ပြန်လည်ဖြေကြားပါ)")
        else:
            core_lines.append(f"{field.title()}: {val}{_source_mark(identity.get(field))}")
    for key, entry in identity.items():
        if key in _IDENTITY_FIELDS:
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}{_source_mark(entry)}")

    rest: list[tuple[str, str, str, str]] = []
    for cat in _CATEGORY_LABELS:
        for key, entry in (memory.get(cat, {}) or {}).items():
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        line = f"  - {_pretty(key).title()}: {val}{_source_mark(entry)}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    indexed: list[str] = []
    if overflow:
        cats  = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]
    if any(_SOURCE_MARK in line for line in core_lines):
        out.insert(
            1,
            f"Entries marked {_SOURCE_MARK} were recorded by YOU, not stated by the "
            f"user. Treat them as your own notes: never present one as something "
            f"they told you, and correct it the moment they say otherwise."
        )

    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    return "\n".join(out) + "\n"


def _score(query_words: list[str], cat: str, key: str, value: str) -> int:
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score   = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        if w in cat:
            score += 1
    return score


def search_memory(query: str, limit: int = 8) -> str:
    memory = load_memory()
    words  = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]

    rows: list[tuple[int, str, str, str]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            s = _score(words, cat, key, val) if words else 1
            if s > 0:
                rows.append((s, cat, key, val))

    if not rows:
        return (f"'{query}' နှင့် ပတ်သက်၍ မှတ်ဉာဏ်ထဲတွင် မတွေ့ရှိပါ။" if query
                else "အသုံးပြုသူနှင့် ပတ်သက်သည့် အချက်အလက် မသိမ်းဆည်းရသေးပါ။")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = [f"{cat}/{_pretty(key)}: {val}" for _s, cat, key, val in rows[:max(1, limit)]]
    head  = (f"'{query}' နှင့် ကိုက်ညီသော မှတ်သားချက်များ:" if query
             else "မှတ်ဉာဏ်ထဲရှိ အချက်အလက်များ:")
    more  = (f"\n(+{len(rows) - len(lines)} ခု ကျန်ပါသေးသည်)"
             if len(rows) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def all_entries_for_ui() -> list[dict]:
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    val,
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

def remember(key: str, value: str, category: str = "notes") -> str:
    # Derived from the same table the prompt uses, so a category that renders
    # cannot drift away from the one that is writable — `interest` was writable
    # here for a while and is in no label table, which is how a fact ends up on
    # disk and never in front of the model.
    valid = set(_CATEGORY_LABELS) | {"identity"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}}, source="user")
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


_SESSION_MAX = 3


def save_session_summary(summary: str, language: str = "Burmese") -> None:
    summary = (summary or "").strip()
    if not summary:
        return
    memory   = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
        "language": language or "Burmese",
    }
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory   = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()
            memory["sessions"] = sessions
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None