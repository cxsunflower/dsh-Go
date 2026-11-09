// Code snacks on the chat page (docs/design/naiwa-pet.md §7): the 5×7 pixel
// font, what the pet eats (the reasoning being written, masked, else the command
// or the jokes), and the flights: one take-off per `every`, at most three in the
// air, a bite at the mouth; a reply only from where eating started, no more
// than 48 behind, a text round and round; nothing flies or ticks when it is
// not eating, animations are off, the page is under another or the app is out
// of sight, and the timer stops once the last crumb has fallen.

import 'dart:math' as math;

import 'package:dsh_app/state/chat_state.dart';
import 'package:dsh_app/ui/chat/run_info.dart';
import 'package:dsh_app/ui/pets/pet_snack.dart';
import 'package:dsh_app/ui/pets/pixel_font.dart';
import 'package:dsh_client/dsh_client.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

var bites = 0;

Widget layer({
  bool active = true,
  int every = 300,
  SnackText text = const SnackText('ab'),
  SnackText fallback = const SnackText(''),
  ({int char, Offset from})? Function()? takeGlyph,
  bool reduced = false,
  bool ticking = true,
}) => MediaQuery(
  data: MediaQueryData(disableAnimations: reduced),
  child: TickerMode(
    enabled: ticking,
    child: Center(
      child: PetSnackLayer(
        anim: 'eat-code',
        scale: 1,
        active: active,
        every: every,
        mouth: const Offset(33, 31),
        launch: const [Rect.fromLTRB(-120, -20, -10, 10), Rect.fromLTRB(80, -20, 180, 10)],
        text: text,
        fallback: fallback,
        takeGlyph: takeGlyph,
        onBite: () => bites++,
      ),
    ),
  ),
);

/// Reply [id] as written so far: [text], all of it ready to eat.
SnackText reply(String text, {String id = 'r1'}) => SnackText(text, reply: id, end: text.length);

PetSnackLayerState snack(WidgetTester tester) => tester.state<PetSnackLayerState>(find.byType(PetSnackLayer));

void hideApp(WidgetTester tester) {
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
}

void showApp(WidgetTester tester) {
  if (tester.binding.lifecycleState == AppLifecycleState.hidden) {
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  }
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
}

