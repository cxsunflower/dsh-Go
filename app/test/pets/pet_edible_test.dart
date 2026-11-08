import 'dart:ui' as ui;

import 'package:dsh_app/state/chat_state.dart';
import 'package:dsh_app/ui/chat/widgets/thinking_pill.dart';
import 'package:dsh_app/ui/pets/pet_perch.dart';
import 'package:dsh_app/ui/pets/pet_snack.dart';
import 'package:dsh_app/ui/pets/pet_stage.dart';
import 'package:dsh_app/pets/pet_sheets.dart';
import 'package:dsh_client/dsh_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support.dart';

Future<int> _ink(WidgetTester tester, GlobalKey boundary, {Rect? region}) async => (await tester.runAsync(() async {
  final image = await (boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary).toImage();
  final data = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!.buffer.asUint8List();
  var alpha = 0;
  final area = (region ?? Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble())).intersect(
    Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble()),
  );
  for (var y = area.top.ceil(); y < area.bottom.floor(); y++) {
    for (var x = area.left.ceil(); x < area.right.floor(); x++) {
      alpha += data[(y * image.width + x) * 4 + 3];
    }
  }
  image.dispose();
  return alpha;
}))!;

class _CountedText extends LeafRenderObjectWidget {
  const _CountedText(this.text);

  final String text;

  @override
  _CountedParagraph createRenderObject(BuildContext context) => _CountedParagraph(text);

  @override
  void updateRenderObject(BuildContext context, _CountedParagraph renderObject) {
    renderObject.text = TextSpan(
      text: text,
      style: const TextStyle(fontSize: 20, color: Colors.black),
    );
  }
}

class _CountedParagraph extends RenderParagraph {
  _CountedParagraph(String text)
    : super(
        TextSpan(
          text: text,
          style: const TextStyle(fontSize: 20, color: Colors.black),
        ),
        textDirection: TextDirection.ltr,
      );

  int boxQueries = 0;

