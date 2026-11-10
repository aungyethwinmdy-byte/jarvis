import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/knowledge/knowledge_service.dart';
import 'package:jarvis_android/live/live_session_config.dart';
import 'package:jarvis_android/live/prompt_builder.dart';

void main() {
  group('KnowledgeService Tests', () {
    test('KnowledgeService loads and formats jarvis_knowledge.md', () async {
      final kb = await KnowledgeService.loadKnowledgeBase();
      expect(kb.isNotEmpty, true);
      expect(kb.contains('[KNOWLEDGE BASE — READ-ONLY REFERENCE]'), true);
      expect(kb.contains('[KNOWLEDGE BASE STRICT RULES]'), true);
      expect(kb.contains('web_search tool'), true);
      expect(kb.contains('ကာကွယ်ရေးဝန်ကြီးဌာန'), true);
      expect(kb.contains('ဗိုလ်ချုပ်ကြီး ရာပြည့်'), true);
      expect(kb.contains('နိုင်ငံခြားရေးဝန်ကြီးဌာန'), true);
      expect(kb.contains('ဦးတင်မောင်ဆွေ'), true);
    });

    test('PromptBuilder and LiveSessionConfig integrate knowledgeBase into systemInstruction', () async {
      final kb = await KnowledgeService.loadKnowledgeBase();
      final sysPrompt = PromptBuilder.buildSystemPrompt(knowledgeBase: kb);
      expect(sysPrompt.contains('[KNOWLEDGE BASE — READ-ONLY REFERENCE]'), true);
      expect(sysPrompt.contains('[KNOWLEDGE BASE & VERIFICATION DIRECTIVES]'), true);

      final payload = LiveSessionConfig.createSetupPayload(
        modelName: 'models/gemini-2.0-flash-exp',
        voiceName: 'Charon',
        tools: [],
        knowledgeBase: kb,
      );

      final setup = payload['setup'] as Map<String, dynamic>;
      final sysInstruction = setup['systemInstruction'] as Map<String, dynamic>;
      final parts = sysInstruction['parts'] as List;
      final text = parts.first['text'] as String;

      expect(text.contains('[KNOWLEDGE BASE — READ-ONLY REFERENCE]'), true);
      expect(text.contains('ကာကွယ်ရေးဝန်ကြီးဌာန'), true);
    });
  });
}
