import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:record/record.dart';
import '../tools/device_channel.dart';
import 'pcm_converter.dart';

/// Handles microphone recording (16kHz PCM) and audio output playback (24kHz PCM).
/// Designed with clean separation to easily support barge-in and future streaming improvements.
class AudioService {
  static AudioService? _instance;
  static AudioService? get instance => _instance;

  final AudioRecorder? _recorder;
  final AudioPlayer? _player;

  StreamSubscription<Uint8List>? _recordSub;
  bool _isRecording = false;
  bool _isPlaying = false;
  int _playbackGeneration = 0;
  bool _isStartingPlayback = false;

  // Buffer for accumulating PCM output chunks from Gemini Live
  final BytesBuilder _outputBuffer = BytesBuilder(copy: false);

  // Buffer for on-demand user voice recording ("recoder ဖွင့်ပြီးအသံဖမ်းပေးပါ")
  bool _isUserRecording = false;
  final BytesBuilder _userRecordingBuffer = BytesBuilder(copy: false);
  DateTime? _userRecordingStartTime;
  String? _lastRecordedFilePath;

  // Callbacks
  void Function(Uint8List chunk)? onAudioChunkRecorded;
  void Function(bool isPlaying)? onPlaybackStateChanged;

  bool get isRecording => _isRecording;
  bool get isPlaying => _isPlaying;
  bool get isUserRecording => _isUserRecording;
  String? get lastRecordedFilePath => _lastRecordedFilePath;
  bool get hasAudioToPlay => _outputBuffer.isNotEmpty;
  int get outputBufferLength => _outputBuffer.length;
  int get playbackGeneration => _playbackGeneration;

  AudioService({
    AudioRecorder? recorder,
    AudioPlayer? player,
    bool isTestMode = false,
  })  : _recorder = isTestMode ? null : (recorder ?? AudioRecorder()),
        _player = isTestMode ? null : (player ?? AudioPlayer()) {
    _instance = this;
    final activePlayer = _player;
    if (!isTestMode && activePlayer != null) {
      activePlayer.setAudioContext(
        AudioContext(
          android: const AudioContextAndroid(
            isSpeakerphoneOn: true,
            stayAwake: true,
            contentType: AndroidContentType.speech,
            usageType: AndroidUsageType.media,
            audioFocus: AndroidAudioFocus.none, // Do not steal audio focus from microphone recorder
            audioMode: AndroidAudioMode.normal,
          ),
          iOS: AudioContextIOS(
            category: AVAudioSessionCategory.playAndRecord,
            options: const {
              AVAudioSessionOptions.defaultToSpeaker,
              AVAudioSessionOptions.allowBluetooth,
            },
          ),
        ),
      ).catchError((e) {
        debugPrint('[AudioService] setAudioContext error: $e');
      });

      activePlayer.onPlayerStateChanged.listen((state) {
        if (_isStartingPlayback) return;
        final playing = state == PlayerState.playing;
        if (_isPlaying != playing) {
          _isPlaying = playing;
          debugPrint(
            '[AudioService] onPlayerStateChanged: state=$state -> isPlaying=$_isPlaying (gen: $_playbackGeneration)',
          );
          onPlaybackStateChanged?.call(_isPlaying);
        }
      });

      activePlayer.onPlayerComplete.listen((_) {
        if (_isStartingPlayback) return;
        if (_isPlaying) {
          _isPlaying = false;
          debugPrint(
            '[AudioService] onPlayerComplete: isPlaying=false (gen: $_playbackGeneration)',
          );
          onPlaybackStateChanged?.call(false);
        }
      });
    }
  }

