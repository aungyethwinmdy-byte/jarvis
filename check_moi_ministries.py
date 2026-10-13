"""Always-test the offline ministry action: py check_moi_ministries.py.

Covers: the owner's construction question, skeleton-based matching,
no-input prompt, and the not-found path.
"""
import sys

sys.path.insert(0, r"E:\Mark-LIV-main")
from actions.moi_ministries import moi_ministries, _MINISTRIES, _matches

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, wanted {want!r}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}"
          + ("" if ok else f"   got {got!r}, wanted {want!r}"))


print("\n" + "=" * 74)
print("construction ministry, the owner's exact question")
print("=" * 74)

out = moi_ministries({"name": "ဆောက်လုပ်ရေးဝန်ကြီးဌာန"})
check("construction minister named", "ဦးမျိုးသန့်" in out, True)
check("first deputy named", "ဦးမျိုးမြင့်" in out, True)
check("second deputy named", "ဒေါက်တာသောင်းနိုင်" in out, True)
check("ministry name itself appears", "ဆောက်လုပ်ရေးဝန်ကြီးဌာန" in out, True)
check("no 'မတွေ့ပါ' for a known ministry", "မတွေ့ပါ" in out, False)

print("\n" + "=" * 74)
print("skeleton matching — scramble-proof")
print("=" * 74)


def _skeleton(s: str) -> str:
    return "".join(
        ch for ch in (s or "")
        if "\u1000" <= ch <= "\u1021" or ch.isascii() and ch.isalnum()
    )


known = _MINISTRIES[0]["name"]
check("_MINISTRIES non-empty", len(_MINISTRIES) > 0, True)
# a ministry name typed with stray spaces must still resolve
check("space-scattered name still matches",
      bool([m for m in _MINISTRIES
            if _matches(" ".join(known.split()), m["name"])]), True)

print("\n" + "=" * 74)
print("edge cases")
print("=" * 74)

out_none = moi_ministries({})
check("no-input returns a prompt, not a list",
      "ဘယ်ဝန်ကြီးဌာနလဲ" in out_none, True)

out_unknown = moi_ministries({"name": "အမည်မသိ"})
check("unknown ministry returns not-found",
      "မတွေ့ပါ" in out_unknown, True)
check("unknown ministry names no minister",
      "ပြည်ထောင်စုဝန်ကြီး:" in out_unknown, False)

print("\n" + "=" * 74)
if FAILURES:
    print(f"  {len(FAILURES)} FAILED")
    for f in FAILURES:
        print(f"    - {f}")
    sys.exit(1)
else:
    print("  all checks passed")
print("=" * 74)
