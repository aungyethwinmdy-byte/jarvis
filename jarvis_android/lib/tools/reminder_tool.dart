import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'base_tool.dart';

/// Reminder tool that sets local Android notifications on the phone.
class ReminderTool extends BaseTool {
  final FlutterLocalNotificationsPlugin _notificationsPlugin =
      FlutterLocalNotificationsPlugin();
  bool _isInitialized = false;

  @override
  String get name => 'set_reminder';

  @override
  String get description =>
      'Set a local notification reminder on the user phone after a specific number of minutes. '
      'Parameters: title (string summary of task), in_minutes (integer delay in minutes).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'title': {
            'type': 'STRING',
            'description': 'Title or task description for the reminder',
          },
          'in_minutes': {
            'type': 'INTEGER',
            'description': 'Minutes from now when the reminder should trigger (e.g. 5, 10, 30)',
          },
        },
        'required': ['title', 'in_minutes'],
      };

  Future<void> _ensureInitialized() async {
    if (_isInitialized) return;

    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidSettings);

    await _notificationsPlugin.initialize(initSettings);

    // Request notification permissions for Android 13+ and register high-priority channel
    final androidImpl = _notificationsPlugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    if (androidImpl != null) {
      await androidImpl.requestNotificationsPermission();
      const channel = AndroidNotificationChannel(
        'jarvis_reminders_channel',
        'Jarvis Reminders',
        description: 'Local notifications set by Jarvis Assistant',
        importance: Importance.max,
        enableVibration: true,
        playSound: true,
      );
      await androidImpl.createNotificationChannel(channel);
    }

    _isInitialized = true;
  }

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    await _ensureInitialized();

    final title = (args['title'] as String?)?.trim() ?? 'သတိပေးချက်';
    final dynamic rawMinutes = args['in_minutes'];
    int inMinutes = 5;
    if (rawMinutes is int) {
      inMinutes = rawMinutes;
    } else if (rawMinutes is num) {
      inMinutes = rawMinutes.toInt();
    } else if (rawMinutes is String) {
      inMinutes = int.tryParse(rawMinutes) ?? 5;
    }

    int delaySeconds = inMinutes > 0 ? inMinutes * 60 : 3;
    if (args.containsKey('in_seconds')) {
      final s = args['in_seconds'];
      if (s is num) {
        delaySeconds = s.toInt();
      } else if (s is String) {
        delaySeconds = int.tryParse(s) ?? 5;
      }
    }

    final notificationId = DateTime.now().millisecondsSinceEpoch ~/ 1000;

    const androidDetails = AndroidNotificationDetails(
      'jarvis_reminders_channel',
      'Jarvis Reminders',
      channelDescription: 'Local notifications set by Jarvis Assistant',
      importance: Importance.max,
      priority: Priority.high,
      showWhen: true,
      enableVibration: true,
      playSound: true,
      icon: '@mipmap/ic_launcher',
    );
    const notificationDetails = NotificationDetails(android: androidDetails);

    // Schedule using Timer
    Timer(Duration(seconds: delaySeconds), () async {
      try {
        await _notificationsPlugin.show(
          notificationId,
          '🔔 JARVIS သတိပေးချက်',
          title,
          notificationDetails,
        );
        debugPrint('[ReminderTool] Notification posted successfully: $title');
      } catch (e) {
        debugPrint('[ReminderTool] Error showing notification: $e');
      }
    });

    final timeDesc = delaySeconds < 60
        ? '$delaySeconds စက္ကန့်'
        : '${delaySeconds ~/ 60} မိနစ်';

    return "ဆရာ့အတွက် '$title' သတိပေးချက်ကို $timeDesc အကြာတွင် ဖုန်းပေါ်၌ သတ်မှတ်ပေးထားပြီး ဖြစ်ပါသည် ခင်ဗျာ။";
  }
}
