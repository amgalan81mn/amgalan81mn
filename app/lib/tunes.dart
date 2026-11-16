import 'package:audioplayers/audioplayers.dart';
import 'package:material_ui/material_ui.dart';

/// Жолооч «авна» дарахад хоёр утсанд ижил дугаартай аялгуу, өнгө гарна.
/// Ойролцоо уулзаж буй хосуудад сервер өөр дугаар оноодог.
const tuneColors = <Color>[
  Color(0xFFE53935),
  Color(0xFF1E88E5),
  Color(0xFF43A047),
  Color(0xFFFDD835),
  Color(0xFF8E24AA),
  Color(0xFFFB8C00),
  Color(0xFF00ACC1),
  Color(0xFFD81B60),
];

const tuneNames = ['Улаан', 'Цэнхэр', 'Ногоон', 'Шар', 'Ягаан', 'Улбар шар', 'Цайвар цэнхэр', 'Гүн ягаан'];

Color tuneColor(int tune) => tuneColors[tune % tuneColors.length];

String tuneName(int tune) => tuneNames[tune % tuneNames.length];

class TunePlayer {
  TunePlayer() {
    _player.setReleaseMode(ReleaseMode.loop);
  }

  final _player = AudioPlayer();
  int? _playing;

  int? get playing => _playing;

  Future<void> play(int tune) async {
    if (_playing == tune) return;
    _playing = tune;
    await _player.stop();
    await _player.play(AssetSource('tunes/tune_${tune % tuneColors.length}.wav'));
  }

  Future<void> stop() async {
    _playing = null;
    await _player.stop();
  }

  Future<void> dispose() => _player.dispose();
}
