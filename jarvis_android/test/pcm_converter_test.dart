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

    test('calculateRms handles empty and zero buffers correctly', () {
      expect(PcmConverter.calculateRms(Uint8List(0)), 0.0);
      expect(PcmConverter.calculateRms(Uint8List(1)), 0.0);

      final silencePcm = Uint8List(320); // 10ms of 16kHz 16-bit silence
      expect(PcmConverter.calculateRms(silencePcm), 0.0);
    });

    test('calculateRms computes accurate RMS for constant amplitude PCM samples', () {
      const sampleCount = 100;
      final pcm = Uint8List(sampleCount * 2);
      final byteData = ByteData.sublistView(pcm);
      const testAmplitude = 1000;
      for (int i = 0; i < sampleCount; i++) {
        byteData.setInt16(i * 2, testAmplitude, Endian.little);
      }

      final rms = PcmConverter.calculateRms(pcm);
      expect((rms - testAmplitude).abs() < 0.01, true);
    });

    test('calculateRms differentiates speaker acoustic echo bleed vs barge-in voice', () {
      const sampleCount = 640; // 40ms frame at 16kHz
      final echoBleedPcm = Uint8List(sampleCount * 2);
      final echoData = ByteData.sublistView(echoBleedPcm);
      // Residual speaker bleed (RMS ~800)
      for (int i = 0; i < sampleCount; i++) {
        echoData.setInt16(i * 2, (i % 2 == 0) ? 800 : -800, Endian.little);
      }
      final echoRms = PcmConverter.calculateRms(echoBleedPcm);
      expect(echoRms < 1800.0, true, reason: 'Speaker bleed should fall below barge-in threshold');

      final userVoicePcm = Uint8List(sampleCount * 2);
      final voiceData = ByteData.sublistView(userVoicePcm);
      // User speech right next to phone (RMS ~3500)
      for (int i = 0; i < sampleCount; i++) {
        voiceData.setInt16(i * 2, (i % 2 == 0) ? 3500 : -3500, Endian.little);
      }
      final voiceRms = PcmConverter.calculateRms(userVoicePcm);
      expect(voiceRms >= 1800.0, true, reason: 'User voice should exceed barge-in threshold');
    });
  });
}
