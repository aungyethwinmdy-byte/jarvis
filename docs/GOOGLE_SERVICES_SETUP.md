# Google Services (Gmail, Drive, Calendar, Tasks) Setup Guide for JARVIS

JARVIS ကို Google Services များနှင့် ချိတ်ဆက်ပြီး အောက်ပါစွမ်းဆောင်ရည်များကို အသုံးပြုနိုင်ပါပြီ-
1. **Gmail:** မဖတ်ရသေးသော အီးမေးလ်များ စစ်ဆေးခြင်း (`"ဂျာဗစ် မေးလ်အသစ်ဝင်လား"` / `"အီးမေးလ် စစ်ပေးပါ"`), အီးမေးလ် အပြည့်အစုံ ဖတ်ပြခြင်း, ရှာဖွေခြင်း, အီးမေးလ် ပို့ခြင်း။
2. **Google Drive:** Drive ထဲရှိ ဖိုင်များ ကြည့်ရှုခြင်း, ရှာဖွေခြင်း။
3. **Google Calendar:** လာမည့် အစီအစဉ်များ စစ်ဆေးခြင်း, အစီအစဉ်သစ် ထည့်သွင်းခြင်း။
4. **Google Tasks:** အလုပ်မှတ်စု (Tasks/To-do) များ ကြည့်ရှုခြင်းနှင့် အသစ်မှတ်သားခြင်း။

---

## ချိတ်ဆက်ရန် အဆင့် ၆ ဆင့် (One-time Setup)

Google Services များကို လုံခြုံစွာ သုံးစွဲနိုင်ရန်အတွက် Google Cloud Console တွင် OAuth 2.0 Client တစ်ခု ဖန်တီးပေးရန် လိုအပ်ပါသည်-

### အဆင့် ၁: Google Cloud Console သို့ သွားပါ
- Browser မှ [Google Cloud Console](https://console.cloud.google.com/) သို့ ဝင်ပါ။
- မိမိ Google Account ဖြင့် Sign in လုပ်ပါ။

### အဆင့် ၂: Project အသစ်တစ်ခု ပြုလုပ်ပါ
- ထိပ်ဘက် Project Dropdown မှ **"New Project"** ကို နှိပ်ပါ။
- Project Name တွင် `Jarvis-Assistant` ဟု ပေးပြီး **Create** လုပ်ပါ။

### အဆင့် ၃: လိုအပ်သော Google APIs များကို Enable လုပ်ပါ
- ဘယ်ဘက် Menu မှ **APIs & Services** > **Library** သို့ သွားပါ။
- အောက်ပါ API (၄) ခုကို တစ်ခုချင်း ရှာဖွေပြီး **Enable** နှိပ်ပေးပါ:
  1. `Gmail API`
  2. `Google Drive API`
  3. `Google Calendar API`
  4. `Google Tasks API`

### အဆင့် ၄: OAuth Consent Screen ပြင်ဆင်ပါ
- **APIs & Services** > **OAuth consent screen** သို့ သွားပါ။
- **User Type:** `External` ကို ရွေးပြီး **Create** နှိပ်ပါ။
- **App name:** `Jarvis` ဟု ပေးပါ။
- **User support email** နှင့် **Developer contact email** တွင် မိမိ Gmail ထည့်ပြီး **Save and Continue** နှိပ်ပါ။
- **Scopes** အဆင့်တွင် မည်သည့်အရာမျှ မရွေးဘဲ **Save and Continue** နှိပ်ပါ။
- **Test users** အဆင့်တွင် **"+ ADD USERS"** နှိပ်၍ မိမိ Gmail အကောင့်ကို ထည့်သွင်းပြီး Save လုပ်ပါ။

### အဆင့် ၅: Credentials (OAuth Client ID) ဒေါင်းလုဒ်ရယူပါ
- **APIs & Services** > **Credentials** သို့ သွားပါ။
- ထိပ်ဘက်မှ **"+ CREATE CREDENTIALS"** > **"OAuth client ID"** ကို ရွေးပါ။
- **Application type:** `Desktop app` ကို ရွေးချယ်ပါ။
- **Name:** `Jarvis Desktop Client` ဟု ပေးပြီး **Create** နှိပ်ပါ။
- Pop-up ပေါ်လာပါက **"DOWNLOAD JSON"** ခလုတ်ကို နှိပ်၍ ဒေါင်းလုဒ်ဆွဲပါ။

### အဆင့် ၆: ဖိုင်ကို ပရောဂျက်ထဲ ထည့်သွင်းခြင်း
- ဒေါင်းလုဒ်ဆွဲထားသော JSON ဖိုင်အမည်အား `credentials.json` ဟု အမည်ပြောင်းပါ။
- ၎င်းဖိုင်ကို ပရောဂျက်၏ `config/credentials.json` လမ်းကြောင်းထဲသို့ ကူးထည့်ပေးပါ။

---

## စမ်းသပ်ခြင်းနှင့် ပထမဆုံးအကြိမ် Login ဝင်ခြင်း

ဖိုင်ထည့်ပြီးပါက Terminal တွင် အောက်ပါ command ကို run နိုင်ပါသည်:

```bash
python check_google.py
```

သို့မဟုတ် JARVIS အား တိုက်ရိုက် **"မေးလ်အသစ် ဝင်လား စစ်ပေးပါ"** ဟု ပြောလိုက်ပါက Browser တဘ်တစ်ခု ပွင့်လာပြီး မိမိ Google အကောင့်ကို Sign-in လုပ်ကာ ခွင့်ပြုချက် (Allow) ပေးလိုက်ရုံဖြင့် အလိုအလျောက် အမြဲတမ်း ချိတ်ဆက်သွားမည် ဖြစ်ပါသည်။
