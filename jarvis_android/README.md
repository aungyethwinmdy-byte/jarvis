# Android JARVIS MVP (Voice Assistant)

Android ဖုန်းပေါ်တွင် တိုက်ရိုက်အသုံးပြုနိုင်သော **JARVIS Mobile Voice Assistant (MVP)** ဖြစ်ပါသည်။ PC server သို့မဟုတ် background server မလိုဘဲ ဖုန်းမှ **Google Gemini Live API (WebSocket)** သို့ တိုက်ရိုက်ချိတ်ဆက်၍ အသံဖြင့် အပြန်အလှန် စကားပြောဆိုနိုင်ပါသည်။

---

## အဓိက အင်္ဂါရပ်များ (Core Features)

1. **Push-to-Talk Voice Chat:**
   - မိုက်ခလုတ်ကို ဖိထားပြီး မြန်မာလို စကားပြောဆိုနိုင်ခြင်း။
   - Input Audio: `16,000 Hz, 16-bit mono PCM` stream။
   - Output Audio: `24,000 Hz, 16-bit mono PCM` playback။
2. **Burmese-First Persona:**
   - အသုံးပြုသူကို "**ဆရာ**" ဟု အမြဲယဉ်ကျေးစွာ ခေါ်ဆိုခြင်း။
   - စကားပြောရာတွင် "ကျွန်တော်"၊ "ခင်ဗျာ/ဗျာ" သုံးစွဲပြီး မြန်မာဘာသာဖြင့်သာ တိုတိုနှင့် လိုရင်းကို ဖြေကြားခြင်း။
   - PC Jarvis (`main.py`) ၏ မူရင်း greeting အတိုင်း ချိတ်ဆက်သည်နှင့် နှုတ်ဆက်စကား စတင်ပြောကြားခြင်း။
3. **Native Mobile Tools (၃ ခု):**
   - ☀️ `get_weather(location)`: Open-Meteo free API ဖြင့် နေပြည်တော်၊ ရန်ကုန်၊ မန္တလေးနှင့် ကမ္ဘာ့မြို့ကြီးများ၏ ရာသီဥတုကို အချိန်နှင့်တပြေးညီ ရယူခြင်း (API key မလို)။
   - 🔍 `web_search(query)`: DuckDuckGo / Wikipedia web search ဖြင့် နောက်ဆုံးရ အချက်အလက်များ ရှာဖွေပေးခြင်း။
   - 🔔 `set_reminder(title, in_minutes)`: `flutter_local_notifications` ဖြင့် ဖုန်းပေါ်တွင် local reminder notification သတ်မှတ်ပေးခြင်း။
4. **Security & Privacy:**
   - Gemini API Key ကို `flutter_secure_storage` (Android Keystore / EncryptedSharedPreferences) ဖြင့် လုံခြုံစွာ သိမ်းဆည်းထားပြီး code သို့မဟုတ် repository ထဲတွင် ဘယ်တော့မှ hardcode မလုပ်ပါ။
5. **Voice & Model Configuration:**
   - Voice: PC config မူရင်းအတိုင်း `Charon` ကို default ထားရှိပြီး Settings တွင် `Puck`, `Kore`, `Fenrir`, `Aoede` တို့သို့ ပြောင်းလဲနိုင်ခြင်း။
   - Model: `models/gemini-3.8-live` (သို့မဟုတ် `models/gemini-2.0-flash-exp`)။

---

## အရေးကြီးသော လိုအပ်ချက်များ (Prerequisites & Network)

> [!IMPORTANT]
> **VPN လိုအပ်ချက် (Myanmar Users):**
> မြန်မာနိုင်ငံမှ Gemini Live WebSocket API ကို တိုက်ရိုက်ချိတ်ဆက်ရာတွင် Google ဘက်မှ Network Restriction ရှိသောကြောင့် **ဖုန်းတွင် VPN (ဥပမာ- 1.1.1.1, Proton, Express, Windscribe စသည်) ဖွင့်ထားရန် မဖြစ်မနေ လိုအပ်ပါသည်**။

- **Flutter SDK:** Version `>= 3.0.0`
- **Android Target:** Android 6.0 (API 23) နှင့် အထက်
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

---

## Settings နှင့် API Key ထည့်သွင်းနည်း

1. App ပွင့်လာပါက ညာဘက်အပေါ်ထောင့်ရှိ **Settings (ဂီယာပုံ) Icon** ကို နှိပ်ပါ။
2. **Gemini API Key** အကွက်တွင် မိမိ၏ Google AI Studio API Key ကို Paste လုပ်ပါ။
3. အသံ (Voice) ကို ရွေးချယ်ပါ (Default: **Charon**)။
4. **သိမ်းဆည်းမည် (Save Settings)** ခလုတ်ကို နှိပ်ပါ။
5. ပင်မမျက်နှာပြင်သို့ ပြန်ရောက်ပါက အလိုအလျောက် Live API သို့ ချိတ်ဆက်သွားမည်ဖြစ်ပြီး စတင်နှုတ်ဆက်သံ ကြားရပါမည်။

---

## စမ်းသပ်စစ်ဆေးခြင်း (Acceptance Tests Verification)

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

---

## စီမံခန့်ခွဲမှု ဖိုင်တည်ဆောက်ပုံ (App Structure)

```
jarvis_android/
├── lib/
│   ├── main.dart                      # App entry point, Dark Jarvis theme & providers
│   ├── audio/
│   │   ├── audio_service.dart         # 16kHz PCM recording & 24kHz PCM playback (barge-in ready)
│   │   └── pcm_converter.dart         # Raw PCM to WAV memory byte converter
│   ├── live/
│   │   ├── live_client.dart           # Gemini Live WebSocket client (connect, stream, tools, errors)
│   │   ├── live_session_config.dart   # Setup payload generator
│   │   └── prompt_builder.dart        # Burmese system prompt adapted from PC Jarvis
│   ├── memory/
│   │   ├── app_prefs.dart             # Voice, model, user settings
│   │   ├── memory_service.dart        # Transcript message history
│   │   └── secure_key_store.dart      # FlutterSecureStorage for Gemini API key
│   ├── settings/
│   │   └── settings_screen.dart       # API key entry, Voice & Model selectors
│   ├── tools/
│   │   ├── base_tool.dart             # Tool base class
│   │   ├── reminder_tool.dart         # Local notifications reminder
│   │   ├── weather_tool.dart          # Free Open-Meteo weather
│   │   └── web_search_tool.dart       # Free DuckDuckGo/Wikipedia search
│   └── ui/
│       ├── home_screen.dart           # Home view with status pill, transcript, push-to-talk
│       └── widgets/
│           ├── mic_button.dart        # Animated Glowing Push-to-Talk button
│           ├── status_pill.dart       # Live status indicator
│           └── transcript_view.dart   # Chat transcript bubble view
├── android/                           # Native Android configuration & manifests
├── test/                              # Unit tests for PCM converter & Live configuration
├── pubspec.yaml                       # Project dependencies
└── README.md                          # Documentation
```
