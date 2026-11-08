// Code snacks on the chat page (docs/design/naiwa-pet.md §7): glyphs of the
// reasoning being written in the conversation on screen, else of the command
// on its run strip or a few built-in jokes (round and round), take off and arc
// into the pet's mouth. Secrets are masked. ASCII is drawn in a 5×7 pixel font,
// anything else (Chinese above all) from the app's font in a 9×9 square of
// whole dots; a dot per art pixel, snapped to the pet's art grid, stepping
// twelve times a second; each one eaten drops a few crumbs. Only drawn: the
// text is not kept, sent or logged. Nothing ticks or repaints unless the pet
// is eating or something is still in the air.

import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:dsh_client/dsh_client.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/chat_state.dart';
import '../../state/sessions_state.dart';
import '../chat/run_info.dart';
import '../chat/secret_mask.dart';
import '../theme/motion.dart';
import 'pixel_font.dart';

/// What the pet eats when no command shows: ASCII only.
const petSnackJokes = [
  'git push -f',
  'rm -rf node_modules',
  'while (true) {}',
  'NaN',
  'undefined',
  '404',
  'null',
  '0xDEADBEEF',
  'sudo !!',
  '=> {}',
  '</div>',
  'TODO',
  ';;;',
  'catch (e) {}',
  'return 42;',
];

/// [petSnackJokes] joined for eating, built from the list (not copied).
final petSnackJokesText = petSnackJokes.join(' ');

/// A character a snack can be: the pixel font's ASCII, or any other of the
/// Basic Multilingual Plane drawn from the app's font, but blanks, controls,
/// combining marks, zero-width and direction marks, variation selectors and
/// what needs a surrogate pair (emoji).
bool petSnackDrawable(int char) {
  if (PixelFont.glyph(char) != null) return true;
  if (char <= 0xA0 || (char >= 0xD800 && char <= 0xDFFF)) return false;
  if (char >= 0x0300 && char <= 0x036F) return false;
  if (char >= 0x2000 && char <= 0x206F) return false;
  if (char >= 0xFE00 && char <= 0xFE0F) return false;
  return char != 0x1680 && char != 0x3000 && char != 0xFEFF;
}

/// What the pet eats while the run strip shows [activity]: its command,
/// secrets masked, or the jokes when it shows none (or none it can draw).
String petSnackText(RunActivity? activity) {
  if (activity != null && activity.detailIsCode) {
    final masked = maskSecrets(activity.detail);
    if (masked.codeUnits.any(petSnackDrawable)) return masked;
  }
  return petSnackJokes.join(' ');
}

/// What the pet eats: the reasoning being written, or a text it eats round
/// and round.
@immutable
class SnackText {
  const SnackText(this.text, {this.reply, this.end = 0});

  /// Reasoning [id] written so far as [text], ready to eat: up to its last
  /// blank or non-ASCII character (the run after it may still grow into a
  /// key, which masking knows only once whole), the last [tail] code units
  /// of that, secrets masked.
  factory SnackText.ofReply(String id, String text) {
    var end = text.length;
    while (end > 0) {
      final c = text.codeUnitAt(end - 1);
      if (c <= 0x20 || c >= 0x7F) break;
      end--;
    }
    // Masked whole: a key block or a long token may start far back. Masking
    // keeps ASCII as long as it was, so the two line up from the end (a
    // surrogate pair inside a secret becomes one mark, further back).
    final masked = maskSecrets(text);
    final to = masked.length - (text.length - end);
    return SnackText(masked.substring(math.max(0, to - tail), to), reply: id, end: end);
  }

  /// Code units of a reasoning kept for eating.
  static const tail = 256;

  /// What there is to eat; for a reasoning, the stretch of it that ends at
  /// [end].
  final String text;

  /// The reasoning being written ([AssistantChatItem.id]/reasoning); null for
  /// a text eaten round and round.
  final String? reply;

  /// For a reasoning: how far into it [text] reaches, in code units.
  final int end;

  @override
  bool operator ==(Object other) =>
      other is SnackText && other.text == text && other.reply == reply && other.end == end;

  @override
  int get hashCode => Object.hash(text, reply, end);
}

