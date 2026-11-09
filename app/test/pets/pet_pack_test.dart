// The runtime pack format (docs/design/pets.md §3): the shipped packs parse
// with their measured values, animations resolve by state and tier, hit boxes
// by the documented lookup order, and broken packs are refused whole, while a
// bad optional `sounds` or `snack` (docs/design/naiwa-pet.md §5) only reads as
// absent.

import 'dart:convert';
import 'dart:io';

import 'package:dsh_app/pets/pet_pack.dart';
import 'package:dsh_app/pets/pet_prefs.dart';
import 'package:dsh_app/pets/pet_state.dart';
import 'package:dsh_app/ui/pets/pet_sprite.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, Object?> _json(String id) =>
    jsonDecode(File('assets/pets/$id/pack.json').readAsStringSync()) as Map<String, Object?>;

PetPack diskPack(String id) => PetPack.parse(_json(id));
final deepy = diskPack('deepy-whale');
final girl = diskPack('whale-girl');

class _NaiwaBundle extends CachingAssetBundle {
  final paths = <String>[];

  @override
  Future<String> loadString(String key, {bool cache = true}) async {
    paths.add(key);
    if (key != 'assets/pets/naiwa/pack.json') throw StateError('Unexpected asset: $key');
    return jsonEncode(_json('naiwa'));
  }

