import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_android/tools/weather_tool.dart';
import 'package:jarvis_android/tools/web_search_tool.dart';

class _RealHttpOverrides extends HttpOverrides {}

void main() {
  HttpOverrides.global = _RealHttpOverrides();

  group('Tools Tests', () {
    test('WeatherTool executes and returns real data for Naypyidaw', () async {
      final tool = WeatherTool();
      expect(tool.name, 'get_weather');
      final result = await tool.execute({'location': 'Naypyidaw'});
      expect(result.isNotEmpty, true);
      expect(result.contains('Naypyidaw'), true);
      expect(result.contains('°C'), true);
    });

    test('WebSearchTool executes and returns search results for Flutter', () async {
      final tool = WebSearchTool();
      expect(tool.name, 'web_search');
      final result = await tool.execute({'query': 'Flutter software'});
      expect(result.isNotEmpty, true);
      expect(result.contains('UNTRUSTED source=web'), true);
    });
  });
}
