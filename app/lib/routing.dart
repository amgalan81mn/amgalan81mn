import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import 'config.dart';

/// Жолоочийн маршрутыг Google Directions-оор авна.
/// Түлхүүр тохируулаагүй үед туршилтад зориулж шулуун шугам үүсгэнэ.
class RouteService {
  static bool get usesGoogle => AppConfig.googleMapsKey.isNotEmpty;

  static Future<List<LatLng>> route(LatLng from, LatLng to) async {
    if (!usesGoogle) return straightLine(from, to);
    final uri = Uri.https('maps.googleapis.com', '/maps/api/directions/json', {
      'origin': '${from.latitude},${from.longitude}',
      'destination': '${to.latitude},${to.longitude}',
      'mode': 'driving',
      'key': AppConfig.googleMapsKey,
    });
    final r = await http.get(uri);
    final body = jsonDecode(r.body) as Map<String, dynamic>;
    final routes = body['routes'] as List? ?? [];
    if (body['status'] != 'OK' || routes.isEmpty) {
      throw Exception('Google маршрут олдсонгүй: ${body['status']}');
    }
    return decodePolyline(routes.first['overview_polyline']['points'] as String);
  }

  static List<LatLng> straightLine(LatLng from, LatLng to) {
    const d = Distance();
    final meters = d.as(LengthUnit.Meter, from, to);
    final n = (meters / 200).ceil().clamp(1, 500);
    return [
      for (var i = 0; i <= n; i++)
        LatLng(
          from.latitude + (to.latitude - from.latitude) * i / n,
          from.longitude + (to.longitude - from.longitude) * i / n,
        ),
    ];
  }

  /// Google-ийн шахсан polyline-ийг задлах.
  static List<LatLng> decodePolyline(String encoded) {
    final points = <LatLng>[];
    var index = 0, lat = 0, lng = 0;
    while (index < encoded.length) {
      for (var k = 0; k < 2; k++) {
        var shift = 0, result = 0, b = 0;
        do {
          b = encoded.codeUnitAt(index++) - 63;
          result |= (b & 0x1f) << shift;
          shift += 5;
        } while (b >= 0x20);
        final delta = (result & 1) != 0 ? ~(result >> 1) : (result >> 1);
        if (k == 0) {
          lat += delta;
        } else {
          lng += delta;
        }
      }
      points.add(LatLng(lat / 1e5, lng / 1e5));
    }
    return points;
  }
}
