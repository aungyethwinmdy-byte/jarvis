import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'audio/audio_service.dart';
import 'live/live_client.dart';
import 'memory/memory_service.dart';
import 'ui/home_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final audioService = AudioService();
  final memoryService = MemoryService();
  final liveClient = LiveClient(
    audioService: audioService,
    memoryService: memoryService,
  );

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider<MemoryService>.value(value: memoryService),
        ChangeNotifierProvider<LiveClient>.value(value: liveClient),
      ],
      child: const JarvisApp(),
    ),
  );
}

class JarvisApp extends StatelessWidget {
  const JarvisApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'JARVIS Voice Assistant',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF070F1E),
        primaryColor: const Color(0xFF00E5FF),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF0B192C),
          elevation: 0,
        ),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF00E5FF),
          secondary: Color(0xFF00ADB5),
          surface: Color(0xFF132030),
        ),
        fontFamily: 'Roboto',
      ),
      home: const HomeScreen(),
    );
  }
}
