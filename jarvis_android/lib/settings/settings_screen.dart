import 'package:flutter/material.dart';
import '../audio/background_service.dart';
import '../memory/app_prefs.dart';
import '../memory/secure_key_store.dart';
import '../tools/device_channel.dart';

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
  bool _wakeWordEnabled = true;
  double _wakeWordThreshold = AppPrefs.defaultWakeWordThreshold;
  bool _handsFreeEnabled = true;
  bool _isBatteryIgnored = false;
  bool _isA11yEnabled = false;
  bool _hasUnsavedChanges = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _apiKeyController.addListener(() {
      if (!_isLoading && mounted) {
        setState(() => _hasUnsavedChanges = true);
      }
    });
  }

  Future<void> _loadSettings() async {
    final key = await SecureKeyStore.getApiKey();
    final voice = await AppPrefs.getVoiceName();
    final model = await AppPrefs.getModelName();
    final wakeWord = await AppPrefs.isWakeWordEnabled();
    final threshold = await AppPrefs.getWakeWordThreshold();
    final handsFree = await AppPrefs.isHandsFreeEnabled();
    final batteryIgnored = await BackgroundService.isBatteryOptimizationIgnored();
    final a11yEnabled = await DeviceChannel.isAccessibilityEnabled();

    debugPrint(
      '[SettingsScreen] Settings loaded: handsFree=$handsFree, threshold=$threshold, wakeWord=$wakeWord, voice=$voice, model=$model, batteryIgnored=$batteryIgnored, a11y=$a11yEnabled',
    );

    if (mounted) {
      setState(() {
        if (key != null) _apiKeyController.text = key;
        _selectedVoice = voice;
        _selectedModel = model;
        _wakeWordEnabled = wakeWord;
        _wakeWordThreshold = threshold;
        _handsFreeEnabled = handsFree;
        _isBatteryIgnored = batteryIgnored;
        _isA11yEnabled = a11yEnabled;
        _isLoading = false;
        _hasUnsavedChanges = false;
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
    await AppPrefs.setWakeWordEnabled(_wakeWordEnabled);
    await AppPrefs.setWakeWordThreshold(_wakeWordThreshold);
    await AppPrefs.setHandsFreeEnabled(_handsFreeEnabled);

    debugPrint(
      '[SettingsScreen] Settings saved: handsFree=$_handsFreeEnabled, threshold=$_wakeWordThreshold, wakeWord=$_wakeWordEnabled, voice=$_selectedVoice, model=$_selectedModel',
    );

    if (mounted) {
      setState(() {
        _isSaving = false;
        _hasUnsavedChanges = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Settings များကို သိမ်းဆည်းပြီးပါပြီ ခင်ဗျာ။'),
          backgroundColor: Colors.teal,
        ),
      );
      Navigator.pop(context, true); // Return true to trigger reconnect/refresh
    }
  }

  @override
  void dispose() {
    _apiKeyController.dispose();
    super.dispose();
  }

  Widget _buildThresholdChip(String label, double value) {
    final isSelected = (_wakeWordThreshold - value).abs() < 0.01;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          setState(() {
            _wakeWordThreshold = value;
            _hasUnsavedChanges = true;
          });
        },
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: isSelected ? Colors.cyanAccent.withOpacity(0.2) : Colors.black26,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: isSelected ? Colors.cyanAccent : Colors.white24,
              width: isSelected ? 1.5 : 1.0,
            ),
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: isSelected ? Colors.cyanAccent : Colors.white70,
              fontSize: 11,
              fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
            ),
          ),
        ),
      ),
    );
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

            // Wake Word (Hey Jarvis) Section
            const Text(
              'Wake Word ("Hey Jarvis")',
              style: TextStyle(
                color: Colors.cyanAccent,
                fontSize: 15,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: const Color(0xFF132030),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.cyanAccent.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.hearing_rounded, color: Colors.cyanAccent, size: 26),
                  const SizedBox(width: 12),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '"Hey Jarvis" အမြဲနားထောင်မည်',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        SizedBox(height: 2),
                        Text(
                          'On-device openWakeWord ဖြင့် ဖုန်းထဲတွင်သာ စစ်ဆေးပြီး အင်တာနက်ဆီ အသံလုံးဝ မပို့ပါ',
                          style: TextStyle(color: Colors.white54, fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                  Switch(
                    value: _wakeWordEnabled,
                    activeColor: Colors.cyanAccent,
                    onChanged: (val) {
                      setState(() {
                        _wakeWordEnabled = val;
                        _hasUnsavedChanges = true;
                      });
                    },
                  ),
                ],
              ),
            ),
            if (_wakeWordEnabled) ...[
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(
                  color: const Color(0xFF132030),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.cyanAccent.withOpacity(0.2)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.tune_rounded, color: Colors.cyanAccent, size: 20),
                        SizedBox(width: 8),
                        Text(
                          'Wake Word အာရုံခံနိုင်စွမ်း (Sensitivity)',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'အသံတိုးတိုးဖြင့် လွယ်ကူစွာ နိုးထစေလိုပါက "ပုံမှန်" (0.15) သို့မဟုတ် "အလွန်မြန်" (0.12) ကို ရွေးပါ',
                      style: TextStyle(color: Colors.white54, fontSize: 11),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        _buildThresholdChip('အလွန်မြန်\n(0.12)', 0.12),
                        const SizedBox(width: 8),
                        _buildThresholdChip('ပုံမှန်\n(0.15)', 0.15),
                        const SizedBox(width: 8),
                        _buildThresholdChip('ထိန်းချုပ်\n(0.20)', 0.20),
                      ],
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 16),

            // Hands-free Live & Barge-in Section
            const Text(
              'Hands-free & Barge-in (အပြန်အလှန်ပြောဆိုမှု)',
              style: TextStyle(
                color: Colors.cyanAccent,
                fontSize: 15,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: const Color(0xFF132030),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.cyanAccent.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.record_voice_over_rounded, color: Colors.cyanAccent, size: 26),
                  const SizedBox(width: 12),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Hands-free Live စနစ် (Barge-in ပါဝင်သည်)',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        SizedBox(height: 2),
                        Text(
                          'ခလုတ်နှိပ်စရာမလိုဘဲ စဉ်ဆက်မပြတ် စကားပြောဆိုနိုင်ပြီး Jarvis ပြောနေစဉ် ကြားဖြတ်ပြောပါက ချက်ချင်းရပ်နားထောင်မည်',
                          style: TextStyle(color: Colors.white54, fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                  Switch(
                    value: _handsFreeEnabled,
                    activeColor: Colors.cyanAccent,
                    onChanged: (val) {
                      setState(() {
                        _handsFreeEnabled = val;
                        _hasUnsavedChanges = true;
                      });
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Battery Optimization Section
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF132030),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: _isBatteryIgnored
                      ? Colors.tealAccent.withOpacity(0.4)
                      : Colors.amberAccent.withOpacity(0.4),
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        _isBatteryIgnored ? Icons.battery_charging_full_rounded : Icons.battery_alert_rounded,
                        color: _isBatteryIgnored ? Colors.tealAccent : Colors.amberAccent,
                        size: 24,
                      ),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Text(
                          'Battery Optimization ကင်းလွတ်ခွင့်',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: _isBatteryIgnored ? Colors.teal.withOpacity(0.2) : Colors.amber.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          _isBatteryIgnored ? 'ကင်းလွတ်ပြီး' : 'မပေးရသေး',
                          style: TextStyle(
                            color: _isBatteryIgnored ? Colors.tealAccent : Colors.amberAccent,
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'ဖုန်း lock ချထားချိန် သို့မဟုတ် အခြား app သုံးနေချိန် "Hey Jarvis" အမြဲတစေ နိုးထနိုင်စေရန် Background Battery Optimization ကို ကင်းလွတ်ခွင့် (Ignore) ပြုလုပ်ပေးထားရန် လိုအပ်ပါသည် ခင်ဗျာ။',
                    style: TextStyle(color: Colors.white70, fontSize: 12, height: 1.35),
                  ),
                  if (!_isBatteryIgnored) ...[
                    const SizedBox(height: 10),
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton.icon(
                        onPressed: () async {
                          await BackgroundService.openBatteryOptimizationSettings();
                          final ignored = await BackgroundService.isBatteryOptimizationIgnored();
                          if (mounted) setState(() => _isBatteryIgnored = ignored);
                        },
                        icon: const Icon(Icons.settings_outlined, size: 16, color: Colors.cyanAccent),
                        label: const Text(
                          'Settings သို့ သွားမည်',
                          style: TextStyle(color: Colors.cyanAccent, fontSize: 12),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 14),

            // Accessibility Automation Service Section
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF0F1B2B),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: _isA11yEnabled
                      ? Colors.tealAccent.withOpacity(0.4)
                      : Colors.amberAccent.withOpacity(0.4),
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        _isA11yEnabled
                            ? Icons.accessibility_new_rounded
                            : Icons.accessibility_rounded,
                        color: _isA11yEnabled ? Colors.tealAccent : Colors.amberAccent,
                        size: 24,
                      ),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Text(
                          'Accessibility Service (မျက်နှာပြင် ထိန်းချုပ်မှု)',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: _isA11yEnabled
                              ? Colors.teal.withOpacity(0.2)
                              : Colors.amber.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          _isA11yEnabled ? 'ခွင့်ပြုပြီး' : 'မဖွင့်ရသေး',
                          style: TextStyle(
                            color: _isA11yEnabled ? Colors.tealAccent : Colors.amberAccent,
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Facebook feed ဖတ်ရှုခြင်း၊ Telegram / Viber တွင် စာရိုက်ပေးခြင်းနှင့် မျက်နှာပြင် အလိုအလျောက် ထိန်းချုပ်နိုင်ရန် JARVIS Automation Service ကို ဖွင့်ထားပေးရန် လိုအပ်ပါသည် ခင်ဗျာ။',
                    style: TextStyle(color: Colors.white70, fontSize: 12, height: 1.35),
                  ),
                  if (!_isA11yEnabled) ...[
                    const SizedBox(height: 10),
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton.icon(
                        onPressed: () async {
                          await DeviceChannel.openAccessibilitySettings();
                          final enabled = await DeviceChannel.isAccessibilityEnabled();
                          if (mounted) setState(() => _isA11yEnabled = enabled);
                        },
                        icon: const Icon(Icons.settings_outlined, size: 16, color: Colors.cyanAccent),
                        label: const Text(
                          'Accessibility ဖွင့်ရန် သွားမည်',
                          style: TextStyle(color: Colors.cyanAccent, fontSize: 12),
                        ),
                      ),
                    ),
                  ],
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
                      setState(() {
                        _selectedVoice = newVoice;
                        _hasUnsavedChanges = true;
                      });
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
                      setState(() {
                        _selectedModel = newModel;
                        _hasUnsavedChanges = true;
                      });
                    }
                  },
                ),
              ),
            ),
            const SizedBox(height: 24),

            if (_hasUnsavedChanges) ...[
              Container(
                margin: const EdgeInsets.only(bottom: 16),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(
                  color: Colors.amber.withOpacity(0.18),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.amberAccent.withOpacity(0.6)),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.warning_amber_rounded, color: Colors.amberAccent, size: 24),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'မသိမ်းရသေးပါ — ပြင်ဆင်ချက်များ အသက်ဝင်စေရန် အောက်ပါ "Save Settings" ခလုတ်ကို နှိပ်ပါ',
                        style: TextStyle(
                          color: Colors.amberAccent,
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],

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
