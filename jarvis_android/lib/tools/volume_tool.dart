import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to control device audio volume.
class SetVolumeTool extends BaseTool {
  @override
  String get name => 'set_volume';

  @override
  String get description =>
      'Set or adjust phone volume level from 0 to 100 percent. '
      'Parameters: percent (integer 0-100), stream (optional string: media, ring, alarm, notification, call).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'percent': {
            'type': 'INTEGER',
            'description': 'Volume percentage from 0 to 100',
          },
          'stream': {
            'type': 'STRING',
            'description':
                'Volume stream: media, ring, alarm, notification, or call (default is media)',
          },
        },
        'required': ['percent'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final dynamic rawPercent = args['percent'];
    int percent = 50;
    if (rawPercent is int) {
      percent = rawPercent;
    } else if (rawPercent is num) {
      percent = rawPercent.toInt();
    } else if (rawPercent is String) {
      percent = int.tryParse(rawPercent) ?? 50;
    }

    final stream = (args['stream'] as String?)?.trim().toLowerCase() ?? 'media';
    return await DeviceChannel.setVolume(percent, stream: stream);
  }
}
