import 'package:flutter/foundation.dart';
import '../audio/audio_service.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to start or stop native voice recording on-demand.
class RecordAudioTool extends BaseTool {
  final AudioService? _audioService;

  RecordAudioTool({AudioService? audioService}) : _audioService = audioService;

  @override
  String get name => 'record_audio';

  @override
  String get description =>
      'Start or stop audio voice recording on the device using native MediaRecorder. '
      'Parameter: action ("start" to begin recording, "stop" to finish and save audio file). '
      'CRITICAL: Call record_audio(action: "start") whenever user asks to record voice/audio/sound, including '
      '"အသံဖမ်းပေးပါ", "ဖမ်းပေးပါ", "အသံဖမ်း", "အသံသွင်းပေးပါ", "recoder ဖွင့်ပြီးအသံဖမ်းပေးပါ", "recorder", "အသံဖမ်းစတင်ပါ", "record voice", "record audio". '
      'Call record_audio(action: "stop") when user asks to stop recording: "ရပ်ပေးပါ", "အသံဖမ်းတာ ရပ်ပေးပါ", "ပိတ်ပေးပါ", "တော်ပြီ", "ရပ်မယ်", "stop".';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'action': {
            'type': 'STRING',
            'description':
                'Action to perform: "start" to begin recording, "stop" to finish recording',
          },
        },
        'required': ['action'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final action = (args['action'] ??
            args['command'] ??
            args['state'] ??
            'start')
        .toString()
        .trim();
    debugPrint('[RecordAudioTool] Executing record_audio with action: "$action"');

    final audio = _audioService ?? AudioService.instance;
    final act = action.toLowerCase();

    if (act == 'start' || act == 'record' || act.contains('စတင်') || act.contains('ဖွင့်')) {
      // 1. Temporarily pause Live's mic stream to release hardware microphone
      bool micStopped = false;
      try {
        debugPrint('[RecordAudioTool] Step 1: Pausing Live mic stream before MediaRecorder start...');
        await audio?.stopRecording();
        micStopped = !(audio?.isRecording ?? false);
        debugPrint('[RecordAudioTool] Step 1 Result: Live mic stopped: $micStopped (audioService.isRecording: ${audio?.isRecording})');
      } catch (e) {
        debugPrint('[RecordAudioTool] Step 1 Error pausing Live mic stream: $e');
      }

      // 2 & 3 & 4. Start Jarvis native MediaRecorder and verify isRecording == true
      debugPrint('[RecordAudioTool] Step 2 & 3: Invoking DeviceChannel.manageAudioRecording("start")...');
      final res = await DeviceChannel.manageAudioRecording('start');
      debugPrint('[RecordAudioTool] Step 4 Native Start Result: "$res"');

      // 5. If failed to start, resume Live mic immediately
      if (!res.contains('စဖမ်းနေပါပြီ') || res.contains('အသံဖမ်းမရပါ')) {
        debugPrint('[RecordAudioTool] Start failed or not confirmed. Resuming Live mic immediately...');
        try {
          await audio?.startRecording(stopActivePlayback: false);
        } catch (_) {}
      }

      return res;
    } else {
      // 1. Stop native MediaRecorder, verify file and save
      debugPrint('[RecordAudioTool] Stop Step 1: Invoking DeviceChannel.manageAudioRecording("stop")...');
      final res = await DeviceChannel.manageAudioRecording('stop');
      debugPrint('[RecordAudioTool] Stop Step 2 Native Result: "$res"');

      // 2. Resume Live's mic stream
      try {
        debugPrint('[RecordAudioTool] Resuming Live mic stream...');
        await audio?.startRecording(stopActivePlayback: false);
        debugPrint('[RecordAudioTool] Live mic stream resumed: ${audio?.isRecording}');
      } catch (e) {
        debugPrint('[RecordAudioTool] Error resuming Live mic stream: $e');
      }

      return res;
    }
  }
}
