import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to check device status (battery level, charging state, audio volume, ringer mode).
class GetDeviceStatusTool extends BaseTool {
  @override
  String get name => 'get_device_status';

  @override
  String get description =>
      'Check phone status including battery level percentage, charging status, plugged type, audio volume, and ringer mode.';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {},
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    return await DeviceChannel.getDeviceStatus();
  }
}
