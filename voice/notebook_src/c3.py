# Cell 3: Config — အခြေအနေ ကြည့်ရန် (ပြင်စရာ မလိုပါ)
import os

# ဒေါ်အေးသန့် reference အသံ + အဲဒီအသံ ဖတ်ထားတဲ့ စာသား
# နှစ်ခုလုံးကို JARVIS ကိုယ်တိုင် တင်ပေးပါတယ် (runtime အသစ်တိုင်း အလိုအလျောက်)
REF_WAV_PATH  = "/content/ref_aye_thant.wav"
REF_TEXT_FILE = "/content/ref_text.txt"

# server log ကို tunnel ကနေ ဖတ်ခွင့်ပြုမလား (GET /log) — ပြဿနာရှာရလွယ်အောင်
# မလိုချင်ရင် False လုပ်ပါ
EXPOSE_LOG = True


def show_state():
    ok = os.path.exists(REF_WAV_PATH)
    txt = ""
    if os.path.exists(REF_TEXT_FILE):
        txt = open(REF_TEXT_FILE, encoding="utf-8").read().strip()
    print(f"reference audio : {REF_WAV_PATH} — {'ရှိပါတယ်' if ok else 'မရှိသေးပါ (JARVIS က တင်ပေးပါမယ်)'}")
    print(f"reference text  : {txt or 'မရှိသေးပါ (JARVIS က တင်ပေးပါမယ်)'}")
    if not ok:
        print("                  → မရှိသေးရင် model ရဲ့ ကိုယ်ပိုင် အသံနဲ့ မြန်မာလို ဖတ်ပါမယ်")


show_state()
