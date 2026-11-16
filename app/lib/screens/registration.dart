import 'package:image_picker/image_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../widgets/common.dart';

const _docNames = {
  'selfie': 'Нүүр зураг',
  'id_front': 'Иргэний үнэмлэх (урд)',
  'id_back': 'Иргэний үнэмлэх (ар)',
  'driver_license': 'Жолооны үнэмлэх',
  'vehicle_certificate': 'Тээврийн хэрэгслийн гэрчилгээ',
  'car_front': 'Машин урдаас',
  'car_back': 'Машин араас (дугаар тод)',
  'car_side': 'Машин хажуугаас',
  'car_interior': 'Салон',
};

const _statusNames = {
  'none': 'Бөглөөгүй',
  'pending': 'Шалгагдаж байна',
  'approved': 'Баталгаажсан',
  'rejected': 'Татгалзсан',
};

class RegistrationScreen extends StatefulWidget {
  const RegistrationScreen({super.key, required this.onChanged});

  final VoidCallback onChanged;

  @override
  State<RegistrationScreen> createState() => _RegistrationScreenState();
}

class _RegistrationScreenState extends State<RegistrationScreen> {
  Map<String, dynamic>? _me;
  List<dynamic> _vehicles = [];
  final _uploaded = <String>{};
  bool _busy = false;

