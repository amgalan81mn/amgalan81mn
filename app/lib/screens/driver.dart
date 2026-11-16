import 'dart:async';

import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../config.dart';
import '../format.dart';
import '../location.dart';
import '../routing.dart';
import '../tunes.dart';
import '../widgets/common.dart';

/// Жолоочийн горим: очих газраа сонгож «Замдаа гарах» дарна. Маршрутын урд, ойролцоо зогсож буй,
/// үнэ таарсан зорчигчид жагсаалтад гарна. «Авна» дарахад хоёр утсанд ижил дуу дугарна.
class DriverScreen extends StatefulWidget {
  const DriverScreen({super.key});

  @override
  State<DriverScreen> createState() => _DriverScreenState();
}

class _DriverScreenState extends State<DriverScreen> {
  final _map = MapController();
  final _tune = TunePlayer();
  Timer? _poll;
  StreamSubscription<LatLng>? _gps;
  DateTime _lastSent = DateTime.fromMillisecondsSinceEpoch(0);

  List<dynamic> _vehicles = [];
  String? _vehicleId;
  LatLng? _here;
  LatLng? _destination;
  List<LatLng> _polyline = [];
  double _priceFactor = 1.0;

  Map<String, dynamic>? _route; // идэвхтэй маршрут
  List<dynamic> _requests = [];
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _init();
    _poll = Timer.periodic(AppConfig.pollInterval, (_) => _refresh());
  }

  @override
  void dispose() {
    _poll?.cancel();
    _gps?.cancel();
    _tune.dispose();
    super.dispose();
  }

  Future<void> _init() async {
    try {
      final vehicles = await Api.instance.get('/me/vehicles') as List<dynamic>;
      _vehicles = vehicles.where((v) => v['status'] == 'approved').toList();
      _vehicleId = _vehicles.isNotEmpty ? _vehicles.first['id'] as String : null;
    } catch (e) {
      if (mounted) showError(context, e);
    }
    _here = await Location.current();
    if (_here != null) _map.move(_here!, 14);
    await _refresh();
  }

  Future<void> _refresh() async {
    try {
      final r = await Api.instance.get('/driver/routes/current') as Map<String, dynamic>?;
      List<dynamic> reqs = [];
      if (r != null) {
        reqs = await Api.instance.get('/driver/routes/${r['id']}/requests') as List<dynamic>;
        _startGps(r['id'] as String);
      } else {
        await _gps?.cancel();
        _gps = null;
      }
      if (!mounted) return;
      setState(() {
        _route = r;
        _requests = reqs;
      });
      // Хүлээж буй (суугаагүй) зорчигч байвал дуу тоглосоор байна
      final waiting = (r?['bookings'] as List? ?? []).where((b) => b['status'] == 'matched').toList();
      if (waiting.isNotEmpty) {
        _tune.play(waiting.last['tune'] as int);
      } else {
        _tune.stop();
      }
    } catch (_) {
      // Сүлжээ түр тасарсан
    }
  }

  void _startGps(String routeId) {
    if (_gps != null) return;
    _gps = Location.driverStream().listen((p) async {
      _here = p;
      if (DateTime.now().difference(_lastSent) < AppConfig.positionInterval) return;
      _lastSent = DateTime.now();
      try {
        await Api.instance.post('/driver/routes/$routeId/position', {'lat': p.latitude, 'lng': p.longitude});
      } catch (_) {}
    });
  }

  Future<void> _act(Future<void> Function() fn) async {
    setState(() => _busy = true);
    try {
      await fn();
      await _refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _previewRoute() async {
    if (_here == null || _destination == null) return;
    try {
      final pts = await RouteService.route(_here!, _destination!);
      setState(() => _polyline = pts);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _start() => _act(() async {
        _here ??= await Location.current();
        if (_here == null) throw Exception('Байршил тодорхойлогдсонгүй');
        if (_polyline.isEmpty) await _previewRoute();
        await Api.instance.post('/driver/routes', {
          'vehicle_id': _vehicleId,
          'polyline': [for (final p in _polyline) [p.latitude, p.longitude]],
          'price_factor': _priceFactor,
        });
      });

  Future<void> _addPeople(Map<String, dynamic> b) async {
    final seats = await showDialog<int>(
      context: context,
      builder: (c) {
        var n = (b['seats'] as int) + 1;
        return StatefulBuilder(
          builder: (c, set) => AlertDialog(
            title: const Text('Хэдэн хүн суусан бэ?'),
            content: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              IconButton(onPressed: n > (b['seats'] as int) + 1 ? () => set(() => n--) : null, icon: const Icon(Icons.remove)),
              Text('$n', style: const TextStyle(fontSize: 24)),
              IconButton(onPressed: () => set(() => n++), icon: const Icon(Icons.add)),
            ]),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c), child: const Text('Болих')),
              FilledButton(onPressed: () => Navigator.pop(c, n), child: const Text('Хадгалах')),
            ],
          ),
        );
      },
    );
    if (seats == null) return;
    await _act(() => Api.instance.post('/driver/bookings/${b['id']}/headcount', {'seats': seats}));
  }

  @override
  Widget build(BuildContext context) {
    final route = _route;
    return Column(children: [
      Expanded(flex: route == null ? 3 : 2, child: _buildMap()),
      Expanded(
        flex: route == null ? 2 : 3,
        child: route == null ? _setupPanel() : _activePanel(route),
      ),
    ]);
  }

  Widget _buildMap() {
    final bookings = (_route?['bookings'] as List? ?? []).cast<Map<String, dynamic>>();
    return FlutterMap(
      mapController: _map,
      options: MapOptions(
        initialCenter: _here ?? ubCenter,
        initialZoom: 14,
        onTap: (_, p) {
          if (_route != null) return;
          setState(() {
            _destination = p;
            _polyline = [];
          });
          _previewRoute();
        },
      ),
      children: [
        osmTiles(),
        if (_polyline.isNotEmpty)
          PolylineLayer(polylines: [Polyline(points: _polyline, strokeWidth: 5, color: Colors.teal)]),
        MarkerLayer(markers: [
          if (_here != null) Marker(point: _here!, width: 40, height: 40, child: const Icon(Icons.directions_car, color: Colors.teal, size: 36)),
          if (_destination != null) Marker(point: _destination!, width: 40, height: 40, child: const Icon(Icons.flag, color: Colors.red, size: 36)),
          for (final r in _requests)
            Marker(
              point: LatLng(r['pickup']['lat'] as double, r['pickup']['lng'] as double),
              width: 36,
              height: 36,
              child: const Icon(Icons.hail, color: Colors.deepOrange, size: 32),
            ),
          for (final b in bookings)
            Marker(
              point: LatLng(b['pickup']['lat'] as double, b['pickup']['lng'] as double),
              width: 40,
              height: 40,
              child: Icon(Icons.person_pin_circle, color: tuneColor(b['tune'] as int), size: 40),
            ),
        ]),
      ],
    );
  }

  Widget _setupPanel() {
    if (_vehicles.isEmpty) {
      return const Center(child: Text('Баталгаажсан машин алга. «Бүртгэл» хэсгээс машинаа бүртгүүлнэ үү.'));
    }
    final pct = ((_priceFactor - 1) * 100).round();
    return ListView(padding: const EdgeInsets.all(12), children: [
      DropdownButtonFormField<String>(
        initialValue: _vehicleId,
        decoration: const InputDecoration(labelText: 'Машин', isDense: true),
        items: [
          for (final v in _vehicles)
            DropdownMenuItem(value: v['id'] as String, child: Text('${v['plate']} · ${v['make']} ${v['model']}')),
        ],
        onChanged: (v) => setState(() => _vehicleId = v),
      ),
      const SizedBox(height: 8),
      Text(_destination == null ? 'Очих газраа газрын зураг дээр дарж сонгоно уу' : 'Маршрут бэлэн'),
      if (!RouteService.usesGoogle)
        const Text('Туршилт: Google түлхүүр тохируулаагүй тул маршрут шулуун шугам байна.', style: TextStyle(fontSize: 11)),
      const SizedBox(height: 8),
      Text('Миний үнэ: үндсэн тарифаас ${pct >= 0 ? '+' : ''}$pct%'),
      Slider(
        value: _priceFactor,
        min: 0.5,
        max: 2.0,
        divisions: 30,
        label: '${pct >= 0 ? '+' : ''}$pct%',
        onChanged: (v) => setState(() => _priceFactor = v),
      ),
      FilledButton.icon(
        onPressed: _busy || _destination == null || _vehicleId == null ? null : _start,
        icon: const Icon(Icons.play_arrow),
        label: const Text('Замдаа гарах'),
      ),
    ]);
  }

  Widget _activePanel(Map<String, dynamic> route) {
    final bookings = (route['bookings'] as List).cast<Map<String, dynamic>>();
    return ListView(padding: const EdgeInsets.all(12), children: [
      Row(children: [
        Expanded(
          child: Text('Сул суудал: ${route['seats_free']} · ${km(route['progress_m'])} / ${km(route['length_m'])}',
              style: const TextStyle(fontWeight: FontWeight.bold)),
        ),
        TextButton(
          onPressed: _busy
              ? null
              : () => _act(() async {
                    await Api.instance.post('/driver/routes/${route['id']}/end');
                    setState(() {
                      _destination = null;
                      _polyline = [];
                    });
                  }),
          child: const Text('Замаа дуусгах'),
        ),
      ]),
      for (final b in bookings) _bookingCard(b),
      const SizedBox(height: 8),
      Text('Замын дагуух зорчигчид', style: Theme.of(context).textTheme.titleMedium),
      if (_requests.isEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('Одоогоор таарах хүн алга')),
      for (final r in _requests)
        Card(
          child: ListTile(
            leading: const Icon(Icons.hail),
            title: Text('${r['passenger_first_name'] ?? 'Зорчигч'} · ${r['seats']} хүн'),
            subtitle: Text('${km(r['away_m'])} урдаа · хамт ${km(r['distance_m'])}\n'
                'Санал: нэг хүн ${money(r['bid_seat_price'])} (таны үнэ ${money(r['ask_seat_price'])})'),
            isThreeLine: true,
            trailing: FilledButton(
              onPressed: _busy || (route['seats_free'] as int) < (r['seats'] as int)
                  ? null
                  : () => _act(() async {
                        final b = await Api.instance.post('/driver/routes/${route['id']}/accept', {'request_id': r['request_id']});
                        await _tune.play((b as Map)['tune'] as int);
                      }),
              child: const Text('Авна'),
            ),
          ),
        ),
    ]);
  }

  Widget _bookingCard(Map<String, dynamic> b) {
    final p = b['passenger'] as Map<String, dynamic>;
    final tune = b['tune'] as int;
    final matched = b['status'] == 'matched';
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: FlashingFrame(
        color: tuneColor(tune),
        active: matched,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            AuthImage((p['photos'] as Map)['selfie'] as String?, size: 48),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${p['first_name']} · ${b['seats']} хүн', style: const TextStyle(fontWeight: FontWeight.bold)),
                Text(matched ? 'Авахаар явж байна · «${tuneName(tune)}» дуу' : 'Машинд сууж байна'),
                Text('${money(b['agreed_total'])} · ${km(b['agreed_distance_m'])}'),
              ]),
            ),
          ]),
          Wrap(spacing: 8, children: [
            if (matched) ...[
              OutlinedButton(onPressed: _busy ? null : () => _addPeople(b), child: const Text('Хүн нэмэх')),
              OutlinedButton(
                onPressed: _busy ? null : () => _act(() => Api.instance.post('/driver/bookings/${b['id']}/cancel')),
                child: const Text('Цуцлах'),
              ),
            ] else ...[
              OutlinedButton(onPressed: _busy ? null : () => _addPeople(b), child: const Text('Хүн нэмэх')),
              FilledButton(
                onPressed: _busy
                    ? null
                    : () => _act(() async {
                          final done = await Api.instance.post('/driver/bookings/${b['id']}/alight', {
                            if (_here != null) 'position': {'lat': _here!.latitude, 'lng': _here!.longitude},
                          });
                          if (mounted) showInfo(context, 'Тооцоо хийгдлээ: танд ${money((done as Map)['driver_earned'])} орлоо');
                        }),
                child: const Text('Буулаа'),
              ),
            ],
          ]),
        ]),
      ),
    );
  }
}
