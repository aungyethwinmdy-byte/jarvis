import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Service to load and format jarvis_knowledge.md (v1.2, 13 Oct 2026) as read-only reference.
class KnowledgeService {
  static String? _cachedFormattedKnowledge;

  /// Loads jarvis_knowledge.md either from rootBundle or local assets file (fallback for testing).
  static Future<String> loadKnowledgeBase() async {
    if (_cachedFormattedKnowledge != null &&
        _cachedFormattedKnowledge!.isNotEmpty) {
      return _cachedFormattedKnowledge!;
    }

    String raw = '';
    try {
      raw = await rootBundle.loadString('assets/jarvis_knowledge.md');
    } catch (_) {
      try {
        final f = File('assets/jarvis_knowledge.md');
        if (await f.exists()) {
          raw = await f.readAsString();
        } else {
          final rootF = File('../jarvis_knowledge.md');
          if (await rootF.exists()) {
            raw = await rootF.readAsString();
          }
        }
      } catch (_) {}
    }

    if (raw.trim().isNotEmpty) {
      _cachedFormattedKnowledge = formatKnowledgeBase(raw);
      return _cachedFormattedKnowledge!;
    }
    return '';
  }

  static String formatKnowledgeBase(String content) {
    return '''
[KNOWLEDGE BASE — READ-ONLY REFERENCE]
Use the information below as a factual reference when answering questions
about Myanmar governance, policy, security, economy, agriculture,
and other topics covered in this knowledge base.

[KNOWLEDGE BASE STRICT RULES]
1. ဖိုင်ထဲတွင် ပါရှိသော အချက်အလက်များကို ဖိုင်ထဲပါရှိသည့်အတိုင်း တိကျမှန်ကန်စွာ ဖြေကြားပါ။
2. ဖိုင်ထဲတွင် မပါရှိပါက လုံးဝ (လုံးဝ) မခန့်မှန်းပါနှင့်။
3. 'လက်ရှိ' (current/present) မေးခွန်းများ သို့မဟုတ် ဖိုင်ထဲတွင် မပါရှိသော မေးခွန်းများ ဖြစ်ပါက web_search tool ဖြင့် အင်တာနက်တွင် အရင်ရှာဖွေစစ်ဆေးပြီးမှသာ ဖြေကြားပါ။

────────────────────────────────────────────────────────────

$content

────────────────────────────────────────────────────────────
[END KNOWLEDGE BASE]
''';
  }

  @visibleForTesting
  static void setMockKnowledge(String? content) {
    _cachedFormattedKnowledge =
        content != null ? formatKnowledgeBase(content) : null;
  }
}
