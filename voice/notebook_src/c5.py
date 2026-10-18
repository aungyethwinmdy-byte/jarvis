# Cell 5: အခြေအနေ စစ်ရန် — ဘယ်အချိန်မဆို ပြန် run လို့ရပါတယ်
import os

print("--- server log (နောက်ဆုံး ၃၀ လိုင်း) ---")
if os.path.exists("/content/server.log"):
    lines = open("/content/server.log", encoding="utf-8", errors="replace").readlines()
    for l in lines[-30:]:
        print(l, end="")
    if not lines:
        print("(လောလောဆယ် ဘာမှ မရှိသေးပါ)")
else:
    print("(log file မရှိသေးပါ — cell 4 ကို အရင် run ပါ)")

print()
print("--- reference အခြေအနေ ---")
wav = os.path.exists("/content/ref_aye_thant.wav")
print("ref audio :", "✅ ရှိပါတယ်" if wav else "❌ မရှိသေးပါ (JARVIS က တင်ပေးပါမယ်)")
if os.path.exists("/content/ref_text.txt"):
    print("ref text  :", open("/content/ref_text.txt", encoding="utf-8").read().strip())
else:
    print("ref text  : ❌ မရှိသေးပါ (JARVIS က တင်ပေးပါမယ်)")
