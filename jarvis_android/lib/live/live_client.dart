import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../audio/audio_service.dart';
import '../audio/background_service.dart';
import '../audio/pcm_converter.dart';
import '../audio/wake_word_service.dart';
import '../knowledge/knowledge_service.dart';
import '../memory/app_prefs.dart';
import '../memory/memory_service.dart';
import '../memory/secure_key_store.dart';
import '../tools/app_launcher_tool.dart';
import '../tools/audio_recorder_tool.dart';
import '../tools/base_tool.dart';
import '../tools/camera_capture_tool.dart';
import '../tools/device_channel.dart';
import '../tools/device_status_tool.dart';
import '../tools/messages_tool.dart';
import '../tools/phone_call_tool.dart';
import '../tools/reminder_tool.dart';
import '../tools/screen_agent_tool.dart';
import '../tools/torch_tool.dart';
import '../tools/volume_tool.dart';
import '../tools/weather_tool.dart';
import '../tools/web_search_tool.dart';
import '../tools/youtube_tool.dart';
import 'live_session_config.dart';
import 'prompt_builder.dart';

enum LiveSessionState {
  disconnected,
  connecting,
  connected,
  listeningWakeWord,
  listening,
  thinking,
  speaking,
  error,
}

/// Core Gemini Live WebSocket Client with on-device Wake Word ("Hey Jarvis") support.
/// Manages real-time streaming audio, background listening, function calling, and Burmese dialogue.
class LiveClient extends ChangeNotifier {
  final AudioService _audioService;
  final MemoryService _memoryService;
  final WakeWordService _wakeWordService;

  WebSocketChannel? _channel;
  StreamSubscription? _channelSub;

  LiveSessionState _state = LiveSessionState.disconnected;
  String _statusMessage = 'အဆင်သင့်ရှိပါသည်';
  String? _lastError;

  bool _initialGreetingDone = false;
  bool _isAwaitingWakeWordTurn = false;
  Timer? _silenceTimer;
  Timer? _thinkingWatchdogTimer;
  Timer? _speakingFallbackTimer;

  // Playback session generation tracking
  int _playbackGeneration = 0;
  int _lastHandledPlaybackGeneration = -1;

  // PTT chunk count tracking to avoid hanging in thinking on empty presses
  int _streamedChunksInCurrentPttTurn = 0;

  // Accumulate transcription chunks so one turn maps to one transcript entry.
  String _pendingInputTranscript = '';
  String _pendingOutputTranscript = '';
  bool _hasPendingInputMessage = false;
  bool _hasPendingOutputMessage = false;

  static const Duration _thinkingWatchdogTimeout = Duration(seconds: 20);

  // Barge-in and double-talk detection state
  double _consecutiveBargeInDurationSec = 0.0;
  static const double _bargeInRequiredDurationSec = 0.16; // ~160ms of sustained speech
  static const double _bargeInRmsThreshold = 1200.0; // Vocal amplitude above speaker bleed

  late final List<BaseTool> _tools;

  // Phone call and AudioFocus suspension state
  bool _isPhoneCallActive = false;
  bool _isAudioFocusLost = false;
  bool _suppressGreetingOnNextConnect = false;

  LiveSessionState get state => _state;
  String get statusMessage => _statusMessage;
  String? get lastError => _lastError;
  bool get isConnected =>
      _channel != null &&
      _state != LiveSessionState.disconnected &&
      _state != LiveSessionState.error;
  WakeWordService get wakeWordService => _wakeWordService;
  int get playbackGeneration => _playbackGeneration;
  int get lastHandledPlaybackGeneration => _lastHandledPlaybackGeneration;
  bool get isPhoneCallActive => _isPhoneCallActive;
  bool get isAudioFocusLost => _isAudioFocusLost;

  LiveClient({
    required AudioService audioService,
    required MemoryService memoryService,
    WakeWordService? wakeWordService,
  })  : _audioService = audioService,
        _memoryService = memoryService,
        _wakeWordService = wakeWordService ?? WakeWordService() {
    _tools = [
      WeatherTool(),
      WebSearchTool(),
      ReminderTool(),
      ToggleTorchTool(),
      SetVolumeTool(),
      OpenAppTool(),
      GetDeviceStatusTool(),
      PlayYouTubeTool(),
      TakeCameraPhotoTool(),
      CheckMessagesTool(),
      SendAppMessageTool(),
      InspectScreenTool(),
      ControlScreenTool(),
      RecordAudioTool(audioService: _audioService),
      MakePhoneCallTool(),
    ];

    // Initialize native device channel listener for phone calls & audio focus
    DeviceChannel.initialize();
    DeviceChannel.onCallStateChanged = handlePhoneCallStateChanged;
    DeviceChannel.onAudioFocusChanged = handleAudioFocusChanged;

    // Listen to mic chunks
    _audioService.onAudioChunkRecorded = _handleRecordedAudioChunk;

    // Wake word detected callback
    _wakeWordService.onWakeWordDetected = _onWakeWordDetected;

    // Listen to playback state changes
    _audioService.onPlaybackStateChanged = (isPlaying) {
      debugPrint(
        '[LiveClient] onPlaybackStateChanged: isPlaying=$isPlaying, state=$_state, gen=$_playbackGeneration',
      );
      if (isPlaying && _state != LiveSessionState.listening) {
        _setState(LiveSessionState.speaking, 'ပြောနေပါသည်...', caller: 'playback_state_true');
      } else if (!isPlaying && (_state == LiveSessionState.speaking || _audioService.isPlaying)) {
        _handlePlaybackCompleted(
          generation: _playbackGeneration,
          reason: 'playback_state_false',
        );
      }
    };
  }

  bool _isDisposed = false;

