import 'package:flutter/foundation.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to launch installed applications on the phone.
class OpenAppTool extends BaseTool {
  @override
  String get name => 'open_app';

  @override
  String get description =>
      'Open or launch an application installed on the phone by its name or package. '
      'Parameter: query (string name of the app e.g. YouTube, Chrome, Facebook, Camera, Settings, Maps).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'query': {
            'type': 'STRING',
            'description':
                'Name or package of the app to launch (e.g. YouTube, Chrome, Facebook, Camera, Settings, Maps)',
          },
        },
        'required': ['query'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final query = (args['query'] ??
            args['app_name'] ??
            args['appName'] ??
            args['name'] ??
            args['package'] ??
            args['package_name'] ??
            args['target'] ??
            args['app'])
        ?.toString()
        .trim() ?? '';
    debugPrint('[OpenAppTool] Executing open_app with query: "$query", raw args: $args');
    if (query.isEmpty) {
      return 'ဖွင့်မည့် အက်ပ်အမည် မပါဝင်ပါ ခင်ဗျာ။';
    }
    return await DeviceChannel.openApp(query);
  }
}
