import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

/// Улаанбаатарын төв: байршил олдохгүй үед газрын зургийн эхлэх цэг.
const ubCenter = LatLng(47.9185, 106.9176);

class Location {
  static Future<bool> ensurePermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) return false;
    var p = await Geolocator.checkPermission();
    if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
    return p == LocationPermission.always || p == LocationPermission.whileInUse;
  }

  static Future<LatLng?> current() async {
    if (!await ensurePermission()) return null;
    try {
      final p = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 15)),
      );
      return LatLng(p.latitude, p.longitude);
    } catch (_) {
      final last = await Geolocator.getLastKnownPosition();
      return last == null ? null : LatLng(last.latitude, last.longitude);
    }
  }

  /// Жолоочийн горим: дэлгэц унтарсан ч мэдэгдэлтэйгээр байршил дамжуулна.
  static Stream<LatLng> driverStream() {
    final settings = defaultTargetPlatform == TargetPlatform.android
        ? AndroidSettings(
            accuracy: LocationAccuracy.high,
            distanceFilter: 10,
            intervalDuration: const Duration(seconds: 3),
            foregroundNotificationConfig: const ForegroundNotificationConfig(
              notificationTitle: 'Dohulehu',
              notificationText: 'Замдаа хүн авч байна. Байршил илгээж байна.',
              enableWakeLock: true,
            ),
          )
        : const LocationSettings(accuracy: LocationAccuracy.high, distanceFilter: 10);
    return Geolocator.getPositionStream(locationSettings: settings).map((p) => LatLng(p.latitude, p.longitude));
  }
}