  void _setState(LiveSessionState newState, String message, {String? caller}) {
    if (_isDisposed) return;
    final oldState = _state;
    _state = newState;
    _statusMessage = message;
    debugPrint(
      '[LiveClient][_setState] ${DateTime.now().toIso8601String()} | $oldState -> $newState | "$message" | caller: ${caller ?? 'unknown'}',
    );
    if (newState == LiveSessionState.thinking) {
      _startThinkingWatchdog();
    } else {
      _cancelThinkingWatchdog();
    }
    notifyListeners();
  }

  void _startThinkingWatchdog() {
    _thinkingWatchdogTimer?.cancel();
    _thinkingWatchdogTimer = Timer(_thinkingWatchdogTimeout, _onThinkingWatchdogTimeout);
  }

  void _cancelThinkingWatchdog() {
    _thinkingWatchdogTimer?.cancel();
    _thinkingWatchdogTimer = null;
  }

  Future<void> _onThinkingWatchdogTimeout() async {
    _thinkingWatchdogTimer = null;
    if (_state != LiveSessionState.thinking) return;

    debugPrint('[LiveClient] Thinking watchdog timed out. Recovering to listening mode...');
    final handsFreeEnabled = await AppPrefs.isHandsFreeEnabled();
    if (_state != LiveSessionState.thinking) return;

    const recoveryMessage = 'ချိတ်ဆက်မှု ကြာနေလို့ ပြန်နားထောင်နေပါသည် ခင်ဗျာ။';
    if (handsFreeEnabled) {
      _setState(LiveSessionState.listening, recoveryMessage, caller: 'watchdog_handsfree');
      await _audioService.restartRecording();
      _startSilenceTimer();
    } else {
      _setState(LiveSessionState.connected, recoveryMessage, caller: 'watchdog_ptt');
    }
  }

  /// Connect to Gemini Live API
  Future<bool> connect({bool triggerGreeting = true}) async {
    if (!triggerGreeting) {
      _suppressGreetingOnNextConnect = true;
    }
    final apiKey = await SecureKeyStore.getApiKey();
    if (apiKey == null || apiKey.isEmpty) {
      _setState(
        LiveSessionState.error,
        'Gemini API Key မရှိသေးပါ။ ကျေးဇူးပြု၍ Settings တွင် API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။',
        caller: 'connect_no_api_key',
      );
      _lastError = 'API_KEY_MISSING';
      return false;
    }

    await disconnect();

    _setState(
      LiveSessionState.connecting,
      'Gemini Live သို့ ချိတ်ဆက်နေပါသည်...',
      caller: 'connect_start',
    );
    _lastError = null;

    try {
      final model = await AppPrefs.getModelName();
      final voice = await AppPrefs.getVoiceName();

      final wsUri = Uri.parse(
        'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=$apiKey',
      );

      _channel = IOWebSocketChannel.connect(
        wsUri,
        headers: {
          'x-goog-api-key': apiKey,
          'Content-Type': 'application/json',
        },
      );

      // Attach listener BEFORE sending messages
      _channelSub = _channel!.stream.listen(
        _onMessageReceived,
        onError: _onStreamError,
        onDone: _onStreamDone,
        cancelOnError: true,
      );

      // Wait for WebSocket handshake
      await _channel!.ready;
      debugPrint('[LiveClient] WebSocket connected and ready');

      // 1. Send the initial configuration Setup message with Knowledge Base
      final knowledgeBase = await KnowledgeService.loadKnowledgeBase();
      final setupPayload = LiveSessionConfig.createSetupPayload(
        modelName: model,
        voiceName: voice,
        tools: _tools,
        knowledgeBase: knowledgeBase,
      );
      debugPrint('[LiveClient] Sending setup payload for model: $model, voice: $voice (kb chars: ${knowledgeBase.length})');
      _channel!.sink.add(jsonEncode(setupPayload));

      return true;
    } catch (e) {
      debugPrint('[LiveClient] Connect exception: $e');
      _setState(
        LiveSessionState.error,
        'ချိတ်ဆက်မှု မအောင်မြင်ပါ။ အင်တာနက်နှင့် VPN ဖွင့်ထားခြင်း ရှိမရှိ စစ်ဆေးပေးပါ ခင်ဗျာ။',
        caller: 'connect_exception',
      );
      _lastError = e.toString();
      final wakeWordEnabled = await AppPrefs.isWakeWordEnabled();
      if (wakeWordEnabled) {
        Future.delayed(const Duration(seconds: 4), () {
          startWakeWordListening();
        });
      }
      return false;
    }
  }

  /// Disconnect current session
  Future<void> disconnect() async {
    _silenceTimer?.cancel();
    _silenceTimer = null;
    _cancelThinkingWatchdog();
    _speakingFallbackTimer?.cancel();
    _speakingFallbackTimer = null;
    _finalizeTranscripts();
    _wakeWordService.stop();

    await _channelSub?.cancel();
    _channelSub = null;
    await _channel?.sink.close();
    _channel = null;
    await _audioService.stopRecording();
    await _audioService.stopPlayback(forGeneration: _playbackGeneration);
    _setState(
      LiveSessionState.disconnected,
      'ချိတ်ဆက်မှု ရပ်ဆိုင်းထားပါသည်',
      caller: 'disconnect',
    );
  }

