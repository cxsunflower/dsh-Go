// The chat page's pet (docs/design/pets.md §2). [PetStage] lays a layer over
// the page (the list's layout untouched); the pet stands on the top edge of the
// topmost capsule above the composer ([PetPerch]), following it through a layer
// link in the same frame, hops when that changes, walks about now and then,
// sleeps when left alone, reacts to taps, drags and long presses, and raises a
// bubble when a turn ends or something waits in another conversation. Only its
// body takes touches. A pack's sounds and code snacks play here too
// (docs/design/naiwa-pet.md §6, §7); a pet that eats runs along its perch to
// the reasoning being written ([PetFood]) and walks home once idle.
//
// Interaction: tap left / right, a second quick tap laughs, drag, sleep after
// 60 s idle. The overlay twin lives in Kotlin.

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../pets/pet_mood.dart';
import '../../pets/pet_overlay_bridge.dart';
import '../../pets/pet_pack.dart';
import '../../pets/pet_prefs.dart';
import '../../pets/pet_sheets.dart';
import '../../pets/pet_signals.dart';
import '../../pets/pet_sounds.dart';
import '../../pets/pet_state.dart';
import '../../state/chat_state.dart';
import '../../state/hosts_state.dart';
import '../../state/notify_state.dart' show chatOnScreenProvider;
import '../../state/sessions_state.dart';
import '../../state/ui_mode_state.dart';
import '../chat/widgets/approval_card.dart';
import '../chat/widgets/question_card.dart';
import '../common/discard_guard.dart';
import '../theme/theme.dart';
import 'pet_bubble.dart';
import 'pet_menu.dart';
import 'pet_perch.dart';
import 'pet_snack.dart';
import 'pet_sprite.dart';

/// Geometry and timing shared with the tests.
abstract final class PetMetrics {
  /// The body keeps this far from either end of its perch.
  static const inset = 16.0;

  /// Areas the pet keeps out of grow by this on each side.
  static const avoidGap = 8.0;

  /// The bubble keeps this far from the page's edges.
  static const bubbleMargin = 16.0;

  /// The highest point of a hop above the straight line.
  static const hopHeight = 18.0;
  static const hop = Duration(milliseconds: 380);

  /// Walking speed along the perch, logical px per second.
  static const walkSpeed = 28.0;

  /// How far a walk goes, as a share of the perch.
  static const walkMin = 0.08;
  static const walkMax = 0.2;

  /// Between walks: 45 s – 5 min, about 2 min on average.
  static const roamEvery = PetEvery();

  /// The lift while held.
  static const dragLift = 10.0;

  /// A drag starts after this much movement.
  static const dragSlop = 6.0;

  /// Dragging a pack with `drag.mirror` turns its art left once the foot has
  /// gone this far left; it turns back only after this far right.
  static const dragMirrorSlop = 2.0;

  /// A second tap this soon after the first laughs; the chain starts over
  /// once the laugh does.
  static const doubleTapWithin = Duration(milliseconds: 1100);

  /// Code snacks take off between these heights over the perch, this far
  /// clear of the body.
  static const snackLow = 12.0;
  static const snackHigh = 40.0;
  static const snackClear = 8.0;

  /// Running to the reasoning being written (docs/design/naiwa-pet.md §7),
  /// logical px per second, at least [runMin] at a time.
  static const runSpeed = 72.0;
  static const runMin = 24.0;

  /// While it eats a reasoning, it runs again after this long.
  static const rerunMin = Duration(seconds: 6);
  static const rerunMax = Duration(seconds: 9);

  /// Back home this long after it went idle away from it.
  static const homeAfter = Duration(milliseconds: 1200);

  /// A reasoning's glyphs take off within this much of the bottom of what
  /// shows of it, this far either side of the mouth.
  static const foodBand = 36.0;
  static const foodSpread = 48.0;

  /// Mouth reach in logical pixels, independent of the pet's art scale.
  static const eraseRadius = 12.0;
  static const eatRadius = 20.0;
}

/// The pet over the chat page. Wrap the page body; capsules inside report
/// with [PetPerch], panels that should send it away with [PetCover], areas
/// it keeps out of with [PetAvoid], the reasoning being written with
/// [PetFood].
class PetStage extends ConsumerStatefulWidget {
  const PetStage({super.key, this.sessionId, this.aside = false, required this.child});

  /// The conversation the page shows (null: a new chat). The pet reads what
  /// it is doing from here.
  final String? sessionId;

  /// A phone on its side is typing: the bars fold away, the pet stays on
  /// the composer.
  final bool aside;
  final Widget child;

  @override
  ConsumerState<PetStage> createState() => _PetStageState();
}

class _PetStageState extends ConsumerState<PetStage> {
  final _registry = PerchRegistry();
  final _content = GlobalKey();
  final _scrolling = ValueNotifier<bool>(false);

  @override
  void dispose() {
    _registry.dispose();
    _scrolling.dispose();
    super.dispose();
  }

  /// Go and look: the conversation on screen scrolls to what waits (or its
  /// newest reply); another conversation opens.
  Future<void> _reveal(PetTarget target, PetBubbleKind kind) async {
    final here = ref.read(activeHostProvider) == target.host && ref.read(currentSessionProvider) == target.sessionId;
    if (here) {
      _scrollTo(kind);
      return;
    }
    if (!await DiscardGuard.confirmLeave(context) || !mounted) return;
    ref.read(activeHostProvider.notifier).select(target.host);
    ref.read(currentSessionProvider.notifier).select(target.sessionId);
  }

  /// Brings the waiting card (or the latest reply) into view.
  void _scrollTo(PetBubbleKind kind) {
    final root = _content.currentContext;
    if (root == null) return;
    final duration = AppMotion.of(context, AppMotion.emphasized);
    BuildContext? card;
    if (kind.waits) {
      void visit(Element e) {
        if (card != null) return;
        final w = e.widget;
        if (w is ApprovalCard || w is QuestionCard) {
          card = e;
          return;
        }
        e.visitChildElements(visit);
      }

      root.visitChildElements(visit);
    }
    if (card case final card?) {
      unawaited(Scrollable.ensureVisible(card, alignment: 1, duration: duration, curve: AppMotion.std));
      return;
    }
    // The newest content: the bottom of the conversation's list.
    ScrollableState? list;
    var tallest = 0.0;
    void find(Element e) {
      if (e is StatefulElement && e.state is ScrollableState) {
        final s = e.state as ScrollableState;
        final box = e.renderObject;
        if (s.widget.axis == Axis.vertical && box is RenderBox && box.hasSize && box.size.height > tallest) {
          tallest = box.size.height;
          list = s;
        }
      }
      e.visitChildElements(find);
    }

    root.visitChildElements(find);
    final position = list?.position;
    if (position == null || !position.hasContentDimensions) return;
    if (duration == Duration.zero) {
      position.jumpTo(position.maxScrollExtent);
    } else {
      unawaited(position.animateTo(position.maxScrollExtent, duration: duration, curve: AppMotion.std));
    }
  }

