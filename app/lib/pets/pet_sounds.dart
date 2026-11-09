// The pet's sounds (docs/design/naiwa-pet.md §6): a sound set
// (`assets/pet_sounds/<id>/sounds.json` and its .wav clips) and the player
// that hands cues to the native SoundPool (MethodChannel `dsh/pet_sound`;
// native: android/.../pet/PetSoundPlugin.kt). Whether the pet may sound at
// all (its pack names a set, 「音效」 on, not quiet, visible) is the chat
// page's call; the player keeps to the foreground and the limits, picks the
// clip and varies its pitch.
//
// Every call tolerates the native side being absent (widget tests, desktop):
// nothing plays.

import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'pet_signals.dart';

/// Naiwa's whole laugh recording: 557,568 source frames at 22050 Hz is
/// 25.286530612... s. Its 11025 Hz copy holds 278,784 frames, the same
/// duration. Milliseconds are rounded to nearest, as the generator writes
/// `ms`; one constant keeps the pose and the audio together.
const naiwaLaughDuration = Duration(milliseconds: 25287);

/// One clip of a set: a .wav beside its sounds.json.
@immutable
class PetClip {
  const PetClip({required this.id, required this.file, this.gain = 1, this.vary = 0.1, this.ms});

  final String id;
  final String file;

  /// Loudness, 0–1.
  final double gain;

  /// How far each play may shift the pitch, 0–0.3: 0.1 plays at 0.9–1.1×.
  final double vary;

  /// The recording's own length, ms; a reaction with a sound keeps its pose
  /// this long (docs/design/naiwa-pet.md §6.2). Null when unknown.
  final int? ms;
}

/// Special cues besides animation names.
abstract final class PetCues {
  /// A code glyph eaten on the chat page.
  static const bite = '@bite';

  /// Let go after a drag.
  static const drop = '@drop';

  /// The quick tap chain's laugh, which may follow a poke at once; the
  /// same-cue and per-minute limits still apply.
  static const tapChain = {'laugh'};
}

/// A sound set: its clips, and the clips each cue (an animation name, or one
/// of [PetCues]) picks from.
@immutable
class PetSoundSet {
  const PetSoundSet({
    required this.id,
    required this.name,
    this.author,
    this.license,
    this.source,
    this.clips = const {},
    this.cues = const {},
  });

  /// Folder name under `assets/pet_sounds/`.
  final String id;
  final String name;
  final String? author;
  final String? license;
  final String? source;

  /// Clip id → clip.
  final Map<String, PetClip> clips;

  /// Cue → the ids of the clips it picks from.
  final Map<String, List<String>> cues;

  static const schema = 1;

  /// Asset path of the set's folder.
  static String folder(String id) => 'assets/pet_sounds/$id';

  String assetOf(PetClip clip) => '${folder(id)}/${clip.file}';

  /// The clips [key] picks from; none for a cue the set doesn't have.
  List<PetClip> cue(String key) => [for (final clip in cues[key] ?? const <String>[]) ?clips[clip]];

  /// Parses sounds.json. A file that fails its checks throws
  /// [FormatException]; a clip that is not a .wav beside it, and a cue's
  /// reference to a missing clip, are dropped.
  factory PetSoundSet.parse(Map<String, Object?> json) {
    if (json['schema'] != schema) throw const FormatException('sounds.json: schema');
    final id = _string(json['id']);
    if (id == null || !_id.hasMatch(id)) throw const FormatException('sounds.json: id');
    if (json['clips'] is! Map) throw const FormatException('sounds.json: clips');
    if (json['cues'] is! Map) throw const FormatException('sounds.json: cues');

    final clips = <String, PetClip>{};
    for (final MapEntry(:key, :value) in _map(json['clips']).entries) {
      final m = _map(value);
      final file = _string(m['file']);
      if (file == null || !_wav.hasMatch(file) || file.contains('..')) continue;
      clips[key] = PetClip(
        id: key,
        file: file,
        gain: (_num(m['gain']) ?? 1.0).clamp(0.0, 1.0),
        vary: (_num(m['vary']) ?? 0.1).clamp(0.0, 0.3),
        ms: switch (_num(m['ms'])) {
          final ms? when ms.isFinite && ms > 0 => ms.round(),
          _ => null,
        },
      );
    }
    final cues = <String, List<String>>{
      for (final MapEntry(:key, :value) in _map(json['cues']).entries)
        key: [
          for (final clip in _list(value))
            if (clip is String && clips.containsKey(clip)) clip,
        ],
    }..removeWhere((_, v) => v.isEmpty);

    return PetSoundSet(
      id: id,
      name: _string(json['name']) ?? id,
      author: _string(json['author']),
      license: _string(json['license']),
      source: _string(json['source']),
      clips: clips,
      cues: cues,
    );
  }

