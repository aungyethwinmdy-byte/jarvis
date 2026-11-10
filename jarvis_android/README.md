# Android JARVIS (Voice Assistant)

Android ဖုန်းပေါ်တွင် တိုက်ရိုက်အသုံးပြုနိုင်သော **JARVIS Mobile Voice Assistant** ဖြစ်ပါသည်။ PC server သို့မဟုတ် background server မလိုဘဲ၊ ဖုန်းမှ **Google Gemini Live API (WebSocket)** သို့ တိုက်ရိုက်ချိတ်ဆက်၍ အသံဖြင့် အပြန်အလှန် စကားပြောဆိုနိုင်ပါသည်။ **Tasker မသုံးပါ** — ထိန်းချုပ်မှုအားလုံး ဒီအက်ပ်ထဲမှာပဲ ရှိသည်။

> [!IMPORTANT]
> **ဖုန်းပေါ်တွင် လက်တွေ့စမ်းသပ်အတည်ပြုခြင်း စည်းမျဉ်း (Verification Rule):**
> ဤမှတ်တမ်းပါ feature တစ်ခုကို "ပြီးစီးပြီ" ဟု မှတ်ယူရန် agent ၏ အစီရင်ခံစာ သို့မဟုတ် unit test အောင်ရုံဖြင့် မလုံလောက်ပါ။ စက်အစစ် (ဖုန်း) ပေါ်တွင် အသံဖြင့် တိုက်ရိုက် စမ်းသပ်စစ်ဆေးပြီး အောင်မြင်မှသာ အပြီးသတ် ပြီးစီးသည်ဟု သတ်မှတ်ရပါမည်။

---

## လက်ရှိအခြေအနေ (2026-11-02 အထိ)

- **MVP (သက်သေပြ၊ အောင်ပြီး):** Push-to-talk၊ မြန်မာလို greeting (ရက်စွဲ/အချိန်ပါ၊ ရာသီဥတုမပါ)၊ get_weather၊ web_search၊ set_reminder (notification တကယ်ထွက်သည်)၊ မြန်မာလို error handling။
- **Wake word + Hands-free (ကုဒ်ရှိ၊ ဖုန်းစစ်ဆဲ):** "Hey Jarvis" ကို စက်ထဲမှာပဲ ရှာသည် (openWakeWord, hey_jarvis.onnx)၊ wake မတိုင်ခင် အသံကို Gemini/အင်တာနက်ဆီ မပို့ပါ။ Foreground service၊ Settings မှာ ON/OFF ခလုတ်၊ 30 စက္ကန့် တိတ်ဆိတ်ရင် wake mode ပြန်သွားသည်။ Wake ပြီးနောက် "ဟုတ်ကဲ့ ဆရာ။" ဟု ဖြေသည်။
- **Barge-in + ဒုတိယအလှည့် (ပြင်ဆဲ၊ ဖုန်းပေါ်တွင် စမ်းသပ်ဆဲ):** စကားပြောနေတုန်း ဖြတ်ပြောလို့ရအောင် ပြင်ထားသော်လည်း၊ အသုံးပြုသူ လက်တွေ့စစ်ချက်အရ ပထမအကြိမ်ပြီးရင် ဆက်မရသေးပါ။ စက်အစစ်ပေါ်တွင် အောင်မြင်မှသာ အပြီးသတ် မှတ်ယူရမည်။
- **Per-app tool များ (ကုဒ်ရှိ၊ အသံနဲ့ စစ်ဆဲ — ၃ ခု ပျက်နေသည်):**
  2026-11-02 အသုံးပြုသူ စစ်ချက်အရ အောက်ပါ ၃ ခု ပျက်နေသဖြင့် ပြင်ဆင်ထားပြီး ဖြစ်သည် (ဖုန်းပေါ်တွင် အသံဖြင့် စစ်ဆေးဆဲ):
  1. **ကင်မရာ (`take_photo`)** — တခြား app ခလုတ်ကို Accessibility ဖြင့် နှိပ်ခြင်း မဟုတ်ဘဲ Jarvis ကိုယ်ပိုင် CameraX (`CameraActivity`) ဖြင့် တိုက်ရိုက် preview ပြ၊ ဓာတ်ပုံရိုက်ပြီး Gallery (DCIM/Camera) ထဲသို့ သိမ်းဆည်းရန် ပြင်ဆင်ထားသည်။
  2. **Facebook / စာအသစ်စစ်ဆေးခြင်း (`check_messages`)** — Screen စာဖတ်သည့် `inspect_screen` နှင့် မရောဘဲ Notification Listener (`JarvisNotificationListener`) မှ ရရှိသော notification (ပို့သူ + အမျိုးအစား) ကိုသာ တိကျစွာ ပြောကြားရန် ပြင်ဆင်ထားသည်။
  3. **အသံဖမ်း (`record_audio`)** — Live ၏ mic stream ကို ခေတ္တရပ်ပြီးမှ Jarvis ကိုယ်ပိုင် MediaRecorder (44.1kHz AAC, .m4a) ဖြင့် အသံဖမ်းစတင်ရန်နှင့်၊ ရပ်ပြီးမှ Live mic stream ပြန်လည်ဖွင့်ပေးရန် ပြင်ဆင်ထားသည်။