  @override
  List<ui.TextBox> getBoxesForSelection(
    TextSelection selection, {
    ui.BoxHeightStyle boxHeightStyle = ui.BoxHeightStyle.tight,
    ui.BoxWidthStyle boxWidthStyle = ui.BoxWidthStyle.tight,
  }) {
    boxQueries++;
    return super.getBoxesForSelection(selection, boxHeightStyle: boxHeightStyle, boxWidthStyle: boxWidthStyle);
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(PetSheets.instance.clear);

  testWidgets('a fast sweep erases a whole reply in one frame, caches boxes, and keeps its record', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    final boundary = GlobalKey();
    const message = AssistantChatItem(id: 'reply', text: 'ABCDEFGHIJKLMNOPQRSTUVWX', reasoning: 'Keep this too');
    final state = ChatState(items: [message]);
    var callbacks = 0;
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: PetPerchScope(
          registry: registry,
          child: Stack(
            key: stage,
            children: [
              Positioned(
                left: 40,
                top: 40,
                child: RepaintBoundary(
                  key: boundary,
                  child: PetFood(
                    active: false,
                    edible: true,
                    onErase: () => callbacks++,
                    child: _CountedText(message.text),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    final meal = tester.state<PetFoodState>(find.byType(PetFood));
    final paragraph = tester.renderObject<_CountedParagraph>(find.byType(_CountedText));
    final rect = meal.rectIn(box)!;
    expect(await _ink(tester, boundary), greaterThan(0));
    final erased = registry.eraseAlong(
      box,
      rect.centerLeft - const Offset(50, 0),
      rect.centerRight + const Offset(50, 0),
      radius: PetMetrics.eraseRadius,
      maxParticles: 2,
    );
    expect(erased.count, message.text.length, reason: 'one pointer update, not one letter per timer');
    expect(erased.glyphs, hasLength(2));
    expect(callbacks, 0, reason: 'callbacks must not run during rendering');
    final queries = paragraph.boxQueries;
    expect(queries, message.text.length);
    await tester.pump(const Duration(milliseconds: 16));
    expect(await _ink(tester, boundary), 0);
    expect(callbacks, 1);
    for (var i = 0; i < 10; i++) {
      expect(registry.eraseAlong(box, rect.topLeft, rect.bottomRight, radius: 50).count, 0);
      paragraph.markNeedsPaint();
      await tester.pump(const Duration(milliseconds: 16));
    }
    expect(paragraph.boxQueries, queries, reason: 'erasing and repainting reuse layout boxes');
    expect(callbacks, 1, reason: 'already erased text does not fire again');
    expect(meal.rectIn(box), rect);
    expect(state.items.single, same(message));
    expect(message.text, 'ABCDEFGHIJKLMNOPQRSTUVWX');
    expect(message.reasoning, 'Keep this too');
    expect(tester.widget<_CountedText>(find.byType(_CountedText)).text, message.text);
  });

  testWidgets('a diagonal jump follows the segment across foods, not its bounding rectangle', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: PetPerchScope(
          registry: registry,
          child: Stack(
            key: stage,
            children: [
              for (final (letter, point) in [
                ('A', const Offset(40, 40)),
                ('B', const Offset(200, 200)),
                ('C', const Offset(400, 400)),
                ('Z', const Offset(400, 40)),
              ])
                Positioned(
                  left: point.dx,
                  top: point.dy,
                  child: PetFood(edible: true, child: _CountedText(letter)),
                ),
            ],
          ),
        ),
      ),
    );
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    final result = registry.eraseAlong(box, const Offset(10, 10), const Offset(460, 460), radius: 16);
    expect(result.count, 3);
    expect(result.glyphs.map((g) => g.char), [65, 66, 67]);
    expect(registry.eraseAlong(box, const Offset(460, 460), const Offset(10, 10), radius: 16).count, 0);
    final untouched = registry.eraseAlong(box, const Offset(410, 50), const Offset(410, 50), radius: 20);
    expect(untouched.count, 1);
    expect(untouched.glyphs.single.char, 90);
  });

  testWidgets('a narrow fast sweep erases only glyphs within 12px of its path', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    const text = 'ABCDEFGHIJKLMNOPQRST';
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: PetPerchScope(
          registry: registry,
          child: Stack(
            key: stage,
            children: const [Positioned(left: 40, top: 40, child: PetFood(edible: true, child: _CountedText(text)))],
          ),
        ),
      ),
    );
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    final paragraph = tester.renderObject<_CountedParagraph>(find.byType(_CountedText));
    final glyphs = [
      for (var i = 0; i < text.length; i++)
        MatrixUtils.transformRect(
          paragraph.getTransformTo(box),
          paragraph.getBoxesForSelection(TextSelection(baseOffset: i, extentOffset: i + 1)).single.toRect(),
        ),
    ];
    final from = glyphs[5].center;
    final to = glyphs[14].center;
    final brush = Rect.fromPoints(from, to).inflate(12);
    final expected = [
      for (var i = 0; i < text.length; i++)
        if (glyphs[i].overlaps(brush)) text.codeUnitAt(i),
    ];
    expect((to - from).distance, greaterThan(150), reason: 'one fast pointer update spans many glyphs');
    expect(expected.length, inExclusiveRange(5, text.length));
    final erased = registry.eraseAlong(box, from, to, radius: PetMetrics.eraseRadius, maxParticles: text.length);
    expect(
      erased.glyphs.map((g) => g.char),
      expected,
      reason: 'only actual glyph boxes touching the narrow path disappear',
    );
    expect(erased.count, expected.length);
    final remaining = registry.eraseAlong(
      box,
      glyphs.first.center,
      glyphs.last.center,
      radius: 12,
      maxParticles: text.length,
    );
    expect(remaining.glyphs.map((g) => g.char), [
      for (final char in text.codeUnits)
        if (!expected.contains(char)) char,
    ]);
  });

