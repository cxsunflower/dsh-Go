// The pet's sounds (docs/design/naiwa-pet.md §6): sounds.json with its bad
// clips and cues dropped, and the player over `dsh/pet_sound`: a set loaded
// once, clips picked without repeats and varied, the three limits, the
// foreground, and no throw when the native side is missing or fails. Also the
// 「音效」 switch (`pet.sound`).

import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:crypto/crypto.dart';
import 'package:dsh_app/pets/pet_prefs.dart';
import 'package:dsh_app/pets/pet_signals.dart';
import 'package:dsh_app/pets/pet_sounds.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _channel = MethodChannel(PetSoundPlayer.channelName);

Map<String, Object?> _json() => {
  'schema': 1,
  'id': 'naiwa',
  'name': '奶蛙鬼畜音效',
  'author': 'github.com/cxsunflower',
  'license': '来自 github.com/cxsunflower，见 ASSETS.md',
  'source': 'app/tool/make_pet_sounds.py 程序合成，不含录音和第三方采样',
  'clips': {
    'laugh': {'file': 'laugh.wav', 'gain': 1.0, 'vary': 0.08, 'ms': 15000},
    'laugh-2': {'file': 'laugh-2.wav'},
    'gasp': {'file': 'gasp.wav', 'gain': 0.8, 'vary': 0.2},
    'chomp-1': {'file': 'chomp-1.wav', 'gain': 0.6, 'vary': 0.2},
    'chomp-2': {'file': 'chomp-2.wav', 'gain': 0.6, 'vary': 0.2},
    'crunch': {'file': 'crunch.wav', 'gain': 0.7},
    'thud': {'file': 'thud.wav', 'vary': 0},
  },
  'cues': {
    'laugh': ['laugh', 'laugh-2'],
    'shocked': ['gasp'],
    '@bite': ['chomp-1', 'chomp-2', 'crunch'],
    '@drop': ['thud'],
  },
};

/// A stand-in for android/.../pet/PetSoundPlugin.kt on `dsh/pet_sound`.
class _Native {
  _Native({this.played = true, this.error});

  /// What `play` answers (the sound really started).
  final bool played;

  /// Thrown by every call instead.
  final Exception? error;

  final calls = <MethodCall>[];

  List<String> get methods => [for (final c in calls) c.method];

  List<Map<Object?, Object?>> get plays => [
    for (final c in calls)
      if (c.method == 'play') c.arguments as Map<Object?, Object?>,
  ];

  void install() {
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_channel, (call) async {
      calls.add(call);
      if (error case final e?) throw e;
      return call.method == 'play' ? played : null;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(_channel, null));
  }
}

/// Draws [values] in turn, over and over.
class _Dice implements math.Random {
  _Dice(this.values);

  final List<double> values;
  var _next = 0;

  @override
  double nextDouble() => values[_next++ % values.length];

  @override
  int nextInt(int max) => (nextDouble() * max).floor();

  @override
  bool nextBool() => nextDouble() < 0.5;
}

/// Asset files by key.
class _Bundle extends CachingAssetBundle {
  _Bundle(this.files);

  final Map<String, String> files;

