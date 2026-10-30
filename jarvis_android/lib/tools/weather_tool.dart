import 'dart:convert';
import 'package:http/http.dart' as http;
import 'base_tool.dart';

/// Weather tool using Open-Meteo free API (No API key needed).
class WeatherTool extends BaseTool {
  @override
  String get name => 'get_weather';

  @override
  String get description =>
      'Get current weather conditions and temperature for a city or region. '
      'Parameter location MUST be provided in English (e.g. Naypyidaw, Yangon, Mandalay, Tokyo).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'location': {
            'type': 'STRING',
            'description': 'City or location name in English (e.g. Naypyidaw, Yangon, Mandalay, Tokyo, Bangkok)',
          },
        },
        'required': ['location'],
      };

  // Pre-resolved coordinates for key Myanmar cities
  static const Map<String, List<double>> _cityCoords = {
    'naypyidaw': [19.7633, 96.0785],
    'yangon': [16.8409, 96.1735],
    'mandalay': [21.9588, 96.0891],
    'taunggyi': [20.7831, 97.0378],
    'bagan': [21.1717, 94.8585],
    'mawlamyine': [16.4914, 97.6283],
    'pathein': [16.7794, 94.7383],
  };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final location = (args['location'] as String?)?.trim() ?? 'Naypyidaw';
    final locKey = location.toLowerCase();

    double lat = 19.7633;
    double lon = 96.0785;
    String resolvedName = location;

    if (_cityCoords.containsKey(locKey)) {
      lat = _cityCoords[locKey]![0];
      lon = _cityCoords[locKey]![1];
    } else {
      // Dynamic geocoding lookup
      try {
        final geoUrl = Uri.parse(
          'https://geocoding-api.open-meteo.com/v1/search?name=${Uri.encodeComponent(location)}&count=1&language=en&format=json',
        );
        final geoRes = await http.get(geoUrl).timeout(const Duration(seconds: 4));
        if (geoRes.statusCode == 200) {
          final data = jsonDecode(geoRes.body);
          final results = data['results'] as List?;
          if (results != null && results.isNotEmpty) {
            lat = (results[0]['latitude'] as num).toDouble();
            lon = (results[0]['longitude'] as num).toDouble();
            resolvedName = results[0]['name'] ?? location;
          }
        }
      } catch (_) {
        // Fallback to default coordinates
      }
    }

    try {
      final forecastUrl = Uri.parse(
        'https://api.open-meteo.com/v1/forecast?latitude=$lat&longitude=$lon'
        '&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m'
        '&timezone=auto',
      );

      final res = await http.get(forecastUrl).timeout(const Duration(seconds: 5));
      if (res.statusCode != 200) {
        return '$location မြို့၏ ရာသီဥတုအချက်အလက်ကို ဆာဗာမှ ရယူ၍ မရနိုင်ပါ ခင်ဗျာ။';
      }

      final data = jsonDecode(res.body);
      final current = data['current'];
      if (current == null) {
        return '$location မြို့၏ လက်ရှိ ရာသီဥတုကို ရှာမတွေ့ပါ ခင်ဗျာ။';
      }

      final double temp = (current['temperature_2m'] as num).toDouble();
      final double apparent = (current['apparent_temperature'] as num).toDouble();
      final int humidity = (current['relative_humidity_2m'] as num).toInt();
      final double wind = (current['wind_speed_10m'] as num).toDouble();
      final int code = (current['weather_code'] as num).toInt();

      final condition = _translateWeatherCode(code);

      return '$resolvedName မြို့၏ လက်ရှိ ရာသီဥတု အခြေအနေမှာ $condition ဖြစ်ပြီး၊ '
          'အပူချိန် ${temp.toStringAsFixed(1)}°C (ခံစားရမှု ${apparent.toStringAsFixed(1)}°C)၊ '
          'စိုထိုင်းဆ $humidity% နှင့် လေတိုက်နှုန်း တစ်နာရီ $wind ကီလိုမီတာ ရှိပါသည် ခင်ဗျာ။';
    } catch (e) {
      return '$location ၏ ရာသီဥတု ရယူရာတွင် ချိတ်ဆက်မှု အခက်အခဲ ရှိနေပါသည်: $e';
    }
  }

  String _translateWeatherCode(int code) {
    if (code == 0) return 'ကောင်းကင်ကြည်လင် သာယာနေသည်';
    if (code >= 1 && code <= 3) return 'တိမ်အနည်းငယ်မှ အသင့်အတင့် ရှိနေသည်';
    if (code == 45 || code == 48) return 'မြူဆိုင်းနေသည်';
    if (code >= 51 && code <= 55) return 'မိုးဖွဲဖွဲ ရွာသွန်းနေသည်';
    if (code >= 61 && code <= 65) return 'မိုးရွာနေသည်';
    if (code >= 71 && code <= 77) return 'နှင်းကျနေသည်';
    if (code >= 80 && code <= 82) return 'မိုးသည်းထန်စွာ ရွာသွန်းနေသည်';
    if (code >= 95) return 'မိုးကြိုးမုန်တိုင်း ဖြစ်ပေါ်နေသည်';
    return 'သာမန်ရာသီဥတု ဖြစ်နေသည်';
  }
}