  testWidgets('stage clipping protects offscreen glyphs until they become visible', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    Widget page(double width) => Directionality(
      textDirection: TextDirection.ltr,
      child: Align(
        alignment: Alignment.topLeft,
        child: SizedBox(
          width: width,
          height: 40,
          child: PetPerchScope(
            registry: registry,
            child: Stack(
              key: stage,
              clipBehavior: Clip.none,
              children: const [
                Positioned(left: 0, top: 0, child: PetFood(edible: true, child: _CountedText('ABCDEFGHIJ'))),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpWidget(page(100));
    RenderBox box() => stage.currentContext!.findRenderObject()! as RenderBox;
    final first = registry.eraseAlong(box(), const Offset(-100, 10), const Offset(400, 10), radius: 30);
    expect(first.count, inExclusiveRange(0, 10));
    await tester.pumpWidget(page(400));
    final second = registry.eraseAlong(box(), const Offset(-100, 10), const Offset(400, 10), radius: 30);
    expect(second.count, 10 - first.count, reason: 'previously offscreen letters were not erased');
  });

  testWidgets('stream append and reflow retain holes; replacing the source resets them', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    Widget page(String text, double width) => Directionality(
      textDirection: TextDirection.ltr,
      child: PetPerchScope(
        registry: registry,
        child: Stack(
          key: stage,
          children: [
            Positioned(
              left: 0,
              top: 0,
              width: width,
              child: PetFood(edible: true, child: _CountedText(text)),
            ),
          ],
        ),
      ),
    );
    PetErasure sweep() => registry.eraseAlong(
      stage.currentContext!.findRenderObject()! as RenderBox,
      Offset.zero,
      const Offset(300, 300),
      radius: 300,
    );
    await tester.pumpWidget(page('ABCD', 300));
    expect(sweep().count, 4);
    await tester.pumpWidget(page('ABCDEF', 40));
    expect(sweep().count, 2);
    await tester.pumpWidget(page('XYZ', 300));
    expect(sweep().count, 3);
  });

  testWidgets('erasure particles are capped and never produce one sound per glyph', (tester) async {
    var bites = 0;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(),
        child: PetSnackLayer(
          anim: 'prone-eat',
          scale: 1,
          active: false,
          every: 260,
          mouth: Offset.zero,
          launch: const [],
          text: const SnackText(''),
          onBite: () => bites++,
        ),
      ),
    );
    final snack = tester.state<PetSnackLayerState>(find.byType(PetSnackLayer));
    for (var i = 0; i < 20; i++) {
      snack.addErasedGlyphs(List.generate(20, (i) => (char: 65, from: Offset(i.toDouble(), 0))));
    }
    expect(snack.flying, 3, reason: 'erasure particles are capped at the slow sky');
    await tester.pump(const Duration(milliseconds: 300));
    expect(snack.bites, PetSnackLayer.maxFlying);
    expect(bites, 0);
    await tester.pump(const Duration(milliseconds: 400));
    expect(snack.running, isFalse);
  });

  testWidgets('onErase coalesces bites and safely lets a parent hide its current UI', (tester) async {
    final stage = GlobalKey();
    var callbacks = 0;
    var hidden = false;
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: StatefulBuilder(
          builder: (context, update) => Stack(
            key: stage,
            children: [
              if (!hidden)
                PetFood(
                  edible: true,
                  onErase: () {
                    callbacks++;
                    update(() => hidden = true);
                  },
                  child: const _CountedText('ABCD'),
                ),
            ],
          ),
        ),
      ),
    );
    expect(callbacks, 0);
    final meal = tester.state<PetFoodState>(find.byType(PetFood));
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    expect(meal.takeGlyph(box, Offset.zero), isNotNull);
    expect(meal.takeGlyph(box, Offset.zero), isNotNull);
    expect(callbacks, 0);
    await tester.pump();
    await tester.pump();
    expect(callbacks, 1);
    expect(find.byType(PetFood), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('eaten glyphs disappear from paint without changing source or layout', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    final boundary = GlobalKey();
    const source = 'AB你😀';
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: PetPerchScope(
          registry: registry,
          child: Stack(
            key: stage,
            children: [
              Positioned(
                left: 20,
                top: 30,
                child: RepaintBoundary(
                  key: boundary,
                  child: const PetFood(
                    active: false,
                    edible: true,
                    child: Text(source, style: TextStyle(fontSize: 20, color: Colors.black)),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    final meal = tester.state<PetFoodState>(find.byType(PetFood));
    final rect = meal.rectIn(box)!;
    expect(registry.foods(box), isEmpty);
    expect(registry.mealAt(box, rect.center), same(meal));
    final before = await _ink(tester, boundary);
    expect(before, greaterThan(0));
    final letters = <int>[];
    for (var i = 0; i < 4; i++) {
      final glyph = meal.takeGlyph(box, rect.center)!;
      expect(rect.contains(glyph.from), isTrue);
      letters.add(glyph.char);
      await tester.pump();
    }
    expect(letters, unorderedEquals([65, 66, 0x4F60, 0x2022]));
    expect(meal.takeGlyph(box, rect.center), isNull);
    expect(await _ink(tester, boundary), 0);
    expect(meal.rectIn(box), rect);
    expect(tester.widget<Text>(find.text(source)).data, source);
  });

  testWidgets('only visible glyphs can be eaten through a clipped scroll window', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    final stage = GlobalKey();
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: PetPerchScope(
          registry: registry,
          child: Stack(
            key: stage,
            children: [
              Positioned(
                left: 20,
                top: 20,
                width: 100,
                height: 20,
                child: ClipRect(
                  child: OverflowBox(
                    alignment: Alignment.topLeft,
                    maxHeight: 100,
                    child: Transform.translate(
                      offset: const Offset(0, -20),
                      child: const PetFood(
                        active: false,
                        edible: true,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            SizedBox(height: 20, child: Text('X', style: TextStyle(fontSize: 16))),
                            SizedBox(height: 20, child: Text('Y', style: TextStyle(fontSize: 16))),
                            SizedBox(height: 20, child: Text('Z', style: TextStyle(fontSize: 16))),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    final meal = tester.state<PetFoodState>(find.byType(PetFood));
    final erased = registry.eraseAlong(box, const Offset(0, 0), const Offset(200, 100), radius: 200);
    expect(erased.count, 1);
    expect(erased.glyphs.single.char, 89);
    expect(meal.takeGlyph(box, const Offset(30, 30)), isNull);
    expect(registry.mealAt(box, const Offset(30, 300)), isNull);
  });

  testWidgets('expanded completed reasoning remains edible', (tester) async {
    final registry = PerchRegistry();
    addTearDown(registry.dispose);
    await tester.pumpWidget(
      testApp(
        PetPerchScope(
          registry: registry,
          child: const Scaffold(body: ThinkingPill(reasoning: 'Completed reasoning.')),
        ),
      ),
    );
    await tester.tap(find.byType(ThinkingPill));
    await tester.pumpAndSettle();
    final foods = tester.widgetList<PetFood>(find.byType(PetFood)).where((food) => food.edible);
    expect(foods, isNotEmpty);
    expect(foods.every((food) => !food.active), isTrue);
  });

  testWidgets('Naiwa uses a 12px mouth while held and 20px after release, preserving nearby text', (tester) async {
    final pack = diskPack('naiwa');
    usePhoneView(tester);
    await warmSheets(tester, pack, pack.animations.values.toList());
    var erased = 0;
    final boundary = GlobalKey();
    const source = 'ABCDEFGHIJKLMNOPQRST';
    await tester.pumpWidget(
      testApp(
        Scaffold(
          body: PetStage(
            child: Stack(
              children: [
                Positioned(
                  left: 32,
                  top: 120,
                  width: 300,
                  height: 280,
                  child: RepaintBoundary(
                    key: boundary,
                    child: PetFood(
                      active: false,
                      edible: true,
                      onErase: () => erased++,
                      child: const Text(source, style: TextStyle(fontFamily: 'JetBrainsMono', fontSize: 20)),
                    ),
                  ),
                ),
                const Positioned(
                  left: 12,
                  right: 12,
                  bottom: 12,
                  child: PetPerch(kind: PerchKind.composer, child: SizedBox(height: 60)),
                ),
              ],
            ),
          ),
        ),
        overrides: petOverrides(pack: pack, clock: TestClock()),
      ),
    );
    for (var i = 0; i < 6; i++) {
      await tester.pump();
    }
    final layer = petLayer(tester);
    final start = tester.getCenter(find.byKey(const ValueKey('pet-body')));
    final gesture = await tester.startGesture(start);
    await gesture.moveBy(const Offset(0, -20));
    await tester.pump();
    final mouthOffset =
        (pack.snack!.mouthOf('prone-eat') - Offset(pack.anchorX, pack.baseline)) * petScaleOn(tester, pack);
    final paragraph = tester.renderObject<RenderParagraph>(
      find.descendant(of: find.text(source), matching: find.byType(RichText)),
    );
    Rect glyph(int index) =>
        paragraph.getBoxesForSelection(TextSelection(baseOffset: index, extentOffset: index + 1)).single.toRect();
    final mouth = glyph(10).center;
    final target = paragraph.localToGlobal(mouth);
    final dragOnly = glyph(11);
    final releaseOnly = glyph(12);
    final untouched = glyph(13);
    expect(dragOnly.left - mouth.dx, lessThan(12));
    expect(releaseOnly.left - mouth.dx, inExclusiveRange(12, 20));
    expect(untouched.left - mouth.dx, inExclusiveRange(20, 32));
    final untouchedInk = await _ink(tester, boundary, region: untouched);
    final releaseInk = await _ink(tester, boundary, region: releaseOnly);
    expect(untouchedInk, greaterThan(0));
    expect(releaseInk, greaterThan(0));
    // Approach vertically so the route does not sweep the neighboring glyphs.
    await gesture.moveBy(target + const Offset(0, 100) - mouthOffset - layer.foot!);
    await tester.pump();
    await gesture.moveBy(target - mouthOffset - layer.foot!);
    await tester.pump(const Duration(milliseconds: 16));
    expect(erased, greaterThan(0), reason: 'dragging erases immediately, before releasing or the 260ms timer');
    expect(await _ink(tester, boundary, region: dragOnly), 0);
    expect(await _ink(tester, boundary, region: releaseOnly), releaseInk);
    expect(await _ink(tester, boundary, region: untouched), untouchedInk);
    await tester.pump(const Duration(milliseconds: 400));
    expect(
      await _ink(tester, boundary, region: releaseOnly),
      releaseInk,
      reason: 'the bite timer must also use 12px while held',
    );
    await gesture.up();
    await tester.pump(const Duration(milliseconds: 16));
    expect(
      await _ink(tester, boundary, region: releaseOnly),
      0,
      reason: 'releasing reaches the glyph inside 20px in one frame',
    );
    expect(await _ink(tester, boundary, region: untouched), untouchedInk);
    final foot = layer.foot!;
    expect(foot.dy, lessThan(450));
    await tester.pump(const Duration(milliseconds: 500));
    expect(layer.playing!.name, 'prone-eat');
    final snack = tester.state<PetSnackLayerState>(find.byType(PetSnackLayer));
    expect(snack.launched, greaterThan(0));
    await tester.pump(const Duration(seconds: 2));
    expect(snack.bites, greaterThan(0));
    expect(
      await _ink(tester, boundary, region: untouched),
      untouchedInk,
      reason: 'stationary eating does not spread beyond 20px',
    );
    expect(tester.widget<Text>(find.text(source)).data, source);
    expect(layer.foot, foot);
    expect(layer.walking, isFalse);
  });
}