  /// Reads `assets/pet_sounds/<id>/sounds.json` from [bundle].
  static Future<PetSoundSet> load(String id, [AssetBundle? bundle]) async {
    final raw = await (bundle ?? rootBundle).loadString('${folder(id)}/sounds.json');
    final json = jsonDecode(raw);
    if (json is! Map<String, Object?>) throw const FormatException('sounds.json');
    return PetSoundSet.parse(json);
  }

  static final _id = RegExp(r'^[a-z0-9-]+$');
  static final _wav = RegExp(r'^[^/\\]+\.wav$');

  static String? _string(Object? v) => v is String ? v : null;
  static double? _num(Object? v) => v is num ? v.toDouble() : null;
  static Map<String, Object?> _map(Object? v) =>
      v is Map ? {for (final MapEntry(:key, :value) in v.entries) '$key': value} : const {};
  static List<Object?> _list(Object? v) => v is List ? v : const [];
}

/// Plays cues through the native SoundPool (`dsh/pet_sound`), within §6.2's limits.
class PetSoundPlayer {
  PetSoundPlayer({MethodChannel? channel, DateTime Function()? clock, math.Random? random, bool Function()? appVisible})
    : _channel = channel ?? const MethodChannel(channelName),
      _clock = clock ?? DateTime.now,
      _random = random ?? math.Random(),
      _appVisible = appVisible ?? _resumed;

  static const channelName = 'dsh/pet_sound';

  /// Between any two sounds.
  static const minGap = Duration(milliseconds: 280);

  /// Between two plays of one cue ([biteGap] for bites).
  static const sameCueGap = Duration(milliseconds: 1500);

  /// Between two bites, however fast the glyphs go in.
  static const biteGap = Duration(milliseconds: 1200);

  /// Sounds in any one minute, bites aside: eating a streaming reply bites
  /// glyph after glyph and would use them all up before the turn's laugh.
  static const perMinute = 24;

  final MethodChannel _channel;
  final DateTime Function() _clock;
  final math.Random _random;
  final bool Function() _appVisible;

  /// Sets handed to the native side.
  final _loaded = <String>{};
  int _epoch = 0;

  /// When the last sound played, a bite or not.
  DateTime? _lastSound;

  /// When the sounds of the last minute played, oldest first, bites left out.
  final _played = <DateTime>[];

  /// Cue → when it last played.
  final _lastAt = <String, DateTime>{};

  /// Cue → the clip it last played.
  final _lastClip = <String, String>{};

  static bool _resumed() {
    final state = WidgetsBinding.instance.lifecycleState;
    return state == null || state == AppLifecycleState.resumed;
  }

  /// Hands [set]'s clips to the native side to load, once per set.
  Future<void> prepare(PetSoundSet set) async {
    if (!_loaded.add(set.id)) return;
    try {
      await _channel.invokeMethod<void>('load', {
        'assets': [for (final clip in set.clips.values) set.assetOf(clip)],
      });
    } on MissingPluginException {
      // Tests, desktop: no sound.
    } on PlatformException {
      // A clip the native side refused stays silent.
    }
  }

