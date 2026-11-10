import 'package:flutter/material.dart';
import '../../live/live_client.dart';

class MicButton extends StatefulWidget {
  final LiveSessionState state;
  final VoidCallback onStartTalking;
  final VoidCallback onStopTalking;

  const MicButton({
    super.key,
    required this.state,
    required this.onStartTalking,
    required this.onStopTalking,
  });

  @override
  State<MicButton> createState() => _MicButtonState();
}

class _MicButtonState extends State<MicButton>
    with SingleTickerProviderStateMixin {
  late AnimationController _animController;
  late Animation<double> _scaleAnimation;

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);

    _scaleAnimation = Tween<double>(begin: 1.0, end: 1.12).animate(
      CurvedAnimation(parent: _animController, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _animController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isListening = widget.state == LiveSessionState.listening;
    final isSpeaking = widget.state == LiveSessionState.speaking;
    final isThinking = widget.state == LiveSessionState.thinking;
    final isWakeWord = widget.state == LiveSessionState.listeningWakeWord;

    Color primaryColor = const Color(0xFF00E5FF);
    if (isListening) {
      primaryColor = Colors.redAccent;
    } else if (isThinking) {
      primaryColor = Colors.amberAccent;
    } else if (isSpeaking) {
      primaryColor = Colors.cyanAccent;
    } else if (isWakeWord) {
      primaryColor = Colors.tealAccent;
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        GestureDetector(
          onTapDown: (_) => widget.onStartTalking(),
          onTapUp: (_) => widget.onStopTalking(),
          onTapCancel: () => widget.onStopTalking(),
          child: AnimatedBuilder(
            animation: _scaleAnimation,
            builder: (context, child) {
              final scale = (isListening || isSpeaking) ? _scaleAnimation.value : 1.0;
              return Transform.scale(
                scale: scale,
                child: Container(
                  width: 84,
                  height: 84,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        primaryColor.withOpacity(0.9),
                        primaryColor.withOpacity(0.4),
                        const Color(0xFF0B192C),
                      ],
                      stops: const [0.4, 0.7, 1.0],
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: primaryColor.withOpacity(isListening ? 0.8 : (isWakeWord ? 0.6 : 0.4)),
                        blurRadius: isListening ? 28 : (isWakeWord ? 20 : 16),
                        spreadRadius: isListening ? 6 : (isWakeWord ? 3 : 2),
                      )
                    ],
                    border: Border.all(
                      color: primaryColor,
                      width: 2.5,
                    ),
                  ),
                  child: Center(
                    child: Icon(
                      isListening
                          ? Icons.mic_rounded
                          : (isSpeaking
                              ? Icons.volume_up_rounded
                              : (isThinking
                                  ? Icons.sync_rounded
                                  : (isWakeWord
                                      ? Icons.hearing_rounded
                                      : Icons.mic_none_rounded))),
                      color: Colors.white,
                      size: 38,
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        const SizedBox(height: 10),
        Text(
          isListening
              ? 'နားထောင်နေပါသည်... (တိုက်ရိုက် ပြောဆိုပါ သို့မဟုတ် ဖိထားပါ)'
              : (isSpeaking
                  ? 'Jarvis ပြောနေပါသည်... (ကြားဖြတ်ပြောနိုင်သည်)'
                  : (isThinking
                      ? 'စဉ်းစားနေပါသည်...'
                      : (isWakeWord
                          ? '"Hey Jarvis" ဟုခေါ်ပါ သို့မဟုတ် ဖိပြီးပြောပါ'
                          : 'ဖိထားပြီး စကားပြောပါ (Push-to-Talk)'))),
          style: TextStyle(
            color: Colors.white.withOpacity(0.7),
            fontSize: 12.5,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }
}