/// What the pet eats in [s]: the reasoning being written, else the command on
/// the run strip, else the jokes. The reply's own text is never eaten.
SnackText petSnackOf(ChatState s) {
  // The newest thing in the turn, as on the run strip: a call running after
  // the reply makes the command the snack.
  for (final item in s.items.reversed) {
    if (item is AssistantChatItem && item.streaming) {
      // Only the reasoning: the answer itself stays whole and unerasable.
      if (item.reasoning.isNotEmpty) return SnackText.ofReply('${item.id}/reasoning', item.reasoning);
      break;
    }
    if (item is UserChatItem ||
        (item is ToolChatItem &&
            (item.status == ToolStatus.running ||
                item.status == ToolStatus.streaming ||
                item.status == ToolStatus.awaitingApproval))) {
      break;
    }
  }
  return SnackText(petSnackText(runActivityOf(s)));
}

/// [petSnackOf] for the conversation on screen.
final petSnackTextProvider = Provider.autoDispose<SnackText>((ref) {
  final id = ref.watch(currentSessionProvider);
  if (id == null) return SnackText(petSnackText(null));
  return ref.watch(chatProvider(id).select(petSnackOf));
});

/// Glyphs flying into the pet's mouth, laid over its canvas: the layer's
/// origin is the canvas's top-left, and it paints outside its own (empty)
/// box. Glyphs take off while [active]; switched off, those in the air still
/// land. With animations off in the system, the app out of sight or the page
/// under another route, nothing flies and nothing ticks.
class PetSnackLayer extends StatefulWidget {
  const PetSnackLayer({
    super.key,
    required this.anim,
    required this.scale,
    required this.active,
    required this.every,
    required this.mouth,
    required this.launch,
    required this.text,
    this.fallback = const SnackText(''),
    this.onBite,
    this.takeGlyph,
  });

  /// The animation playing: a new one restarts the rhythm.
  final String anim;

  /// Logical pixels per art pixel: a glyph's dot is this square.
  final double scale;
  final bool active;

  /// Milliseconds between take-offs.
  final int every;

  /// Where glyphs vanish.
  final Offset mouth;

  /// Where they take off.
  final List<Rect> launch;

  /// What they spell: a reasoning's new characters in order (no more than
  /// [backlog] behind), or a text from the top again at its end; blanks and
  /// anything but printable ASCII are skipped.
  final SnackText text;

  /// What to eat when [takeGlyph] finds nothing at the mouth: the built-in
  /// ASCII jokes, round and round. Empty means stay quiet.
  final SnackText fallback;

  /// A glyph was eaten.
  final VoidCallback? onBite;
  final ({int char, Offset from})? Function()? takeGlyph;

  /// Glyphs in the air at most: one bite is readable on its own.
  static const maxFlying = 3;

  /// At least this long between take-offs on the chat page, whatever a pack's
  /// `snack.every` says; one glyph at a time (docs/design/naiwa-pet.md §7).
  static const slowestEvery = 1200;

  /// A reply's characters waiting at most: further behind, it skips to the
  /// newest.
  static const backlog = 48;

  /// Twelve steps a second.
  static const step = Duration(microseconds: 1000000 ~/ 12);

  /// Dice for take-off points, flights and crumbs (tests seed it).
  static math.Random random = math.Random();

  @override
  State<PetSnackLayer> createState() => PetSnackLayerState();
}

class PetSnackLayerState extends State<PetSnackLayer> with WidgetsBindingObserver {
  static const _stepMs = 1000 / 12;
  static const _crumbMs = 300.0;

  final _repaint = ValueNotifier<int>(0);
  final _flying = <_Glyph>[];
  final _crumbs = <_Crumb>[];
  Timer? _timer;

  /// Steps taken: the clock flights and crumbs are timed by.
  int _steps = 0;
  int _base = 0;

  /// When the next glyph takes off, ms on that clock; null while not eating.
  double? _due;

  /// Where in a looped text the next glyph comes from.
  int _next = 0;

  /// Where in [PetSnackLayer.fallback] the next glyph comes from.
  int _nextFallback = 0;

  /// How far into the reply glyphs have been taken, in its code units.
  int _eaten = 0;
  int _launched = 0;
  int _bites = 0;

  /// Something was on the last frame (it has to be wiped once gone).
  bool _drawn = false;
  bool _reduced = false;
  bool _ticking = true;
  bool _appVisible = true;

  @visibleForTesting
  int get flying => _flying.length;

  @visibleForTesting
  int get crumbs => _crumbs.length;

  /// Glyphs that took off, and those eaten.
  @visibleForTesting
  int get launched => _launched;

  @visibleForTesting
  int get bites => _bites;

  /// What is in the air, in take-off order.
  @visibleForTesting
  String get aloft => String.fromCharCodes([for (final g in _flying) g.char]);

  /// The step timer runs.
  @visibleForTesting
  bool get running => _timer != null;

