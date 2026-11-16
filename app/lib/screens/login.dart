import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../widgets/common.dart';
import 'home.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  bool _codeSent = false;
  bool _busy = false;

  Future<void> _request() async {
    setState(() => _busy = true);
    try {
      final dev = await Api.instance.requestOtp(_phone.text);
      setState(() => _codeSent = true);
      if (dev != null && mounted) {
        _code.text = dev;
        showInfo(context, 'Туршилтын горим: код автоматаар бөглөгдлөө');
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify() async {
    setState(() => _busy = true);
    try {
      await Api.instance.verifyOtp(_phone.text, _code.text);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const HomeScreen()));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 48),
            Text('Dohulehu', style: Theme.of(context).textTheme.displaySmall, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            const Text('Замдаа хүн авч, дөхүүлж өгье', textAlign: TextAlign.center),
            const SizedBox(height: 48),
            TextField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(labelText: 'Утасны дугаар', prefixText: '+976 ', border: OutlineInputBorder()),
              enabled: !_codeSent,
            ),
            if (_codeSent) ...[
              const SizedBox(height: 16),
              TextField(
                controller: _code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(labelText: 'SMS код', border: OutlineInputBorder()),
              ),
            ],
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _busy ? null : (_codeSent ? _verify : _request),
              child: Text(_codeSent ? 'Нэвтрэх' : 'Код авах'),
            ),
            if (_codeSent)
              TextButton(onPressed: () => setState(() => _codeSent = false), child: const Text('Дугаар солих')),
          ],
        ),
      ),
    );
  }
}
