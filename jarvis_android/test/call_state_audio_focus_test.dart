import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/audio/audio_service.dart';
import 'package:jarvis_android/audio/wake_word_service.dart';
import 'package:jarvis_android/live/live_client.dart';
import 'package:jarvis_android/memory/memory_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class MockAudioService extends AudioService {
  bool recordStarted = false;
  bool recordStopped = false;
  bool playbackStopped = false;
  int recordedStopPlaybackGen = -1;
  int playAccumulatedAudioCallCount = 0;
  bool simulatePlaying = false;
  int simulatedBufferLength = 0;

  MockAudioService() : super(isTestMode: true);

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
    recordStopped = false;
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
    recordStarted = false;
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

class MockWakeWordService extends WakeWordService {
  bool isStarted = false;
  bool isStopped = false;

  @override
  bool get isInitialized => true;

  @override
  Future<bool> initialize() async => true;

  @override
  void start() {
    isStarted = true;
    isStopped = false;
  }

  @override
  void stop() {
    isStopped = true;
    isStarted = false;
  }
}

class MockWebSocketSink implements WebSocketSink {
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

class MockWebSocketChannel implements WebSocketChannel {
  final StreamController _controller = StreamController.broadcast();
  final MockWebSocketSink _sink = MockWebSocketSink();

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

  late MockAudioService mockAudio;
  late MemoryService memoryService;
  late MockWakeWordService mockWakeWord;
  late LiveClient liveClient;
  late MockWebSocketChannel mockChannel;

  setUp(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('flutter_foreground_task/methods'),
      (MethodCall methodCall) async {
        if (methodCall.method == 'isRunningService') return true;
        if (methodCall.method == 'startService') return true;
        if (methodCall.method == 'stopService') return true;
        return null;
      },
    );

    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('com.jarvis.android/device_control'),
      (MethodCall methodCall) async {
        return {'state': 'IDLE', 'granted': true, 'success': true};
      },
    );

    SharedPreferences.setMockInitialValues({
      'hands_free_enabled': false,
      'wake_word_enabled': true,
      'wake_word_threshold': 0.15,
    });
    mockAudio = MockAudioService();
    memoryService = MemoryService();
    mockWakeWord = MockWakeWordService();
    liveClient = LiveClient(
      audioService: mockAudio,
      memoryService: memoryService,
      wakeWordService: mockWakeWord,
    );

    mockChannel = MockWebSocketChannel();
    liveClient.attachChannelForTesting(mockChannel);
  });

  tearDown(() {
    liveClient.dispose();
  });

  group('Phone Call Interruption & Recovery Tests', () {
    test('1. Incoming phone call while IDLE pauses mic, stops wake word and silences Jarvis', () async {
      // Setup: LiveClient in listeningWakeWord mode
      liveClient.setStateForTesting(
        LiveSessionState.listeningWakeWord,
        'အသင့်ရှိပါသည် ("Hey Jarvis" ဟုခေါ်ပါ)',
      );
      mockAudio.recordStarted = true;
      mockAudio.recordStopped = false;

      // Phone call starts (RINGING)
      await liveClient.handlePhoneCallStateChanged('RINGING');

      expect(liveClient.isPhoneCallActive, isTrue);
      expect(mockAudio.recordStopped, isTrue);
      expect(mockWakeWord.isStopped, isTrue);
      expect(liveClient.state, equals(LiveSessionState.connected));
      expect(liveClient.statusMessage, contains('ဖုန်းခေါ်ဆိုမှု ရှိနေပါသည်'));

      // While call is active, PTT startTalking should be ignored
      await liveClient.startTalking();
      expect(liveClient.state, equals(LiveSessionState.connected));

      // Mic chunks arriving during phone call are dropped
      liveClient.simulatePcmChunkForTesting(Uint8List(320));
      expect(mockChannel._sink.sentMessages.isEmpty, isTrue);

      // Phone call transitions to OFFHOOK (user answers call)
      await liveClient.handlePhoneCallStateChanged('OFFHOOK');
      expect(liveClient.isPhoneCallActive, isTrue);
      expect(mockAudio.recordStopped, isTrue);

      // Phone call ends (IDLE)
      await liveClient.handlePhoneCallStateChanged('IDLE');

      expect(liveClient.isPhoneCallActive, isFalse);
      // Silently resumes wake mode without speaking auto greeting
      expect(liveClient.state, equals(LiveSessionState.listeningWakeWord));
      expect(mockWakeWord.isStarted, isTrue);
      expect(mockAudio.recordStarted, isTrue);

      // Verify no greeting audio was played
      expect(mockAudio.playAccumulatedAudioCallCount, equals(0));
    });

    test('2. Incoming phone call while in active Live conversation (speaking) immediately halts playback & abandons turn', () async {
      // Setup: LiveClient is speaking
      liveClient.setStateForTesting(LiveSessionState.speaking, 'ပြောနေပါသည်...');
      mockAudio.simulatePlaying = true;
      liveClient.setPlaybackGenerationForTesting(5);

      // Phone call arrives (RINGING)
      await liveClient.handlePhoneCallStateChanged('RINGING');

      expect(liveClient.isPhoneCallActive, isTrue);
      expect(mockAudio.playbackStopped, isTrue);
      expect(mockAudio.isPlaying, isFalse);
      expect(mockAudio.recordStopped, isTrue);
      expect(liveClient.state, equals(LiveSessionState.connected));

      // Phone call ends (IDLE)
      await liveClient.handlePhoneCallStateChanged('IDLE');

      expect(liveClient.isPhoneCallActive, isFalse);
      expect(liveClient.state, equals(LiveSessionState.listeningWakeWord));
      // Returned silently to wake mode without speaking greeting
      expect(mockAudio.playAccumulatedAudioCallCount, equals(0));
    });

    test('3. AudioFocus LOSS stops playback/mic and GAIN restores wake mode', () async {
      liveClient.setStateForTesting(LiveSessionState.speaking, 'ပြောနေပါသည်...');
      mockAudio.simulatePlaying = true;

      // Transient focus loss (e.g. navigation or phone ringing)
      await liveClient.handleAudioFocusChanged('LOSS_TRANSIENT');

      expect(liveClient.isAudioFocusLost, isTrue);
      expect(mockAudio.playbackStopped, isTrue);
      expect(mockAudio.recordStopped, isTrue);

      // Audio focus restored
      await liveClient.handleAudioFocusChanged('GAIN');

      expect(liveClient.isAudioFocusLost, isFalse);
      expect(liveClient.state, equals(LiveSessionState.listeningWakeWord));
    });

    test('4. Socket reconnect after call suppresses auto-greeting when setupComplete arrives', () async {
      // Simulate socket dead during call
      liveClient.attachChannelForTesting(mockChannel);
      liveClient.setPhoneCallActiveForTesting(true);

      // Simulate channel emitting setupComplete when suppressGreetingOnNextConnect is true
      liveClient.setSuppressGreetingOnNextConnectForTesting(true);

      final setupCompleteJson = jsonEncode({'setupComplete': {}});
      mockChannel.emit(setupCompleteJson);

      await Future.delayed(const Duration(milliseconds: 50));

      // Verify startup greeting was NOT triggered (clientContent not sent)
      final greetingTurn = mockChannel._sink.sentMessages.where((msg) {
        if (msg is String && msg.contains('clientContent')) {
          return true;
        }
        return false;
      }).toList();

      expect(greetingTurn.isEmpty, isTrue);
      // Suppress flag cleared
      expect(liveClient.suppressGreetingOnNextConnectForTesting, isFalse);
    });
  });
}
