import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'config.dart';

class ApiError implements Exception {
  ApiError(this.status, this.message, [this.detail = const {}]);

  final int status;
  final String message;
  final Map<String, dynamic> detail;

  String? get code => detail['code'] as String?;

  @override
  String toString() => message;
}

/// Серверийн API. Токеныг утсанд хадгална.
class Api {
  Api._();

  static final Api instance = Api._();
  static const _tokenKey = 'token';

  String? _token;
  final _client = http.Client();

  bool get loggedIn => _token != null;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_tokenKey);
  }

  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
  }

  Map<String, String> get authHeaders => {if (_token != null) 'Authorization': 'Bearer $_token'};

  Uri _uri(String path, [Map<String, dynamic>? query]) => Uri.parse('${AppConfig.apiBase}$path')
      .replace(queryParameters: query?.map((k, v) => MapEntry(k, '$v')));

  dynamic _decode(http.Response r) {
    final body = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 200 && r.statusCode < 300) return body;
    final detail = body is Map ? body['detail'] : null;
    if (detail is Map<String, dynamic>) {
      throw ApiError(r.statusCode, '${detail['message'] ?? 'Алдаа'}', detail);
    }
    if (detail is List && detail.isNotEmpty) {
      throw ApiError(r.statusCode, '${(detail.first as Map)['msg']}');
    }
    throw ApiError(r.statusCode, detail is String ? detail : 'Сервертэй холбогдоход алдаа гарлаа');
  }

  Future<dynamic> get(String path, [Map<String, dynamic>? query]) async =>
      _decode(await _client.get(_uri(path, query), headers: authHeaders));

  Future<dynamic> post(String path, [Object? body, Map<String, String>? headers]) async => _decode(
        await _client.post(
          _uri(path),
          headers: {...authHeaders, 'Content-Type': 'application/json', ...?headers},
          body: jsonEncode(body ?? {}),
        ),
      );

  Future<dynamic> put(String path, Object body) async => _decode(
        await _client.put(
          _uri(path),
          headers: {...authHeaders, 'Content-Type': 'application/json'},
          body: jsonEncode(body),
        ),
      );

  Future<dynamic> upload(String path, Uint8List bytes, String filename) async {
    final req = http.MultipartRequest('POST', _uri(path))
      ..headers.addAll(authHeaders)
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    return _decode(await http.Response.fromStream(await _client.send(req)));
  }

  String documentUrl(String id) => '${AppConfig.apiBase}/documents/$id';

  /// Нэг үйлдлийг давхар илгээхээс сэргийлэх түлхүүр (мөнгөний хүсэлтүүдэд).
  static String idempotencyKey() {
    final r = Random.secure();
    return List.generate(24, (_) => r.nextInt(16).toRadixString(16)).join();
  }

  // ---------------------------------------------------------------- нэвтрэлт

  Future<String?> requestOtp(String phone) async {
    final r = await post('/auth/otp/request', {'phone': phone});
    return r['dev_code'] as String?;
  }

  Future<void> verifyOtp(String phone, String code) async {
    final r = await post('/auth/otp/verify', {'phone': phone, 'code': code});
    _token = r['token'] as String;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, _token!);
  }
}
