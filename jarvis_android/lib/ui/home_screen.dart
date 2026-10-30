import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';
import '../live/live_client.dart';
import '../memory/memory_service.dart';
import '../memory/secure_key_store.dart';
import '../settings/settings_screen.dart';
import 'widgets/mic_button.dart';
import 'widgets/status_pill.dart';
import 'widgets/transcript_view.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _initializeAndConnect();
    });
  }

  Future<void> _initializeAndConnect() async {
    // 1. Request microphone & notification permissions
    await [
      Permission.microphone,
      Permission.notification,
    ].request();

    // 2. Check API key and connect
    final hasKey = await SecureKeyStore.hasApiKey();
    if (!mounted) return;

    if (!hasKey) {
      _promptForKey();
    } else {
      final liveClient = Provider.of<LiveClient>(context, listen: false);
      await liveClient.connect();
    }
  }

  void _promptForKey() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Gemini API Key ထည့်သွင်းရန် လိုအပ်ပါသည် ခင်ဗျာ။'),
        backgroundColor: Colors.blueGrey,
        action: SnackBarAction(
          label: 'SETTINGS',
          textColor: Colors.cyanAccent,
          onPressed: _openSettings,
        ),
        duration: const Duration(seconds: 6),
      ),
    );
  }

  void _openSettings() async {
    final liveClient = Provider.of<LiveClient>(context, listen: false);
    final needReconnect = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );

    if (needReconnect == true && mounted) {
      await liveClient.connect();
    }
  }

  @override
  Widget build(BuildContext context) {
    final liveClient = Provider.of<LiveClient>(context);
    final memoryService = Provider.of<MemoryService>(context);

    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: const BoxDecoration(
                color: Colors.cyanAccent,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: Colors.cyanAccent,
                    blurRadius: 8,
                    spreadRadius: 2,
                  )
                ],
              ),
            ),
            const SizedBox(width: 10),
            const Text(
              'JARVIS',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                letterSpacing: 2.0,
                color: Colors.white,
              ),
            ),
          ],
        ),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined, color: Colors.cyanAccent),
            tooltip: 'Settings',
            onPressed: _openSettings,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            const SizedBox(height: 10),
            // Status Pill Indicator
            StatusPill(
              state: liveClient.state,
              message: liveClient.statusMessage,
            ),

            if (liveClient.lastError != null) ...[
              const SizedBox(height: 8),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: Colors.red.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.redAccent.withOpacity(0.3)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline_rounded,
                          color: Colors.redAccent, size: 20),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          liveClient.statusMessage,
                          style: const TextStyle(
                              color: Colors.redAccent, fontSize: 12),
                        ),
                      ),
                      TextButton(
                        onPressed: liveClient.connect,
                        child: const Text('ပြန်ချိတ်မည်',
                            style: TextStyle(color: Colors.cyanAccent, fontSize: 12)),
                      ),
                    ],
                  ),
                ),
              ),
            ],

            // Transcript Chat View
            Expanded(
              child: TranscriptView(
                messages: memoryService.messages,
              ),
            ),

            // Push-to-Talk Microphone Button
            Padding(
              padding: const EdgeInsets.only(bottom: 24, top: 12),
              child: MicButton(
                state: liveClient.state,
                onStartTalking: liveClient.startTalking,
                onStopTalking: liveClient.stopTalking,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
