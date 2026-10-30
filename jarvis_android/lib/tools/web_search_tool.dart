import 'dart:convert';
import 'package:http/http.dart' as http;
import 'base_tool.dart';

/// Web search tool for querying live web information and facts without external API keys.
class WebSearchTool extends BaseTool {
  @override
  String get name => 'web_search';

  @override
  String get description =>
      'Search the web for up-to-date facts, answers, news, and queries. '
      'Parameter query should be in English or transliterated keywords for best search matching.';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'query': {
            'type': 'STRING',
            'description': 'Search keywords or question in English',
          },
        },
        'required': ['query'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final query = (args['query'] as String?)?.trim() ?? '';
    if (query.isEmpty) {
      return 'ရှာဖွေမည့် အကြောင်းအရာ query မပါဝင်ပါ ခင်ဗျာ။';
    }

    final StringBuffer buffer = StringBuffer();

    // 1. DuckDuckGo Instant Answer
    try {
      final ddgUrl = Uri.parse(
        'https://api.duckduckgo.com/?q=${Uri.encodeComponent(query)}&format=json&no_html=1&skip_disambig=1',
      );
      final ddgRes = await http.get(ddgUrl).timeout(const Duration(seconds: 5));
      if (ddgRes.statusCode == 200) {
        final data = jsonDecode(ddgRes.body);
        final abstractText = data['AbstractText'] as String?;
        final heading = data['Heading'] as String?;
        if (abstractText != null && abstractText.isNotEmpty) {
          buffer.writeln('[DuckDuckGo Info]: $heading - $abstractText');
        }
      }
    } catch (_) {}

    // 2. Wikipedia Search API
    try {
      final wikiUrl = Uri.parse(
        'https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${Uri.encodeComponent(query)}&format=json&utf8=1&srlimit=2',
      );
      final wikiRes = await http.get(wikiUrl).timeout(const Duration(seconds: 5));
      if (wikiRes.statusCode == 200) {
        final data = jsonDecode(wikiRes.body);
        final searchItems = data['query']?['search'] as List?;
        if (searchItems != null && searchItems.isNotEmpty) {
          for (final item in searchItems) {
            final title = item['title'];
            final snippet = (item['snippet'] as String? ?? '')
                .replaceAll(RegExp(r'<[^>]*>'), '');
            buffer.writeln('[$title]: $snippet');
          }
        }
      }
    } catch (_) {}

    if (buffer.isEmpty) {
      return "'$query' နှင့် ပတ်သက်သည့် အချက်အလက်ကို အင်တာနက်ရှာဖွေမှုတွင် တိုက်ရိုက် မတွေ့ရှိရပါ ခင်ဗျာ။";
    }

    return "<<<UNTRUSTED source=web>>>\n${buffer.toString().trim()}\n<<<END UNTRUSTED>>>";
  }
}