  /// Start on-device listening for "Hey Jarvis"
  Future<bool> startWakeWordListening() async {
    final wakeWordEnabled = await AppPrefs.isWakeWordEnabled();
    if (!wakeWordEnabled) return false;

    _silenceTimer?.cancel();
    _silenceTimer = null;

    // 1. Initialize models if not ready
    final userThreshold = await AppPrefs.getWakeWordThreshold();
    _wakeWordService.threshold = userThreshold;
    debugPrint('[LiveClient] startWakeWordListening with threshold: $userThreshold');

    if (!_wakeWordService.isInitialized) {
      _setState(
        LiveSessionState.connecting,
        'Wake Word engine ပြင်ဆင်နေပါသည်...',
        caller: 'startWakeWordListening_init',
      );
      final ok = await _wakeWordService.initialize();
      if (!ok) {
        debugPrint('[LiveClient] WakeWordService init failed');
        _setState(
          LiveSessionState.error,
          'Wake Word စတင်၍ မရပါ ခင်ဗျာ။',
          caller: 'startWakeWordListening_init_failed',
        );
        return false;
      }
    }

    // 2. Start Android Foreground Service with persistent notification
    await BackgroundService.start();

    // 3. Start audio recording strictly for local on-device wake word engine
    _wakeWordService.start();
    await _audioService.restartRecording(stopActivePlayback: false);

    _setState(
      LiveSessionState.listeningWakeWord,
      'အသင့်ရှိပါသည် ("Hey Jarvis" ဟုခေါ်ပါ)',
      caller: 'startWakeWordListening_success',
    );
    return true;
  }

  /// Stop wake word listening
  Future<void> stopWakeWordListening() async {
    _silenceTimer?.cancel();
    _silenceTimer = null;
    _wakeWordService.stop();
    await BackgroundService.stop();

    if (_state == LiveSessionState.listeningWakeWord) {
      await _audioService.stopRecording();
      _setState(
        LiveSessionState.connected,
        'အဆင်သင့်ရှိပါသည်',
        caller: 'stopWakeWordListening',
      );
    }
  }

  /// Triggered when on-device engine detects "Hey Jarvis"
  Future<void> _onWakeWordDetected() async {
    if (_isPhoneCallActive) {
      debugPrint('[LiveClient] Wake word detected ignored: phone call is active');
      return;
    }
    debugPrint('[LiveClient] *** Wake Word "Hey Jarvis" Detected! ***');
    _silenceTimer?.cancel();
    _wakeWordService.stop();

    _setState(
      LiveSessionState.thinking,
      '"Hey Jarvis" ကြားသိပါပြီ...',
      caller: 'onWakeWordDetected',
    );

    _isAwaitingWakeWordTurn = true;
    if (!isConnected) {
      final ok = await connect();
      if (!ok) {
        _isAwaitingWakeWordTurn = false;
        _setState(
          LiveSessionState.error,
          'Gemini Live ချိတ်ဆက်မှု မအောင်မြင်ပါ ခင်ဗျာ။',
          caller: 'onWakeWordDetected_connect_failed',
        );
        Future.delayed(const Duration(seconds: 4), () {
          startWakeWordListening();
        });
        return;
      }
    } else {
      // Already connected, trigger response immediately
      _triggerWakeWordGreeting();
    }
  }

  /// Interrupt playback immediately (Tap-to-interrupt / Barge-in)
  Future<void> interruptPlayback() async {
    if (_state == LiveSessionState.speaking || _audioService.isPlaying) {
      _speakingFallbackTimer?.cancel();
      _speakingFallbackTimer = null;
      _lastHandledPlaybackGeneration = _playbackGeneration;
      await _audioService.stopPlayback(forGeneration: _playbackGeneration);
      _audioService.clearIncomingBuffer();
      _setState(
        LiveSessionState.listening,
        'နားထောင်နေပါသည်...',
        caller: 'interruptPlayback',
      );
      _startSilenceTimer();
      await _audioService.restartRecording();
    }
  }

  /// Push-to-Talk: Start streaming microphone
  Future<void> startTalking() async {
    if (_isPhoneCallActive) {
      debugPrint('[LiveClient] startTalking ignored: phone call is active');
      return;
    }
    _silenceTimer?.cancel();
    _wakeWordService.stop();
    _streamedChunksInCurrentPttTurn = 0;

    if (_audioService.isPlaying) {
      _speakingFallbackTimer?.cancel();
      _speakingFallbackTimer = null;
      _lastHandledPlaybackGeneration = _playbackGeneration;
      await _audioService.stopPlayback(forGeneration: _playbackGeneration);
      _audioService.clearIncomingBuffer();
    }

    if (!isConnected) {
      final ok = await connect();
      if (!ok) return;
    }

    _setState(
      LiveSessionState.listening,
      'နားထောင်နေပါသည်...',
      caller: 'startTalking',
    );
    await _audioService.restartRecording();
  }

  /// Push-to-Talk: Stop streaming microphone & notify turn end
  Future<void> stopTalking() async {
    if (_state == LiveSessionState.listening) {
      if (_streamedChunksInCurrentPttTurn == 0) {
        debugPrint(
          '[LiveClient] PTT released with 0 chunks streamed. Cancelling turn without audioStreamEnd.',
        );
        final handsFreeEnabled = await AppPrefs.isHandsFreeEnabled();
        if (handsFreeEnabled) {
          _setState(
            LiveSessionState.listening,
            'နားထောင်နေပါသည်...',
            caller: 'stopTalking_empty_handsfree',
          );
          await _audioService.restartRecording();
          _startSilenceTimer();
        } else {
          await _audioService.stopRecording();
          _setState(
            LiveSessionState.connected,
            'အဆင်သင့်ရှိပါသည်',
            caller: 'stopTalking_empty_ptt',
          );
        }
        return;
      }

      final handsFreeEnabled = await AppPrefs.isHandsFreeEnabled();
      if (!handsFreeEnabled) {
        await _audioService.stopRecording();
      }
      _setState(
        LiveSessionState.thinking,
        'စဉ်းစားနေပါသည်...',
        caller: 'stopTalking',
      );

      // Notify Gemini that client audio stream has ended (turn complete trigger)
      if (_channel != null) {
        final endPayload = {
          'realtimeInput': {
            'audioStreamEnd': true,
          }
        };
        _channel!.sink.add(jsonEncode(endPayload));
      }
    }
  }