---

## အဓိက အင်္ဂါရပ်များ (Core Features)

1. **Push-to-Talk Voice Chat:**
   - မိုက်ခလုတ်ကို ဖိထားပြီး မြန်မာလို စကားပြောဆိုနိုင်ခြင်း။
   - Input Audio: `16,000 Hz, 16-bit mono PCM` stream။
   - Output Audio: `24,000 Hz, 16-bit mono PCM` playback။
2. **Wake word + Hands-free:**
   - "Hey Jarvis" (on-device openWakeWord)၊ အမြဲနားထောင်ခြင်း၊ Foreground service၊ Settings ON/OFF၊ 30s တိတ်ဆိတ်ရင် wake mode ပြန်သွားခြင်း။
3. **Barge-in:** စကားပြောနေတုန်း ဖြတ်ပြောလို့ရခြင်း (ပြင်ဆဲ)။
4. **Burmese-First Persona:**
   - အသုံးပြုသူကို "**ဆရာ**" ဟု အမြဲယဉ်ကျေးစွာ ခေါ်ဆိုခြင်း။
   - စကားပြောရာတွင် "ကျွန်တော်"၊ "ခင်ဗျာ/ဗျာ" သုံးစွဲပြီး မြန်မာဘာသာဖြင့်သာ တိုတိုနှင့် လိုရင်းကို ဖြေကြားခြင်း။
   - PC Jarvis (`main.py`) ၏ မူရင်း greeting အတိုင်း ချိတ်ဆက်သည်နှင့် နှုတ်ဆက်စကား စတင်ပြောကြားခြင်း (ရက်စွဲ/အချိန်ပါ၊ ရာသီဥတုမပါ)။
5. **Native Mobile Tools (၁၄ ခု):**
   - ☀️ `get_weather(location)`: Open-Meteo free API (API key မလို)။
   - 🔍 `web_search(query)`: DuckDuckGo / Wikipedia ရှာဖွေမှု။
   - 🔔 `set_reminder(title, in_minutes)`: Native exact alarm / local notifications သတိပေးချက်။
   - 🔦 `toggle_torch(enable)`: ဓာတ်မီး အဖွင့်/အပိတ်။
   - 🔊 `set_volume(percent, stream)`: အသံအတိုးအကျယ် (media, ring, alarm, notification, call) သတ်မှတ်ခြင်း။
   - 📱 `open_app(query)`: ဖုန်းထဲရှိ App များကို ရှာဖွေဖွင့်လှစ်ခြင်း။
   - 🔋 `get_device_status()`: ဘက်ထရီရာခိုင်နှုန်း၊ အားသွင်းမှုအခြေအနေ၊ အပူချိန်၊ အသံပမာဏနှင့် စက်အခြေအနေ စစ်ဆေးခြင်း။
   - ▶️ `play_youtube(query)`: YouTube တွင် သီချင်း/ဗီဒီယို တိုက်ရိုက်ရှာဖွေဖွင့်ခြင်း။
   - 📷 `take_photo()`: Jarvis ကိုယ်ပိုင် CameraX Viewfinder ဖြင့် ဓာတ်ပုံရိုက်ပြီး Gallery (DCIM/Camera) ထဲ သိမ်းဆည်းခြင်း။
   - 📣 `check_messages(app)`: Telegram, Viber, Facebook, Messenger စသည့် app များမှ notification အကျဉ်းများကို NotificationListenerService ဖြင့် စစ်ဆေးဖတ်ပြခြင်း (screen စာဖတ်ခြင်းနှင့် မရောပါ)။
   - ✉️ `send_app_message(app, recipient, message, auto_send)`: Telegram, Viber, Facebook စသည့် app များထဲသို့ ကိုယ်တိုင်ဝင်ရောက်၍ ရှာဖွေရေးခလုတ်နှိပ်၊ လက်ခံသူရှာ၊ စာသားရိုက်ထည့်ပြီး Send ခလုတ်နှိပ်၍ အလိုအလျောက် စာပို့ပေးခြင်း (Autonomous Messaging)။
   - 🖥️ `inspect_screen()`: မေးမြန်းသည့်အခါ လက်ရှိ Screen ပေါ်တွင် ပေါ်နေသော စာသားများနှင့် feed များကို ဖတ်ပြခြင်း။
   - 👆 `control_screen(action, target, field, x, y)`: Screen ပေါ်တွင် click နှိပ်ခြင်း၊ send ခလုတ်နှိပ်ခြင်း၊ scroll အထက်/အောက်ဆွဲခြင်း၊ စာရိုက်ထည့်ခြင်း၊ back/home သွားခြင်း (Autonomous UI Control)။
   - 🎙️ `record_audio(action)`: Jarvis ကိုယ်ပိုင် MediaRecorder (44.1kHz AAC, .m4a) ဖြင့် အသံဖမ်းယူခြင်း (start / stop)။
