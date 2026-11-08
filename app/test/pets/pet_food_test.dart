// The pet running to the reasoning being written (docs/design/naiwa-pet.md
// §7): [PetFood] reports its box while active; a pet whose working animation
// eats runs along its perch to below that reasoning at 72 px/s, facing its way, runs
// again every 6–9 s, never into an area it keeps out of and not at all with
// animations off; the reply gone, it stops where it is; idle, it walks home
// 1.2 s later, unless it was dragged (where it was put is home).

import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:dsh_app/pets/pet_mood.dart';
import 'package:dsh_app/pets/pet_pack.dart';
import 'package:dsh_app/pets/pet_sheets.dart';
import 'package:dsh_app/state/hosts_state.dart';
import 'package:dsh_app/ui/pets/pet_perch.dart';
import 'package:dsh_app/ui/pets/pet_snack.dart';
import 'package:dsh_app/ui/pets/pet_sprite.dart';
import 'package:dsh_app/ui/pets/pet_stage.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support.dart';

/// Deepy with a mouth, eating while it types.
final snacky = PetPack.parse({
  ...(jsonDecode(File('assets/pets/deepy-whale/pack.json').readAsStringSync()) as Map<String, Object?>),
  'snack': {
    'mouth': {'x': 40, 'y': 38},
    'every': {'typing': 400},
  },
});

const frame = Duration(milliseconds: 16);

late TestClock clock;
late ProviderContainer container;

/// The chat page's bottom with a reply being written on its right
/// ([HarnessConfig.food]); the pet eats [text].
Future<void> pumpChase(
  WidgetTester tester, {
  PetPack? pack,
  SnackText text = const SnackText('', reply: 'd1'),
  bool avoid = false,
  bool food = true,
  Iterable<String> warm = const [],
}) async {
  final p = pack ?? snacky;
  usePhoneView(tester);
  await warmSheets(tester, p, [for (final name in ['idle', 'typing', 'roam-hop', ...warm]) p.animations[name]!]);
  await tester.pumpWidget(
    testApp(
      const ChatBottomHarness(),
      overrides: [
        ...petOverrides(pack: p, clock: clock),
        harnessConfigProvider.overrideWith(() => HarnessConfigController(HarnessConfig(food: food, avoid: avoid))),
        petSnackTextProvider.overrideWithValue(text),
      ],
    ),
  );
  container = ProviderScope.containerOf(tester.element(find.byType(ChatBottomHarness)));
  for (var i = 0; i < 4; i++) {
    await tester.pump();
  }
  await tester.pump(const Duration(milliseconds: 300));
}

/// Something runs: the pet works (Deepy types).
void work() => container
    .read(testSignalsProvider.notifier)
    .set(PetSignals(lastInteraction: clock.now, runs: const [PetRun(HostRef.local, 'a')]));

/// The conversation on screen waits for the model or reasons: the pet thinks.
void think() => container
    .read(testSignalsProvider.notifier)
    .set(
      PetSignals(
        lastInteraction: clock.now,
        focus: const PetFocus(host: HostRef.local, sessionId: 'a', activity: PetActivity.thinking),
      ),
    );

/// Nothing runs any more, long after it started: the pet is idle at once.
void rest() {
  clock.advance(const Duration(seconds: 30));
  container.read(testSignalsProvider.notifier).set(PetSignals(lastInteraction: clock.now));
}

/// Work starts; pumps until the pet is off, then its first step.
Future<void> run(WidgetTester tester) async {
  work();
  await pumpUntil(tester, () => petLayer(tester).walking, step: frame, limit: const Duration(seconds: 1));
  expect(petLayer(tester).walking, isTrue, reason: 'it runs');
  await tester.pump();
}

/// Pumps [step] at a time until [done] (at most [limit]); how long that took.
Future<Duration> pumpUntil(
  WidgetTester tester,
  bool Function() done, {
  Duration step = const Duration(milliseconds: 100),
  Duration limit = const Duration(seconds: 12),
}) async {
  var spent = Duration.zero;
  while (!done() && spent < limit) {
    await tester.pump(step);
    spent += step;
  }
  return spent;
}

