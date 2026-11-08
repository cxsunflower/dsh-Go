import 'dart:math' as math;

import 'package:dsh_app/pets/pet_pack.dart';
import 'package:dsh_app/pets/pet_sheets.dart';
import 'package:dsh_app/pets/pet_sounds.dart';
import 'package:dsh_app/pets/pet_signals.dart';
import 'package:dsh_app/pets/pet_state.dart';
import 'package:dsh_app/pets/pet_mood.dart';
import 'package:dsh_app/state/hosts_state.dart';
import 'package:dsh_app/state/notify_state.dart';
import 'package:dsh_app/ui/pets/pet_sprite.dart';
import 'package:dsh_app/ui/pets/pet_stage.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support.dart';

const _channel = MethodChannel(PetSoundPlayer.channelName);
const _laughAsset = 'assets/pet_sounds/naiwa/hahahahahahaha.wav';
const _sounds = PetSoundSet(
  id: 'naiwa',
  name: '奶蛙测试音效',
  clips: {'hahahahahahaha': PetClip(id: 'hahahahahahaha', file: 'hahahahahahaha.wav', vary: 0, ms: 25287)},
  cues: {
    'laugh': ['hahahahahahaha'],
    'laugh-point': ['hahahahahahaha'],
    'laugh-roll': ['hahahahahahaha'],
    'laugh-belly': ['hahahahahahaha'],
  },
);

class _NativeSound {
  final calls = <MethodCall>[];
  bool laughing = false;

  int get stops => calls.where((call) => call.method == 'stop').length;

  int get laughPlays => calls
      .where((call) => call.method == 'play' && (call.arguments as Map<Object?, Object?>)['asset'] == _laughAsset)
      .length;

  void install() {
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_channel, (call) async {
      calls.add(call);
      if (call.method == 'play') {
        laughing = (call.arguments as Map<Object?, Object?>)['asset'] == _laughAsset;
        return true;
      }
      if (call.method == 'stop' || call.method == 'release') laughing = false;
      return null;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(_channel, null));
  }
}

Future<void> _elapse(WidgetTester tester, TestClock clock, Duration duration) async {
  clock.advance(duration);
  await tester.pump(duration);
}

Future<PetPack> _pumpNaiwa(WidgetTester tester, TestClock clock) async {
  final pack = diskPack('naiwa');
  usePhoneView(tester);
  // The shared LRU keeps only three unpinned sheets. Keep the two poses
  // asserted below decoded while the intervening tap poses are loaded.
  PetSheets.instance.pin(pack, pack.animations['laugh']!);
  PetSheets.instance.pin(pack, pack.reaction('drag')!);
  await warmSheets(tester, pack, [
    pack.animFor(PetStateName.idle),
    pack.animations['laugh']!,
    pack.reaction('drag')!,
    pack.reaction('tapLeft')!,
    pack.reaction('tapRight')!,
  ]);
  await tester.pumpWidget(
    testApp(
      const ChatBottomHarness(),
      overrides: [
        ...petOverrides(pack: pack, clock: clock),
        chatOnScreenProvider.overrideWith(() => FlagController(true)),
        petSoundSetProvider.overrideWith((ref, id) async => _sounds),
        petSoundPlayerProvider.overrideWith((ref) => PetSoundPlayer(clock: clock.call, appVisible: () => true)),
      ],
    ),
  );
  FocusManager.instance.primaryFocus?.unfocus();
  for (var i = 0; i < 4; i++) {
    await tester.pump();
  }
  await _elapse(tester, clock, const Duration(milliseconds: 300));
  expect(tester.state<PetSpriteState>(find.byType(PetSprite)).shown?.name, 'idle');
  return pack;
}

Offset _bodyPoint(WidgetTester tester, PetPack pack) {
  final hit = pack
      .hitBoxFor(petLayer(tester).playing!)
      .intersect(Rect.fromLTRB(0, 0, pack.canvas.width, pack.baseline));
  return petCanvas(tester).topLeft + hit.center * petScaleOn(tester, pack);
}

/// A turn ends in the conversation on screen: 1.5 s later it celebrates with
/// the belly laugh, and that pose scores the long recording.
Future<Duration> _celebrate(WidgetTester tester, PetPack pack, TestClock clock, _NativeSound native) async {
  final started = clock.now;
  final bus = ProviderScope.containerOf(tester.element(find.byType(PetLayer)));
  bus.read(petEventBusProvider).add(
    PetEvent(kind: PetEventKind.done, host: HostRef.local, sessionId: 'a', key: 'turn', at: clock.now),
  );
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pump();
  Duration? untilShown;
  for (var i = 0; i < 4; i++) {
    await _elapse(tester, clock, const Duration(milliseconds: 900));
    if (petLayer(tester).playing?.name == 'laugh' && untilShown == null) {
      untilShown = clock.now.difference(started);
    }
  }
  await tester.pump();
  final layer = petLayer(tester);
  expect(layer.playing?.name, 'laugh', reason: 'the celebration pose');
  expect(tester.state<PetSpriteState>(find.byType(PetSprite)).shown?.name, 'laugh');
  return untilShown ?? clock.now.difference(started);
}

