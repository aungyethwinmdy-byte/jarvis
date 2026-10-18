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


def show_gpu():
    """Which device the model speaks on: seconds a line, or minutes a line.

    Measured 2026-10-18: on CPU this model took 741.7 seconds to say 24
    characters, against a Cloudflare tunnel that cuts a request at about a
    hundred — so on CPU nothing comes back through it at all.
    """
    try:
        import torch
        if torch.cuda.is_available():
            print(f"GPU             : ✅ {torch.cuda.get_device_name(0)}")
        else:
            print("GPU             : ❌ မရှိပါ — CPU နဲ့ run နေပါတယ်!")
            print("                  → Runtime → Change runtime type → T4 GPU လုပ်ပြီး")
            print("                    Run all ပြန်လုပ်ပါ (CPU ဆိုရင် တစ်ကြောင်း ၁၂ မိနစ်အထိ ကြာတယ်)")
    except Exception as e:  # noqa: BLE001
        print(f"GPU             : ? စစ်လို့ မရပါ ({type(e).__name__})")


show_gpu()
show_state()
