import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/audio/pcm_converter.dart';

void main() {
  group('PcmConverter Tests', () {
    test('pcmToWav prepends valid 44-byte RIFF/WAVE header', () {
      final fakePcm = Uint8List(48000); // 1 second of 24kHz 16-bit mono
      final wav = PcmConverter.pcmToWav(fakePcm, sampleRate: 24000);

      expect(wav.length, 44 + fakePcm.length);

      // Check "RIFF"
      expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');

      // Check "WAVE"
      expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');

      // Check "fmt "
      expect(String.fromCharCodes(wav.sublist(12, 16)), 'fmt ');

      // Check "data"
      expect(String.fromCharCodes(wav.sublist(36, 40)), 'data');
    });
  });
}