6. **Security & Privacy:**
   - Gemini API Key ကို `flutter_secure_storage` (Android Keystore / EncryptedSharedPreferences) ဖြင့် လုံခြုံစွာ သိမ်းဆည်းထားပြီး code သို့မဟုတ် repository ထဲတွင် ဘယ်တော့မှ hardcode မလုပ်ပါ။
   - Tool များကို code ထဲမှာပဲ သတ်မှတ်ထားသည် (Gemini က tool အသစ် ထွင်ခေါ်၍ မရပါ)။
   - **ပို့ခြင်း/ခေါ်ခြင်း/ဖျက်ခြင်းမလုပ်ခင် အတည်ပြုချက်တောင်းရမည်:** ဥပမာ စာမပို့မီ လက်ခံသူနှင့် စာသားအတိအကျကို ပြန်ဖတ်ပြပြီး အသုံးပြုသူ အတည်ပြုမှသာ လုပ်ဆောင်ခြင်း။
   - Accessibility နှင့် Notification Listener ကို အသုံးပြုသူက အသံဖြင့် ခိုင်းစေမှသာ တစ်ကြိမ်စာ အသုံးပြုခြင်း။ Background တွင် screen အလိုအလျောက် မဖတ်ပါ၊ password / PIN / ဘဏ် screen များနှင့် OTP notification များကို လုံးဝ မဖတ်ပါ။
   - Accessibility service ဖော်ပြချက်စာသားကိုလည်း အထက်ပါစည်းမျဉ်းအတိုင်းသာ သတ်မှတ်ထားသည်။
7. **Voice & Model Configuration:**
   - Voice: PC config မူရင်းအတိုင်း `Charon` ကို default ထားရှိပြီး Settings တွင် `Puck`, `Kore`, `Fenrir`, `Aoede` တို့သို့ ပြောင်းလဲနိုင်ခြင်း။
   - Model: `models/gemini-3.8-live` (သို့မဟုတ် `models/gemini-2.0-flash-exp`)။

---

## အရေးကြီးသော လိုအပ်ချက်များ (Prerequisites & Network)

> [!IMPORTANT]
> **VPN လိုအပ်ချက် (Myanmar Users):**
> မြန်မာနိုင်ငံမှ Gemini Live WebSocket API ကို တိုက်ရိုက်ချိတ်ဆက်ရာတွင် Google ဘက်မှ Network Restriction ရှိသောကြောင့် **ဖုန်းတွင် VPN (ဥပမာ- 1.1.1.1, Proton, Express, Windscribe စသည်) ဖွင့်ထားရန် မဖြစ်မနေ လိုအပ်ပါသည်**။

- **Flutter SDK:** Version `>= 3.0.0`
- **Android Target:** Android 6.0 (API 23) နှင့် အထက် (လက်ရှိစမ်းသပ်ဆဲဖုန်း: Redmi Note 15 Pro 5G, Android 16)
- **Gemini API Key:** Google AI Studio (aistudio.google.com) မှ ရယူထားသော API key

---

