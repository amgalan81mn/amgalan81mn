import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';

const _kindNames = {
  'topup': 'Цэнэглэлт',
  'trip_settlement': 'Аялал',
  'payout': 'Данс руу татсан',
  'payout_reversal': 'Татсан мөнгө буцсан',
};

/// Хэтэвч цэнэглэх цонх. Одоогоор туршилтын горим; төлбөрийн систем холбогдоход QPay нэхэмжлэл болно.
Future<bool> topUpDialog(BuildContext context, {int? suggested}) async {
  final amount = TextEditingController(text: suggested?.toString() ?? '20000');
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: const Text('Хэтэвч цэнэглэх'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: amount, keyboardType: TextInputType.number, decoration: const InputDecoration(suffixText: '₮')),
        const SizedBox(height: 8),
        const Text('Туршилтын горим: жинхэнэ мөнгө хасагдахгүй.', style: TextStyle(fontSize: 12)),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Болих')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Цэнэглэх')),
      ],
    ),
  );
  if (ok != true) return false;
  try {
    await Api.instance.post(
      '/wallet/topup/dev',
      {'amount': int.tryParse(amount.text) ?? 0},
      {'Idempotency-Key': Api.idempotencyKey()},
    );
    return true;
  } catch (e) {
    if (context.mounted) showError(context, e);
    return false;
  }
}

class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key, required this.canDrive});

  final bool canDrive;

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  Map<String, dynamic>? _wallet;
  List<dynamic> _txs = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final w = await Api.instance.get('/wallet') as Map<String, dynamic>;
      final t = await Api.instance.get('/wallet/transactions') as List<dynamic>;
      setState(() {
        _wallet = w;
        _txs = t;
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _payout() async {
    final amount = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Данс руу татах'),
        content: TextField(controller: amount, keyboardType: TextInputType.number, decoration: const InputDecoration(suffixText: '₮')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Болих')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Татах')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await Api.instance.post('/wallet/payouts', {'amount': int.tryParse(amount.text) ?? 0}, {'Idempotency-Key': Api.idempotencyKey()});
      if (mounted) showInfo(context, 'Хүсэлт илгээгдлээ. Банкны шилжүүлэг хийгдэнэ');
      _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = _wallet;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(children: [
                const Text('Ашиглах боломжтой'),
                Text(money(w?['available']), style: Theme.of(context).textTheme.displaySmall),
                if ((w?['held'] ?? 0) > 0) Text('Аялалд түгжигдсэн: ${money(w?['held'])}'),
                const SizedBox(height: 12),
                Wrap(spacing: 8, children: [
                  FilledButton.icon(
                    onPressed: () async {
                      if (await topUpDialog(context)) _load();
                    },
                    icon: const Icon(Icons.add),
                    label: const Text('Цэнэглэх'),
                  ),
                  if (widget.canDrive)
                    OutlinedButton.icon(onPressed: _payout, icon: const Icon(Icons.account_balance), label: const Text('Данс руу татах')),
                ]),
              ]),
            ),
          ),
          const SizedBox(height: 8),
          Text('Гүйлгээ', style: Theme.of(context).textTheme.titleMedium),
          for (final t in _txs)
            ListTile(
              dense: true,
              title: Text(_kindNames[t['kind']] ?? '${t['kind']}'),
              subtitle: Text('${t['at']}'.substring(0, 16).replaceFirst('T', ' ')),
              trailing: Text(
                money(t['amount'] as num),
                style: TextStyle(color: (t['amount'] as num) < 0 ? Colors.red : Colors.green, fontWeight: FontWeight.bold),
              ),
            ),
          if (_txs.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('Гүйлгээ алга')),
        ],
      ),
    );
  }
}
