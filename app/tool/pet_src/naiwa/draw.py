#!/usr/bin/env python3
"""Draws 奶蛙 scheme A, the classic yellow one (pack id `naiwa`): pet.json and sheets/<anim>.png.

Run from the repository root (needs numpy and Pillow):

    python app/tool/pet_src/naiwa/draw.py [--check] [--preview] [--strip ANIM ...]

A run redraws all 26 animations, writes sheets/<anim>.png (1x single-row strips of
64x64 cells) and pet.json next to this script, then checks them against
docs/design/naiwa-pet.md sections 3 and 4. `--check` redraws in memory and only
verifies, failing when the files on disk are stale. `--preview` also writes a
contact sheet of every frame (4x on a checkerboard) to
app/build/pet_src_preview/naiwa.png; `--strip ANIM` writes a 4x grid of each named
animation to app/build/pet_src_preview/naiwa/ANIM.png. No clock and no randomness:
two runs give byte-identical files.

How the art is made: a small rig on integer pixels, no anti-aliasing.

* The trunk (head and body in one piece, no neck) is a per-row half-width profile
  about x = 32: a dome, sides widening to a low belly, a rounded bottom. A pose
  squashes or stretches it about the hip line, shears it (leaning), and moves or
  rotates the whole figure.
* The belly is an ellipse inside the trunk; an arm is two capsules (shoulder, elbow,
  hand) ending in a 4x4 paw; legs are short capsules on half-ellipse feet.
* Light comes from the top left: a dark rim on the bottom-right edges, a highlight
  on the crown. The outline is the 4-neighbour dilation of all parts minus the
  parts (1 px, stair-stepped); a limb in front of the trunk gets its own outline
  where it overlaps.
* Eyes, mouths and props are hand-drawn bitmaps stamped at rig anchors. Detached
  props (哈, Z, !, ?, code glyphs and tiles, crumbs, sweat) get an 8-neighbour
  outline and keep at least one clear pixel from the body, so the pack builder's
  largest-blob rule never counts them as body. Props held in a paw, the carried
  file box and the snot bubble touch the body on purpose.
"""
import argparse
import hashlib
import io
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..'))
SHEETS = os.path.join(HERE, 'sheets')
PREVIEW_DIR = os.path.join(REPO, 'app', 'build', 'pet_src_preview')
PACK_ID = 'naiwa'

W = H = 64
MIN_FRAMES, MAX_FRAMES = 4, 16
MIN_MS, MAX_MS = 60, 400
MAX_TOTAL_FRAMES = 400
MAX_COLORS = 256

# docs/design/naiwa-pet.md section 3, in table order.
ANIM_NAMES = [
    'idle', 'idle-look', 'idle-giggle', 'snack', 'dance', 'thinking',
    'eat-code', 'eat-code-fast', 'feast', 'juggle', 'juggle-many', 'shocked', 'laugh',
    'laugh-point', 'laugh-roll', 'laugh-belly', 'alert', 'devour', 'carry', 'sleep',
    'wake', 'walk', 'poke-left', 'poke-right', 'tickle', 'prone-eat',
]
ONE_SHOT = {'wake', 'poke-left', 'poke-right', 'tickle'}
EATING = ['eat-code', 'eat-code-fast', 'feast', 'devour', 'snack']   # mouth at snack.mouth
OWN_MOUTH = ['prone-eat']   # eating with the mouth elsewhere: snack.mouths

PALETTE = {
    'line': '#4A2E12',
    'body': '#F6D24A', 'body_hi': '#FFE98A', 'body_lo': '#DDA92F', 'body_lo2': '#B98522',
    'belly': '#F8EBC8', 'belly_lo': '#E6D3A3',
    'eye': '#A6DC78', 'pupil': '#141414', 'white': '#FFFFFF',
    'mouth': '#4A1222', 'tongue': '#E86A7C',
    'paw': '#6F665A', 'paw_lo': '#4F483F',
    'blush': '#F6A08E',
    'ha': '#FF5A3C', 'zz': '#8FA6D8', 'bang': '#FF4040', 'ask': '#6FB7FF', 'sweat': '#8ED8FF',
    'snot': '#CFF4FF',
    'code_line': '#282C34', 'tile': '#3E4451',
    'c1': '#C678DD', 'c2': '#98C379', 'c3': '#D19A66', 'c4': '#61AFEF', 'c5': '#E5C07B',
    'c6': '#ABB2BF',
    'box': '#D9A05B', 'box_lo': '#B07A3A', 'box_hi': '#F0C987', 'paper': '#FFF8E6',
    'ghost_r': '#FF3D6E', 'ghost_c': '#2EE6FF',
}
NAMES = list(PALETTE)
IDX = {n: i + 1 for i, n in enumerate(NAMES)}
CODE_COLORS = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6']
# One-frame colour swaps for the 鬼畜 cuts.
TINTS = {
    'pink': {'body': '#FF8FC8', 'body_hi': '#FFC4E3', 'body_lo': '#E0609F',
             'body_lo2': '#B8407E', 'belly': '#FFE6F3', 'belly_lo': '#F2B8D4'},
    'cyan': {'body': '#6FE0F0', 'body_hi': '#B8F5FF', 'body_lo': '#3FB3CF',
             'body_lo2': '#2A8AA8', 'belly': '#E6FBFF', 'belly_lo': '#B5E4EE'},
}


def rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------- raster helpers

YS, XS = np.mgrid[0:H, 0:W]
CX, CY = XS + 0.5, YS + 0.5


def shifted(m, dy, dx):
    """out[y, x] = m[y + dy, x + dx]; False outside the canvas."""
    out = np.zeros_like(m)
    out[max(0, -dy):H - max(0, dy), max(0, -dx):W - max(0, dx)] = \
        m[max(0, dy):H - max(0, -dy), max(0, dx):W - max(0, -dx)]
    return out


def dilate4(m):
    return m | shifted(m, 1, 0) | shifted(m, -1, 0) | shifted(m, 0, 1) | shifted(m, 0, -1)


def dilate8(m):
    d = dilate4(m)
    return d | shifted(m, 1, 1) | shifted(m, 1, -1) | shifted(m, -1, 1) | shifted(m, -1, -1)


def capsule(a, b, r):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = np.zeros_like(CX) if l2 == 0 else np.clip(((CX - ax) * dx + (CY - ay) * dy) / l2, 0, 1)
    return (CX - ax - t * dx) ** 2 + (CY - ay - t * dy) ** 2 < r * r


def ellipse(c, rx, ry, rot=0.0):
    dx, dy = CX - c[0], CY - c[1]
    if rot:
        cs, sn = math.cos(rot), math.sin(rot)
        dx, dy = dx * cs + dy * sn, -dx * sn + dy * cs
    return (dx / rx) ** 2 + (dy / ry) ** 2 < 1


def iround(v):
    return int(math.floor(v + 0.5))


def bitmap_mask(rows, x0, y0):
    """Mask of a bitmap's painted (non-'.') cells with its top-left at (x0, y0)."""
    m = np.zeros((H, W), bool)
    for j, row in enumerate(rows):
        for i, c in enumerate(row):
            if c != '.' and 0 <= y0 + j < H and 0 <= x0 + i < W:
                m[y0 + j, x0 + i] = True
    return m


def stamp(lab, rows, x0, y0, colors, clip=None):
    """Paint a character bitmap with its top-left at (x0, y0); '.' is skipped."""
    for j, row in enumerate(rows):
        y = y0 + j
        if not 0 <= y < H:
            continue
        for i, c in enumerate(row):
            x = x0 + i
            if c == '.' or not 0 <= x < W or (clip is not None and not clip[y, x]):
                continue
            lab[y, x] = IDX[colors[c]]


def iround_from(v, c):
    """Round half away from the grid line nearest c, so features mirrored about it
    land on mirrored pixels."""
    c = iround(c)
    d = v - c
    return int(c + math.copysign(math.floor(abs(d) + 0.5), d))


def corner(rows, cx, cy, axis):
    """Top-left that centres a bitmap on canvas point (cx, cy)."""
    return iround_from(cx - len(rows[0]) / 2, axis), iround(cy - len(rows) / 2)


# ---------------------------------------------------------------- face parts

FACE = {'o': 'line', 'g': 'eye', 'k': 'pupil', 'w': 'white', 'm': 'mouth', 't': 'tongue',
        'p': 'blush'}


def disc_rows(n, rim, inside, edge):
    """An n x n round bitmap: `rim` within `edge` px of the circle, `inside` within it."""
    r = n / 2
    return [['.' if d > r - 0.15 else (rim if d > r - edge else inside)
             for d in (math.hypot(i + 0.5 - r, j + 0.5 - r) for i in range(n))]
            for j in range(n)]


def eye_rows(kind, look=(0, 0), side=-1):
    """Eye bitmap; side -1 is the eye on the viewer's left."""
    if kind in ('open', 'wide'):
        n = 7 if kind == 'open' else 9
        rows = disc_rows(n, 'o', 'g', 1.2)
        c0 = (n - 3) // 2
        for j in range(3):
            for i in range(3):
                y, x = c0 + j + look[1], c0 + i + look[0]
                if rows[y][x] == 'g':
                    rows[y][x] = 'k'
        if rows[c0 + look[1]][c0 + look[0]] == 'k':
            rows[c0 + look[1]][c0 + look[0]] = 'w'
        return [''.join(r_) for r_ in rows]
    if kind == 'closed':      # a blink
        return [".......", ".......", ".......", ".ooooo.", ".......", ".......", "......."]
    if kind == 'happy':       # laughing: bold arcs bowed up
        return [".......", ".......", "..ooo..", ".ooooo.", "oo...oo", "o.....o", "......."]
    if kind == 'shut':        # asleep: arcs bowed down
        return [".......", ".......", "o.....o", ".o...o.", "..ooo..", ".......", "......."]
    if kind == 'sleepy':
        return [".......", ".......", "ooooooo", "ogkkkgo", ".ogggo.", "..ooo..", "......."]
    if kind == 'squeeze':     # > <
        rows = ["oo...", ".ooo.", "...oo", ".ooo.", "oo..."]
        return rows if side < 0 else [r_[::-1] for r_ in rows]
    raise ValueError(kind)


