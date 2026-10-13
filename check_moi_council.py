"""Always-test the offline NDSC roster action: py check_moi_council.py.

Covers: member-name → position, position → members, full-roster query,
no-input prompt, not-found path, and action discovery registration.
"""
import sys

sys.path.insert(0, r"E:\Mark-LIV-main")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # console may default to cp1252
except Exception:
    pass
from actions.moi_council import moi_council, _COUNCIL, _matches, TOOL

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, wanted {want!r}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}"
          + ("" if ok else f"   got {got!r}, wanted {want!r}"))


print("\n" + "=" * 74)
print("member name → position (owner's pasted list, 74156)")
print("=" * 74)

out = moi_council({"name": "ဦးမင်းအောင်လှိုင်"})
check("president's position exact", "နိုင်ငံတော်သမ္မတ" in out, True)
check("president answer is exact-match line",
      "ဦးမင်းအောင်လှိုင် သည်" in out, True)

out = moi_council({"name": "ဗိုလ်ချုပ်ကြီး ထွန်းအောင်"})
check("defence minister named", "ကာကွယ်ရေးဝန်ကြီးဌာန" in out, True)
check("defence minister full title", "ပြည်ထောင်စုဝန်ကြီး" in out, True)

# space-scattered typing must still resolve (skeleton matching)
out = moi_council({"name": "ဒုတိယ ဗိုလ်ချုပ်ကြီး ဖုန်းမြတ်"})
check("border affairs minister, spaced title", "နယ်စပ်ရေးရာဝန်ကြီးဌာန" in out, True)

print("\n" + "=" * 74)
print("position → member(s)")
print("=" * 74)

out = moi_council({"name": "ဒုတိယသမ္မတ"})
check("first deputy president named", "ဦးညိုစော" in out, True)
check("second deputy president named", "ဒေါ်နန်းနွဲ့နွဲ့အေး" in out, True)

out = moi_council({"name": "တပ်မတော်ကာကွယ်ရေးဦးစီးချုပ်"})
check("commander-in-chief named", "ရဲဝင်းဦး" in out, True)

print("\n" + "=" * 74)
print("whole council → full roster")
print("=" * 74)

out = moi_council({"name": "အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ အဖွဲ့ဝင် စာရင်း"})
check("council title shown", "အမျိုးသားကာကွယ်ရေးနှင့် လုံခြုံရေးကောင်စီ" in out, True)
check("source URL noted", "74156" in out, True)
for name, _pos in _COUNCIL:
    check(f"roster contains {name}", name in out, True)
check("roster numbering ၁။ starts", "၁။" in out, True)
check("roster numbering ၁၁။ ends", "၁၁။" in out, True)

print("\n" + "=" * 74)
print("edge cases")
print("=" * 74)

out_none = moi_council({})
check("no-input returns a prompt", "ဘယ်သူရဲ့ ရာထူးလဲ" in out_none, True)

out_unknown = moi_council({"name": "အမည်မသိလူ"})
check("unknown person returns not-found", "မတွေ့ပါ" in out_unknown, True)

print("\n" + "=" * 74)
print("action registration")
print("=" * 74)

check("TOOL name unique", TOOL["name"], "moi_council")
check("TOOL has handler", callable(TOOL.get("handler")), True)
check("data has 11 members", len(_COUNCIL), 11)

try:
    from pathlib import Path
    from core.action_loader import discover_actions
    reg = discover_actions(Path(r"E:\Mark-LIV-main\actions"), logger=lambda *_: None)
    check("discovered by action_loader", reg.has("moi_council"), True)
except Exception as exc:  # noqa: BLE001
    check(f"discovery raised {exc}", False, True)

print("\n" + "=" * 74)
if FAILURES:
    print(f"  {len(FAILURES)} FAILED")
    for f in FAILURES:
        print(f"    - {f}")
    sys.exit(1)
else:
    print("  all checks passed")
print("=" * 74)
