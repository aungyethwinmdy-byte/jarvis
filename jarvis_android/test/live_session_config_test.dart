import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/live/live_session_config.dart';
import 'package:jarvis_android/live/prompt_builder.dart';
import 'package:jarvis_android/tools/weather_tool.dart';

void main() {
  group('LiveSessionConfig Tests', () {
    test('createSetupPayload generates valid Gemini Live structure', () {
      final payload = LiveSessionConfig.createSetupPayload(
        modelName: 'models/gemini-3.8-live',
        voiceName: 'Charon',
        tools: [WeatherTool()],
      );

      expect(payload.containsKey('setup'), true);
      final setup = payload['setup'] as Map<String, dynamic>;

      expect(setup['model'], 'models/gemini-3.8-live');
      expect(setup['generationConfig']['responseModalities'], ['AUDIO']);
      expect(setup['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'], 'Charon');

      final tools = setup['tools'] as List;
      expect(tools.isNotEmpty, true);

      final prompt = PromptBuilder.buildSystemPrompt();
      expect(prompt.contains('ဆရာ'), true);
      expect(prompt.contains('မြန်မာဘာသာ'), true);
    });
  });
}
