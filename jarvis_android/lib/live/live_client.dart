import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../audio/audio_service.dart';
import '../memory/app_prefs.dart';
import '../memory/memory_service.dart';
import '../memory/secure_key_store.dart';
import '../tools/base_tool.dart';
import '../tools/reminder_tool.dart';
import '../tools/weather_tool.dart';
import '../tools/web_search_tool.dart';
import 'live_session_config.dart';
import 'prompt_builder.dart';

enum LiveSessionState {
  disconnected,
  connecting,
  connected,
  listening,
  thinking,
  speaking,
  error,
}

/// Core Gemini Live WebSocket Client.
/// Manages real-time bidirectional streaming audio, function calling, and Burmese transcription.
class LiveClient extends ChangeNotifier {
  final AudioService _audioService;
  final MemoryService _memoryService;

  WebSocketChannel? _channel;
  StreamSubscription? _channelSub;

  LiveSessionState _state = LiveSessionState.disconnected;
  String _statusMessage = 'အဆင်သင့်ရှိပါသည်';
  String? _lastError;

  final List<BaseTool> _tools = [
    WeatherTool(),
    WebSearchTool(),
    ReminderTool(),
  ];

  LiveSessionState get state => _state;
  String get statusMessage => _statusMessage;
  String? get lastError => _lastError;
  bool get isConnected => _state != LiveSessionState.disconnected && _state != LiveSessionState.error;

  LiveClient({
    required AudioService audioService,
    required MemoryService memoryService,
  })  : _audioService = audioService,
        _memoryService = memoryService {
    // Listen to mic chunks and send to WebSocket
    _audioService.onAudioChunkRecorded = _handleRecordedAudioChunk;

    // Listen to playback state changes
    _audioService.onPlaybackStateChanged = (isPlaying) {
      if (isPlaying && _state != LiveSessionState.listening) {
        _setState(LiveSessionState.speaking, 'ပြောနေပါသည်...');
      } else if (!isPlaying && _state == LiveSessionState.speaking) {
        _setState(LiveSessionState.connected, 'အဆင်သင့်ရှိပါသည်');
      }
    };
  }

  void _setState(LiveSessionState newState, String message) {
    _state = newState;
    _statusMessage = message;
    notifyListeners();
  }

