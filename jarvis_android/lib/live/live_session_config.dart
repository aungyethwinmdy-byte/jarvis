import '../tools/base_tool.dart';
import 'prompt_builder.dart';

/// Builds the setup payload for Gemini Live WebSockets connection.
class LiveSessionConfig {
  static Map<String, dynamic> createSetupPayload({
    required String modelName,
    required String voiceName,
    required List<BaseTool> tools,
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
            {'text': PromptBuilder.buildSystemPrompt()}
          ],
        },
        if (functionDeclarations.isNotEmpty)
          'tools': [
            {'functionDeclarations': functionDeclarations}
          ],
        'inputAudioTranscription': {},
        'outputAudioTranscription': {},
      }
    };
  }
}
