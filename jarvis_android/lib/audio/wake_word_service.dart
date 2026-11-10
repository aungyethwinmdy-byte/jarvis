import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:open_wake_word/open_wake_word.dart';

/// On-Device Wake Word Engine using openWakeWord (Hey Jarvis model).
/// Processes 16kHz PCM audio completely locally with ZERO internet/cloud transmission.
class WakeWordService {
  bool _isInitialized = false;
  bool _isListening = false;
  double _lastProbability = 0.0;
  double threshold = 0.15; // Tuned for natural voice pickup across varied accents
  Timer? _pollTimer;

  // Buffer to accumulate raw PCM bytes into 1280-sample (2560 bytes) chunks
  final List<int> _audioBuffer = [];

  // Callback when "Hey Jarvis" is triggered
  VoidCallback? onWakeWordDetected;

  bool get isInitialized => _isInitialized;
  bool get isListening => _isListening;
  double get lastProbability => _lastProbability;

  /// Initialize openWakeWord ONNX pipeline with bundled assets
  Future<bool> initialize() async {
    if (_isInitialized) return true;

    try {
      debugPrint('[WakeWordService] Initializing openWakeWord models...');
      final ok = await OpenWakeWord.init(
        melModelAssetPath: 'assets/models/melspectrogram.onnx',
        embModelAssetPath: 'assets/models/embedding_model.onnx',
        wwModelAssetPaths: ['assets/models/hey_jarvis.onnx'],
      );

      _isInitialized = ok;
      debugPrint('[WakeWordService] Initialization result: $ok (threshold: $threshold)');
      return ok;
    } catch (e) {
      debugPrint('[WakeWordService] Initialization error: $e');
      _isInitialized = false;
      return false;
    }
  }

  /// Start listening for "Hey Jarvis"
  void start() {
    _audioBuffer.clear();
    _isListening = true;
    _lastProbability = 0.0;
    debugPrint('[WakeWordService] Started listening for "Hey Jarvis" (threshold: $threshold)');

    // Background polling timer: C++ worker threads run asynchronously;
    // polling ensures predictions are immediately captured as soon as ONNX finishes.
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(milliseconds: 30), (_) {
      if (!_isListening || !_isInitialized) return;
      final prob = OpenWakeWord.getProbability();
      if (prob > 0.0) {
        _lastProbability = prob;
        if (prob >= 0.08) {
          debugPrint(
            '[WakeWordService] Wake word probability: ${prob.toStringAsFixed(3)}',
          );
        }
        if (prob >= threshold || OpenWakeWord.isActivated()) {
          debugPrint(
            '[WakeWordService] *** "Hey Jarvis" DETECTED! (prob: ${prob.toStringAsFixed(3)}, threshold: $threshold) ***',
          );
          stop();
          onWakeWordDetected?.call();
        }
      }
    });
  }

  /// Stop listening for wake word
  void stop() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _isListening = false;
    _audioBuffer.clear();
    debugPrint('[WakeWordService] Stopped listening for wake word');
  }

  /// Process incoming 16kHz 16-bit mono PCM chunk from microphone
  void processPcmChunk(Uint8List chunk) {
    if (!_isInitialized || !_isListening) return;

    _audioBuffer.addAll(chunk);

    // openWakeWord operates on 1280 samples = 2560 bytes (16-bit mono PCM)
    const chunkSize = 2560;
    while (_audioBuffer.length >= chunkSize && _isListening) {
      final sampleBytes = Uint8List.fromList(_audioBuffer.sublist(0, chunkSize));
      _audioBuffer.removeRange(0, chunkSize);

      // Convert little-endian 16-bit PCM bytes to Int16List safely
      const sampleCount = chunkSize ~/ 2;
      final int16Samples = Int16List(sampleCount);
      final byteData = ByteData.sublistView(sampleBytes);
      for (int i = 0; i < sampleCount; i++) {
        int16Samples[i] = byteData.getInt16(i * 2, Endian.little);
      }

      OpenWakeWord.processAudio(int16Samples);
      final prob = OpenWakeWord.getProbability();
      if (prob > 0.0) {
        _lastProbability = prob;
        if (prob >= 0.08) {
          debugPrint(
            '[WakeWordService] Wake word probability: ${prob.toStringAsFixed(3)}',
          );
        }

        if (prob >= threshold || OpenWakeWord.isActivated()) {
          debugPrint(
            '[WakeWordService] *** "Hey Jarvis" DETECTED! (prob: ${prob.toStringAsFixed(3)}, threshold: $threshold) ***',
          );
          stop(); // Pause wake word listening while conversation is active
          onWakeWordDetected?.call();
          break;
        }
      }
    }
  }

  /// Free native engine resources
  void dispose() {
    stop();
    if (_isInitialized) {
      try {
        OpenWakeWord.destroy();
      } catch (_) {}
      _isInitialized = false;
    }
  }
}
