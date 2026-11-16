import 'package:dohulehu/format.dart';
import 'package:dohulehu/routing.dart';
import 'package:dohulehu/tunes.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';

void main() {
  test('мөнгийг мянгатаар тусгаарлана', () {
    expect(money(0), '0₮');
    expect(money(12000), '12,000₮');
    expect(money(-1234567), '-1,234,567₮');
    expect(km(5993), '6.0 км');
  });

  test('Google polyline задлах (Google-ийн жишээ)', () {
    final pts = RouteService.decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@');
    expect(pts.length, 3);
    expect(pts[0].latitude, closeTo(38.5, 1e-5));
    expect(pts[0].longitude, closeTo(-120.2, 1e-5));
    expect(pts[2].latitude, closeTo(43.252, 1e-5));
    expect(pts[2].longitude, closeTo(-126.453, 1e-5));
  });

  test('шулуун маршрут ойролцоогоор 200 м тутам цэгтэй', () {
    final pts = RouteService.straightLine(const LatLng(47.92, 106.80), const LatLng(47.92, 106.90));
    expect(pts.first, const LatLng(47.92, 106.80));
    expect(pts.last.longitude, closeTo(106.90, 1e-9));
    expect(pts.length, greaterThan(30));
  });

  test('аялгуу бүр өөр өнгөтэй, дугаар давтагдана', () {
    expect(tuneColors.toSet().length, tuneColors.length);
    expect(tuneColor(8), tuneColor(0));
    expect(tuneNames.length, tuneColors.length);
  });
}
