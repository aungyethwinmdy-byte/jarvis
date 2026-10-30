import 'package:flutter/material.dart';
import '../memory/app_prefs.dart';
import '../memory/secure_key_store.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final TextEditingController _apiKeyController = TextEditingController();
  bool _obscureKey = true;
  bool _isLoading = true;
  bool _isSaving = false;

  String _selectedVoice = AppPrefs.defaultVoice;
  String _selectedModel = AppPrefs.defaultModel;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final key = await SecureKeyStore.getApiKey();
    final voice = await AppPrefs.getVoiceName();
    final model = await AppPrefs.getModelName();

    if (mounted) {
      setState(() {
        if (key != null) _apiKeyController.text = key;
        _selectedVoice = voice;
        _selectedModel = model;
        _isLoading = false;
      });
    }
  }

  Future<void> _saveSettings() async {
    setState(() => _isSaving = true);
    final key = _apiKeyController.text.trim();

    if (key.isNotEmpty) {
      await SecureKeyStore.saveApiKey(key);
    } else {
      await SecureKeyStore.deleteApiKey();
    }

    await AppPrefs.saveVoiceName(_selectedVoice);
    await AppPrefs.saveModelName(_selectedModel);

    if (mounted) {
      setState(() => _isSaving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Settings များကို သိမ်းဆည်းပြီးပါပြီ ခင်ဗျာ။'),
          backgroundColor: Colors.teal,
        ),
      );
      Navigator.pop(context, true); // Return true to trigger reconnect
    }
  }

  @override
  void dispose() {
    _apiKeyController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(color: Colors.cyanAccent)),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Jarvis Settings'),
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // VPN Reminder Card
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.amber.withOpacity(0.12),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.amberAccent.withOpacity(0.4)),
              ),
              child: const Row(
                children: [
                  Icon(Icons.vpn_lock_rounded, color: Colors.amberAccent, size: 28),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'သတိပြုရန်: မြန်မာနိုင်ငံမှ Gemini Live API သုံးနိုင်ရန် ဖုန်းတွင် VPN ဖွင့်ထားရန် လိုအပ်ပါသည်။',
                      style: TextStyle(
                        color: Colors.amberAccent,
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            // API Key Section
            const Text(
              'Gemini API Key',
              style: TextStyle(
                color: Colors.cyanAccent,
                fontSize: 15,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'API Key ကို flutter_secure_storage ထဲတွင် encrypted လုပ်ပြီး လုံခြုံစွာ သိမ်းဆည်းပါသည်။',
              style: TextStyle(color: Colors.white54, fontSize: 12),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _apiKeyController,
              obscureText: _obscureKey,
              style: const TextStyle(color: Colors.white, fontFamily: 'monospace'),
              decoration: InputDecoration(
                hintText: 'Gemini API key',
                hintStyle: const TextStyle(color: Colors.white24),
                filled: true,
                fillColor: const Color(0xFF132030),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: Colors.white24),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: Colors.cyanAccent.withOpacity(0.3)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: Colors.cyanAccent, width: 2),
                ),
                suffixIcon: IconButton(
                  icon: Icon(
                    _obscureKey ? Icons.visibility_off : Icons.visibility,
                    color: Colors.cyanAccent,
                  ),
                  onPressed: () => setState(() => _obscureKey = !_obscureKey),
                ),
              ),
            ),
            const SizedBox(height: 28),

            // Voice Selection Section
            const Text(
              'အသံရွေးချယ်မှု (Voice)',
              style: TextStyle(
                color: Colors.cyanAccent,
                fontSize: 15,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'PC Jarvis ၏ လက်ရှိ config: Charon (ရွေးချယ်နိုင်သော စာရင်း: Charon, Puck, Kore, Fenrir, Aoede)',
              style: TextStyle(color: Colors.white54, fontSize: 12),
            ),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: const Color(0xFF132030),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.cyanAccent.withOpacity(0.3)),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _selectedVoice,
                  isExpanded: true,
                  dropdownColor: const Color(0xFF132030),
                  items: AppPrefs.availableVoices.map((voice) {
                    return DropdownMenuItem<String>(
                      value: voice,
                      child: Row(
                        children: [
                          Icon(
                            Icons.record_voice_over_rounded,
                            color: voice == _selectedVoice ? Colors.cyanAccent : Colors.white60,
                            size: 20,
                          ),
                          const SizedBox(width: 10),
                          Text(
                            voice,
                            style: TextStyle(
                              color: voice == _selectedVoice ? Colors.cyanAccent : Colors.white,
                              fontWeight: voice == _selectedVoice ? FontWeight.bold : FontWeight.normal,
                            ),
                          ),
                          if (voice == AppPrefs.defaultVoice)
                            const Text(' (PC Default)', style: TextStyle(color: Colors.white38, fontSize: 12)),
                        ],
                      ),
                    );
                  }).toList(),
                  onChanged: (newVoice) {
                    if (newVoice != null) {
                      setState(() => _selectedVoice = newVoice);
                    }
                  },
                ),
              ),
            ),
            const SizedBox(height: 28),

            // Model Selection Section
            const Text(
              'Gemini Live Model',
              style: TextStyle(
                color: Colors.cyanAccent,
                fontSize: 15,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: const Color(0xFF132030),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.cyanAccent.withOpacity(0.3)),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _selectedModel,
                  isExpanded: true,
                  dropdownColor: const Color(0xFF132030),
                  items: AppPrefs.availableModels.map((model) {
                    return DropdownMenuItem<String>(
                      value: model,
                      child: Text(
                        model,
                        style: TextStyle(
                          color: model == _selectedModel ? Colors.cyanAccent : Colors.white,
                          fontSize: 13,
                        ),
                      ),
                    );
                  }).toList(),
                  onChanged: (newModel) {
                    if (newModel != null) {
                      setState(() => _selectedModel = newModel);
                    }
                  },
                ),
              ),
            ),
            const SizedBox(height: 40),

            // Save Button
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton(
                onPressed: _isSaving ? null : _saveSettings,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF00ADB5),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  elevation: 6,
                ),
                child: _isSaving
                    ? const CircularProgressIndicator(color: Colors.black)
                    : const Text(
                        'သိမ်းဆည်းမည် (Save Settings)',
                        style: TextStyle(
                          color: Colors.black,
                          fontSize: 15,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
