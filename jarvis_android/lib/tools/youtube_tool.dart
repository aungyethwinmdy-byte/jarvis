import 'package:flutter/foundation.dart';
import 'base_tool.dart';
import 'device_channel.dart';

/// Tool to play or search for songs, artists, or videos on YouTube.
class PlayYouTubeTool extends BaseTool {
  @override
  String get name => 'play_youtube';

  @override
  String get description =>
      'Search and play songs, artists, music videos, or topics directly on the YouTube app. '
      'Parameter: query (string name of the song, artist, or video to play).';

  @override
  Map<String, dynamic> get parametersSchema => {
        'type': 'OBJECT',
        'properties': {
          'query': {
            'type': 'STRING',
            'description':
                'Name of the song, artist, video, or topic to search and play on YouTube (e.g. "Shwe Htoo song", "Taylor Swift", "Myanmar song")',
          },
        },
        'required': ['query'],
      };

  @override
  Future<String> execute(Map<String, dynamic> args) async {
    final query = (args['query'] ??
            args['song'] ??
            args['song_name'] ??
            args['title'] ??
            args['artist'] ??
            args['search'])
        ?.toString()
        .trim() ?? '';
    debugPrint('[PlayYouTubeTool] Executing play_youtube with query: "$query"');
    return await DeviceChannel.playYouTube(query);
  }
}