/// [key]'s box in the stage's coordinates, where [PetLayerState.foot] is.
Rect inStage(WidgetTester tester, String key) =>
    tester.getRect(find.byKey(ValueKey(key))).shift(-tester.getTopLeft(find.byType(PetLayer)));

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    clock = TestClock();
    PetLayer.random = math.Random(7);
  });
  tearDown(PetSheets.instance.clear);

  group('PetFood', () {
    testWidgets('reports its box to the stage while active; switched off or gone, nothing', (tester) async {
      final registry = PerchRegistry();
      addTearDown(registry.dispose);
      var changes = 0;
      registry.addListener(() => changes++);
      final stage = GlobalKey();
      Widget page({bool active = true, bool food = true}) => Directionality(
        textDirection: TextDirection.ltr,
        child: PetPerchScope(
          registry: registry,
          child: Stack(
            key: stage,
            children: [
              if (food)
                Positioned(
                  left: 10,
                  top: 20,
                  width: 100,
                  height: 50,
                  child: PetFood(active: active, child: const SizedBox.expand()),
                ),
            ],
          ),
        ),
      );
      RenderBox box() => stage.currentContext!.findRenderObject()! as RenderBox;

      await tester.pumpWidget(page());
      expect(registry.foods(box()), [const Rect.fromLTWH(10, 20, 100, 50)]);
      expect(changes, 1);
      await tester.pumpWidget(page(active: false));
      expect(registry.foods(box()), isEmpty);
      expect(changes, 2);
      await tester.pumpWidget(page());
      expect(registry.foods(box()), hasLength(1));
      await tester.pumpWidget(page(food: false));
      expect(registry.foods(box()), isEmpty);
      expect(changes, 4);
    });
  });

  group('running to the reasoning', () {
    testWidgets('working: it runs below the reply at 72 px/s, facing its way, then eats there', (tester) async {
      await pumpChase(tester);
      final layer = petLayer(tester);
      final home = layer.foot!.dx;
      final food = inStage(tester, 'food');
      expect(home, lessThan(food.left));
      await tester.pump(const Duration(seconds: 2));
      expect(layer.walking, isFalse, reason: 'idle, it does not run');
      await run(tester);
      expect(layer.chasing, isTrue);
      expect(layer.playing!.name, 'roam-hop');
      expect(tester.widget<PetSprite>(find.byType(PetSprite)).flip, isTrue, reason: 'Deepy faces left');
      final x0 = layer.foot!.dx;
      await tester.pump(const Duration(milliseconds: 500));
      expect(layer.foot!.dx - x0, closeTo(PetMetrics.runSpeed / 2, 1));
      await pumpUntil(tester, () => !layer.walking, limit: const Duration(seconds: 5));
      expect(layer.walking, isFalse);
      final x = layer.foot!.dx;
      expect(x - home, greaterThanOrEqualTo(PetMetrics.runMin));
      expect(x, inInclusiveRange(food.left - 0.5, food.right + 0.5));
      expect(layer.playing!.name, 'typing');
    });

    testWidgets('while it eats, it runs again every 6–9 s', (tester) async {
      await pumpChase(tester);
      final layer = petLayer(tester);
      await run(tester);
      await pumpUntil(tester, () => !layer.walking, limit: const Duration(seconds: 5));
      for (var i = 0; i < 3; i++) {
        final waited = await pumpUntil(tester, () => layer.walking);
        expect(waited.inMilliseconds, inInclusiveRange(6000, 9100));
        await pumpUntil(tester, () => !layer.walking, limit: const Duration(seconds: 5));
      }
    });

    testWidgets('idle again: 1.2 s later it walks home at walking pace', (tester) async {
      await pumpChase(tester);
      final layer = petLayer(tester);
      final home = layer.foot!.dx;
      await run(tester);
      await pumpUntil(tester, () => !layer.walking, limit: const Duration(seconds: 5));
      final away = layer.foot!.dx;
      rest();
      await tester.pump();
      expect(layer.chasing, isFalse);
      await tester.pump(const Duration(milliseconds: 1100));
      expect(layer.walking, isFalse);
      expect(layer.foot!.dx, closeTo(away, 0.01));
      await tester.pump(const Duration(milliseconds: 200));
      expect(layer.walking, isTrue);
      await tester.pump();
      expect(layer.playing!.name, 'roam-hop');
      final x0 = layer.foot!.dx;
      await tester.pump(const Duration(seconds: 1));
      expect(x0 - layer.foot!.dx, closeTo(PetMetrics.walkSpeed, 1));
      await pumpUntil(tester, () => !layer.walking);
      expect(layer.foot!.dx, closeTo(home, 0.5));
    });

    testWidgets('the reply gone mid-run: it stops where it is and eats there', (tester) async {
      await pumpChase(tester);
      final layer = petLayer(tester);
      final home = layer.foot!.dx;
      await run(tester);
      await tester.pump(const Duration(milliseconds: 600));
      container.read(harnessConfigProvider.notifier).set(const HarnessConfig());
      await tester.pump();
      expect(layer.walking, isFalse);
      expect(layer.chasing, isFalse);
      final stopped = layer.foot!.dx;
      expect(stopped - home, greaterThan(PetMetrics.runMin));
      for (var i = 0; i < 20; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(layer.foot!.dx, closeTo(stopped, 0.01));
      expect(layer.playing!.name, 'typing');
    });

    testWidgets('dragged while it eats: where it is put is home, no walk back', (tester) async {
      await pumpChase(tester, warm: ['react-drag']);
      final layer = petLayer(tester);
      await run(tester);
      await pumpUntil(tester, () => !layer.walking, limit: const Duration(seconds: 5));
      final s = petScaleOn(tester, snacky);
      final canvas = petCanvas(tester);
      final gesture = await tester.startGesture(
        Offset(canvas.left + snacky.anchorX * s, canvas.top + (snacky.contentBox.top + 8) * s),
      );
      await gesture.moveBy(const Offset(-10, 0));
      await tester.pump();
      await gesture.moveBy(const Offset(-50, 0));
      await tester.pump();
      await gesture.up();
      await tester.pump(const Duration(milliseconds: 400));
      final put = layer.foot!.dx;
      await tester.pump(const Duration(seconds: 5));
      expect(layer.walking, isFalse, reason: 'it eats where it was put for a while');
      expect(layer.foot!.dx, closeTo(put, 0.01));
      rest();
      await tester.pump();
      await tester.pump(const Duration(seconds: 5));
      expect(layer.walking, isFalse, reason: 'that is home now');
      expect(layer.foot!.dx, closeTo(put, 0.01));
    });

    testWidgets('running about, it never steps into an area it keeps out of', (tester) async {
      await pumpChase(tester, avoid: true);
      final layer = petLayer(tester);
      final key = inStage(tester, 'jump').inflate(PetMetrics.avoidGap);
      final s = petScaleOn(tester, snacky);
      final left = (snacky.anchorX - snacky.contentBox.left) * s;
      final right = (snacky.contentBox.right - snacky.anchorX) * s;
      work();
      var runs = 0;
      var walked = false;
      for (var i = 0; i < 300; i++) {
        await tester.pump(const Duration(milliseconds: 100));
        final x = layer.foot!.dx;
        expect(x + right <= key.left + 0.5 || x - left >= key.right - 0.5, isTrue, reason: 'foot $x, key $key');
        if (layer.walking && !walked) runs++;
        walked = layer.walking;
      }
      expect(runs, greaterThanOrEqualTo(2));
    });

    testWidgets('animations off: it eats where it stands and never runs', (tester) async {
      tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(
        disableAnimations: true,
      );
      addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
      await pumpChase(tester);
      final layer = petLayer(tester);
      final home = layer.foot!.dx;
      work();
      for (var i = 0; i < 20; i++) {
        await tester.pump(const Duration(seconds: 1));
        expect(layer.walking, isFalse);
      }
      expect(layer.chasing, isTrue);
      expect(layer.foot!.dx, closeTo(home, 0.01));
    });

    testWidgets('thinking over a reasoning that streams: it chews as on a reply, and runs below it', (tester) async {
      await pumpChase(tester, text: const SnackText('', reply: 'd1/reasoning'), warm: ['thinking']);
      final layer = petLayer(tester);
      think();
      await pumpUntil(tester, () => layer.walking, step: frame, limit: const Duration(seconds: 1));
      expect(layer.chasing, isTrue);
      await pumpUntil(tester, () => !layer.walking, limit: const Duration(seconds: 5));
      expect(layer.playing!.name, 'typing');
    });

    testWidgets('thinking with nothing written yet: it thinks where it stands', (tester) async {
      await pumpChase(tester, text: const SnackText('ls'), warm: ['thinking']);
      final layer = petLayer(tester);
      final home = layer.foot!.dx;
      think();
      await tester.pump(const Duration(seconds: 3));
      expect(layer.chasing, isFalse);
      expect(layer.playing!.name, 'thinking');
      expect(layer.foot!.dx, closeTo(home, 0.01));
    });

    testWidgets('a reasoning below the viewport (no reachable block): it stays and eats the jokes', (tester) async {
      await pumpChase(tester, food: false, text: const SnackText('', reply: 'd1/reasoning'), warm: ['thinking']);
      final layer = petLayer(tester);
      final home = layer.foot!.dx;
      think();
      await tester.pump(const Duration(milliseconds: 300));
      final snack = tester.state<PetSnackLayerState>(find.byType(PetSnackLayer));
      await pumpUntil(tester, () => snack.launched > 0, step: frame, limit: const Duration(seconds: 3));
      expect(layer.chasing, isFalse, reason: 'no PetFood block is on screen to run to');
      expect(layer.foot!.dx, closeTo(home, 0.01));
      expect(layer.playing!.name, 'typing');
      expect(snack.widget.text.text, petSnackJokesText);
      expect(snack.launched, greaterThan(0));
    });

    for (final (name, pack, text) in [
      ('a pet that does not eat', deepy, const SnackText('', reply: 'd1')),
      ('a command to eat, no reply', snacky, const SnackText('ls -la')),
    ]) {
      testWidgets('$name: it stays where it is', (tester) async {
        await pumpChase(tester, pack: pack, text: text);
        final layer = petLayer(tester);
        final home = layer.foot!.dx;
        work();
        await tester.pump(const Duration(seconds: 10));
        expect(layer.chasing, isFalse);
        expect(layer.foot!.dx, closeTo(home, 0.01));
      });
    }
  });
}
