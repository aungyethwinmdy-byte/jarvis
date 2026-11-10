import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to make direct cellular phone calls to contacts or phone numbers
/// with optional operator routing (e.g. MPT, Mytel, Atom, Ooredoo, SIM 1, SIM 2).
class MakePhoneCallTool extends BaseTool {
  @override
  String get name => 'make_phone_call';

  @override
  String get description =>
      'Make a direct cellular phone call to a recipient (contact name or phone number) '
      'using an optional specific SIM operator (e.g. "mpt", "mytel", "atom", "ooredoo", "sim1", "sim2"). '
      'Parameters: recipient (string, required - contact name like "mother", "mom", "အမေ", "အဖေ", or direct phone number), '
      'sim_operator (string, optional - operator to route the call through, such as "mpt", "mytel", "atom", "ooredoo", "sim1", "sim2"). '
      'STRICT: Use when the user asks to place a phone call ("ဖုန်းခေါ်ပေးပါ", "ဖုန်းဆက်ပေးပါ", "call", "make a phone call", "mother ဆီကို mpt နဲ့ ဖုန်းခေါ်ပေးပါ").';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'recipient': {
            'type': 'STRING',
            'description':
                'The contact name or phone number to call (e.g. "mother", "mom", "အမေ", "အဖေ", "09259001117").',
          },
          'sim_operator': {
            'type': 'STRING',
            'description':
                'Optional SIM operator to place the call: "mpt", "mytel", "atom", "ooredoo", "sim1", "sim2".',
          },
        },
        'required': ['recipient'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final dynamic rawRecipient = args['recipient'];
    final dynamic rawSimOp =
        args['sim_operator'] ?? args['simOperator'] ?? args['operator'];

    final recipient = rawRecipient?.toString().trim() ?? '';
    final simOperator = rawSimOp?.toString().trim();

    if (recipient.isEmpty) {
      return 'ဖုန်းခေါ်ဆိုရန် လက်ခံမည့်သူ သို့မဟုတ် ဖုန်းနံပါတ် မပါရှိပါ ခင်ဗျာ။';
    }

    return await DeviceChannel.makePhoneCall(
      recipient: recipient,
      simOperator:
          (simOperator != null && simOperator.isNotEmpty) ? simOperator : null,
    );
  }
}
