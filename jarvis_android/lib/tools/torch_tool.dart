import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to control device flashlight (Torch).
class ToggleTorchTool extends BaseTool {
  @override
  String get name => 'toggle_torch';

  @override
  String get description =>
      'Turn the physical phone flashlight/torch on or off. '
      'Parameter: enable (boolean, true to turn on, false to turn off). '
      'STRICT: Use ONLY for flashlight requests ("ဓာတ်မီးဖွင့်ပေးပါ", "မီးထိုးပေးပါ", "ဓာတ်မီးပိတ်ပေးပါ", "ဓာတ်မီး"). '
      'NEVER call toggle_torch for voice, audio, sound, or recording requests ("အသံဖမ်းပေးပါ", "ဖမ်းပေးပါ", "အသံသွင်း", "record audio")!';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'enable': {
            'type': 'BOOLEAN',
            'description': 'True to turn on flashlight, false to turn off',
          },
        },
        'required': ['enable'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final dynamic rawEnable = args['enable'];
    bool enable = true;
    if (rawEnable is bool) {
      enable = rawEnable;
    } else if (rawEnable is String) {
      enable = rawEnable.toLowerCase() == 'true' || rawEnable == '1';
    }
    return await DeviceChannel.toggleTorch(enable);
  }
}