  /// Handle incoming audio chunk from microphone
  void _handleRecordedAudioChunk(Uint8List chunk) async {
    // 0. Drop all chunks when a phone call is active
    if (_isPhoneCallActive) {
      return;
    }

    // 1. In Wake Word mode: Strictly on-device. Zero network traffic.
    if (_state == LiveSessionState.listeningWakeWord) {
      _wakeWordService.processPcmChunk(chunk);
      return;
    }

    // 2. In Speaking mode (Jarvis speaking through speaker):
    // Handle Barge-in while preventing acoustic self-interruption (echo differentiation)
    if (_state == LiveSessionState.speaking || _audioService.isPlaying) {
      final rms = PcmConverter.calculateRms(chunk);
      final chunkDurationSec = (chunk.length / 2) / 16000.0;
      debugPrint(
        '[LiveClient] Speaking mic chunk: len=${chunk.length}, dur=${(chunkDurationSec * 1000).toStringAsFixed(1)}ms, rms=${rms.toStringAsFixed(1)}',
      );
      if (rms >= _bargeInRmsThreshold) {
        _consecutiveBargeInDurationSec += chunkDurationSec;
        if (_consecutiveBargeInDurationSec >= _bargeInRequiredDurationSec) {
          debugPrint(
            '[LiveClient] *** USER BARGE-IN DETECTED! (duration: ${(_consecutiveBargeInDurationSec * 1000).toStringAsFixed(0)}ms, RMS: ${rms.toStringAsFixed(1)}) ***',
          );
          _consecutiveBargeInDurationSec = 0.0;
          _speakingFallbackTimer?.cancel();
          _speakingFallbackTimer = null;
          _lastHandledPlaybackGeneration = _playbackGeneration;

          // Immediately stop playback client-side and clear buffered audio
          await _audioService.stopPlayback(forGeneration: _playbackGeneration);
          _audioService.clearIncomingBuffer();
          _setState(
            LiveSessionState.listening,
            'နားထောင်နေပါသည်...',
            caller: 'barge_in',
          );
          _resetSilenceTimer();

          // Stream the barge-in vocal chunk to Gemini Live
          _streamPcmChunk(chunk);
        }
      } else {
        _consecutiveBargeInDurationSec = 0.0;
        // Residual speaker echo / bleed or background noise -> drop chunk to prevent self-interruption
      }
      return;
    }

    // 3. In Thinking mode: Model is processing/generating response.
    // If user speaks loudly, stream chunk so server VAD detects interruption.
    if (_state == LiveSessionState.thinking) {
      final rms = PcmConverter.calculateRms(chunk);
      debugPrint(
        '[LiveClient] Thinking mic chunk: len=${chunk.length}, rms=${rms.toStringAsFixed(1)}',
      );
      if (rms >= _bargeInRmsThreshold && _channel != null) {
        debugPrint(
          '[LiveClient] Streaming vocal chunk during thinking (RMS: ${rms.toStringAsFixed(1)})',
        );
        _streamPcmChunk(chunk);
      }
      return;
    }

    // 4. In Live conversation listening mode:
    if (_state == LiveSessionState.listening && _channel != null) {
      final rms = PcmConverter.calculateRms(chunk);
      if (rms >= 1000.0) {
        debugPrint(
          '[LiveClient] Listening speech chunk: len=${chunk.length}, rms=${rms.toStringAsFixed(1)}',
        );
      }
      if (rms >= 1600.0) {
        // Active human speech detected -> reset 30s silence countdown
        _resetSilenceTimer();
      }
      _streamPcmChunk(chunk);
      return;
    }

    // Dropped mic chunks in any other state (connected, error, disconnected, connecting)
    final rms = PcmConverter.calculateRms(chunk);
    debugPrint(
      '[LiveClient] Mic chunk dropped - state: $_state, len: ${chunk.length}, rms: ${rms.toStringAsFixed(1)}',
    );
  }

  void _streamPcmChunk(Uint8List chunk) {
    if (_channel == null) return;
    _streamedChunksInCurrentPttTurn++;
    final base64Audio = base64Encode(chunk);
    final audioPayload = {
      'realtimeInput': {
        'audio': {
          'mimeType': 'audio/pcm;rate=16000',
          'data': base64Audio,
        }
      }
    };
    _channel!.sink.add(jsonEncode(audioPayload));
  }

  void _appendInputTranscript(String text) {
    _pendingInputTranscript += text;
    if (_hasPendingInputMessage) {
      _memoryService.updateLastMessage(
        _pendingInputTranscript,
        sender: MessageSender.user,
      );
    } else {
      _memoryService.addUserMessage(_pendingInputTranscript);
      _hasPendingInputMessage = true;
    }
  }

  void _appendOutputTranscript(String text) {
    _pendingOutputTranscript += text;
    if (_hasPendingOutputMessage) {
      _memoryService.updateLastMessage(
        _pendingOutputTranscript,
        sender: MessageSender.assistant,
      );
    } else {
      _memoryService.addAssistantMessage(_pendingOutputTranscript);
      _hasPendingOutputMessage = true;
    }
  }

  void _finalizeOutputTranscript() {
    _pendingOutputTranscript = '';
    _hasPendingOutputMessage = false;
  }

  /// Completes the current turn's transcript entries. Further chunks start new
  /// messages instead of updating the finalized turn.
  void _finalizeTranscripts() {
    _pendingInputTranscript = '';
    _hasPendingInputMessage = false;
    _finalizeOutputTranscript();
  }

  /// Start or reset 30-second silence timer to revert to wake word mode
  void _startSilenceTimer() {
    _silenceTimer?.cancel();
    _silenceTimer = Timer(const Duration(seconds: 30), () {
      debugPrint('[LiveClient] 30 seconds silence reached. Reverting to wake word mode...');
      _revertToWakeWordMode();
    });
  }

  void _resetSilenceTimer() {
    _startSilenceTimer();
  }

