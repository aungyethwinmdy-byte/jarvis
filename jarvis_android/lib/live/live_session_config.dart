import '../tools/base_tool.dart';
import 'prompt_builder.dart';

/// Builds the setup payload for Gemini Live WebSockets connection.
class LiveSessionConfig {
  static Map<String, dynamic> createSetupPayload({
    required String modelName,
    required String voiceName,
    required List<BaseTool> tools,
    String? knowledgeBase,
  }) {
    final functionDeclarations =
        tools.map((t) => t.toFunctionDeclaration()).toList();

    return {
      'setup': {
        'model': modelName,
        'generationConfig': {
          'responseModalities': ['AUDIO'],
          'speechConfig': {
            'voiceConfig': {
              'prebuiltVoiceConfig': {
                'voiceName': voiceName,
              },
            },
          },
        },
        'systemInstruction': {
          'parts': [
            {'text': PromptBuilder.buildSystemPrompt(knowledgeBase: knowledgeBase)}
          ],
        },
        if (functionDeclarations.isNotEmpty)
          'tools': [
            {'functionDeclarations': functionDeclarations}
          ],
        'inputAudioTranscription': {},
        'outputAudioTranscription': {},
        'realtimeInputConfig': {
          'automaticActivityDetection': {
            'disabled': false,
            'startOfSpeechSensitivity': 'START_SENSITIVITY_HIGH',
            'prefixPaddingMs': 100,
            'endOfSpeechSensitivity': 'END_SENSITIVITY_HIGH',
            'silenceDurationMs': 400,
          },
        },
      }
    };
  }
}
