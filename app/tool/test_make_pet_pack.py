#!/usr/bin/env python3
"""Checks the pet packs in assets/pets/ against their source art and the pack format.

Run from app/ (Pillow and numpy; ffmpeg, if installed, decodes the APNGs independently):

    python3 -I tool/test_make_pet_pack.py

The source art is in tool/pet_src (the tool's default `--src`); the source comparisons
and the rebuild check fail, not skip, when it is missing. The sprite source format is
checked on a tiny pet drawn here into a temporary directory.
Format: docs/design/pets.md section 3.
"""
import contextlib
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from unittest import mock

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_pet_pack as tool  # noqa: E402

APP = os.path.dirname(HERE)
PETS = os.path.join(APP, 'assets', 'pets')
SRC = tool.DEFAULT_SRC
IDS = ['deepy-whale', 'whale-girl', 'naiwa']
STATES = ['idle', 'thinking', 'working', 'juggling', 'error', 'attention', 'notification',
          'sweeping', 'carrying', 'sleeping', 'waking', 'roam']
REACTIONS = ['tapLeft', 'tapRight', 'tickle', 'drag']
# Animations that legitimately leave the baseline: lifted by the user, or in water.
OFF_GROUND = {'deepy-whale': {'react-drag'}, 'whale-girl': {'swim'}, 'naiwa': set()}
MAX_DIP = 2               # logical px a tilt / squash / bob may go below the baseline
MAX_SHEET = 4096


def load(pid):
    d = os.path.join(PETS, pid)
    with open(os.path.join(d, 'pack.json'), encoding='utf-8') as fh:
        return json.load(fh), d


def rgba(path):
    with Image.open(path) as im:
        return np.asarray(im.convert('RGBA'))


def norm(a):
    a = np.array(a, dtype=np.uint8, copy=True)
    a[a[..., 3] == 0] = 0
    return a


def expand(pack, d, name):
    """Full-canvas frames of one animation, rebuilt from pack.json + sheet (own code, not the tool's)."""
    a, s = pack['animations'][name], pack['scale']
    sheet = rgba(os.path.join(d, a['sheet']))
    H, W = pack['canvas']['h'] * s, pack['canvas']['w'] * s
    bx, by = a['box']['x'] * s, a['box']['y'] * s
    out = []
    for f in a['frames']:
        r, c = divmod(f['i'], a['cols'])
        frame = np.zeros((H, W, 4), np.uint8)
        frame[by:by + a['frameH'], bx:bx + a['frameW']] = \
            sheet[r * a['frameH']:(r + 1) * a['frameH'], c * a['frameW']:(c + 1) * a['frameW']]
        out.append(frame)
    return out


def referenced(pack):
    names = set()
    for v in pack['states'].values():
        names.update(v)
    for v in pack['tiers'].values():
        names.update(t['anim'] for t in v)
    names.update(pack['reactions'].values())
    names.add(pack['roam']['anim'])
    names.update(x['anim'] for x in pack['idlePool']['anims'])
    for b in pack['bonus'].values():
        names.update(b['anims'])
    return names


def hit_box_of(pack, name):
    h = pack['hitBoxes']
    if name in h['byAnim']:
        return h['byAnim'][name]
    if name in h['sleepingAnims']:
        return h['sleeping']
    if name in h['wideAnims']:
        return h['wide']
    return h['default']


def body_grid(f, s):
    """Largest 8-connected blob of opaque logical cells (own flood fill, not the tool's)."""
    H, W = f.shape[0] // s, f.shape[1] // s
    g = (f[..., 3] >= 128).reshape(H, s, W, s).any(axis=(1, 3))
    label = np.zeros((H, W), int)
    sizes = [0]
    for y in range(H):
        for x in range(W):
            if g[y, x] and not label[y, x]:
                n = len(sizes)
                label[y, x] = n
                todo, size = [(y, x)], 0
                while todo:
                    cy, cx = todo.pop()
                    size += 1
                    for ny in range(max(cy - 1, 0), min(cy + 2, H)):
                        for nx in range(max(cx - 1, 0), min(cx + 2, W)):
                            if g[ny, nx] and not label[ny, nx]:
                                label[ny, nx] = n
                                todo.append((ny, nx))
                sizes.append(size)
    return label == int(np.argmax(sizes)) if len(sizes) > 1 else g


def body_occupancy(pack, d, name):
    """Per logical cell: the share of the animation's time it is body."""
    a, s = pack['animations'][name], pack['scale']
    occ, memo = None, {}
    for f, fr in zip(expand(pack, d, name), a['frames']):
        if fr['i'] not in memo:
            memo[fr['i']] = body_grid(f, s).astype(float)
        occ = memo[fr['i']] * fr['ms'] if occ is None else occ + memo[fr['i']] * fr['ms']
    return occ / a['ms']


def inside(b, outer):
    return (outer['x'] <= b['x'] and outer['y'] <= b['y'] and b['x'] + b['w'] <= outer['x'] + outer['w']
            and b['y'] + b['h'] <= outer['y'] + outer['h'])


def lowest_opaque_edge(f, scale):
    ys = np.nonzero((f[..., 3] >= 128).any(axis=1))[0]
    return (int(ys[-1]) + 1) / scale


def neighbours(m):
    o = np.zeros_like(m)
    o[1:] |= m[:-1]
    o[:-1] |= m[1:]
    o[:, 1:] |= m[:, :-1]
    o[:, :-1] |= m[:, 1:]
    return o