  Future<void> _revertToWakeWordMode() async {
    _silenceTimer?.cancel();
    _silenceTimer = null;

    final wakeWordEnabled = await AppPrefs.isWakeWordEnabled();
    if (wakeWordEnabled) {
      await startWakeWordListening();
    } else {
      _setState(
        LiveSessionState.connected,
        'အဆင်သင့်ရှိပါသည်',
        caller: 'revertToWakeWord_ptt',
      );
    }
  }

  /// Callback when audio playback finishes
  Future<void> _handlePlaybackCompleted({
    int? generation,
    String reason = 'playback_ended',
  }) async {
    debugPrint(
      '[LiveClient] _handlePlaybackCompleted called (gen: $generation, lastHandled: $_lastHandledPlaybackGeneration, reason: $reason, state: $_state)',
    );

    if (generation != null) {
      if (_lastHandledPlaybackGeneration == generation) {
        debugPrint(
          '[LiveClient] Playback gen $generation already handled. Ignoring duplicate call.',
        );
        return;
      }
      _lastHandledPlaybackGeneration = generation;
    }

    _speakingFallbackTimer?.cancel();
    _speakingFallbackTimer = null;

    if (_isAwaitingWakeWordTurn) {
      _isAwaitingWakeWordTurn = false;
      _initialGreetingDone = true;
      final handsFreeEnabled = await AppPrefs.isHandsFreeEnabled();
      if (handsFreeEnabled) {
        _setState(
          LiveSessionState.listening,
          'နားထောင်နေပါသည်...',
          caller: '_handlePlaybackCompleted_wake_handsfree',
        );
        await _audioService.restartRecording(stopActivePlayback: false);
        _startSilenceTimer();
      } else {
        _setState(
          LiveSessionState.connected,
          'အဆင်သင့်ရှိပါသည်',
          caller: '_handlePlaybackCompleted_wake_ptt',
        );
      }
      return;
    }

    if (!_initialGreetingDone) {
      _initialGreetingDone = true;
      final wakeWordEnabled = await AppPrefs.isWakeWordEnabled();
      if (wakeWordEnabled) {
        await startWakeWordListening();
        return;
      }
      _setState(
        LiveSessionState.connected,
        'အဆင်သင့်ရှိပါသည်',
        caller: '_handlePlaybackCompleted_greeting_done',
      );
      return;
    }

    final handsFreeEnabled = await AppPrefs.isHandsFreeEnabled();
    if (handsFreeEnabled) {
      // Hands-free Mode: Automatically resume continuous listening for next command
      _setState(
        LiveSessionState.listening,
        'နားထောင်နေပါသည်...',
        caller: '_handlePlaybackCompleted_handsfree',
      );
      await _audioService.restartRecording(stopActivePlayback: false);
      _startSilenceTimer();
    } else {
      // Push-to-Talk fallback: Go to connected and wait for user to press button
      _setState(
        LiveSessionState.connected,
        'အဆင်သင့်ရှိပါသည်',
        caller: '_handlePlaybackCompleted_ptt',
      );
    }
  }