  /// Plays one of [key]'s clips at [gain] × the clip's own. True when the
  /// play went to the native side (which may still stay silent: in a call,
  /// not loaded yet). False when the app is away, the set has no such
  /// cue, a limit drops it (nothing is queued) or the native side failed.
  Future<bool> cue(PetSoundSet set, String key, {double gain = 1}) async {
    final epoch = _epoch;
    if (!_appVisible()) return false;
    final clips = set.cue(key);
    if (clips.isEmpty) return false;
    final now = _clock();
    if (!_allows(key, now)) return false;
    _remember(key, now);
    final clip = _pick(key, clips);
    final rate = 1 + (_random.nextDouble() * 2 - 1) * clip.vary;
    final volume = (clip.gain * gain).clamp(0.0, 1.0);
    await prepare(set);
    if (epoch != _epoch || !_appVisible()) return false;
    try {
      await _channel.invokeMethod<bool>('play', {'asset': set.assetOf(clip), 'volume': volume, 'rate': rate});
      return true;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  /// Whether [cue] would sound [key] now, without playing it or changing any
  /// limit: the page asks before it switches to a reaction whose sound would
  /// be dropped, so the pose and its recording stay together. Same conditions
  /// as [cue] short of the native call.
  bool wouldAllow(PetSoundSet set, String key, {DateTime? at}) {
    if (!_appVisible()) return false;
    if (set.cue(key).isEmpty) return false;
    return _allows(key, at ?? _clock());
  }

  void _remember(String key, DateTime now) {
    _played.removeWhere((t) => now.difference(t) >= const Duration(minutes: 1));
    _lastSound = now;
    _lastAt[key] = now;
    if (key != PetCues.bite) _played.add(now);
  }

  /// Cancels pending cues and the current voice, keeping decoded clips ready.
  Future<void> stop() async {
    _epoch++;
    try {
      await _channel.invokeMethod<void>('stop');
    } on MissingPluginException {
      // Tests, desktop: nothing is playing.
    } on PlatformException {
      // The native player may already have gone away.
    }
  }

  /// Lets the native SoundPool go; a later cue loads its set again.
  Future<void> release() async {
    _epoch++;
    _loaded.clear();
    try {
      await _channel.invokeMethod<void>('release');
    } on MissingPluginException {
      // Tests, desktop: nothing was loaded.
    } on PlatformException {
      // Nothing more to let go of from here.
    }
  }

  /// §6.2's limits; a bite is held back by [minGap] and [biteGap] only. Pure:
  /// neither [cue] nor [wouldAllow] changes the window here; [cue] prunes it
  /// when it remembers a play.
  bool _allows(String key, DateTime now) {
    final bite = key == PetCues.bite;
    if (!bite && _played.where((t) => now.difference(t) < const Duration(minutes: 1)).length >= perMinute) {
      return false;
    }
    final lastSound = _lastSound;
    // A quick tap chain deliberately changes the poke into a laugh; same-cue
    // and per-minute limits still apply.
    if (key != 'laugh-belly' && !PetCues.tapChain.contains(key) &&
        lastSound != null && now.difference(lastSound) < minGap) {
      return false;
    }
    final last = _lastAt[key];
    return last == null || now.difference(last) >= (bite ? biteGap : sameCueGap);
  }

  /// One of [clips] at random; with more than one, not the one [key] played last.
  PetClip _pick(String key, List<PetClip> clips) {
    final fresh = [
      for (final c in clips)
        if (c.id != _lastClip[key]) c,
    ];
    final from = fresh.isEmpty ? clips : fresh;
    final clip = from.length == 1 ? from.single : from[_random.nextInt(from.length)];
    _lastClip[key] = clip.id;
    return clip;
  }
}

/// One sound set, loaded once per id.
final petSoundSetProvider = FutureProvider.family<PetSoundSet, String>(
  (ref, id) => PetSoundSet.load(id, ref.watch(petAssetBundleProvider)),
);

/// The chat page's pet's player; its native SoundPool goes with it.
final petSoundPlayerProvider = Provider<PetSoundPlayer>((ref) {
  final player = PetSoundPlayer(clock: ref.watch(petClockProvider));
  ref.onDispose(() => unawaited(player.release()));
  return player;
});