## စတင်အသုံးပြုပုံ (Setup & Run)

### ၁။ Dependency များ ဒေါင်းလုဒ်ရယူခြင်း
```bash
cd jarvis_android
flutter pub get
```

### ၂။ Debug Mode ဖြင့် Run ခြင်း (ဖုန်းကို USB ကြိုးထိုး၍ သို့မဟုတ် Emulator တွင်)
```bash
flutter run
```

### ၃။ Debug APK ထုတ်ယူခြင်း (Building Debug APK)
```bash
flutter build apk --debug
```
တည်ဆောက်ပြီးသော APK ဖိုင်ကို `build/app/outputs/flutter-apk/app-debug.apk` တွင် ရရှိနိုင်ပြီး ဖုန်းထဲသို့ install ပြုလုပ်နိုင်ပါသည်။
**စည်းမျဉ်း:** PC မှာ ပြင်ပြီး batch တစ်ခုစာ သေချာမှ ဖုန်းကို တစ်ခါတည်း install လုပ်ပါ။ Fix တစ်ခုချင်းစီတိုင်း ဖုန်းကို ခဏခဏ ပြန် install မလုပ်ပါနှင့်။

---

## Settings နှင့် API Key ထည့်သွင်းနည်း

1. App ပွင့်လာပါက ညာဘက်အပေါ်ထောင့်ရှိ **Settings (ဂီယာပုံ) Icon** ကို နှိပ်ပါ။
2. **Gemini API Key** အကွက်တွင် မိမိ၏ Google AI Studio API Key ကို Paste လုပ်ပါ။
3. အသံ (Voice) ကို ရွေးချယ်ပါ (Default: **Charon**)။
4. Wake word၊ Hands-free၊ Threshold (ဥပမာ 0.12 သို့မဟုတ် 0.15) ကို ရွေးပါ။
5. **သိမ်းဆည်းမည် (Save Settings)** ခလုတ်ကို နှိပ်ပါ။ (ခလုတ်မနှိပ်မချင်း toggle ပြောင်းရုံဖြင့် မသိမ်းပါ)။
6. ပင်မမျက်နှာပြင်သို့ ပြန်ရောက်ပါက အလိုအလျောက် Live API သို့ ချိတ်ဆက်သွားမည်ဖြစ်ပြီး စတင်နှုတ်ဆက်သံ ကြားရပါမည်။
7. Redmi/HyperOS ဖုန်းတွင်: Battery saver → **No restrictions**၊ Autostart **ON**၊ Recent apps တွင် Jarvis card ကို **Lock** လုပ်ထားပါ (Restart လုပ်ပါက lock ပျက်တတ်၍ ပြန် lock ရပါမည်)။

---

## စမ်းသပ်စစ်ဆေးခြင်း (Acceptance Tests Verification)

### MVP (အောင်ပြီး)
| စမ်းသပ်ချက် (Test) | မျှော်မှန်းရလဒ် (Expected Result) |
|---|---|
| **၁။ VPN & Key ချိတ်ဆက်မှု** | VPN ဖွင့်၊ Key ထည့်ပြီးသည်နှင့် အစိမ်းရောင် Status Pill ပြသပြီး Live ချိတ်မိခြင်း။ |
| **၂။ မြန်မာလို Greeting** | ချိတ်ဆက်မိသည်နှင့် "မင်္ဂလာပါ ဆရာ ကျွန်တော် ဂျာဗစ် ပါ..." ဟု အသံထွက် နှုတ်ဆက်ခြင်း။ |
| **၃။ Push-to-Talk စကားပြောခြင်း** | မိုက်ခလုတ်ဖိထားပြီး "ဒီနေ့ ဘာနေ့လဲ" သို့မဟုတ် စကားပြောပါက မြန်မာလို ပြန်လည်ဖြေကြားခြင်း။ |
| **၄။ ရာသီဥတု မေးမြန်းခြင်း** | "နေပြည်တော် ရာသီဥတု ဘယ်လိုရှိလဲ" ဟု မေးပါက `get_weather` tool ခေါ်ယူပြီး အပူချိန်နှင့် အခြေအနေကို မြန်မာလို ဖြေကြားခြင်း။ |
| **၅။ Web Search မေးမြန်းခြင်း** | "Flutter ဆိုတာ ဘာလဲ" ဟု မေးပါက `web_search` tool ခေါ်ယူပြီး အချက်အလက် ရှင်းပြပေးခြင်း။ |
| **၆။ Reminder သတ်မှတ်ခြင်း** | "ငါးမိနစ်နေရင် ရေနွေးအိုးပိတ်ဖို့ သတိပေးပါ" ဟု ပြောပါက reminder သတ်မှတ်ပေးပြီး ဖုန်း notification တက်လာခြင်း။ |
| **၇။ Error ကိုင်တွယ်မှု** | အင်တာနက်မရှိလျှင် သို့မဟုတ် VPN မဖွင့်ထားပါက "ချိတ်ဆက်မှု မအောင်မြင်ပါ (VPN စစ်ဆေးပါ)" ဟု မြန်မာလို ရှင်းလင်းစွာ ပြသခြင်း။ |
| **၈။ Code ထဲတွင် API Key မပါဝင်မှု** | Grep ဖြင့် စစ်ဆေးပြီးဖြစ်၍ code ထဲတွင် hardcoded API key လုံးဝ မပါဝင်ခြင်း။ |