def fctl_delays(path):
    with open(path, 'rb') as fh:
        data = fh.read()
    p, out = 8, []
    while p < len(data):
        (n,) = struct.unpack('>I', data[p:p + 4])
        if data[p + 4:p + 8] == b'fcTL':
            num, den = struct.unpack('>HH', data[p + 8 + 20:p + 8 + 24])
            out.append(1000 * num / (den or 100))
        p += 12 + n
    return out


def ffmpeg_frames(path, w, h):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'rgba',
                          '-fps_mode', 'passthrough', '-'], check=True, capture_output=True).stdout
    n = len(raw) // (w * h * 4)
    return [norm(x) for x in np.frombuffer(raw, np.uint8).reshape(n, h, w, 4)]


def pillow_frames(path):
    out = []
    with Image.open(path) as im:
        for i in range(getattr(im, 'n_frames', 1)):
            im.seek(i)
            out.append(norm(np.asarray(im.convert('RGBA'))))
    return out


HAVE_FFMPEG = shutil.which('ffmpeg') is not None


class PackFormat(unittest.TestCase):
    def test_fields(self):
        for pid in IDS:
            p, _ = load(pid)
            with self.subTest(pid):
                self.assertEqual(p['schema'], 1)
                self.assertEqual(p['id'], pid)
                for k in ('name', 'author', 'license', 'source'):
                    self.assertIsInstance(p[k], str)
                    self.assertTrue(p[k])
                self.assertIs(p['pixelArt'], True)
                self.assertIsInstance(p['scale'], int)
                self.assertGreaterEqual(p['scale'], 1)
                cw, ch = p['canvas']['w'], p['canvas']['h']
                self.assertTrue(isinstance(cw, int) and isinstance(ch, int))
                self.assertEqual(list(p['states']), STATES)
                self.assertEqual(sorted(p['reactions']), sorted(REACTIONS))
                for s, ts in p['tiers'].items():
                    self.assertIn(s, STATES)
                    mins = [t['min'] for t in ts]
                    self.assertEqual(mins, sorted(mins, reverse=True))
                    self.assertGreaterEqual(mins[-1], 1)
                self.assertEqual(sorted(p['tiers']), ['juggling', 'working'])
                for group in ('minDisplay', 'autoReturn'):
                    for s, ms in p['timings'][group].items():
                        self.assertIn(s, STATES)
                        self.assertTrue(isinstance(ms, int) and ms > 0)
                self.assertNotIn('notification', p['timings']['autoReturn'], 'notification holds')
                self.assertIn('notification', p['timings']['minDisplay'])
                self.assertEqual(p['timings']['wakeMs'], p['animations'][p['states']['waking'][0]]['ms'])
                self.assertEqual(sorted(p['timings']), ['autoReturn', 'minDisplay', 'wakeMs'])
                self.assertIn(sorted(p['roam']), (['anim', 'faces'], ['anim', 'faces', 'free']))
                self.assertIn(p['roam']['faces'], ('left', 'right', 'front'))
                self.assertIs(p['roam'].get('free', True), True, 'roam.free is only written as true')
                if 'drag' in p:
                    self.assertEqual(p['drag'], {'mirror': True}, 'drag.mirror is only written as true')
                self.assertEqual(p['sleep']['afterMs'], 60000)
                self.assertEqual(len(p['states']['idle']), 1, 'idle fidgets live in idlePool')
                pool = p['idlePool']
                self.assertEqual(pool['everyMs'], {'mean': 120000, 'min': 45000, 'max': 300000})
                self.assertTrue(pool['anims'])
                for x in pool['anims']:
                    self.assertEqual(sorted(x), ['anim', 'ms', 'weight'])
                    self.assertNotEqual(x['anim'], p['states']['idle'][0])
                    self.assertGreater(x['weight'], 0)
                    self.assertEqual(x['ms'] % p['animations'][x['anim']]['ms'], 0, 'whole loops')
                for st, b in p['bonus'].items():
                    self.assertIn(st, STATES)
                    self.assertTrue(b['anims'])
                    self.assertTrue(0 < b['chance'] < 1)
                    for n in b['anims']:
                        self.assertNotIn(n, p['states'][st], 'a bonus is not the state animation')
                cb = p['contentBox']
                self.assertTrue(0 <= cb['x'] and cb['x'] + cb['w'] <= cw)
                self.assertTrue(0 <= cb['y'] and cb['y'] + cb['h'] <= ch)
                self.assertTrue(cb['x'] <= p['anchor']['x'] <= cb['x'] + cb['w'])
                self.assertTrue(cb['y'] < p['anchor']['baseline'] <= cb['y'] + cb['h'])

    def test_metadata(self):
        """Both pets are DSH-TUI mascots, used with the author's permission."""
        want = {
            'deepy-whale': ('Deepy 小鲸鱼', 'DSH-TUI（Clawd on Desk 主题包 v1.0.0）'),
            'whale-girl': ('鲸娘', 'https://dshtui.com/pets/whale-girl-emoji/'),
        }
        for pid, (name, source) in want.items():
            p, d = load(pid)
            with self.subTest(pid):
                self.assertEqual(p['name'], name)
                self.assertEqual(p['author'], 'DSH-TUI')
                self.assertEqual(p['license'], 'DSH-TUI 吉祥物，作者授权 dsh-go 使用')
                self.assertEqual(p['source'], source)
                self.assertNotIn('sizeScale', p)
                self.assertNotIn('free', p['roam'])
                with open(os.path.join(d, 'pack.json'), encoding='utf-8') as fh:
                    self.assertNotIn('非官方', fh.read())

    def test_naiwa_metadata(self):
        """The naiwa pets are redrawn after a fan-made character: unofficial, and they say so."""
        for pid, name in (('naiwa', '奶蛙'),):
            p, _ = load(pid)
            with self.subTest(pid):
                self.assertEqual(p['name'], name)
                self.assertEqual(p['author'], 'github.com/cxsunflower')
                self.assertEqual(p['license'], tool.PACKS[pid]['license'])
                self.assertEqual(p['source'], tool.PACKS[pid]['source'])
                self.assertIn('非官方', p['license'])
                self.assertEqual(p['sounds'], 'naiwa')
                self.assertNotIn('sizeScale', p)
                self.assertIs(p['roam']['free'], True)
                self.assertEqual(p['drag'], {'mirror': True}, 'Naiwa turns left when dragged left')
                self.assertEqual(p['reactions']['drag'], 'prone-eat')
                self.assertIn('prone-eat', p['snack']['every'])
                self.assertIn('prone-eat', p['snack']['mouths'])
                self.assertTrue(os.path.isfile(os.path.join(APP, 'assets', 'pet_sounds', 'naiwa', 'sounds.json')))

    def test_every_reference_exists_and_every_animation_is_used(self):
        for pid in IDS:
            p, d = load(pid)
            with self.subTest(pid):
                refs = referenced(p)
                self.assertEqual(refs - set(p['animations']), set(), 'missing animations')
                self.assertEqual(set(p['animations']) - refs, set(), 'unused animations')
                for s in STATES:
                    self.assertTrue(p['states'][s], s)
                sheets = {a['sheet'] for a in p['animations'].values()}
                for f in sheets:
                    self.assertTrue(os.path.isfile(os.path.join(d, f)), f)
                stray = {f for f in os.listdir(d) if f != 'pack.json'} - sheets
                self.assertEqual(stray, set(), 'files nothing refers to')

    def test_frame_geometry(self):
        for pid in IDS:
            p, d = load(pid)
            s, cw, ch = p['scale'], p['canvas']['w'], p['canvas']['h']
            for name, a in p['animations'].items():
                with self.subTest(pid=pid, anim=name):
                    box = a['box']
                    self.assertTrue(all(isinstance(box[k], int) for k in 'xywh'))
                    self.assertTrue(0 <= box['x'] and box['x'] + box['w'] <= cw)
                    self.assertTrue(0 <= box['y'] and box['y'] + box['h'] <= ch)
                    self.assertEqual(a['frameW'], box['w'] * s)
                    self.assertEqual(a['frameH'], box['h'] * s)
                    idx = [f['i'] for f in a['frames']]
                    cells = max(idx) + 1
                    self.assertEqual(set(idx), set(range(cells)), 'every stored cell is played')
                    rows = math.ceil(cells / a['cols'])
                    self.assertLessEqual(a['cols'], cells)
                    with Image.open(os.path.join(d, a['sheet'])) as im:
                        w, h = im.size
                    self.assertEqual((w, h), (a['cols'] * a['frameW'], rows * a['frameH']))
                    self.assertLessEqual(max(w, h), MAX_SHEET)
                    self.assertTrue(all(isinstance(f['ms'], int) and f['ms'] > 0 for f in a['frames']))
                    self.assertEqual(a['ms'], sum(f['ms'] for f in a['frames']))
                    self.assertIsInstance(a['loop'], bool)

    def test_transparency(self):
        for pid in IDS:
            p, d = load(pid)
            for name, a in p['animations'].items():
                with self.subTest(pid=pid, anim=name):
                    with Image.open(os.path.join(d, a['sheet'])) as im:
                        mode, info = im.mode, dict(im.info)
                    self.assertTrue(mode == 'RGBA' or (mode == 'P' and 'transparency' in info),
                                    f'{a["sheet"]} has no alpha ({mode})')
                    sheet = rgba(os.path.join(d, a['sheet']))
                    clear = sheet[..., 3] == 0
                    self.assertFalse(sheet[clear][:, :3].any(), 'transparent pixels must be 0,0,0,0')
                    # grid padding after the last cell stays empty
                    cells = max(f['i'] for f in a['frames']) + 1
                    for i in range(cells, math.ceil(cells / a['cols']) * a['cols']):
                        r, c = divmod(i, a['cols'])
                        pad = sheet[r * a['frameH']:(r + 1) * a['frameH'], c * a['frameW']:(c + 1) * a['frameW']]
                        self.assertFalse(pad.any())
                    for k, f in enumerate(expand(p, d, name)):
                        al = f[..., 3]
                        self.assertGreater((al == 0).mean(), 0.5, f'frame {k}: background is not transparent')
                        semi = (al > 0) & (al < 255)
                        rgb = f[..., :3].astype(int)
                        self.assertFalse((semi & (rgb.max(-1) <= 20)).any(), f'frame {k}: dark fringe')
                        # A matte fringe is the anti-aliased rim of opaque art (touching both
                        # opaque and clear pixels) blended toward white. Authored pure-white
                        # glows and pale particles away from the body are fine.
                        rim = semi & neighbours(al == 255) & neighbours(al == 0)
                        pale = (rgb.min(-1) >= 235) & ~(rgb == 255).all(-1)
                        self.assertFalse((rim & pale).any(), f'frame {k}: light fringe')
                        if pid != 'deepy-whale':    # Deepy's shadow is the one semi-transparent art
                            self.assertFalse(semi.any(), 'pixel art: alpha is 0 or 255')

    def test_hit_boxes(self):
        for pid in IDS:
            p, d = load(pid)
            h, cw, ch = p['hitBoxes'], p['canvas']['w'], p['canvas']['h']
            canvas = {'x': 0, 'y': 0, 'w': cw, 'h': ch}
            with self.subTest(pid):
                self.assertEqual(sorted(h), ['byAnim', 'default', 'sleeping', 'sleepingAnims', 'wide',
                                             'wideAnims'])
                for b in [h['default'], h['wide'], h['sleeping']] + list(h['byAnim'].values()):
                    self.assertTrue(all(isinstance(b[k], int) for k in 'xywh'))
                    self.assertTrue(inside(b, canvas))
                self.assertTrue(inside(h['default'], h['wide']))
                listed = h['wideAnims'] + h['sleepingAnims'] + list(h['byAnim'])
                self.assertEqual(len(listed), len(set(listed)), 'an animation is in one class')
                self.assertEqual(set(listed) - set(p['animations']), set())
                self.assertNotIn(p['states']['idle'][0], listed)
                self.assertEqual(h['sleepingAnims'], p['states']['sleeping'])
                # default is the idle body: the cells that are body a quarter of the time or more
                occ = body_occupancy(p, d, p['states']['idle'][0])
                ys, xs = np.nonzero(occ >= 0.25)
                self.assertEqual(h['default'], {'x': int(xs.min()), 'y': int(ys.min()),
                                                'w': int(xs.max() - xs.min() + 1),
                                                'h': int(ys.max() - ys.min() + 1)})
            for name in p['animations']:
                with self.subTest(pid=pid, anim=name):
                    occ = body_occupancy(p, d, name)
                    b = hit_box_of(p, name)
                    caught = occ[b['y']:b['y'] + b['h'], b['x']:b['x'] + b['w']].sum() / occ.sum()
                    self.assertGreaterEqual(caught, 0.9, 'the box misses the body')
                    # a box no bigger than this animation's own visible extent, give or take a pixel
                    a = p['animations'][name]['box']
                    if name not in h['wideAnims']:
                        grown = {'x': a['x'] - 1, 'y': a['y'] - 1, 'w': a['w'] + 2, 'h': a['h'] + 2}
                        self.assertTrue(inside(b, grown), f'{b} is larger than the art {a}')

    def test_scale_is_needed(self):
        """A pack stored above 1x must not be an exact blow-up of a 1x pack."""
        for pid in IDS:
            p, d = load(pid)
            s = p['scale']
            if s == 1:
                continue
            with self.subTest(pid):
                exact = True
                for name in p['animations']:
                    for f in expand(p, d, name):
                        small = f[::s, ::s]
                        if not np.array_equal(np.repeat(np.repeat(small, s, 0), s, 1), f):
                            exact = False
                            break
                    if not exact:
                        break
                self.assertFalse(exact, 'every frame survives 1x: store it at scale 1')

    def test_anchor_and_content_box(self):
        for pid in IDS:
            p, d = load(pid)
            s, base = p['scale'], p['states']['idle'][0]
            idle = expand(p, d, base)
            with self.subTest(pid):
                g = Counter(lowest_opaque_edge(f, s) for f in idle)
                rest = min(v for v, k in g.items() if k == max(g.values()))
                self.assertEqual(p['anchor']['baseline'], rest)
                cx = np.mean([(np.nonzero(f[..., 3] >= 128)[1] + 0.5).mean() / s for f in idle])
                self.assertLessEqual(abs(p['anchor']['x'] - cx), 0.25)
                union = np.zeros(idle[0].shape[:2], bool)
                for f in idle:
                    union |= f[..., 3] >= 128
                ys, xs = np.nonzero(union)
                box = {'x': int(xs.min() // s), 'y': int(ys.min() // s)}
                box['w'] = math.ceil((xs.max() + 1) / s) - box['x']
                box['h'] = math.ceil((ys.max() + 1) / s) - box['y']
                self.assertEqual(p['contentBox'], box)
            for name in p['animations']:
                if name in OFF_GROUND[pid]:
                    continue
                with self.subTest(pid=pid, anim=name):
                    edges = [lowest_opaque_edge(f, s) for f in expand(p, d, name)]
                    self.assertIn(p['anchor']['baseline'], edges, 'never stands on the baseline')
                    self.assertLessEqual(max(edges) - p['anchor']['baseline'], MAX_DIP)


class AgainstSource(unittest.TestCase):
    def test_sources_present(self):
        for pid in IDS:
            self.assertTrue(os.path.isdir(os.path.join(SRC, pid)), f'{SRC}/{pid} is missing')

    def test_deepy_matches_apngs(self):
        p, d = load('deepy-whale')
        root = os.path.join(SRC, 'deepy-whale', 'assets')
        apngs = sorted(f[:-5] for f in os.listdir(root) if f.endswith('.apng'))
        self.assertEqual(sorted(p['animations']), apngs)
        s = p['scale']
        for name in apngs:
            with self.subTest(name):
                path = os.path.join(root, name + '.apng')
                delays = fctl_delays(path)
                got = expand(p, d, name)
                self.assertEqual([f['ms'] for f in p['animations'][name]['frames']], delays)
                self.assertEqual(len(got), len(delays))
                h, w = got[0].shape[:2]
                ref = ffmpeg_frames(path, w, h) if HAVE_FFMPEG else pillow_frames(path)
                self.assertEqual(len(ref), len(got))
                for k, (a, b) in enumerate(zip(got, ref)):
                    self.assertTrue(np.array_equal(a, b), f'frame {k} differs from the APNG')
                with Image.open(path) as im:
                    self.assertEqual(im.size, (p['canvas']['w'] * s, p['canvas']['h'] * s))

    def test_deepy_mapping_follows_theme(self):
        p, _ = load('deepy-whale')
        theme = json.loads(tool.read_text(os.path.join(SRC, 'deepy-whale', 'theme.json')))
        stem = lambda f: os.path.splitext(f)[0]
        for st, files in theme['states'].items():
            want = ['idle' if f.endswith('.svg') else stem(f) for f in files]
            self.assertEqual(p['states'][st][:len(want)], want, st)
        self.assertEqual(p['states']['idle'] + [x['anim'] for x in p['idlePool']['anims']],
                         [stem(x['file']) for x in theme['idleAnimations']])
        self.assertEqual({x['anim']: x['ms'] for x in p['idlePool']['anims']},
                         {stem(x['file']): x['duration'] for x in theme['idleAnimations'][1:]})
        self.assertEqual(p['bonus'], {})
        self.assertEqual(p['tiers']['working'],
                         [{'min': t['minSessions'], 'anim': stem(t['file'])} for t in theme['workingTiers']])
        self.assertEqual(p['tiers']['juggling'],
                         [{'min': t['minSessions'], 'anim': stem(t['file'])} for t in theme['jugglingTiers']])
        self.assertEqual(p['timings']['minDisplay'], theme['timings']['minDisplay'])
        held = dict(theme['timings']['autoReturn'])
        held.pop('notification')            # holds until dealt with (pets.md section 12 #7)
        self.assertEqual(p['timings']['autoReturn'], held)
        self.assertEqual(p['timings']['wakeMs'], theme['timings']['wakeDuration'])
        r = theme['reactions']
        self.assertEqual(p['reactions'], {'tapLeft': stem(r['clickLeft']['file']),
                                          'tapRight': stem(r['clickRight']['file']),
                                          'tickle': stem(r['double']['files'][0]),
                                          'drag': stem(r['drag']['file'])})
        self.assertTrue(theme['roamFlipAssets'])   # Clawd: the art faces left, mirrored to walk right
        self.assertEqual(p['roam']['faces'], 'left')
        self.assertEqual(p['hitBoxes']['sleepingAnims'],
                         [stem(f) for f in theme['sleepingHitboxFiles']])
        layout = theme['layout']
        self.assertEqual(p['canvas'], {'w': theme['viewBox']['width'], 'h': theme['viewBox']['height']})
        # Clawd's baselineY is the shadow's centre line, half a pixel under the feet.
        self.assertEqual(layout['baselineY'] - p['anchor']['baseline'], 0.5)
        self.assertLessEqual(abs(layout['centerX'] - p['anchor']['x']), 1)

    def test_whale_girl_matches_sheets_and_gifs(self):
        p, d = load('whale-girl')
        root = os.path.join(SRC, 'whale-girl')
        html = tool.read_text(os.path.join(root, 'index.html'))
        data = json.loads(re.search(r'id="set-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(sorted(p['animations']), sorted(a['key'] for a in data['anims']))
        self.assertEqual(p['canvas'], {'w': data['w'], 'h': data['h']})
        cw = data['w']
        for a in data['anims']:
            key = a['key']
            with self.subTest(key):
                got = expand(p, d, key)
                self.assertEqual([f['ms'] for f in p['animations'][key]['frames']], a['durs'])
                sheet = rgba(os.path.join(root, 'sheets', f'{key}.png'))
                ref = [norm(sheet[:, i * cw:(i + 1) * cw]) for i in range(sheet.shape[1] // cw)]
                self.assertEqual(len(got), len(ref))
                for k, (x, y) in enumerate(zip(got, ref)):
                    self.assertTrue(np.array_equal(x, y), f'frame {k} differs from the sheet')
                # GIF: consecutive identical frames are merged into one, durations summed.
                merged, md = [], []
                for f, ms in zip(got, a['durs']):
                    if merged and np.array_equal(merged[-1], f):
                        md[-1] += ms
                    else:
                        merged.append(f)
                        md.append(ms)
                gd, gf = [], []
                with Image.open(os.path.join(root, 'gifs', f'{a["i"]:02d}-{key}.gif')) as gif:
                    for i in range(gif.n_frames):
                        gif.seek(i)
                        gd.append(gif.info['duration'])
                        gf.append(norm(np.asarray(gif.convert('RGBA'))))
                self.assertEqual(md, gd)
                f8 = gf[0].shape[1] // cw
                for k, (x, g) in enumerate(zip(merged, gf)):
                    self.assertTrue(np.array_equal(np.repeat(np.repeat(x, f8, 0), f8, 1), g),
                                    f'GIF frame {k} differs')

    def test_whale_girl_timings_follow_her_page(self):
        """Each temporary state lasts the loops the page holds it; no hold = one loop minimum."""
        p, _ = load('whale-girl')
        html = tool.read_text(os.path.join(SRC, 'whale-girl', 'index.html'))
        table = re.search(r'const AGENT = \[(.*?)\];', html, re.S).group(1)
        holds = {k: int(h) for k, h in re.findall(r"key: '([\w-]+)', [^}]*?hold: (\d+)", table)}
        self.assertEqual(holds, {'error': 1, 'happy': 2, 'notification': 3, 'carrying': 2, 'waking': 1})
        loop = lambda st: p['animations'][p['states'][st][0]]['ms']
        want = lambda st: holds.get(p['states'][st][0], 1) * loop(st)
        t = p['timings']
        self.assertEqual(t['minDisplay'], {'attention': want('attention'), 'error': want('error'),
                                           'sweeping': want('sweeping'), 'notification': want('notification'),
                                           'carrying': want('carrying'), 'working': 1000, 'thinking': 1000})
        self.assertEqual(t['autoReturn'], {'attention': want('attention'), 'error': want('error'),
                                           'sweeping': 300000, 'carrying': want('carrying')})
        self.assertEqual(t['wakeMs'], want('waking'))
        self.assertEqual((t['autoReturn']['attention'], t['autoReturn']['error'], t['autoReturn']['carrying'],
                          t['wakeMs']), (3040, 1480, 2240, 1880))
        self.assertEqual(p['bonus'], {'attention': {'anims': ['smile-hearts', 'thumbs-up'], 'chance': 0.2}})
        self.assertEqual(p['states']['attention'], ['happy'])
        self.assertEqual(p['roam'], {'anim': 'swim', 'faces': 'front'})

    def test_rebuild_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pid in IDS:
                tool.build(pid, SRC, tmp, log=lambda *_: None)
                ours, fresh = os.path.join(PETS, pid), os.path.join(tmp, pid)
                self.assertEqual(sorted(os.listdir(ours)), sorted(os.listdir(fresh)), pid)
                for f in os.listdir(ours):
                    with open(os.path.join(ours, f), 'rb') as a, open(os.path.join(fresh, f), 'rb') as b:
                        self.assertEqual(a.read(), b.read(), f'{pid}/{f} is stale: rerun the tool')


# A tiny sprite pet (docs/design/naiwa-pet.md section 4): a 6x8 body standing on y 14 of a
# 16x16 canvas, one pixel of it changing per frame, props a pixel or more away from it.
TINY = dict(kind='sprite', dir='tiny', name='Tiny', author='test', license='test', source='test',
            faces='front', preview_zoom=2, preview_per_row=8)
BODY, EYE, PROP = (250, 214, 92, 255), (40, 30, 30, 255), (90, 200, 120, 255)


def tiny_pet():
    return {
        'id': 'tiny', 'w': 16, 'h': 16,
        'anims': [
            {'key': 'idle', 'durs': [100, 100, 100, 100], 'loop': True},
            {'key': 'laugh', 'durs': [100, 150, 100, 150], 'loop': True},
            {'key': 'busy', 'durs': [120, 120, 120, 120], 'loop': True},
            {'key': 'wake', 'durs': [200, 100, 100, 200], 'loop': False},
            {'key': 'poke', 'durs': [80, 80, 80, 80], 'loop': False},
            {'key': 'fidget', 'durs': [100, 100, 100, 100], 'loop': True},
        ],
        'states': {'idle': ['idle'], 'thinking': ['busy'], 'working': ['busy'], 'juggling': ['busy'],
                   'error': ['busy'], 'attention': ['laugh'], 'notification': ['busy'], 'sweeping': ['busy'],
                   'carrying': ['busy'], 'sleeping': ['busy'], 'waking': ['wake'], 'roam': ['busy']},
        'tiers': {'working': [{'min': 2, 'anim': 'laugh'}, {'min': 1, 'anim': 'busy'}]},
        'idlePool': [{'anim': 'fidget', 'loops': 3, 'weight': 2}],
        'bonus': {'attention': {'anims': ['fidget'], 'chance': 0.5}},
        'reactions': {'tapLeft': 'poke', 'tapRight': 'poke', 'tickle': 'poke', 'drag': 'busy'},
        'holds': {'attention': 3, 'error': 2, 'notification': 2, 'waking': 2, 'sweeping': 1},
        'faces': 'front',
        'sounds': 'tiny-test',        # no such sound set: the build only notes it
        'snack': {'mouth': {'x': 8, 'y': 9}, 'every': {'busy': 300, 'laugh': 150}},
    }


def tiny_frames():
    marks = {'idle': (8, 6), 'laugh': (11, 7), 'busy': (8, 7), 'wake': (9, 6), 'poke': (12, 6), 'fidget': (7, 9)}
    out = {}
    for key, (y, x) in marks.items():
        out[key] = []
        for k in range(4):
            f = np.zeros((16, 16, 4), np.uint8)
            f[6:14, 5:11] = BODY
            f[y, x + k % 2] = EYE
            if key in ('laugh', 'busy'):
                f[2:4, 12 + k % 2] = PROP
            out[key].append(f)
    return out


def write_sprite(d, pet, frames):
    os.makedirs(os.path.join(d, 'sheets'))
    with open(os.path.join(d, 'pet.json'), 'w', encoding='utf-8') as fh:
        json.dump(pet, fh)
    for key, fs in frames.items():
        Image.fromarray(np.concatenate(fs, axis=1)).save(os.path.join(d, 'sheets', f'{key}.png'))


def pet_anim(pet, key):
    return next(a for a in pet['anims'] if a['key'] == key)


def paint(frame, y, x, rgba):
    frame[y, x] = rgba


class SpriteSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        packs = mock.patch.dict(tool.PACKS, {'tiny': TINY})
        packs.start()
        self.addCleanup(packs.stop)

    def build(self, edit=lambda pet, frames: None):
        """The tiny pet, changed by edit(pet, frames), built: (pack.json, pack dir, log lines)."""
        pet, frames = tiny_pet(), tiny_frames()
        edit(pet, frames)
        root = tempfile.mkdtemp(dir=self.tmp)
        write_sprite(os.path.join(root, 'src', 'tiny'), pet, frames)
        log = []
        tool.build('tiny', os.path.join(root, 'src'), os.path.join(root, 'out'), log=log.append)
        d = os.path.join(root, 'out', 'tiny')
        with open(os.path.join(d, 'pack.json'), encoding='utf-8') as fh:
            return json.load(fh), d, log

    def test_pack(self):
        p, d, log = self.build()
        pet, frames = tiny_pet(), tiny_frames()
        self.assertEqual(list(p)[-4:], ['roam', 'sleep', 'sounds', 'snack'])
        self.assertEqual(p['sounds'], 'tiny-test')
        self.assertEqual(p['snack'], pet['snack'])
        self.assertTrue(any("'tiny-test'" in line and 'sounds.json' in line for line in log),
                        'a sound set that is not there yet is noted')
        self.assertEqual(list(p['states'].items()), [(s, pet['states'][s]) for s in STATES])
        for k in ('tiers', 'bonus', 'reactions'):
            self.assertEqual(p[k], pet[k], k)
        self.assertEqual(p['roam'], {'anim': 'busy', 'faces': 'front'})
        self.assertEqual(p['sleep'], {'afterMs': 60000})
        self.assertEqual((p['scale'], p['canvas']), (1, {'w': 16, 'h': 16}))
        self.assertEqual(p['anchor'], {'x': 8, 'baseline': 14})
        self.assertEqual(p['contentBox'], {'x': 5, 'y': 6, 'w': 6, 'h': 8})
        self.assertEqual(sorted(p['animations']), sorted(frames))
        for a in pet['anims']:
            with self.subTest(a['key']):
                self.assertEqual([f['ms'] for f in p['animations'][a['key']]['frames']], a['durs'])
                got = expand(p, d, a['key'])
                self.assertEqual(len(got), len(frames[a['key']]))
                for k, (x, y) in enumerate(zip(got, frames[a['key']])):
                    self.assertTrue(np.array_equal(x, y), f'frame {k} differs from the strip')

    def test_snack_mouths(self):
        """mouths moves the mouth in animations the pet eats in; it goes between mouth and every."""
        mouths = {'laugh': {'x': 12, 'y': 10}}
        p, _, _ = self.build(lambda pet, f: pet['snack'].update(mouths=mouths))
        self.assertEqual(list(p['snack']), ['mouth', 'mouths', 'every'])
        self.assertEqual(p['snack'], dict(tiny_pet()['snack'], mouths=mouths))

    def test_free_roam_comes_from_the_pack_entry(self):
        with mock.patch.dict(tool.PACKS, {'tiny': dict(TINY, free=True)}):
            p, _, _ = self.build()
        self.assertEqual(list(p['roam'].items()), [('anim', 'busy'), ('faces', 'front'), ('free', True)])

    def test_drag_mirror_comes_from_the_pack_entry(self):
        p, _, _ = self.build()
        self.assertNotIn('drag', p, 'no drag.mirror unless the pack asks for it')
        with mock.patch.dict(tool.PACKS, {'tiny': dict(TINY, drag_mirror=True)}):
            p, _, _ = self.build()
        self.assertEqual(p['drag'], {'mirror': True})

    def test_timings_follow_holds(self):
        """holds x one loop of the state's animation; carrying has no hold, so one loop."""
        p, _, _ = self.build()
        self.assertEqual({n: a['ms'] for n, a in p['animations'].items()},
                         {'idle': 400, 'laugh': 500, 'busy': 480, 'wake': 600, 'poke': 320, 'fidget': 400})
        t = p['timings']
        self.assertEqual(t['minDisplay'], {'attention': 1500, 'error': 960, 'sweeping': 480, 'notification': 960,
                                           'carrying': 480, 'working': 1000, 'thinking': 1000})
        self.assertEqual(t['autoReturn'], {'attention': 1500, 'error': 960, 'sweeping': 300000, 'carrying': 480})
        self.assertEqual(t['wakeMs'], 1200)

    def test_idle_pool_plays_whole_loops(self):
        p, _, _ = self.build()
        self.assertEqual(p['idlePool'], {'everyMs': {'mean': 120000, 'min': 45000, 'max': 300000},
                                         'anims': [{'anim': 'fidget', 'ms': 1200, 'weight': 2}]})

    def test_one_shots_play_once(self):
        p, _, _ = self.build()
        self.assertEqual({n: a['loop'] for n, a in p['animations'].items()},
                         {'idle': True, 'laugh': True, 'busy': True, 'wake': False, 'poke': False, 'fidget': True})

    def test_rebuild_is_byte_identical(self):
        _, a, _ = self.build()
        _, b, _ = self.build()
        self.assertEqual(sorted(os.listdir(a)), sorted(os.listdir(b)))
        for f in os.listdir(a):
            with open(os.path.join(a, f), 'rb') as x, open(os.path.join(b, f), 'rb') as y:
                self.assertEqual(x.read(), y.read(), f)
        with open(os.path.join(a, 'pack.json'), 'rb') as fh:
            self.assertNotIn(b'\r', fh.read(), 'LF line ends on every OS')

    def test_rejects_broken_sources(self):
        cases = [
            ('mouth off the canvas', lambda p, f: p['snack']['mouth'].update(x=16), r'off the 16x16 canvas'),
            ('mouth above the canvas', lambda p, f: p['snack']['mouth'].update(y=-1), r'off the 16x16 canvas'),
            ('a state names a missing animation', lambda p, f: p['states'].update(thinking=['nope']),
             r'states\.thinking: no animation nope'),
            ('snack.every names a missing animation', lambda p, f: p['snack']['every'].update(nope=100),
             r'snack\.every: no animation nope'),
            ('a mouths point off the canvas', lambda p, f: p['snack'].update(mouths={'laugh': {'x': 3, 'y': 16}}),
             r'snack\.mouths\.laugh: \(3, 16\) is off the 16x16 canvas'),
            ('a mouths animation that eats nothing', lambda p, f: p['snack'].update(mouths={'poke': {'x': 3, 'y': 9}}),
             r'snack\.mouths\.poke: not in snack\.every'),
            ('mouths names a missing animation', lambda p, f: p['snack'].update(mouths={'nope': {'x': 3, 'y': 9}}),
             r'snack\.mouths: no animation nope'),
            ('empty mouths', lambda p, f: p['snack'].update(mouths={}), r'snack\.mouths: not a non-empty object'),
            ('waking loops', lambda p, f: pet_anim(p, 'wake').update(loop=True), r'wake: plays once'),
            ('a tap reaction loops', lambda p, f: pet_anim(p, 'poke').update(loop=True), r'poke: plays once'),
            ('strip a frame short', lambda p, f: f['busy'].pop(), r'sheets/busy\.png: 48x16 for 4 frames'),
            ('strip a pixel too wide', lambda p, f: f['busy'].append(np.zeros((16, 1, 4), np.uint8)),
             r'sheets/busy\.png: 65x16 for 4 frames'),
            ('too few frames', lambda p, f: (pet_anim(p, 'busy')['durs'].pop(), f['busy'].pop()),
             r'busy: 3 frames'),
            ('a frame too short', lambda p, f: pet_anim(p, 'busy').update(durs=[30, 120, 120, 120]),
             r'busy: frame durations'),
            ('semi-transparent pixel', lambda p, f: paint(f['idle'][0], 7, 7, (250, 214, 92, 128)),
             r'semi-transparent'),
            ('a prop in the idle loop', lambda p, f: paint(f['idle'][1], 1, 1, EYE), r'idle frame 1: 1 px apart'),
            ('an unused animation', lambda p, f: (p['anims'].append({'key': 'spare', 'durs': [100] * 4, 'loop': True}),
                                                  f.update(spare=f['idle'])), r'spare not used'),
            ('a missing state', lambda p, f: p['states'].pop('roam'), r'states: no roam'),
            ('a missing reaction', lambda p, f: p['reactions'].pop('drag'), r'reactions: no drag'),
            ('a hold on a debounced state', lambda p, f: p['holds'].update(working=2), r"holds: \['working'\]"),
            ('a bonus that always plays', lambda p, f: p['bonus']['attention'].update(chance=1),
             r'chance 1 is not strictly between'),
            ('a sounds id that is not one', lambda p, f: p.update(sounds='Tiny Test'), r"sounds 'Tiny Test'"),
            ('a snack every 0 ms', lambda p, f: p['snack']['every'].update(busy=0), r'snack\.every\.busy'),
            ('an unknown key', lambda p, f: p.update(hold={}), r"unknown keys \['hold'\]"),
            ('faces against the pack', lambda p, f: p.update(faces='left'), r"faces 'left'"),
        ]
        for what, edit, msg in cases:
            with self.subTest(what), self.assertRaisesRegex(tool.BuildError, msg):
                self.build(edit)

    def test_full_build_skips_a_sprite_pack_not_drawn_yet(self):
        src, out, preview = (os.path.join(self.tmp, d) for d in ('src', 'out', 'preview'))
        write_sprite(os.path.join(src, 'tiny'), tiny_pet(), tiny_frames())
        with mock.patch.dict(tool.PACKS, {'tiny': TINY, 'later': dict(TINY, dir='later')}, clear=True):
            with contextlib.redirect_stdout(io.StringIO()) as said:
                self.assertEqual(tool.main(['--src', src, '--out', out, '--preview', preview]), 0)
            self.assertIn('later: skipped', said.getvalue())
            self.assertTrue(os.path.isfile(os.path.join(out, 'tiny', 'pack.json')))
            self.assertTrue(os.path.isfile(os.path.join(preview, 'tiny.png')))
            self.assertFalse(os.path.exists(os.path.join(out, 'later')))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tool.main(['--src', src, '--out', out, '--only', 'later']), 1)
            self.assertIn('pet.json is missing', err.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