  /// Connect to Gemini Live API
  Future<bool> connect() async {
    final apiKey = await SecureKeyStore.getApiKey();
    if (apiKey == null || apiKey.isEmpty) {
      _setState(
        LiveSessionState.error,
        'Gemini API Key မရှိသေးပါ။ ကျေးဇူးပြု၍ Settings တွင် API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။',
      );
      _lastError = 'API_KEY_MISSING';
      return false;
    }

    await disconnect();

    _setState(LiveSessionState.connecting, 'Gemini Live သို့ ချိတ်ဆက်နေပါသည်...');
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

      // Attach listener BEFORE sending messages so no events are lost
      _channelSub = _channel!.stream.listen(
        _onMessageReceived,
        onError: _onStreamError,
        onDone: _onStreamDone,
        cancelOnError: true,
      );

      // Wait for WebSocket handshake to complete
      await _channel!.ready;
      debugPrint('[LiveClient] WebSocket connected and ready');

      // 1. Send the initial configuration Setup message
      final setupPayload = LiveSessionConfig.createSetupPayload(
        modelName: model,
        voiceName: voice,
        tools: _tools,
      );
      debugPrint('[LiveClient] Sending setup payload for model: $model, voice: $voice');
      _channel!.sink.add(jsonEncode(setupPayload));

      return true;
    } catch (e) {
      debugPrint('[LiveClient] Connect exception: $e');
      _setState(
        LiveSessionState.error,
        'ချိတ်ဆက်မှု မအောင်မြင်ပါ။ အင်တာနက်နှင့် VPN ဖွင့်ထားခြင်း ရှိမရှိ စစ်ဆေးပေးပါ ခင်ဗျာ။',
      );
      _lastError = e.toString();
      return false;
    }
  }

  /// Disconnect current session
  Future<void> disconnect() async {
    await _channelSub?.cancel();
    _channelSub = null;
    await _channel?.sink.close();
    _channel = null;
    await _audioService.stopRecording();
    await _audioService.stopPlayback();
    _setState(LiveSessionState.disconnected, 'ချိတ်ဆက်မှု ရပ်ဆိုင်းထားပါသည်');
  }

  /// Push-to-Talk: Start streaming microphone
  Future<void> startTalking() async {
    if (!isConnected) {
      final ok = await connect();
      if (!ok) return;
    }

    _setState(LiveSessionState.listening, 'နားထောင်နေပါသည်...');
    await _audioService.startRecording();
  }

  /// Push-to-Talk: Stop streaming microphone & notify turn end
  Future<void> stopTalking() async {
    if (_state == LiveSessionState.listening) {
      await _audioService.stopRecording();
      _setState(LiveSessionState.thinking, 'စဉ်းစားနေပါသည်...');

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

  /// Send raw recorded PCM chunk as base64 to Gemini Live
  void _handleRecordedAudioChunk(Uint8List chunk) {
    if (_channel == null || _state != LiveSessionState.listening) return;

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

  /// Handle incoming WebSocket messages from Gemini Live server
  Future<void> _onMessageReceived(dynamic event) async {
    try {
      final String rawJson = event is String ? event : utf8.decode(event as List<int>);
      debugPrint('[LiveClient] Message received: $rawJson');
      final Map<String, dynamic> data = jsonDecode(rawJson);

      // 1. Setup complete -> Trigger startup greeting
      if (data.containsKey('setupComplete')) {
        _setState(LiveSessionState.connected, 'ချိတ်ဆက်မှု အောင်မြင်ပါသည်');
        _triggerStartupGreeting();
        return;
      }

      // 2. Server Content: audio output, transcriptions, interruptions
      if (data.containsKey('serverContent')) {
        final sc = data['serverContent'] as Map<String, dynamic>;

        // Interrupted (Barge-in by user)
        if (sc['interrupted'] == true) {
          debugPrint('[LiveClient] Model interrupted');
          await _audioService.stopPlayback();
          _setState(LiveSessionState.connected, 'အဆင်သင့်ရှိပါသည်');
          return;
        }

        // Input transcription (What user spoke in Burmese)
        if (sc.containsKey('inputTranscription')) {
          final text = sc['inputTranscription']?['text'] as String?;
          if (text != null && text.trim().isNotEmpty) {
            _memoryService.addUserMessage(text);
          }
        }

        // Output transcription (What Jarvis spoke in Burmese)
        if (sc.containsKey('outputTranscription')) {
          final text = sc['outputTranscription']?['text'] as String?;
          if (text != null && text.trim().isNotEmpty) {
            _memoryService.addAssistantMessage(text);
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
                final pcmBytes = base64Decode(base64Pcm);
                _audioService.appendIncomingPcmChunk(pcmBytes);
              }
            }
          }
        }

        // Turn complete -> Play accumulated spoken audio
        if (sc['turnComplete'] == true) {
          await _audioService.playAccumulatedAudio();
        }
      }

      // 3. Tool Calls (Function calling)
      if (data.containsKey('toolCall')) {
        final toolCall = data['toolCall'] as Map<String, dynamic>;
        final functionCalls = toolCall['functionCalls'] as List?;
        if (functionCalls != null && functionCalls.isNotEmpty) {
          _setState(LiveSessionState.thinking, 'လုပ်ဆောင်ချက် စစ်ဆေးနေပါသည်...');
          await _handleToolCalls(functionCalls);
        }
      }
    } catch (e) {
      debugPrint('[LiveClient] Message processing error: $e');
    }
  }

  /// Triggers spoken greeting in Burmese upon successful live connection
  void _triggerStartupGreeting() {
    if (_channel == null) return;

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
    _setState(
      LiveSessionState.error,
      'ချိတ်ဆက်မှု ပြတ်တောက်သွားပါသည် (VPN သို့မဟုတ် အင်တာနက် စစ်ဆေးပေးပါ ခင်ဗျာ)။',
    );
    _lastError = error.toString();
  }

  void _onStreamDone() {
    final code = _channel?.closeCode;
    final reason = _channel?.closeReason;
    debugPrint('[LiveClient] WebSocket closed - closeCode: $code, closeReason: $reason');
    if (_state != LiveSessionState.disconnected) {
      _setState(
        LiveSessionState.disconnected,
        'Gemini Live ချိတ်ဆက်မှု ပြီးဆုံးသွားပါသည် (code: $code)',
      );
    }
  }

  @override
  void dispose() {
    disconnect();
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
