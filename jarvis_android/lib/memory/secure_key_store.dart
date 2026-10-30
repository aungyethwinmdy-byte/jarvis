import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Secure storage helper for the Gemini API Key.
/// The key is never kept in plain code, git repositories, or logged to console.
class SecureKeyStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(
      encryptedSharedPreferences: true,
    ),
  );

  static const _keyApiKey = 'gemini_api_key';

  /// Retrieve the Gemini API key from encrypted secure storage
  static Future<String?> getApiKey() async {
    try {
      // Check for one-time initialization file in app's private files folder
      final initFile = File('/data/user/0/com.jarvis.android/files/init_key.txt');
      if (await initFile.exists()) {
        try {
          final raw = await initFile.readAsString();
          final trimmed = raw.trim();
          if (trimmed.isNotEmpty) {
            await saveApiKey(trimmed);
            debugPrint('[SecureKeyStore] Seeded API key successfully into secure storage');
          }
          await initFile.delete();
        } catch (e) {
          debugPrint('[SecureKeyStore] Error handling init file: $e');
        }
      }

      final key = await _storage.read(key: _keyApiKey);
      return (key != null && key.trim().isNotEmpty) ? key.trim() : null;
    } catch (_) {
      return null;
    }
  }

  /// Save the Gemini API key to encrypted secure storage
  static Future<void> saveApiKey(String apiKey) async {
    await _storage.write(key: _keyApiKey, value: apiKey.trim());
  }

  /// Remove the API key
  static Future<void> deleteApiKey() async {
    await _storage.delete(key: _keyApiKey);
  }

  /// Check if an API key has been configured
  static Future<bool> hasApiKey() async {
    final key = await getApiKey();
    return key != null && key.isNotEmpty;
  }
}
