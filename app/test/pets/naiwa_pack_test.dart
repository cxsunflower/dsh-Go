import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:dsh_app/pets/pet_library.dart';
import 'package:dsh_app/pets/pet_mood.dart';
import 'package:dsh_app/pets/pet_pack.dart';
import 'package:dsh_app/pets/pet_pack_validator.dart';
import 'package:dsh_app/pets/pet_sheets.dart';
import 'package:dsh_app/pets/pet_signals.dart';
import 'package:dsh_app/pets/pet_state.dart';
import 'package:dsh_app/state/hosts_state.dart';
import 'package:dsh_app/ui/pets/pet_stage.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support.dart';

final _folder = Directory('assets/pets/naiwa').absolute;

Map<String, Object?> _manifest() =>
    jsonDecode(File('${_folder.path}/pack.json').readAsStringSync()) as Map<String, Object?>;

PetPack _pack() => PetPack.parse({..._manifest(), 'id': 'user-naiwa'}, dir: _folder.path);

class _Pick implements math.Random {
  _Pick(this.index, {this.draw = 0});
  final int index;
  final double draw;
  @override
  bool nextBool() => false;
  @override
  double nextDouble() => draw;
  @override
  int nextInt(int max) => index % max;
}

late TestClock clock;
late ProviderContainer container;

Future<PetPack> _pump(WidgetTester tester, _Pick random) async {
  final pack = _pack();
  PetLayer.random = random;
  usePhoneView(tester);
  for (final anim in pack.animations.values) {
    PetSheets.instance.pin(pack, anim);
  }
  await warmSheets(tester, pack);
  await tester.pumpWidget(
    testApp(
      const ChatBottomHarness(),
      overrides: petOverrides(pack: pack, clock: clock),
    ),
  );
  container = ProviderScope.containerOf(tester.element(find.byType(ChatBottomHarness)));
  for (var i = 0; i < 4; i++) {
    await tester.pump();
  }
  await tester.pump(const Duration(milliseconds: 300));
  return pack;
}

Future<void> _step(WidgetTester tester, Duration duration) async {
  clock.advance(duration);
  container.read(petMoodProvider(PetScope.global).notifier).refresh();
  await tester.pump(duration);
  await tester.pump();
}

