import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Reminder tool that sets reliable Android notifications on the phone.
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
            'description':
                'Minutes from now when the reminder should trigger (e.g. 5, 10, 30)',
          },
        },
        'required': ['title', 'in_minutes'],
      };

  Future<void> _ensureInitialized() async {
    if (_isInitialized) return;

    try {
      const androidSettings =
          AndroidInitializationSettings('@mipmap/ic_launcher');
      const initSettings = InitializationSettings(android: androidSettings);

      await _notificationsPlugin.initialize(initSettings);

      final androidImpl = _notificationsPlugin
          .resolvePlatformSpecificImplementation<
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
    } catch (e) {
      debugPrint('[ReminderTool] Initialization warning: $e');
    }
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

    // Schedule through native Android AlarmManager (fires reliably even in deep sleep/Doze mode)
    final nativeResult = await DeviceChannel.setReminder(title, delaySeconds);

    // If delay is very short (<= 5 seconds), also backup with in-memory notification
    if (delaySeconds <= 5) {
      Timer(Duration(seconds: delaySeconds), () async {
        try {
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
          const notificationDetails =
              NotificationDetails(android: androidDetails);
          await _notificationsPlugin.show(
            DateTime.now().millisecondsSinceEpoch ~/ 1000,
            '🔔 JARVIS သတိပေးချက်',
            title,
            notificationDetails,
          );
        } catch (e) {
          debugPrint('[ReminderTool] LocalNotification error: $e');
        }
      });
    }

    return nativeResult;
  }
}
