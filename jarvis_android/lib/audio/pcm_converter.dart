import 'dart:math' as math;
import 'dart:typed_data';

/// Utility to wrap raw PCM audio chunks into standard WAV format.
///
/// Gemini Live output is 24,000 Hz, 16-bit mono PCM.
/// Standard audio players on mobile require a standard WAV RIFF header
/// to decode and play raw PCM streams seamlessly.
class PcmConverter {
  /// Prepends a 44-byte RIFF/WAVE header to raw PCM bytes.
  static Uint8List pcmToWav(
    Uint8List pcmData, {
    int sampleRate = 24000,
    int numChannels = 1,
    int bitsPerSample = 16,
  }) {
    final byteRate = sampleRate * numChannels * (bitsPerSample ~/ 8);
    final blockAlign = numChannels * (bitsPerSample ~/ 8);
    final dataSize = pcmData.length;
    final chunkSize = 36 + dataSize;

    final header = ByteData(44);

    // "RIFF"
    header.setUint8(0, 0x52);
    header.setUint8(1, 0x49);
    header.setUint8(2, 0x46);
    header.setUint8(3, 0x46);
    header.setUint32(4, chunkSize, Endian.little);

    // "WAVE"
    header.setUint8(8, 0x57);
    header.setUint8(9, 0x41);
    header.setUint8(10, 0x56);
    header.setUint8(11, 0x45);

    // "fmt "
    header.setUint8(12, 0x66);
    header.setUint8(13, 0x6D);
    header.setUint8(14, 0x74);
    header.setUint8(15, 0x20);
    header.setUint32(16, 16, Endian.little); // Subchunk1Size (16 for PCM)
    header.setUint16(20, 1, Endian.little); // AudioFormat (1 for PCM)
    header.setUint16(22, numChannels, Endian.little);
    header.setUint32(24, sampleRate, Endian.little);
    header.setUint32(28, byteRate, Endian.little);
    header.setUint16(32, blockAlign, Endian.little);
    header.setUint16(34, bitsPerSample, Endian.little);

    // "data"
    header.setUint8(36, 0x64);
    header.setUint8(37, 0x61);
    header.setUint8(38, 0x74);
    header.setUint8(39, 0x61);
    header.setUint32(40, dataSize, Endian.little);

    final wavBytes = Uint8List(44 + dataSize);
    wavBytes.setRange(0, 44, header.buffer.asUint8List());
    wavBytes.setRange(44, 44 + dataSize, pcmData);

    return wavBytes;
  }

  /// Computes Root Mean Square (RMS) energy level of 16-bit little-endian PCM audio.
  /// Used for Voice Activity Detection (VAD), barge-in speech detection, and echo differentiation.
  static double calculateRms(Uint8List pcmData) {
    if (pcmData.isEmpty) return 0.0;
    final sampleCount = pcmData.length ~/ 2;
    if (sampleCount == 0) return 0.0;

    double sumSquares = 0.0;
    final byteData = ByteData.sublistView(pcmData);
    for (int i = 0; i < sampleCount; i++) {
      final sample = byteData.getInt16(i * 2, Endian.little);
      sumSquares += sample * sample;
    }
    return math.sqrt(sumSquares / sampleCount);
  }
}