  /// Start recording 16kHz 16-bit mono PCM stream from microphone
  Future<bool> startRecording({
    bool stopActivePlayback = true,
    bool forceRestart = false,
  }) async {
    try {
      if (_isRecording && !forceRestart && _recordSub != null) return true;
      if (_isRecording) {
        await stopRecording();
      }

      // Stop any existing playback on new speech (barge-in behavior)
      if (stopActivePlayback) {
        await stopPlayback();
      }

      final recorder = _recorder;
      if (recorder == null) {
        _isRecording = true;
        return true;
      }

      final hasPermission = await recorder.hasPermission();
      if (!hasPermission) {
        debugPrint('[AudioService] Microphone permission not granted');
        return false;
      }

      const config = RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
        echoCancel: true,
        noiseSuppress: true,
        androidConfig: AndroidRecordConfig(
          audioSource: AndroidAudioSource.mic,
          audioManagerMode: AudioManagerMode.modeNormal,
          speakerphone: false,
        ),
      );

      int attempt = 0;
      const maxAttempts = 3;
      while (attempt < maxAttempts) {
        attempt++;
        try {
          final stream = await recorder.startStream(config);
          _isRecording = true;
          debugPrint(
            '[AudioService] Recording started (attempt $attempt, 16kHz PCM mono, echoCancel: true, noiseSuppress: true, audioSource: mic, modeNormal)',
          );

          _recordSub = stream.listen((chunk) {
            if (_isUserRecording) {
              _userRecordingBuffer.add(chunk);
            }
            if (_isRecording && onAudioChunkRecorded != null) {
              if (_isPlaying) {
                final rms = PcmConverter.calculateRms(chunk);
                debugPrint(
                  '[AudioService] Playback active - mic chunk received: len=${chunk.length}, rms=${rms.toStringAsFixed(1)}, isRecording=$_isRecording, isPlaying=$_isPlaying',
                );
              }
              onAudioChunkRecorded!(chunk);
            }
          }, onError: (err) {
            debugPrint('[AudioService] Record stream error: $err');
          });

          return true;
        } catch (e) {
          debugPrint('[AudioService] Recording attempt $attempt failed: $e');
          if (attempt < maxAttempts) {
            await Future.delayed(const Duration(milliseconds: 250));
          } else {
            rethrow;
          }
        }
      }
      return false;
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
      await _recorder?.stop();
      debugPrint('[AudioService] Recording stopped');
    } catch (e) {
      debugPrint('[AudioService] Error stopping recording: $e');
    }
  }

  /// Cleanly restarts microphone recording to prevent stalled native streams.
  Future<bool> restartRecording({bool stopActivePlayback = false}) async {
    await stopRecording();
    return await startRecording(
      stopActivePlayback: stopActivePlayback,
      forceRestart: true,
    );
  }

  /// Append incoming 24kHz raw PCM chunk from Gemini Live
  void appendIncomingPcmChunk(Uint8List chunk) {
    _outputBuffer.add(chunk);
  }

  /// Discard all incoming audio chunks buffered for playback
  void clearIncomingBuffer() {
    _outputBuffer.clear();
  }

  /// Play all accumulated PCM audio chunks as a single WAV stream
  Future<void> playAccumulatedAudio() async {
    final pcmBytes = _outputBuffer.takeBytes();
    if (pcmBytes.isEmpty) return;

    _playbackGeneration++;
    final currentGen = _playbackGeneration;
    _isStartingPlayback = true;

    try {
      final player = _player;
      if (player == null) {
        _isPlaying = true;
        _isStartingPlayback = false;
        onPlaybackStateChanged?.call(true);
        return;
      }

      final wavBytes = PcmConverter.pcmToWav(
        pcmBytes,
        sampleRate: 24000,
        numChannels: 1,
        bitsPerSample: 16,
      );

      await player.stop();
      await player.setVolume(1.0);
      _isPlaying = true;
      _isStartingPlayback = false;
      debugPrint(
        '[AudioService] Playback started: gen=$currentGen, wavBytes=${wavBytes.length}',
      );
      onPlaybackStateChanged?.call(true);

      await player.play(BytesSource(wavBytes));
    } catch (e) {
      debugPrint('[AudioService] Audio playback error: $e');
      _isStartingPlayback = false;
      _isPlaying = false;
      onPlaybackStateChanged?.call(false);
    }
  }

  /// Stop playback immediately and clear any buffered audio chunks (Barge-in / Interrupted)
  Future<void> stopPlayback({int? forGeneration}) async {
    if (forGeneration != null && forGeneration != _playbackGeneration) {
      debugPrint(
        '[AudioService] stopPlayback ignored: requested gen $forGeneration != current gen $_playbackGeneration',
      );
      return;
    }
    _outputBuffer.clear();
    if (_isPlaying) {
      _isPlaying = false;
      try {
        await _player?.stop();
      } catch (e) {
        debugPrint('[AudioService] Error stopping player: $e');
      }
      debugPrint('[AudioService] Playback stopped: gen=$_playbackGeneration');
      onPlaybackStateChanged?.call(false);
    }
  }

  /// Set playing state for tests
  @visibleForTesting
  void setPlayingForTesting(bool playing) {
    _isPlaying = playing;
  }

  /// Set generation for tests
  @visibleForTesting
  void setPlaybackGenerationForTesting(int gen) {
    _playbackGeneration = gen;
  }

  /// Start on-demand user voice recording.
  Future<String> startUserRecording() async {
    if (_isUserRecording) {
      return "လက်ရှိတွင် အသံဖမ်းယူမှု စတင်နေဆဲ ဖြစ်ပါသည် ဆရာ။";
    }

    try {
      _userRecordingBuffer.clear();
      _userRecordingStartTime = DateTime.now();
      _isUserRecording = true;

      // Ensure mic stream is active
      if (!_isRecording) {
        final ok = await startRecording(stopActivePlayback: false);
        if (!ok) {
          _isUserRecording = false;
          return "မိုက်ခရိုဖုန်း အသုံးပြုခွင့် မရရှိသဖြင့် အသံဖမ်းယူ၍ မရပါ ခင်ဗျာ။";
        }
      }

      debugPrint('[AudioService] User voice recording started successfully');
      return "အသံဖမ်းယူခြင်းကို စတင်ပေးလိုက်ပါပြီ ခင်ဗျာ။ ရပ်တန့်လိုပါက 'အသံဖမ်းတာ ရပ်ပေးပါ' သို့မဟုတ် 'ပိတ်ပေးပါ' ဟု အမိန့်ပေးနိုင်ပါသည် ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[AudioService] startUserRecording error: $e');
      _isUserRecording = false;
      return "အသံဖမ်းယူခြင်း စတင်ရာတွင် အခက်အခဲရှိပါသည်: $e";
    }
  }

  /// Stop on-demand user voice recording and save as standard WAV file.
  Future<String> stopUserRecording() async {
    if (!_isUserRecording) {
      return "လက်ရှိတွင် အသံဖမ်းယူနေခြင်း မရှိပါ ခင်ဗျာ။";
    }

    try {
      _isUserRecording = false;
      final duration = _userRecordingStartTime != null
          ? DateTime.now().difference(_userRecordingStartTime!).inSeconds.clamp(1, 86400)
          : 1;

      final pcmBytes = _userRecordingBuffer.takeBytes();
      final wavBytes = PcmConverter.pcmToWav(
        pcmBytes,
        sampleRate: 16000,
        numChannels: 1,
        bitsPerSample: 16,
      );

      // Locate appropriate storage directory for recordings
      Directory? targetDir;
      final candidates = [
        Directory('/sdcard/Music/JarvisRecordings'),
        Directory('/storage/emulated/0/Music/JarvisRecordings'),
        Directory('/sdcard/Download/JarvisRecordings'),
        Directory('${Directory.systemTemp.path}/JarvisRecordings'),
      ];

      for (final cand in candidates) {
        try {
          if (!cand.existsSync()) {
            cand.createSync(recursive: true);
          }
          targetDir = cand;
          break;
        } catch (_) {
          continue;
        }
      }

      targetDir ??= Directory.systemTemp;

      final now = DateTime.now();
      final ts = '${now.year}${now.month.toString().padLeft(2, '0')}${now.day.toString().padLeft(2, '0')}_${now.hour.toString().padLeft(2, '0')}${now.minute.toString().padLeft(2, '0')}${now.second.toString().padLeft(2, '0')}';
      final file = File('${targetDir.path}/JARVIS_REC_$ts.wav');

      await file.writeAsBytes(wavBytes, flush: true);
      _lastRecordedFilePath = file.path;
      debugPrint('[AudioService] User voice recording saved: ${file.path} (${wavBytes.length} bytes, duration: $duration s)');

      // Register file with Android MediaStore
      await DeviceChannel.scanMediaFile(file.path);

      return "အသံဖမ်းယူခြင်းကို ရပ်တန့်ပြီး ဖိုင်အဖြစ် သိမ်းဆည်းပေးလိုက်ပါပြီ ခင်ဗျာ (ကြာချိန် $duration စက္ကန့်၊ ဖိုင်အမည်: JARVIS_REC_$ts.wav)။";
    } catch (e) {
      debugPrint('[AudioService] stopUserRecording error: $e');
      return "အသံဖမ်းယူမှု သိမ်းဆည်းရာတွင် အခက်အခဲရှိပါသည်: $e";
    }
  }

  /// Dispatch start/stop action for user voice recording.
  Future<String> manageUserRecording(String action) async {
    final act = action.trim().toLowerCase();
    if (act == 'start' || act == 'record' || act.contains('စတင်') || act.contains('ဖွင့်')) {
      return await startUserRecording();
    } else if (act == 'stop' || act == 'finish' || act == 'end' || act.contains('ရပ်') || act.contains('ပိတ်')) {
      return await stopUserRecording();
    } else {
      if (_isUserRecording) {
        return await stopUserRecording();
      } else {
        return await startUserRecording();
      }
    }
  }

  /// Dispose resources
  Future<void> dispose() async {
    await stopRecording();
    await stopPlayback();
    await _recorder?.dispose();
    await _player?.dispose();
  }
}
