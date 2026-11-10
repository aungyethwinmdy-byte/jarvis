import 'package:shared_preferences/shared_preferences.dart';

/// App preferences for Voice selection, Model name, and Identity.
class AppPrefs {
  static const String _keyVoiceName = 'voice_name';
  static const String _keyModelName = 'model_name';
  static const String _keyWakeWordEnabled = 'wake_word_enabled';
  static const String _keyWakeWordThreshold = 'wake_word_threshold';
  static const String _keyHandsFreeEnabled = 'hands_free_enabled';

  // Default threshold for openWakeWord hey_jarvis model
  static const double defaultWakeWordThreshold = 0.15;

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

  static Future<bool> isWakeWordEnabled() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_keyWakeWordEnabled) ?? true;
  }

  static Future<void> setWakeWordEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_keyWakeWordEnabled, enabled);
  }

  static Future<double> getWakeWordThreshold() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getDouble(_keyWakeWordThreshold);
    return saved ?? defaultWakeWordThreshold;
  }

  static Future<void> setWakeWordThreshold(double threshold) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(_keyWakeWordThreshold, threshold);
  }

  static Future<bool> isHandsFreeEnabled() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_keyHandsFreeEnabled) ?? true;
  }

  static Future<void> setHandsFreeEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_keyHandsFreeEnabled, enabled);
  }
}
