import 'package:flutter_map/flutter_map.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';

void showError(BuildContext context, Object e) {
  if (!context.mounted) return;
  final text = e is ApiError ? e.message : 'Сүлжээний алдаа: $e';
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
}

void showInfo(BuildContext context, String text) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
}

TileLayer osmTiles() => TileLayer(
      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      userAgentPackageName: 'mn.dohulehu.dohulehu',
    );

class AuthImage extends StatelessWidget {
  const AuthImage(this.documentId, {super.key, this.size = 64});

  final String? documentId;
  final double size;

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: size,
      height: size,
      color: Colors.black12,
      child: const Icon(Icons.image_not_supported_outlined),
    );
    if (documentId == null) return placeholder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Image.network(
        Api.instance.documentUrl(documentId!),
        headers: Api.instance.authHeaders,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => placeholder,
      ),
    );
  }
}

/// Хоёр утсанд ижил өнгөөр анивчих хүрээ (шуугиантай газар, дуугүй горимд хэрэгтэй).
class FlashingFrame extends StatefulWidget {
  const FlashingFrame({super.key, required this.color, required this.active, required this.child});

  final Color color;
  final bool active;
  final Widget child;

  @override
  State<FlashingFrame> createState() => _FlashingFrameState();
}

class _FlashingFrameState extends State<FlashingFrame> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 500));

  @override
  void initState() {
    super.initState();
    if (widget.active) _c.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(FlashingFrame old) {
    super.didUpdateWidget(old);
    if (widget.active && !_c.isAnimating) _c.repeat(reverse: true);
    if (!widget.active && _c.isAnimating) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) => Container(
          decoration: BoxDecoration(
            color: widget.active ? Color.lerp(widget.color.withValues(alpha: 0.15), widget.color, _c.value) : null,
            border: Border.all(color: widget.color, width: 6),
            borderRadius: BorderRadius.circular(16),
          ),
          padding: const EdgeInsets.all(12),
          child: child,
        ),
        child: widget.child,
      );
}