  @override
  Future<ByteData> load(String key) => throw StateError('This bundle only serves the manifest: $key');
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Naiwa permits free dragging and uses the prone mouth for eating', () {
    final pack = PetPack.parse(_json('naiwa'));
    expect(pack.freeRoam, isTrue);
    expect(pack.dragMirror, isTrue, reason: 'drags left mirror the art and its mouth');
    expect(deepy.freeRoam, isFalse);
    expect(deepy.dragMirror, isFalse);
    expect(girl.dragMirror, isFalse);
    expect(pack.snack!.mouthOf('prone-eat'), pack.snack!.mouths['prone-eat']);
    expect(pack.snack!.mouthOf('idle'), pack.snack!.mouth);
    expect(pack.snack!.everyOf('prone-eat'), greaterThan(0));
  });

  group('Naiwa pixel pack', () {
    test('loads its own sprite manifest and feeding anchors', () async {
      final bundle = _NaiwaBundle();
      final pack = await PetPack.load('naiwa', bundle);
      expect(pack.id, 'naiwa');
      expect(pack.pixelArt, isTrue);
      expect(pack.sounds, 'naiwa');
      expect(pack.snack!.mouthOf('prone-eat'), diskPack('naiwa').snack!.mouthOf('prone-eat'));
      expect(bundle.paths, ['assets/pets/naiwa/pack.json']);
    });
  });

  group('pet choices and saved preferences', () {
    Future<ProviderContainer> load(String? id) async {
      SharedPreferences.setMockInitialValues({
        PetPrefsController.keys.pack: ?id,
        PetPrefsController.keys.size: 'large',
        PetPrefsController.keys.quiet: true,
        PetPrefsController.keys.sound: false,
        PetPrefsController.keys.position: 0.7,
        PetPrefsController.keys.hidden: DateTime(2030).millisecondsSinceEpoch,
      });
      final container = ProviderContainer();
      addTearDown(container.dispose);
      container.read(petPrefsProvider);
      await pumpEventQueue();
      expect(container.read(petPrefsProvider).loaded, isTrue);
      return container;
    }

    test('original pets remain available, adding pixel Naiwa with Deepy the default', () {
      expect(builtInPets, ['deepy-whale', 'whale-girl', 'naiwa']);
      expect(defaultPetId, 'deepy-whale');
      expect(const PetPrefs().packId, 'deepy-whale');
    });

    for (final id in ['nailong', 'naiwa-galaxy', 'naiwa-gb', 'naiwa-live2d']) {
      test('retired $id migrates without changing the other preferences', () async {
        final container = await load(id);
        final prefs = container.read(petPrefsProvider);
        expect(prefs.packId, 'naiwa');
        expect(prefs.packExplicit, isTrue);
        expect(prefs.size, PetSize.large);
        expect(prefs.quiet, isTrue);
        expect(prefs.sound, isFalse);
        expect(prefs.position, 0.7);
        expect(prefs.hiddenUntil, DateTime(2030));
        expect((await SharedPreferences.getInstance()).getString(PetPrefsController.keys.pack), 'naiwa');
      });
    }

    for (final id in ['deepy-whale', 'whale-girl', 'naiwa', noPetId]) {
      test('current choice $id stays explicit and unchanged', () async {
        final container = await load(id);
        expect(container.read(petPrefsProvider).packId, id);
        expect(container.read(petPrefsProvider).packExplicit, isTrue);
        expect((await SharedPreferences.getInstance()).getString(PetPrefsController.keys.pack), id);
      });
    }

    test('a stale caller also saves the migrated choice', () async {
      final container = await load(noPetId);
      await container.read(petPrefsProvider.notifier).setPack('nailong');
      expect(container.read(petPrefsProvider).packId, 'naiwa');
      expect(container.read(petPrefsProvider).hiddenUntil, isNull);
      expect((await SharedPreferences.getInstance()).getString(PetPrefsController.keys.pack), 'naiwa');
    });
  });

  group('Deepy 小鲸鱼', () {
    test('canvas, 5× sheets, foot point, body', () {
      expect(deepy.id, 'deepy-whale');
      expect(deepy.name, 'Deepy 小鲸鱼');
      expect(deepy.scale, 5);
      expect(deepy.pixelArt, isTrue);
      expect(deepy.canvas, const Size(52, 52));
      expect(deepy.anchorX, 28);
      expect(deepy.baseline, 48);
      expect(deepy.contentBox, const Rect.fromLTWH(12, 26, 36, 22));
    });

    test('cells sit in a grid of cols, cropped to box', () {
      final idle = deepy.animFor(PetStateName.idle);
      expect(idle.name, 'idle');
      expect(idle.frameWidth, idle.box.width * 5);
      expect(idle.frameHeight, idle.box.height * 5);
      expect(idle.sourceRect(0), Rect.fromLTWH(0, 0, idle.frameWidth.toDouble(), idle.frameHeight.toDouble()));
      final next = idle.sourceRect(idle.cols);
      expect(next.left, 0, reason: 'cell `cols` starts the second row');
      expect(next.top, idle.frameHeight.toDouble());
      expect(idle.durationMs, idle.frames.fold<int>(0, (s, f) => s + f.ms));
    });

    test('every sheet fits a 4096 texture', () {
      for (final a in deepy.animations.values) {
        final cells = a.frames.map((f) => f.i).reduce((x, y) => x > y ? x : y) + 1;
        final rows = (cells / a.cols).ceil();
        expect(a.cols * a.frameWidth, lessThanOrEqualTo(4096), reason: a.name);
        expect(rows * a.frameHeight, lessThanOrEqualTo(4096), reason: a.name);
      }
    });

    test('states and tiers pick their animations', () {
      expect(deepy.animFor(PetStateName.thinking).name, 'thinking');
      expect(deepy.animFor(PetStateName.working, tier: 1).name, 'typing');
      expect(deepy.animFor(PetStateName.working, tier: 2).name, 'music');
      expect(deepy.animFor(PetStateName.working, tier: 3).name, 'building');
      expect(deepy.animFor(PetStateName.working, tier: 7).name, 'building');
      expect(deepy.animFor(PetStateName.juggling, tier: 1).name, 'music');
      expect(deepy.animFor(PetStateName.juggling, tier: 2).name, 'conducting');
      expect(deepy.animFor(PetStateName.notification).name, 'notification');
      expect(deepy.animFor(PetStateName.attention).name, 'happy');
      expect(deepy.animFor(PetStateName.error).name, 'error');
      expect(deepy.animFor(PetStateName.sweeping).name, 'compacting');
      expect(deepy.animFor(PetStateName.carrying).name, 'carrying');
      expect(deepy.animFor(PetStateName.sleeping).name, 'sleeping');
      expect(deepy.animFor(PetStateName.waking).name, 'waking');
    });

    test('reactions, walking, waking, timings', () {
      expect(deepy.reaction('tapLeft')!.name, 'react-left');
      expect(deepy.reaction('tapRight')!.name, 'react-right');
      expect(deepy.reaction('tickle')!.name, 'react-double');
      expect(deepy.reaction('drag')!.name, 'react-drag');
      expect(deepy.reaction('tapLeft')!.loop, isFalse);
      expect(deepy.reaction('drag')!.loop, isTrue);
      expect(deepy.roam.name, 'roam-hop');
      expect(deepy.roamFacing, PetFacing.left);
      expect(deepy.mirrorWalking(right: true), isTrue, reason: 'drawn facing left');
      expect(deepy.mirrorWalking(right: false), isFalse);
      expect(deepy.wakeDuration, 1500);
      expect(deepy.autoReturn.containsKey('notification'), isFalse, reason: 'notification waits until handled');
      expect(deepy.sleepAfter, const Duration(seconds: 60));
      expect(deepy.bonus, isEmpty);
    });

    test('hit boxes: byAnim, then sleeping, then wide, then default', () {
      final hits = _json('deepy-whale')['hitBoxes']! as Map<String, Object?>;
      Rect rect(Object? m) {
        final r = m! as Map<String, Object?>;
        return Rect.fromLTWH(
          (r['x']! as num).toDouble(),
          (r['y']! as num).toDouble(),
          (r['w']! as num).toDouble(),
          (r['h']! as num).toDouble(),
        );
      }

      final byAnim = hits['byAnim']! as Map<String, Object?>;
      for (final MapEntry(:key, :value) in byAnim.entries) {
        expect(deepy.hitBoxFor(deepy.animations[key]!), rect(value), reason: key);
      }
      for (final name in (hits['sleepingAnims']! as List).cast<String>()) {
        if (byAnim.containsKey(name)) continue;
        expect(deepy.hitBoxFor(deepy.animations[name]!), rect(hits['sleeping']), reason: name);
      }
      for (final name in (hits['wideAnims']! as List).cast<String>()) {
        if (byAnim.containsKey(name)) continue;
        expect(deepy.hitBoxFor(deepy.animations[name]!), rect(hits['wide']), reason: name);
      }
      expect(deepy.hitBoxFor(deepy.animations['idle']!), rect(hits['default']));
      expect(deepy.hitBoxFor(deepy.animations['thinking']!), rect(hits['default']), reason: 'the cloud is no body');
    });

    test('idle extras with their play times and interval', () {
      expect(deepy.idles.map((e) => e.anim), ['idle-look', 'idle-spout']);
      expect(deepy.idles.map((e) => e.ms), [6800, 6400]);
      expect(deepy.idleEvery.min, 45000);
      expect(deepy.idleEvery.max, 300000);
      expect(deepy.idleEvery.draw(0), const Duration(seconds: 45));
      expect(deepy.idleEvery.draw(0.999999), const Duration(minutes: 5));
      // The median of min + Exp(mean − min) ≈ 45 + 75 × ln 2 s.
      expect(deepy.idleEvery.draw(0.5).inSeconds, inInclusiveRange(95, 98));
    });
  });

  group('鲸娘', () {
    test('1× pixel art, front-facing swim, attention extras', () {
      expect(girl.name, '鲸娘');
      expect(girl.scale, 1);
      expect(girl.canvas, const Size(69, 66));
      expect(girl.anchorX, 35.5);
      expect(girl.baseline, 60);
      expect(girl.roam.name, 'swim');
      expect(girl.roamFacing, PetFacing.front);
      expect(girl.mirrorWalking(right: true), isFalse);
      expect(girl.mirrorWalking(right: false), isFalse);
      expect(girl.reaction('tapLeft')!.name, 'poke-left');
      expect(girl.reaction('tickle')!.name, 'tickle');
      final bonus = girl.bonusOf(PetStateName.attention)!;
      expect(bonus.anims, unorderedEquals(['smile-hearts', 'thumbs-up']));
      expect(bonus.chance, 0.2);
      expect(girl.wakeDuration, 1880);
      expect(
        girl.hitBoxFor(girl.animations['swim']!).height,
        greaterThan(girl.hitBoxFor(girl.animations['idle']!).height - 1),
      );
    });

    test('each strip is one row', () {
      for (final a in girl.animations.values) {
        final cells = a.frames.map((f) => f.i).reduce((x, y) => x > y ? x : y) + 1;
        expect(a.cols, greaterThanOrEqualTo(cells), reason: a.name);
      }
    });
  });

  group('broken packs are refused', () {
    Map<String, Object?> base() => _json('whale-girl');

    test('another schema', () {
      expect(() => PetPack.parse({...base(), 'schema': 2}), throwsFormatException);
    });

    test('a state naming a missing animation', () {
      final json = base();
      final states = {
        ...json['states']! as Map<String, Object?>,
        'error': ['nope'],
      };
      expect(() => PetPack.parse({...json, 'states': states}), throwsFormatException);
    });

    test('a frame without time', () {
      final json = base();
      final anims = {...json['animations']! as Map<String, Object?>};
      final idle = {...anims['idle']! as Map<String, Object?>};
      idle['frames'] = [
        {'i': 0, 'ms': 0},
      ];
      anims['idle'] = idle;
      expect(() => PetPack.parse({...json, 'animations': anims}), throwsFormatException);
    });

    test('a reaction naming a missing animation', () {
      final json = base();
      expect(
        () => PetPack.parse({
          ...json,
          'reactions': {'tapLeft': 'nope'},
        }),
        throwsFormatException,
      );
    });
  });

  group('sounds and snack', () {
    PetPack parse(Map<String, Object?> extra) => PetPack.parse({..._json('whale-girl'), ...extra});
    PetSnack? snack(Object? x, Object? y, Map<String, Object?> every) => parse({
      'snack': {
        'mouth': {'x': x, 'y': y},
        'every': every,
      },
    }).snack;

    test('the two older packs have neither', () {
      for (final pack in [deepy, girl]) {
        expect(pack.sounds, isNull, reason: pack.id);
        expect(pack.snack, isNull, reason: pack.id);
      }
    });

    test('sounds: a sound set id, anything else reads as none', () {
      expect(parse({'sounds': 'naiwa'}).sounds, 'naiwa');
      expect(parse({'sounds': 'naiwa-2'}).sounds, 'naiwa-2');
      for (final bad in ['Naiwa', 'nai wa', '../naiwa', 'naiwa/x', r'naiwa\x', '', 7, true]) {
        expect(parse({'sounds': bad}).sounds, isNull, reason: '$bad');
      }
    });

    test('snack: the mouth in art pixels, an interval per animation', () {
      final s = snack(33, 31, {'idle': 700, 'swim': 380})!;
      expect(s.mouth, const Offset(33, 31));
      expect(s.every, {'idle': 700, 'swim': 380});
      expect(s.everyOf('swim'), 380);
      expect(s.everyOf('tickle'), isNull, reason: 'no glyphs while it plays');
    });

    test('snack: the mouth must sit on the canvas, its edges included', () {
      final w = girl.canvas.width, h = girl.canvas.height;
      const every = {'idle': 700};
      expect(snack(0, 0, every), isNotNull);
      expect(snack(w, h, every), isNotNull);
      expect(snack(w + 1, 31, every), isNull);
      expect(snack(33, h + 1, every), isNull);
      expect(snack(-1, 31, every), isNull);
      expect(snack(33, -0.5, every), isNull);
      expect(snack('33', 31, every), isNull);
      expect(snack(33, null, every), isNull);
    });

    test('snack: an entry naming no animation or without a positive time is dropped', () {
      final s = snack(33, 31, {'idle': 700, 'nope': 300, 'swim': 0, 'tickle': -5, 'poke-left': 'fast'})!;
      expect(s.every, {'idle': 700});
    });

    test('snack: none left, no snack; the pack itself still loads', () {
      final pack = parse({
        'snack': {
          'mouth': {'x': 33, 'y': 31},
          'every': {'nope': 300, 'swim': 0, 'tickle': -5},
        },
      });
      expect(pack.snack, isNull);
      expect(pack.animations.keys, girl.animations.keys);
    });
  });

  test('a pack still carrying sizeScale reads without it; the app sizes every pet', () {
    final plain = diskPack('naiwa');
    final legacy = PetPack.parse({..._json('naiwa'), 'sizeScale': 2});
    expect(legacy.contentBox, plain.contentBox);
    expect(
      [for (final s in PetSize.values) petDevicePixels(legacy, s, 3)],
      [for (final s in PetSize.values) petDevicePixels(plain, s, 3)],
    );
  });
}
