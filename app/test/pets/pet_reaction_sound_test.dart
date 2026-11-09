// A one-off reaction and its recording are one event (docs/design/naiwa-pet.md
// §6.2): a cue the rate limits would drop keeps the current pose, so no silent
// pose plays; a reaction with a recording stays until that recording ends.
// `drag.mirror` turns the art (and its mouth) to the way a drag goes.

import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:dsh_app/pets/pet_mood.dart';
import 'package:dsh_app/pets/pet_pack.dart';
import 'package:dsh_app/pets/pet_sheets.dart';
import 'package:dsh_app/pets/pet_signals.dart';
import 'package:dsh_app/pets/pet_sounds.dart';
import 'package:dsh_app/pets/pet_state.dart';
import 'package:dsh_app/state/notify_state.dart';
import 'package:dsh_app/ui/pets/pet_sprite.dart';
import 'package:dsh_app/ui/pets/pet_stage.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support.dart';

const _channel = MethodChannel(PetSoundPlayer.channelName);

/// 1 s per reaction: long enough that a pose held for its recording differs
/// from the animation's own length.
PetSoundSet _set({int leftMs = 1000, int rightMs = 1000, int tickleMs = 1000, int laughMs = 25287}) => PetSoundSet(
  id: 'naiwa',
  name: '奶蛙测试音效',
  clips: {
    'dajiaosei': PetClip(id: 'dajiaosei', file: 'dajiaosei.wav', vary: 0, ms: leftMs),
    'diu': PetClip(id: 'diu', file: 'diu.wav', vary: 0, ms: rightMs),
    'andi': PetClip(id: 'andi', file: 'andi.wav', vary: 0, ms: tickleMs),
    'hahahahahahaha': PetClip(id: 'hahahahahahaha', file: 'hahahahahahaha.wav', vary: 0, ms: laughMs),
  },
  cues: {
    'poke-left': ['dajiaosei'],
    'poke-right': ['diu'],
    'wake': ['andi'],
    'laugh': ['hahahahahahaha'],
    'laugh-point': ['hahahahahahaha'],
    'laugh-roll': ['hahahahahahaha'],
    'laugh-belly': ['hahahahahahaha'],
  },
);

class _Native {
  final calls = <MethodCall>[];

  List<String> get assets => [
    for (final call in calls)
      if (call.method == 'play') (call.arguments as Map<Object?, Object?>)['asset']! as String,
  ];

  void install() {
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_channel, (call) async {
      calls.add(call);
      return call.method == 'play' ? true : null;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(_channel, null));
  }
}

late TestClock clock;

Future<void> _elapse(WidgetTester tester, Duration duration) async {
  clock.advance(duration);
  await tester.pump(duration);
}

Future<PetPack> _pump(
  WidgetTester tester, {
  PetSoundSet? sounds,
  bool sound = true,
  bool quiet = false,
  PetPack? pack,
  PetSoundPlayer? player,
}) async {
  final p = pack ?? diskPack('naiwa');
  usePhoneView(tester);
  await warmSheets(tester, p, [
    p.animFor(PetStateName.idle),
    p.animFor(PetStateName.sleeping),
    p.animFor(PetStateName.waking),
    p.reactions.values.map((name) => p.animations[name]!).first,
    p.reactions['tapLeft'],
    p.reactions['tapRight'],
    p.reactions['tickle'],
  ].whereType<PetAnimation>());
  await tester.pumpWidget(
    testApp(
      const ChatBottomHarness(),
      overrides: <Override>[
        ...petOverrides(pack: p, clock: clock, sound: sound, quiet: quiet),
        chatOnScreenProvider.overrideWith(() => FlagController(true)),
        if (sounds != null) petSoundSetProvider.overrideWith((ref, id) async => sounds),
        petSoundPlayerProvider.overrideWith(
          (ref) => player ?? PetSoundPlayer(clock: clock.call, appVisible: () => true),
        ),
      ],
    ),
  );
  for (var i = 0; i < 4; i++) {
    await tester.pump();
  }
  // Let the set resolve before the first tap: a later build reads its clips.
  final container = ProviderScope.containerOf(tester.element(find.byType(PetLayer)));
  if (sounds != null) await container.read(petSoundSetProvider('naiwa').future);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
  return p;
}

/// A tap on [left] or the right half of the body, on the pet clock.
Offset _bodyPoint(WidgetTester tester, PetPack pack) {
  // The idle pose's box: the same body from the first frame on, whatever is
  // playing when a test asks.
  final hit = pack
      .hitBoxFor(pack.animFor(PetStateName.idle))
      .intersect(Rect.fromLTRB(0, 0, pack.canvas.width, pack.baseline));
  return petCanvas(tester).topLeft + hit.center * petScaleOn(tester, pack);
}

