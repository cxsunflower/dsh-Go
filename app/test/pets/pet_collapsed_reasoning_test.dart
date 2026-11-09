import 'dart:ui' as ui;

import 'package:dsh_app/state/cot_translation_state.dart';
import 'package:dsh_app/state/sessions_state.dart';
import 'package:dsh_app/ui/chat/render/markdown_body.dart';
import 'package:dsh_app/ui/chat/widgets/assistant_message.dart';
import 'package:dsh_app/ui/chat/widgets/message_actions.dart';
import 'package:dsh_app/ui/chat/widgets/thinking_pill.dart';
import 'package:dsh_app/ui/pets/pet_perch.dart';
import 'package:dsh_client/dsh_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../chat/support/harness.dart';

const _reasoning = 'The first line of reasoning.\n\nA second paragraph that is hidden while collapsed.';
const _answer = 'The answer stays available.';
const _translation = '这是翻译后的思考正文。';
const _limits = CotTranslationLimits(
  maxTextChars: 4000,
  provider: 'bing',
  targetLanguage: 'auto',
  availableProviders: ['bing'],
);

Finder get _edible => find.byWidgetPredicate((widget) => widget is PetFood && widget.edible);
Finder get _reasoningBody => find.descendant(of: find.byType(ThinkingPill), matching: find.byType(MarkdownBody));

Widget _scene(Widget child, PerchRegistry registry, GlobalKey stage, {List<Override> overrides = const []}) => testApp(
  PetPerchScope(
    registry: registry,
    child: Scaffold(
      body: RepaintBoundary(
        key: stage,
        child: SizedBox.expand(
          child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: child),
        ),
      ),
    ),
  ),
  overrides: overrides.isEmpty
      ? [cotTranslationProvider.overrideWith((ref) async => null), reasoningTranslatorProvider.overrideWithValue(null)]
      : overrides,
);

PetFoodState _foodOf(WidgetTester tester, Finder child) =>
    tester.state<PetFoodState>(find.ancestor(of: child, matching: _edible).first);

Future<void> _bite(WidgetTester tester, PetFoodState food, GlobalKey stage, Offset mouth) async {
  final box = stage.currentContext!.findRenderObject()! as RenderBox;
  expect(food.takeGlyph(box, box.globalToLocal(mouth)), isNotNull);
  await tester.pump();
}

Future<void> _eraseAll(WidgetTester tester, PetFoodState food, GlobalKey stage) async {
  final box = stage.currentContext!.findRenderObject()! as RenderBox;
  final center = food.rectIn(box)!.center;
  expect(food.eraseAlong(box, center, center, radius: 10000, maxParticles: 0).count, greaterThan(0));
  await tester.pump();
  expect(food.takeGlyph(box, center), isNull, reason: 'all visible glyphs were actually erased');
}

Future<int> _ink(WidgetTester tester, GlobalKey stage) async => (await tester.runAsync(() async {
  final image = await (stage.currentContext!.findRenderObject()! as RenderRepaintBoundary).toImage();
  final data = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!.buffer.asUint8List();
  var alpha = 0;
  for (var i = 3; i < data.length; i += 4) {
    alpha += data[i];
  }
  image.dispose();
  return alpha;
}))!;

Future<void> _toggle(WidgetTester tester, {bool active = false}) async {
  await tester.tap(find.text(active ? '思考中' : '思考'));
  await pumpFrames(tester, 4);
}

PerchRegistry _registry(WidgetTester tester) {
  final registry = PerchRegistry();
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    registry.dispose();
  });
  return registry;
}