  @override
  Future<ByteData> load(String key) async => ByteData.sublistView(Uint8List.fromList(utf8.encode(files[key]!)));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('the bundled set is the six pak effects at gain 1, rate 1, each with its length', () async {
    final set = await PetSoundSet.load('naiwa');
    expect(set.clips.keys, ['hahahahahahaha', 'dajiaosei', 'diu', 'andi', 'gagadilaxia', 'houla']);
    for (final clip in set.clips.values) {
      expect((clip.gain, clip.vary), (1.0, 0.0));
      expect(clip.ms, greaterThan(0));
      expect((await rootBundle.load(set.assetOf(clip))).lengthInBytes, greaterThan(0));
    }
    final laugh = set.clips['hahahahahahaha']!;
    expect(laugh.ms, 25287);
    final data = await rootBundle.load(set.assetOf(laugh));
    expect(data.lengthInBytes, 557646);
    expect(
      sha256.convert(data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes)).toString(),
      '1ab7df516239b45d12bbed056c211618d6d58b83783da158aad7167306d67ffc',
      reason: 'the whole 25.286531 s of dynamo_singularity_lp, resampled to 11025 Hz for SoundPool',
    );
    final native = _Native()..install();
    var now = DateTime(2026, 11, 7);
    final player = PetSoundPlayer(clock: () => now, random: _Dice([0, 0.999]), appVisible: () => true);
    expect(await player.cue(set, PetCues.bite), isFalse);
    expect(await player.cue(set, PetCues.drop), isFalse);
    expect(native.calls, isEmpty);
    for (final cue in ['laugh', 'laugh-point', 'laugh-roll', 'laugh-belly']) {
      expect(await player.cue(set, cue), isTrue);
      expect(native.plays.last, {'asset': set.assetOf(laugh), 'volume': 1.0, 'rate': 1.0});
      now = now.add(const Duration(seconds: 2));
    }
    await player.release();
  });

  group('PetSoundSet', () {
    test('clips with their gain and vary, cues as clip lists, assets beside sounds.json', () {
      final set = PetSoundSet.parse(_json());
      expect(set.id, 'naiwa');
      expect(set.name, '奶蛙鬼畜音效');
      expect(set.author, 'github.com/cxsunflower');
      expect(set.source, startsWith('app/tool/make_pet_sounds.py'));
      final big = set.clips['laugh']!;
      expect(big.file, 'laugh.wav');
      expect(big.gain, 1.0);
      expect(big.vary, 0.08);
      expect(big.ms, 15000);
      final triple = set.clips['laugh-2']!;
      expect(triple.gain, 1.0, reason: 'gain defaults to 1');
      expect(triple.vary, 0.1, reason: 'vary defaults to 0.1');
      expect(triple.ms, isNull, reason: 'ms is optional');
      expect(set.cue('laugh').map((c) => c.id), ['laugh', 'laugh-2']);
      expect(set.cue(PetCues.bite).map((c) => c.id), ['chomp-1', 'chomp-2', 'crunch']);
      expect(set.cue(PetCues.drop).single.file, 'thud.wav');
      expect(set.cue('sleep'), isEmpty, reason: 'a silent animation');
      expect(set.assetOf(big), 'assets/pet_sounds/naiwa/laugh.wav');
    });

    test('the name falls back to the id', () {
      expect(PetSoundSet.parse(_json()..remove('name')).name, 'naiwa');
    });

    test('another schema, a bad id, no clips or no cues: refused', () {
      expect(() => PetSoundSet.parse({..._json(), 'schema': 2}), throwsFormatException);
      for (final id in [null, '', 'Naiwa', 'nai wa', '../naiwa']) {
        expect(() => PetSoundSet.parse({..._json(), 'id': id}), throwsFormatException, reason: '$id');
      }
      expect(
        () => PetSoundSet.parse({
          ..._json(),
          'clips': ['laugh.wav'],
        }),
        throwsFormatException,
      );
      expect(() => PetSoundSet.parse(_json()..remove('cues')), throwsFormatException);
    });

    test('a clip that is not a .wav beside sounds.json is dropped', () {
      final set = PetSoundSet.parse({
        ..._json(),
        'clips': {
          'ok': {'file': 'ok.wav'},
          'up': {'file': '../up.wav'},
          'folder': {'file': 'x/folder.wav'},
          'windows': {'file': r'x\windows.wav'},
          'dots': {'file': 'a..wav'},
          'mp3': {'file': 'ok.mp3'},
          'bare': {'file': '.wav'},
          'none': {'gain': 1},
        },
        'cues': {
          'laugh': ['ok', 'up', 'folder'],
          'shocked': ['windows', 'mp3'],
        },
      });
      expect(set.clips.keys, ['ok']);
      expect(set.cues, {
        'laugh': ['ok'],
      });
    });

    test('a cue naming a missing clip loses it; a cue with none left is gone', () {
      final set = PetSoundSet.parse({
        ..._json(),
        'cues': {
          'laugh': ['laugh', 'nope', 7],
          'shocked': ['nope'],
          '@drop': 'thud',
        },
      });
      expect(set.cues, {
        'laugh': ['laugh'],
      });
      expect(set.cue('shocked'), isEmpty);
    });

    test('gain is held to 0–1, vary to 0–0.3', () {
      final set = PetSoundSet.parse({
        ..._json(),
        'clips': {
          'loud': {'file': 'loud.wav', 'gain': 3, 'vary': 0.9},
          'below': {'file': 'below.wav', 'gain': -1, 'vary': -0.2},
          'odd': {'file': 'odd.wav', 'gain': 'max', 'vary': null},
        },
      });
      expect([for (final c in set.clips.values) (c.gain, c.vary)], [(1.0, 0.3), (0.0, 0.0), (1.0, 0.1)]);
    });

    test('loads assets/pet_sounds/<id>/sounds.json through the pets’ asset bundle', () async {
      final c = ProviderContainer(
        overrides: [
          petAssetBundleProvider.overrideWithValue(
            _Bundle({'assets/pet_sounds/naiwa/sounds.json': jsonEncode(_json())}),
          ),
        ],
      );
      addTearDown(c.dispose);
      final set = await c.read(petSoundSetProvider('naiwa').future);
      expect(set.cue('laugh'), hasLength(2));
    });
  });

  group('PetSoundPlayer', () {
    late DateTime now;
    final set = PetSoundSet.parse(_json());

    setUp(() => now = DateTime(2026, 11, 7, 12));

    void wait(int ms) => now = now.add(Duration(milliseconds: ms));

    PetSoundPlayer player({math.Random? random, bool Function()? visible}) =>
        PetSoundPlayer(clock: () => now, random: random ?? math.Random(1), appVisible: visible ?? () => true);

    test('the laugh may follow any other sound at once, but not itself', () async {
      final native = _Native()..install();
      final p = player();
      final sounds = await PetSoundSet.load('naiwa');
      expect(await p.cue(sounds, 'poke-left'), isTrue);
      wait(280);
      expect(await p.cue(sounds, 'laugh'), isTrue);
      expect(native.plays.last['asset'], endsWith('/hahahahahahaha.wav'));
      wait(80);
      expect(await p.cue(sounds, 'laugh-point'), isFalse, reason: 'the long laugh needs no second start');
      expect(native.plays, hasLength(2));
    });

    test('prepare loads a set once, every clip of it', () async {
      final native = _Native()..install();
      final p = player();
      await p.prepare(set);
      await p.prepare(set);
      expect(await p.cue(set, 'laugh'), isTrue);
      expect(native.methods, ['load', 'play']);
      expect(native.calls.first.arguments, {
        'assets': [
          'assets/pet_sounds/naiwa/laugh.wav',
          'assets/pet_sounds/naiwa/laugh-2.wav',
          'assets/pet_sounds/naiwa/gasp.wav',
          'assets/pet_sounds/naiwa/chomp-1.wav',
          'assets/pet_sounds/naiwa/chomp-2.wav',
          'assets/pet_sounds/naiwa/crunch.wav',
          'assets/pet_sounds/naiwa/thud.wav',
        ],
      });
      await p.prepare(PetSoundSet.parse({..._json(), 'id': 'other'}));
      expect(native.methods, ['load', 'play', 'load'], reason: 'another set loads on its own');
    });

    test('a cue before prepare loads its set first', () async {
      final native = _Native()..install();
      expect(await player().cue(set, 'laugh'), isTrue);
      expect(native.methods, ['load', 'play']);
    });

    test('play: the clip, its gain times the cue’s (at most 1), the pitch within its vary', () async {
      final native = _Native()..install();
      // One clip: nothing to pick; 0.75 raises the pitch by half its vary.
      final p = player(random: _Dice([0.75]));
      expect(await p.cue(set, 'shocked', gain: 0.5), isTrue);
      wait(2000);
      expect(await p.cue(set, 'shocked', gain: 3), isTrue);
      final plays = native.plays;
      expect(plays, hasLength(2));
      expect(plays[0]['asset'], 'assets/pet_sounds/naiwa/gasp.wav');
      expect(plays[0]['volume'], closeTo(0.4, 1e-9));
      expect(plays[0]['rate'], closeTo(1.1, 1e-9));
      expect(plays[1]['volume'], 1.0);
    });

    test('true means the play went out, whatever the native side made of it', () async {
      _Native(played: false).install();
      expect(await player().cue(set, 'laugh'), isTrue);
    });

    test('several clips: never the same one twice in a row, even when the dice says so', () async {
      final native = _Native()..install();
      // Always the first of what there is to pick from.
      final p = player(random: _Dice([0]));
      for (var i = 0; i < 6; i++) {
        expect(await p.cue(set, PetCues.bite), isTrue);
        wait(1200);
      }
      final bites = [for (final a in native.plays) a['asset']];
      for (var i = 1; i < bites.length; i++) {
        expect(bites[i], isNot(bites[i - 1]), reason: '$bites');
      }
      // A single clip has nothing else to play.
      wait(2000);
      expect(await p.cue(set, PetCues.drop), isTrue);
      wait(2000);
      expect(await p.cue(set, PetCues.drop), isTrue);
      expect(native.plays.skip(6).map((a) => a['asset']), everyElement('assets/pet_sounds/naiwa/thud.wav'));
    });

    test('any two sounds at least 280 ms apart; a dropped one is not queued', () async {
      final native = _Native()..install();
      final p = player();
      expect(await p.cue(set, 'laugh'), isTrue);
      wait(279);
      expect(await p.cue(set, PetCues.drop), isFalse);
      wait(1);
      expect(await p.cue(set, PetCues.drop), isTrue);
      expect(native.plays, hasLength(2));
    });

    test('wouldAllow asks without playing or spending a limit', () async {
      final native = _Native()..install();
      final p = player();
      expect(p.wouldAllow(set, 'laugh'), isTrue);
      expect(native.calls, isEmpty, reason: 'a question is not a play');
      expect(p.wouldAllow(set, 'laugh'), isTrue, reason: 'and does not reserve anything');
      expect(p.wouldAllow(set, 'sleep'), isFalse, reason: 'no clip for that cue');
      expect(await p.cue(set, 'laugh'), isTrue);
      wait(80);
      expect(p.wouldAllow(set, 'laugh'), isFalse, reason: 'the same cue within 1.5 s');
      expect(p.wouldAllow(set, PetCues.drop), isFalse, reason: 'within 280 ms of the last sound');
      wait(200);
      expect(p.wouldAllow(set, PetCues.drop), isTrue);
      expect(native.plays, hasLength(1), reason: 'only the one real play went out');
    });

    test('wouldAllow keeps the minute and the app’s foreground', () async {
      final native = _Native()..install();
      var visible = true;
      final p = player(visible: () => visible);
      for (var i = 0; i < PetSoundPlayer.perMinute; i++) {
        expect(await p.cue(set, 'laugh'), isTrue, reason: 'sound ${i + 1}');
        wait(2000);
      }
      expect(p.wouldAllow(set, 'laugh'), isFalse, reason: 'the minute is full');
      expect(p.wouldAllow(set, PetCues.bite), isTrue, reason: 'bites are outside that count');
      visible = false;
      expect(p.wouldAllow(set, 'laugh'), isFalse, reason: 'not in front');
      expect(native.plays, hasLength(PetSoundPlayer.perMinute));
    });

    test('the same cue at least 1.5 s apart, a bite 1.2 s', () async {
      final native = _Native()..install();
      final p = player();
      expect(await p.cue(set, 'laugh'), isTrue);
      wait(1000);
      expect(await p.cue(set, 'laugh'), isFalse);
      expect(await p.cue(set, 'shocked'), isTrue, reason: 'another cue is free to play');
      wait(499);
      expect(await p.cue(set, 'laugh'), isFalse);
      wait(1);
      expect(await p.cue(set, 'laugh'), isTrue);
      wait(1000);
      expect(await p.cue(set, PetCues.bite), isTrue);
      wait(1199);
      expect(await p.cue(set, PetCues.bite), isFalse);
      wait(1);
      expect(await p.cue(set, PetCues.bite), isTrue, reason: 'sooner than 1.5 s');
      expect(native.plays, hasLength(5));
    });

    test('at most 24 sounds in any minute', () async {
      final native = _Native()..install();
      final p = player();
      for (var i = 0; i < PetSoundPlayer.perMinute; i++) {
        expect(await p.cue(set, 'laugh'), isTrue, reason: 'sound ${i + 1}');
        wait(2000);
      }
      // Played from 0 to 46 s; at 48 s the minute is full.
      expect(await p.cue(set, 'laugh'), isFalse);
      wait(11999);
      expect(await p.cue(set, 'laugh'), isFalse, reason: 'the first is 59.999 s old');
      wait(1);
      expect(await p.cue(set, 'laugh'), isTrue, reason: 'the first has left the minute');
      expect(native.plays, hasLength(PetSoundPlayer.perMinute + 1));
    });

    test('with the minute’s 24 used up, bites still play', () async {
      final native = _Native()..install();
      final p = player();
      for (var i = 0; i < PetSoundPlayer.perMinute; i++) {
        expect(await p.cue(set, 'laugh'), isTrue, reason: 'sound ${i + 1}');
        wait(2000);
      }
      expect(await p.cue(set, 'shocked'), isFalse, reason: 'the minute is full');
      expect(await p.cue(set, PetCues.bite), isTrue);
      wait(1200);
      expect(await p.cue(set, PetCues.bite), isTrue);
      expect(native.plays, hasLength(PetSoundPlayer.perMinute + 2));
    });

    test('bites take none of the 24: after a long run of them a laugh still plays', () async {
      final native = _Native()..install();
      final p = player();
      // Twice the minute's count, all within the last minute when the laugh comes.
      for (var i = 0; i < 2 * PetSoundPlayer.perMinute; i++) {
        expect(await p.cue(set, PetCues.bite), isTrue, reason: 'bite ${i + 1}');
        wait(1200);
      }
      expect(await p.cue(set, 'laugh'), isTrue);
      expect(native.plays, hasLength(2 * PetSoundPlayer.perMinute + 1));
    });

    test('bites keep 280 ms from the other sounds, both ways', () async {
      final native = _Native()..install();
      final p = player();
      expect(await p.cue(set, 'laugh'), isTrue);
      wait(279);
      expect(await p.cue(set, PetCues.bite), isFalse);
      wait(1);
      expect(await p.cue(set, PetCues.bite), isTrue);
      wait(279);
      expect(await p.cue(set, 'shocked'), isFalse);
      wait(1);
      expect(await p.cue(set, 'shocked'), isTrue);
      expect(native.plays, hasLength(3));
    });

    test('not in front: nothing goes out', () async {
      final native = _Native()..install();
      var visible = false;
      final p = player(visible: () => visible);
      expect(await p.cue(set, 'laugh'), isFalse);
      expect(native.calls, isEmpty);
      visible = true;
      expect(await p.cue(set, 'laugh'), isTrue, reason: 'the dropped cue held nothing back');
    });

    test('a cue the set has no clip for plays nothing', () async {
      final native = _Native()..install();
      expect(await player().cue(set, 'sleep'), isFalse);
      expect(native.calls, isEmpty);
    });

    test('a native error is swallowed: false, nothing thrown', () async {
      final native = _Native(error: PlatformException(code: 'bad_asset'))..install();
      final p = player();
      await p.prepare(set);
      expect(await p.cue(set, 'laugh'), isFalse);
      await p.release();
      expect(native.methods, ['load', 'play', 'release']);
    });

    test('without the native side nothing throws and nothing plays', () async {
      _Native(error: MissingPluginException()).install();
      final p = player();
      await p.prepare(set);
      expect(await p.cue(set, 'laugh'), isFalse);
      await p.release();
    });

    test('release lets the pool go; the next cue loads its set again', () async {
      final native = _Native()..install();
      final p = player();
      await p.cue(set, 'laugh');
      await p.release();
      wait(2000);
      await p.cue(set, 'laugh');
      expect(native.methods, ['load', 'play', 'release', 'load', 'play']);
    });

    test('release during prepare cancels the pending cue but allows a fresh cue', () async {
      final loading = Completer<void>();
      final prepared = Completer<void>();
      final methods = <String>[];
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(_channel, (call) async {
        methods.add(call.method);
        if (call.method == 'load' && !loading.isCompleted) {
          loading.complete();
          await prepared.future;
        }
        return call.method == 'play' ? true : null;
      });
      addTearDown(() {
        if (!prepared.isCompleted) prepared.complete();
        messenger.setMockMethodCallHandler(_channel, null);
      });
      final p = player();
      final pending = p.cue(set, 'laugh');
      await loading.future;
      expect(methods, ['load']);

      await p.release();
      prepared.complete();
      expect(await pending, isFalse);
      expect(methods, ['load', 'release'], reason: 'the cancelled cue must never send play');

      wait(2000);
      expect(await p.cue(set, 'laugh'), isTrue);
      expect(methods, ['load', 'release', 'load', 'play']);
    });

    test('the app’s player runs on the pet clock and lets go with its container', () async {
      final native = _Native()..install();
      final c = ProviderContainer(overrides: [petClockProvider.overrideWithValue(() => now)]);
      final p = c.read(petSoundPlayerProvider);
      expect(await p.cue(set, 'laugh'), isTrue);
      wait(300);
      expect(await p.cue(set, 'shocked'), isTrue, reason: '300 ms went by on the pet clock');
      c.dispose();
      await pumpEventQueue();
      expect(native.methods.last, 'release');
    });
  });

  group('「音效」', () {
    Future<ProviderContainer> load(Map<String, Object> stored) async {
      SharedPreferences.setMockInitialValues(stored);
      final c = ProviderContainer();
      addTearDown(c.dispose);
      c.read(petPrefsProvider);
      for (var i = 0; i < 40 && !c.read(petPrefsProvider).loaded; i++) {
        await Future<void>.delayed(Duration.zero);
      }
      expect(c.read(petPrefsProvider).loaded, isTrue);
      return c;
    }

    test('removed Naiwa skins migrate to classic without changing other preferences', () async {
      for (final id in ['naiwa-galaxy', 'naiwa-gb']) {
        final c = await load({PetPrefsController.keys.pack: id, PetPrefsController.keys.sound: false});
        expect(c.read(petPrefsProvider).packId, 'naiwa');
        expect(c.read(petPrefsProvider).sound, isFalse);
        expect((await SharedPreferences.getInstance()).getString(PetPrefsController.keys.pack), 'naiwa');
      }
    });

    test('on by default; switched off, it stays off', () async {
      final c = await load({});
      expect(c.read(petPrefsProvider).sound, isTrue);
      await c.read(petPrefsProvider.notifier).setSound(false);
      expect(c.read(petPrefsProvider).sound, isFalse);
      expect((await SharedPreferences.getInstance()).getBool(PetPrefsController.keys.sound), isFalse);
      final again = await load({PetPrefsController.keys.sound: false});
      expect(again.read(petPrefsProvider).sound, isFalse);
    });
  });
}
