// Where the pet can stand. The capsules above the composer (the composer
// itself, the run strip, the todo / goal bars, the banners, the plugins' status
// line and capsule row) wrap themselves in [PetPerch]; the chat page's pet
// layer stands on the top edge of the topmost one it can see. Each perch is a
// layer link leader, so the pet follows its capsule in the same frame
// (keyboard, a growing composer, the strip rising) without a frame of lag. The
// reasoning being written wraps itself in [PetFood]: a pet that eats runs along
// its perch to below it.
//
// Outside a [PetPerchScope] (Bot chats, settings previews) the wrappers are
// plain pass-throughs.

import 'dart:math' as math;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

import '../chat/secret_mask.dart';

/// What a perch is.
enum PerchKind {
  /// The composer (or the read-only bar in its place): the fallback.
  composer,

  /// The run strip (思考条).
  strip,

  /// The todo and goal bars.
  dock,

  /// The banners and the auto-approve pill above them.
  banner,

  /// The plugins' status line and the capsule row (ui.json's and plugins'):
  /// the foot on the row's top edge, the capsules themselves stay free.
  plugin,
}

/// Where a perch is, in the stage's coordinates.
@immutable
class PerchSpot {
  const PerchSpot(this.perch, this.rect);

  final PetPerchState perch;
  final Rect rect;

  PerchKind get kind => perch.widget.kind;
  LayerLink get link => perch.link;
}

/// The perches, avoid areas, covers and food under one stage.
class PerchRegistry extends ChangeNotifier {
  final List<PetPerchState> _perches = [];
  final List<PetAvoidState> _avoids = [];
  final List<PetCoverState> _covers = [];
  final List<PetFoodState> _foods = [];

  /// The kind of perch the pet stands on now (null: none, or no pet). The
  /// run strip hides its whale tail while the pet stands on it.
  final occupied = ValueNotifier<PerchKind?>(null);

  /// A pet is drawn: perches lead their layer links. Without one they add
  /// no layer at all, so pages without a pet composite unchanged.
  final leading = ValueNotifier<bool>(false);

  void _add(PetPerchState p) {
    _perches.add(p);
    notifyListeners();
  }

  void _remove(PetPerchState p) {
    _perches.remove(p);
    notifyListeners();
  }

  void _changed() => notifyListeners();

  /// The live perches with a box on screen, in [stage]'s coordinates.
  List<PerchSpot> spots(RenderBox stage) => [
    for (final p in _perches)
      if (p.widget.active)
        if (p.rectIn(stage) case final rect? when rect.height >= 1 && rect.width >= 1) PerchSpot(p, rect),
  ];

  /// Areas the pet steps aside from (the jump-to-bottom key).
  List<Rect> avoids(RenderBox stage) => [
    for (final a in _avoids)
      if (a.widget.active) ?a.rectIn(stage),
  ];

  /// Something the pet hides for (the slash palette) is up.
  bool get covered => _covers.any((c) => c.widget.active);

  /// What the pet runs to and eats (the reasoning being written), boxes whole:
  /// the stage finds what of them shows.
  List<Rect> foods(RenderBox stage) => [
    for (final f in _foods)
      if (f.widget.active) ?f.rectIn(stage),
  ];

  PetFoodState? mealAt(RenderBox stage, Offset mouth) {
    PetFoodState? closest;
    var distance = double.infinity;
    for (final food in _foods) {
      if (!food.widget.edible) continue;
      final rect = food.visibleRectIn(stage);
      if (rect == null || !rect.inflate(32).contains(mouth)) continue;
      final next = (rect.center - mouth).distanceSquared;
      if (next < distance) {
        closest = food;
        distance = next;
      }
    }
    return closest;
  }

  /// Erases the whole swept area, even when a pointer jumps over several foods.
  PetErasure eraseAlong(RenderBox stage, Offset from, Offset to, {double radius = 32, int maxParticles = 3}) {
    var count = 0;
    final glyphs = <PetGlyph>[];
    final sweep = Rect.fromPoints(from, to).inflate(radius);
    for (final food in List.of(_foods)) {
      if (!food.widget.edible) continue;
      final visible = food.visibleRectIn(stage);
      if (visible == null || !sweep.overlaps(visible)) continue;
      final erased = food.eraseAlong(stage, from, to, radius: radius, maxParticles: maxParticles - glyphs.length);
      count += erased.count;
      glyphs.addAll(erased.glyphs);
    }
    return PetErasure(count, glyphs);
  }

  @override
  void dispose() {
    occupied.dispose();
    leading.dispose();
    super.dispose();
  }
}

/// Puts [registry] under a stage; [PetPerch]es below report to it.
class PetPerchScope extends InheritedWidget {
  const PetPerchScope({super.key, required this.registry, required super.child});

  final PerchRegistry registry;