Future<void> _tap(WidgetTester tester, PetPack pack, {required bool left}) async {
  await tester.tapAt(_tapPoint(tester, pack, left: left));
  await tester.pump();
  await tester.pump();
}

Offset _tapPoint(WidgetTester tester, PetPack pack, {required bool left}) {
  final s = petScaleOn(tester, pack);
  // The body's box as it is now: a one-off pose can sit a little off the idle
  // canvas, and the tap must still land on it.
  final body = tester.getRect(find.byKey(const ValueKey('pet-body')));
  final hit = pack
      .hitBoxFor(pack.animFor(PetStateName.idle))
      .intersect(Rect.fromLTRB(0, 0, pack.canvas.width, pack.baseline));
  final dy = body.center.dy;
  final dx = left ? body.left + (hit.left + 3) * s : body.right - (pack.canvas.width - hit.right + 3) * s;
  return Offset(dx, dy);
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    clock = TestClock();
    PetLayer.random = math.Random(7);
  });
  tearDown(PetSheets.instance.clear);

  testWidgets('a single tap pokes left and plays its clip', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'poke-left');
    expect(native.assets, ['assets/pet_sounds/naiwa/dajiaosei.wav']);
  });

  testWidgets('two quick taps: the second laughs and plays the laugh clip', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'poke-left');
    clock.advance(const Duration(milliseconds: 100));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'laugh');
    expect(native.assets, ['assets/pet_sounds/naiwa/dajiaosei.wav', 'assets/pet_sounds/naiwa/hahahahahahaha.wav']);
    await _elapse(tester, naiwaLaughDuration - const Duration(milliseconds: 400));
    expect(petLayer(tester).playing!.name, 'laugh', reason: 'the pose stays for the whole recording');
    await _elapse(tester, const Duration(milliseconds: 500));
    expect(petLayer(tester).playing!.name, 'idle');
  });

  testWidgets('Naiwa brought in as a zip (user-naiwa) laughs on two taps for the whole recording too', (tester) async {
    final native = _Native()..install();
    final json = jsonDecode(File('assets/pets/naiwa/pack.json').readAsStringSync()) as Map<String, Object?>;
    final copy = PetPack.parse({...json, 'id': 'user-naiwa'}, dir: 'assets/pets/naiwa');
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000), pack: copy);
    await _tap(tester, pack, left: true);
    clock.advance(const Duration(milliseconds: 100));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'laugh');
    expect(native.assets.last, 'assets/pet_sounds/naiwa/hahahahahahaha.wav');
    await _elapse(tester, naiwaLaughDuration - const Duration(milliseconds: 400));
    expect(petLayer(tester).playing!.name, 'laugh', reason: 'the pose stays for the whole recording');
  });

  testWidgets('a tap during the quick-tap laugh ends it; the next tap pokes instead of laughing again', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'poke-left');
    clock.advance(const Duration(milliseconds: 100));
    await _tap(tester, pack, left: false);
    expect(petLayer(tester).playing!.name, 'laugh', reason: 'the second tap of the run laughs');
    clock.advance(const Duration(milliseconds: 400));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'idle', reason: 'a tap during the recording ends it');
    final sounds = native.assets.length;
    clock.advance(const Duration(milliseconds: 400));
    await _tap(tester, pack, left: false);
    expect(petLayer(tester).playing!.name, 'poke-right', reason: 'the chain started over: a lone tap pokes');
    expect(native.assets, hasLength(sounds + 1), reason: 'and it played no laugh');
    expect(native.assets.last, 'assets/pet_sounds/naiwa/diu.wav');
  });

  testWidgets('a tap after the long-press menu still pokes', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await tester.longPressAt(_bodyPoint(tester, pack));
    await tester.pumpAndSettle();
    expect(find.text('换宠物'), findsOneWidget);
    await tester.tapAt(const Offset(200, 40));
    await tester.pumpAndSettle();
    expect(find.text('换宠物'), findsNothing);
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'poke-left');
    expect(native.assets.last, 'assets/pet_sounds/naiwa/dajiaosei.wav');
  });

  testWidgets('a long press in the middle of the quick-tap chain starts it over', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await _tap(tester, pack, left: true);
    clock.advance(const Duration(milliseconds: 100));
    await _tap(tester, pack, left: false);
    expect(petLayer(tester).playing!.name, 'laugh', reason: 'the second tap of the run laughs');
    await tester.longPressAt(_bodyPoint(tester, pack));
    await tester.pumpAndSettle();
    await tester.tapAt(const Offset(200, 40));
    await tester.pumpAndSettle();
    expect(find.text('换宠物'), findsNothing);
    clock.advance(const Duration(milliseconds: 300));
    await _tap(tester, pack, left: false);
    expect(petLayer(tester).playing!.name, 'poke-right', reason: 'the menu ended the chain: this is a lone tap');
    expect(native.assets.last, 'assets/pet_sounds/naiwa/diu.wav');
  });

  testWidgets('tapping a sleeping Naiwa wakes it and plays its clip', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    final container = ProviderScope.containerOf(tester.element(find.byType(PetLayer)));
    clock.advance(const Duration(seconds: 61));
    container.read(petMoodProvider(PetScope.global).notifier).refresh();
    await tester.pump();
    expect(petLayer(tester).playing!.name, 'sleep');
    await _tap(tester, pack, left: true);
    container.read(petMoodProvider(PetScope.global).notifier).refresh();
    await tester.pump();
    expect(petLayer(tester).playing!.name, 'wake', reason: 'a tap only wakes it');
    expect(native.assets.last, 'assets/pet_sounds/naiwa/andi.wav');
  });

  testWidgets('a second tap outside the window is two separate pokes', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await _tap(tester, pack, left: true);
    clock.advance(PetMetrics.doubleTapWithin + const Duration(milliseconds: 100));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'poke-left');
    expect(native.assets, ['assets/pet_sounds/naiwa/dajiaosei.wav'],
        reason: 'the same poke is still within its 1.5 s same-cue gap, so it is not restarted');
  });

  testWidgets('a quick-tap laugh dropped by the limits keeps the poke and plays nothing', (tester) async {
    final native = _Native()..install();
    // The same player has just laughed, so its 1.5 s same-cue gap drops the
    // double tap's laugh: the poke must stay, with nothing new playing.
    final player = PetSoundPlayer(clock: clock.call, appVisible: () => true);
    expect(await player.cue(_set(), 'laugh'), isTrue);
    final firstPlay = native.assets.length;
    // Outside the 280 ms global gap as well, so only the laugh's own 1.5 s
    // same-cue gap can drop the second tap.
    clock.advance(const Duration(milliseconds: 300));
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000), player: player);
    await _tap(tester, pack, left: true);
    clock.advance(const Duration(milliseconds: 100));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'poke-left', reason: 'a pose without its sound never starts');
    expect(native.assets.last, 'assets/pet_sounds/naiwa/dajiaosei.wav');
    expect(native.assets.length, firstPlay + 1, reason: 'the laugh was dropped, only the poke played');
    expect(petLayer(tester).reactionBlocked, 'limit');
  });

  testWidgets('past the limits: the next tap does turn and does sound', (tester) async {
    final native = _Native()..install();
    // Short recordings: the first pose has ended before the second tap.
    final pack = await _pump(tester, sounds: _set(leftMs: 1000, rightMs: 1000));
    await _tap(tester, pack, left: true);
    clock.advance(const Duration(milliseconds: 1600));
    await _tap(tester, pack, left: false);
    expect(petLayer(tester).playing!.name, 'poke-right');
    expect(petLayer(tester).reactionBlocked, isNull);
    expect(native.assets, ['assets/pet_sounds/naiwa/dajiaosei.wav', 'assets/pet_sounds/naiwa/diu.wav']);
  });

  testWidgets('a pack without sounds still turns on every tap', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, pack: deepy);
    await _tap(tester, pack, left: true);
    final first = petLayer(tester).playing!.name;
    clock.advance(const Duration(milliseconds: 100));
    await _tap(tester, pack, left: false);
    expect(petLayer(tester).playing!.name, isNot(first), reason: 'silent packs are not gated');
    expect(petLayer(tester).reactionBlocked, isNull);
    expect(native.calls, isEmpty);
  });

  testWidgets('sound off or quiet: no pose that would need a missing sound', (tester) async {
    for (final (label, sound, quiet) in [('sound off', false, false), ('quiet', true, true)]) {
      await tester.pumpWidget(const SizedBox.expand());
      await tester.pump();
      final native = _Native()..install();
      final pack = await _pump(tester, sounds: _set(), sound: sound, quiet: quiet);
      final before = petLayer(tester).playing!.name;
      await _tap(tester, pack, left: true);
      expect(petLayer(tester).playing!.name, before, reason: label);
      expect(petLayer(tester).reactionBlocked, sound ? 'quiet' : 'sound-off', reason: label);
      expect(native.assets, isEmpty, reason: '$label: nothing played');
    }
  });

  testWidgets('a reaction with a recording keeps its pose until the recording ends', (tester) async {
    final native = _Native()..install();
    // The animation itself is 900 ms; the clip is 3 s.
    final pack = await _pump(tester, sounds: _set(leftMs: 3000));
    await _tap(tester, pack, left: true);
    expect(native.assets, hasLength(1));
    await _elapse(tester, const Duration(milliseconds: 1200));
    expect(petLayer(tester).playing!.name, 'poke-left', reason: 'the pose outlasts its 900 ms animation');
    await _elapse(tester, const Duration(milliseconds: 2000));
    expect(petLayer(tester).playing!.name, 'idle');
  });

  testWidgets('a tap after the chain window ends the laugh without another sound', (tester) async {
    final native = _Native()..install();
    final pack = await _pump(tester, sounds: _set(leftMs: 3000));
    await _tap(tester, pack, left: true);
    await _elapse(tester, const Duration(milliseconds: 100));
    await _tap(tester, pack, left: true);
    expect(petLayer(tester).playing!.name, 'laugh', reason: 'the second tap of the run laughs');
    final sounds = native.assets.length;
    final stops = native.calls.where((c) => c.method == 'stop').length;
    await _elapse(tester, PetMetrics.doubleTapWithin + const Duration(milliseconds: 100));
    await _tap(tester, pack, left: true);
    await tester.pump();
    await tester.pump();
    expect(petLayer(tester).playing!.name, 'idle', reason: 'a lone tap during the laugh ends it');
    expect(native.assets, hasLength(sounds), reason: 'and nothing new played');
    expect(native.calls.where((c) => c.method == 'stop').length, stops + 1, reason: 'the native clip stops');
  });

  group('drag.mirror', () {
    testWidgets('dragging Naiwa left mirrors its art; dragging right keeps the drawn side', (tester) async {
      final pack = await _pump(tester);
      expect(pack.dragMirror, isTrue);
      final start = _bodyPoint(tester, pack);
      final gesture = await tester.startGesture(start);
      // Past the 6 dp drag slop, but only 4 dp left of where it started.
      await gesture.moveBy(const Offset(-8, 0));
      await tester.pump();
      expect(petLayer(tester).dragMirrored, isTrue);
      expect(tester.widget<PetSprite>(find.byType(PetSprite)).flip, isTrue);
      await gesture.up();
      await tester.pump();
      expect(petLayer(tester).dragMirrored, isFalse, reason: 'the held pose ends with the drag');
    });

    testWidgets('dragging right from the start never mirrors, and jitter keeps one direction', (tester) async {
      final pack = await _pump(tester);
      final start = _bodyPoint(tester, pack);
      final gesture = await tester.startGesture(start);
      await gesture.moveBy(const Offset(4, 0));
      await tester.pump();
      expect(petLayer(tester).dragMirrored, isFalse, reason: 'rightwards');
      await gesture.moveBy(const Offset(-10, 0));
      await tester.pump();
      expect(petLayer(tester).dragMirrored, isTrue, reason: 'now left of where it began');
      for (final dx in const [3.0, -1.0, 2.0, -1.0, 2.5]) {
        await gesture.moveBy(Offset(dx, 0));
        await tester.pump();
        expect(petLayer(tester).dragMirrored, isTrue, reason: 'a ${dx}px wobble must not turn it back');
      }
      await gesture.moveBy(const Offset(12, 0));
      await tester.pump();
      expect(petLayer(tester).dragMirrored, isFalse, reason: 'clearly right of where it began');
      await gesture.up();
      await tester.pump();
    });

    testWidgets('Deepy and Whale girl do not mirror while dragged', (tester) async {
      for (final id in ['deepy-whale', 'whale-girl']) {
        await tester.pumpWidget(const SizedBox.expand());
        final pack = await _pump(tester, pack: diskPack(id));
        expect(pack.dragMirror, isFalse, reason: id);
        final start = _bodyPoint(tester, pack);
        final gesture = await tester.startGesture(start);
        await gesture.moveBy(const Offset(-40, 0));
        await tester.pump();
        expect(petLayer(tester).dragMirrored, isFalse, reason: '$id keeps its drawn side');
        expect(tester.widget<PetSprite>(find.byType(PetSprite)).flip, isFalse, reason: id);
        await gesture.up();
        await tester.pump();
      }
    });
  });
}
