import 'dart:async';

import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../config.dart';
import '../format.dart';
import '../location.dart';
import '../tunes.dart';
import '../widgets/common.dart';
import 'wallet.dart';

/// Зорчигчийн горим: зогсож буй газраа (GPS) болон очих газраа (газрын зураг дээр дарж) сонгоод
/// нэг суудалд төлөх үнээ тавина. Жолооч авахыг хүсэхэд дуу дугарч, машины мэдээлэл гарна.
class PassengerScreen extends StatefulWidget {
  const PassengerScreen({super.key, required this.identityApproved});

  final bool identityApproved;

  @override
  State<PassengerScreen> createState() => _PassengerScreenState();
}

class _PassengerScreenState extends State<PassengerScreen> {
  final _map = MapController();
  final _tune = TunePlayer();
  final _bid = TextEditingController();
  Timer? _poll;
  Timer? _ping;

  LatLng? _pickup;
  LatLng? _dropoff;
  int _seats = 1;
  bool _multiLeg = true; // олон машинаар дамжиж болно
  Map<String, dynamic>? _journey; // идэвхтэй эсвэл саяхан дууссан аян
  Map<String, dynamic>? _quote;
  Map<String, dynamic>? _request; // одоогийн захиалга
  Map<String, dynamic>? _finished; // дууссан аяллын дүн
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _locate();
    _refresh();
    _poll = Timer.periodic(AppConfig.pollInterval, (_) => _refresh());
    // Аяны үед байршлаа илгээнэ: явганаар алхахад суух цэг хамт шилжиж, жолооч нарт зөв харагдана
    _ping = Timer.periodic(AppConfig.positionInterval, (_) => _sendPosition());
  }

  Future<void> _sendPosition() async {
    final j = _journey;
    if (j == null || j['status'] != 'active') return;
    final here = await Location.current();
    if (here == null) return;
    try {
      final r = await Api.instance.post('/rides/journeys/${j['id']}/position', {'lat': here.latitude, 'lng': here.longitude});
      if (mounted) setState(() => _journey = r as Map<String, dynamic>);
    } catch (_) {}
  }

  @override
  void dispose() {
    _poll?.cancel();
    _ping?.cancel();
    _tune.dispose();
    super.dispose();
  }

  Future<void> _locate() async {
    final here = await Location.current();
    if (!mounted) return;
    if (here == null) {
      showInfo(context, 'Байршил тодорхойлогдсонгүй. Газрын зураг дээр удаан дарж зогсож буй газраа сонгоно уу');
      return;
    }
    setState(() => _pickup = here);
    _map.move(here, 15);
    _loadQuote();
  }

  Future<void> _refresh() async {
    try {
      final r = await Api.instance.get('/rides/requests/current');
      final j = await Api.instance.get('/rides/journeys/current');
      if (!mounted) return;
      final previous = _request?['booking'] as Map<String, dynamic>?;
      final wasActive = _journey?['status'] == 'active';
      setState(() {
        _request = r as Map<String, dynamic>?;
        _journey = j as Map<String, dynamic>?;
      });
      if (wasActive && _journey?['status'] == 'finished') {
        setState(() => _finished = {'journey': _journey});
        return;
      }
      final booking = _request?['booking'] as Map<String, dynamic>?;
      if (booking != null && booking['status'] == 'matched') {
        _tune.play(booking['tune'] as int);
      } else {
        _tune.stop();
      }
      // Жолооч маршрутаа дуусгаж буулгасан бол дүнг харуулна
      if (r == null && _journey == null && previous != null && previous['status'] == 'boarded') {
        final done = await Api.instance.get('/rides/bookings/${previous['id']}');
        if (mounted) setState(() => _finished = done as Map<String, dynamic>);
      }
    } catch (_) {
      // Сүлжээ түр тасарсан: дараагийн удаа дахин оролдоно
    }
  }

  Future<void> _loadQuote() async {
    if (_pickup == null || _dropoff == null) return;
    try {
      final q = await Api.instance.get('/rides/quote', {
        'pickup_lat': _pickup!.latitude,
        'pickup_lng': _pickup!.longitude,
        'dropoff_lat': _dropoff!.latitude,
        'dropoff_lng': _dropoff!.longitude,
        'seats': _seats,
      });
      setState(() {
        _quote = q as Map<String, dynamic>;
        _bid.text = '${_quote!['suggested_seat_price']}';
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
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

  Future<void> _submit() async {
    final bid = int.tryParse(_bid.text) ?? 0;
    setState(() => _busy = true);
    try {
      await Api.instance.post('/rides/requests', {
        'pickup': {'lat': _pickup!.latitude, 'lng': _pickup!.longitude},
        'dropoff': {'lat': _dropoff!.latitude, 'lng': _dropoff!.longitude},
        'seats': _seats,
        'bid_seat_price': bid,
        'multi_leg': _multiLeg,
      });
      await _refresh();
    } on ApiError catch (e) {
      if (e.status == 402 && mounted) {
        final shortfall = e.detail['shortfall'] as int?;
        showInfo(context, 'Хэтэвчинд ${money(shortfall)} дутуу байна. Цэнэглэнэ үү');
        if (await topUpDialog(context, suggested: shortfall) && mounted) {
          setState(() => _busy = false);
          return _submit();
        }
      } else if (mounted) {
        showError(context, e);
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.identityApproved) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Унаа хүсэхийн өмнө «Бүртгэл» хэсэгт хувийн мэдээллээ бүрэн оруулж баталгаажуулна уу.', textAlign: TextAlign.center),
        ),
      );
    }
    final booking = _request?['booking'] as Map<String, dynamic>?;
    return Column(children: [
      Expanded(child: _buildMap(booking)),
      Padding(
        padding: const EdgeInsets.all(12),
        child: _finished != null
            ? _finishedPanel()
            : booking != null
                ? _bookingPanel(booking)
                : _request != null
                    ? _waitingPanel()
                    : _requestPanel(),
      ),
    ]);
  }

  Widget _buildMap(Map<String, dynamic>? booking) {
    final driverPos = booking?['driver']?['position'] as Map<String, dynamic>?;
    return FlutterMap(
      mapController: _map,
      options: MapOptions(
        initialCenter: _pickup ?? ubCenter,
        initialZoom: 14,
        onTap: (_, p) {
          if (_request != null) return;
          setState(() => _dropoff = p);
          _loadQuote();
        },
        onLongPress: (_, p) {
          if (_request != null) return;
          setState(() => _pickup = p);
          _loadQuote();
        },
      ),
      children: [
        osmTiles(),
        MarkerLayer(markers: [
          if (_pickup != null)
            Marker(point: _pickup!, width: 40, height: 40, child: const Icon(Icons.person_pin_circle, color: Colors.teal, size: 40)),
          if (_dropoff != null)
            Marker(point: _dropoff!, width: 40, height: 40, child: const Icon(Icons.flag, color: Colors.red, size: 36)),
          if (driverPos != null)
            Marker(
              point: LatLng(driverPos['lat'] as double, driverPos['lng'] as double),
              width: 40,
              height: 40,
              child: Icon(Icons.directions_car, color: tuneColor(booking!['tune'] as int), size: 36),
            ),
        ]),
      ],
    );
  }

  Widget _requestPanel() {
    final q = _quote;
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(
        _dropoff == null ? 'Очих газраа газрын зураг дээр дарж сонгоно уу' : 'Зай ойролцоогоор ${km(q?['estimated_distance_m'])}',
        textAlign: TextAlign.center,
      ),
      if (q != null) ...[
        const SizedBox(height: 4),
        Text(
          'Үндсэн үнэ ${money(q['base_seat_price'])} · ердийн хүрээ ${money(q['band_low'])}–${money(q['band_high'])}',
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 12),
        ),
      ],
      const SizedBox(height: 8),
      Row(children: [
        const Text('Хүний тоо'),
        IconButton(
          onPressed: _seats > 1
              ? () {
                  setState(() => _seats--);
                  _loadQuote();
                }
              : null,
          icon: const Icon(Icons.remove_circle_outline),
        ),
        Text('$_seats', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        IconButton(
          onPressed: _seats < 7
              ? () {
                  setState(() => _seats++);
                  _loadQuote();
                }
              : null,
          icon: const Icon(Icons.add_circle_outline),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TextField(
            controller: _bid,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Нэг хүний үнэ', suffixText: '₮', isDense: true),
          ),
        ),
      ]),
      const Text('Өндөр үнэ тавибал жолоочид түрүүлж харагдана.', style: TextStyle(fontSize: 12)),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        dense: true,
        value: _multiLeg,
        onChanged: (v) => setState(() => _multiLeg = v),
        title: const Text('Олон машинаар дамжиж болно'),
        subtitle: const Text('Хүргэхгүй ч дөхүүлэх машинд сууна. Түгжрэлд бууж, өөр машинд сууж үргэлжлүүлнэ.'),
      ),
      const SizedBox(height: 8),
      FilledButton(
        onPressed: _busy || _pickup == null || _dropoff == null ? null : _submit,
        child: Text('Унаа хүсэх · нийт ${money((int.tryParse(_bid.text) ?? 0) * _seats)}'),
      ),
    ]);
  }

  Widget _waitingPanel() {
    final j = _journey;
    final ahead = j?['drivers_ahead'] as Map<String, dynamic>?;
    final legs = (j?['legs'] as List?) ?? [];
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const LinearProgressIndicator(),
      const SizedBox(height: 12),
      if (j != null && legs.isNotEmpty)
        Text('Аян үргэлжилж байна: ${legs.length} машин солигдсон · үлдсэн ${km(j['remaining_m'])}',
            textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.bold)),
      Text('Чиглэлийн жолооч хайж байна… (${_request!['seats']} хүн, нэг хүн ${money(_request!['bid_seat_price'])})',
          textAlign: TextAlign.center),
      if (ahead != null)
        Text(
          ahead['count'] == 0 ? 'Ойролцоо таарах жолооч одоогоор алга' : 'Ойролцоо ${ahead['count']} жолооч таны чиглэлд явж байна',
          textAlign: TextAlign.center,
        ),
      if (j != null) const Text('Алхаж байгаа бол суух цэг тань таныг дагаж шилжинэ.', textAlign: TextAlign.center, style: TextStyle(fontSize: 12)),
      const SizedBox(height: 8),
      OutlinedButton(
        onPressed: _busy
            ? null
            : () => _act(() => j != null
                ? Api.instance.post('/rides/journeys/${j['id']}/finish')
                : Api.instance.post('/rides/requests/${_request!['id']}/cancel')),
        child: Text(j != null ? 'Аяныг дуусгах (үлдсэн мөнгө буцна)' : 'Цуцлах'),
      ),
    ]);
  }

  Widget _bookingPanel(Map<String, dynamic> b) {
    final driver = b['driver'] as Map<String, dynamic>;
    final car = b['vehicle'] as Map<String, dynamic>;
    final tune = b['tune'] as int;
    final matched = b['status'] == 'matched';
    final photos = car['photos'] as Map<String, dynamic>;
    return FlashingFrame(
      color: tuneColor(tune),
      active: matched,
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (matched)
          Text('Жолооч таныг авахаар ирж байна! «${tuneName(tune)}» дуу хоёр утсанд тоглож байна',
              style: const TextStyle(fontWeight: FontWeight.bold), textAlign: TextAlign.center),
        const SizedBox(height: 8),
        Row(children: [
          AuthImage((driver['photos'] as Map)['selfie'] as String?, size: 56),
          const SizedBox(width: 8),
          AuthImage((photos['car_back'] ?? photos['car_front']) as String?, size: 56),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(car['plate'] as String, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900, letterSpacing: 2)),
              Text('${car['color']} ${car['make']} ${car['model']}'),
              Text('Жолооч: ${driver['last_name']?.toString().characters.first ?? ''}. ${driver['first_name']}'),
              Text('Сул суудал: ${car['seats_free']}'),
            ]),
          ),
        ]),
        const SizedBox(height: 8),
        Text('Тохирсон үнэ: ${money(b['agreed_total'])} (${km(b['agreed_distance_m'])}). Замд өөр хүн суувал буурна.',
            style: const TextStyle(fontSize: 12)),
        const SizedBox(height: 8),
        if (matched)
          Row(children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _busy ? null : () => _act(() => Api.instance.post('/rides/bookings/${b['id']}/cancel')),
                child: const Text('Цуцлах'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: FilledButton(
                onPressed: _busy
                    ? null
                    : () => _act(() async {
                          await Api.instance.post('/rides/bookings/${b['id']}/board');
                          await _tune.stop();
                        }),
                child: const Text('Суулаа'),
              ),
            ),
          ])
        else ...[
          if (b['jammed'] == true && b['journey_id'] != null)
            Container(
              padding: const EdgeInsets.all(8),
              margin: const EdgeInsets.only(bottom: 8),
              color: Colors.orange.withValues(alpha: 0.2),
              child: Text(
                'Түгжрэлд орлоо. ${(_journey?['drivers_ahead']?['count'] ?? 0) > 0 ? 'Урд ${_journey!['drivers_ahead']['count']} жолооч таны чиглэлд хөдөлж байна. ' : ''}'
                'Бууж алхаад дараагийн машинд сууж болно.',
              ),
            ),
          FilledButton(
            onPressed: _busy ? null : () => _alight(b),
            child: Text(b['journey_id'] != null ? 'Буулаа (аян үргэлжилнэ)' : 'Буулаа'),
          ),
        ],
      ]),
    );
  }

  Future<void> _alight(Map<String, dynamic> b) => _act(() async {
        final here = await Location.current();
        final done = await Api.instance.post('/rides/bookings/${b['id']}/alight', {
          if (here != null) 'position': {'lat': here.latitude, 'lng': here.longitude},
        }) as Map<String, dynamic>;
        await _tune.stop();
        if (b['journey_id'] != null) {
          // Энэ машины тооцоо хийгдлээ; аян дуусаагүй бол дараагийн машин хайлт автоматаар эхэлсэн
          final j = await Api.instance.get('/rides/journeys/current') as Map<String, dynamic>?;
          if (j != null && j['status'] == 'active') {
            if (mounted) showInfo(context, 'Энэ машинд ${money(done['fare_total'])} төллөө. Дараагийн машин хайж байна');
            setState(() => _journey = j);
            return;
          }
          setState(() => _finished = {'journey': j});
          return;
        }
        setState(() => _finished = done);
      });

  Widget _finishedPanel() {
    final f = _finished!;
    final j = f['journey'] as Map<String, dynamic>?;
    if (f.containsKey('journey')) {
      final legs = ((j?['legs'] as List?) ?? []).cast<Map<String, dynamic>>();
      final total = legs.fold<int>(0, (a, l) => a + ((l['fare_total'] as num?)?.toInt() ?? 0));
      return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Аян дууслаа', style: Theme.of(context).textTheme.titleLarge, textAlign: TextAlign.center),
        for (final l in legs) Text('${l['plate']} · ${km(l['distance_m'])} · ${money(l['fare_total'])}', textAlign: TextAlign.center),
        Text('Нийт: ${money(total)}. Үлдсэн мөнгө хэтэвчинд буцсан.', textAlign: TextAlign.center, style: const TextStyle(fontSize: 16)),
        const SizedBox(height: 8),
        FilledButton(
          onPressed: () => setState(() {
            _finished = null;
            _journey = null;
            _dropoff = null;
            _quote = null;
          }),
          child: const Text('Болсон'),
        ),
      ]);
    }
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('Аялал дууслаа', style: Theme.of(context).textTheme.titleLarge, textAlign: TextAlign.center),
      Text('Төлсөн: ${money(f['fare_total'])}', textAlign: TextAlign.center, style: const TextStyle(fontSize: 18)),
      if ((f['refund'] ?? 0) > 0) Text('Хэтэвчинд буцсан: ${money(f['refund'])}', textAlign: TextAlign.center),
      const SizedBox(height: 8),
      FilledButton(
        onPressed: () => setState(() {
          _finished = null;
          _dropoff = null;
          _quote = null;
        }),
        child: const Text('Болсон'),
      ),
    ]);
  }
}
