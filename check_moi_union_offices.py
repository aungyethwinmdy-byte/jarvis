"""Always-test the offline union-offices action: py check_moi_union_offices.py.

Covers: org → chair/deputies, person → org/position, full-list query,
no-input prompt, not-found path, and action discovery registration.
"""
import sys

sys.path.insert(0, r"E:\Mark-LIV-main")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # console may default to cp1252
except Exception:
    pass
from actions.moi_union_offices import moi_union_offices, _OFFICES, TOOL

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, wanted {want!r}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}"
          + ("" if ok else f"   got {got!r}, wanted {want!r}"))


print("\n" + "=" * 74)
print("organization → chair and deputies")
print("=" * 74)

out = moi_union_offices({"name": "ပြည်သူ့လွှတ်တော်"})
check("Pyithu Hluttaw chair", "ဦးခင်ရီ" in out, True)
check("Pyithu Hluttaw deputy", "ဦးမောင်မောင်အုန်း" in out, True)
check("Pyithu Hluttaw label", "ဥက္ကဋ္ဌ" in out, True)

out = moi_union_offices({"name": "မြန်မာနိုင်ငံတော်ဗဟိုဘဏ်"})
check("central bank chair", "ဒေါ်သန်းသန်းဆွေ" in out, True)
check("central bank deputy 1", "ဦးဇော်မြင့်နိုင်" in out, True)
check("central bank deputy 2", "ဦးသက်ထွန်းအောင်" in out, True)
check("central bank deputy 3", "ဒေါက်တာနွယ်နွယ်" in out, True)

out = moi_union_offices({"name": "ပြည်ထောင်စုတရားလွှတ်တော်ချုပ်ရုံး"})
check("chief justice named", "ဦးသာဌေး" in out, True)
check("supreme court has no deputy listed", "ဒုတိယဥက္ကဋ္ဌ:" in out, False)

print("\n" + "=" * 74)
print("person → organization and position")
print("=" * 74)

out = moi_union_offices({"name": "ဦးခင်ရီ"})
check("Khin Gyi is Pyithu Hluttaw chair",
      "ပြည်သူ့လွှတ်တော်" in out and "ဥက္ကဋ္ဌ" in out, True)

out = moi_union_offices({"name": "ဒေါက်တာသီတာဦး"})
check("Dr Thida Oo leads Attorney-General office",
      "ပြည်ထောင်စုရှေ့နေချုပ်" in out, True)

out = moi_union_offices({"name": "ဦးသန်းလင်းအုန်း"})
check("Than Lin Oon chairs NHRC",
      "မြန်မာနိုင်ငံ အမျိုးသားလူ့အခွင့်အရေး ကော်မရှင်ရုံး" in out
      and "ဥက္ကဋ္ဌ" in out, True)

print("\n" + "=" * 74)
print("whole list → full roster")
print("=" * 74)

out = moi_union_offices({"name": "ပြည်ထောင်စုအဆင့် ရုံး၊ အဖွဲ့အစည်းများ စာရင်း"})
check("list title shown", "ပြည်ထောင်စုအဆင့် ရုံး၊ အဖွဲ့အစည်းများ" in out, True)
check("source URL noted", "13696" in out, True)
for org, chair, deputies in _OFFICES:
    check(f"list contains {org}", org in out, True)
    check(f"list contains chair {chair}", chair in out, True)
    for d in deputies:
        check(f"list contains deputy {d}", d in out, True)
check("Burmese numbering starts ၁။", "၁။" in out, True)
check("Burmese numbering ends ၁၂။", "၁၂။" in out, True)

print("\n" + "=" * 74)
print("edge cases")
print("=" * 74)

out_none = moi_union_offices({})
check("no-input returns a prompt", "ဘယ်ရုံး/အဖွဲ့အစည်းလဲ" in out_none, True)

out_unknown = moi_union_offices({"name": "အမည်မသိအဖွဲ့"})
check("unknown org returns not-found", "မတွေ့ပါ" in out_unknown, True)

print("\n" + "=" * 74)
print("action registration")
print("=" * 74)

check("TOOL name unique", TOOL["name"], "moi_union_offices")
check("TOOL has handler", callable(TOOL.get("handler")), True)
check("data has 12 organizations", len(_OFFICES), 12)

try:
    from pathlib import Path
    from core.action_loader import discover_actions
    reg = discover_actions(Path(r"E:\Mark-LIV-main\actions"), logger=lambda *_: None)
    check("discovered by action_loader", reg.has("moi_union_offices"), True)
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