  /// Handle incoming WebSocket messages from Gemini Live server
  Future<void> _onMessageReceived(dynamic event) async {
    try {
      final String rawJson = event is String ? event : utf8.decode(event as List<int>);
      debugPrint('[LiveClient] Message received: $rawJson');
      final Map<String, dynamic> data = jsonDecode(rawJson);

      // 1. Setup complete -> Trigger startup greeting or wake word response
      if (data.containsKey('setupComplete')) {
        debugPrint(
          '[LiveClient] setupComplete: awaitingWakeWord=$_isAwaitingWakeWordTurn, initialGreetingDone=$_initialGreetingDone, suppressGreeting=$_suppressGreetingOnNextConnect',
        );
        if (_suppressGreetingOnNextConnect) {
          _suppressGreetingOnNextConnect = false;
          _initialGreetingDone = true;
          _isAwaitingWakeWordTurn = false;
          await _resumeWakeModeSilently();
          return;
        }
        if (_isAwaitingWakeWordTurn) {
          _setState(
            LiveSessionState.connected,
            'ချိတ်ဆက်မှု အောင်မြင်ပါသည်',
            caller: 'setupComplete_wake',
          );
          _triggerWakeWordGreeting();
        } else if (!_initialGreetingDone) {
          _setState(
            LiveSessionState.connected,
            'ချိတ်ဆက်မှု အောင်မြင်ပါသည်',
            caller: 'setupComplete_init',
          );
          _triggerStartupGreeting();
        } else {
          final handsFreeEnabled = await AppPrefs.isHandsFreeEnabled();
          if (handsFreeEnabled) {
            _setState(
              LiveSessionState.listening,
              'နားထောင်နေပါသည်...',
              caller: 'setupComplete_resume_handsfree',
            );
            await _audioService.restartRecording(stopActivePlayback: false);
            _startSilenceTimer();
          } else {
            _setState(
              LiveSessionState.connected,
              'အဆင်သင့်ရှိပါသည်',
              caller: 'setupComplete_resume_ptt',
            );
          }
        }
        return;
      }

      // Voice Activity Detection (Gemini VAD / server-side barge-in signal)
      final va = (data['voiceActivity'] ??
              (data['serverContent'] is Map
                  ? (data['serverContent'] as Map)['voiceActivity']
                  : null))
          as Map<String, dynamic>?;
      if (va != null) {
        final type = va['type'] as String?;
        if (type == 'ACTIVITY_START' || type == 'VOICE_ACTIVITY_START') {
          debugPrint('[LiveClient] Gemini VAD: ACTIVITY_START');
          _resetSilenceTimer();
          if (_state == LiveSessionState.speaking || _audioService.isPlaying) {
            _speakingFallbackTimer?.cancel();
            _speakingFallbackTimer = null;
            _lastHandledPlaybackGeneration = _playbackGeneration;
            await _audioService.stopPlayback(forGeneration: _playbackGeneration);
            _audioService.clearIncomingBuffer();
            _setState(
              LiveSessionState.listening,
              'နားထောင်နေပါသည်...',
              caller: 'vad_activity_start',
            );
            _startSilenceTimer();
          }
        } else if (type == 'ACTIVITY_END' || type == 'VOICE_ACTIVITY_END') {
          debugPrint('[LiveClient] Gemini VAD: ACTIVITY_END');
          _resetSilenceTimer();
          if (_state == LiveSessionState.listening) {
            _setState(
              LiveSessionState.thinking,
              'စဉ်းစားနေပါသည်...',
              caller: 'vad_activity_end',
            );
          }
        }
      }

      // 2. Server Content: audio output, transcriptions, interruptions
      if (data.containsKey('serverContent')) {
        final sc = data['serverContent'] as Map<String, dynamic>;

        // Interrupted (Barge-in by user detected by server)
        if (sc['interrupted'] == true) {
          debugPrint('[LiveClient] Model interrupted signal from server');
          _speakingFallbackTimer?.cancel();
          _speakingFallbackTimer = null;
          _lastHandledPlaybackGeneration = _playbackGeneration;
          _finalizeOutputTranscript();
          await _audioService.stopPlayback(forGeneration: _playbackGeneration);
          _audioService.clearIncomingBuffer();
          _setState(
            LiveSessionState.listening,
            'နားထောင်နေပါသည်...',
            caller: 'server_interrupted',
          );
          _startSilenceTimer();
          return;
        }

        // Input transcription (What user spoke in Burmese)
        if (sc.containsKey('inputTranscription')) {
          final text = sc['inputTranscription']?['text'] as String?;
          if (text != null && text.trim().isNotEmpty) {
            _appendInputTranscript(text);
            _resetSilenceTimer();
          }
        }

        // Output transcription (What Jarvis spoke in Burmese)
        if (sc.containsKey('outputTranscription')) {
          final text = sc['outputTranscription']?['text'] as String?;
          if (text != null && text.trim().isNotEmpty) {
            _appendOutputTranscript(text);
          }
        }

        // Model audio chunks
        final modelTurn = sc['modelTurn'] as Map<String, dynamic>?;
        if (modelTurn != null && modelTurn.containsKey('parts')) {
          final parts = modelTurn['parts'] as List;
          for (final part in parts) {
            if (part is Map && part.containsKey('inlineData')) {
              final inlineData = part['inlineData'];
              final base64Pcm = inlineData['data'] as String?;
              if (base64Pcm != null && base64Pcm.isNotEmpty) {
                // Model audio is a valid response; the connection is not stalled.
                _cancelThinkingWatchdog();
                final pcmBytes = base64Decode(base64Pcm);
                _audioService.appendIncomingPcmChunk(pcmBytes);
              }
            }
          }
        }

        // Turn complete -> Play accumulated spoken audio
        if (sc['turnComplete'] == true) {
          _cancelThinkingWatchdog();
          _finalizeTranscripts();
          if (_audioService.hasAudioToPlay) {
            _playbackGeneration++;
            final currentGen = _playbackGeneration;
            _setState(
              LiveSessionState.speaking,
              'ပြောနေပါသည်...',
              caller: 'turnComplete_hasAudio',
            );

            final bufferBytes = _audioService.outputBufferLength;
            final estimatedSeconds = bufferBytes / 48000.0; // 24000 samples/sec * 2 bytes
            final fallbackMs = (estimatedSeconds * 1000).toInt() + 5000;
            final fallbackDuration = Duration(milliseconds: fallbackMs);
            debugPrint(
              '[LiveClient] turnComplete: starting playback gen=$currentGen, bufferBytes=$bufferBytes (~${estimatedSeconds.toStringAsFixed(2)}s). Fallback timeout: ${fallbackDuration.inSeconds}s',
            );

            _speakingFallbackTimer?.cancel();
            _speakingFallbackTimer = Timer(fallbackDuration, () {
              if (_playbackGeneration == currentGen &&
                  _lastHandledPlaybackGeneration != currentGen) {
                debugPrint(
                  '[LiveClient] Speaking fallback timer expired for gen=$currentGen! Fallback calling _handlePlaybackCompleted',
                );
                _handlePlaybackCompleted(
                  generation: currentGen,
                  reason: 'speaking_fallback_timeout',
                );
              }
            });

            await _audioService.playAccumulatedAudio();
          } else {
            // No audio to play (silent/text turn or interrupted), switch back to listening or wake word
            await _handlePlaybackCompleted(reason: 'turnComplete_no_audio');
          }
        }
      }

      // 3. Tool Calls (Function calling)
      if (data.containsKey('toolCall')) {
        final toolCall = data['toolCall'] as Map<String, dynamic>;
        final functionCalls = toolCall['functionCalls'] as List?;
        if (functionCalls != null && functionCalls.isNotEmpty) {
          _setState(
            LiveSessionState.thinking,
            'လုပ်ဆောင်ချက် စစ်ဆေးနေပါသည်...',
            caller: 'tool_call',
          );
          await _handleToolCalls(functionCalls);
        }
      }
    } catch (e) {
      debugPrint('[LiveClient] Message processing error: $e');
    }
  }