  static PerchRegistry? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<PetPerchScope>()?.registry;

  @override
  bool updateShouldNotify(PetPerchScope old) => old.registry != registry;
}

Rect? _rectOf(BuildContext context, RenderBox stage) {
  final box = context.findRenderObject();
  if (box is! RenderBox || !box.attached || !box.hasSize || !stage.attached) return null;
  try {
    final topLeft = box.localToGlobal(Offset.zero, ancestor: stage);
    return topLeft & box.size;
  } catch (_) {
    // Not under the stage (moved by a global key): not a perch now.
    return null;
  }
}

/// A capsule the pet can stand on. [active] false while it is on its way out.
class PetPerch extends StatefulWidget {
  const PetPerch({super.key, required this.kind, this.active = true, required this.child});

  final PerchKind kind;
  final bool active;
  final Widget child;

  @override
  State<PetPerch> createState() => PetPerchState();
}

class PetPerchState extends State<PetPerch> {
  final link = LayerLink();
  PerchRegistry? _registry;

  Rect? rectIn(RenderBox stage) => _rectOf(context, stage);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final registry = PetPerchScope.maybeOf(context);
    if (registry == _registry) return;
    _registry?._remove(this);
    _registry = registry;
    registry?._add(this);
  }

  @override
  void didUpdateWidget(PetPerch oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active != widget.active || oldWidget.kind != widget.kind) _registry?._changed();
  }

  @override
  void dispose() {
    _registry?._remove(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final registry = _registry;
    if (registry == null) return widget.child;
    return ValueListenableBuilder<bool>(
      valueListenable: registry.leading,
      builder: (context, leading, child) => _PetLeader(link: link, active: leading, child: child),
      child: widget.child,
    );
  }
}

/// [CompositedTransformTarget] that leads only while [active]: off, it is a
/// plain pass-through (no layer), and the tree never changes shape.
class _PetLeader extends SingleChildRenderObjectWidget {
  const _PetLeader({required this.link, required this.active, super.child});

  final LayerLink link;
  final bool active;

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderPetLeader(link, active);

  @override
  void updateRenderObject(BuildContext context, _RenderPetLeader renderObject) => renderObject
    ..link = link
    ..active = active;
}

class _RenderPetLeader extends RenderProxyBox {
  _RenderPetLeader(this._link, this._active);

  LayerLink _link;
  set link(LayerLink value) {
    if (value == _link) return;
    _link = value;
    markNeedsPaint();
  }

  bool _active;
  set active(bool value) {
    if (value == _active) return;
    _active = value;
    markNeedsCompositingBitsUpdate();
    markNeedsPaint();
  }

  @override
  bool get alwaysNeedsCompositing => _active;

  @override
  void performLayout() {
    super.performLayout();
    _link.leaderSize = size;
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    if (!_active) {
      layer = null;
      super.paint(context, offset);
      return;
    }
    final leader = layer;
    if (leader is LeaderLayer) {
      leader
        ..link = _link
        ..offset = offset;
    } else {
      layer = LeaderLayer(link: _link, offset: offset);
    }
    context.pushLayer(layer!, super.paint, Offset.zero);
  }
}

/// An area the pet steps aside from while [active] (it stands beside it).
class PetAvoid extends StatefulWidget {
  const PetAvoid({super.key, this.active = true, required this.child});

  final bool active;
  final Widget child;

  @override
  State<PetAvoid> createState() => PetAvoidState();
}

class PetAvoidState extends State<PetAvoid> {
  PerchRegistry? _registry;