MOUTHS = {
    'smile': ["o......o", ".oooooo."],
    'line': ["oooooo"],
    'grin': ["oooooooo", "ommmmmmo", ".otttto.", "..oooo.."],
    'laugh': ["oooooooooooo",
              "owwwwwwwwwwo",
              "ommmmmmmmmmo",
              "ommmmmmmmmmo",
              ".ommmttmmmo.",
              "..omttttmo..",
              "...oooooo..."],
    'roar': ["oooooooooooo",           # the widest laugh: fangs, tongue
             "owwwwwwwwwwo",
             "owmmmmmmmmwo",
             "ommmmmmmmmmo",
             "ommmmmmmmmmo",
             ".ommmttmmmo.",
             "..omttttmo..",
             "...oooooo..."],
    'o': [".oo.", "owwo", "ommo", "ommo", ".oo."],
    'O': [".oooo.", "owwwwo", "ommmmo", "ommmmo", "ommmmo", "ommmmo", ".oooo."],
    'eat': ["..oooooo..",               # wide open for code; its centre is snack.mouth
            ".owwwwwwo.",
            "ommmmmmmmo",
            "ommmmmmmmo",
            "ommmmmmmmo",
            "ommmttmmmo",
            ".ommttmmo.",
            "..oooooo.."],
    'chew_a': [".oooooo.", "o......o"],
    'chew_b': ["o......o", ".oooooo."],
    'yawn': [".oooo.", "ommmmo", "ommmmo", "ommmmo", "omttmo", "omttmo", ".oooo."],
    'wavy': [".oo..oo.", "o..oo..o"],
    'burp': [".oo.", "ommo", ".oo."],
}


# ---------------------------------------------------------------- props

GLYPHS = {
    'ha': [".......X...",              # 哈: 口 on the left, 合 on the right
           "......X.X..",
           ".....X...X.",
           "XXX.X.....X",
           "X.X...XXX..",
           "X.X........",
           "X.X..XXXXX.",
           "XXX..X...X.",
           ".....XXXXX."],
    '!': ["XX", "XX", "XX", "XX", "XX", "..", "XX"],
    '?': [".XXX.", "XX.XX", "...XX", "..XX.", "..XX.", ".....", "..XX."],
    'Z': ["XXXXX", "...X.", "..X..", ".X...", "XXXXX"],
    'z': ["XXX", ".X.", "XXX"],
    '.': ["X"],
    'sweat': [".X.", "XXX", "XXX"],
    'semi': ["XX", "XX", "..", "..", "XX", "XX", ".X", "X."],
    'puff': [".XXX..", "XXXXX.", "XXXXXX", ".XXXX."],
    'crumb': ["X"],
}
CODE_FONT = {
    '{': [".XX", ".X.", "X..", ".X.", ".XX"], '}': ["XX.", ".X.", "..X", ".X.", "XX."],
    '[': ["XX.", "X..", "X..", "X..", "XX."], ']': [".XX", "..X", "..X", "..X", ".XX"],
    '(': [".X.", "X..", "X..", "X..", ".X."], ')': [".X.", "..X", "..X", "..X", ".X."],
    '<': ["..X", ".X.", "X..", ".X.", "..X"], '>': ["X..", ".X.", "..X", ".X.", "X.."],
    ';': ["...", ".X.", "...", ".X.", "X.."], '=': ["...", "XXX", "...", "XXX", "..."],
    '+': ["...", ".X.", "XXX", ".X.", "..."], '0': ["XXX", "X.X", "X.X", "X.X", "XXX"],
    'f': [".XX", ".X.", "XXX", ".X.", ".X."], 'n': ["...", "XX.", "X.X", "X.X", "X.X"],
    'x': ["...", "...", "X.X", ".X.", "X.X"],
}
BOX = ["oooooooooooooooo",
       "ohhhhhhhhhhhhhho",
       "oooooooooooooooo",
       "obbbbbbbbbbbbblo",
       "obbpppppppppbblo",
       "obbpaaapcccpbblo",
       "obbpppppppppbblo",
       "obbbbbbbbbbbbblo",
       "obbbbbbbbbbbbllo",
       "oooooooooooooooo"]
BOX_COLORS = {'o': 'line', 'h': 'box_hi', 'b': 'box', 'l': 'box_lo', 'p': 'paper',
              'a': 'c1', 'c': 'c4'}


def glyph_cells(kind, *args):
    """Prop -> list of (rows, x0, y0, colour) pieces and its outline colour."""
    if kind == 'code':
        text, x, y = args[:3]
        colors = args[3] if len(args) > 3 else CODE_COLORS
        if isinstance(colors, str):
            colors = [colors]
        pieces = [(CODE_FONT[ch], x + 4 * i, y, colors[i % len(colors)])
                  for i, ch in enumerate(text) if ch != ' ']
        return pieces, 'code_line'
    name, x, y = args[:3]
    color = args[3] if len(args) > 3 else {'ha': 'ha', '!': 'bang', '?': 'ask', 'Z': 'zz',
                                            'z': 'zz', '.': 'ask', 'sweat': 'sweat',
                                            'puff': 'white'}.get(name, 'c5')
    return [(GLYPHS[name], x, y, color)], 'line'