### Wake + Hands-free + Barge-in (စစ်ဆဲ)
- "Hey Jarvis" → ၃ ကြိမ် ဆက်တိုက် hands-free မေးခွန်း ဖြေနိုင်ခြင်း။
- စကားပြောနေတုန်း ဖြတ်ပြောပါက (barge-in အသံကျယ် + အသံတိုး) Jarvis က ရပ်ပြီး နားထောင်ခြင်း။
- အဖြေပြီးချင်း Status Pill က listening ပြရမည် (connected မဟုတ်ပါ)။
- 30s တိတ်ဆိတ်ပါက wake mode ပြန်သွားပြီး ပြန် wake လို့ရခြင်း။
- Settings ပြောင်း + Save + app restart လုပ်ပြီးနောက် တန်ဖိုးများ အတိအကျ ကျန်ရှိခြင်း။

### Per-app Tools (ဖုန်းပေါ်တွင် အသံဖြင့် စစ်ဆဲ)
- **ကင်မရာ (`take_photo`)**: "ကင်မရာဖွင့်ပြီး ဓာတ်ပုံရိုက်ပေးပါ" → CameraX preview ပြပြီး ဓာတ်ပုံရိုက်ခြင်း၊ Gallery (DCIM/Camera) ထဲတွင် ဖိုင်အမှန်တကယ် ရောက်ရှိခြင်း။
- **Facebook / စာအသစ်စစ်ဆေးခြင်း (`check_messages`)**: "Facebook မှာ notification ဘာတွေတက်နေလဲ" → Listener မှ ရရှိသော notification (ပို့သူ + အမျိုးအစား) ကို ပြောကြားခြင်း၊ notification မရှိပါက "Facebook တွင် notification အသစ် မရှိပါ ခင်ဗျာ" ဟုသာ တိကျစွာပြောခြင်း (screen feed စာသားများ အစားထိုး မပြောပါ)။
- **အသံဖမ်း (`record_audio`)**: "အသံဖမ်းပေးပါ" (Live mic ခေတ္တရပ်ပြီး စဖမ်းခြင်း) → "ရပ်ပေးပါ" → .m4a ဖိုင် တကယ်ရှိပြီး ကြာချိန်နှင့် လမ်းကြောင်း ပြောကြားခြင်း (Live mic ပြန်ပွင့်ခြင်း)။
- **YouTube (`play_youtube`)**: သီချင်းရှာဖွင့်ပြီး အသံတကယ်ထွက်ခြင်း။
- **Telegram / Viber စာစစ်ခြင်း (`check_messages`)**: စာအသစ်ရှိမရှိကို notification မှတစ်ဆင့် ပြောကြားခြင်း။
- **Torch / Volume / Battery (`toggle_torch`, `set_volume`, `get_device_status`, `open_app`)**: အသံဖြင့် ခိုင်းစေသည့်အတိုင်း တစ်ချက်ချင်း အလုပ်လုပ်ခြင်း။
- **Screen ဖတ်ခြင်းနှင့် ထိန်းချုပ်ခြင်း (`inspect_screen`, `control_screen`)**: မျက်နှာပြင်ပေါ်ရှိ စာသားများကို ဖတ်ပြခြင်းနှင့် UI elements များအား လိုအပ်သလို အလိုအလျောက် ထိန်းချုပ်ဆောင်ရွက်ခြင်း။
- **Knowledge Base Source of Truth Checklist**: Repo root ရှိ `jarvis_knowledge.md` (v1.2, 13 Oct 2026) သည် **Single Source of Truth** ဖြစ်ပါသည်။ Root ဖိုင်ကို ပြင်ဆင်မွမ်းမံတိုင်း `jarvis_android/assets/jarvis_knowledge.md` ထဲသို့ မပျက်မကွက် ပြန်လည်ကူးယူ ထည့်သွင်းရပါမည်။ Live session စတင်တိုင်း System Instruction ထဲတွင် read-only reference အဖြစ် ထည့်သွင်းထားပြီး ဖိုင်ထဲပါတာကို အတိအကျဖြေရန်နှင့် ဖိုင်ထဲမပါသော/လက်ရှိမေးခွန်းများကို `web_search` ဖြင့် ရှာဖွေစစ်ဆေးပြီးမှ ဖြေရန် သတ်မှတ်ထားသည်။

