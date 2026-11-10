import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Platform channel bridge to native Android device controls.
class DeviceChannel {
  static const MethodChannel _channel =
      MethodChannel('com.jarvis.android/device_control');

  static void Function(String state)? onCallStateChanged;
  static void Function(String focus)? onAudioFocusChanged;
  static bool _initialized = false;

  /// Initialize bidirectional platform method channel handlers.
  static void initialize() {
    if (_initialized) return;
    _initialized = true;
    _channel.setMethodCallHandler((call) async {
      try {
        switch (call.method) {
          case 'onCallStateChanged':
            final state = call.arguments is Map
                ? (call.arguments['state'] as String? ?? 'IDLE')
                : 'IDLE';
            debugPrint('[DeviceChannel] Received onCallStateChanged: $state');
            onCallStateChanged?.call(state);
            break;
          case 'onAudioFocusChanged':
            final focus = call.arguments is Map
                ? (call.arguments['focus'] as String? ?? 'LOSS')
                : 'LOSS';
            debugPrint('[DeviceChannel] Received onAudioFocusChanged: $focus');
            onAudioFocusChanged?.call(focus);
            break;
        }
      } catch (e) {
        debugPrint('[DeviceChannel] Error in method call handler: $e');
      }
    });
  }

  /// Query current telephony call state ('IDLE', 'RINGING', 'OFFHOOK').
  static Future<String> getCallState() async {
    if (!kIsWeb && !Platform.isAndroid) return 'IDLE';
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>('getCallState');
      return res?['state'] as String? ?? 'IDLE';
    } catch (e) {
      debugPrint('[DeviceChannel] getCallState error: $e');
      return 'IDLE';
    }
  }

  /// Request transient audio focus for voice interaction.
  static Future<bool> requestVoiceFocus() async {
    if (!kIsWeb && !Platform.isAndroid) return true;
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>('requestVoiceFocus');
      return res?['granted'] as bool? ?? false;
    } catch (e) {
      debugPrint('[DeviceChannel] requestVoiceFocus error: $e');
      return false;
    }
  }

  /// Abandon transient audio focus.
  static Future<void> abandonVoiceFocus() async {
    if (!kIsWeb && !Platform.isAndroid) return;
    try {
      await _channel.invokeMapMethod<String, dynamic>('abandonVoiceFocus');
    } catch (e) {
      debugPrint('[DeviceChannel] abandonVoiceFocus error: $e');
    }
  }

  /// Turn flashlight / torch on or off.
  static Future<String> toggleTorch(bool enable) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "ဓာတ်မီး ထိန်းချုပ်မှုသည် Android စနစ်ပေါ်တွင်သာ ရရှိနိုင်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'toggleTorch',
        {'enable': enable},
      );
      return res?['message'] as String? ??
          "ဓာတ်မီးကို ${enable ? "ဖွင့်" : "ပိတ်"}ပေးလိုက်ပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] toggleTorch error: $e');
      return "ဓာတ်မီး ထိန်းချုပ်ရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Set volume level (0-100%).
  static Future<String> setVolume(int percent, {String stream = 'media'}) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "အသံပမာဏ ထိန်းချုပ်မှုသည် Android စနစ်ပေါ်တွင်သာ ရရှိနိုင်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'setVolume',
        {'stream': stream, 'percent': percent},
      );
      return res?['message'] as String? ??
          "အသံပမာဏကို $percent% သို့ သတ်မှတ်ပေးလိုက်ပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] setVolume error: $e');
      return "အသံပမာဏ ပြောင်းလဲရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Read current volume.
  static Future<String> getVolume({String? stream}) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "လက်ရှိ မီဒီယာအသံပမာဏသည် ၇၀% ဖြစ်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'getVolume',
        {'stream': stream},
      );
      return res?['message'] as String? ??
          "အသံပမာဏကို စစ်ဆေးပြီးပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] getVolume error: $e');
      return "အသံပမာဏ စစ်ဆေးရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Open an app by name or package.
  static Future<String> openApp(String query) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "အက်ပ်ဖွင့်ခြင်းသည် Android စနစ်ပေါ်တွင်သာ ရရှိနိုင်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'openApp',
        {'query': query},
      );
      return res?['message'] as String? ??
          "'$query' အက်ပ်ကို ဖွင့်ပေးလိုက်ပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] openApp error: $e');
      return "'$query' အက်ပ်ကို ဖွင့်ရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Get device status (battery, charging, volume, ringer).
  static Future<String> getDeviceStatus() async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "လက်ရှိ ဘက်ထရီ ၈၅% ရှိပြီး အားမသွင်းပါ။ မီဒီယာ အသံပမာဏသည် ၇၀% ဖြစ်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'getDeviceStatus',
      );
      return res?['summary'] as String? ??
          "စက်ပစ္စည်း အခြေအနေကို စစ်ဆေးပြီးပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] getDeviceStatus error: $e');
      return "စက်ပစ္စည်း အခြေအနေ စစ်ဆေးရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Schedule a reminder via native Android AlarmManager.
  static Future<String> setReminder(String title, int delaySeconds) async {
    if (!kIsWeb && !Platform.isAndroid) {
      final timeDesc = delaySeconds < 60 ? '$delaySeconds စက္ကန့်' : '${delaySeconds ~/ 60} မိနစ်';
      return "ဆရာ့အတွက် '$title' သတိပေးချက်ကို $timeDesc အကြာတွင် ဖုန်းပေါ်၌ သတ်မှတ်ပေးထားပြီး ဖြစ်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'setReminder',
        {'title': title, 'delaySeconds': delaySeconds},
      );
      final timeDesc = delaySeconds < 60 ? '$delaySeconds စက္ကန့်' : '${delaySeconds ~/ 60} မိနစ်';
      return res?['message'] as String? ??
          "ဆရာ့အတွက် '$title' သတိပေးချက်ကို $timeDesc အကြာတွင် ဖုန်းပေါ်၌ တိကျစွာ သတ်မှတ်ပေးထားပြီး ဖြစ်ပါသည် ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] setReminder error: $e');
      final timeDesc = delaySeconds < 60 ? '$delaySeconds စက္ကန့်' : '${delaySeconds ~/ 60} မိနစ်';
      return "ဆရာ့အတွက် '$title' သတိပေးချက်ကို $timeDesc အကြာတွင် ဖုန်းပေါ်၌ သတ်မှတ်ပေးထားပြီး ဖြစ်ပါသည် ခင်ဗျာ။";
    }
  }

  /// Search and play songs/videos on YouTube.
  static Future<String> playYouTube(String query) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "YouTube တွင် '$query' ကို ဖွင့်ပေးလိုက်ပါပြီ ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'playYouTube',
        {'query': query},
      );
      return res?['message'] as String? ??
          "YouTube တွင် '$query' ကို ဖွင့်ပေးလိုက်ပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] playYouTube error: $e');
      return "YouTube ဖွင့်ရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Open camera and take photo automatically with requested lens ("back" or "front").
  static Future<String> takeCameraPhoto({String camera = 'back'}) async {
    if (!kIsWeb && !Platform.isAndroid) {
      final isFront = camera.toLowerCase().contains('front') || camera.contains('ရှေ့');
      final label = isFront ? 'ရှေ့ကင်မရာ (Front)' : 'နောက်ကင်မရာ (Back)';
      return "$label ကို ဖွင့်ပြီး ဓာတ်ပုံရိုက်ကူးပေးလိုက်ပါပြီ ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'takeCameraPhoto',
        {'camera': camera},
      );
      return res?['message'] as String? ??
          "ကင်မရာကို ဖွင့်ပြီး ဓာတ်ပုံရိုက်ကူးပေးလိုက်ပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] takeCameraPhoto error: $e');
      return "ကင်မရာ ဓာတ်ပုံရိုက်ရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Check incoming notifications for Telegram, Viber, Facebook, etc.
  static Future<String> checkMessages({String? app}) async {
    if (!kIsWeb && !Platform.isAndroid) {
      final appName = (app != null && app.toLowerCase().contains('face'))
          ? 'Facebook'
          : (app != null && app.toLowerCase().contains('tele'))
              ? 'Telegram'
              : (app != null && app.toLowerCase().contains('viber'))
                  ? 'Viber'
                  : (app ?? "အက်ပ်များ");
      return "လက်ရှိတွင် $appName မှ notification သို့မဟုတ် စာအသစ် မရှိသေးပါ ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'checkMessages',
        {'app': app},
      );
      return res?['summary'] as String? ??
          "လက်ရှိတွင် ${app ?? "အက်ပ်များ"} မှ စာအသစ် မရှိသေးပါ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] checkMessages error: $e');
      return "စာအသစ် စစ်ဆေးရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Inspect on-screen UI text and content.
  static Future<String> inspectScreen() async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "မျက်နှာပြင်တွင် ဖော်ပြထားသော အချက်အလက်များကို စစ်ဆေးပြီးပါပြီ ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'inspectScreen',
      );
      final textSummary = res?['textSummary'] as String? ?? '';
      if (textSummary.isNotEmpty) {
        return "မျက်နှာပြင်ပေါ်ရှိ အချက်အလက်များ:\n$textSummary";
      }
      return res?['message'] as String? ?? "မျက်နှာပြင်ပေါ်တွင် ဖတ်ရှုနိုင်သော စာသား မတွေ့ပါ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] inspectScreen error: $e');
      return "မျက်နှာပြင် အချက်အလက် စစ်ဆေးရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Autonomous screen interaction: click, send, scroll, shutter, input, back, home.
  static Future<String> controlScreen({
    required String action,
    String? target,
    String? field,
  }) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return "မျက်နှာပြင် လုပ်ဆောင်ချက် $action ပြီးမြောက်ပါသည် ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'controlScreen',
        {
          'action': action,
          'target': target,
          'field': field,
        },
      );
      return res?['message'] as String? ?? "မျက်နှာပြင် လုပ်ဆောင်ချက် $action ပြီးမြောက်ပါသည် ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] controlScreen error: $e');
      return "မျက်နှာပြင် ထိန်းချုပ်ရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Send chat message inside an installed app (Telegram, Viber, Facebook, etc.).
  /// Confirmation gate: autoSend defaults to false (draft mode).
  static Future<String> sendAppMessage({
    required String app,
    String? recipient,
    required String message,
    bool autoSend = false,
  }) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return autoSend
          ? "$app တွင် ${recipient ?? ''} ထံသို့ '$message' ဟု စာပို့ပေးလိုက်ပါပြီ ခင်ဗျာ။"
          : "မူကြမ်း: $app တွင် ${recipient ?? ''} ထံသို့ '$message' ဟု စာရိုက်ထားပြီးပါပြီ ဆရာ။ ပို့လိုက်ရမလား ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'sendAppMessage',
        {
          'app': app,
          'recipient': recipient,
          'message': message,
          'autoSend': autoSend,
        },
      );
      return res?['message'] as String? ??
          "$app တွင် စာပို့ဆောင်မှု လုပ်ဆောင်ပြီးပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] sendAppMessage error: $e');
      return "$app တွင် စာပို့ရာတွင် အခက်အခဲရှိပါသည် ခင်ဗျာ။";
    }
  }

  /// Start or stop native audio recorder.
  static Future<String> manageAudioRecording(String action) async {
    if (!kIsWeb && !Platform.isAndroid) {
      return action == "start" ? "စဖမ်းနေပါပြီ" : "ရပ်ပါပြီ၊ 10 စက္ကန့်စာ သိမ်းပြီးပါပြီ";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'manageAudioRecording',
        {'action': action},
      );
      final success = res?['success'] as bool? ?? false;
      final msg = res?['message'] as String? ?? '';
      if (!success) {
        final exception = res?['exception'] as String? ?? '';
        return msg.isNotEmpty ? msg : "အသံဖမ်းမရပါ: $exception";
      }
      return msg.isNotEmpty ? msg : (action == "start" ? "စဖမ်းနေပါပြီ" : "ရပ်ပါပြီ");
    } catch (e) {
      debugPrint('[DeviceChannel] manageAudioRecording error: $e');
      return "အသံဖမ်းမရပါ: ${e.toString()}";
    }
  }

  /// Notify Android MediaScanner to index newly saved audio or media files.
  static Future<void> scanMediaFile(String filePath) async {
    if (!kIsWeb && !Platform.isAndroid) return;
    try {
      await _channel.invokeMapMethod<String, dynamic>(
        'scanMediaFile',
        {'filePath': filePath},
      );
    } catch (e) {
      debugPrint('[DeviceChannel] scanMediaFile error: $e');
    }
  }

  /// Make a direct cellular phone call to a recipient (contact or phone number)
  /// with an optional SIM operator ("mpt", "mytel", "atom", "ooredoo", "sim1", "sim2").
  static Future<String> makePhoneCall({
    required String recipient,
    String? simOperator,
  }) async {
    if (!kIsWeb && !Platform.isAndroid) {
      final op = simOperator != null ? " ($simOperator ဖြင့်)" : "";
      return "$recipient ထံသို့$op ဖုန်းခေါ်ဆိုပေးလိုက်ပါပြီ ခင်ဗျာ။";
    }
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>(
        'makePhoneCall',
        {
          'recipient': recipient,
          'simOperator': simOperator,
        },
      );
      return res?['message'] as String? ??
          "$recipient ထံသို့ ဖုန်းခေါ်ဆိုပေးလိုက်ပါပြီ ခင်ဗျာ။";
    } catch (e) {
      debugPrint('[DeviceChannel] makePhoneCall error: $e');
      return "ဖုန်းခေါ်ဆိုရာတွင် အခက်အခဲရှိပါသည်: $e";
    }
  }

  /// Get available SIM card operators in the device.
  static Future<List<Map<String, dynamic>>> getSimOperators() async {
    if (!kIsWeb && !Platform.isAndroid) return [];
    try {
      final res = await _channel.invokeListMethod<dynamic>('getSimOperators');
      if (res == null) return [];
      return res.map((item) => Map<String, dynamic>.from(item as Map)).toList();
    } catch (e) {
      debugPrint('[DeviceChannel] getSimOperators error: $e');
      return [];
    }
  }

  /// Check if Jarvis Accessibility Service is currently active and granted.
  static Future<bool> isAccessibilityEnabled() async {
    if (!kIsWeb && !Platform.isAndroid) return true;
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>('isAccessibilityEnabled');
      return res?['enabled'] as bool? ?? false;
    } catch (e) {
      debugPrint('[DeviceChannel] isAccessibilityEnabled error: $e');
      return false;
    }
  }

  /// Open Android system Accessibility settings.
  static Future<bool> openAccessibilitySettings() async {
    if (!kIsWeb && !Platform.isAndroid) return false;
    try {
      final res = await _channel.invokeMapMethod<String, dynamic>('openAccessibilitySettings');
      return res?['success'] as bool? ?? false;
    } catch (e) {
      debugPrint('[DeviceChannel] openAccessibilitySettings error: $e');
      return false;
    }
  }
}
