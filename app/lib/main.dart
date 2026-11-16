import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'screens/home.dart';
import 'screens/login.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.instance.load();
  runApp(const DohulehuApp());
}

class DohulehuApp extends StatelessWidget {
  const DohulehuApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Dohulehu',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: const Color(0xFF00897B), useMaterial3: true),
      home: Api.instance.loggedIn ? const HomeScreen() : const LoginScreen(),
    );
  }
}
