import 'package:flutter/foundation.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to open the camera and take a photo automatically using CameraX.
class TakeCameraPhotoTool extends BaseTool {
  @override
  String get name => 'take_photo';

  @override
  String get description =>
      'Open the phone camera viewfinder and take a photograph automatically using CameraX. '
      'Parameter: camera ("back" for rear camera, "front" for front/selfie camera; defaults to "back"). '
      'Use when asked to take a photo ("နောက်ကင်မရာနဲ့ ရိုက်ပေးပါ", "back camera", "ကင်မရာဖွင့်ပြီး ဓာတ်ပုံရိုက်ပေးပါ", "ဓာတ်ပုံရိုက်ပေးပါ", "ရှေ့ကင်မရာနဲ့ ရိုက်ပေးပါ", "selfie").';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'camera': {
            'type': 'STRING',
            'description': 'Camera lens to use: "back" (rear camera, default) or "front" (front camera / selfie)',
          },
        },
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final camera = (args['camera'] ?? args['lens'] ?? 'back').toString();
    debugPrint('[TakeCameraPhotoTool] Executing take_photo with camera: "$camera"');
    return await DeviceChannel.takeCameraPhoto(camera: camera);
  }
}
