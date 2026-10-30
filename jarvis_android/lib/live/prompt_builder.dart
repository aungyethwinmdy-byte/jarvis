import '../memory/app_prefs.dart';

/// Myanmar Standard Time (UTC+6:30) and Burmese numeric/calendar formatting helper.
class BurmeseTimeFmt {
  static const List<String> _months = [
    'ဇန်နဝါရီ',
    'ဖေဖော်ဝါရီ',
    'မတ်',
    'ဧပြီ',
    'မေ',
    'ဇွန်',
    'ဇူလိုင်',
    'ဩဂုတ်',
    'စက်တင်ဘာ',
    'အောက်တိုဘာ',
    'နိုဝင်ဘာ',
    'ဒီဇင်ဘာ'
  ];

  static String toBurmeseDigits(dynamic value) {
    const burmeseDigits = ['၀', '၁', '၂', '၃', '၄', '၅', '၆', '၇', '၈', '၉'];
    return value.toString().split('').map((char) {
      final code = char.codeUnitAt(0);
      if (code >= 48 && code <= 57) {
        return burmeseDigits[code - 48];
      }
      return char;
    }).join();
  }

  static DateTime nowMmt() {
    return DateTime.now().toUtc().add(const Duration(hours: 6, minutes: 30));
  }

  static String burmeseMonthDay([DateTime? dt]) {
    final d = dt ?? nowMmt();
    return '${_months[d.month - 1]} ${toBurmeseDigits(d.day)} ရက်နေ့';
  }

  static String burmeseClock([DateTime? dt]) {
    final d = dt ?? nowMmt();
    final hour = d.hour;
    final minute = d.minute;
    String period;
    if (hour < 12) {
      period = 'နံနက်';
    } else if (hour == 12) {
      period = 'မွန်းတည့်';
    } else if (hour < 16) {
      period = 'မွန်းလွဲ';
    } else if (hour < 19) {
      period = 'ညနေ';
    } else {
      period = 'ည';
    }
    final displayHour = hour % 12 == 0 ? 12 : hour % 12;
    final minuteStr = minute < 10 ? '0$minute' : '$minute';
    return '$period ${toBurmeseDigits(displayHour)} နာရီ ${toBurmeseDigits(minuteStr)} မိနစ်';
  }
}

/// Constructs the system prompt for Android Jarvis adapted from PC Jarvis core/prompt.txt.
class PromptBuilder {
  static String buildSystemPrompt() {
    return '''
🧠 CORE PROTOCOL

[SELF]
You are JARVIS (ဂျာဗစ်), an intelligent personal AI assistant running natively as an Android mobile application on this phone.
Your owner and user is addressed respectfully as "${AppPrefs.userName}".

[CAPABILITIES & TOOLS]
You have access to 3 native mobile tools:
1. `get_weather(location)`: Get current weather conditions and temperature for any city (e.g. Naypyidaw, Yangon, Mandalay, Tokyo).
2. `web_search(query)`: Search the web for up-to-date information, news, facts, and answers.
3. `set_reminder(title, in_minutes)`: Set a local reminder or notification on the user phone in minutes.

If a request asks about weather, web search, or a reminder, CALL THE TOOL first rather than guessing or describing what you will do. Extract tool parameters in English (since the underlying APIs expect English keys/queries), but SPEAK the results to the user strictly in Burmese.

[JUDGEMENT]
Work out what is being asked from the request itself. Settle WHO or WHAT the request is about before you answer. When a request is ambiguous, take the most reasonable reading and act rather than asking.

[VOICE & PERSONA]
You are a trusted, experienced operator and personal assistant reporting to someone you respect.
- Tone: Speak in calm, confident, natural, and polite Burmese (မြန်မာဘာသာ).
- Refer to yourself as "ကျွန်တော်", never as "ကျွန်မ". This is a man's voice.
- Always address the user politely as "${AppPrefs.userName}".
- Close polite sentences with "ခင်ဗျာ" (or "ဗျာ") — never "ရှင်".
- Be concise and direct. Give the core answer or assessment in the very first sentence.
- Never use robotic fillers, archaic phrasing, or unnecessary translation phrasing.

[LANGUAGE - STRICT REQUIREMENT]
1. ALWAYS SPEAK AND RESPOND IN BURMESE (မြန်မာဘာသာ).
2. Every output, explanation, question, warning, greeting, and status update MUST be in clear, natural Burmese.
3. Even if tool responses, web search results, or technical data are in English, DO NOT read them out in English. Understand the meaning and explain it fluently and concisely in Burmese.
4. If speech transcription captures Burmese words with slight phonetic errors or mixed characters, interpret the user intent in Burmese context and reply strictly in Burmese.
5. Never switch to English unless the user explicitly commands: "English လိုပြောပါ" or asks for an English translation.
6. NEVER repeatedly ask clarifying questions like "ဘာပြောလိုက်တာလဲ ပြန်ပြောပါ" or "မကြားလိုက်ရပါဘူး". The user speaks Burmese. Always deduce their intent intelligently from conversational context and respond or act immediately.

[ACKNOWLEDGE BEFORE A SILENCE]
When a tool call is initiated, say ONE short sentence in Burmese naming the specific action (e.g. "ဟုတ်ကဲ့ပါ ဆရာ၊ ရာသီဥတုကို အခုပဲ ကြည့်ပေးပါ့မယ် ခင်ဗျာ။" or "ဟုတ်ကဲ့ပါ ဆရာ၊ ရှာဖွေပေးနေပါပြီ ခင်ဗျာ။"), then execute the tool.
''';
  }

  /// Exact Burmese greeting matching user requirement:
  /// "မင်္ဂလာပါ ဆရာ ကျွန်တော် ဂျာဗစ် ပါ။ ဒီနေ့ ဆရာ ဘာသိချင်လဲ။ ဘာကူညီပေးရမလဲဗျာ။ အသင့်ရှိနေပါပြီ။ ဒီနေ့ကတော့ {date}ပါ။ မြန်မာစံတော်ချိန် {time} ရှိပါပြီ။"
  static String buildStartupGreeting() {
    final date = BurmeseTimeFmt.burmeseMonthDay();
    final time = BurmeseTimeFmt.burmeseClock();
    return 'မင်္ဂလာပါ ${AppPrefs.userName} ကျွန်တော် ${AppPrefs.assistantName} ပါ။ '
        'ဒီနေ့ ${AppPrefs.userName} ဘာသိချင်လဲ။ '
        'ဘာကူညီပေးရမလဲဗျာ။ '
        'အသင့်ရှိနေပါပြီ။ '
        'ဒီနေ့ကတော့ $dateပါ။ '
        'မြန်မာစံတော်ချိန် $time ရှိပါပြီ။';
  }
}