  /// Triggers spoken greeting in Burmese upon initial setup
  void _triggerStartupGreeting() {
    if (_channel == null) return;

    _setState(
      LiveSessionState.thinking,
      'စတင်နှုတ်ဆက်ရန် ပြင်ဆင်နေပါသည်...',
      caller: '_triggerStartupGreeting',
    );

    final greetingPrompt =
        'အောက်ပါ နှုတ်ခွန်းဆက်စကားကို မင်္ဂလာရှိစွာ၊ နွေးထွေးယဉ်ကျေးစွာ အသံထွက်ဖတ်ပါ:\n'
        '${PromptBuilder.buildStartupGreeting()}\n'
        'Tool မခေါ်ပါနှင့်။ မြန်မာဘာသာဖြင့်သာ ပြောပါ။';

    final greetingPayload = {
      'clientContent': {
        'turns': [
          {
            'role': 'user',
            'parts': [
              {'text': greetingPrompt}
            ]
          }
        ],
        'turnComplete': true,
      }
    };

    _channel!.sink.add(jsonEncode(greetingPayload));
  }

  /// Triggers concise acknowledgment "ဟုတ်ကဲ့ ဆရာ" when "Hey Jarvis" is detected
  void _triggerWakeWordGreeting() {
    if (_channel == null) return;

    _isAwaitingWakeWordTurn = true;
    _setState(
      LiveSessionState.thinking,
      '"Hey Jarvis" ကြားသိပါပြီ...',
      caller: '_triggerWakeWordGreeting',
    );
    const wakePrompt =
        'ဆရာက "Hey Jarvis" ဟု နှိုးထလိုက်ပါပြီ။ "ဟုတ်ကဲ့ ဆရာ" ဟုသာ အလွန်တိုတို ချက်ချင်း တုံ့ပြန်ပြီး ဆရာ့အမိန့်ကို နားထောင်ပေးပါ ခင်ဗျာ။ အခြား မည်သည့်စကားမှ မပိုပါစေနှင့်။';

    final greetingPayload = {
      'clientContent': {
        'turns': [
          {
            'role': 'user',
            'parts': [
              {'text': wakePrompt}
            ]
          }
        ],
        'turnComplete': true,
      }
    };

    _channel!.sink.add(jsonEncode(greetingPayload));
  }

  /// Execute tools and return toolResponse
  Future<void> _handleToolCalls(List functionCalls) async {
    final List<Map<String, dynamic>> responses = [];

    for (final call in functionCalls) {
      final callId = call['id'] as String? ?? '';
      final toolName = call['name'] as String? ?? '';
      final args = (call['args'] as Map<String, dynamic>?) ?? {};

      debugPrint('[LiveClient] Tool call: $toolName args: $args');
      _memoryService.addSystemMessage('Tool ခေါ်ယူမှု: $toolName', isToolCall: true);

      final tool = _tools.firstWhere(
        (t) => t.name == toolName,
        orElse: () => _DummyNotFoundTool(toolName),
      );

      final result = await tool.execute(args);

      responses.add({
        'id': callId,
        'name': toolName,
        'response': {
          'result': result,
        }
      });
    }

    if (_channel != null && responses.isNotEmpty) {
      final toolResponsePayload = {
        'toolResponse': {
          'functionResponses': responses,
        }
      };
      _channel!.sink.add(jsonEncode(toolResponsePayload));
    }
  }

  void _onStreamError(dynamic error) {
    debugPrint('[LiveClient] WebSocket stream error: $error');
    _lastError = error.toString();
    _setState(
      LiveSessionState.error,
      'ချိတ်ဆက်မှု ပြတ်တောက်သွားပါသည် (VPN သို့မဟုတ် အင်တာနက် စစ်ဆေးပေးပါ ခင်ဗျာ)။',
      caller: 'stream_error',
    );

    _channel = null;
    _channelSub?.cancel();
    _channelSub = null;
    _finalizeTranscripts();

    AppPrefs.isWakeWordEnabled().then((enabled) {
      if (enabled && !_isPhoneCallActive) {
        startWakeWordListening();
      }
    });
  }

  void _onStreamDone() {
    final code = _channel?.closeCode;
    final reason = _channel?.closeReason;
    debugPrint('[LiveClient] WebSocket closed - closeCode: $code, closeReason: $reason');
    _channel = null;
    _channelSub?.cancel();
    _channelSub = null;
    _finalizeTranscripts();

    AppPrefs.isWakeWordEnabled().then((enabled) {
      if (enabled && !_isPhoneCallActive) {
        startWakeWordListening();
      } else if (_state != LiveSessionState.disconnected && !_isPhoneCallActive) {
        _setState(
          LiveSessionState.disconnected,
          'Gemini Live ချိတ်ဆက်မှု ပြီးဆုံးသွားပါသည် (code: $code)',
          caller: 'stream_done',
        );
      }
    });
  }

  /// Handle incoming/outgoing phone call state changes (RINGING, OFFHOOK, IDLE).
  Future<void> handlePhoneCallStateChanged(String state) async {
    final upper = state.trim().toUpperCase();
    debugPrint(
      '[LiveClient] handlePhoneCallStateChanged: $upper (current isCallActive: $_isPhoneCallActive, state: $_state)',
    );

    if (upper == 'RINGING' || upper == 'OFFHOOK') {
      if (_isPhoneCallActive) return;
      _isPhoneCallActive = true;
      _isAwaitingWakeWordTurn = false;
      _consecutiveBargeInDurationSec = 0.0;

      // 1. Immediately stop playback & discard buffered audio
      _speakingFallbackTimer?.cancel();
      _speakingFallbackTimer = null;
      _lastHandledPlaybackGeneration = _playbackGeneration;
      await _audioService.stopPlayback(forGeneration: _playbackGeneration);
      _audioService.clearIncomingBuffer();

      // 2. Stop microphone recording
      await _audioService.stopRecording();

      // 3. Stop wake word engine
      _wakeWordService.stop();

      // 4. Abandon active Live turn & timers
      _silenceTimer?.cancel();
      _silenceTimer = null;
      _cancelThinkingWatchdog();
      _finalizeTranscripts();

      // 5. Update state silently to connected (paused during phone call)
      _setState(
        LiveSessionState.connected,
        'ဖုန်းခေါ်ဆိုမှု ရှိနေပါသည်...',
        caller: 'call_state_ringing_offhook',
      );
    } else if (upper == 'IDLE') {
      if (!_isPhoneCallActive) {
        debugPrint('[LiveClient] Call was not active, ignoring IDLE event.');
        return;
      }
      _isPhoneCallActive = false;
      debugPrint('[LiveClient] Call ended (IDLE). Checking socket status...');

      // Small delay to allow Android hardware to release telecom audio routing
      await Future.delayed(const Duration(milliseconds: 200));

      final socketAlive = isConnected && _channel != null;
      debugPrint('[LiveClient] Post-call socket status: alive=$socketAlive');

      if (!socketAlive) {
        _suppressGreetingOnNextConnect = true;
        debugPrint('[LiveClient] Reconnecting WebSocket silently without auto-greeting...');
        final ok = await connect(triggerGreeting: false);
        if (!ok) {
          debugPrint('[LiveClient] Reconnect failed. Reverting to wake word listening in background...');
          _suppressGreetingOnNextConnect = false;
          await _resumeWakeModeSilently();
        }
      } else {
        await _resumeWakeModeSilently();
      }
    }
  }