void main() {
  testWidgets('eating the collapsed summary leaves the full reasoning recoverable by expanding', (tester) async {
    final registry = _registry(tester);
    final stage = GlobalKey();
    const item = AssistantChatItem(id: 'a1', text: _answer, reasoning: _reasoning);
    Widget scene() => _scene(const AssistantMessage(item: item, showActions: true), registry, stage);
    await tester.pumpWidget(scene());
    await pumpFrames(tester, 2);

    final summary = _foodOf(tester, find.text('The first line of reasoning.'));
    final box = stage.currentContext!.findRenderObject()! as RenderBox;
    expect(summary.widget.active, isFalse);
    expect(registry.mealAt(box, summary.rectIn(box)!.center), same(summary));
    expect(_reasoningBody, findsNothing);

    final before = await _ink(tester, stage);
    await _eraseAll(tester, summary, stage);
    expect(await _ink(tester, stage), lessThan(before));
    for (var i = 0; i < 2; i++) {
      await _toggle(tester);
      expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
      expect(find.text(_answer), findsOneWidget);
      expect(find.byType(ReplyActionRow), findsOneWidget);
      await _eraseAll(tester, _foodOf(tester, _reasoningBody), stage);
      await _toggle(tester);
    }
    await tester.pumpWidget(scene());
    await _toggle(tester);
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
    expect(item.reasoning, _reasoning);
    expect(item.text, _answer);

    // Leaving and reopening the page uses the original, unmodified transcript.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(scene());
    await _toggle(tester);
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
  });

  testWidgets('translated and original views recover without clearing the translation cache', (tester) async {
    final registry = _registry(tester);
    final stage = GlobalKey();
    final translated = <String>[];
    await tester.pumpWidget(
      _scene(
        const ThinkingPill(reasoning: _reasoning),
        registry,
        stage,
        overrides: [
          currentSessionProvider.overrideWith(() => FixedSession('s1')),
          cotTranslationProvider.overrideWith((ref) async => _limits),
          reasoningTranslatorProvider.overrideWithValue((text, {required limits, sessionId}) async {
            translated.add(text);
            return _translation;
          }),
        ],
      ),
    );
    await _toggle(tester);
    final food = _foodOf(tester, _reasoningBody);
    final before = tester.getSize(_reasoningBody);
    expect(food.widget.onErase, isNull, reason: 'an expanded bite must not consume the whole hidden section');
    // The reasoning, header and body, is one food: the answer beside it is not.
    expect(find.ancestor(of: find.text(_answer), matching: _edible), findsNothing);

    await _bite(tester, food, stage, tester.getCenter(_reasoningBody));
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
    expect(tester.getSize(_reasoningBody), before);
    expect(_foodOf(tester, _reasoningBody), same(food));
    // There are still other glyphs at their original positions after the bite.
    await _bite(tester, food, stage, tester.getCenter(_reasoningBody));

    await tester.tap(find.text('翻译'));
    await pumpFrames(tester, 4);
    await tester.pumpAndSettle();
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, '$_translation\n\n$_translation');
    expect(translated, hasLength(2));
    final translatedInk = await _ink(tester, stage);
    await _eraseAll(tester, _foodOf(tester, _reasoningBody), stage);
    expect(await _ink(tester, stage), lessThan(translatedInk));
    await _toggle(tester);
    await _eraseAll(tester, _foodOf(tester, find.text('思考')), stage);
    await _toggle(tester);
    await tester.pumpAndSettle();
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, '$_translation\n\n$_translation');
    expect(await _ink(tester, stage), translatedInk);
    expect(translated, hasLength(2), reason: 'restoring the view does not request the same translation again');

    await tester.tap(find.text('查看原文'));
    await tester.pumpAndSettle();
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
    final originalInk = await _ink(tester, stage);
    final originalFood = _foodOf(tester, _reasoningBody);
    await _eraseAll(tester, originalFood, stage);
    await tester.tap(find.text('查看译文'));
    await tester.pumpAndSettle();
    expect(await _ink(tester, stage), translatedInk);
    await tester.tap(find.text('查看原文'));
    await tester.pumpAndSettle();
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
    expect(await _ink(tester, stage), originalInk);
    // Switching views keeps the same thought slot; what was eaten in the
    // other view never leaks into this one.
    expect(translated, hasLength(2));
  });

  testWidgets('streaming keeps the full reasoning recoverable and commit still collapses the body', (tester) async {
    final registry = _registry(tester);
    final stage = GlobalKey();
    final item = ValueNotifier(
      const AssistantChatItem(id: 'draft', rowKey: 'm1.1', text: '', reasoning: _reasoning, streaming: true),
    );
    addTearDown(item.dispose);
    await tester.pumpWidget(
      _scene(
        ValueListenableBuilder(
          valueListenable: item,
          builder: (context, value, _) => AssistantMessage(item: value),
        ),
        registry,
        stage,
      ),
    );
    await pumpFrames(tester, 2);
    expect(find.byType(ThinkingTicker), findsOneWidget);
    final summary = _foodOf(tester, find.text('思考中'));
    await _bite(tester, summary, stage, tester.getCenter(find.text('思考中')));
    await _toggle(tester, active: true);
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);

    const suffix = 'A newly streamed thought.';
    item.value = const AssistantChatItem(
      id: 'draft',
      rowKey: 'm1.1',
      text: '',
      reasoning: '$_reasoning\n\n$suffix',
      streaming: true,
    );
    await pumpFrames(tester, 2);
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, '$_reasoning\n\n$suffix');
    final pill = tester.state(find.byType(ThinkingPill));
    item.value = const AssistantChatItem(id: 'a20', rowKey: 'm1.1', text: _answer, reasoning: '$_reasoning\n\n$suffix');
    await pumpFrames(tester, 5);
    expect(tester.state(find.byType(ThinkingPill)), same(pill));
    expect(_reasoningBody, findsNothing, reason: 'committing still folds manually expanded reasoning');
    await _toggle(tester);
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, '$_reasoning\n\n$suffix');

    // A different message in the same parent must not inherit this meal.
    item.value = const AssistantChatItem(id: 'a21', text: _answer, reasoning: _reasoning);
    await pumpFrames(tester, 2);
    await _toggle(tester);
    expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
  });

  for (final reopenDuringCollapse in [false, true]) {
    testWidgets('reopening erased text restores paint (during collapse: $reopenDuringCollapse)', (tester) async {
      final registry = _registry(tester);
      final stage = GlobalKey();
      await tester.pumpWidget(_scene(const ThinkingPill(reasoning: _reasoning), registry, stage));
      await _toggle(tester);
      await tester.pumpAndSettle();
      final food = _foodOf(tester, _reasoningBody);
      final size = tester.getSize(_reasoningBody);
      final before = await _ink(tester, stage);
      await _eraseAll(tester, food, stage);
      expect(tester.getSize(_reasoningBody), size);
      expect(await _ink(tester, stage), lessThan(before));

      // Collapse through the body gesture; reopen through the header.
      await tester.tapAt(tester.getCenter(_reasoningBody));
      await tester.pump();
      if (reopenDuringCollapse) {
        expect(food.mounted, isTrue, reason: 'the previous mask still exists during the closing animation');
      } else {
        await pumpFrames(tester, 4);
      }
      await _toggle(tester);
      await tester.pumpAndSettle();
      expect(tester.widget<MarkdownBody>(_reasoningBody).text, _reasoning);
      expect(tester.getSize(_reasoningBody), size);
      expect(_foodOf(tester, _reasoningBody), isNot(same(food)));
      expect(food.mounted, isFalse);

      final box = stage.currentContext!.findRenderObject()! as RenderBox;
      expect(food.eraseAlong(box, Offset.zero, box.size.bottomRight(Offset.zero), radius: 10000).count, 0);
      await pumpFrames(tester, 4);
      expect(await _ink(tester, stage), before, reason: 'restored glyphs stay painted after stale erasure attempts');
    });
  }
}
