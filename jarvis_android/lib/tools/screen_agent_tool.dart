import 'package:flutter/foundation.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to inspect current screen content and read feeds (e.g. Facebook feed, messages).
class InspectScreenTool extends BaseTool {
  @override
  String get name => 'inspect_screen';

  @override
  String get description =>
      'Inspect and extract all visible text and interactive elements currently shown on the phone screen. '
      'Use when the user asks what is on screen or to inspect a feed (e.g. "Facebook ဖွင့်ပြီး ဘာတွေထူးလဲ ငါ့ကိုပြောပါ", "မျက်နှာပြင်မှာ ဘာတွေရှိလဲ").';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {},
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    debugPrint('[InspectScreenTool] Executing inspect_screen');
    return await DeviceChannel.inspectScreen();
  }
}

/// Tool to control screen elements autonomously (click, send, scroll, type, back, home).
class ControlScreenTool extends BaseTool {
  @override
  String get name => 'control_screen';

  @override
  String get description =>
      'Perform autonomous UI actions on the screen: click a button/element, click the send button, scroll up/down, type text into input fields, go back, or go home. '
      'Parameters: action ("click", "send", "input", "scroll_down", "scroll_up", "back", "home"), target (text to click or type), field (optional input field hint/id).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'action': {
            'type': 'STRING',
            'description':
                'Action to perform: "click", "send", "input", "scroll_down", "scroll_up", "back", or "home"',
          },
          'target': {
            'type': 'STRING',
            'description':
                'Text of element to click or text to enter into input field (optional for scroll, back, home, send)',
          },
          'field': {
            'type': 'STRING',
            'description':
                'Optional hint, description, or id of the input field to focus and type into (e.g. "search", "message")',
          },
        },
        'required': ['action'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final action = (args['action'] ?? 'click').toString().trim();
    final target = (args['target'] ?? args['text'] ?? args['query'])?.toString().trim();
    final field = (args['field'] ?? args['input_field'])?.toString().trim();

    debugPrint('[ControlScreenTool] Executing control_screen action: $action, target: $target, field: $field');
    return await DeviceChannel.controlScreen(
      action: action,
      target: target,
      field: field,
    );
  }
}