  @override
  Widget build(BuildContext context) {
    // The overlay outside the app hears every state while the chat lives.
    ref.listen<void>(petOverlayBridgeProvider, (_, _) {});
    return PetPerchScope(
      registry: _registry,
      child: Listener(
        behavior: HitTestBehavior.translucent,
        onPointerDown: (_) => ref.read(petInteractionProvider.notifier).touch(),
        child: NotificationListener<ScrollNotification>(
          onNotification: (n) {
            if (n is ScrollStartNotification) _scrolling.value = true;
            if (n is ScrollEndNotification) _scrolling.value = false;
            return false;
          },
          child: Stack(
            fit: StackFit.expand,
            children: [
              _FocusReporter(
                sessionId: widget.sessionId,
                child: KeyedSubtree(key: _content, child: widget.child),
              ),
              Positioned.fill(
                child: PetLayer(registry: _registry, aside: widget.aside, scrolling: _scrolling, onReveal: _reveal),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// What the page's conversation is doing, for [_FocusReporter] (null: a new chat).
final _pageFocusProvider = Provider.autoDispose.family<PetFocus?, String?>((ref, id) {
  if (id == null) return null;
  final host = ref.watch(activeHostProvider);
  final compacting = ref.watch(petCompactingProvider(id));
  return ref.watch(chatProvider(id).select((s) => petFocusOf(host, id, s, compacting: compacting)));
});

/// Tells the pet what the conversation on screen is doing (its activity,
/// compaction, an open card), from the page's own chat state.
///
/// Through a subscription, not this widget's builds: with the app in the
/// background there are no frames, and the pet out there still has to see the
/// turn end. A frozen 「running」 would keep it working and swallow the turn's
/// 做完了 (a new round, as far as it could tell), while the notification stays
/// silent for the pet to say it (`ResultSilence`).
class _FocusReporter extends ConsumerStatefulWidget {
  const _FocusReporter({required this.sessionId, required this.child});

  final String? sessionId;
  final Widget child;

  @override
  ConsumerState<_FocusReporter> createState() => _FocusReporterState();
}

class _FocusReporterState extends ConsumerState<_FocusReporter> {
  late final PetFocusController _focus;
  ProviderSubscription<PetFocus?>? _sub;

  @override
  void initState() {
    super.initState();
    _focus = ref.read(petFocusProvider.notifier);
    _follow();
  }

  @override
  void didUpdateWidget(_FocusReporter old) {
    super.didUpdateWidget(old);
    if (old.sessionId != widget.sessionId) _follow();
  }

  void _follow() {
    _sub?.close();
    _sub = ref.listenManual(_pageFocusProvider(widget.sessionId), (_, next) => _report(next), fireImmediately: true);
  }

  void _report(PetFocus? focus) {
    // Not while building (the first report comes from initState): right after.
    scheduleMicrotask(() {
      if (mounted) _focus.report(focus);
    });
  }

  @override
  void dispose() {
    _sub?.close();
    final focus = _focus;
    // The page is gone: nothing on screen.
    scheduleMicrotask(() => focus.report(null));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// The pet itself, over the whole stage. Hit tests only on its body and its
/// bubble.
class PetLayer extends ConsumerStatefulWidget {
  const PetLayer({super.key, required this.registry, this.aside = false, this.scrolling, this.onReveal});

  final PerchRegistry registry;
  final bool aside;

  /// The page's list is scrolling (no walks then).
  final ValueListenable<bool>? scrolling;

  /// Go and look at [target] (a tapped bubble, a tap while it rings).
  final void Function(PetTarget target, PetBubbleKind kind)? onReveal;

  /// Dice for walks, idle rotation and celebrations (tests seed it).
  static math.Random random = math.Random();

  @override
  ConsumerState<PetLayer> createState() => PetLayerState();
}

class PetLayerState extends ConsumerState<PetLayer> with TickerProviderStateMixin, WidgetsBindingObserver {
  // ── Where it stands ──
  PerchSpot? _spot;
  Size _stage = Size.zero;
  Offset _stageGlobal = Offset.zero;
  List<Rect> _avoid = const [];
  bool _covered = false;

  /// Its foot point at the last check, in stage coordinates (a hop starts there).
  Offset? _lastFoot;
  bool _polling = false;

  late final AnimationController _hop = AnimationController(vsync: this, value: 1, duration: PetMetrics.hop)
    ..addListener(_tick);
  Offset _hopFrom = Offset.zero;

  // ── Walking ──
  late final AnimationController _walk = AnimationController(vsync: this)
    ..addListener(_tick)
    ..addStatusListener(_walked);
  double _walkFrom = 0;
  double _walkTo = 0;
  double? _roamed;
  bool _walking = false;
  bool _walkRight = false;

  // ── Eating the reasoning being written ──
  /// What shows of it, in stage coordinates.
  Rect? _food;
  PetFoodState? _meal;
  final _snacks = GlobalKey<PetSnackLayerState>();

  /// The state's animation eats, and what it eats is that reasoning.
  bool _feeding = false;
  bool _chasing = false;

  /// The next run may start: at once when chasing starts, then on [_chaseTimer].
  bool _runDue = false;

  /// The walk under way is a run to the reasoning.
  bool _running = false;

  /// Runs took it away from home: idle, it walks back.
  bool _fed = false;
  Timer? _chaseTimer;
  Timer? _homeTimer;

  // ── Held ──
  bool _dragging = false;

  /// Dragged left far enough: the art (and its mouth) mirrors. Cleared only
  /// after [PetMetrics.dragMirrorSlop] the other way, so a jittering finger
  /// does not flip it back and forth.
  bool _dragLeft = false;

  /// Where the drag started, in stage coordinates: the mirroring turns on and
  /// off [PetMetrics.dragMirrorSlop] either side of it.
  double? _dragFrom;
  Offset? _freeFoot;
  double _dragFoot = 0;
  double _lift = 0;
  late final AnimationController _drop = AnimationController(vsync: this, value: 1)..addListener(_tick);
  double _dropFrom = 0;

  // ── One-offs ──
  PetAnimation? _reaction;
  bool _laughing = false;

  /// The current one-off has a recording playing (any reaction, not only the
  /// laugh): interrupting it stops the native clip.
  bool _audible = false;
  late final PetSoundPlayer _soundPlayer;
  Timer? _reactionTimer;
  PetAnimation? _variant;
  Timer? _idleTimer;
  Timer? _roamTimer;
  Timer? _unhideTimer;
  final List<DateTime> _taps = [];
  bool _ready = false;
  bool _bodyFullyHidden = true;
  PetStateName? _lastState;
  PetPack? _statePack;
  PetPack? _pinned;

  // ── Sounds ──
  /// The animation whose cue came last (a running one does not repeat it).
  String? _cued;
  PetSoundSet? _prepared;

  /// Where the foot stands now, in stage coordinates (tests).
  @visibleForTesting
  Offset? get foot => _freeFoot ?? (_spot == null ? null : _spot!.rect.topLeft + Offset(_footX(_spot!), 0));

  /// The perch it stands on (tests).
  @visibleForTesting
  PerchKind? get perch => _spot?.kind;

  @visibleForTesting
  bool get hopping => _hop.isAnimating;

  @visibleForTesting
  bool get walking => _walking;

  /// It eats the reasoning being written, running to it now and then (tests).
  @visibleForTesting
  bool get chasing => _chasing;

  /// The animation playing now (tests).
  @visibleForTesting
  PetAnimation? get playing => _anim;
  PetAnimation? _anim;

  /// Why the last one-off did not start (tests): a sound it needed would
  /// have been dropped, or the pet could not be heard. Null when it played.
  @visibleForTesting
  String? get reactionBlocked => _blocked;
  String? _blocked;

  /// The art is mirrored while held (tests).
  @visibleForTesting
  bool get dragMirrored => _mirror;
  bool get _mirror =>
      (_dragging && _pack?.dragMirror == true && _dragLeft) || (_walking && (_pack?.mirrorWalking(right: _walkRight) ?? false));

  /// In the tree (not parked by a moving global key or a closing route).
  bool _active = true;

  @override
  void initState() {
    super.initState();
    _soundPlayer = ref.read(petSoundPlayerProvider);
    WidgetsBinding.instance.addObserver(this);
    widget.registry.addListener(_schedulePoll);
  }

  @override
  void deactivate() {
    _active = false;
    if (_reaction != null) _clearReaction();
    super.deactivate();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed && _reaction != null) setState(_clearReaction);
  }

  @override
  void activate() {
    super.activate();
    _active = true;
    _schedulePoll();
  }

  @override
  void didUpdateWidget(PetLayer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.registry != widget.registry) {
      oldWidget.registry.removeListener(_schedulePoll);
      widget.registry.addListener(_schedulePoll);
    }
    if (oldWidget.aside != widget.aside) _schedulePoll();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _clearReaction();
    widget.registry.removeListener(_schedulePoll);
    widget.registry.occupied.value = null;
    _reactionTimer?.cancel();
    _idleTimer?.cancel();
    _roamTimer?.cancel();
    _unhideTimer?.cancel();
    _chaseTimer?.cancel();
    _homeTimer?.cancel();
    _hop.dispose();
    _walk.dispose();
    _drop.dispose();
    super.dispose();
  }

  void _tick() => setState(() {});

  DateTime get _now => ref.read(petClockProvider)();

  // ── Geometry ───────────────────────────────────────────────────────────────

  void _schedulePoll() {
    if (_polling || !mounted) return;
    _polling = true;
    SchedulerBinding.instance.addPostFrameCallback(_poll);
    SchedulerBinding.instance.ensureVisualUpdate();
  }

  /// After every frame that happens: which perch is topmost, how wide it
  /// is, what to keep out of. Changes rebuild; the vertical position needs
  /// none (the layer link carries it, without a frame of lag).
  void _poll(Duration _) {
    _polling = false;
    if (!mounted || !_active) return;
    if (_reaction != null && (!_visible || _typing || !ref.read(chatOnScreenProvider))) setState(_clearReaction);
    final stage = context.findRenderObject();
    if (stage is! RenderBox || !stage.hasSize || !stage.attached) return;
    var spots = widget.registry.spots(stage);
    if (widget.aside) {
      spots = [
        for (final s in spots)
          if (s.kind == PerchKind.composer) s,
      ];
    }
    PerchSpot? top;
    for (final s in spots) {
      if (top == null || s.rect.top < top.rect.top - 0.5) top = s;
    }
    final avoid = [for (final r in widget.registry.avoids(stage)) r.inflate(PetMetrics.avoidGap)];
    final covered = widget.registry.covered;
    // Only a pet that eats follows the reasoning: it moves with every delta.
    final food = _pack?.snack == null ? null : _foodOver(top, widget.registry.foods(stage), stage.size);
    final point = _freeFoot;
    final pack = _pack;
    final mouth = pack?.snack?.mouthOf('prone-eat');
    final meal = point != null && pack != null && mouth != null
        ? widget.registry.mealAt(stage, point + (mouth - Offset(pack.anchorX, pack.baseline)) * _scale)
        : null;
    final global = stage.localToGlobal(Offset.zero);
    final old = _spot;
    final moved = top?.perch != old?.perch;
    final changed =
        moved ||
        (top != null &&
            old != null &&
            ((top.rect.width - old.rect.width).abs() > 0.25 || (top.rect.left - old.rect.left).abs() > 0.25)) ||
        stage.size != _stage ||
        (global - _stageGlobal).distance > 0.01 ||
        covered != _covered ||
        meal != _meal ||
        (point != null && top?.rect.top != old?.rect.top) ||
        !_sameRects(avoid, _avoid) ||
        !_sameRects([?food], [?_food]);
    if (moved && top != null && old != null && _lastFoot != null && _freeFoot == null) {
      // Hop from where it stood to the new perch.
      _spot = top;
      _hopFrom = _lastFoot! - (top.rect.topLeft + Offset(_footX(top), 0));
      if (AppMotion.reduced(context) || _hopFrom.distance < 1 || !_visible) {
        _hop.value = 1;
      } else {
        _hop.duration = PetMetrics.hop;
        unawaited(_hop.forward(from: 0));
      }
    }
    if (changed) {
      setState(() {
        _spot = top;
        _stage = stage.size;
        _stageGlobal = global;
        _avoid = avoid;
        _covered = covered;
        _food = food;
        _meal = meal;
        if (_freeFoot case final point?) _freeFoot = _clampFree(point);
      });
    }
    final spot = _spot;
    _lastFoot = foot;
    final shown = _visible && _ready;
    // Perches lead their links once there is a pet to draw (and keep leading
    // while it fades out when covered or hidden).
    final leading = _ready && _pack != null;
    if (widget.registry.leading.value != leading) widget.registry.leading.value = leading;
    final occupied = shown && _freeFoot == null ? spot?.kind : null;
    if (widget.registry.occupied.value != occupied) widget.registry.occupied.value = occupied;
    ref.read(petLayerShownProvider.notifier).set(shown);
    final shownPack = _pack;
    ref
        .read(petHeadroomProvider.notifier)
        .set(
          shown && shownPack != null && _freeFoot == null
              ? (shownPack.baseline - shownPack.contentBox.top) * _scale
              : 0,
        );
    _syncChase();
    // Keep watching while frames come (keyboard, strips rising).
    _polling = true;
    SchedulerBinding.instance.addPostFrameCallback(_poll);
  }

  static bool _sameRects(List<Rect> a, List<Rect> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if ((a[i].topLeft - b[i].topLeft).distance > 0.25 || a[i].size != b[i].size) return false;
    }
    return true;
  }

  /// What shows of the newest of [foods] (the lowest) within the stage,
  /// above [spot]; null when nothing does.
  static Rect? _foodOver(PerchSpot? spot, List<Rect> foods, Size stage) {
    if (spot == null) return null;
    Rect? newest;
    for (final f in foods) {
      final shows = Rect.fromLTRB(
        math.max(f.left, 0.0),
        math.max(f.top, 0.0),
        math.min(f.right, stage.width),
        math.min(f.bottom, spot.rect.top),
      );
      if (shows.width < 1 || shows.height < 1) continue;
      if (newest == null || shows.bottom > newest.bottom) newest = shows;
    }
    return newest;
  }

  PetPack? get _pack => ref.read(currentPetPackProvider);

  double get _dpr => MediaQuery.devicePixelRatioOf(context);

  double get _scale {
    final pack = _pack;
    if (pack == null) return 1;
    return petScale(pack, ref.read(petPrefsProvider).size, _dpr);
  }

  /// Body extents left and right of the foot point, logical px.
  (double, double) _extents(PetPack pack, double s) =>
      ((pack.anchorX - pack.contentBox.left) * s, (pack.contentBox.right - pack.anchorX) * s);

  /// The range the foot may take along [spot] (its own coordinates).
  (double, double) _range(PerchSpot spot) {
    final pack = _pack;
    final w = spot.rect.width;
    if (pack == null) return (w / 2, w / 2);
    final (left, right) = _extents(pack, _scale);
    final lo = PetMetrics.inset + left;
    final hi = w - PetMetrics.inset - right;
    if (hi <= lo) return (w / 2, w / 2);
    return (lo, hi);
  }

  /// Steps [x] out of the areas it keeps out of, to the nearer side.
  double _clear(PerchSpot spot, double x) {
    final pack = _pack;
    final (lo, hi) = _range(spot);
    if (pack == null) return x.clamp(lo, hi);
    final s = _scale;
    final (left, right) = _extents(pack, s);
    final height = (pack.baseline - pack.contentBox.top) * s;
    for (final area in _avoid) {
      final r = area.shift(-spot.rect.topLeft);
      // Only what sits beside the body: above the perch, within its height.
      if (r.bottom < -height || r.top > 0) continue;
      if (x + right <= r.left || x - left >= r.right) continue;
      final before = r.left - right;
      final after = r.right + left;
      final fitsBefore = before >= lo;
      final fitsAfter = after <= hi;
      if (fitsBefore && (!fitsAfter || x - before <= after - x)) {
        x = before;
      } else if (fitsAfter) {
        x = after;
      }
    }
    return x.clamp(lo, hi);
  }

  /// Where the foot stands along [spot].
  double _footX(PerchSpot spot) {
    final (lo, hi) = _range(spot);
    if (_dragging) return _dragFoot.clamp(lo, hi);
    final prefs = ref.read(petPrefsProvider);
    final share = _walking ? _walkFrom + (_walkTo - _walkFrom) * _walk.value : (_roamed ?? prefs.position);
    return _clear(spot, (share * spot.rect.width).clamp(lo, hi));
  }

  bool get _visible {
    final prefs = ref.read(petPrefsProvider);
    return _pack != null &&
        prefs.loaded &&
        prefs.enabled &&
        !prefs.hiddenAt(_now) &&
        !ref.read(uiModeProvider).web &&
        _spot != null &&
        !_covered;
  }

  PetScope get _scope => _spot?.kind == PerchKind.strip ? PetScope.focus : PetScope.global;

  // ── Play ───────────────────────────────────────────────────────────────────

  void _onState(PetStateName next) {
    if (!mounted || !_active) return;
    final pack = _pack;
    if (pack == null) return;
    if (next != PetStateName.idle) {
      _idleTimer?.cancel();
      _roamTimer?.cancel();
      _homeTimer?.cancel();
      // A run to the reply goes on: the chase decides when it stops.
      if (_walking && !_running) {
        _roamed = _walkFrom + (_walkTo - _walkFrom) * _walk.value;
        _walk.stop();
        _walking = false;
      }
      _variant = null;
    }
    // A celebration now and then plays one of its extras.
    if (next == PetStateName.attention) {
      final bonus = pack.bonusOf(PetStateName.attention);
      if (bonus != null && PetLayer.random.nextDouble() < bonus.chance) {
        _variant = pack.animations[bonus.anims[PetLayer.random.nextInt(bonus.anims.length)]];
      }
      final celebration = _variant ?? pack.animFor(next);
      if (!_laughing && _isLaugh(celebration)) _play(celebration);
    }
    // Touching a sleeper only wakes it.
    if (next == PetStateName.sleeping || next == PetStateName.waking) _clearReaction();
    if (next == PetStateName.idle) _armIdle();
    setState(() {});
  }

  bool get _reduced => AppMotion.reduced(context);

  /// Idle: now and then an idle extra, now and then a walk; home first if
  /// runs took it away.
  void _armIdle() {
    _idleTimer?.cancel();
    _roamTimer?.cancel();
    if (_fed) _armHome();
    final pack = _pack;
    if (_reduced || pack == null) return;
    _idleTimer = Timer(pack.idleEvery.draw(PetLayer.random.nextDouble()), _idleTick);
    _armRoam();
  }

  void _armRoam() {
    _roamTimer?.cancel();
    if (_freeFoot != null) return;
    _roamTimer = Timer(PetMetrics.roamEvery.draw(PetLayer.random.nextDouble()), _roam);
  }

  /// Plays one idle extra (weighted pick, for its ms), then back to idle.
  void _idleTick() {
    if (!mounted || !_active) return;
    final pack = _pack;
    if (pack == null || _lastState != PetStateName.idle) return;
    final pool = pack.idles;
    if (pool.isEmpty) return;
    if (_walking || _reaction != null || _dragging || !_visible) {
      _idleTimer = Timer(pack.idleEvery.draw(PetLayer.random.nextDouble()), _idleTick);
      return;
    }
    final total = pool.fold<double>(0, (sum, e) => sum + e.weight);
    var pick = PetLayer.random.nextDouble() * total;
    var chosen = pool.last;
    for (final entry in pool) {
      pick -= entry.weight;
      if (pick <= 0) {
        chosen = entry;
        break;
      }
    }
    final anim = pack.animations[chosen.anim];
    if (_isLaugh(anim)) {
      _play(anim);
      return;
    }
    setState(() => _variant = anim);
    final ms = chosen.ms > 0 ? chosen.ms : (anim?.durationMs ?? 4800);
    _idleTimer = Timer(Duration(milliseconds: ms), () {
      if (!mounted) return;
      setState(() => _variant = null);
      _idleTimer = Timer(pack.idleEvery.draw(PetLayer.random.nextDouble()), _idleTick);
    });
  }

  bool get _typing {
    final focus = FocusManager.instance.primaryFocus;
    final ctx = focus?.context;
    if (ctx == null) return false;
    return ctx.widget is EditableText || ctx.findAncestorWidgetOfExactType<EditableText>() != null;
  }

  /// Walks a little way along the perch (and back home the next time).
  void _roam() {
    if (!mounted || !_active) return;
    if (_freeFoot != null) return;
    final spot = _spot;
    final pack = _pack;
    if (spot == null || pack == null || _lastState != PetStateName.idle) return;
    final bubbleUp = ref.read(petScopedStateProvider(_scope)).bubble != null;
    if (_dragging || _reaction != null || _typing || (widget.scrolling?.value ?? false) || bubbleUp || !_visible) {
      _armRoam();
      return;
    }
    final home = ref.read(petPrefsProvider).position;
    final from = _roamed ?? home;
    final r = PetLayer.random;
    final to = _roamed != null
        ? home
        : (from +
                  (r.nextBool() ? 1 : -1) *
                      (PetMetrics.walkMin + r.nextDouble() * (PetMetrics.walkMax - PetMetrics.walkMin)))
              .clamp(0.0, 1.0);
    // Not into an area it keeps out of, not past the perch's ends.
    final (lo, hi) = _range(spot);
    final endX = _clear(spot, (to * spot.rect.width).clamp(lo, hi));
    final startX = _footX(spot);
    if ((endX - startX).abs() < 4) {
      _armRoam();
      return;
    }
    _go(spot, startX, endX, PetMetrics.walkSpeed);
  }

  /// Walks the foot from [startX] to [endX] along [spot] at [speed];
  /// [run]: to the reasoning being written.
  void _go(PerchSpot spot, double startX, double endX, double speed, {bool run = false}) {
    setState(() {
      _walkFrom = startX / spot.rect.width;
      _walkTo = endX / spot.rect.width;
      _walkRight = endX > startX;
      _walking = true;
      _running = run;
      _variant = null;
    });
    _walk.duration = Duration(milliseconds: ((endX - startX).abs() / speed * 1000).round());
    unawaited(_walk.forward(from: 0));
  }

  void _walked(AnimationStatus status) {
    if (status != AnimationStatus.completed || !_walking) return;
    final run = _running;
    final home = ref.read(petPrefsProvider).position;
    setState(() {
      _walking = false;
      _running = false;
      _roamed = (_walkTo - home).abs() < 0.002 ? null : _walkTo;
      _fed = (run || _fed) && _roamed != null;
    });
    if (run && _chasing) {
      _armChase();
    } else if (_lastState == PetStateName.idle) {
      _armRoam();
    }
  }

  // ── Eating the reasoning being written ─────────────────────────────────────

  /// After every frame: while the state's animation eats a reasoning and
  /// some of it shows, it runs along the perch to below it (at once, then
  /// every 6–9 s); otherwise it stops where it is.
  void _syncChase() {
    final spot = _spot;
    final food = _food;
    if (!_feeding || spot == null || food == null || _dragging || _freeFoot != null) {
      _endChase();
      return;
    }
    if (!_chasing) {
      _chasing = true;
      _runDue = true;
      _homeTimer?.cancel();
    }
    // No new run while it is busy, cannot be seen or the page moves; one
    // under way goes on.
    if (!_runDue || _walking || _reaction != null || _hop.isAnimating || _drop.isAnimating) return;
    if (_reduced || !_visible || !_ready || (widget.scrolling?.value ?? false)) return;
    _runDue = false;
    _run(spot, food);
  }

  /// Runs to somewhere under [food], at least [PetMetrics.runMin] from where
  /// it stands; already that close all over it, it eats where it is.
  void _run(PerchSpot spot, Rect food) {
    final (lo, hi) = _range(spot);
    final from = _footX(spot);
    final left = math.max(lo, food.left - spot.rect.left);
    final right = math.min(hi, food.right - spot.rect.left);
    final before = math.max(0.0, math.min(right, from - PetMetrics.runMin) - left);
    final after = math.max(0.0, right - math.max(left, from + PetMetrics.runMin));
    if (before + after <= 0) {
      _armChase();
      return;
    }
    final pick = PetLayer.random.nextDouble() * (before + after);
    final to = _clear(spot, pick < before ? left + pick : right - (pick - before));
    if ((to - from).abs() < 4) {
      _armChase();
      return;
    }
    _go(spot, from, to, PetMetrics.runSpeed, run: true);
  }

  void _armChase() {
    _chaseTimer?.cancel();
    final wait = PetMetrics.rerunMin + (PetMetrics.rerunMax - PetMetrics.rerunMin) * PetLayer.random.nextDouble();
    _chaseTimer = Timer(wait, () {
      if (!mounted || !_chasing) return;
      _runDue = true;
      if (_active) _syncChase();
    });
  }

  /// Stops chasing; a run under way stops where it is.
  void _endChase() {
    if (!_chasing) return;
    _chasing = false;
    _runDue = false;
    _chaseTimer?.cancel();
    if (_running) {
      _walk.stop();
      setState(() {
        _roamed = _walkFrom + (_walkTo - _walkFrom) * _walk.value;
        _walking = false;
        _running = false;
        _fed = true;
      });
    }
    if (_fed && _lastState == PetStateName.idle) _armHome();
  }

  void _armHome() {
    _homeTimer?.cancel();
    _homeTimer = Timer(PetMetrics.homeAfter, _goHome);
  }

  /// Idle away from home after runs: back at walking pace. Out of sight or
  /// with animations off it is simply there.
  void _goHome() {
    if (!mounted || !_fed || _lastState != PetStateName.idle || _walking) return;
    final spot = _spot;
    if (spot == null) return;
    if (!_active || _reaction != null || _hop.isAnimating || (widget.scrolling?.value ?? false)) {
      _armHome();
      return;
    }
    final (lo, hi) = _range(spot);
    final endX = _clear(spot, (ref.read(petPrefsProvider).position * spot.rect.width).clamp(lo, hi));
    final startX = _footX(spot);
    if (_reduced || !_visible || (endX - startX).abs() < 4) {
      setState(() {
        _roamed = null;
        _fed = false;
      });
      return;
    }
    _go(spot, startX, endX, PetMetrics.walkSpeed);
  }

  /// Naiwa's two-tap laugh and the long recording its laugh poses hold for
  /// come with its sound set, not its id: a copy brought in as a zip is
  /// `user-naiwa` and laughs the same.
  bool get _naiwa => _pack?.sounds == 'naiwa';

  /// The four laugh poses, the ones the long laugh recording scores: their
  /// pose holds for the recording.
  bool _isLaugh(PetAnimation? anim) => _naiwa && anim != null && anim.name.startsWith('laugh');

  /// Whether this pack's one-off [anim] is heard: it names a cue the set has
  /// a sound for, and the pet may sound now. Null when no sound goes with it
  /// (silent cues, a pack without sounds) — those animate regardless.
  bool? _heard(PetAnimation anim) {
    final sounds = _pack?.sounds;
    if (sounds == null) return null;
    final prefs = ref.read(petPrefsProvider);
    if (!prefs.sound || prefs.quiet) return false;
    if (!_visible || !_ready || !ref.read(chatOnScreenProvider)) return false;
    final set = ref.read(petSoundSetProvider(sounds)).value;
    if (set == null || set.cue(anim.name).isEmpty) return null;
    return _soundPlayer.wouldAllow(set, anim.name);
  }

  /// Plays a one-off only when its sound can go out with it: a reaction whose
  /// cue the rate limits would drop keeps the current pose, so a silent pose
  /// never plays (docs/design/naiwa-pet.md §6.2).
  void _play(PetAnimation? anim) {
    final pack = _pack;
    if (anim == null || pack == null) return;
    _blocked = null;
    // The same one-off is already showing (a state flash that re-armed): keep
    // it, and its recording, rather than asking the limits for a second play.
    if (_reaction == anim && _laughing == _isLaugh(anim)) return;
    final heard = _heard(anim);
    if (heard == false) {
      _blocked = _whySilent(anim) ?? 'sound';
      return;
    }
    _clearReaction();
    _laughing = _isLaugh(anim);
    if (_laughing) {
      // Whatever was tapped before, the laugh ends the chain: a tap during
      // or after it never pairs with an older one into another laugh.
      _taps.clear();
      _walk.stop();
      _walking = false;
      _running = false;
      _idleTimer?.cancel();
      _roamTimer?.cancel();
      _homeTimer?.cancel();
    }
    final duration = _hold(anim, pack);
    setState(() {
      _reaction = anim;
      _variant = null;
      _audible = heard == true;
    });
    // The pose and its recording start together, this frame: [_heard] already
    // asked the player, so this is the one play, not a second question.
    if (heard == true) {
      _cued = anim.name;
      final sounds = pack.sounds;
      final set = sounds == null ? null : ref.read(petSoundSetProvider(sounds)).value;
      if (set != null) unawaited(_soundPlayer.cue(set, anim.name));
    }
    _reactionTimer = Timer(duration, () {
      if (!mounted) return;
      setState(_clearReaction);
      if (_lastState == PetStateName.idle) _armIdle();
    });
  }

  /// Why [anim]'s sound cannot go out: the pet is muted, or the player's rate
  /// limits would drop it. Null when it is only not audible yet (hidden).
  String? _whySilent(PetAnimation anim) {
    final sounds = _pack?.sounds;
    if (sounds == null) return null;
    final prefs = ref.read(petPrefsProvider);
    if (!prefs.sound) return 'sound-off';
    if (prefs.quiet) return 'quiet';
    final set = ref.read(petSoundSetProvider(sounds)).value;
    if (set == null || set.cue(anim.name).isEmpty) return null;
    return _soundPlayer.wouldAllow(set, anim.name) ? null : 'limit';
  }

  /// How long [anim] stays: the laugh for its whole recording, any other
  /// reaction with a sound for that clip's length, else its own play time.
  Duration _hold(PetAnimation anim, PetPack pack) {
    if (_laughing) return naiwaLaughDuration;
    final sounds = pack.sounds;
    if (sounds == null) return Duration(milliseconds: pack.playOf(anim));
    final prefs = ref.read(petPrefsProvider);
    if (!prefs.sound || prefs.quiet) return Duration(milliseconds: pack.playOf(anim));
    final set = ref.read(petSoundSetProvider(sounds)).value;
    final clip = set?.cue(anim.name).firstOrNull;
    if (clip?.ms case final ms?) {
      return Duration(milliseconds: math.max(ms, pack.playOf(anim)));
    }
    return Duration(milliseconds: pack.playOf(anim));
  }

  void _clearReaction() {
    _reactionTimer?.cancel();
    if (_audible) unawaited(_soundPlayer.stop());
    _laughing = false;
    _audible = false;
    _reaction = null;
  }

  // ── Touch ──────────────────────────────────────────────────────────────────

  void _onTapUp(TapUpDetails details) {
    final pack = _pack;
    if (pack == null) return;
    ref.read(petInteractionProvider.notifier).touch();
    final pet = ref.read(petScopedStateProvider(_scope));
    // Asleep: the touch wakes it, no poke on top of the yawn.
    if (pet.state == PetStateName.sleeping || pet.state == PetStateName.waking) return;
    // Ringing: a tap goes to see what waits, like the bubble.
    if (pet.state == PetStateName.notification && pet.target != null) {
      HapticFeedback.selectionClick();
      final question = ref.read(petPendingProvider).where((p) => p.target == pet.target).firstOrNull?.question ?? false;
      widget.onReveal?.call(pet.target!, question ? PetBubbleKind.question : PetBubbleKind.approval);
      return;
    }
    // A tap during the recording ends it; the next tap starts a chain afresh.
    if (_laughing) {
      _taps.clear();
      setState(_clearReaction);
      return;
    }
    final now = _now;
    _taps
      ..removeWhere((t) => now.difference(t) > PetMetrics.doubleTapWithin)
      ..add(now);
    if (_taps.length >= 2 && _naiwa) {
      // The second of two quick taps laughs. The chain ends here (see
      // [_play]), so one more tap is a lone tap again, never a third step.
      HapticFeedback.lightImpact();
      _play(pack.animFor(PetStateName.attention));
      return;
    }
    HapticFeedback.selectionClick();
    final left = details.localPosition.dx < pack.anchorX * _scale;
    _play(pack.reaction(left ? 'tapLeft' : 'tapRight'));
  }

  Offset _clampFree(Offset point) {
    final pack = _pack!;
    final bounds = pack.contentBox.expandToInclude(_anim?.box ?? pack.contentBox);
    final left = (pack.anchorX - bounds.left) * _scale;
    final right = _stage.width - (bounds.right - pack.anchorX) * _scale;
    final top = (pack.baseline - bounds.top) * _scale;
    final bottom = _stage.height - (bounds.bottom - pack.baseline) * _scale;
    return Offset(point.dx.clamp(left, math.max(left, right)), point.dy.clamp(top, math.max(top, bottom)));
  }

  void _onDragStart(DragStartDetails details) {
    final spot = _spot;
    if (spot == null) return;
    HapticFeedback.selectionClick();
    ref.read(petInteractionProvider.notifier).touch();
    _roamTimer?.cancel();
    _idleTimer?.cancel();
    _homeTimer?.cancel();
    _chaseTimer?.cancel();
    _chasing = false;
    _runDue = false;
    _walk.stop();
    final startX = spot.rect.left + _footX(spot);
    setState(() {
      _dragFoot = _footX(spot);
      _dragFrom = startX;
      _dragLeft = false;
      if (_pack?.freeRoam == true) {
        _freeFoot = _clampFree(_freeFoot ?? spot.rect.topLeft + Offset(_dragFoot, 0));
        _hop.value = 1;
      }
      _dragging = true;
      _walking = false;
      _running = false;
      // Where it is dropped is its spot: no way back.
      _fed = false;
      _roamed = null;
      _variant = null;
      _clearReaction();
      _lift = -PetMetrics.dragLift;
      _drop.value = 1;
    });
    if (_freeFoot case final point?) _eraseBetween(point, point);
  }

  void _eraseBetween(Offset from, Offset to, {double radius = PetMetrics.eraseRadius}) {
    final pack = _pack;
    final mouth = pack?.snack?.mouthOf('prone-eat');
    final stage = context.findRenderObject();
    if (pack == null || mouth == null || stage is! RenderBox || !stage.attached || !stage.hasSize) return;
    final mouthOffset = (_mouth(pack, mouth) - Offset(pack.anchorX, pack.baseline)) * _scale;
    final erased = widget.registry.eraseAlong(stage, from + mouthOffset, to + mouthOffset, radius: radius);
    final origin = to - Offset(pack.anchorX, pack.baseline) * _scale;
    _snacks.currentState?.addErasedGlyphs([
      for (final glyph in erased.glyphs) (char: glyph.char, from: glyph.from - origin),
    ]);
  }

  /// A snack mouth in art pixels, the other way when the art is mirrored.
  Offset _mouth(PetPack pack, Offset mouth) => _mirror ? Offset(2 * pack.anchorX - mouth.dx, mouth.dy) : mouth;

  void _onDragUpdate(DragUpdateDetails details) {
    final spot = _spot;
    if (spot == null || !_dragging) return;
    final foot = _stageX;
    if (_freeFoot case final point?) {
      final next = _clampFree(point + details.delta);
      setState(() => _freeFoot = next);
      _turnDrag(foot, next.dx);
      _eraseBetween(point, next);
      return;
    }
    final (lo, hi) = _range(spot);
    setState(() {
      _dragFoot = (_dragFoot + details.delta.dx).clamp(lo, hi);
      // Held up a little; pulling up lifts it further, with some give.
      _lift = (_lift + details.delta.dy * 0.4).clamp(-PetMetrics.dragLift * 4, -PetMetrics.dragLift * 0.5);
    });
    _turnDrag(foot, _dragFoot);
  }

  /// The foot's x in the stage's coordinates.
  double get _stageX {
    final spot = _spot;
    return spot == null ? 0 : spot.rect.left + _footX(spot);
  }

  /// Turns the art to the way the foot has actually gone, once it is
  /// [PetMetrics.dragMirrorSlop] past where the drag began. It turns back only
  /// from the other side of that mark, so small back-and-forth movements keep
  /// one direction.
  void _turnDrag(double from, double to) {
    final pack = _pack;
    final start = _dragFrom;
    if (pack == null || !pack.dragMirror || start == null) return;
    final left = !_dragLeft && to < start - PetMetrics.dragMirrorSlop;
    final right = _dragLeft && to > start + PetMetrics.dragMirrorSlop;
    if (!left && !right) return;
    setState(() => _dragLeft = left);
  }

  void _onDragEnd([DragEndDetails? _]) {
    final spot = _spot;
    if (!_dragging || spot == null) return;
    if (_freeFoot case final point?) {
      _eraseBetween(point, point, radius: PetMetrics.eatRadius);
      if ((point.dy - spot.rect.top).abs() > 32 || point.dx < spot.rect.left || point.dx > spot.rect.right) {
        setState(() {
          _dragging = false;
          _dragLeft = false;
          _lift = 0;
        });
        _cue(PetCues.drop);
        if (_lastState == PetStateName.idle) _armIdle();
        return;
      }
      _dragFoot = point.dx - spot.rect.left;
      _freeFoot = null;
      _lift = 0;
    }
    // Let go: it settles on the perch, out of any area it keeps out of.
    final x = _clear(spot, _dragFoot);
    setState(() {
      _dragging = false;
      _dragLeft = false;
      _dropFrom = _lift;
      _lift = 0;
    });
    _cue(PetCues.drop);
    unawaited(ref.read(petPrefsProvider.notifier).setPosition(x / spot.rect.width));
    final drop = AppMotion.of(context, AppMotion.standard);
    if (drop == Duration.zero) {
      _drop.value = 1;
    } else {
      _drop.duration = drop;
      unawaited(_drop.forward(from: 0));
    }
    if (_lastState == PetStateName.idle) _armIdle();
    // Eating: it eats where it was put for a while before it runs again.
    if (_feeding && _food != null) {
      _chasing = true;
      _armChase();
    }
  }

  Future<void> _menu() async {
    final pack = _pack;
    if (pack == null) return;
    setState(() {
      _clearReaction();
      // The menu ends a tap chain: taps after it start over.
      _taps.clear();
    });
    ref.read(petInteractionProvider.notifier).touch();
    await showPetMenu(context, pack: pack);
  }

  /// Sounds [key] (an animation's name, or one of [PetCues]) if the pet may be
  /// heard: its pack has sounds, they are on, quiet mode is off, and it shows
  /// on the chat in front (docs/design/naiwa-pet.md §6.2). The player checks
  /// the app is in front and keeps the limits.
  void _cue(String key) {
    if (!mounted || !_active) return;
    if (key == 'laugh-belly' && _naiwa && !_laughing) return;
    final sounds = _pack?.sounds;
    final prefs = ref.read(petPrefsProvider);
    if (sounds == null || !prefs.sound || prefs.quiet) return;
    if (!_visible || !_ready || !ref.read(chatOnScreenProvider)) return;
    final set = ref.read(petSoundSetProvider(sounds)).value;
    if (set != null) unawaited(ref.read(petSoundPlayerProvider).cue(set, key));
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  /// [origin] moved so the canvas's top-left lands on a device pixel.
  Offset _snap(PerchSpot spot, Offset origin) {
    final dpr = _dpr;
    final global = _stageGlobal + spot.rect.topLeft + origin;
    final snapped = Offset((global.dx * dpr).roundToDouble() / dpr, (global.dy * dpr).roundToDouble() / dpr);
    return origin + (snapped - global);
  }

  /// Where code snacks take off, in canvas coordinates ([origin] is the
  /// canvas's offset from the perch): a band over the perch, on either side
  /// of the body.
  List<Rect> _snackLaunch(PerchSpot spot, PetPack pack, double s, Offset origin) {
    final top = -PetMetrics.snackHigh - origin.dy;
    final bottom = -PetMetrics.snackLow - origin.dy;
    final left = -origin.dx;
    final right = spot.rect.width - origin.dx;
    final bodyLeft = pack.contentBox.left * s - PetMetrics.snackClear;
    final bodyRight = pack.contentBox.right * s + PetMetrics.snackClear;
    return [
      if (bodyLeft > left) Rect.fromLTRB(left, top, bodyLeft, bottom),
      if (right > bodyRight) Rect.fromLTRB(bodyRight, top, right, bottom),
    ];
  }

  /// Where a reply's glyphs take off, in canvas coordinates: a band along
  /// the bottom of what shows of it ([food], stage coordinates), either side
  /// of the [mouth].
  List<Rect> _replyLaunch(PerchSpot spot, Rect food, Offset mouth, Offset origin) {
    final top = spot.rect.top + origin.dy;
    return [
      Rect.fromLTRB(
        mouth.dx - PetMetrics.foodSpread,
        math.max(food.top, food.bottom - PetMetrics.foodBand) - top,
        mouth.dx + PetMetrics.foodSpread,
        food.bottom - top,
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final pack = ref.watch(currentPetPackProvider);
    final prefs = ref.watch(petPrefsProvider);
    if (_reaction != null && (!identical(pack, _pinned) || !prefs.sound || prefs.quiet || !_visible)) _clearReaction();
    if (!identical(pack, _pinned) || !_visible) _freeFoot = null;
    final pet = ref.watch(petScopedStateProvider(_scope));
    ref.watch(uiModeProvider.select((m) => m.web));
    // A new state (or the pack just arrived): arm what goes with it.
    if (pet.state != _lastState || !identical(pack, _statePack)) {
      _lastState = pet.state;
      _statePack = pack;
      final next = pet.state;
      WidgetsBinding.instance.addPostFrameCallback((_) => _onState(next));
    }
    if (pack != null && !identical(pack, _pinned)) {
      _pinned = pack;
      PetSheets.instance.pin(pack, pack.animFor(PetStateName.idle));
      _ready = false;
    }
    // Its sounds load ahead of their first cue.
    final sounds = prefs.sound ? pack?.sounds : null;
    if (sounds != null) {
      final set = ref.watch(petSoundSetProvider(sounds)).value;
      if (set != null && !identical(set, _prepared)) {
        _prepared = set;
        unawaited(ref.read(petSoundPlayerProvider).prepare(set));
      }
    }
    _armUnhide(prefs);
    _schedulePoll();

    final spot = _spot;
    if (pack == null || spot == null) {
      _bodyFullyHidden = true;
      _feeding = false;
      return const SizedBox.expand();
    }
    final s = _scale;
    final visible = _visible;
    final canvas = Size(pack.canvas.width * s, pack.canvas.height * s);
    final footX = _footX(spot);

    // Hop: from the old foot point to the new along an arc.
    final t = _hop.value;
    final eased = Curves.easeInOut.transform(t);
    final hop = _hopFrom * (1 - eased) + Offset(0, t < 1 ? -PetMetrics.hopHeight * 4 * t * (1 - t) : 0);
    final lift = _dragging ? _lift : _dropFrom * (1 - Curves.easeIn.transform(_drop.value));
    var origin = Offset(footX - pack.anchorX * s, -pack.baseline * s) + hop + Offset(0, lift);
    if (_freeFoot case final point?) {
      _freeFoot = _clampFree(point);
      origin = _freeFoot! - spot.rect.topLeft - Offset(pack.anchorX * s, pack.baseline * s);
    }
    if (!_dragging && !_hop.isAnimating && !_walking && !_drop.isAnimating) origin = _snap(spot, origin);

    final snack = pack.snack;
    final snackText = ref.watch(petSnackTextProvider);
    final reply = snack != null && snackText.reply != null;
    // What the state itself plays, walks and one-offs aside. A pet that eats
    // chews on a reasoning as it streams.
    final own =
        (pet.state == PetStateName.idle || pet.state == PetStateName.attention ? _variant : null) ??
        (reply && pet.state == PetStateName.thinking
            ? pack.animFor(PetStateName.working, tier: 1)
            : pack.animFor(pet.state, tier: pet.tier));
    final meal = _freeFoot != null ? _meal : null;
    final eating = meal != null ? pack.animations['prone-eat'] : null;
    final anim =
        (_laughing ? _reaction : null) ??
        eating ??
        (_dragging
            ? (pack.reaction('drag') ?? pack.animFor(pet.state, tier: pet.tier))
            : _reaction ?? (_walking ? pack.roam : null) ?? own);
    _anim = anim;
    // Idle's extras may eat too, but only work sends it after a reasoning.
    _feeding = snack != null && reply && pet.state != PetStateName.idle && snack.everyOf(own.name) != null;
    // A one-off with a sound that the limits would drop never reached this
    // frame: [_play] kept the pose, and it sounds the one it did start. Every
    // other animation is sounded here, when it first shows.
    if (anim.name != _cued) {
      _cued = anim.name;
      // The laugh and the other one-offs sound from [_play], together with the
      // pose it starts; sounding them here first would spend the limit that
      // pose then needs.
      if (!_isLaugh(anim)) _cue(anim.name);
    }
    final flip = _mirror;

    // Only the body takes touches: the animation's hit box, never below the
    // foot line (the capsule under it keeps its taps).
    final box = pack.hitBoxFor(anim);
    final mirrored = flip
        ? Rect.fromLTRB(2 * pack.anchorX - box.right, box.top, 2 * pack.anchorX - box.left, box.bottom)
        : box;
    final hitRect = Rect.fromLTRB(
      mirrored.left * s,
      mirrored.top * s,
      mirrored.right * s,
      math.min(mirrored.bottom, pack.baseline) * s,
    );
    final shown = visible && _ready;
    final fadeDuration = AppMotion.of(context, AppMotion.standard);
    // Resume before the first visible fade-in frame; a reversed fade keeps running.
    if (shown) _bodyFullyHidden = false;
    final pauseSprite = !visible && (_bodyFullyHidden || fadeDuration == Duration.zero);

    final body = CompositedTransformFollower(
      link: spot.link,
      showWhenUnlinked: false,
      offset: origin,
      child: IgnorePointer(
        ignoring: !shown,
        child: AnimatedOpacity(
          opacity: shown ? 1 : 0,
          duration: fadeDuration,
          curve: AppMotion.std,
          onEnd: () {
            // A show request may have arrived since the fade began.
            if (shown) return;
            // Zero-duration completion may happen while widgets are updating.
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (!mounted || (_visible && _ready) || _bodyFullyHidden) return;
              setState(() => _bodyFullyHidden = true);
            });
          },
          child: MediaQuery(
            // A drag starts after 6dp (the default slop is far more).
            data: MediaQuery.of(context)
                .copyWith(gestureSettings: const DeviceGestureSettings(touchSlop: PetMetrics.dragSlop / 2)),
            child: GestureDetector(
              // The pet follows the finger from where it went down.
              dragStartBehavior: DragStartBehavior.down,
              onTapUp: _onTapUp,
              onLongPress: _menu,
              onPanStart: _onDragStart,
              onPanUpdate: _onDragUpdate,
              onPanEnd: _onDragEnd,
              onPanCancel: _onDragEnd,
              child: _HitRect(
                rect: hitRect,
                child: RepaintBoundary(
                  child: SizedBox.fromSize(
                    key: const ValueKey('pet-body'),
                    size: canvas,
                    child: PetSprite(
                      pack: pack,
                      anim: anim,
                      scale: s,
                      flip: flip,
                      paused: pauseSprite,
                      onShown: () {
                        if (_ready) return;
                        // Shown during a frame: ready right after it.
                        WidgetsBinding.instance.addPostFrameCallback((_) {
                          if (mounted && !_ready) setState(() => _ready = true);
                        });
                      },
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );

    final bubble = shown && !_dragging ? pet.bubble : null;
    const room = 160.0;
    // Over the head, and over what the state holds up (Deepy's 「!」, a
    // thought cloud): the higher of the body and the state's own art.
    final stateAnim = _variant ?? pack.animFor(pet.state, tier: pet.tier);
    final headArt = math.min(pack.contentBox.top, stateAnim.box.top) * s;
    final bubbleBox = Size(math.max(0, _stage.width - 2 * PetMetrics.bubbleMargin), room);
    final centre = spot.rect.left + origin.dx + pack.anchorX * s - PetMetrics.bubbleMargin;
    final speech = TweenAnimationBuilder<double>(
      tween: Tween(end: headArt),
      duration: AppMotion.of(context, AppMotion.standard),
      curve: AppMotion.std,
      builder: (context, head, child) => CompositedTransformFollower(
        link: spot.link,
        showWhenUnlinked: false,
        offset: Offset(PetMetrics.bubbleMargin - spot.rect.left, origin.dy + head - PetBubbleMetrics.lift - room),
        child: child,
      ),
      child: SizedBox.fromSize(
        size: bubbleBox,
        child: CustomSingleChildLayout(
          delegate: _BubbleLayout(centre),
          child: PetBubbleSwitcher(
            child: bubble == null
                ? null
                : _Swipe(
                    key: ValueKey(bubble.id),
                    onSwipeUp: () => ref.read(petMoodProvider(PetScope.global).notifier).dismissBubble(bubble.id),
                    child: PetBubbleView(
                      bubble: bubble,
                      onTap: () {
                        ref.read(petMoodProvider(PetScope.global).notifier).dismissBubble(bubble.id);
                        widget.onReveal?.call(bubble.target, bubble.kind);
                      },
                    ),
                  ),
          ),
        ),
      ),
    );

    final every = snack?.everyOf(anim.name);
    final mouth = snack == null ? Offset.zero : _mouth(pack, snack.mouthOf(anim.name));
    final food = _food;
    // One glyph at a time, slowly enough to follow: a reading pace, not the
    // animation's own snack.every (docs/design/naiwa-pet.md §7).
    final biteEvery = every == null ? null : math.max(every, PetSnackLayer.slowestEvery);

    return Stack(
      clipBehavior: Clip.none,
      children: [
        body,
        if (snack != null && shown)
          CompositedTransformFollower(
            link: spot.link,
            showWhenUnlinked: false,
            offset: origin,
            child: IgnorePointer(
              child: RepaintBoundary(
                // Its own consumer: a reply grows many times a second.
                child: Consumer(
                  builder: (context, ref, _) => PetSnackLayer(
                    key: _snacks,
                    anim: anim.name,
                    scale: s,
                    active: (!_dragging || pack.freeRoam) && biteEvery != null,
                    every: biteEvery ?? 0,
                    mouth: mouth * s,
                    launch: _dragging && pack.freeRoam
                        ? [Rect.fromLTWH(mouth.dx * s + 8, mouth.dy * s - 18, 28, 36)]
                        : reply && food != null
                        ? _replyLaunch(spot, food, mouth * s, origin)
                        : _snackLaunch(spot, pack, s, origin),
                    // No reasoning block on screen at all: there is nothing
                    // nearby to reach, so eat the jokes round and round.
                    text: reply && food == null ? SnackText(petSnackJokesText) : snackText,
                    // Nothing within reach at the mouth (the thinking has
                    // scrolled away or run out): the built-in ASCII jokes.
                    fallback: reply && food != null ? SnackText(petSnackJokesText) : const SnackText(''),
                    takeGlyph: meal == null
                        ? null
                        : () {
                            final stage = this.context.findRenderObject();
                            if (stage is! RenderBox || !stage.attached || !stage.hasSize) return null;
                            final canvasOrigin = spot.rect.topLeft + origin;
                            final point = canvasOrigin + mouth * s;
                            final erased = meal.eraseAlong(
                              stage,
                              point,
                              point,
                              radius: _dragging ? PetMetrics.eraseRadius : PetMetrics.eatRadius,
                              maxParticles: 1,
                            );
                            final glyph = erased.glyphs.firstOrNull;
                            return glyph == null ? null : (char: glyph.char, from: glyph.from - canvasOrigin);
                          },
                    onBite: () => _cue(PetCues.bite),
                  ),
                ),
              ),
            ),
          ),
        speech,
      ],
    );
  }

  void _armUnhide(PetPrefs prefs) {
    _unhideTimer?.cancel();
    final until = prefs.hiddenUntil;
    if (until == null) return;
    final wait = until.difference(_now);
    if (wait.isNegative) return;
    _unhideTimer = Timer(wait + const Duration(milliseconds: 10), () {
      if (mounted) setState(() {});
    });
  }
}

/// Places the bubble over the pet's head, kept inside the page.
class _BubbleLayout extends SingleChildLayoutDelegate {
  _BubbleLayout(this.centre);

  /// The pet's centre, in the box's coordinates.
  final double centre;

  @override
  BoxConstraints getConstraintsForChild(BoxConstraints constraints) => constraints.loosen();

  @override
  Offset getPositionForChild(Size size, Size child) {
    final x = (centre - child.width / 2).clamp(0.0, math.max(0.0, size.width - child.width));
    return Offset(x.roundToDouble(), size.height - child.height);
  }

  @override
  bool shouldRelayout(_BubbleLayout old) => old.centre != centre;
}

/// An upward flick sends the bubble away without opening anything.
class _Swipe extends StatelessWidget {
  const _Swipe({super.key, required this.onSwipeUp, required this.child});

  final VoidCallback onSwipeUp;
  final Widget child;

  @override
  Widget build(BuildContext context) => GestureDetector(
    onVerticalDragEnd: (d) {
      if ((d.primaryVelocity ?? 0) < -150) onSwipeUp();
    },
    child: child,
  );
}

/// Takes touches only inside [rect].
class _HitRect extends SingleChildRenderObjectWidget {
  const _HitRect({required this.rect, super.child});

  final Rect rect;

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderHitRect(rect);

  @override
  void updateRenderObject(BuildContext context, _RenderHitRect renderObject) => renderObject.rect = rect;
}

class _RenderHitRect extends RenderProxyBox {
  _RenderHitRect(this.rect);

  Rect rect;

  @override
  bool hitTest(BoxHitTestResult result, {required Offset position}) {
    if (!rect.contains(position)) return false;
    result.add(BoxHitTestEntry(this, position));
    return true;
  }
}