> [!NOTE]
> ADB test အောင်ရုံ၊ unit test အောင်ရုံဖြင့် "ပြီးပြီ" ဟု မမှတ်ယူရပါ။ အထက်ပါ အသံဖြင့် စစ်ဆေးချက်များ အားလုံး အောင်မြင်မှသာ အပြီးသတ် မှတ်ယူရပါမည်။

---

## စီမံခန့်ခွဲမှု ဖိုင်တည်ဆောက်ပုံ (App Structure)

လက်ရှိ `jarvis_android/` ၏ အမှန်တကယ် ရှိနေသော ဖိုင်တည်ဆောက်ပုံ ဖြစ်ပါသည်:

```
jarvis_android/
├── lib/
│   ├── main.dart                      # App entry point, Dark Jarvis theme & providers
│   ├── audio/
│   │   ├── audio_service.dart         # 16kHz PCM recording & 24kHz PCM playback (barge-in & RMS volume tracking)
│   │   ├── background_service.dart    # Android Foreground service lifecycle management
│   │   ├── pcm_converter.dart         # Raw PCM to WAV memory byte converter & RMS calculation
│   │   └── wake_word_service.dart     # On-device "Hey Jarvis" detection (openWakeWord)
│   ├── live/
│   │   ├── live_client.dart           # Gemini Live WebSocket client (connect, stream, tools, errors, turns)
│   │   ├── live_session_config.dart   # Gemini Live setup payload & tool declarations
│   │   └── prompt_builder.dart        # Burmese system prompt adapted from PC Jarvis & greeting generator
│   ├── memory/
│   │   ├── app_prefs.dart             # Voice, model, wake word, threshold, hands-free settings
│   │   ├── memory_service.dart        # Transcript message history & system event logging
│   │   └── secure_key_store.dart      # FlutterSecureStorage for Gemini API key (Keystore)
│   ├── settings/
│   │   └── settings_screen.dart       # API key entry, Voice & Model selectors, wake settings & threshold slider
│   ├── tools/
│   │   ├── app_launcher_tool.dart     # open_app tool (launch apps by query/name)
│   │   ├── audio_recorder_tool.dart   # record_audio tool (start/stop MediaRecorder with mic coordination)
│   │   ├── base_tool.dart             # Base class & Gemini FunctionDeclaration schema interface
│   │   ├── camera_capture_tool.dart   # take_photo tool (Jarvis CameraX photo capture)
│   │   ├── device_channel.dart        # MethodChannel bridge to native Android DeviceController
│   │   ├── device_status_tool.dart    # get_device_status tool (battery, charging, volume, ringer)
│   │   ├── messages_tool.dart         # check_messages tool (Telegram, Viber, Facebook notification listener)
│   │   ├── reminder_tool.dart         # set_reminder tool (local notifications / alarm receiver)
│   │   ├── screen_agent_tool.dart     # inspect_screen & control_screen tools (accessibility screen OCR & control)
│   │   ├── torch_tool.dart            # toggle_torch tool (flashlight on/off)
│   │   ├── volume_tool.dart           # set_volume tool (media/ring/alarm volume 0-100%)
│   │   ├── weather_tool.dart          # get_weather tool (Open-Meteo free API)
│   │   ├── web_search_tool.dart       # web_search tool (DuckDuckGo / Wikipedia search)
│   │   └── youtube_tool.dart          # play_youtube tool (YouTube direct search & play)
│   └── ui/
│       ├── home_screen.dart           # Home view with status pill, transcript, push-to-talk & wake indicators
│       └── widgets/
│           ├── mic_button.dart        # Animated Glowing Push-to-Talk button with volume reaction
│           ├── status_pill.dart       # Live status indicator (disconnected, connecting, connected, listening, thinking, speaking)
│           └── transcript_view.dart   # Chat transcript bubble view (user, jarvis, tool calls)
├── android/
│   ├── app/src/main/
│   │   ├── AndroidManifest.xml        # Permissions, queries, foreground service, receivers, activities
│   │   ├── kotlin/com/jarvis/android/
│   │   │   ├── CameraActivity.kt      # Native CameraX photo capture activity & Gallery sync
│   │   │   ├── DeviceController.kt    # Native Android hardware/system controls & window overlay
│   │   │   ├── JarvisAccessibilityService.kt # Accessibility service for screen inspect & UI control
│   │   │   ├── JarvisAudioRecorder.kt # Native MediaRecorder for on-demand audio recording
│   │   │   ├── JarvisNotificationListener.kt # NotificationListenerService for real-time notifications
│   │   │   ├── MainActivity.kt        # FlutterActivity & MethodChannel handler
│   │   │   └── ReminderReceiver.kt    # Exact alarm broadcast receiver for reminders
│   │   └── res/xml/
│   │       └── accessibility_service_config.xml # Accessibility service configuration
│   └── app/build.gradle.kts           # Gradle build script (CameraX, Desugaring, Java 17)
├── assets/
│   └── models/
│       ├── hey_jarvis.onnx            # Target wake word detection model
│       ├── melspectrogram.onnx        # Audio melspectrogram feature extraction model
│       └── embedding_model.onnx       # Audio embedding feature extraction model
├── test/
│   ├── app_prefs_test.dart            # App preferences & settings unit tests
│   ├── live_client_barge_in_test.dart # Live client barge-in handling & turn management tests
│   ├── live_session_config_test.dart  # Live session configuration & tool schema tests
│   ├── pcm_converter_test.dart        # PCM conversion & RMS volume unit tests
│   └── tools_test.dart                # Unit tests for all 13 tools & device channel
├── pubspec.yaml                       # Project dependencies
└── README.md                          # Documentation (ဤဖိုင်)
```

