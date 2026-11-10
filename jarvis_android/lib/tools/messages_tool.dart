import 'package:flutter/foundation.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to check incoming messages from Telegram, Viber, Facebook, Messenger, etc.
class CheckMessagesTool extends BaseTool {
  @override
  String get name => 'check_messages';

  @override
  String get description =>
      'Check for newly arrived messages or notifications from messaging apps such as Telegram, Viber, Facebook, Messenger. '
      'Parameter: app (optional string: "telegram", "viber", "facebook", "messenger", or "all").';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'app': {
            'type': 'STRING',
            'description':
                'Specific app to check messages for: "telegram", "viber", "facebook", "messenger", or "all"',
          },
        },
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final app = (args['app'] ?? args['app_name'] ?? args['query'])?.toString().trim();
    debugPrint('[CheckMessagesTool] Executing check_messages for app: "$app"');
    return await DeviceChannel.checkMessages(app: app);
  }
}

/// Tool to send chat or text messages inside installed messaging apps autonomously.
class SendAppMessageTool extends BaseTool {
  @override
  String get name => 'send_app_message';

  @override
  String get description =>
      'Draft or send a chat message inside an installed messaging app (Telegram, Viber, Facebook Messenger, WhatsApp) '
      'by opening the app, searching for the recipient/contact, typing the message, and holding as draft for user confirmation. '
      'Parameters: app (string: "telegram", "viber", "facebook", "messenger", "whatsapp"), '
      'recipient (optional string: contact name or person), '
      'message (string: message body to send), '
      'auto_send (optional boolean, default false: prepares draft, types message into input field and awaits user confirmation; set true ONLY when user explicitly confirms to send).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'app': {
            'type': 'STRING',
            'description':
                'Messaging app to open: "telegram", "viber", "facebook", "messenger", or "whatsapp"',
          },
          'recipient': {
            'type': 'STRING',
            'description': 'Name or contact to search and send message to',
          },
          'message': {
            'type': 'STRING',
            'description': 'The exact message text to type and send',
          },
          'auto_send': {
            'type': 'BOOLEAN',
            'description':
                'Whether to immediately click Send after typing (default false to hold draft for user confirmation)',
          },
        },
        'required': ['app', 'message'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final app = (args['app'] ?? args['app_name'] ?? 'telegram').toString().trim();
    final recipient = (args['recipient'] ?? args['contact'] ?? args['to'])?.toString().trim();
    final message = (args['message'] ?? args['text'] ?? args['body'] ?? '').toString().trim();
    final autoSend = args['auto_send'] == true || args['send'] == true;

    debugPrint('[SendAppMessageTool] Executing send_app_message app: $app, recipient: $recipient, message: $message, autoSend: $autoSend');
    return await DeviceChannel.sendAppMessage(
      app: app,
      recipient: recipient,
      message: message,
      autoSend: autoSend,
    );
  }
}
