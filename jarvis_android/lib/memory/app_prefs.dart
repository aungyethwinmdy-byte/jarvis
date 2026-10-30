import 'package:shared_preferences/shared_preferences.dart';

/// App preferences for Voice selection, Model name, and Identity.
class AppPrefs {
  static const String _keyVoiceName = 'voice_name';
  static const String _keyModelName = 'model_name';

  // Allowed Gemini Live prebuilt voices
  static const List<String> availableVoices = [
    'Charon',
    'Puck',
    'Kore',
    'Fenrir',
    'Aoede',
  ];

  // Default matching PC config (voice_name: Charon, fallback: Kore)
  static const String defaultVoice = 'Charon';
  static const String fallbackVoice = 'Kore';

  // Live Model
  static const String defaultModel = 'models/gemini-3.8-live';
  static const List<String> availableModels = [
    'models/gemini-3.8-live',
    'models/gemini-2.0-flash-exp',
  ];

  // Identity
  static const String userName = 'ဆရာ';
  static const String assistantName = 'ဂျာဗစ်';

  static Future<String> getVoiceName() async {
    final prefs = await SharedPreferences.getInstance();
    final v = prefs.getString(_keyVoiceName) ?? defaultVoice;
    return availableVoices.contains(v) ? v : fallbackVoice;
  }

  static Future<void> saveVoiceName(String voice) async {
    if (availableVoices.contains(voice)) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_keyVoiceName, voice);
    }
  }

  static Future<String> getModelName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyModelName) ?? defaultModel;
  }

  static Future<void> saveModelName(String model) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyModelName, model);
  }
}
