import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:jarvis_android/memory/app_prefs.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('AppPrefs Wake Word Threshold Tests', () {
    test('threshold migration ဖြုတ်ပြီး user threshold အတိအကျ ပြန်ရသည် (0.20 preserved)', () async {
      SharedPreferences.setMockInitialValues({'wake_word_threshold': 0.20});
      final threshold = await AppPrefs.getWakeWordThreshold();
      expect(threshold, 0.20);
    });

    test('returns exact user threshold for 0.12', () async {
      SharedPreferences.setMockInitialValues({'wake_word_threshold': 0.12});
      final threshold = await AppPrefs.getWakeWordThreshold();
      expect(threshold, 0.12);
    });

    test('returns default 0.15 only when no threshold is set in preferences', () async {
      SharedPreferences.setMockInitialValues({});
      final threshold = await AppPrefs.getWakeWordThreshold();
      expect(threshold, 0.15);
    });
  });
}
