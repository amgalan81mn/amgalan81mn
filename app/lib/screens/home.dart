import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../widgets/common.dart';
import 'driver.dart';
import 'login.dart';
import 'market.dart';
import 'passenger.dart';
import 'registration.dart';
import 'wallet.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Map<String, dynamic>? _me;
  bool _driverMode = false;
  int _tab = 0;

  @override
  void initState() {
    super.initState();
    _loadMe();
  }

  Future<void> _loadMe() async {
    try {
      final me = await Api.instance.get('/me') as Map<String, dynamic>;
      setState(() {
        _me = me;
        if (me['can_drive'] != true) _driverMode = false;
      });
    } on ApiError catch (e) {
      if (e.status == 401 || e.status == 403) return _logout();
      if (mounted) showError(context, e);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _logout() async {
    await Api.instance.logout();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const LoginScreen()));
  }

  void _toggleMode(bool driver) {
    if (driver && _me?['can_drive'] != true) {
      showInfo(context, 'Жолоочийн горим бүртгэл баталгаажсаны дараа нээгдэнэ');
      setState(() => _tab = 3);
      return;
    }
    setState(() => _driverMode = driver);
  }

  @override
  Widget build(BuildContext context) {
    final me = _me;
    if (me == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final pages = [
      _driverMode ? const DriverScreen() : PassengerScreen(identityApproved: me['identity_status'] == 'approved'),
      WalletScreen(canDrive: me['can_drive'] == true),
      const MarketScreen(),
      RegistrationScreen(onChanged: _loadMe),
    ];
    return Scaffold(
      appBar: AppBar(
        title: SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: false, label: Text('Зорчигч'), icon: Icon(Icons.hail)),
            ButtonSegment(value: true, label: Text('Жолооч'), icon: Icon(Icons.directions_car)),
          ],
          selected: {_driverMode},
          onSelectionChanged: (s) => _toggleMode(s.first),
        ),
        actions: [IconButton(onPressed: _logout, icon: const Icon(Icons.logout), tooltip: 'Гарах')],
      ),
      body: IndexedStack(index: _tab, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) {
          setState(() => _tab = i);
          if (i == 0 || i == 3) _loadMe();
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.route), label: 'Аялал'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet), label: 'Хэтэвч'),
          NavigationDestination(icon: Icon(Icons.candlestick_chart), label: 'Зах зээл'),
          NavigationDestination(icon: Icon(Icons.badge), label: 'Бүртгэл'),
        ],
      ),
    );
  }
}
