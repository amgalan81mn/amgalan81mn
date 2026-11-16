/// Тохиргоог `flutter run --dart-define=API_BASE=http://192.168.1.10:8000` гэх мэтээр солино.
class AppConfig {
  /// Android эмулятороос компьютерийн localhost руу хандах хаяг нь 10.0.2.2.
  /// Жинхэнэ утсаар туршихдаа компьютерийнхээ дотоод IP хаягийг өгнө.
  static const apiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://10.0.2.2:8000');

  /// Google Directions API түлхүүр. Хоосон бол маршрутыг шулуун шугамаар (туршилтын) үүсгэнэ.
  static const googleMapsKey = String.fromEnvironment('GOOGLE_MAPS_KEY');

  /// Жолоочийн байршил илгээх давтамж.
  static const positionInterval = Duration(seconds: 5);

  /// Төлөв шинэчлэх давтамж (дараа WebSocket-оор солино).
  static const pollInterval = Duration(seconds: 3);
}