  /// Handle Android AudioFocus loss or gain.
  Future<void> handleAudioFocusChanged(String focus) async {
    final upper = focus.trim().toUpperCase();
    debugPrint(
      '[LiveClient] handleAudioFocusChanged: $upper (isCallActive: $_isPhoneCallActive, state: $_state)',
    );

    if (upper.contains('LOSS')) {
      _isAudioFocusLost = true;
      _consecutiveBargeInDurationSec = 0.0;
      _isAwaitingWakeWordTurn = false;

      // Immediately stop playback & discard buffered audio
      _speakingFallbackTimer?.cancel();
      _speakingFallbackTimer = null;
      _lastHandledPlaybackGeneration = _playbackGeneration;
      await _audioService.stopPlayback(forGeneration: _playbackGeneration);
      _audioService.clearIncomingBuffer();

      // Stop microphone recording
      await _audioService.stopRecording();

      // Stop wake word engine
      _wakeWordService.stop();

      // Abandon active Live turn & timers
      _silenceTimer?.cancel();
      _silenceTimer = null;
      _cancelThinkingWatchdog();
      _finalizeTranscripts();

      if (!_isPhoneCallActive) {
        _setState(
          LiveSessionState.connected,
          'အသံအသုံးပြုမှု ရပ်ဆိုင်းထားပါသည်...',
          caller: 'audio_focus_loss',
        );
      }
    } else if (upper.contains('GAIN')) {
      if (_isAudioFocusLost) {
        _isAudioFocusLost = false;
        if (!_isPhoneCallActive) {
          debugPrint('[LiveClient] Audio focus GAIN: resuming wake mode silently');
          await _resumeWakeModeSilently();
        }
      }
    }
  }

  /// Silently returns to wake word mode or connected state without speaking greeting.
  Future<void> _resumeWakeModeSilently() async {
    debugPrint('[LiveClient] _resumeWakeModeSilently called');
    _silenceTimer?.cancel();
    _silenceTimer = null;
    _consecutiveBargeInDurationSec = 0.0;
    _isAwaitingWakeWordTurn = false;

    final wakeWordEnabled = await AppPrefs.isWakeWordEnabled();
    if (wakeWordEnabled) {
      await startWakeWordListening();
    } else {
      _setState(
        LiveSessionState.connected,
        'အဆင်သင့်ရှိပါသည်',
        caller: '_resumeWakeModeSilently_ptt',
      );
    }
  }

  // --- Methods visible for unit testing ---
  @visibleForTesting
  void setPhoneCallActiveForTesting(bool active) {
    _isPhoneCallActive = active;
  }

  @visibleForTesting
  void setAudioFocusLostForTesting(bool lost) {
    _isAudioFocusLost = lost;
  }

  @visibleForTesting
  bool get suppressGreetingOnNextConnectForTesting => _suppressGreetingOnNextConnect;

  @visibleForTesting
  void setSuppressGreetingOnNextConnectForTesting(bool suppress) {
    _suppressGreetingOnNextConnect = suppress;
  }

  @visibleForTesting
  void setStateForTesting(LiveSessionState newState, String message, {String? caller}) {
    _setState(newState, message, caller: caller);
  }

  @visibleForTesting
  Future<void> handlePlaybackCompletedForTesting({
    int? generation,
    String reason = 'test',
  }) async {
    await _handlePlaybackCompleted(generation: generation, reason: reason);
  }

  @visibleForTesting
  void setPlaybackGenerationForTesting(int gen) {
    _playbackGeneration = gen;
  }

  @visibleForTesting
  void simulatePcmChunkForTesting(Uint8List chunk) {
    _handleRecordedAudioChunk(chunk);
  }

  @visibleForTesting
  void attachChannelForTesting(WebSocketChannel channel) {
    _channelSub?.cancel();
    _channel = channel;
    _channelSub = channel.stream.listen(
      _onMessageReceived,
      onError: _onStreamError,
      onDone: _onStreamDone,
      cancelOnError: true,
    );
  }

  @visibleForTesting
  void setInitialGreetingDoneForTesting(bool done) {
    _initialGreetingDone = done;
  }

  @override
  void dispose() {
    _isDisposed = true;
    _speakingFallbackTimer?.cancel();
    _speakingFallbackTimer = null;
    disconnect();
    _wakeWordService.dispose();
    super.dispose();
  }
}

class _DummyNotFoundTool extends BaseTool {
  final String _missingName;
  _DummyNotFoundTool(this._missingName);

  @override
  String get name => _missingName;

  @override
  String get description => '';

  @override
  Map<String, dynamic> get parametersSchema => {};

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    return '$_missingName ဟုခေါ်သော tool မရှိသေးပါ ခင်ဗျာ။';
  }
}