**Android permissions (လက်ရှိ `AndroidManifest.xml` အရ):**
`INTERNET`, `RECORD_AUDIO`, `CAMERA`, `POST_NOTIFICATIONS`, `SCHEDULE_EXACT_ALARM`, `USE_EXACT_ALARM`, `VIBRATE`, `ACCESS_NETWORK_STATE`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MICROPHONE`, `WAKE_LOCK`, `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, `FLASHLIGHT`, `SYSTEM_ALERT_WINDOW`, `USE_FULL_SCREEN_INTENT`, `QUERY_ALL_PACKAGES`, `BIND_NOTIFICATION_LISTENER_SERVICE`, `BIND_ACCESSIBILITY_SERVICE`။

> [!NOTE]
> Permission အသစ် ထပ်တိုးတိုင်း `AndroidManifest.xml` နှင့်အတူ README တွင်ပါ မဖြစ်မနေ အမြဲတမ်း ဖြည့်စွက်ပြင်ဆင်ရပါမည်။

---

## မလုပ်ရသေးတာများ (Out of scope — သတိပြုရန်)

- သတင်းကို အလိုအလျောက် ကြေညာခြင်း မလုပ်ပါ (`newsroom_watch` / `background_monitor` auto-news ကို ဖုန်း build ထဲ မထည့်ပါ)။ သတင်းသည် မေးမြန်းလာမှသာ on-demand ရှာဖွေပေးခြင်း ဖြစ်သည်။
- Tasker သို့မဟုတ် တခြား automation အက်ပ်များကို မသုံးပါ — ထိန်းချုပ်မှု အားလုံးသည် ဤအက်ပ်ထဲတွင်သာ တိုက်ရိုက် တည်ဆောက်ထားသည်။
- Root command၊ device-admin၊ uninstall/delete ပြုလုပ်ခြင်းများ မပါဝင်ပါ။
- Gotcha ၏ Kotlin code များကို မကူးယူပါ (AGPL-3.0) — အယူအဆကိုသာ Dart နှင့် သီးသန့် native code ဖြင့် အသစ် ပြန်လည်ရေးသားထားခြင်း ဖြစ်သည်။
