import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../widgets/common.dart';

/// Зах зээлийн үнийн лааны график. Утга нь индекс: 1.00 = үндсэн тариф.
/// Саарал зурвас нь лааны гол (ердийн үнийн доод, дээд хязгаар).
class MarketScreen extends StatefulWidget {
  const MarketScreen({super.key});

  @override
  State<MarketScreen> createState() => _MarketScreenState();
}

class _MarketScreenState extends State<MarketScreen> {
  String _interval = '1h';
  Map<String, dynamic>? _data;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await Api.instance.get('/market/candles', {'interval': _interval, 'count': 48});
      setState(() => _data = d as Map<String, dynamic>);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final candles = (d?['candles'] as List? ?? []).cast<Map<String, dynamic>>();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: '15m', label: Text('15 мин')),
            ButtonSegment(value: '1h', label: Text('1 цаг')),
            ButtonSegment(value: '1d', label: Text('1 өдөр')),
          ],
          selected: {_interval},
          onSelectionChanged: (s) {
            setState(() => _interval = s.first);
            _load();
          },
        ),
        const SizedBox(height: 16),
        SizedBox(
          height: 280,
          child: candles.isEmpty
              ? const Center(child: Text('Энэ хугацаанд хэлцэл алга'))
              : CustomPaint(
                  painter: CandlePainter(
                    candles,
                    (d!['band_low'] as num).toDouble(),
                    (d['band_high'] as num).toDouble(),
                    Theme.of(context).colorScheme.onSurface,
                  ),
                ),
        ),
        const SizedBox(height: 12),
        const Text('1.00 = үндсэн тариф. Унаа ховордоход дээшилж, эрэлт багасахад буурна. '
            'Саарал зурвас нь ердийн үнийн хүрээ.'),
        if (candles.isNotEmpty)
          Text('Сүүлийн үнэ: ${(candles.last['close'] as num).toStringAsFixed(2)} · хэлцэл: ${candles.last['deals']}'),
      ]),
    );
  }
}

class CandlePainter extends CustomPainter {
  CandlePainter(this.candles, this.bandLow, this.bandHigh, this.ink);

  final List<Map<String, dynamic>> candles;
  final double bandLow, bandHigh;
  final Color ink;

  @override
  void paint(Canvas canvas, Size size) {
    double v(Map<String, dynamic> c, String k) => (c[k] as num).toDouble();
    var lo = bandLow, hi = bandHigh;
    for (final c in candles) {
      lo = lo < v(c, 'low') ? lo : v(c, 'low');
      hi = hi > v(c, 'high') ? hi : v(c, 'high');
    }
    final pad = (hi - lo) * 0.1 + 0.01;
    lo -= pad;
    hi += pad;
    double y(double value) => size.height * (1 - (value - lo) / (hi - lo));

    canvas.drawRect(
      Rect.fromLTRB(0, y(bandHigh), size.width, y(bandLow)),
      Paint()..color = ink.withValues(alpha: 0.08),
    );
    canvas.drawLine(Offset(0, y(1)), Offset(size.width, y(1)), Paint()..color = ink.withValues(alpha: 0.3));

    final w = size.width / candles.length;
    for (var i = 0; i < candles.length; i++) {
      final c = candles[i];
      final up = v(c, 'close') >= v(c, 'open');
      final paint = Paint()..color = up ? const Color(0xFF2E7D32) : const Color(0xFFC62828);
      final x = w * i + w / 2;
      canvas.drawLine(Offset(x, y(v(c, 'high'))), Offset(x, y(v(c, 'low'))), paint..strokeWidth = 1.5);
      final top = y(up ? v(c, 'close') : v(c, 'open'));
      final bottom = y(up ? v(c, 'open') : v(c, 'close'));
      canvas.drawRect(Rect.fromLTRB(x - w * 0.35, top, x + w * 0.35, bottom == top ? top + 1.5 : bottom), paint);
    }
  }

  @override
  bool shouldRepaint(CandlePainter old) => old.candles != candles;
}
