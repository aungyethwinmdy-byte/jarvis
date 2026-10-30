import 'package:flutter/material.dart';
import '../../memory/memory_service.dart';

class TranscriptView extends StatelessWidget {
  final List<ChatMessage> messages;

  const TranscriptView({
    super.key,
    required this.messages,
  });

  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.graphic_eq_rounded,
              size: 54,
              color: Colors.cyanAccent.withOpacity(0.3),
            ),
            const SizedBox(height: 12),
            Text(
              'မိုက်ခလုတ်ကို ဖိထားပြီး စကားပြောပါ',
              style: TextStyle(
                color: Colors.white.withOpacity(0.4),
                fontSize: 14,
              ),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount: messages.length,
      itemBuilder: (context, index) {
        final msg = messages[index];
        final isUser = msg.sender == MessageSender.user;
        final isTool = msg.isToolCall;

        if (isTool) {
          return Center(
            child: Container(
              margin: const EdgeInsets.symmetric(vertical: 4),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.blueGrey.withOpacity(0.2),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.blueGrey.withOpacity(0.3)),
              ),
              child: Text(
                '⚡ ${msg.text}',
                style: const TextStyle(
                  color: Colors.cyanAccent,
                  fontSize: 11,
                  fontFamily: 'monospace',
                ),
              ),
            ),
          );
        }

        return Align(
          alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 6),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.78,
            ),
            decoration: BoxDecoration(
              color: isUser
                  ? const Color(0xFF005A9E).withOpacity(0.85)
                  : const Color(0xFF1B2838),
              borderRadius: BorderRadius.circular(16).copyWith(
                bottomRight: isUser ? const Radius.circular(2) : null,
                bottomLeft: !isUser ? const Radius.circular(2) : null,
              ),
              border: Border.all(
                color: isUser
                    ? Colors.lightBlueAccent.withOpacity(0.4)
                    : Colors.cyanAccent.withOpacity(0.2),
              ),
              boxShadow: [
                BoxShadow(
                  color: (isUser ? Colors.blue : Colors.cyan).withOpacity(0.1),
                  blurRadius: 8,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment:
                  isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                Text(
                  isUser ? 'ဆရာ' : 'JARVIS',
                  style: TextStyle(
                    color: isUser ? Colors.lightBlueAccent : Colors.cyanAccent,
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                SelectableText(
                  msg.text,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 14.5,
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