Future<void> _tap(WidgetTester tester, PetPack pack) async {
  final canvas = petCanvas(tester);
  final scale = petScaleOn(tester, pack);
  await tester.tapAt(canvas.topLeft + pack.contentBox.center * scale);
  await _step(tester, const Duration(milliseconds: 100));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    clock = TestClock();
  });
  tearDown(PetSheets.instance.clear);

  test(
    'CLI-built silent pack imports through the app validator and library, with all 24 animations reachable',
    () async {
      final tmp = Directory.systemTemp.createTempSync('naiwa-import-');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final zip = File('${tmp.path}/pixel-naiwa.zip');
      final built = await Process.run(
        Platform.isWindows ? 'python' : 'python3',
        ['../tooling/pets/build_pet_pack.py', '--src', _folder.path, '--out', zip.path],
        environment: {'PYTHONIOENCODING': 'utf-8'},
      );
      expect(built.exitCode, 0, reason: '${built.stdout}\n${built.stderr}');
      final bytes = await zip.readAsBytes();
      final validated = PetPackValidator.validateArchive(bytes);
      final pack = validated.pack;
      expect(pack.animations.length, 24);
      expect(pack.animations.values.fold<int>(0, (sum, a) => sum + a.frames.length), 861);
      expect(validated.sheets.length, 24);
      for (final removed in ['laugh', 'laugh-point', 'laugh-belly', 'tickle']) {
        expect(pack.animations.containsKey(removed), isFalse);
      }
      expect(validated.dropped, isEmpty);
      for (final key in ['sounds', 'snack', 'drag']) {
        expect(validated.json.containsKey(key), isFalse);
      }
      expect(validated.json['roam'], {'anim': 'walk', 'faces': 'front'});
      final reachable = <String>{
        for (final state in PetStateName.values)
          for (final tier in [0, 1, 2, 3]) pack.animFor(state, tier: tier).name,
        for (final idle in pack.idles) idle.anim,
        ...?pack.bonusOf(PetStateName.attention)?.anims,
        for (final variants in pack.reactions.values) ...variants,
        pack.roam.name,
      };
      expect(reachable, unorderedEquals(pack.animations.keys));
      final library = PetLibrary(() async => Directory('${tmp.path}/pets'));
      final imported = await library.install(zip);
      expect(imported.id, 'user-naiwa');
      final loaded = await library.load(imported.id);
      expect(loaded.animFor(PetStateName.attention).name, 'celebrate');
      expect(loaded.bonusOf(PetStateName.attention), isNull);
      expect(loaded.animFor(PetStateName.carrying).name, 'carrying');
      expect(loaded.reactions['tickle'], ['laugh-roll']);
      expect(loaded.reaction('annoyed')!.name, 'annoyed');
      expect(loaded.reaction('drag')!.name, 'crawl');
    },
  );

  testWidgets('dragging loops crawl and releasing returns to idle', (tester) async {
    final pack = await _pump(tester, _Pick(0));
    final gesture = await tester.startGesture(
      petCanvas(tester).topLeft + pack.contentBox.center * petScaleOn(tester, pack),
    );
    await gesture.moveBy(const Offset(20, 0));
    await tester.pump();
    await gesture.moveBy(const Offset(30, -20));
    await tester.pump();
    expect(petLayer(tester).playing?.name, 'crawl');
    await _step(tester, const Duration(seconds: 2));
    expect(petLayer(tester).playing?.name, 'crawl');
    await gesture.up();
    await _step(tester, const Duration(milliseconds: 400));
    expect(petLayer(tester).playing?.name, 'idle');
  });

  for (final (index, name) in ['idle-look', 'idle-giggle', 'snack', 'dance'].indexed) {
    testWidgets('$name appears within 30 seconds, returns to idle and does not postpone sleep', (tester) async {
      final pack = await _pump(tester, _Pick(index, draw: (index + 0.5) / 4));
      var seen = false;
      for (var i = 0; i < 300; i++) {
        await _step(tester, const Duration(milliseconds: 100));
        if (petLayer(tester).playing?.name == name) {
          seen = true;
          break;
        }
      }
      expect(seen, isTrue);
      await _step(tester, Duration(milliseconds: pack.idles.firstWhere((a) => a.anim == name).ms + 100));
      expect(petLayer(tester).playing?.name, 'idle');
      await _step(tester, const Duration(seconds: 61));
      expect(petLayer(tester).playing?.name, 'sleep');
    });
  }

  testWidgets('three taps laugh then roll; six taps interrupt with annoyed and start a new chain', (tester) async {
    final pack = await _pump(tester, _Pick(0));
    await _tap(tester, pack);
    await _tap(tester, pack);
    expect(petLayer(tester).playing?.name, 'poke-right', reason: 'two taps do not start a special laugh');
    for (var i = 0; i < 3; i++) {
      await _tap(tester, pack);
      expect(petLayer(tester).playing?.name, 'laugh-roll');
    }
    await _tap(tester, pack);
    expect(petLayer(tester).playing?.name, 'annoyed');
    await _step(tester, Duration(milliseconds: pack.playOf(pack.animations['annoyed']!) + 100));
    expect(petLayer(tester).playing?.name, 'idle');
    await _tap(tester, pack);
    expect(petLayer(tester).playing?.name, 'poke-right');
  });

  testWidgets('laugh-roll returns after one pass instead of holding for a recording', (tester) async {
    final pack = await _pump(tester, _Pick(0));
    expect(pack.playOf(pack.animations['laugh-roll']!), 2940);
    for (var i = 0; i < 3; i++) {
      await _tap(tester, pack);
    }
    expect(petLayer(tester).playing?.name, 'laugh-roll');
    await _step(tester, const Duration(milliseconds: 2300));
    expect(petLayer(tester).playing?.name, 'laugh-roll');
    await _step(tester, const Duration(milliseconds: 740));
    expect(petLayer(tester).playing?.name, 'idle');
  });

  for (final (index, name) in ['typing', 'typing-both', 'typing-fast'].indexed) {
    testWidgets('${index + 1} running conversations play $name', (tester) async {
      await _pump(tester, _Pick(0));
      container
          .read(testSignalsProvider.notifier)
          .set(
            PetSignals(
              lastInteraction: clock.now,
              focus: const PetFocus(host: HostRef.local, sessionId: '0', activity: PetActivity.working),
              runs: [for (var i = 0; i <= index; i++) PetRun(HostRef.local, '$i')],
            ),
          );
      await tester.pump();
      await tester.pump();
      expect(petLayer(tester).playing?.name, name);
    });
  }

  testWidgets('import signal loops carrying a parcel and releases after import ends', (tester) async {
    await _pump(tester, _Pick(0));
    container.read(testSignalsProvider.notifier).set(PetSignals(lastInteraction: clock.now, carrying: true));
    await tester.pump();
    await tester.pump();
    expect(petLayer(tester).playing?.name, 'carrying');
    await _step(tester, const Duration(seconds: 3));
    expect(petLayer(tester).playing?.name, 'carrying');
    container.read(testSignalsProvider.notifier).set(PetSignals(lastInteraction: clock.now));
    await tester.pump();
    await _step(tester, const Duration(seconds: 2));
    expect(petLayer(tester).playing?.name, 'idle');
  });

  testWidgets('completion celebrates for one pass and returns to idle', (tester) async {
    final pack = await _pump(tester, _Pick(0));
    final complete = pack.animations['celebrate']!;
    expect(complete.loop, isFalse);
    expect(pack.playOf(complete), 2080);
    container
        .read(petEventBusProvider)
        .add(PetEvent(kind: PetEventKind.done, host: HostRef.local, sessionId: 'finished', key: 'turn', at: clock.now));
    await tester.pump();
    await _step(tester, const Duration(milliseconds: 1600));
    expect(petLayer(tester).playing?.name, 'celebrate');
    await _step(tester, Duration(milliseconds: pack.playOf(complete) - 100));
    expect(petLayer(tester).playing?.name, 'celebrate');
    await _step(tester, const Duration(milliseconds: 200));
    expect(petLayer(tester).playing?.name, 'idle');
  });
}