def draw_props(lab, props):
    """Paint props over the figure; returns (detached prop pixels, attached prop pixels).

    Kinds: ('glyph', name, x, y[, colour]) and ('code', text, x, y[, colours]) fly free
    with an outline; a '-held' suffix ('glyph-held', 'code-held') marks one held in a
    paw, and '-in' ('code-in') one inside the open mouth, drawn without outline;
    ('block', text, x, y[, colours]) is a juggled code tile, (x, y) its top-left;
    ('box', x, y) is carried and ('bubble', x, y, size) hangs from the face. Held,
    carried and hanging props may touch the body; the others must not.
    """
    free = np.zeros((H, W), bool)
    held = np.zeros((H, W), bool)
    for pr in props:
        kind = pr[0]
        if kind == 'box':
            stamp(lab, BOX, pr[1], pr[2], BOX_COLORS)
            held |= bitmap_mask(BOX, pr[1], pr[2])
            continue
        if kind == 'bubble':
            x, y, n = pr[1:]
            rows = disc_rows(n, 'o', 's', 1.0)
            if n >= 4:
                rows[n // 3][n // 3] = 'w'
            rows = [''.join(r) for r in rows]
            stamp(lab, rows, x, y, {'o': 'line', 's': 'snot', 'w': 'white'})
            held |= bitmap_mask(rows, x, y)
            continue
        if kind == 'block':
            text, x, y = pr[1:4]
            colors = pr[4] if len(pr) > 4 else CODE_COLORS
            colors = [colors] if isinstance(colors, str) else colors
            w, h = 4 * len(text) + 3, 9
            tile = (XS >= x) & (XS < x + w) & (YS >= y) & (YS < y + h)
            for cx, cy in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
                tile &= ~((XS == cx) & (YS == cy))
            lab[tile] = IDX['code_line']
            lab[tile & ~dilate4(~tile)] = IDX['tile']
            for i, ch in enumerate(text):
                lab[bitmap_mask(CODE_FONT[ch], x + 2 + 4 * i, y + 2)] = IDX[colors[i % len(colors)]]
            free |= tile
            continue
        base, _, mode = kind.partition('-')
        pieces, line = glyph_cells(base, *pr[1:])
        m = np.zeros((H, W), bool)
        for rows, x0, y0, color in pieces:
            m |= bitmap_mask(rows, x0, y0)
        if mode != 'in':
            ol = dilate8(m) & ~m
            lab[ol] = IDX[line]
            if mode == 'held':
                held |= m | ol
            else:
                free |= m | ol
        for rows, x0, y0, color in pieces:
            lab[bitmap_mask(rows, x0, y0)] = IDX[color]
    return free, held


# ---------------------------------------------------------------- the rig

HB = 26                    # trunk height: rows 27..52 at rest
HIP_X, HIP_Y = 32.0, 53.0  # trunk bottom centre on the canvas
# Trunk half-width per row, bottom row first. Whole pixels, so at rest every row is
# 2 * hw pixels wide and symmetric about x = 32.
PROFILE = [10, 12, 13, 14, 14, 14, 14, 14, 13, 13, 13, 13, 12, 12, 12, 12,
           11, 11, 11, 11, 11, 11, 10, 9, 7, 5]
assert len(PROFILE) == HB
EYE_U, EYE_V = 6.5, 20.5
MOUTH_V = 14.5
SHOULDER_V = 12.5
BELLY_V, BELLY_RX, BELLY_RY = 5.0, 9.0, 7.0
ARM_R, PAW_R = 1.9, 1.75
GROUND = 60                # idle foot line: the bottom edge of the lowest opaque row
SIT = ((-8.0, -1.5), (8.0, -1.5))   # sole centres when sitting

ARMS = {   # (elbow, hand) of the right arm in trunk space; u is mirrored for the left
    'down': ((12.5, 9.0), (12.5, 5.0)),
    'down_in': ((12.0, 9.0), (11.0, 5.5)),
    'down_out': ((13.0, 9.5), (14.0, 5.5)),
    'hip': ((16.0, 9.5), (11.5, 5.0)),
    'head': ((16.0, 20.5), (10.0, 25.0)),
    'point': ((15.5, 12.5), (19.5, 13.5)),
    'chin': ((8.0, 3.0), (3.0, 9.5)),
    'fold': ((11.0, 5.5), (0.5, 3.5)),     # across the belly, under the other forearm
    'out': ((15.5, 13.5), (19.5, 15.5)),
    'out_up': ((15.5, 15.0), (19.0, 19.5)),
    'out_dn': ((15.5, 12.0), (19.5, 11.0)),
    'belly': ((13.0, 8.0), (6.0, 6.0)),
    'belly_up': ((13.0, 8.5), (6.5, 7.5)),
    'cover': ((9.5, 8.5), (2.5, 14.0)),
    'feed': ((12.5, 8.5), (7.0, 13.0)),
    'reach': ((15.5, 12.0), (19.5, 12.0)),
    'wave': ((16.0, 16.0), (17.5, 22.0)),
    'wave_b': ((16.5, 15.5), (20.0, 20.5)),
    'catch': ((15.5, 11.5), (17.0, 16.5)),
    'toss': ((15.0, 14.5), (15.5, 21.0)),
    'hold': ((14.5, 21.0), (7.0, 28.5)),
    'stretch': ((12.5, 22.0), (10.5, 30.5)),
    'flail_a': ((16.0, 17.0), (19.0, 22.0)),
    'flail_b': ((16.0, 13.0), (20.0, 15.5)),
    'lap': ((12.0, 7.0), (9.0, 3.5)),
}
PAWS = {'point': 'point', 'wave': 'open', 'wave_b': 'open'}
LEGS = {   # (left foot, right foot) bottom centres relative to the hip line
    'stand': ((-6.5, -6.0), (6.5, -6.0)),
    'lift_l': ((-8.0, -3.5), (6.5, -6.0)),
    'lift_r': ((-6.5, -6.0), (8.0, -3.5)),
    'step_l': ((-6.0, -4.5), (6.5, -6.0)),
    'step_r': ((-6.5, -6.0), (6.0, -4.5)),
}

BASE = dict(x=0.0, y=0.0, rot=0.0, sx=1.0, sy=1.0, lean=0.0,
            eyes='open', look=(0, 0), mouth='smile', face=(0.0, 0.0), blush=False,
            arms=('down', 'down'), legs='stand', sit=False, cheeks=0.0, belly=0.0,
            props=(), tint=None, ghost=0, prone=None)


def pose(base=None, **kw):
    p = dict(BASE if base is None else base)
    p.update(kw)
    return p


class Rig:
    def __init__(self, p):
        self.p = p
        self.ox, self.oy = HIP_X + p['x'], HIP_Y + p['y']
        th = math.radians(p['rot'])
        self.c, self.s = math.cos(th), math.sin(th)

    def hw(self, v):
        hw = np.interp(np.asarray(v, float) - 0.5, np.arange(HB), PROFILE)
        if self.p['cheeks']:
            hw = hw + self.p['cheeks'] * np.clip(1 - np.abs(v - MOUTH_V) / 3.5, 0, 1)
        if self.p['belly']:
            hw = hw + self.p['belly'] * np.clip(1 - np.abs(v - BELLY_V) / 5.0, 0, 1)
        return hw

    def fig(self, u, v):
        """Figure space (rest pose, y up from the hip line) -> canvas."""
        return (self.ox + u * self.c - v * self.s, self.oy - (u * self.s + v * self.c))

    def trunk_pt(self, u, v):
        p = self.p
        return self.fig(u * p['sx'] + p['lean'] * v / HB, v * p['sy'])

    def local(self):
        p = self.p
        fu, fv = CX - self.ox, self.oy - CY
        u = fu * self.c + fv * self.s
        v = -fu * self.s + fv * self.c
        v = v / p['sy']
        u = (u - p['lean'] * v / HB) / p['sx']
        return u, v

    def trunk(self, u, v):
        return (v > 0) & (v < HB) & (np.abs(u) < self.hw(v))

    def belly(self, u, v):
        rx = BELLY_RX + self.p['belly']
        return (u / rx) ** 2 + ((v - BELLY_V) / BELLY_RY) ** 2 < 1

    def arm(self, side, spec):
        name = spec if isinstance(spec, str) else None
        (eu, ev), (hu, hv) = ARMS[spec] if name else spec
        sh = self.trunk_pt(side * (float(self.hw(SHOULDER_V)) - 2.5), SHOULDER_V)
        el = self.trunk_pt(side * eu, ev)
        ha = self.trunk_pt(side * hu, hv)
        arm = capsule(sh, el, ARM_R) | capsule(el, ha, ARM_R)
        pc = (iround_from(ha[0], self.ox), iround(ha[1]))
        paw = ellipse(pc, PAW_R, PAW_R)
        style = PAWS.get(name)
        if style == 'point':
            dx, dy = ha[0] - el[0], ha[1] - el[1]
            n = math.hypot(dx, dy) or 1
            paw |= capsule(pc, (pc[0] + 4.2 * dx / n, pc[1] + 4.2 * dy / n - 0.5), 0.75)
        elif style == 'open':
            paw = ellipse(pc, 2.0, 1.9)
        return arm & ~paw, paw

    def legs(self):
        spec = self.p['legs']
        feet_pts = LEGS[spec] if isinstance(spec, str) else spec
        legs = np.zeros((H, W), bool)
        feet = np.zeros((H, W), bool)
        for side, (fx, fy) in zip((-1, 1), feet_pts):
            hip = self.fig(side * 5.0, 2.0)
            ank = self.fig(fx * 0.9, fy + 2.5)
            legs |= capsule(hip, ank, 2.5)
            fc = self.fig(fx, fy + 0.1)
            # A half-ellipse: flat sole, round top (in figure space).
            fu, fv = CX - fc[0], fc[1] - CY
            a = fu * self.c + fv * self.s
            b = -fu * self.s + fv * self.c
            feet |= ((a / 3.6) ** 2 + (b / 2.6) ** 2 < 1) & (b > 0)
        return legs & ~feet, feet

    def sit_feet(self, spots):
        """Soles in front of the trunk when sitting (or kicking on its back)."""
        m = np.zeros((H, W), bool)
        for u, v in spots:
            m |= ellipse(self.fig(u, v), 3.0, 2.3)
        return m


def dark_rim(m):
    """The bottom-right rim of a part, lit from the top left."""
    return m & ~(shifted(m, 1, 1) & shifted(m, 0, 2) & shifted(m, 2, 0))


# ---------------------------------------------------------------- lying on its belly
#
# prone-eat, played while dragged, has a figure of its own seen from the side: crawling
# on its belly with the rump on the left and the legs stretched out behind it, the head
# at the right end held up on the forepaws and turned to the viewer, so code flies in
# from the right.

PRONE_TOP, PRONE_X = 34, 41.0    # head: top row, centre line
# Head half-width per row from the top: the idle dome squashed.
PRONE_HEAD = [5, 7, 9, 10, 11, 11, 12, 12, 12, 13, 13, 13, 13, 13, 13, 12, 12, 11, 9]
PRONE_FACE_U = 2.0               # the face turned a little to the right
PRONE_EYE_DY, PRONE_MOUTH_DY = 5.5, 12.0   # below the head's top row
# Body: a round rump and a lower chest under the head (centre, radii), cut flat by the floor.
PRONE_BODY = (((16.0, 52.0), 8.5, 7.5), ((30.0, 53.5), 13.0, 6.0))
PRONE_KNEES = ((11.0, 55.0), (13.0, 55.5))  # far and near shin pivots, inside the rump
PRONE_SHIN = 6.5
PRONE_SHOULDERS = ((48.0, 50.0), (31.0, 50.0))  # far and near, under the head
PRONE_PAWS = ((52.5, 57.0), (30.0, 57.0))       # flat on the floor; the far one past the chin


def prone_shin(knee, deg):
    """A shin from `knee`, tilted `deg` from upright towards the head (-90 lies flat
    behind), and its foot, the sole turned away from the knee."""
    a = math.radians(deg)
    dx, dy = math.sin(a), -math.cos(a)
    ank = (knee[0] + PRONE_SHIN * dx, knee[1] + PRONE_SHIN * dy)
    sole = (ank[0] + 2.4 * dx, ank[1] + 2.4 * dy)
    fu, fv = CX - sole[0], CY - sole[1]
    along, across = fu * dx + fv * dy, fu * dy - fv * dx
    foot = ((across / 3.8) ** 2 + (along / 3.0) ** 2 < 1) & (along < 0)
    return capsule(knee, ank, 2.3) & ~foot, foot


def prone_arm(shoulder, paw, step):
    """An arm down to its paw on the floor, the paw moved `step` = (dx, lift)."""
    pc = (paw[0] + step[0], paw[1] - step[1])
    paw = ellipse(pc, PAW_R + 0.4, PAW_R)
    return capsule(shoulder, pc, ARM_R) & ~paw, paw


def render_prone(p):
    q = p['prone']
    lab = np.zeros((H, W), np.uint8)
    floor = YS < GROUND - 1          # the outline takes the last row
    top = PRONE_TOP + q.get('nod', 0)
    mouth_y = top + PRONE_MOUTH_DY
    hw = np.asarray(PRONE_HEAD, float)[np.clip(YS - top, 0, len(PRONE_HEAD) - 1)]
    if p['cheeks']:
        hw = hw + p['cheeks'] * np.clip(1 - np.abs(CY - mouth_y) / 3.5, 0, 1)
    head = (YS >= top) & (YS < top + len(PRONE_HEAD)) & (np.abs(CX - PRONE_X) < hw) & floor
    (rump_c, rump_rx, rump_ry), (chest_c, chest_rx, chest_ry) = PRONE_BODY
    rise = q.get('rise', 0)          # the rump bobs as the hind feet push
    body = (ellipse((rump_c[0], rump_c[1] - rise / 2), rump_rx, rump_ry + rise / 2)
            | ellipse(chest_c, chest_rx, chest_ry)) & floor
    belly = ellipse((21.0, 58.5), 12.5, 4.5) & body
    legs = [prone_shin(k, a) for k, a in zip(PRONE_KNEES, q['kick'])]
    arms = [prone_arm(s, pw, st) for s, pw, st in zip(PRONE_SHOULDERS, PRONE_PAWS, q['paws'])]
    (far_shin, far_foot), (near_shin, near_foot), (far_arm, far_paw), (near_arm, near_paw) = (
        (limb & floor, end & floor) for limb, end in legs + arms)

    sil = np.zeros((H, W), bool)

    def put(mask, name):
        lab[mask] = IDX[name]

    def layer(*parts):
        """(mask, fill, dark) parts as one piece, outlined against what is behind it."""
        nonlocal sil
        piece = np.zeros((H, W), bool)
        for mask, fill, dark in parts:
            put(mask, fill)
            put(dark_rim(mask), dark)
            piece |= mask
        put(dilate4(piece) & ~piece & sil, 'line')
        sil = sil | piece

    layer((far_shin, 'body_lo', 'body_lo2'), (far_foot, 'paw_lo', 'paw_lo'))
    layer((near_shin, 'body', 'body_lo'), (near_foot, 'paw', 'paw_lo'))
    layer((far_arm, 'body_lo', 'body_lo2'), (far_paw, 'paw_lo', 'paw_lo'))
    layer((body, 'body', 'body_lo'))
    put(body & ~shifted(body, -1, -1) & (YS < 50) & (XS < 20), 'body_hi')
    put(belly, 'belly')
    put(belly & (dark_rim(body) | ~shifted(belly, 1, 1)), 'belly_lo')
    layer((head, 'body', 'body_lo'))
    hi = head & ellipse((PRONE_X - 5.5, top + 2.5), 2.2, 1.2)
    hi |= head & ~shifted(head, -1, -1) & (YS < top + 7) & (XS < PRONE_X + 2)
    put(hi & ~dark_rim(head), 'body_hi')
    layer((near_arm, 'body', 'body_lo'), (near_paw, 'paw', 'paw_lo'))
    put(dilate4(sil) & ~sil, 'line')

    skin = head & ~dilate4(near_arm | near_paw)
    fx = PRONE_X + PRONE_FACE_U

    def face_part(rows, cx, cy):
        x0, y0 = corner(rows, cx, cy, fx)
        stamp(lab, rows, x0, y0, FACE, skin)
        return x0 + len(rows[0]) / 2, y0 + len(rows) / 2

    eye_y = top + PRONE_EYE_DY
    for side in (-1, 1):
        face_part(eye_rows(p['eyes'], p['look'], side), fx + side * EYE_U, eye_y)
        if p['blush']:
            face_part(["pp"], fx + side * (EYE_U + 2.0), eye_y + 5.0)
    centre = face_part(MOUTHS[p['mouth']], fx, mouth_y)
    free, held = draw_props(lab, p['props'])
    return dict(lab=lab, body=dilate4(sil), free=free, held=held,
                mouth=centre if p['mouth'] == 'eat' else None, tint=p['tint'])


def render(p):
    """Pose -> (labels, body mask incl. outline, detached-prop mask, open-mouth centre)."""
    if p['prone']:
        return render_prone(p)
    rig = Rig(p)
    lab = np.zeros((H, W), np.uint8)
    u, v = rig.local()
    trunk = rig.trunk(u, v)
    if p['rot']:   # a turned outline gets 1 px spikes and notches: shave and fill them
        n4 = sum(shifted(trunk, dy, dx).astype(int) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        trunk = np.where(trunk, n4 >= 2, n4 >= 3)
    belly = rig.belly(u, v) & trunk
    if p['sit']:
        legs, feet = np.zeros((H, W), bool), np.zeros((H, W), bool)
        soles = rig.sit_feet(SIT if p['sit'] is True else p['sit'])
    else:
        legs, feet = rig.legs()
        soles = np.zeros((H, W), bool)
    arms = [rig.arm(s, a) for s, a in zip((-1, 1), p['arms'])]

    sil = trunk | legs | feet | soles
    for a, pw in arms:
        sil |= a | pw

    def put(mask, name):
        lab[mask] = IDX[name]

    put(legs, 'body')
    put(legs & ~shifted(legs, 0, 2), 'body_lo')
    put(feet, 'paw')
    put(feet & ~shifted(feet, 0, 1), 'paw_lo')
    put(trunk, 'body')
    # Light from the top left: dark rim bottom right, a highlight on the crown.
    dark = dark_rim(trunk)
    put(dark, 'body_lo')
    put(belly, 'belly')
    put(belly & (dark | ~shifted(belly, 1, 1)), 'belly_lo')
    hi = trunk & ellipse(rig.trunk_pt(-5.0, HB - 3.0), 2.2, 1.2)
    hi |= trunk & ~shifted(trunk, -1, -1) & (v > HB - 9) & (u < 2)
    put(hi & ~dark, 'body_hi')
    put(dilate4(trunk) & legs & ~trunk, 'body_lo2')
    if soles.any():
        put(soles, 'paw')
        put(soles & ~shifted(soles, 1, 1), 'paw_lo')
        put(dilate4(soles) & ~soles & trunk, 'line')
    for a, pw in arms:
        limb = a | pw
        put(a, 'body')
        put(a & ~(shifted(limb, 1, 1) & shifted(limb, 0, 1)), 'body_lo')
        put(pw, 'paw')
        put(pw & ~shifted(pw, 1, 1), 'paw_lo')
        put(dilate4(limb) & ~limb & (trunk | legs | feet | soles), 'line')
    put(dilate4(sil) & ~sil, 'line')
    body = dilate4(sil)

    # Face, behind any paw raised in front of it.
    limbs = np.zeros((H, W), bool)
    for a, pw in arms:
        limbs |= a | pw
    skin = trunk & ~dilate4(limbs)

    def face_part(rows, cx, cy):
        x0, y0 = corner(rows, cx, cy, rig.ox)
        stamp(lab, rows, x0, y0, FACE, skin)
        return x0 + len(rows[0]) / 2, y0 + len(rows) / 2

    fu, fv = p['face']
    for side in (-1, 1):
        face_part(eye_rows(p['eyes'], p['look'], side),
                  *rig.trunk_pt(side * EYE_U + fu, EYE_V + fv))
        if p['blush']:
            face_part(["pp"], *rig.trunk_pt(side * (EYE_U + 2.0) + fu, EYE_V - 5.0 + fv))
    centre = face_part(MOUTHS[p['mouth']], *rig.trunk_pt(fu, MOUTH_V + fv))
    mouth = centre if p['mouth'] == 'eat' else None

    if p['ghost']:
        g = p['ghost']
        lab[shifted(body, 0, g) & ~body & (lab == 0)] = IDX['ghost_r']
        lab[shifted(body, 0, -g) & ~body & (lab == 0)] = IDX['ghost_c']
        body = body | shifted(body, 0, g) | shifted(body, 0, -g)

    # ('box',) with no position rests on the paws, centred on the figure.
    paw_top = int(np.argmax(np.any([pw for _, pw in arms], axis=0).any(axis=1)))
    props = tuple(('box', iround(rig.ox) - len(BOX[0]) // 2, paw_top + 2 - len(BOX))
                  if pr == ('box',) else pr for pr in p['props'])
    free, held = draw_props(lab, props)
    return dict(lab=lab, body=body, free=free, held=held, mouth=mouth, tint=p['tint'])


def to_rgba(frame):
    pal = dict(PALETTE)
    pal.update(TINTS.get(frame['tint'], {}))
    table = np.zeros((len(NAMES) + 1, 4), np.uint8)
    for n, i in IDX.items():
        table[i] = rgb(pal[n]) + (255,)
    return table[frame['lab']]


# ---------------------------------------------------------------- animations
#
# Each animation is a list of (pose, ms). Poses are built from BASE; the mouth used
# for eating ('eat') must stay on one point in every eating animation (snack.mouth).

def P(*bases, **kw):
    """A pose from BASE, then each base dict in order, then the keywords."""
    p = dict(BASE)
    for b in bases:
        p.update(b)
    p.update(kw)
    return p


def anim_idle():
    up = dict(sy=27 / 26)
    dn = dict(sy=25 / 26, sx=1.03, belly=0.5)
    return [
        (P(), 260), (P(up), 200), (P(up), 240), (P(), 200), (P(dn), 240), (P(), 220),
        (P(), 260), (P(up), 200), (P(up), 240), (P(), 200), (P(eyes='closed'), 100),
        (P(), 180),
    ]


def anim_idle_look():
    L = dict(look=(-1, 0), lean=-1, face=(-0.5, 0))
    R = dict(look=(1, 0), lean=1, face=(0.5, 0))
    return [
        (P(), 200), (P(L), 160), (P(L, arms=('down_out', 'down_in')), 360),
        (P(L), 280), (P(), 160), (P(R), 160), (P(R, arms=('down_in', 'down_out')), 360),
        (P(R), 280), (P(eyes='closed'), 100), (P(), 200),
    ]


def anim_idle_giggle():
    g = dict(eyes='happy', mouth='line', arms=('down_in', 'cover'), blush=True)
    a = P(g)
    b = P(g, y=-1, sy=1.02)
    c = P(g, sy=0.97, sx=1.03)
    return [
        (P(look=(1, 0)), 220), (P(eyes='happy', mouth='smile', blush=True), 160),
        (a, 120), (b, 90), (c, 90), (b, 90), (a, 120), (b, 90), (c, 90), (a, 220),
    ]


def ha_at(x, y):
    return ('glyph', 'ha', x, y)


def anim_snack():
    lying = (('glyph', 'semi', 57, 35, 'c4'),)
    chew = dict(arms=('down', 'down_in'), cheeks=1.5)
    return [
        (P(look=(1, 1), props=lying), 240),
        (P(look=(1, 0), arms=('down', 'reach'), lean=1, props=lying), 200),
        (P(look=(1, 0), arms=('down', 'reach'), lean=1,
           props=(('glyph-held', 'semi', 51, 32, 'c4'),)), 160),
        (P(arms=('down', 'feed'), mouth='eat', props=(('code-in', ';', 31, 37, 'c4'),)), 200),
        (P(chew, mouth='chew_a'), 150),
        (P(chew, mouth='chew_b', eyes='happy'), 150),
        (P(chew, mouth='chew_a'), 150),
        (P(mouth='line', eyes='happy'), 200),
        (P(mouth='burp', eyes='closed', sy=1.04, props=(('glyph', 'puff', 41, 18),)), 260),
        (P(mouth='smile', eyes='happy', blush=True), 300),
    ]


def anim_dance():
    base = dict(eyes='happy', mouth='laugh', face=(0, 0.5), arms=('out', 'out'))
    return [
        (P(base, lean=-3, legs='lift_r', arms=('out_dn', 'out_up')), 160),
        (P(base, lean=-4, legs='lift_r', arms=('out_dn', 'out_up'), y=-1), 200),
        (P(base, lean=-3, legs='lift_r', arms=('out_dn', 'out_up')), 160),
        (P(base, lean=-1), 120),
        (P(base, lean=1), 120),
        (P(base, lean=3, legs='lift_l', arms=('out_up', 'out_dn')), 160),
        (P(base, lean=4, legs='lift_l', arms=('out_up', 'out_dn'), y=-1), 200),
        (P(base, lean=3, legs='lift_l', arms=('out_up', 'out_dn')), 160),
        (P(base, lean=1), 120),
        (P(base, lean=-1), 120),
    ]


def anim_thinking():
    t = dict(arms=('chin', 'fold'), look=(1, -1), mouth='line', lean=1)
    q = lambda dy: ('glyph', '?', 44, 14 + dy)
    d = lambda n: tuple(('glyph', '.', 44 + 3 * i, 22) for i in range(n))
    return [
        (P(t, props=d(1)), 300), (P(t, props=d(2)), 300), (P(t, props=d(3)), 300),
        (P(t, look=(0, -1), props=d(3)), 300), (P(t, props=(q(0),)), 220),
        (P(t, props=(q(-1),)), 220), (P(t, look=(0, -1), props=(q(0),)), 300),
        (P(t, eyes='closed', props=(q(0),)), 120),
    ]


def anim_eat_code():
    o = dict(mouth='eat', look=(1, 0))
    chew = dict(mouth='chew_a', cheeks=1, eyes='happy')
    fly = lambda ch, c, i: ('code', ch, (58, 53, 48)[i], (30, 32, 34)[i], c)
    fr = []
    for ch, c in (('{', 'c1'), ('0', 'c3')):
        fr += [(P(o, props=(fly(ch, c, 0),)), 100), (P(o, props=(fly(ch, c, 1),)), 90),
               (P(o, props=(fly(ch, c, 2),)), 90),
               (P(o, look=(0, 0), props=(('code-in', ch, 31, 37, c),)), 110),
               (P(chew), 140), (P(chew, mouth='chew_b'), 140)]
    return fr


def anim_eat_code_fast():
    """Both paws stuff code in turn: one at the mouth while the other grabs the next."""
    seq = [('[', 'c2'), ('(', 'c4'), ('+', 'c1'), (']', 'c2'), (')', 'c4'), (';', 'c5')]
    fr = []
    for i in range(5):
        side = 1 if i % 2 == 0 else -1
        (ch, c), (nxt, nc) = seq[i], seq[i + 1]
        props = (('code-in', ch, 31, 37, c), ('code-held', nxt, 51 if side > 0 else 10, 33, nc))
        fr.append((P(mouth='eat', look=(side, 0),
                     arms=('feed', 'reach') if side > 0 else ('reach', 'feed'), props=props), 90))
        fr.append((P(mouth='chew_a' if side > 0 else 'chew_b', cheeks=1, eyes='happy',
                     arms=('feed', 'feed')), 80))
    return fr


def anim_feast():
    eat = dict(mouth='eat', arms=('feed', 'feed'))
    chew = dict(cheeks=1.5, arms=('belly_up', 'belly_up'), eyes='squeeze')
    sw = lambda k: (('glyph', 'sweat', 17, 19 + k), ('glyph', 'sweat', 44, 18 + k))
    spray = [[(10, 36, 'c1'), (53, 34, 'c2'), (12, 44, 'c5'), (51, 43, 'c4')],
             [(8, 32, 'c2'), (55, 31, 'c1'), (9, 41, 'c4'), (54, 40, 'c5')],
             [(5, 29, 'c5'), (58, 28, 'c4'), (6, 38, 'c1'), (57, 37, 'c2')]]
    cr = lambda k: tuple(('glyph', 'crumb', x, y, c) for x, y, c in spray[k])
    fly = lambda ch, c, side: ('code', ch, 48 if side > 0 else 13, 33, c)
    inn = lambda ch, c: ('code-in', ch, 31, 37, c)
    return [
        (P(eat, props=(inn('{', 'c1'), fly('}', 'c1', 1)) + sw(0)), 70),
        (P(chew, mouth='chew_a', x=1, props=cr(0) + sw(0)), 60),
        (P(eat, props=(inn('}', 'c1'), fly('(', 'c4', -1)) + sw(1)), 60),
        (P(chew, mouth='chew_b', x=-1, props=cr(1) + sw(1)), 60),
        (P(eat, ghost=1, props=(inn('(', 'c4'),) + sw(1)), 60),
        (P(chew, mouth='chew_a', x=1, tint='pink', props=cr(2) + sw(2)), 60),
        (P(chew, mouth='chew_b', x=-1, props=cr(0) + sw(2)), 60),
        (P(eat, props=(inn('=', 'c3'), fly(';', 'c5', 1)) + sw(0)), 70),
        (P(chew, mouth='chew_a', x=1, props=cr(1) + sw(0)), 60),
        (P(eat, props=(inn(';', 'c5'), fly('[', 'c2', -1)) + sw(1)), 60),
        (P(chew, mouth='chew_b', x=-1, tint='cyan', props=cr(0) + sw(1)), 60),
        (P(eat, props=(inn('[', 'c2'),) + sw(2)), 60),
        (P(chew, mouth='chew_a', x=1, ghost=1, props=cr(2) + sw(2)), 60),
        (P(chew, mouth='chew_b', props=cr(1) + sw(0)), 80),
    ]


def anim_juggle():
    """Two code tiles, one fountain per paw, half a cycle apart."""
    ys = [24, 18, 13, 10, 9, 10, 13, 18]
    xs = [4, 4, 5, 6, 6, 6, 5, 4]
    fr = []
    for k in range(8):
        i, j = k, (k + 4) % 8
        props = (('block', '{}', xs[i], ys[i], 'c1'), ('block', '[]', 53 - xs[j], ys[j], 'c2'))
        arms = tuple('toss' if n in (1, 2) else 'catch' for n in (i, j))
        fr.append((P(look=(-1, -1) if ys[i] < ys[j] else (1, -1), mouth='grin', arms=arms,
                     sy=1.02 if k % 4 == 1 else 1.0, props=props), 130))
    return fr


def anim_juggle_many():
    """Four tiles, two per paw: up on the inside, down on the outside, hips swaying."""
    ys = [24, 18, 13, 9, 7, 6, 6, 7, 9, 13, 18, 23]
    xs = [10, 10, 10, 9, 8, 7, 5, 3, 2, 1, 1, 2]
    tiles = [('{', 'c1', 0, -1), ('[', 'c2', 6, -1), ('(', 'c3', 3, 1), ('<', 'c4', 9, 1)]
    fr = []
    for k in range(12):
        props, low = [], {-1: False, 1: False}
        for ch, c, phase, side in tiles:
            i = (k + phase) % 12
            props.append(('block', ch, xs[i] if side < 0 else 57 - xs[i], ys[i], c))
            low[side] |= i in (11, 0)
        lean = [-2, -1, 0, 1, 2, 1, 0, -1, -2, -1, 0, 1][k]
        fr.append((P(mouth='laugh', eyes='happy', face=(0, 0.5), lean=lean,
                     arms=tuple('catch' if low[s] else 'toss' for s in (-1, 1)),
                     legs='step_l' if k % 4 < 2 else 'step_r', props=tuple(props)), 100))
    return fr


def anim_shocked():
    s = dict(eyes='wide', mouth='O', arms=('head', 'head'))
    sw = lambda k: (('glyph', 'sweat', 12, 19 + k), ('glyph', 'sweat', 49, 19 + k))
    bang = (('glyph', '!', 26, 12), ('glyph', '?', 31, 12))
    return [
        (P(s, sy=1.08, y=-2, props=bang), 70), (P(s, x=2, props=bang), 60),
        (P(s, x=-2, props=bang), 60), (P(s, sy=1.08, y=-2, ghost=2, props=bang), 60),
        (P(s, x=2, tint='cyan', props=bang), 60), (P(s, x=-2, props=bang), 60),
        (P(s, x=1, props=bang + sw(0)), 120), (P(s, x=-1, props=bang + sw(1)), 120),
        (P(s, x=1, props=sw(2)), 120), (P(s, x=-1, props=bang + sw(0)), 120),
        (P(s, x=1, props=bang + sw(1)), 120), (P(s, x=-1, props=sw(2)), 120),
    ]


def anim_laugh():
    L = dict(eyes='happy', mouth='laugh', arms=('belly', 'belly'), blush=True, face=(0, 1.5))
    R = dict(L, mouth='roar', face=(0, 2.0), sy=1.07, y=-1)
    return [
        (P(L, sy=1.04), 120),
        (P(R, arms=('belly_up', 'belly_up'), props=(ha_at(49, 10),)), 100),
        (P(L, sy=1.04, props=(ha_at(50, 7),)), 100),
        (P(L, sy=0.97, sx=1.03, belly=1.5, props=(ha_at(51, 4),)), 100),
        (P(L, sy=1.04), 100),
        (P(R, arms=('belly_up', 'belly_up'), props=(ha_at(3, 10),)), 100),
        (P(L, sy=1.04, props=(ha_at(2, 7),)), 100),
        (P(L, sy=0.97, sx=1.03, belly=1.5, props=(ha_at(1, 4),)), 100),
        (P(L, sy=1.04), 100), (P(L, sy=1.0), 140),
    ]


def anim_laugh_point():
    L = dict(eyes='happy', mouth='laugh', arms=('hip', 'point'), face=(0.5, 1.0), lean=1)
    return [
        (P(L), 120), (P(L, sy=1.04, y=-1), 100), (P(L, sy=0.97, sx=1.03), 100),
        (P(L, sy=1.04, y=-1, props=(ha_at(48, 8),)), 100), (P(L, props=(ha_at(48, 6),)), 100),
        (P(L, sy=0.97, sx=1.03), 100), (P(L, sy=1.04, y=-1), 100), (P(L), 140),
    ]


def grounded(p):
    """The pose moved up or down so its lowest pixel sits on the idle foot line."""
    bottom = int(np.nonzero(render(p)['lab'].any(axis=1))[0][-1])
    return dict(p, y=p['y'] + GROUND - 1 - bottom)


def anim_laugh_roll():
    """Rolled onto its back laughing: rocking side to side, soles kicking in the air."""
    R = dict(eyes='happy', mouth='roar', arms=('belly', 'belly'), face=(0, 1.0), blush=True)
    kick = [((-9.0, 4.0), (8.0, -1.0)), ((-8.0, -1.0), (9.0, 4.0))]
    fr = []
    for k, rot in enumerate([0, 12, 22, 12, 0, -12, -22, -12]):
        props = (ha_at(48, 10),) if k in (1, 2) else (ha_at(5, 10),) if k in (5, 6) else ()
        # Rock about the middle of the trunk, not the hips.
        p = P(R, sit=kick[k % 2], rot=rot, x=13 * math.sin(math.radians(rot)), props=props)
        fr.append((grounded(p), 110))
    return fr


def anim_laugh_belly():
    # Both paws press into the middle of the belly; the feet stay planted while
    # the trunk folds and rebounds, readable even at the chat pet's small size.
    hold = ((13.0, 7.0), (4.0, 5.5))
    brace = ((13.0, 7.0), (4.0, 7.0))
    L = dict(eyes='happy', mouth='laugh', arms=(hold, hold), face=(0, 1.5), blush=True)
    J = dict(L, mouth='roar', belly=1.5, sy=0.86, sx=1.07, lean=1.5, arms=(brace, brace))
    U = dict(L, sy=1.08, lean=-1.5)
    return [
        (P(L), 120), (P(J), 90), (P(U), 90), (P(J, props=(ha_at(49, 12),)), 90),
        (P(U, props=(ha_at(50, 9),)), 90), (P(J), 90), (P(U, props=(ha_at(3, 11),)), 90),
        (P(J, props=(ha_at(2, 8),)), 120),
    ]


def anim_alert():
    a = dict(arms=('hip', 'wave'), mouth='grin', eyes='open')
    ex = lambda dy: (('glyph', '!', 31, 14 + dy),)
    return [
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b')), props=ex(-1)), 160),
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b'))), 160),
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b')), props=ex(-1)), 160),
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b'))), 160),
    ]


DEVOUR_LINE = 'fn(x)=>{'    # four bites, four characters showing on the ribbon


def anim_devour():
    """A line of code rides in on a ribbon at mouth height; one character per bite."""
    def ribbon(start):
        return tuple(('code', ch, 48 + 4 * i, 34 - (2 * i) // 3, CODE_COLORS[(start + i) % 6])
                     for i, ch in enumerate(DEVOUR_LINE[start:start + 4]))

    fr = []
    for b in range(4):
        gulp = ('code-in', DEVOUR_LINE[b], 31, 37, CODE_COLORS[b % 6])
        fr += [(P(mouth='eat', look=(1, 0), arms=('down', 'belly'), props=ribbon(b)), 120),
               (P(mouth='eat', arms=('down', 'belly'), props=(gulp,) + ribbon(b + 1)), 100),
               (P(mouth='chew_a', cheeks=1, eyes='happy', arms=('down', 'belly_up'),
                  props=ribbon(b + 1)), 120)]
    return fr


def anim_carry():
    c = dict(arms=('hold', 'hold'), mouth='grin', look=(0, -1), props=(('box',),))
    return [
        (P(c), 140), (P(c, legs='step_l', y=-1), 140), (P(c), 140), (P(c, sy=0.97), 140),
        (P(c), 140), (P(c, legs='step_r', y=-1), 140), (P(c), 140), (P(c, sy=0.97), 140),
    ]


def anim_sleep():
    """Dozing while sitting: the snot bubble swells and shrinks with each breath."""
    s = dict(sit=True, y=2, eyes='shut', mouth='line', arms=('lap', 'lap'))
    z = [[('glyph', 'z', 44, 22)],
         [('glyph', 'z', 44, 21), ('glyph', 'Z', 48, 15)],
         [('glyph', 'z', 44, 20), ('glyph', 'Z', 48, 14)],
         [('glyph', 'Z', 48, 13)]]
    fr = []
    for k, n in enumerate([3, 4, 5, 6, 7, 6, 4, 3]):
        nod = dict(face=(0, -0.5), lean=0.5) if 3 <= k <= 5 else {}
        fr.append((P(s, nod, sy=1.02 if n >= 5 else 1.0,
                     props=(('bubble', 34, 40 - n // 2, n),) + tuple(z[k // 2])), 380))
    return fr


def anim_wake():
    s = dict(sit=True, y=2, arms=('lap', 'lap'))
    return [
        (P(s, eyes='shut', mouth='line'), 260),
        (P(s, eyes='sleepy', mouth='line'), 200),
        (P(eyes='sleepy', mouth='yawn', arms=('stretch', 'stretch'), sy=1.08, y=-1), 300),
        (P(eyes='closed', mouth='yawn', arms=('stretch', 'stretch'), sy=1.1, y=-2), 360),
        (P(eyes='sleepy', mouth='line', sy=0.95, sx=1.04), 160),
        (P(eyes='open', mouth='smile', sy=1.03), 140),
        (P(eyes='closed'), 100),
        (P(), 200),
    ]


def anim_walk():
    return [
        (P(legs='step_l', lean=-1, arms=('down_out', 'down_in')), 140),
        (P(legs='lift_l', lean=-1, y=-1, arms=('down_out', 'down_in')), 120),
        (P(legs='step_l', lean=-1, arms=('down', 'down')), 120),
        (P(lean=0, sy=0.97, sx=1.02), 120),
        (P(legs='step_r', lean=1, arms=('down_in', 'down_out')), 140),
        (P(legs='lift_r', lean=1, y=-1, arms=('down_in', 'down_out')), 120),
        (P(legs='step_r', lean=1, arms=('down', 'down')), 120),
        (P(lean=0, sy=0.97, sx=1.02), 120),
    ]


def anim_poke(direction):
    d = direction
    return [
        (P(eyes='squeeze', mouth='wavy', lean=3 * d, sx=1.05, sy=0.95, x=d), 90),
        (P(eyes='squeeze', mouth='wavy', lean=5 * d, x=d), 110),
        (P(eyes='open', mouth='o', lean=3 * d), 100),
        (P(eyes='open', mouth='o', lean=-2 * d), 110),
        (P(eyes='open', mouth='smile', lean=1 * d), 110),
        (P(eyes='open', mouth='smile', lean=-1 * d), 120),
        (P(eyes='closed'), 100),
        (P(), 160),
    ]


def anim_tickle():
    T = dict(eyes='squeeze', mouth='laugh', arms=('belly', 'belly'), blush=True, face=(0, 1.0))
    U = dict(eyes='happy', mouth='laugh', arms=('flail_a', 'flail_b'), blush=True, face=(0, 1.0))
    return [
        (P(T, x=1), 70), (P(T, x=-1), 60), (P(U, sy=1.06, y=-1, props=(ha_at(50, 8),)), 60),
        (P(T, x=1), 60), (P(T, x=-1, ghost=2), 60), (P(U, sy=1.06, y=-1, props=(ha_at(3, 10),)), 60),
        (P(T, x=2, tint='pink'), 60), (P(T, x=-2), 60),
        (P(U, arms=('flail_b', 'flail_a'), sy=1.06, y=-1, props=(ha_at(50, 6), ha_at(3, 11))), 70),
        (P(T, x=1), 60), (P(T, x=-1), 60), (P(T, sy=0.95, sx=1.04), 100),
        (P(eyes='happy', mouth='smile', blush=True), 160), (P(), 200),
    ]


def anim_prone_eat():
    """Dragged: crawling on its belly with the head up, a forepaw stepping out per bite
    (the diagonal hind foot with it), munching code that flies in from the right."""
    swing = [(-2, 1), (0, 2), (2, 0), (2, 0), (1, 0), (0, 0)]     # forepaw (dx, lift)
    stance = [(0, 0), (0, 0), (-1, 0), (-1, 0), (-2, 0), (-2, 0)]
    lift = [-78, -82, -90, -90, -90, -90]                         # hind shin tilts
    press = [-90, -90, -90, -94, -94, -90]
    rise = [0, 0, 0, 1, 1, 0]
    fr = []
    for b, (ch, c) in enumerate((('{', 'c1'), ('+', 'c2'))):
        def crawl(k, nod=0, **kw):
            paws, kick = (stance[k], swing[k]), (lift[k], press[k])   # (far, near)
            if b:   # the far forepaw steps, with the near hind foot
                paws, kick = paws[::-1], kick[::-1]
            return P(prone=dict(paws=paws, kick=kick, rise=rise[k], nod=nod), **kw)
        fly = lambda x, y: (('code', ch, x, y, c),)
        crumbs = lambda i: tuple(('glyph', 'crumb', *path[i], c) for path in (
            ((58, 40), (59, 44), (59, 48)), ((61, 43), (62, 46), (61, 50))))
        fr += [
            (crawl(0, mouth='eat', look=(1, 0), props=fly(59, 33)), 110),
            (crawl(1, mouth='eat', look=(1, 0), props=fly(57, 39)), 100),
            (crawl(2, mouth='eat', look=(0, 1), props=(('code-in', ch, 42, 44, c),)), 100),
            (crawl(3, nod=1, mouth='chew_a', cheeks=1.5, eyes='squeeze', blush=True,
                   props=crumbs(0)), 130),
            (crawl(4, mouth='chew_b', cheeks=1.5, eyes='happy', blush=True, props=crumbs(1)), 120),
            (crawl(5, mouth='chew_a', cheeks=1.0, eyes='happy', props=crumbs(2)), 120),
        ]
    return fr


ANIMS = {
    'idle': anim_idle, 'idle-look': anim_idle_look, 'idle-giggle': anim_idle_giggle,
    'snack': anim_snack, 'dance': anim_dance, 'thinking': anim_thinking,
    'eat-code': anim_eat_code, 'eat-code-fast': anim_eat_code_fast, 'feast': anim_feast,
    'juggle': anim_juggle, 'juggle-many': anim_juggle_many, 'shocked': anim_shocked,
    'laugh': anim_laugh, 'laugh-point': anim_laugh_point, 'laugh-roll': anim_laugh_roll,
    'laugh-belly': anim_laugh_belly, 'alert': anim_alert, 'devour': anim_devour,
    'carry': anim_carry, 'sleep': anim_sleep, 'wake': anim_wake, 'walk': anim_walk,
    'poke-left': lambda: anim_poke(1), 'poke-right': lambda: anim_poke(-1),
    'tickle': anim_tickle, 'prone-eat': anim_prone_eat,
}


# ---------------------------------------------------------------- pet.json

def pet_json(anims, mouth, mouths):
    return {
        'id': PACK_ID,
        'w': W, 'h': H,
        'anims': [{'key': n, 'durs': anims[n]['durs'], 'loop': n not in ONE_SHOT}
                  for n in ANIM_NAMES],
        'states': {
            'idle': ['idle'], 'thinking': ['thinking'], 'working': ['eat-code'],
            'juggling': ['juggle'], 'error': ['shocked'], 'attention': ['laugh'],
            'notification': ['alert'], 'sweeping': ['devour'], 'carrying': ['carry'],
            'sleeping': ['sleep'], 'waking': ['wake'], 'roam': ['walk'],
        },
        'tiers': {
            'working': [{'min': 3, 'anim': 'feast'}, {'min': 2, 'anim': 'eat-code-fast'},
                        {'min': 1, 'anim': 'eat-code'}],
            'juggling': [{'min': 2, 'anim': 'juggle-many'}, {'min': 1, 'anim': 'juggle'}],
        },
        'idlePool': [
            {'anim': 'idle-look', 'loops': 2, 'weight': 2},
            {'anim': 'idle-giggle', 'loops': 2, 'weight': 2},
            {'anim': 'snack', 'loops': 1, 'weight': 2},
            {'anim': 'dance', 'loops': 2, 'weight': 1},
        ],
        'bonus': {'attention': {'anims': ['laugh-point', 'laugh-roll', 'laugh-belly'],
                                'chance': 0.5}},
        'reactions': {'tapLeft': 'poke-left', 'tapRight': 'poke-right', 'tickle': 'tickle',
                      'drag': 'prone-eat'},
        'holds': {'attention': 3, 'error': 2, 'notification': 2, 'carrying': 2, 'waking': 1,
                  'sweeping': 1},
        'faces': 'front',
        'sounds': 'naiwa',
        'snack': {
            'mouth': {'x': mouth[0], 'y': mouth[1]},
            'mouths': {n: {'x': x, 'y': y} for n, (x, y) in mouths.items()},
            'every': {'eat-code': 700, 'eat-code-fast': 380, 'feast': 200, 'devour': 260,
                      'snack': 1500, 'prone-eat': 260},
        },
    }


def dumps(obj, indent=0):
    """JSON with short values on one line and one animation per line."""
    pad = '  ' * indent
    compact = json.dumps(obj, ensure_ascii=False, separators=(', ', ': '))
    if not isinstance(obj, (dict, list)) or len(compact) <= 96:
        return compact
    if isinstance(obj, list):
        inner = ',\n'.join(pad + '  ' + dumps(x, indent + 1) for x in obj)
        return '[\n' + inner + '\n' + pad + ']'
    inner = ',\n'.join(f'{pad}  {json.dumps(k, ensure_ascii=False)}: {dumps(x, indent + 1)}'
                       for k, x in obj.items())
    return '{\n' + inner + '\n' + pad + '}'


# ---------------------------------------------------------------- build

def draw_all():
    """name -> dict(frames=[rgba], durs=[ms], meta=[render info])."""
    out = {}
    for name in ANIM_NAMES:
        seq = ANIMS[name]()
        metas = [render(p) for p, _ in seq]
        out[name] = dict(frames=[to_rgba(m) for m in metas], durs=[ms for _, ms in seq],
                         meta=metas, poses=[p for p, _ in seq])
    return out


def snack_mouth(anims, names=EATING):
    """The open mouth's centre over the open-mouth frames of `names`, in art pixels."""
    pts = [m['mouth'] for n in names for m in anims[n]['meta'] if m['mouth']]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return iround(float(np.median(xs))), iround(float(np.median(ys)) - 0.5)


def snack_mouths(anims):
    return {n: snack_mouth(anims, [n]) for n in OWN_MOUTH}


def sheet_png(frames):
    """1x single-row strip as PNG bytes: indexed with tRNS when it has <= 256 colours."""
    strip = np.concatenate(frames, axis=1)
    flat = strip.reshape(-1, 4)
    colors, inverse = np.unique(flat, axis=0, return_inverse=True)
    buf = io.BytesIO()
    if len(colors) <= 256:
        im = Image.fromarray(inverse.reshape(strip.shape[:2]).astype(np.uint8), 'P')
        im.putpalette(colors[:, :3].astype(np.uint8).tobytes())
        im.save(buf, 'PNG', optimize=True, transparency=colors[:, 3].astype(np.uint8).tobytes())
    else:
        Image.fromarray(strip, 'RGBA').save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def outputs(anims):
    files = {os.path.join('sheets', f'{n}.png'): sheet_png(anims[n]['frames']) for n in ANIM_NAMES}
    spec = pet_json(anims, snack_mouth(anims), snack_mouths(anims))
    files['pet.json'] = (dumps(spec) + '\n').encode('utf-8')
    return files


# ---------------------------------------------------------------- checks

def blobs8(mask):
    """8-connected components of a bool mask, largest first, as lists of (y, x)."""
    seen = np.zeros_like(mask)
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        stack, comp = [(int(y0), int(x0))], []
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def check(anims, files):
    """Problems as a list of strings (empty when everything holds)."""
    bad = []
    names = list(anims)
    if names != ANIM_NAMES:
        bad.append(f'animations {names} != the {len(ANIM_NAMES)} of naiwa-pet.md section 3')
    total = sum(len(a['durs']) for a in anims.values())
    if total > MAX_TOTAL_FRAMES:
        bad.append(f'{total} frames in total (max {MAX_TOTAL_FRAMES})')
    for n, a in anims.items():
        k = len(a['durs'])
        if not MIN_FRAMES <= k <= MAX_FRAMES:
            bad.append(f'{n}: {k} frames (allowed {MIN_FRAMES}..{MAX_FRAMES})')
        for i, ms in enumerate(a['durs']):
            if not MIN_MS <= ms <= MAX_MS:
                bad.append(f'{n} frame {i}: {ms} ms (allowed {MIN_MS}..{MAX_MS})')
        sheet = np.asarray(Image.open(io.BytesIO(files[os.path.join('sheets', f'{n}.png')])).convert('RGBA'))
        if sheet.shape != (H, W * k, 4):
            bad.append(f'{n}: sheet is {sheet.shape[1]}x{sheet.shape[0]}, want {W * k}x{H}')
            continue
        if not np.array_equal(sheet, np.concatenate(a['frames'], axis=1)):
            bad.append(f'{n}: PNG round trip is not lossless')
        alpha = sheet[..., 3]
        if not np.isin(alpha, (0, 255)).all():
            bad.append(f'{n}: alpha other than 0 / 255')
        if sheet[alpha == 0].any():
            bad.append(f'{n}: transparent pixels that are not 0,0,0,0')
        colors = len(np.unique(sheet.reshape(-1, 4), axis=0))
        if colors > MAX_COLORS:
            bad.append(f'{n}: {colors} colours (max {MAX_COLORS})')
        for i, (fr, m) in enumerate(zip(a['frames'], a['meta'])):
            opaque = fr[..., 3] > 0
            body = m['body'] | m['held']
            if (m['free'] & dilate8(body)).any():
                bad.append(f'{n} frame {i}: a detached prop touches the body')
            comps = blobs8(opaque)
            big = np.zeros_like(opaque)
            for y, x in comps[0]:
                big[y, x] = True
            if not np.array_equal(big, opaque & body):
                bad.append(f'{n} frame {i}: the largest 8-connected blob is not the body')
    idle = anims['idle']
    grounds = {int(np.nonzero(f[..., 3].any(axis=1))[0][-1]) + 1 for f in idle['frames']}
    if grounds != {GROUND}:
        bad.append(f'idle: feet on lines {sorted(grounds)}, want {GROUND}')
    for i, (fr, m) in enumerate(zip(idle['frames'], idle['meta'])):
        if len(blobs8(fr[..., 3] > 0)) != 1:
            bad.append(f'idle frame {i}: has detached props')
    first = idle['frames'][0][..., 3] > 0
    for n in sorted(ONE_SHOT):
        last = anims[n]['frames'][-1][..., 3] > 0
        iou = (first & last).sum() / (first | last).sum()
        if iou < 0.9:
            bad.append(f'{n}: last frame is not back near idle (mask overlap {iou:.0%})')
    points = [(EATING, 'snack.mouth', snack_mouth(anims))]
    points += [([n], f'snack.mouths[{n}]', pt) for n, pt in snack_mouths(anims).items()]
    for names, label, (mx, my) in points:
        for n in names:
            for x, y in (m['mouth'] for m in anims[n]['meta'] if m['mouth']):
                if abs(x - mx) > 1 or abs(y - 0.5 - my) > 1:
                    bad.append(f'{n}: open mouth at ({x}, {y}) is off {label} ({mx}, {my})')
    for i, m in enumerate(anims['prone-eat']['meta']):
        line = int(np.nonzero(m['body'].any(axis=1))[0][-1]) + 1
        if not GROUND <= line <= GROUND + 2:
            bad.append(f'prone-eat frame {i}: belly on line {line}, want {GROUND}..{GROUND + 2}')
    spec = json.loads(files['pet.json'])
    snack = spec['snack']
    for n in sorted(set(snack['mouths']) - set(snack['every'])):
        bad.append(f'snack.mouths: {n} is not in snack.every')
    used = set(sum(spec['states'].values(), []))
    used |= {t['anim'] for ts in spec['tiers'].values() for t in ts}
    used |= {x['anim'] for x in spec['idlePool']} | set(spec['reactions'].values())
    used |= set(spec['bonus']['attention']['anims']) | set(snack['every']) | set(snack['mouths'])
    for n in sorted(used - set(ANIM_NAMES)):
        bad.append(f'pet.json refers to unknown animation {n}')
    for n in sorted(set(ANIM_NAMES) - used):
        bad.append(f'pet.json never uses {n}')
    return bad


def hit_box_report(anims):
    """Runs the pack builder's hit-box rules when its module is importable."""
    sys.path.insert(0, os.path.join(REPO, 'app', 'tool'))
    try:
        import make_pet_pack as mpp
    except Exception as e:   # the builder is optional here
        return [f'hit boxes: make_pet_pack not importable ({e}), skipped'], []
    finally:
        sys.path.pop(0)
    mapping = {'base_idle': 'idle', 'states': {'sleeping': ['sleep']}}
    data = {n: dict(frames=a['frames'], durs=a['durs']) for n, a in anims.items()}
    try:
        hits, _ = mpp.hit_boxes(data, 1, mapping, ANIM_NAMES)
    except mpp.BuildError as e:
        return [], [f'hit boxes: {e}']
    return [f'hit boxes: default {hits["default"]}  wide {hits["wide"]}',
            f'  wideAnims {hits["wideAnims"]}', f'  byAnim {sorted(hits["byAnim"])}'], []


# ---------------------------------------------------------------- preview

def checker(w, h, s=8):
    yy, xx = np.mgrid[0:h, 0:w]
    on = ((yy // s + xx // s) % 2).astype(bool)
    a = np.empty((h, w, 4), np.uint8)
    a[...] = (226, 229, 240, 255)
    a[on] = (246, 247, 252, 255)
    return Image.fromarray(a, 'RGBA')


def preview(anims, path, zoom=4, per_row=8):
    fw = W * zoom
    gap, cap, head = 6, 14, 18
    rows = [(n, math.ceil(len(a['frames']) / per_row)) for n, a in anims.items()]
    width = 12 + per_row * (fw + gap)
    height = 12 + sum(head + r * (fw + cap + gap) for _, r in rows)
    img = Image.new('RGBA', (width, height), (250, 250, 252, 255))
    d = ImageDraw.Draw(img)
    tile = checker(fw, fw)
    y = 12
    for n, r in rows:
        a = anims[n]
        d.text((12, y + 3), f'{n}  {len(a["durs"])} frames  {sum(a["durs"])} ms  '
                            f'{"once" if n in ONE_SHOT else "loop"}', fill=(20, 22, 40))
        y += head
        for k, fr in enumerate(a['frames']):
            rr, cc = divmod(k, per_row)
            x0, y0 = 12 + cc * (fw + gap), y + rr * (fw + cap + gap)
            t = tile.copy()
            t.alpha_composite(Image.fromarray(fr, 'RGBA').resize((fw, fw), Image.NEAREST))
            img.paste(t, (x0, y0))
            d.text((x0 + 2, y0 + fw + 1), f'{k}  {a["durs"][k]}ms', fill=(70, 74, 100))
        y += r * (fw + cap + gap)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert('RGB').save(path)
    return path


def strip(anims, name, path, zoom=4, per_row=4):
    """One animation, wrapped `per_row` frames to a row."""
    a = anims[name]
    fw = W * zoom
    rows = math.ceil(len(a['frames']) / per_row)
    img = Image.new('RGBA', (per_row * (fw + 4), rows * (fw + 4)), (250, 250, 252, 255))
    for k, fr in enumerate(a['frames']):
        t = checker(fw, fw, 16)
        t.alpha_composite(Image.fromarray(fr, 'RGBA').resize((fw, fw), Image.NEAREST))
        img.paste(t, ((k % per_row) * (fw + 4), (k // per_row) * (fw + 4)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert('RGB').save(path)
    return path


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='verify the files on disk, write nothing')
    ap.add_argument('--preview', action='store_true', help='contact sheet in app/build/pet_src_preview')
    ap.add_argument('--strip', nargs='*', default=[], metavar='ANIM', help='4x grid per animation')
    args = ap.parse_args(argv)

    anims = draw_all()
    files = outputs(anims)
    problems = check(anims, files)
    if args.check:
        for rel, data in files.items():
            path = os.path.join(HERE, rel)
            if not os.path.exists(path) or open(path, 'rb').read() != data:
                problems.append(f'{rel} is stale: rerun draw.py')
    else:
        os.makedirs(SHEETS, exist_ok=True)
        for f in os.listdir(SHEETS):
            if f.endswith('.png') and f[:-4] not in ANIM_NAMES:
                os.remove(os.path.join(SHEETS, f))
        for rel, data in files.items():
            with open(os.path.join(HERE, rel), 'wb') as fh:
                fh.write(data)
    info, errors = hit_box_report(anims)
    problems += errors
    total = sum(len(a['durs']) for a in anims.values())
    digest = hashlib.sha256(b''.join(files[k] for k in sorted(files))).hexdigest()[:16]
    print(f'{PACK_ID}: {len(anims)} animations, {total} frames, '
          f'{sum(len(v) for k, v in files.items() if k.endswith(".png")) / 1024:.1f} KB of sheets, '
          f'snack.mouth {snack_mouth(anims)}, mouths {snack_mouths(anims)}, sha256 {digest}')
    for line in info:
        print('  ' + line)
    if args.preview:
        print('  preview ' + preview(anims, os.path.join(PREVIEW_DIR, f'{PACK_ID}.png')))
    for n in args.strip:
        if n not in anims:
            problems.append(f'--strip: unknown animation {n}')
            continue
        print('  strip ' + strip(anims, n, os.path.join(PREVIEW_DIR, PACK_ID, f'{n}.png')))
    for p in problems:
        print(f'error: {p}', file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