class _NoBonus implements math.Random {
  @override
  double nextDouble() => 1.0;

  @override
  int nextInt(int max) => 0;

  @override
  bool nextBool() => false;
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    // No random bonus: attention celebrates with its plain `laugh` state
    // animation, whose pose the long recording scores.
    PetLayer.random = _NoBonus();
  });
  tearDown(PetSheets.instance.clear);

  testWidgets('Naiwa celebrates a finished turn for the whole 25.287 s recording, then back to idle', (tester) async {
    final clock = TestClock();
    final native = _NativeSound()..install();
    final pack = await _pumpNaiwa(tester, clock);
    final lead = await _celebrate(tester, pack, clock, native);
    expect(native.laughPlays, 1, reason: 'the long laugh actually reached the native player');
    expect(naiwaLaughDuration, const Duration(milliseconds: 25287));

    // From where the celebration started showing: the stage and its sprite
    // both began from that moment.
    // The timer started [lead] ago; [elapsed] is what has run since then.
    var elapsed = Duration.zero;
    for (final checkpoint in const [Duration(seconds: 1), Duration(seconds: 8), Duration(milliseconds: 20000)]) {
      await _elapse(tester, clock, checkpoint - elapsed);
      await tester.pump();
      elapsed = checkpoint;
      final sprite = tester.state<PetSpriteState>(find.byType(PetSprite));
      expect(petLayer(tester).playing?.name, 'laugh', reason: 'at $checkpoint');
      expect(sprite.shown?.name, 'laugh', reason: 'sprite at $checkpoint');
      expect(sprite.shown!.loop, isTrue);
      final cells = {sprite.shown!.frames[sprite.frame].i};
      // Real sprite cells must keep advancing, including after many full loops.
      // This also fits between 20 s and the clip's 25.287 s ending.
      for (var i = 0; i < 4; i++) {
        const step = Duration(milliseconds: 50);
        await _elapse(tester, clock, step);
        elapsed += step;
        expect(sprite.shown?.name, 'laugh');
        cells.add(sprite.shown!.frames[sprite.frame].i);
      }
      expect(cells.length, greaterThan(1), reason: 'a frozen last frame is not a looping laugh at $checkpoint');
      expect(native.laughPlays, 1, reason: 'looping the art must not restart the audio');
    }

    // 300 ms before its recording ends it is still there; 700 ms later it is
    // back to idle. [lead] is how long ago the pose started.
    final justBeforeEnd = naiwaLaughDuration - lead - const Duration(milliseconds: 300);
    await _elapse(tester, clock, justBeforeEnd - elapsed);
    expect(petLayer(tester).playing?.name, 'laugh');
    await _elapse(tester, clock, const Duration(milliseconds: 700));
    expect(petLayer(tester).playing?.name, 'idle');
    expect(tester.state<PetSpriteState>(find.byType(PetSprite)).shown?.name, 'idle');
  });

  testWidgets('dragging Naiwa interrupts the laugh animation and sends native stop', (tester) async {
    final clock = TestClock();
    final native = _NativeSound()..install();
    final pack = await _pumpNaiwa(tester, clock);
    await _celebrate(tester, pack, clock, native);
    await _elapse(tester, clock, const Duration(seconds: 1));
    expect(native.laughPlays, 1);
    expect(native.laughing, isTrue);
    final stopsBeforeDrag = native.stops;

    final gesture = await tester.startGesture(_bodyPoint(tester, pack));
    await gesture.moveBy(const Offset(40, -40));
    await tester.pump();
    expect(petLayer(tester).playing?.name, pack.reaction('drag')!.name);
    expect(tester.state<PetSpriteState>(find.byType(PetSprite)).shown?.name, pack.reaction('drag')!.name);
    expect(native.stops, greaterThan(stopsBeforeDrag), reason: 'dragging must stop the already playing native clip');
    expect(native.laughing, isFalse);

    await gesture.up();
    await tester.pump();
    await _elapse(tester, clock, naiwaLaughDuration + const Duration(milliseconds: 100));
    expect(petLayer(tester).playing?.name, isNot('laugh'));
    expect(tester.state<PetSpriteState>(find.byType(PetSprite)).shown?.name, isNot('laugh'));
    expect(native.laughPlays, 1, reason: 'the cancelled reaction must not resume or replay its sound');
    expect(native.laughing, isFalse);
  });
}