  Rect? rectIn(RenderBox stage) => _rectOf(context, stage);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final registry = PetPerchScope.maybeOf(context);
    if (registry == _registry) return;
    _registry?._avoids.remove(this);
    _registry = registry;
    registry?._avoids.add(this);
    registry?._changed();
  }

  @override
  void didUpdateWidget(PetAvoid oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active != widget.active) _registry?._changed();
  }

  @override
  void dispose() {
    _registry?._avoids.remove(this);
    _registry?._changed();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// What the pet runs to and eats while [active]: the reasoning being written.
class PetFood extends StatefulWidget {
  const PetFood({super.key, this.active = true, this.edible = false, this.onErase, required this.child});

  final bool active;
  final bool edible;

  /// Called after a frame that erased new, visible glyphs, once per frame.
  /// This only affects the current UI; callers must not change chat records.
  final VoidCallback? onErase;
  final Widget child;

  @override
  State<PetFood> createState() => PetFoodState();
}

class PetFoodState extends State<PetFood> {
  PerchRegistry? _registry;
  bool _eraseQueued = false;

  Rect? rectIn(RenderBox stage) => _rectOf(context, stage);

  Rect? visibleRectIn(RenderBox stage) {
    final box = context.findRenderObject();
    if (box is! RenderBox || !box.attached || !box.hasSize) return null;
    return _visibleRect(box, stage);
  }

  ({int char, Offset from})? takeGlyph(RenderBox stage, Offset mouth) {
    if (!mounted || !widget.edible) return null;
    final box = context.findRenderObject();
    final glyph = box is _RenderPetTextMask ? box.takeGlyph(stage, mouth) : null;
    if (glyph != null) _didErase();
    return glyph;
  }

  PetErasure eraseAlong(RenderBox stage, Offset from, Offset to, {double radius = 32, int maxParticles = 3}) {
    if (!mounted || !widget.edible) return const PetErasure(0, []);
    final box = context.findRenderObject();
    if (box is! _RenderPetTextMask) return const PetErasure(0, []);
    final erased = box.eraseAlong(stage, from, to, radius: radius, maxParticles: maxParticles);
    if (erased.count > 0) _didErase();
    return erased;
  }

  void _didErase() {
    if (_eraseQueued || widget.onErase == null) return;
    _eraseQueued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _eraseQueued = false;
      if (mounted) widget.onErase?.call();
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final registry = PetPerchScope.maybeOf(context);
    if (registry == _registry) return;
    _registry?._foods.remove(this);
    _registry = registry;
    registry?._foods.add(this);
    registry?._changed();
  }

  @override
  void didUpdateWidget(PetFood oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active != widget.active || oldWidget.edible != widget.edible) _registry?._changed();
  }

  @override
  void dispose() {
    _registry?._foods.remove(this);
    _registry?._changed();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.edible ? _PetTextMask(child: widget.child) : widget.child;
}

Rect? _visibleRect(RenderBox box, RenderBox stage) {
  var rect = MatrixUtils.transformRect(
    box.getTransformTo(stage),
    Offset.zero & box.size,
  ).intersect(Offset.zero & stage.size);
  RenderObject child = box;
  while (child.parent != null) {
    final parent = child.parent!;
    if (parent is RenderOffstage && parent.offstage) return null;
    final clip = parent.describeApproximatePaintClip(child);
    if (clip != null) rect = rect.intersect(MatrixUtils.transformRect(parent.getTransformTo(stage), clip));
    if (rect.isEmpty) return null;
    child = parent;
  }
  return rect.isEmpty ? null : rect;
}

class _PetTextMask extends SingleChildRenderObjectWidget {
  const _PetTextMask({required super.child});

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderPetTextMask();
}

typedef PetGlyph = ({int char, Offset from});

/// All glyphs disappear immediately; only a few become decorative particles.
class PetErasure {
  const PetErasure(this.count, this.glyphs);

  final int count;
  final List<PetGlyph> glyphs;
}

class _FoodGlyph {
  const _FoodGlyph(this.start, this.char, this.boxes);

  final int start;
  final int char;
  final List<Rect> boxes;
}

class _ParagraphFood {
  _ParagraphFood(this.span, this.text, this.layout, this.offsets);

  final InlineSpan span;
  final String text;
  final int layout;
  final Set<int> offsets;
  final glyphs = <_FoodGlyph>[];
  final holes = Path();

  void eat(_FoodGlyph glyph) {
    offsets.add(glyph.start);
    for (final rect in glyph.boxes) {
      holes.addRect(rect);
    }
  }
}

/// A square brush continuously interpolated along the pointer segment.
/// Slab intersection avoids both sampling gaps and work proportional to speed.
bool _sweeps(Rect rect, Offset from, Offset to, double radius) {
  final target = rect.inflate(radius);
  var enter = 0.0;
  var leave = 1.0;
  for (final (start, delta, low, high) in [
    (from.dx, to.dx - from.dx, target.left, target.right),
    (from.dy, to.dy - from.dy, target.top, target.bottom),
  ]) {
    if (delta.abs() < 0.000001) {
      if (start < low || start > high) return false;
    } else {
      final a = (low - start) / delta;
      final b = (high - start) / delta;
      enter = math.max(enter, math.min(a, b));
      leave = math.min(leave, math.max(a, b));
      if (enter > leave) return false;
    }
  }
  return true;
}

class _RenderPetTextMask extends RenderProxyBox {
  final _eaten = <RenderParagraph, _ParagraphFood>{};
  int _layout = 0;

  @override
  void performLayout() {
    super.performLayout();
    _layout++;
  }

  List<RenderParagraph> _paragraphs() {
    final result = <RenderParagraph>[];
    void visit(RenderObject object) {
      if (object is RenderOffstage && object.offstage) return;
      // Nested food owns its own mask and callback.
      if (object is _RenderPetTextMask) return;
      if (object is RenderParagraph && object.attached && object.hasSize) result.add(object);
      object.visitChildren(visit);
    }

    if (child case final child?) visit(child);
    _eaten.removeWhere((paragraph, _) => !result.contains(paragraph));
    return result;
  }

  _ParagraphFood _food(RenderParagraph paragraph) {
    final old = _eaten[paragraph];
    if (old != null && identical(old.span, paragraph.text) && old.layout == _layout) return old;
    final text = paragraph.text.toPlainText();
    final food = _ParagraphFood(
      paragraph.text,
      text,
      _layout,
      old != null && text.startsWith(old.text) ? old.offsets : <int>{},
    );
    final masked = maskSecrets(text);
    var start = 0;
    for (final glyph in text.characters) {
      final end = start + glyph.length;
      if (glyph.trim().isNotEmpty) {
        final code = masked.length == text.length ? masked.codeUnitAt(start) : 0x2022;
        final entry = _FoodGlyph(start, code >= 0xD800 && code <= 0xDFFF ? 0x2022 : code, [
          for (final box in paragraph.getBoxesForSelection(TextSelection(baseOffset: start, extentOffset: end)))
            box.toRect(),
        ]);
        food.glyphs.add(entry);
        if (food.offsets.contains(start)) food.eat(entry);
      }
      start = end;
    }
    return _eaten[paragraph] = food;
  }

  PetGlyph? takeGlyph(RenderBox stage, Offset mouth) {
    if (!attached || !hasSize || !stage.attached || !stage.hasSize) return null;
    ({_ParagraphFood food, _FoodGlyph glyph, Rect rect})? picked;
    var distance = double.infinity;
    for (final paragraph in _paragraphs()) {
      final visible = _visibleRect(paragraph, stage);
      if (visible == null) continue;
      final food = _food(paragraph);
      final transform = paragraph.getTransformTo(stage);
      for (final glyph in food.glyphs) {
        if (food.offsets.contains(glyph.start)) continue;
        for (final box in glyph.boxes) {
          final rect = MatrixUtils.transformRect(transform, box);
          if (!visible.contains(rect.center)) continue;
          final next = (rect.center - mouth).distanceSquared;
          if (next < distance) {
            distance = next;
            picked = (food: food, glyph: glyph, rect: rect);
          }
        }
      }
    }
    if (picked == null) return null;
    picked.food.eat(picked.glyph);
    markNeedsPaint();
    return (char: picked.glyph.char, from: picked.rect.center);
  }

  PetErasure eraseAlong(RenderBox stage, Offset from, Offset to, {required double radius, required int maxParticles}) {
    if (!attached || !hasSize || !stage.attached || !stage.hasSize) return const PetErasure(0, []);
    final sweep = Rect.fromPoints(from, to).inflate(radius);
    var count = 0;
    final particles = <PetGlyph>[];
    for (final paragraph in _paragraphs()) {
      final visible = _visibleRect(paragraph, stage);
      if (visible == null || !sweep.overlaps(visible)) continue;
      final food = _food(paragraph);
      final transform = paragraph.getTransformTo(stage);
      for (final glyph in food.glyphs) {
        if (food.offsets.contains(glyph.start)) continue;
        for (final box in glyph.boxes) {
          final rect = MatrixUtils.transformRect(transform, box);
          if (!visible.contains(rect.center) || !_sweeps(rect.intersect(visible), from, to, radius)) continue;
          food.eat(glyph);
          count++;
          if (particles.length < maxParticles) particles.add((char: glyph.char, from: rect.center));
          break;
        }
      }
    }
    if (count > 0) markNeedsPaint();
    return PetErasure(count, particles);
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final holes = Path();
    for (final paragraph in _paragraphs()) {
      if (_eaten[paragraph]?.offsets.isNotEmpty != true) continue;
      holes.addPath(_food(paragraph).holes.transform(paragraph.getTransformTo(this).storage), Offset.zero);
    }
    if (holes.getBounds().isEmpty) {
      super.paint(context, offset);
      return;
    }
    final path = Path.combine(PathOperation.difference, Path()..addRect(Offset.zero & size), holes);
    context.pushClipPath(needsCompositing, offset, Offset.zero & size, path, super.paint, clipBehavior: Clip.hardEdge);
  }
}

/// While [active], the pet fades away (a panel opened right where it stands).
class PetCover extends StatefulWidget {
  const PetCover({super.key, this.active = true, required this.child});

  final bool active;
  final Widget child;

  @override
  State<PetCover> createState() => PetCoverState();
}

class PetCoverState extends State<PetCover> {
  PerchRegistry? _registry;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final registry = PetPerchScope.maybeOf(context);
    if (registry == _registry) return;
    _registry?._covers.remove(this);
    _registry = registry;
    registry?._covers.add(this);
    registry?._changed();
  }

  @override
  void didUpdateWidget(PetCover oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active != widget.active) _registry?._changed();
  }

  @override
  void dispose() {
    _registry?._covers.remove(this);
    _registry?._changed();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
