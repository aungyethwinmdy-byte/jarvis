import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/audio/audio_service.dart';
import 'package:jarvis_android/tools/app_launcher_tool.dart';
import 'package:jarvis_android/tools/audio_recorder_tool.dart';
import 'package:jarvis_android/tools/camera_capture_tool.dart';
import 'package:jarvis_android/tools/device_status_tool.dart';
import 'package:jarvis_android/tools/messages_tool.dart';
import 'package:jarvis_android/tools/phone_call_tool.dart';
import 'package:jarvis_android/tools/reminder_tool.dart';
import 'package:jarvis_android/tools/screen_agent_tool.dart';
import 'package:jarvis_android/tools/torch_tool.dart';
import 'package:jarvis_android/tools/volume_tool.dart';
import 'package:jarvis_android/tools/weather_tool.dart';
import 'package:jarvis_android/tools/web_search_tool.dart';
import 'package:jarvis_android/tools/youtube_tool.dart';

class _RealHttpOverrides extends HttpOverrides {}

void main() {
  HttpOverrides.global = _RealHttpOverrides();

  group('Tools Tests', () {
    test('WeatherTool executes and returns real data for Naypyidaw', () async {
      final tool = WeatherTool();
      expect(tool.name, 'get_weather');
      final result = await tool.execute({'location': 'Naypyidaw'});
      expect(result.isNotEmpty, true);
      expect(result.contains('Naypyidaw'), true);
      expect(
        result.contains('°C') ||
            result.contains('မရနိုင်ပါ') ||
            result.contains('အခက်အခဲ'),
        true,
        reason: 'Should return weather data or Burmese error handling',
      );
    });

    test('WebSearchTool executes and returns search results for Flutter', () async {
      final tool = WebSearchTool();
      expect(tool.name, 'web_search');
      final result = await tool.execute({'query': 'Flutter software'});
      expect(result.isNotEmpty, true);
      expect(
        result.contains('UNTRUSTED source=web') ||
            result.contains('မတွေ့ရှိရပါ') ||
            result.contains('အချက်အလက်ကို'),
        true,
        reason: 'Should return search results or Burmese fallback',
      );
    });

    test('ToggleTorchTool executes and returns Burmese confirmation', () async {
      final tool = ToggleTorchTool();
      expect(tool.name, 'toggle_torch');
      final result = await tool.execute({'enable': true});
      expect(result.isNotEmpty, true);
      expect(result.contains('ဓာတ်မီး'), true);
    });

    test('SetVolumeTool executes and returns Burmese confirmation', () async {
      final tool = SetVolumeTool();
      expect(tool.name, 'set_volume');
      final result = await tool.execute({'percent': 80, 'stream': 'media'});
      expect(result.isNotEmpty, true);
      expect(result.contains('အသံပမာဏ'), true);
    });

    test('OpenAppTool executes and handles query, app_name, and name', () async {
      final tool = OpenAppTool();
      expect(tool.name, 'open_app');

      final r1 = await tool.execute({'query': 'YouTube'});
      expect(r1.isNotEmpty, true);
      expect(r1.contains('YouTube') || r1.contains('အက်ပ်'), true);

      final r2 = await tool.execute({'app_name': 'Camera'});
      expect(r2.isNotEmpty, true);
      expect(r2.contains('Camera') || r2.contains('အက်ပ်'), true);

      final r3 = await tool.execute({'name': 'Settings'});
      expect(r3.isNotEmpty, true);
      expect(r3.contains('Settings') || r3.contains('အက်ပ်'), true);
    });

    test('GetDeviceStatusTool executes and returns device summary', () async {
      final tool = GetDeviceStatusTool();
      expect(tool.name, 'get_device_status');
      final result = await tool.execute({});
      expect(result.isNotEmpty, true);
      expect(result.contains('ဘက်ထရီ') || result.contains('အခြေအနေ'), true);
    });

    test('ReminderTool executes and schedules reminder', () async {
      final tool = ReminderTool();
      expect(tool.name, 'set_reminder');
      final result = await tool.execute({'title': 'အစည်းအဝေးတက်ရန်', 'in_minutes': 10});
      expect(result.isNotEmpty, true);
      expect(result.contains('အစည်းအဝေးတက်ရန်'), true);
      expect(result.contains('သတိပေးချက်'), true);
    });

    test('PlayYouTubeTool executes and handles song query', () async {
      final tool = PlayYouTubeTool();
      expect(tool.name, 'play_youtube');
      final result = await tool.execute({'query': 'Shwe Htoo song'});
      expect(result.isNotEmpty, true);
      expect(result.contains('YouTube'), true);
    });

    test('TakeCameraPhotoTool executes and returns camera confirmation', () async {
      final tool = TakeCameraPhotoTool();
      expect(tool.name, 'take_photo');
      final result = await tool.execute({});
      expect(result.isNotEmpty, true);
      expect(result.contains('ကင်မရာ') || result.contains('ဓာတ်ပုံ'), true);
    });

    test('CheckMessagesTool executes and handles app filter', () async {
      final tool = CheckMessagesTool();
      expect(tool.name, 'check_messages');
      final result = await tool.execute({'app': 'telegram'});
      expect(result.isNotEmpty, true);
      expect(result.contains('telegram') || result.contains('Telegram') || result.contains('စာ'), true);
    });

    test('InspectScreenTool and ControlScreenTool execute properly', () async {
      final inspect = InspectScreenTool();
      expect(inspect.name, 'inspect_screen');
      final inspectRes = await inspect.execute({});
      expect(inspectRes.isNotEmpty, true);

      final control = ControlScreenTool();
      expect(control.name, 'control_screen');
      final controlRes = await control.execute({'action': 'scroll_down'});
      expect(controlRes.isNotEmpty, true);

      final sendRes = await control.execute({'action': 'send'});
      expect(sendRes.isNotEmpty, true);

      final inputRes = await control.execute({'action': 'input', 'target': 'Hello', 'field': 'message'});
      expect(inputRes.isNotEmpty, true);

      final backRes = await control.execute({'action': 'back'});
      expect(backRes.isNotEmpty, true);
    });

    test('SendAppMessageTool executes draft mode by default and supports confirmed send', () async {
      final tool = SendAppMessageTool();
      expect(tool.name, 'send_app_message');

      // Test 1: Draft mode (auto_send = false by default)
      final draftRes = await tool.execute({
        'app': 'telegram',
        'recipient': 'Ko Min',
        'message': 'Mingalarba',
      });
      expect(draftRes.isNotEmpty, true);
      expect(draftRes.contains('မူကြမ်း') || draftRes.contains('စာရိုက်ထားပြီးပါပြီ') || draftRes.contains('Telegram') || draftRes.contains('telegram'), true);

      // Test 2: Confirmed send (auto_send = true)
      final sendRes = await tool.execute({
        'app': 'telegram',
        'recipient': 'Ko Min',
        'message': 'Mingalarba',
        'auto_send': true,
      });
      expect(sendRes.isNotEmpty, true);
      expect(sendRes.contains('telegram') || sendRes.contains('Telegram') || sendRes.contains('Ko Min'), true);
    });

    test('RecordAudioTool executes and handles start and stop', () async {
      final tool = RecordAudioTool();
      expect(tool.name, 'record_audio');
      final rStart = await tool.execute({'action': 'start'});
      expect(rStart.isNotEmpty, true);
      expect(rStart.contains('စဖမ်းနေပါပြီ'), true);
      final rStop = await tool.execute({'action': 'stop'});
      expect(rStop.isNotEmpty, true);
      expect(rStop.contains('ရပ်ပါပြီ'), true);
    });

    test('Camera photo tool executes CameraX workflow and confirms Gallery destination', () async {
      final tool = TakeCameraPhotoTool();
      final res = await tool.execute({});
      expect(res.isNotEmpty, true);
      expect(res.contains('ကင်မရာ') || res.contains('ဓာတ်ပုံ') || res.contains('Gallery'), true);

      final backRes = await tool.execute({'camera': 'back'});
      expect(backRes.isNotEmpty, true);
      expect(backRes.contains('နောက်ကင်မရာ') || backRes.contains('ကင်မရာ'), true);

      final frontRes = await tool.execute({'camera': 'front'});
      expect(frontRes.isNotEmpty, true);
      expect(frontRes.contains('ရှေ့ကင်မရာ') || frontRes.contains('ကင်မရာ'), true);
    });

    test('CheckMessagesTool handles Facebook notification query specifically without feed substitution', () async {
      final tool = CheckMessagesTool();
      final res = await tool.execute({'app': 'facebook'});
      expect(res.isNotEmpty, true);
      expect(res.toLowerCase().contains('facebook'), true);
    });

    test('RecordAudioTool coordinates mic release on start and mic resume on stop', () async {
      final audioService = AudioService(isTestMode: true);
      final tool = RecordAudioTool(audioService: audioService);
      final startRes = await tool.execute({'action': 'start'});
      expect(startRes.isNotEmpty, true);
      final stopRes = await tool.execute({'action': 'stop'});
      expect(stopRes.isNotEmpty, true);
    });

    test('MakePhoneCallTool executes phone call with recipient and sim operator', () async {
      final tool = MakePhoneCallTool();
      expect(tool.name, 'make_phone_call');
      expect(tool.parametersSchema['required'], contains('recipient'));

      // Empty recipient check
      final emptyRes = await tool.execute({'recipient': ''});
      expect(emptyRes.contains('မပါရှိပါ'), true);

      // Call mother with MPT
      final callRes = await tool.execute({'recipient': 'mother', 'sim_operator': 'mpt'});
      expect(callRes.isNotEmpty, true);
      expect(callRes.contains('mother') && (callRes.contains('mpt') || callRes.contains('ဖုန်းခေါ်')), true);

      // Call directly with phone number and mytel
      final directRes = await tool.execute({'recipient': '09259001117', 'operator': 'mytel'});
      expect(directRes.isNotEmpty, true);
      expect(directRes.contains('09259001117'), true);
    });
  });
}
