"""Isolated checks for the topic extractor in actions/reporter_news.py.

Why this file exists: `_extract_topic` decides whether a `query` is a topic to
search for or a question to be answered as-is, and getting it wrong fails
**silently in both directions** —

    too eager   → a real topic inside a sentence is ignored and the general
                  official list is returned (the bug the narrowing exists for)
    too lax     → the whole sentence is used as a substring, matches nothing,
                  and the question is answered "no story contains that"

Both were measured on 2026-09-30, on the owner's own questions, one after the
other. The logic is pure text, so it belongs in a fast offline check rather
than in `check_agent.py`, whose live sections take minutes.

Run: python check_topic.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "actions"))

import reporter_news as rn  # noqa: E402

_fails = []
_passes = 0


def ok(label: str, got, want) -> None:
    global _passes
    if got == want:
        _passes += 1
        print(f"  OK    {label}")
    else:
        _fails.append(label)
        print(f"  FAIL  {label}  got {got!r} want {want!r}")


print("\n── A bare topic is a topic ──")
# The simplest case, and the one the narrowing was added for: a keyword, no
# question around it. Nothing may be stripped from it.
for word in ("မုန်တိုင်း", "ပညာရေး", "ရွှေဈေး", "ကယ်ဆယ်ရေး", "ရေကြီးရေလျှံ"):
    ok(f"a bare topic survives: {word}", rn._extract_topic(word), word)

print("\n── The owner's own question names no topic ──")
# Measured 2026-09-30. Every word here is grammar, a paper name, an office, or
# the word "news". The right answer is "" — and that is what lets the office
# branch below answer it as the office question it is.
_Q_OFFICE = "ဒီနေ့ကြေးမုံသတင်းစာမှာ ပြည်ထောင်စုဝန်ကြီး ဘယ်သူတွေရဲ့ သတင်းတွေပါလဲ"
ok("an office question yields no topic", rn._extract_topic(_Q_OFFICE), "")
_Q_TWO_OFFICES = ("ဒီနေ့ မြန်မာ့အလင်းသတင်းစာမှာ နိုင်ငံတော်သမ္မတ၊ "
                  "ဒုတိယသမ္မတ (၂) ဦးတို့ရဲ့ သတင်းတွေ ရှိလား")
ok("a two-office question yields no topic",
   rn._extract_topic(_Q_TWO_OFFICES), "")

print("\n── A real topic inside a sentence is dug out ──")
# The other failure direction: this question is sentence-shaped, but it carries
# a genuine topic. Skipping the narrowing because of the shape returns the
# general list — the exact bug measured before.
_Q_ASTRONAUT = "ဒီနေ့ သတင်းစာထဲ အာကာသယာဉ်မှူး ပါသလဲ"
ok("a topic inside a sentence is extracted",
   rn._extract_topic(_Q_ASTRONAUT), "အာကာသယာဉ်မှူး")
ok("…with the paper named and no space",
   rn._extract_topic("ဒီနေ့ ကြေးမုံသတင်းစာထဲ မုန်တိုင်း ပါသလဲ"), "မုန်တိုင်း")
ok("…and with the paper named and a space",
   rn._extract_topic("ဒီနေ့ ကြေးမုံ သတင်းစာထဲ မုန်တိုင်း ပါသလဲ"), "မုန်တိုင်း")

print("\n── The parameter must never be the whole sentence ──")
# The single property that matters most: whatever comes back must be short
# enough to be a real word and must not be the question itself.
for q in (_Q_OFFICE, _Q_TWO_OFFICES, _Q_ASTRONAUT,
          "ဒီနေ့ သတင်းစာထဲ အာကာသယာဉ်မှူး ပါသလား"):
    got = rn._extract_topic(q)
    ok(f"never the whole question: …{q[-8:]}", got != q and len(got) <= 24, True)

print("\n── Empty and whitespace input ──")
for blank in ("", "   ", None):
    ok(f"blank input yields no topic: {blank!r}", rn._extract_topic(blank or ""), "")

print(f"\n{'=' * 60}")
print(f"  {_passes} passed, {len(_fails)} failed")
if _fails:
    for f in _fails:
        print(f"    - {f}")
print(f"{'=' * 60}\n")
sys.exit(1 if _fails else 0)
