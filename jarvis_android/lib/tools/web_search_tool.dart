import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'base_tool.dart';

/// Web search tool for querying live web information and facts across DuckDuckGo, Google News, and Wikipedia.
class WebSearchTool extends BaseTool {
  @override
  String get name => 'web_search';

  @override
  String get description =>
      'Search the web for up-to-date facts, answers, news, and queries. '
      'Parameter query can be keywords, names, or topics in Burmese or English.';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'query': {
            'type': 'STRING',
            'description': 'Search keywords or question (English or Burmese)',
          },
        },
        'required': ['query'],
      };

  String _cleanHtml(String text) {
    return text
        .replaceAll(RegExp(r'<[^>]*>'), '')
        .replaceAll('&quot;', '"')
        .replaceAll('&amp;', '&')
        .replaceAll('&#39;', "'")
        .replaceAll('&apos;', "'")
        .replaceAll('&lt;', '<')
        .replaceAll('&gt;', '>')
        .replaceAll('&nbsp;', ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
  }

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final query = (args['query'] as String?)?.trim() ?? '';
    if (query.isEmpty) {
      return 'ရှာဖွေမည့် အကြောင်းအရာ query မပါဝင်ပါ ခင်ဗျာ။';
    }

    final StringBuffer buffer = StringBuffer();
    final Set<String> seenTitles = {};

    // 1. DuckDuckGo HTML Mobile Search (Real web snippets without API key)
    try {
      final ddgUrl = Uri.parse(
        'https://html.duckduckgo.com/html/?q=${Uri.encodeComponent(query)}',
      );
      final ddgRes = await http.get(
        ddgUrl,
        headers: {
          'User-Agent':
              'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
          'Accept-Language': 'en-US,en;q=0.9',
        },
      ).timeout(const Duration(seconds: 5));

      if (ddgRes.statusCode == 200) {
        final body = ddgRes.body;
        // Match results by result snippets and titles
        final snippetMatches = RegExp(
          r'<a class="result__snippet"[^>]*>(.*?)<\/a>',
          dotAll: true,
        ).allMatches(body);

        final titleMatches = RegExp(
          r'<h2 class="result__title">[\s\S]*?<a[^>]*>(.*?)<\/a>',
          dotAll: true,
        ).allMatches(body);

        final snippets = snippetMatches.toList();
        final titles = titleMatches.toList();

        for (int i = 0; i < snippets.length && i < 3; i++) {
          final snippetText = _cleanHtml(snippets[i].group(1) ?? '');
          final titleText = i < titles.length ? _cleanHtml(titles[i].group(1) ?? '') : '';
          if (snippetText.isNotEmpty) {
            final key = titleText.toLowerCase();
            if (key.isNotEmpty && !seenTitles.contains(key)) {
              seenTitles.add(key);
              buffer.writeln('• ${titleText.isNotEmpty ? "$titleText: " : ""}$snippetText');
            } else if (key.isEmpty) {
              buffer.writeln('• $snippetText');
            }
          }
        }
      }
    } catch (e) {
      debugPrint('[WebSearchTool] DDG search error: $e');
    }

    // 2. Google News RSS Search (Latest breaking news and live updates)
    final isNewsQuery = query.toLowerCase().contains('news') ||
        query.contains('သတင်း') ||
        query.toLowerCase().contains('today') ||
        buffer.isEmpty;

    if (isNewsQuery) {
      try {
        final newsUrl = Uri.parse(
          'https://news.google.com/rss/search?q=${Uri.encodeComponent(query)}&hl=en-US&gl=US&ceid=US:en',
        );
        final newsRes = await http.get(newsUrl).timeout(const Duration(seconds: 5));
        if (newsRes.statusCode == 200) {
          final body = newsRes.body;
          final itemMatches = RegExp(
            r'<item>[\s\S]*?<title>(.*?)<\/title>[\s\S]*?<description>(.*?)<\/description>',
            dotAll: true,
          ).allMatches(body);

          int newsCount = 0;
          for (final m in itemMatches) {
            if (newsCount >= 3) break;
            final rawTitle = m.group(1) ?? '';
            final rawDesc = m.group(2) ?? '';
            final cleanTitle = _cleanHtml(rawTitle);
            final cleanDesc = _cleanHtml(rawDesc);

            final key = cleanTitle.toLowerCase();
            if (cleanTitle.isNotEmpty && !seenTitles.contains(key)) {
              seenTitles.add(key);
              buffer.writeln('• [သတင်း] $cleanTitle: $cleanDesc');
              newsCount++;
            }
          }
        }
      } catch (e) {
        debugPrint('[WebSearchTool] Google News error: $e');
      }
    }

    // 3. Wikipedia Search API (General facts & knowledge)
    if (buffer.length < 150) {
      try {
        final wikiUrl = Uri.parse(
          'https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${Uri.encodeComponent(query)}&format=json&utf8=1&srlimit=2',
        );
        final wikiRes = await http.get(wikiUrl).timeout(const Duration(seconds: 4));
        if (wikiRes.statusCode == 200) {
          final data = jsonDecode(wikiRes.body);
          final searchItems = data['query']?['search'] as List?;
          if (searchItems != null && searchItems.isNotEmpty) {
            for (final item in searchItems) {
              final title = item['title'] as String? ?? '';
              final snippet = _cleanHtml(item['snippet'] as String? ?? '');
              final key = title.toLowerCase();
              if (title.isNotEmpty && snippet.isNotEmpty && !seenTitles.contains(key)) {
                seenTitles.add(key);
                buffer.writeln('• [$title]: $snippet');
              }
            }
          }
        }
      } catch (e) {
        debugPrint('[WebSearchTool] Wikipedia error: $e');
      }
    }

    if (buffer.isEmpty) {
      return "'$query' နှင့် ပတ်သက်သည့် အချက်အလက်ကို အင်တာနက်ရှာဖွေမှုတွင် တိုက်ရိုက် မတွေ့ရှိရပါ ခင်ဗျာ။";
    }

    return "<<<UNTRUSTED source=web>>>\n${buffer.toString().trim()}\n<<<END UNTRUSTED>>>";
  }
}