  /// A few samples of an already erased area. Erasure never waits for flights
  /// or plays one sound per letter, and a busy sky simply drops extra samples.
  void addErasedGlyphs(Iterable<({int char, Offset from})> glyphs) {
    if (_reduced || !_ticking || !_appVisible) return;
    for (final glyph in glyphs.take(3)) {
      if (_flying.length >= PetSnackLayer.maxFlying) break;
      _flying.add(
        _Glyph(
          glyph.char,
          colour: _launched++ % _palette.length,
          from: glyph.from,
          at: _now,
          ms: 240,
          arc: 6 * widget.scale,
          audible: false,
        ),
      );
    }
    _sync();
    if (_flying.isNotEmpty) {
      _drawn = true;
      _repaint.value++;
    }
  }

  double get _now => _steps * _stepMs;

  @override
  void initState() {
    super.initState();
    _eaten = widget.text.end;
    _appVisible = _visibleIn(WidgetsBinding.instance.lifecycleState);
    WidgetsBinding.instance.addObserver(this);
  }

  // As PetSprite: inactive views can still be visible.
  static bool _visibleIn(AppLifecycleState? state) => switch (state) {
    null || AppLifecycleState.resumed || AppLifecycleState.inactive => true,
    _ => false,
  };

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appVisible = _visibleIn(state);
    _sync();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduced = AppMotion.reduced(context);
    _ticking = TickerMode.valuesOf(context).enabled;
    _sync();
  }

  @override
  void didUpdateWidget(PetSnackLayer oldWidget) {
    super.didUpdateWidget(oldWidget);
    final text = widget.text;
    // Another reply, or eating starts again: only what is written from now.
    if (text.reply != oldWidget.text.reply || (widget.active && !oldWidget.active)) _eaten = text.end;
    if (text.text != oldWidget.text.text) _next = 0;
    if (oldWidget.anim != widget.anim) _due = null;
    _sync();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _stop();
    _repaint.dispose();
    super.dispose();
  }

  /// Ticks while the pet eats or something is still in the air, and only
  /// where it can be seen; elsewhere the air is cleared.
  void _sync() {
    if (_reduced || !_ticking || !_appVisible) {
      _stop();
      _due = null;
      _flying.clear();
      _crumbs.clear();
      if (_drawn) {
        _drawn = false;
        _repaint.value++;
      }
      return;
    }
    _due = widget.active ? (_due ?? _now) : null;
    if (_due != null || _flying.isNotEmpty || _crumbs.isNotEmpty) {
      _start();
    } else {
      _stop();
    }
  }

  void _start() {
    if (_timer != null) return;
    _base = _steps;
    _timer = Timer.periodic(PetSnackLayer.step, _tick);
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
  }

  void _tick(Timer timer) {
    _steps = _base + timer.tick;
    final now = _now;
    _crumbs.removeWhere((c) => now - c.at >= _crumbMs);
    var eaten = 0;
    var audible = 0;
    _flying.removeWhere((g) {
      if (now - g.at < g.ms) return false;
      eaten++;
      if (g.audible) audible++;
      _crumble(g, now);
      return true;
    });
    final due = _due;
    if (due != null && now >= due && _flying.length < PetSnackLayer.maxFlying) {
      _launch(now);
      final next = due + widget.every;
      _due = next > now ? next : now + widget.every;
    }
    _bites += eaten;
    final busy = _flying.isNotEmpty || _crumbs.isNotEmpty;
    if (busy || _drawn) _repaint.value++;
    _drawn = busy;
    if (!busy && _due == null) _stop();
    for (var i = 0; i < audible; i++) {
      widget.onBite?.call();
    }
  }

  void _launch(double now) {
    final take = widget.takeGlyph;
    final taken = take?.call();
    final glyph = take == null ? null : (taken ?? _fallbackGlyph());
    if (take != null && glyph == null) return;
    final from = glyph?.from ?? _takeOff();
    if (from == null) return;
    final char = glyph?.char ?? _nextChar();
    if (char == null) return;
    final r = PetSnackLayer.random;
    _flying.add(
      _Glyph(
        char,
        colour: _launched++ % _palette.length,
        from: from,
        at: now,
        ms: 700 + 300 * r.nextDouble(),
        arc: (8 + 8 * r.nextDouble()) * widget.scale,
        audible: take == null,
      ),
    );
  }

  /// A joke glyph at a launch point, when the reasoning at the mouth has run
  /// out; null for an empty fallback.
  ({int char, Offset from})? _fallbackGlyph() {
    final text = widget.fallback.text;
    if (text.isEmpty) return null;
    final from = _takeOff();
    if (from == null) return null;
    for (var i = 0; i < text.length; i++) {
      if (_nextFallback >= text.length) _nextFallback = 0;
      final char = text.codeUnitAt(_nextFallback++);
      if (petSnackDrawable(char)) return (char: char, from: from);
    }
    return null;
  }

  /// The next glyph, or null when there is none to draw: a reply's next new
  /// one, or a looped text's next.
  int? _nextChar() {
    final snack = widget.text;
    final text = snack.text;
    if (snack.reply != null) {
      final end = snack.end;
      final start = end - text.length;
      _eaten = math.max(_eaten, math.max(start, end - PetSnackLayer.backlog));
      while (_eaten < end) {
        final char = text.codeUnitAt(_eaten++ - start);
        if (petSnackDrawable(char)) return char;
      }
      return null;
    }
    for (var i = 0; i < text.length; i++) {
      if (_next >= text.length) _next = 0;
      final char = text.codeUnitAt(_next++);
      if (petSnackDrawable(char)) return char;
    }
    return null;
  }

  /// A take-off point, uniform over the launch areas.
  Offset? _takeOff() {
    final areas = widget.launch;
    final total = areas.fold(0.0, (sum, a) => sum + a.width * a.height);
    if (total <= 0) return null;
    final r = PetSnackLayer.random;
    var pick = r.nextDouble() * total;
    var area = areas.last;
    for (final a in areas) {
      final size = a.width * a.height;
      if (pick < size) {
        area = a;
        break;
      }
      pick -= size;
    }
    return Offset(area.left + r.nextDouble() * area.width, area.top + r.nextDouble() * area.height);
  }

  void _crumble(_Glyph glyph, double now) {
    final r = PetSnackLayer.random;
    for (var i = 2 + r.nextInt(2); i > 0; i--) {
      _crumbs.add(
        _Crumb(
          colour: glyph.colour,
          at: now,
          dx: 4 * r.nextDouble() - 2,
          drift: 2 * r.nextDouble() - 1,
          fall: 3 + 3 * r.nextDouble(),
        ),
      );
    }
  }

  void _paint(Canvas canvas, double s, Offset mouth) {
    final now = _now;
    for (final g in _flying) {
      final p = ((now - g.at) / g.ms).clamp(0.0, 1.0);
      final x = g.from.dx + (mouth.dx - g.from.dx) * p;
      final y = g.from.dy + (mouth.dy - g.from.dy) * p - 4 * g.arc * p * (1 - p);
      if (PixelFont.glyph(g.char) == null) {
        final image = _wideGlyph(g.char);
        final dst = Rect.fromLTWH(
          (x / s - _wide / 2).roundToDouble() * s,
          (y / s - _wide / 2).roundToDouble() * s,
          _wide * s,
          _wide * s,
        );
        const src = Rect.fromLTWH(0, 0, _wideSize, _wideSize);
        for (final (dx, dy) in const [(-1, 0), (1, 0), (0, -1), (0, 1)]) {
          canvas.drawImageRect(image, src, dst.shift(Offset(dx * s, dy * s)), _wideOutline);
        }
        canvas.drawImageRect(image, src, dst, _widePaints[g.colour]);
        continue;
      }
      final (dots, outline) = _glyphPaths(g.char);
      canvas
        ..save()
        ..translate(
          (x / s - PixelFont.width / 2).roundToDouble() * s,
          (y / s - PixelFont.height / 2).roundToDouble() * s,
        )
        ..scale(s)
        ..drawPath(outline, _outlinePaint)
        ..drawPath(dots, _palettePaints[g.colour])
        ..restore();
    }
    for (final c in _crumbs) {
      final t = (now - c.at) / _crumbMs;
      final x = (mouth.dx / s + c.dx + c.drift * t).roundToDouble() * s;
      final y = (mouth.dy / s + c.fall * t * t).roundToDouble() * s;
      canvas.drawRect(
        Rect.fromLTWH(x, y, s, s),
        Paint()
          ..isAntiAlias = false
          ..color = _palette[c.colour].withValues(alpha: 1 - t),
      );
    }
  }

  @override
  Widget build(BuildContext context) => CustomPaint(
    painter: _SnackPainter(this, scale: widget.scale, mouth: widget.mouth, repaint: _repaint),
  );
}

