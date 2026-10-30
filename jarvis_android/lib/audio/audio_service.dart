import 'dart:async';
import 'dart:typed_data';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:record/record.dart';
import 'pcm_converter.dart';

/// Handles microphone recording (16kHz PCM) and audio output playback (24kHz PCM).
/// Designed with clean separation to easily support barge-in and future streaming improvements.
class AudioService {
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();

  StreamSubscription<Uint8List>? _recordSub;
  bool _isRecording = false;
  bool _isPlaying = false;

  // Buffer for accumulating PCM output chunks from Gemini Live
  final BytesBuilder _outputBuffer = BytesBuilder(copy: false);

  // Callbacks
  void Function(Uint8List chunk)? onAudioChunkRecorded;
  void Function(bool isPlaying)? onPlaybackStateChanged;

  bool get isRecording => _isRecording;
  bool get isPlaying => _isPlaying;

  AudioService() {
    _player.onPlayerStateChanged.listen((state) {
      final playing = state == PlayerState.playing;
      if (_isPlaying != playing) {
        _isPlaying = playing;
        onPlaybackStateChanged?.call(_isPlaying);
      }
    });

    _player.onPlayerComplete.listen((_) {
      _isPlaying = false;
      onPlaybackStateChanged?.call(false);
    });
  }

  /// Start recording 16kHz 16-bit mono PCM stream from microphone
  Future<bool> startRecording() async {
    try {
      if (_isRecording) return true;

      // Stop any existing playback on new speech (barge-in behavior)
      await stopPlayback();

      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        debugPrint('[AudioService] Microphone permission not granted');
        return false;
      }

      const config = RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
      );

      final stream = await _recorder.startStream(config);
      _isRecording = true;

      _recordSub = stream.listen((chunk) {
        if (_isRecording && onAudioChunkRecorded != null) {
          onAudioChunkRecorded!(chunk);
        }
      }, onError: (err) {
        debugPrint('[AudioService] Record stream error: $err');
      });

      return true;
    } catch (e) {
      debugPrint('[AudioService] Failed to start recording: $e');
      _isRecording = false;
      return false;
    }
  }

  /// Stop recording stream
  Future<void> stopRecording() async {
    if (!_isRecording) return;
    try {
      _isRecording = false;
      await _recordSub?.cancel();
      _recordSub = null;
      await _recorder.stop();
    } catch (e) {
      debugPrint('[AudioService] Error stopping recording: $e');
    }
  }

  /// Append incoming 24kHz raw PCM chunk from Gemini Live
  void appendIncomingPcmChunk(Uint8List chunk) {
    _outputBuffer.add(chunk);
  }

  /// Play all accumulated PCM audio chunks as a single WAV stream
  Future<void> playAccumulatedAudio() async {
    final pcmBytes = _outputBuffer.takeBytes();
    if (pcmBytes.isEmpty) return;

    try {
      final wavBytes = PcmConverter.pcmToWav(
        pcmBytes,
        sampleRate: 24000,
        numChannels: 1,
        bitsPerSample: 16,
      );

      await _player.stop();
      _isPlaying = true;
      onPlaybackStateChanged?.call(true);

      await _player.play(BytesSource(wavBytes));
    } catch (e) {
      debugPrint('[AudioService] Audio playback error: $e');
      _isPlaying = false;
      onPlaybackStateChanged?.call(false);
    }
  }

  /// Stop playback immediately and clear any buffered audio chunks (Barge-in / Interrupted)
  Future<void> stopPlayback() async {
    _outputBuffer.clear();
    if (_isPlaying) {
      try {
        await _player.stop();
      } catch (e) {
        debugPrint('[AudioService] Error stopping player: $e');
      }
      _isPlaying = false;
      onPlaybackStateChanged?.call(false);
    }
  }

  /// Dispose resources
  Future<void> dispose() async {
    await stopRecording();
    await stopPlayback();
    await _recorder.dispose();
    await _player.dispose();
  }
}