  final _last = TextEditingController();
  final _first = TextEditingController();
  final _register = TextEditingController();
  final _license = TextEditingController();
  final _bank = TextEditingController();
  final _account = TextEditingController();
  final _holder = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final me = await Api.instance.get('/me') as Map<String, dynamic>;
      final vehicles = await Api.instance.get('/me/vehicles') as List<dynamic>;
      setState(() {
        _me = me;
        _vehicles = vehicles;
        _last.text = me['last_name'] ?? _last.text;
        _first.text = me['first_name'] ?? _first.text;
        _register.text = me['register_no'] ?? _register.text;
        final d = me['driver'] as Map<String, dynamic>?;
        if (d != null) {
          _license.text = d['license_no'] ?? '';
          _bank.text = d['bank_name'] ?? '';
          _account.text = d['bank_account_no'] ?? '';
          _holder.text = d['bank_account_holder'] ?? '';
        }
      });
      widget.onChanged();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _run(Future<void> Function() action, {String? done}) async {
    setState(() => _busy = true);
    try {
      await action();
      if (done != null && mounted) showInfo(context, done);
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _photo(String path, String kind) async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.photo_camera), title: const Text('Зураг авах'), onTap: () => Navigator.pop(c, ImageSource.camera)),
          ListTile(leading: const Icon(Icons.photo), title: const Text('Галерейгаас'), onTap: () => Navigator.pop(c, ImageSource.gallery)),
        ]),
      ),
    );
    if (source == null) return;
    final file = await ImagePicker().pickImage(
      source: source,
      maxWidth: 1600,
      imageQuality: 80,
      preferredCameraDevice: kind == 'selfie' ? CameraDevice.front : CameraDevice.rear,
    );
    if (file == null) return;
    final bytes = await file.readAsBytes();
    await _run(() async {
      await Api.instance.upload(path, bytes, file.name);
      _uploaded.add(path);
    }, done: '${_docNames[kind]} хадгалагдлаа');
  }

  Widget _status(String status, String? reason) {
    final color = switch (status) {
      'approved' => Colors.green,
      'pending' => Colors.orange,
      'rejected' => Colors.red,
      _ => Colors.grey,
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Chip(label: Text(_statusNames[status] ?? status), backgroundColor: color.withValues(alpha: 0.15)),
      if (reason != null) Text('Шалтгаан: $reason', style: const TextStyle(color: Colors.red)),
    ]);
  }

  Widget _photoTiles(String basePath, List<String> kinds, List<dynamic> missing, bool locked) => Column(
        children: [
          for (final k in kinds)
            ListTile(
              dense: true,
              leading: Icon(
                missing.contains(k) ? Icons.radio_button_unchecked : Icons.check_circle,
                color: missing.contains(k) ? null : Colors.green,
              ),
              title: Text(_docNames[k]!),
              trailing: locked ? null : const Icon(Icons.photo_camera),
              onTap: locked || _busy ? null : () => _photo('$basePath/$k', k),
            ),
        ],
      );

  Future<void> _addVehicle() async {
    final plate = TextEditingController(), make = TextEditingController(), model = TextEditingController();
    final color = TextEditingController(), seats = TextEditingController(text: '4');
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Машин нэмэх'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: plate, decoration: const InputDecoration(labelText: 'Улсын дугаар (1234УБА)')),
            TextField(controller: make, decoration: const InputDecoration(labelText: 'Марк (Toyota)')),
            TextField(controller: model, decoration: const InputDecoration(labelText: 'Загвар (Prius)')),
            TextField(controller: color, decoration: const InputDecoration(labelText: 'Өнгө')),
            TextField(controller: seats, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Зорчигчийн суудлын тоо')),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Болих')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Нэмэх')),
        ],
      ),
    );
    if (ok != true) return;
    await _run(
      () => Api.instance.post('/me/vehicles', {
        'plate': plate.text,
        'make': make.text,
        'model': model.text,
        'color': color.text,
        'seats': int.tryParse(seats.text) ?? 4,
      }),
      done: 'Машин нэмэгдлээ. Зургуудаа оруулна уу',
    );
  }

  @override
  Widget build(BuildContext context) {
    final me = _me;
    if (me == null) return const Center(child: CircularProgressIndicator());
    final idStatus = me['identity_status'] as String;
    final idLocked = idStatus == 'pending' || idStatus == 'approved';
    final driver = me['driver'] as Map<String, dynamic>?;
    final drvStatus = driver?['status'] as String? ?? 'none';
    final drvLocked = drvStatus == 'pending' || drvStatus == 'approved';

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Хувийн мэдээлэл', style: Theme.of(context).textTheme.titleLarge),
          const Text('Хулгай, дээрэм зэргээс хэрэглэгчдийг хамгаалах зорилгоор бүх хэрэглэгч бүрэн бүртгүүлнэ. '
              'Үнэмлэхний зураг шифрлэгдэж хадгалагдах бөгөөд зөвхөн шалгагч админ харна.'),
          _status(idStatus, me['identity_reject_reason'] as String?),
          TextField(controller: _last, enabled: !idLocked, decoration: const InputDecoration(labelText: 'Овог')),
          TextField(controller: _first, enabled: !idLocked, decoration: const InputDecoration(labelText: 'Нэр')),
          TextField(controller: _register, enabled: !idLocked, decoration: const InputDecoration(labelText: 'Регистрийн дугаар (УБ90010112)')),
          if (!idLocked)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _busy
                    ? null
                    : () => _run(
                          () => Api.instance.put('/me/identity', {
                            'last_name': _last.text,
                            'first_name': _first.text,
                            'register_no': _register.text,
                          }),
                          done: 'Хадгалагдлаа',
                        ),
                child: const Text('Хадгалах'),
              ),
            ),
          _photoTiles('/me/documents', ['selfie', 'id_front', 'id_back'], me['missing_identity_documents'] as List, idLocked),
          if (!idLocked)
            FilledButton(
              onPressed: _busy ? null : () => _run(() => Api.instance.post('/me/identity/submit'), done: 'Шалгалтад илгээгдлээ'),
              child: const Text('Шалгуулахаар илгээх'),
            ),
          const Divider(height: 40),
          Text('Жолооч болох', style: Theme.of(context).textTheme.titleLarge),
          const Text('Орлогоо татах банкны дансны эзэмшигч таны бүртгэлтэй нэртэй таарах ёстой.'),
          _status(drvStatus, driver?['reject_reason'] as String?),
          TextField(controller: _license, enabled: !drvLocked, decoration: const InputDecoration(labelText: 'Жолооны үнэмлэхний дугаар')),
          TextField(controller: _bank, enabled: !drvLocked, decoration: const InputDecoration(labelText: 'Банк')),
          TextField(controller: _account, enabled: !drvLocked, decoration: const InputDecoration(labelText: 'Дансны дугаар')),
          TextField(controller: _holder, enabled: !drvLocked, decoration: const InputDecoration(labelText: 'Данс эзэмшигчийн нэр')),
          if (!drvLocked)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _busy
                    ? null
                    : () => _run(
                          () => Api.instance.put('/me/driver', {
                            'license_no': _license.text,
                            'bank_name': _bank.text,
                            'bank_account_no': _account.text,
                            'bank_account_holder': _holder.text,
                          }),
                          done: 'Хадгалагдлаа',
                        ),
                child: const Text('Хадгалах'),
              ),
            ),
          if (driver != null)
            _photoTiles('/me/documents', ['driver_license'], driver['missing_documents'] as List, drvLocked),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: Text('Машин', style: Theme.of(context).textTheme.titleMedium)),
            TextButton.icon(onPressed: _busy ? null : _addVehicle, icon: const Icon(Icons.add), label: const Text('Нэмэх')),
          ]),
          for (final v in _vehicles) _vehicleCard(v as Map<String, dynamic>),
          if (driver != null && !drvLocked)
            FilledButton(
              onPressed: _busy ? null : () => _run(() => Api.instance.post('/me/driver/submit'), done: 'Шалгалтад илгээгдлээ'),
              child: const Text('Жолоочийн бүртгэл илгээх'),
            ),
        ],
      ),
    );
  }

  Widget _vehicleCard(Map<String, dynamic> v) {
    final status = v['status'] as String;
    final locked = status == 'pending' || status == 'approved';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${v['plate']} · ${v['make']} ${v['model']} · ${v['color']} · ${v['seats']} суудал',
              style: const TextStyle(fontWeight: FontWeight.bold)),
          _status(status, v['reject_reason'] as String?),
          _photoTiles(
            '/me/vehicles/${v['id']}/documents',
            ['vehicle_certificate', 'car_front', 'car_back', 'car_side', 'car_interior'],
            v['missing_documents'] as List,
            locked,
          ),
          if (!locked)
            OutlinedButton(
              onPressed: _busy ? null : () => _run(() => Api.instance.post('/me/vehicles/${v['id']}/submit'), done: 'Машин шалгалтад илгээгдлээ'),
              child: const Text('Машиныг шалгуулах'),
            ),
        ]),
      ),
    );
  }
}
