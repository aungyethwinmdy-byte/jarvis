import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/audio/audio_service.dart';
import 'package:jarvis_android/audio/wake_word_service.dart';
import 'package:jarvis_android/live/live_client.dart';
import 'package:jarvis_android/memory/app_prefs.dart';
import 'package:jarvis_android/memory/memory_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class FakeAudioService extends AudioService {
  bool recordStarted = false;
  bool recordStopped = false;
  bool playbackStopped = false;
  int recordedStopPlaybackGen = -1;
  int playAccumulatedAudioCallCount = 0;
  bool simulatePlaying = false;
  int simulatedBufferLength = 0;

  FakeAudioService() : super(isTestMode: true);

  @override
  bool get isPlaying => simulatePlaying;

  @override
  int get outputBufferLength => simulatedBufferLength;

  @override
  Future<bool> startRecording({
    bool stopActivePlayback = true,
    bool forceRestart = false,
  }) async {
    recordStarted = true;
    return true;
  }

  @override
  Future<bool> restartRecording({bool stopActivePlayback = false}) async {
    await stopRecording();
    return await startRecording(
      stopActivePlayback: stopActivePlayback,
      forceRestart: true,
    );
  }

  @override
  Future<void> stopRecording() async {
    recordStopped = true;
  }

  @override
  Future<void> stopPlayback({int? forGeneration}) async {
    playbackStopped = true;
    simulatePlaying = false;
    if (forGeneration != null) {
      recordedStopPlaybackGen = forGeneration;
    }
  }

  @override
  Future<void> playAccumulatedAudio() async {
    playAccumulatedAudioCallCount++;
    simulatePlaying = true;
    onPlaybackStateChanged?.call(true);
  }
}

class FakeWakeWordService extends WakeWordService {
  @override
  Future<bool> initialize() async {
    return true;
  }
}

class FakeWebSocketSink implements WebSocketSink {
  final List<dynamic> sentMessages = [];
  bool isClosed = false;

  @override
  void add(dynamic data) {
    sentMessages.add(data);
  }

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future addStream(Stream stream) async {}

  @override
  Future close([int? closeCode, String? closeReason]) async {
    isClosed = true;
  }

  @override
  Future get done => Future.value();

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class FakeWebSocketChannel implements WebSocketChannel {
  final StreamController _controller = StreamController.broadcast();
  final FakeWebSocketSink _sink = FakeWebSocketSink();

  @override
  Stream get stream => _controller.stream;

  @override
  WebSocketSink get sink => _sink;

  @override
  int? get closeCode => null;

  @override
  String? get closeReason => null;

  @override
  String? get protocol => null;

  @override
  Future<void> get ready => Future.value();

  void emit(dynamic data) {
    _controller.add(data);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late FakeAudioService fakeAudio;
  late MemoryService memoryService;
  late LiveClient liveClient;
  late FakeWebSocketChannel fakeChannel;

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'hands_free_enabled': true,
      'wake_word_enabled': true,
      'wake_word_threshold': 0.15,
    });
    fakeAudio = FakeAudioService();
    memoryService = MemoryService();
    liveClient = LiveClient(
      audioService: fakeAudio,
      memoryService: memoryService,
      wakeWordService: FakeWakeWordService(),
    );
    fakeChannel = FakeWebSocketChannel();
    liveClient.attachChannelForTesting(fakeChannel);
  });

  group('LiveClient Barge-in and Turn Management Tests', () {
    test('PTT အလွတ်နှိပ်ရင် audioStreamEnd မပို့ဘဲ cancel ဖြစ်သည်', () async {
      await AppPrefs.setHandsFreeEnabled(false);
      liveClient.setStateForTesting(LiveSessionState.connected, 'အဆင်သင့်ရှိပါသည်');

      // User presses down
      await liveClient.startTalking();
      expect(liveClient.state, LiveSessionState.listening);

      // User releases without any chunk streamed
      await liveClient.stopTalking();

      // Verify no audioStreamEnd was dispatched to WebSocket
      final hasAudioStreamEnd = fakeChannel._sink.sentMessages.any(
        (msg) => msg.toString().contains('audioStreamEnd'),
      );
      expect(hasAudioStreamEnd, false, reason: 'Empty PTT tap must NOT send audioStreamEnd');
      expect(liveClient.state, LiveSessionState.connected);

      // Now test with at least one chunk streamed
      await liveClient.startTalking();
      expect(liveClient.state, LiveSessionState.listening);
      liveClient.simulatePcmChunkForTesting(Uint8List(320)); // Streams 1 chunk
      await liveClient.stopTalking();

      final hasAudioStreamEndNow = fakeChannel._sink.sentMessages.any(
        (msg) => msg.toString().contains('audioStreamEnd'),
      );
      expect(hasAudioStreamEndNow, true, reason: 'Valid PTT with speech must send audioStreamEnd');
      expect(liveClient.state, LiveSessionState.thinking);
    });

    test('speaking timeout fallback test: playback end မရောက်ရင် fallback ဖြင့် listening သို့ ပြန်လည်ရောက်ရှိသည်', () async {
      await AppPrefs.setHandsFreeEnabled(true);
      liveClient.setInitialGreetingDoneForTesting(true);
      liveClient.setStateForTesting(LiveSessionState.speaking, 'ပြောနေပါသည်...');
      liveClient.setPlaybackGenerationForTesting(42);

      // Trigger fallback timeout directly
      await liveClient.handlePlaybackCompletedForTesting(
        generation: 42,
        reason: 'speaking_fallback_timeout',
      );

      expect(liveClient.state, LiveSessionState.listening);
      expect(liveClient.statusMessage, 'နားထောင်နေပါသည်...');
      expect(liveClient.lastHandledPlaybackGeneration, 42);
      expect(fakeAudio.recordStarted, true);
    });

    test('playback end callback လွဲရင် _handlePlaybackCompleted တစ်ခါတည်းသာ အလုပ်လုပ်သည် (Double completion guard)', () async {
      await AppPrefs.setHandsFreeEnabled(true);
      liveClient.setInitialGreetingDoneForTesting(true);
      liveClient.setStateForTesting(LiveSessionState.speaking, 'ပြောနေပါသည်...');
      liveClient.setPlaybackGenerationForTesting(7);

      // First completion call (e.g. from fallback timer)
      await liveClient.handlePlaybackCompletedForTesting(generation: 7, reason: 'first');
      expect(liveClient.lastHandledPlaybackGeneration, 7);
      expect(liveClient.state, LiveSessionState.listening);

      // Change state manually to verify second call is ignored
      liveClient.setStateForTesting(LiveSessionState.thinking, 'စဉ်းစားနေပါသည်...');

      // Duplicate callback for the same generation (e.g. late player callback)
      await liveClient.handlePlaybackCompletedForTesting(generation: 7, reason: 'duplicate');

      // State remains thinking because gen 7 was already handled
      expect(liveClient.state, LiveSessionState.thinking);
    });

    test('playback generation guard: stale generation stopPlayback မလုပ်ဆောင်စေရ', () async {
      final audio = AudioService(isTestMode: true);
      audio.setPlaybackGenerationForTesting(5);
      audio.setPlayingForTesting(true);

      // Try stopping for generation 3 (stale)
      await audio.stopPlayback(forGeneration: 3);
      expect(audio.isPlaying, true, reason: 'Stale generation must not stop playback');

      // Stop for correct generation 5
      await audio.stopPlayback(forGeneration: 5);
      expect(audio.isPlaying, false, reason: 'Matching generation must stop playback');
    });
  });
}
