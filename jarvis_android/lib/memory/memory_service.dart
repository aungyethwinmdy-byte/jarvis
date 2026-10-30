import 'package:flutter/foundation.dart';

enum MessageSender { user, assistant, system }

class ChatMessage {
  final MessageSender sender;
  final String text;
  final DateTime timestamp;
  final bool isToolCall;

  ChatMessage({
    required this.sender,
    required this.text,
    DateTime? timestamp,
    this.isToolCall = false,
  }) : timestamp = timestamp ?? DateTime.now();
}

/// In-memory and session memory manager for Jarvis conversations.
class MemoryService extends ChangeNotifier {
  final List<ChatMessage> _messages = [];

  List<ChatMessage> get messages => List.unmodifiable(_messages);

  void addUserMessage(String text) {
    if (text.trim().isEmpty) return;
    _messages.add(ChatMessage(sender: MessageSender.user, text: text.trim()));
    notifyListeners();
  }

  void addAssistantMessage(String text) {
    if (text.trim().isEmpty) return;
    _messages.add(ChatMessage(sender: MessageSender.assistant, text: text.trim()));
    notifyListeners();
  }

  void addSystemMessage(String text, {bool isToolCall = false}) {
    _messages.add(ChatMessage(
      sender: MessageSender.system,
      text: text.trim(),
      isToolCall: isToolCall,
    ));
    notifyListeners();
  }

  void clear() {
    _messages.clear();
    notifyListeners();
  }
}
