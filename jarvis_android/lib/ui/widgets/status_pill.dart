import 'package:flutter/material.dart';
import '../../live/live_client.dart';

class StatusPill extends StatelessWidget {
  final LiveSessionState state;
  final String message;

  const StatusPill({
    super.key,
    required this.state,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    Color dotColor;
    Color bgColor;

    switch (state) {
      case LiveSessionState.connected:
        dotColor = Colors.tealAccent;
        bgColor = Colors.teal.withOpacity(0.15);
        break;
      case LiveSessionState.listeningWakeWord:
        dotColor = Colors.cyanAccent;
        bgColor = Colors.cyan.withOpacity(0.18);
        break;
      case LiveSessionState.listening:
        dotColor = Colors.redAccent;
        bgColor = Colors.redAccent.withOpacity(0.18);
        break;
      case LiveSessionState.thinking:
        dotColor = Colors.amberAccent;
        bgColor = Colors.amber.withOpacity(0.15);
        break;
      case LiveSessionState.speaking:
        dotColor = Colors.cyanAccent;
        bgColor = Colors.cyan.withOpacity(0.2);
        break;
      case LiveSessionState.error:
        dotColor = Colors.deepOrangeAccent;
        bgColor = Colors.deepOrange.withOpacity(0.15);
        break;
      case LiveSessionState.connecting:
        dotColor = Colors.lightBlueAccent;
        bgColor = Colors.lightBlue.withOpacity(0.15);
        break;
      case LiveSessionState.disconnected:
        dotColor = Colors.grey;
        bgColor = Colors.white10;
        break;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: dotColor.withOpacity(0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(
              color: dotColor,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: dotColor.withOpacity(0.7),
                  blurRadius: 6,
                  spreadRadius: 2,
                )
              ],
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              message,
              style: TextStyle(
                color: dotColor,
                fontSize: 13,
                fontWeight: FontWeight.w500,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
