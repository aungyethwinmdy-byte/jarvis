import 'package:flutter/foundation.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

@pragma('vm:entry-point')
void startForegroundCallback() {
  FlutterForegroundTask.setTaskHandler(_JarvisForegroundTaskHandler());
}

class _JarvisForegroundTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {
    debugPrint('[ForegroundService] Started at $timestamp by $starter');
  }

  @override
  void onRepeatEvent(DateTime timestamp) {}

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {
    debugPrint('[ForegroundService] Destroyed at $timestamp (isTimeout: $isTimeout)');
  }
}

/// Manages Android Foreground Service for persistent background wake word listening.
class BackgroundService {
  static bool _isInitialized = false;

  /// Initialize foreground task settings
  static void initialize() {
    if (_isInitialized) return;

    FlutterForegroundTask.initCommunicationPort();

    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'jarvis_wake_word_channel',
        channelName: 'Jarvis Wake Word Service',
        channelDescription: 'Foreground service for listening to Hey Jarvis wake word',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
      ),
      iosNotificationOptions: const IOSNotificationOptions(
        showNotification: false,
        playSound: false,
      ),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.repeat(5000),
        autoRunOnBoot: false,
        autoRunOnMyPackageReplaced: false,
        allowWakeLock: true,
        allowWifiLock: true,
      ),
    );

    _isInitialized = true;
  }

  /// Start foreground listening service with persistent notification:
  /// "Jarvis is listening for Hey Jarvis"
  static Future<bool> start() async {
    initialize();

    if (await FlutterForegroundTask.isRunningService) {
      return true;
    }

    final result = await FlutterForegroundTask.startService(
      serviceId: 256,
      notificationTitle: 'JARVIS',
      notificationText: 'Jarvis is listening for Hey Jarvis',
      serviceTypes: [ForegroundServiceTypes.microphone],
      callback: startForegroundCallback,
    );

    debugPrint('[ForegroundService] Start service result: $result');
    return result is ServiceRequestSuccess;
  }

  /// Stop foreground listening service
  static Future<bool> stop() async {
    if (await FlutterForegroundTask.isRunningService) {
      final result = await FlutterForegroundTask.stopService();
      debugPrint('[ForegroundService] Stop service result: $result');
      return result is ServiceRequestSuccess;
    }
    return true;
  }

  /// Check if foreground service is actively running
  static Future<bool> isRunning() async {
    return await FlutterForegroundTask.isRunningService;
  }

  /// Request battery optimization exemption
  static Future<bool> requestBatteryOptimization() async {
    return await FlutterForegroundTask.requestIgnoreBatteryOptimization();
  }

  /// Open system battery optimization settings
  static Future<bool> openBatteryOptimizationSettings() async {
    return await FlutterForegroundTask.openIgnoreBatteryOptimizationSettings();
  }

  /// Check whether battery optimization is already disabled
  static Future<bool> isBatteryOptimizationIgnored() async {
    return await FlutterForegroundTask.isIgnoringBatteryOptimizations;
  }
}
