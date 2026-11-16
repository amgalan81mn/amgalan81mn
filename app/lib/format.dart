String money(num? v) {
  if (v == null) return '-';
  final s = v.round().abs().toString();
  final b = StringBuffer(v < 0 ? '-' : '');
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
    b.write(s[i]);
  }
  return '$b₮';
}

String km(num? meters) => meters == null ? '-' : '${(meters / 1000).toStringAsFixed(1)} км';