void main() {
  setUp(() {
    bites = 0;
    PetSnackLayer.random = math.Random(7);
  });

  group('pixel font', () {
    test('every printable ASCII character has a glyph of 5 columns × 7 rows', () {
      for (var c = 0x21; c <= 0x7E; c++) {
        final char = String.fromCharCode(c);
        final glyph = PixelFont.glyph(c);
        expect(glyph, hasLength(PixelFont.width), reason: char);
        expect(glyph!.every((column) => column >= 0 && column < 1 << PixelFont.height), isTrue, reason: char);
        expect(glyph.any((column) => column != 0), isTrue, reason: char);
      }
    });

    test('no two glyphs alike', () {
      final seen = <String>{};
      for (var c = 0x21; c <= 0x7E; c++) {
        expect(seen.add(PixelFont.glyph(c)!.join(',')), isTrue, reason: String.fromCharCode(c));
      }
    });

    test('blanks, control characters and anything past ASCII have none', () {
      for (final c in [0x00, 0x09, 0x0A, 0x20, 0x7F, 0xE9, '中'.codeUnitAt(0), '😀'.codeUnitAt(0)]) {
        expect(PixelFont.glyph(c), isNull, reason: '0x${c.toRadixString(16)}');
      }
    });
  });

  group('what it eats', () {
    test('the command on the run strip, its secrets masked', () {
      const command = 'curl -H "Authorization: Bearer sk-0123456789abcdef0123456789abcdef" https://x';
      final text = petSnackText(
        const RunActivity(kind: ActivityKind.tool, title: '运行命令', detail: command, detailIsCode: true),
      );
      expect(text, startsWith('curl -H'));
      expect(text, isNot(contains('sk-0123456789abcdef0123456789abcdef')));
    });

    test('the jokes otherwise: nothing runs, the detail is no code, or none of it can be drawn', () {
      final jokes = petSnackJokes.join(' ');
      expect(petSnackText(null), jokes);
      expect(petSnackText(const RunActivity(kind: ActivityKind.thinking, title: '思考', detail: 'x = 1')), jokes);
      expect(
        petSnackText(const RunActivity(kind: ActivityKind.tool, title: '读取', detail: ' 😀 ', detailIsCode: true)),
        jokes,
      );
      expect(jokes.codeUnits.every((c) => c == 0x20 || PixelFont.glyph(c) != null), isTrue);
    });

    test('a command in Chinese is eaten too', () {
      expect(
        petSnackText(const RunActivity(kind: ActivityKind.tool, title: '读取', detail: '说明 文档', detailIsCode: true)),
        '说明 文档',
      );
    });

    test('drawable: ASCII and Chinese; not blanks, marks, zero-width characters or emoji', () {
      for (final c in ['a', ';', '中', '～', '？', '，']) {
        expect(petSnackDrawable(c.codeUnitAt(0)), isTrue, reason: c);
      }
      for (final c in [0x20, 0x09, 0x0A, 0xA0, 0x0301, 0x200B, 0x2028, 0x3000, 0xFE0F, 0xFEFF, '😀'.codeUnitAt(0)]) {
        expect(petSnackDrawable(c), isFalse, reason: '0x${c.toRadixString(16)}');
      }
    });

    test('a reply up to its last blank: what follows may still grow into a key', () {
      final s = SnackText.ofReply('d1', 'run curl sk-0123');
      expect(s.reply, 'd1');
      expect(s.end, 9);
      expect(s.text, 'run curl ');
    });

    test('a reply masked, its last 256 code units kept', () {
      const key = 'sk-0123456789abcdef0123456789abcdef';
      const text = 'export KEY=$key\n';
      final masked = SnackText.ofReply('d1', text);
      expect(masked.end, text.length);
      expect(masked.text, hasLength(text.length));
      expect(masked.text, startsWith('export KEY=sk-'));
      expect(masked.text, isNot(contains(key)));

      final long = SnackText.ofReply('d1', '${'x' * 300} ');
      expect(long.end, 301);
      expect(long.text, '${'x' * 255} ');
    });

    test('a secret that masking shortens (a surrogate pair is one mark) still lines up from the end', () {
      const text = 'see https://u:p😀ss@host ';
      final s = SnackText.ofReply('d1', text);
      expect(s.end, text.length);
      expect(s.text, endsWith('@host '));
      expect(s.text, isNot(contains('ss@')));
    });

    test('in a conversation: only the reasoning; a reply without one leaves the command or jokes', () {
      const writing = AssistantChatItem(id: 'd1', text: 'Hello there', reasoning: '', streaming: true);
      final s = petSnackOf(const ChatState(items: [writing], running: true));
      expect(s.reply, isNull, reason: 'the answer itself is never eaten');

      const done = AssistantChatItem(id: 'a1', text: 'Hello there', reasoning: '');
      expect(petSnackOf(const ChatState(items: [done])).reply, isNull);

      const call = ToolChatItem(
        callId: 'c1',
        name: 'bash',
        arguments: '{"command":"ls"}',
        status: ToolStatus.running,
      );
      expect(petSnackOf(const ChatState(items: [writing, call])).reply, isNull);
    });

    test('its reasoning under a name of its own, even once the answer starts', () {
      const reasoning = AssistantChatItem(id: 'd1', text: '', reasoning: 'The user said hi ', streaming: true);
      expect(
        petSnackOf(const ChatState(items: [reasoning], running: true)),
        const SnackText('The user said hi ', reply: 'd1/reasoning', end: 17),
      );
      const writing = AssistantChatItem(id: 'd1', text: '嗨～', reasoning: 'The user said hi ', streaming: true);
      expect(
        petSnackOf(const ChatState(items: [writing], running: true)),
        const SnackText('The user said hi ', reply: 'd1/reasoning', end: 17),
      );
      const waiting = AssistantChatItem(id: 'd1', text: '', reasoning: '', streaming: true);
      expect(petSnackOf(const ChatState(items: [waiting], running: true)).reply, isNull);
    });
  });

  group('eating a reply', () {
    testWidgets('only what is written after it starts, never from the top again', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: reply('hello ')));
      await tester.pump(const Duration(milliseconds: 500));
      expect(snack(tester).launched, 0, reason: 'written before it started');
      await tester.pumpWidget(layer(every: 1, text: reply('hello wor')));
      await tester.pump(const Duration(milliseconds: 500));
      expect(snack(tester).aloft, 'wor');
      await tester.pumpWidget(layer(every: 1, text: reply('hello world ')));
      await tester.pump(const Duration(seconds: 6));
      expect(snack(tester).launched, greaterThanOrEqualTo(5));
    });

    testWidgets('Chinese flies too, drawn from the font', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: reply('')));
      await tester.pumpWidget(layer(every: 1, text: reply('你好，世界')));
      await tester.pump(const Duration(seconds: 6));
      expect(snack(tester).launched, greaterThanOrEqualTo(5), reason: 'each character takes its own slow turn');
    });

    testWidgets('far ahead: no more than 48 behind, the rest skipped', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: reply('')));
      final burst = String.fromCharCodes([for (var i = 0; i < 100; i++) 0x41 + i % 26]);
      await tester.pumpWidget(layer(every: 1, text: reply(burst)));
      for (var i = 0; i < 720; i++) {
        await tester.pump(PetSnackLayer.step);
      }
      expect(snack(tester).launched, PetSnackLayer.backlog);
    });

    testWidgets('another reply: only what it writes from then', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: reply('abc')));
      await tester.pumpWidget(layer(every: 1, text: reply('abcdef')));
      await tester.pump(const Duration(seconds: 4));
      expect(snack(tester).launched, greaterThanOrEqualTo(3));
      await tester.pumpWidget(layer(every: 1, text: reply('xyz', id: 'r2')));
      await tester.pump(const Duration(seconds: 4));
      expect(snack(tester).launched, 3);
      await tester.pumpWidget(layer(every: 1, text: reply('xyz12', id: 'r2')));
      await tester.pump(const Duration(seconds: 4));
      expect(snack(tester).launched, 5);
    });

    testWidgets('only its last stretch is passed: what is new at the end', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: const SnackText('wxyz', reply: 'r1', end: 1000)));
      await tester.pumpWidget(layer(every: 1, text: const SnackText('yz12', reply: 'r1', end: 1002)));
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, greaterThanOrEqualTo(2));
    });

    testWidgets('switched on again (after a run): only what is written from then', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: reply('ab')));
      await tester.pumpWidget(layer(active: false, every: 1, text: reply('abcd')));
      await tester.pumpWidget(layer(every: 1, text: reply('abcde')));
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, 0);
      await tester.pumpWidget(layer(every: 1, text: reply('abcdef')));
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, 1);
    });

    testWidgets('a text round and round: in order, from the top again at its end', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: const SnackText('a b')));
      await tester.pump(const Duration(seconds: 5));
      expect(snack(tester).launched, greaterThanOrEqualTo(4));
    });
  });

  group('flights', () {
    testWidgets('nothing within reach at the mouth: the joke falls back in, round and round', (tester) async {
      await tester.pumpWidget(
        layer(every: 100, text: reply(''), takeGlyph: () => null, fallback: const SnackText('ab')),
      );
      await tester.pump(const Duration(seconds: 5));
      expect(snack(tester).launched, greaterThanOrEqualTo(4));
    });

    testWidgets('an empty fallback stays quiet when nothing is within reach', (tester) async {
      await tester.pumpWidget(
        layer(every: 100, text: reply(''), takeGlyph: () => null, fallback: const SnackText('')),
      );
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, 0);
    });

    testWidgets('the chat page slows a pack to at least 1200 ms a bite; one glyph at a time', (tester) async {
      expect(PetSnackLayer.slowestEvery, 1200);
      await tester.pumpWidget(layer(every: PetSnackLayer.slowestEvery));
      final state = snack(tester);
      expect(state.running, isTrue);
      expect(state.launched, 0);
      // Steps of 1/12 s: the first take-off at 83 ms, the second at 1283 ms.
      await tester.pump(const Duration(milliseconds: 100));
      expect(state.launched, 1);
      await tester.pump(const Duration(milliseconds: 1100));
      expect(state.launched, 1, reason: 'the next glyph waits a full 1200 ms');
      await tester.pump(const Duration(milliseconds: 200));
      expect(state.launched, 2);
    });

    testWidgets('at the mouth a glyph vanishes with a bite; its crumbs fall, then the timer stops', (tester) async {
      await tester.pumpWidget(layer(every: 5000));
      await tester.pump(const Duration(milliseconds: 100));
      final state = snack(tester);
      expect(state.flying, 1);
      // No more take-offs; this one flies 700–1000 ms from 83 ms.
      await tester.pumpWidget(layer(active: false, every: 5000));
      await tester.pump(const Duration(milliseconds: 1000));
      expect(state.flying, 0);
      expect(state.bites, 1);
      expect(bites, 1);
      expect(state.crumbs, inInclusiveRange(2, 3));
      expect(state.running, isTrue);
      await tester.pump(const Duration(milliseconds: 400));
      expect(state.crumbs, 0);
      expect(state.running, isFalse);
    });

    testWidgets('never more than three in the air', (tester) async {
      await tester.pumpWidget(layer(every: 1));
      final state = snack(tester);
      var most = 0;
      for (var i = 0; i < 40; i++) {
        await tester.pump(PetSnackLayer.step);
        expect(state.flying, lessThanOrEqualTo(PetSnackLayer.maxFlying));
        most = math.max(most, state.flying);
      }
      expect(most, PetSnackLayer.maxFlying);
      expect(PetSnackLayer.maxFlying, 3);
    });

    testWidgets('switched off: those in the air land, no more take off, then nothing ticks', (tester) async {
      await tester.pumpWidget(layer(every: 200));
      await tester.pump(const Duration(milliseconds: 700));
      final state = snack(tester);
      final launched = state.launched;
      expect(launched, greaterThan(1));
      expect(state.flying, launched);
      await tester.pumpWidget(layer(active: false, every: 200));
      expect(state.running, isTrue);
      await tester.pump(const Duration(seconds: 2));
      expect(state.launched, launched);
      expect(state.flying, 0);
      expect(state.crumbs, 0);
      expect(state.bites, launched);
      expect(bites, launched);
      expect(state.running, isFalse);
    });

    testWidgets('not eating: nothing takes off and nothing ticks', (tester) async {
      await tester.pumpWidget(layer(active: false));
      expect(snack(tester).running, isFalse);
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, 0);
    });

    testWidgets('animations off, or the page under another: nothing flies and nothing ticks', (tester) async {
      await tester.pumpWidget(layer(reduced: true));
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, 0);
      expect(snack(tester).running, isFalse);

      await tester.pumpWidget(layer(ticking: false));
      await tester.pump(const Duration(seconds: 2));
      expect(snack(tester).launched, 0);
      expect(snack(tester).running, isFalse);

      // Turned off mid-meal: what was in the air goes at once.
      await tester.pumpWidget(layer());
      await tester.pump(const Duration(milliseconds: 400));
      expect(snack(tester).flying, greaterThan(0));
      await tester.pumpWidget(layer(reduced: true));
      expect(snack(tester).flying, 0);
      expect(snack(tester).running, isFalse);
    });

    testWidgets('the app out of sight: the air clears and nothing ticks; back, it eats again', (tester) async {
      showApp(tester);
      addTearDown(() => showApp(tester));
      await tester.pumpWidget(layer());
      await tester.pump(const Duration(milliseconds: 400));
      final state = snack(tester);
      expect(state.flying, greaterThan(0));
      hideApp(tester);
      expect(state.flying, 0);
      expect(state.running, isFalse);
      showApp(tester);
      expect(state.running, isTrue);
    });

    testWidgets('blanks and emoji are skipped: such a text never takes off', (tester) async {
      await tester.pumpWidget(layer(every: 1, text: const SnackText(' 😀\u3000\n')));
      await tester.pump(const Duration(seconds: 1));
      expect(snack(tester).launched, 0);
    });
  });
}