/// A glyph in the air: where it took off (its centre), when and for how long
/// (ms on the step clock), and how high its arc rises (logical px).
class _Glyph {
  _Glyph(
    this.char, {
    required this.colour,
    required this.from,
    required this.at,
    required this.ms,
    required this.arc,
    this.audible = true,
  });

  final int char;
  final int colour;
  final Offset from;
  final double at;
  final double ms;
  final double arc;
  final bool audible;
}

/// A crumb falling from the mouth, in art pixels: where it starts beside the
/// mouth, and how far it drifts and falls before it fades out.
class _Crumb {
  _Crumb({required this.colour, required this.at, required this.dx, required this.drift, required this.fall});

  final int colour;
  final double at;
  final double dx;
  final double drift;
  final double fall;
}

// Code-highlight colours with a dark outline: readable on light and dark.
const _palette = [
  Color(0xFFC678DD),
  Color(0xFF98C379),
  Color(0xFFD19A66),
  Color(0xFF61AFEF),
  Color(0xFFE5C07B),
  Color(0xFFABB2BF),
];

final _palettePaints = [
  for (final colour in _palette)
    Paint()
      ..isAntiAlias = false
      ..color = colour,
];

final _outlinePaint = Paint()
  ..isAntiAlias = false
  ..color = const Color(0xFF282C34);

/// Dots on a side of a glyph drawn from the app's font.
const _wide = 9;
const _wideSize = 9.0;

/// Its coverage as whole dots of [colour]: a dot about half covered or less
/// is none.
Paint _wideDots(Color colour) => Paint()
  ..isAntiAlias = false
  ..filterQuality = FilterQuality.none
  ..colorFilter = ColorFilter.matrix(<double>[
    0, 0, 0, 0, colour.r * 255, //
    0, 0, 0, 0, colour.g * 255, //
    0, 0, 0, 0, colour.b * 255, //
    0, 0, 0, 4, -384, //
  ]);

final _widePaints = [for (final colour in _palette) _wideDots(colour)];
final _wideOutline = _wideDots(_outlinePaint.color);

final _wideCache = <int, ui.Image>{};

/// [char] from the app's font, white on clear in a [_wide]-dot square. Kept
/// for the next time; past 256 of them the lot is let go.
ui.Image _wideGlyph(int char) {
  final cached = _wideCache[char];
  if (cached != null) return cached;
  if (_wideCache.length >= 256) {
    for (final image in _wideCache.values) {
      image.dispose();
    }
    _wideCache.clear();
  }
  final painter = TextPainter(
    text: TextSpan(
      text: String.fromCharCode(char),
      style: const TextStyle(fontSize: _wideSize, height: 1, color: Color(0xFFFFFFFF)),
    ),
    textDirection: TextDirection.ltr,
  )..layout();
  final recorder = ui.PictureRecorder();
  painter.paint(Canvas(recorder), Offset((_wideSize - painter.width) / 2, (_wideSize - painter.height) / 2));
  painter.dispose();
  final picture = recorder.endRecording();
  final image = picture.toImageSync(_wide, _wide);
  picture.dispose();
  return _wideCache[char] = image;
}

final _glyphPathCache = <int, (Path, Path)>{};

/// [char]'s dots and its one-dot outline (each dot's four neighbours), a unit
/// per dot.
(Path, Path) _glyphPaths(int char) {
  final cached = _glyphPathCache[char];
  if (cached != null) return cached;
  final dots = Path();
  final outline = Path();
  final columns = PixelFont.glyph(char)!;
  for (var x = 0; x < PixelFont.width; x++) {
    for (var y = 0; y < PixelFont.height; y++) {
      if (columns[x] & (1 << y) == 0) continue;
      dots.addRect(Rect.fromLTWH(x.toDouble(), y.toDouble(), 1, 1));
      for (final (dx, dy) in const [(-1, 0), (1, 0), (0, -1), (0, 1)]) {
        outline.addRect(Rect.fromLTWH((x + dx).toDouble(), (y + dy).toDouble(), 1, 1));
      }
    }
  }
  return _glyphPathCache[char] = (dots, outline);
}

class _SnackPainter extends CustomPainter {
  _SnackPainter(this.state, {required this.scale, required this.mouth, required Listenable repaint})
    : super(repaint: repaint);

  final PetSnackLayerState state;
  final double scale;
  final Offset mouth;

  @override
  void paint(Canvas canvas, Size size) => state._paint(canvas, scale, mouth);

  @override
  bool shouldRepaint(_SnackPainter old) => old.state != state || old.scale != scale || old.mouth != mouth;
}
