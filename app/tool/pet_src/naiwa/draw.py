#!/usr/bin/env python3
"""Draws 奶蛙 scheme A, the classic yellow one (pack id `naiwa`): pet.json and sheets/<anim>.png.

Run from the repository root (needs numpy and Pillow):

    python app/tool/pet_src/naiwa/draw.py [--check] [--preview [PATH]] [--strip ANIM ...] [--gif ANIM ...] [--gallery DIR] [--completion-previews DIR]

A run redraws all 24 animations, writes sheets/<anim>.png (1x single-row strips of
64x64 cells) and pet.json next to this script, then checks them against
docs/design/naiwa-pet.md sections 3 and 4. `--check` redraws in memory and only
verifies, failing when the files on disk are stale. `--preview` also writes a
contact sheet of every frame (4x on a checkerboard) to
app/build/pet_src_preview/naiwa.png (or PATH); `--strip ANIM` writes a 4x grid of each named
animation to app/build/pet_src_preview/naiwa/ANIM.png; `--gif ANIM` writes an animated
preview beside it, with the original frame timing. `--gallery DIR` writes all
animations as looping 3x GIFs for the README. `--completion-previews DIR` writes
the completion sequence, returning to idle when no new task arrives. No clock and no randomness:
two runs give byte-identical files.

How the art is made: a small rig on integer pixels, no anti-aliasing.

* The trunk (head and body in one piece, no neck) is a per-row half-width profile
  about x = 32: a dome, sides widening to a low belly, a rounded bottom. A pose
  stretches the torso between the hip and a rigid head. The head moves on whole
  pixels without scaling or shearing; a roll rotates the whole figure.
* The belly is an ellipse inside the trunk; an arm is two capsules (shoulder, elbow,
  hand) ending in a 4x4 paw. Arms follow the shoulder without torso distortion;
  the rasterized elbow uses a half-pixel grid and the wrist shares the palm's
  integer anchor. Legs are short capsules on half-ellipse feet.
* Light comes from the top left: a dark rim on the bottom-right edges, a highlight
  on the crown. The outline is the 4-neighbour dilation of all parts minus the
  parts (1 px, stair-stepped); a limb in front of the trunk gets its own outline
  where it overlaps. Where those lines would double up, leave a pinhole or stick
  out by a pixel, the limb grows a pixel to meet the line next to it; the trunk
  and the head keep their shape.
* Every piece moves by whole pixels and all at once: the figure's offset, each
  foot, the belly bulge and the crawl's shins are rounded before drawing, and an
  eased arm is redrawn only when its palm reaches the next pixel. Otherwise each
  part crosses its own rounding on a different frame, and playback ripples.
* Eyes, mouths and props are hand-drawn bitmaps stamped at rig anchors. Detached
  props (哈, Z, !, ?, code glyphs and tiles, crumbs, sweat) get an 8-neighbour
  outline and keep at least one clear pixel from the body, so the pack builder's
  largest-blob rule never counts them as body. Props held in a paw and the
  snot bubble touch the body on purpose.
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
MIN_FRAMES, MAX_FRAMES = 4, 64
MIN_MS, MAX_MS = 40, 400
MAX_TOTAL_FRAMES = 1024
MAX_COLORS = 256

# Animation catalogue order; docs/design/naiwa-pet.md section 2 maps the triggers.
ANIM_NAMES = [
    'idle', 'idle-look', 'idle-giggle', 'snack', 'dance', 'thinking',
    'typing', 'typing-both', 'typing-fast', 'terminal', 'terminals', 'shocked', 'celebrate',
    'laugh-roll', 'alert', 'eat-paper', 'carrying', 'sleep',
    'wake', 'walk', 'poke-left', 'poke-right', 'annoyed', 'crawl',
]
ONE_SHOT = {'celebrate', 'wake', 'poke-left', 'poke-right', 'laugh-roll', 'annoyed'}
EATING = ['eat-paper', 'snack']   # shared upright mouth position

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
    'ghost_r': '#FF3D6E', 'ghost_c': '#2EE6FF',
    'check_green': '#30AF69', 'check_edge': '#186943',
    'deck': '#4B5263',
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
        # At diagonal extremes the pupil's upper-left corner falls on the rim.
        # Keep one highlight on the nearest visible pupil pixel instead.
        hy, hx = c0 + look[1], c0 + look[0]
        py, px = min(((y, x) for y in range(n) for x in range(n) if rows[y][x] == 'k'),
                     key=lambda pt: (pt[0] - hy) ** 2 + (pt[1] - hx) ** 2)
        rows[py][px] = 'w'
        return [''.join(r_) for r_ in rows]
    if kind == 'closed':      # a blink
        return [".......", ".......", ".......", ".ooooo.", ".......", ".......", "......."]
    if kind == 'happy':       # laughing: bold arcs bowed up
        return [".......", ".......", "..ooo..", ".ooooo.", "oo...oo", "o.....o", "......."]
    if kind == 'shut':        # asleep: arcs bowed down
        return [".......", ".......", "o.....o", ".o...o.", "..ooo..", ".......", "......."]
    if kind == 'sleepy':
        return [".......", ".......", "ooooooo", "ogkkkgo", ".ogggo.", "..ooo..", "......."]
    if kind == 'annoyed':     # inward-sloping lids; keep the green iris and highlight
        rows = ["ooo....", "oggooo.", "ogwkkoo", "ogkkkgo", ".ogggo.", "..ooo..", "......."]
        return rows if side < 0 else [r_[::-1] for r_ in rows]
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
    'la': ['..oooooo..', '.owwwwwwo.', 'ommmmmmmmo', 'ommmmmmmmo',
           'ommmmmmmmo', 'ommttttmmo', '.omttttmo.', '..oooooo..'],
    'la_close': ['..oooooo..', '.owwwwwwo.', 'ommmmmmmmo', '.omttttmo.',
                 '..omttmo..', '...oooo...'],
    'eat': ["..oooooo..",               # wide open for code; its centre is upright mouth
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
    'pout': [".oooo.", "o....o"],
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

# Held in front of the belly, under the forepaws. Seen from a little above: the
# back edge is narrower, two staggered rows of keys and a space bar sit on the
# lighter deck, and a darker front edge gives it depth.
KEYBOARD = [
    "..oooooooooooooooooooooooooo..",
    ".odddkkdkkdkkdkkdkkdkkdkkdddo.",
    ".oddddddddddddddddddddddddddo.",
    "odkkdkkdkkdkkdkkdkkdkkdkkdkkdo",
    "oddddddddddddddddddddddddddddo",
    "oddkkkkddkkkkkkkkkkkkddkkkkddo",
    "offffffffffffffffffffffffffffo",
    ".oooooooooooooooooooooooooooo.",
]
KEYBOARD_AT = (17, 48)   # top-left; symmetric about x = 32

# Held against the belly, behind both forepaws. Tape and a downward arrow make
# the parcel read as an import even without a caption or sound.
PARCEL = [
    "oooooooooooooo", "obbbbbttbbbbbo", "obbbbbttbbbbbo", "oooooooooooooo",
    "obbbwwwwwwbbbo", "obbbwwkkwwbbbo", "obbbwwkkwwbbbo", "obbbkkkkkkbbbo",
    "obbbwkkkkwbbbo", "obbbwwkkwwbbbo", "obbbwwwwwwbbbo", "oddddddddddddo",
    "oooooooooooooo",
]

# The paper's lower edge rolls toward the viewer, with its curled end on the right.
PAPER_CURL = [
    '.oooooooo..',
    'owwwwwwwoo.',
    'owwwwwwoswo',
    '.osssssosoo',
    '..ooooooo..',
]


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


def rect_mask(x, y, w, h):
    return (XS >= x) & (XS < x + w) & (YS >= y) & (YS < y + h)


def paper_pixels(x, top, length, offset, bend):
    """A printed sheet feeds upward from a curled lower edge into the mouth."""
    bend = iround_from(bend, 0)   # the lower end sways as one piece, not row after row
    lab = np.zeros((H, W), np.uint8)
    for row in range(length - len(PAPER_CURL)):
        cx = iround(x + bend * (row / max(1, length - 1)) ** 2)
        y = top + row
        lab[rect_mask(cx - 4, y, 8, 1)] = IDX['code_line']
        lab[rect_mask(cx - 3, y, 6, 1)] = IDX['white']
        if (row + offset) % 6 == 2:
            lab[rect_mask(cx - 2, y, 4, 1)] = IDX['c6']
        elif (row + offset) % 6 == 3:
            lab[rect_mask(cx - 2, y, 2, 1)] = IDX['c1']
    stamp(lab, PAPER_CURL, iround(x + bend) - 5, top + length - len(PAPER_CURL),
          {'o': 'code_line', 'w': 'white', 's': 'c6'})
    return lab


def draw_props(lab, props):
    """Paint props over the figure; returns (detached prop pixels, attached prop pixels).

    Kinds: ('glyph', name, x, y[, colour]) and ('code', text, x, y[, colours]) fly free
    with an outline; a '-held' suffix ('glyph-held', 'code-held') marks one held in a
    paw, and '-in' ('code-in') one inside the open mouth, drawn without outline;
    ('block', text, x, y[, colours]) is a juggled code tile, (x, y) its top-left;
    ('bubble', x, y, size) hangs from the face; ('check', x, y, size) is a detached
    green completion badge. ('keyboard', lit) sits under the paws, lit being the
    (x, y, fresh) keys just struck; terminal icons float above the paws;
    paper-held is a printed sheet held against the mouth.
    Held and hanging props may touch the body; the others must not.
    """
    free = np.zeros((H, W), bool)
    held = np.zeros((H, W), bool)
    for pr in props:
        kind = pr[0]
        if kind == 'keyboard':
            stamp(lab, KEYBOARD, *KEYBOARD_AT, {'o': 'code_line', 'd': 'deck', 'k': 'c6', 'f': 'tile'})
            # A struck key flashes white with a glow under it, then stays blue a frame.
            for x, y, fresh in pr[1]:
                lab[rect_mask(x, y, 2, 1)] = IDX['white' if fresh else 'c4']
                if fresh:
                    lab[rect_mask(x, y + 1, 2, 1)] = IDX['c4']
            held |= bitmap_mask(KEYBOARD, *KEYBOARD_AT)
            continue
        if kind == 'terminal':
            x, y, color, phase = pr[1:]
            mask = rect_mask(x, y, 14, 12)
            for xx, yy in ((x, y), (x + 13, y), (x, y + 11), (x + 13, y + 11)):
                mask &= ~((XS == xx) & (YS == yy))
            lab[mask] = IDX['code_line']
            lab[rect_mask(x + 1, y + 1, 12, 10)] = IDX['tile']
            lab[rect_mask(x + 2, y + 1, 10, 2)] = IDX[color]
            stamp(lab, ['X..', '.X.', '..X', '.X.', 'X..'], x + 3, y + 4, {'X': 'white'})
            lab[rect_mask(x + 8, y + 9, 3 if phase < .65 else 1, 1)] = IDX['white']
            free |= mask
            continue
        if kind == 'paper-held':
            paper = paper_pixels(*pr[1:])
            mask = paper != 0
            lab[mask] = paper[mask]
            held |= mask
            continue
        if kind == 'check':
            x, y, size = pr[1:]
            mask = (XS >= x) & (XS < x + size) & (YS >= y) & (YS < y + size)
            for xx, yy in ((x, y), (x + size - 1, y), (x, y + size - 1), (x + size - 1, y + size - 1)):
                mask &= ~((XS == xx) & (YS == yy))
            inside = mask & ~dilate4(~mask)
            lab[mask] = IDX['check_edge']
            lab[inside] = IDX['check_green']
            a = (x + size * .23, y + size * .52)
            b = (x + size * .43, y + size * .72)
            c = (x + size * .79, y + size * .27)
            tick = capsule(a, b, .8) | capsule(b, c, .8)
            lab[tick & inside] = IDX['white']
            free |= mask
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
HEAD_BASE = 12              # the head above this line is rigid; only the torso stretches
HIP_X, HIP_Y = 32.0, 53.0  # trunk bottom centre on the canvas
# Trunk half-width per row, bottom row first. Whole pixels, so at rest every row is
# 2 * hw pixels wide and symmetric about x = 32.
PROFILE = [10, 12, 13, 14, 14, 14, 14, 14, 13, 13, 13, 13, 12, 12, 12, 12,
           11, 11, 11, 11, 11, 11, 10, 9, 7, 5]
assert len(PROFILE) == HB
EYE_U, EYE_V = 6.5, 20.5
MOUTH_V = 14.5
SHOULDER_U, SHOULDER_V = 9.5, 12.5
BELLY_V, BELLY_RX, BELLY_RY = 5.0, 9.0, 7.0
ARM_R, PAW_R = 1.9, 1.75
# Segment lengths measured from the front idle pose, shared with the crawl.
UPPER_ARM, FOREARM = math.hypot(3.0, 3.5), 4.0
GROUND = 60                # idle foot line: the bottom edge of the lowest opaque row
SIT = ((-8.0, -1.5), (8.0, -1.5))   # sole centres when sitting

ARMS = {   # elbow/hand direction targets; lengths come from the front idle pose
    'down': ((12.5, 9.0), (12.5, 5.0)),
    'down_in': ((12.0, 9.0), (11.0, 5.5)),
    'down_out': ((13.0, 9.5), (14.0, 5.5)),
    'hip': ((16.0, 9.5), (11.5, 5.0)),
    'head': ((14.0, 14.0), (15.5, 19.0)),
    'chin': ((9.0, 8.0), (5.0, 10.5)),
    'fold': ((10.0, 8.5), (5.5, 6.5)),
    'out': ((15.5, 13.5), (19.5, 15.5)),
    'out_up': ((15.5, 15.0), (19.0, 19.5)),
    'out_dn': ((15.5, 12.0), (19.5, 11.0)),
    'belly': ((13.0, 8.0), (6.0, 6.0)),
    'belly_up': ((13.0, 8.5), (6.5, 7.5)),
    'cover': ((5.5, 11.0), (2.5, 14.0)),
    'feed': ((12.5, 8.5), (7.0, 13.0)),
    'reach': ((15.5, 12.0), (19.5, 12.0)),
    'wave': ((16.0, 16.0), (17.5, 22.0)),
    'wave_b': ((16.5, 15.5), (20.0, 20.5)),
    'catch': ((15.5, 11.5), (17.0, 16.5)),
    'toss': ((15.0, 14.5), (15.5, 21.0)),
    'stretch': ((12.5, 16.5), (15.0, 21.5)),
    'lap': ((12.0, 7.0), (9.0, 3.5)),
}
PAWS = {'wave': 'open', 'wave_b': 'open'}
LEGS = {   # (left foot, right foot) bottom centres relative to the hip line
    'stand': ((-6.5, -6.0), (6.5, -6.0)),
    'lift_l': ((-8.0, -3.5), (6.5, -6.0)),
    'lift_r': ((-6.5, -6.0), (8.0, -3.5)),
    'step_l': ((-6.0, -4.5), (6.5, -6.0)),
    'step_r': ((-6.5, -6.0), (6.0, -4.5)),
}

BASE = dict(x=0.0, y=0.0, rot=0.0, sy=1.0, lean=0.0,
            eyes='open', look=(0, 0), mouth='smile', face=(0.0, 0.0), blush=False,
            arms=('down', 'down'), legs='stand', sit=False, cheeks=0.0, belly=0.0,
            props=(), tint=None, ghost=0, prone=None, parcel=False, cover_mouth=False,
            open_paws=(False, False))


def pose(base=None, **kw):
    p = dict(BASE if base is None else base)
    p.update(kw)
    return p


class Rig:
    def __init__(self, p):
        self.p = p
        # Place the figure on whole pixels and bulge the belly in half-pixel steps.
        # A fraction would let the hip, head and feet cross their rounding on
        # different frames, and an eased move would then play back as a ripple
        # running through the body. The torso keeps its width in every pose.
        self.ox, self.oy = HIP_X + iround_from(p['x'], 0), HIP_Y + iround(p['y'])
        self.bulge = iround(p['belly'] * 2) / 2
        th = math.radians(p['rot'])
        self.c, self.s = math.cos(th), math.sin(th)
        # Snap the rigid head once, so translating it preserves every outline pixel.
        hx, hy = self.fig(p['lean'] * EYE_V / HB, HEAD_BASE + EYE_V * (p['sy'] - 1))
        self.head_x, self.head_y = iround(hx), iround(hy)
        dx, dy = self.head_x - self.ox, self.oy - self.head_y
        self.head_u = dx * self.c + dy * self.s
        self.head_v = -dx * self.s + dy * self.c

    def hw(self, v):
        hw = np.interp(np.asarray(v, float) - 0.5, np.arange(HB), PROFILE)
        if self.p['cheeks']:
            hw = hw + (self.p['cheeks'] * np.clip(1 - np.abs(v - MOUTH_V) / 3.5, 0, 1)
                       * (v < HEAD_BASE))
        if self.bulge:
            hw = hw + self.bulge * np.clip(1 - np.abs(v - BELLY_V) / 5.0, 0, 1)
        return hw

    def fig(self, u, v):
        """Figure space (rest pose, y up from the hip line) -> canvas."""
        return (self.ox + u * self.c - v * self.s, self.oy - (u * self.s + v * self.c))

    def trunk_pt(self, u, v):
        if v >= HEAD_BASE:
            return (self.head_x + u * self.c - (v - HEAD_BASE) * self.s,
                    self.head_y - u * self.s - (v - HEAD_BASE) * self.c)
        t = v / HEAD_BASE
        return self.fig(u + self.head_u * t, self.head_v * t)

    def face_pt(self, u, v):
        # Snap the face as a group: odd/even bitmap heights otherwise move a frame apart.
        p = self.p
        fu, fv = p['face']
        cx, cy = self.trunk_pt(fu, EYE_V + fv)
        cy = iround(cy - .5) + .5
        dv = v - EYE_V - fv
        du = u - fu
        return cx + du * self.c - dv * self.s, cy - du * self.s - dv * self.c

    def local(self):
        fu, fv = CX - self.ox, self.oy - CY
        u = fu * self.c + fv * self.s
        v = -fu * self.s + fv * self.c
        t = v / self.head_v
        return (np.where(v >= self.head_v, u - self.head_u, u - self.head_u * t),
                np.where(v >= self.head_v, v - self.head_v + HEAD_BASE, t * HEAD_BASE))

    def trunk(self, u, v):
        return (v > 0) & (v < HB) & (np.abs(u) < self.hw(v))

    def belly(self, u, v):
        rx = BELLY_RX + self.bulge
        return (u / rx) ** 2 + ((v - BELLY_V) / BELLY_RY) ** 2 < 1

    def arm_joints(self, side, spec):
        """Move from the shoulder with rigid limbs; torso breathing must not twist them."""
        name = spec if isinstance(spec, str) else None
        (eu, ev), (hu, hv) = ARMS[spec] if name else spec
        sh = self.trunk_pt(side * SHOULDER_U, SHOULDER_V)
        dx, dy = side * (eu - SHOULDER_U), ev - SHOULDER_V
        upper = math.hypot(dx, dy)
        el = (sh[0] + UPPER_ARM * (dx * self.c - dy * self.s) / upper,
              sh[1] - UPPER_ARM * (dx * self.s + dy * self.c) / upper)
        dx, dy = side * (hu - eu), hv - ev
        fore = math.hypot(dx, dy)
        ha = (el[0] + FOREARM * (dx * self.c - dy * self.s) / fore,
              el[1] - FOREARM * (dx * self.s + dy * self.c) / fore)
        return sh, el, ha

    def arm(self, side, spec):
        sh, el, ha = self.arm_joints(side, spec)
        pc = (iround_from(ha[0], self.ox), iround(ha[1]))
        style = PAWS.get(spec) if isinstance(spec, str) else None
        return arm_pixels(sh, el, pc, style == 'open' or self.p['open_paws'][0 if side < 0 else 1])

    def legs(self):
        spec = self.p['legs']
        feet_pts = LEGS[spec] if isinstance(spec, str) else spec
        legs = np.zeros((H, W), bool)
        feet = np.zeros((H, W), bool)
        for side, (fx, fy), (rx, ry) in zip((-1, 1), feet_pts, LEGS['stand']):
            # Step in whole pixels from the standing spot, so the sole keeps its shape.
            fx, fy = rx + iround_from(fx - rx, 0), ry + iround(fy - ry)
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


def joined(m):
    """`m` without its lone pixels: a shade one pixel big reads as a speck."""
    near = np.zeros_like(m)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                near |= shifted(m, dy, dx)
    return m & near


def settle(layers, rigid):
    """Outline the stacked pieces with lines one pixel thick; returns (line, opaque).

    `layers`, back to front, are (masks, border): the masks of one piece's parts
    in paint order, and for a stamped bitmap the outline it brings itself (else
    None). A piece gets a line where it overlaps the pieces behind it, and the
    whole figure gets one around it. Where two of those lines run side by side,
    where they leave a pinhole or a slit one pixel wide, and where one pixel
    sticks out, a few local rules repair it. A part takes over the line pixels
    cleared next to it and its mask grows in place, unless it is one of `rigid`,
    the masks that keep their shape.
    """
    owner = np.zeros((H, W), np.uint8)   # the part seen at each pixel, 1-based
    line = np.zeros((H, W), bool)
    locked = np.zeros((H, W), bool)      # a bitmap's own outline is left alone
    plain = np.zeros((H, W), bool)       # pieces without an outline of their own
    behind = np.zeros((H, W), bool)
    parts, piece_of, rigid_of = [], [None], [True]
    for n, (masks, border) in enumerate(layers):
        piece = np.zeros((H, W), bool) if border is None else border.copy()
        for m in masks:
            parts.append(m)
            piece_of.append(n)
            rigid_of.append(any(m is fixed for fixed in rigid))
            owner[m] = len(parts)
            piece |= m
        line &= ~piece
        locked &= ~piece
        if border is None:
            line |= dilate4(piece) & ~piece & behind
            plain |= piece
        else:
            owner[border] = 0
            line |= border
            locked |= border
        behind |= piece
    line |= dilate4(plain) & ~behind

    def sides(m):
        return shifted(m, 0, -1), shifted(m, -1, 0), shifted(m, 0, 1), shifted(m, 1, 0)

    for _ in range(H):   # settles within a few rounds
        opaque = line | (owner > 0)
        # A line pixel held by one neighbour is a spike: clear it, and let the
        # fill it uncovers become the outline.
        spike = line & ~locked & (sum(s.astype(int) for s in sides(opaque)) <= 1)
        line &= ~spike
        opaque &= ~spike
        bare = opaque & ~line & dilate4(~opaque)
        line |= bare
        # A transparent pixel squeezed from two sides is a pinhole or a slit one
        # pixel wide: draw through it.
        left, up, right, down = sides(opaque)
        slit = ~opaque & ((left & right) | (up & down))
        line |= slit
        opaque |= slit
        changed = bool(spike.any() or bare.any() or slit.any())
        # A line pixel away from the edge whose fill neighbours are all one piece
        # separates nothing. Give it to that piece, the pieces in front first, when
        # it doubles a line (it lies in a 2 x 2 block of line, or an overlap line
        # steps along the contour as the inner corner of a stair) or ends a line
        # poking into the fill.
        left, up, right, down = sides(opaque)
        inner = np.argwhere(line & ~locked & left & up & right & down)
        for n in reversed(range(len(layers))):
            for y, x in inner:
                if not line[y, x]:
                    continue
                l, u, r, d = line[y, x - 1], line[y - 1, x], line[y, x + 1], line[y + 1, x]
                found = [owner[y + dy, x + dx] for (dy, dx), drawn
                         in zip(((0, -1), (-1, 0), (0, 1), (1, 0)), (l, u, r, d)) if not drawn]
                if not found or {piece_of[q] for q in found} != {n}:
                    continue
                block = ((l and u and line[y - 1, x - 1]) or (u and r and line[y - 1, x + 1])
                         or (r and d and line[y + 1, x + 1]) or (d and l and line[y + 1, x - 1]))
                stair = len(found) == 2 and l != r and owner[y, x]
                if not (block or stair or len(found) >= 3):
                    continue
                if piece_of[owner[y, x]] != n:   # the piece has to grow into it
                    free = [q for q in found if not rigid_of[q]]
                    if not free:
                        continue
                    owner[y, x] = free[0]
                line[y, x] = False
                changed = True
        if not changed:
            break
    for i, m in enumerate(parts, 1):
        m |= (owner == i) & ~line
    return line, line | (owner > 0)


def arm_pixels(shoulder, elbow, hand, open_paw=False):
    """Rasterize one articulated piece, with its wrist attached to the snapped palm."""
    shoulder = tuple(iround(v * 2) / 2 for v in shoulder)
    elbow = tuple(iround(v * 2) / 2 for v in elbow)
    paw = ellipse(hand, 2.0, 1.9) if open_paw else ellipse(hand, PAW_R, PAW_R)
    dx, dy = hand[0] - elbow[0], hand[1] - elbow[1]
    wrist = ((CX - hand[0]) * dx + (CY - hand[1]) * dy
             < -PAW_R / 2 * math.hypot(dx, dy))
    arm = capsule(shoulder, elbow, ARM_R) | (capsule(elbow, hand, ARM_R) & wrist)
    return arm & ~paw, paw


# ---------------------------------------------------------------- lying on its belly
#
# crawl, played while dragged, has a figure of its own seen from the side: crawling
# on its belly with the rump on the left and the legs stretched out behind it, the head
# at the right end held up on the forepaws and turned to the viewer.

PRONE_TOP, PRONE_X = 34, 41.0    # head: top row, centre line
# Head half-width per row from the top: the idle dome squashed.
PRONE_HEAD = [5, 7, 9, 10, 11, 11, 12, 12, 12, 13, 13, 13, 13, 13, 13, 12, 12, 11, 9]
PRONE_FACE_U = 2.0               # the face turned a little to the right
PRONE_EYE_DY, PRONE_MOUTH_DY = 5.5, 12.0   # below the head's top row
# Body: a round rump and a lower chest under the head (centre, radii), cut flat by the floor.
PRONE_BODY = (((16.0, 52.0), 8.5, 7.5), ((30.0, 53.5), 13.0, 6.0))
PRONE_KNEES = ((12.0, 55.0), (13.0, 55.5))  # far and near shin pivots, inside the rump
PRONE_SHIN = 6.5
PRONE_SHOULDERS = ((43.0, 52.0), (30.5, 51.0))  # far side hidden by chest; near side below face
PRONE_PAWS = ((46.0, 57.0), (32.0, 57.0))


def prone_shin(knee, deg):
    """A shin tilted from upright (-90 lies behind), ending in a slim rounded foot."""
    # Swing in steps of about one pixel at the ankle, so the shin never creeps.
    step = math.degrees(1 / PRONE_SHIN)
    a = math.radians(step * iround((deg + 90) / step) - 90)
    dx, dy = math.sin(a), -math.cos(a)
    ank = (knee[0] + PRONE_SHIN * dx, knee[1] + PRONE_SHIN * dy)
    sole = (ank[0] + .8 * dx, ank[1] + .8 * dy)
    fu, fv = CX - sole[0], CY - sole[1]
    along, across = fu * dx + fv * dy, fu * dy - fv * dx
    foot = (across / 1.8) ** 2 + (along / 2.6) ** 2 < 1
    return capsule(knee, ank, 2.3) & ~foot, foot


def prone_arm(shoulder, paw, step):
    """Bend two fixed-length arm segments to reach the paw, with the elbow behind it."""
    pc = (iround(paw[0] + step[0]), iround(paw[1] - step[1]))
    dx, dy = pc[0] - shoulder[0], pc[1] - shoulder[1]
    distance = math.hypot(dx, dy)
    if not abs(UPPER_ARM - FOREARM) < distance < UPPER_ARM + FOREARM:
        raise ValueError(f'prone paw outside short-arm reach: {distance}')
    along = (UPPER_ARM ** 2 - FOREARM ** 2 + distance ** 2) / (2 * distance)
    bend = math.sqrt(UPPER_ARM ** 2 - along ** 2)
    elbow = (shoulder[0] + (along * dx - bend * dy) / distance,
             shoulder[1] + (along * dy + bend * dx) / distance)
    return arm_pixels(shoulder, elbow, pc)


def render_prone(p):
    q = p['prone']
    lab = np.zeros((H, W), np.uint8)
    floor = YS < GROUND - 1          # the outline takes the last row
    top = PRONE_TOP + q.get('nod', 0)
    mouth_y = top + PRONE_MOUTH_DY
    hw = np.asarray(PRONE_HEAD, float)[np.clip(YS - top, 0, len(PRONE_HEAD) - 1)]
    head = (YS >= top) & (YS < top + len(PRONE_HEAD)) & (np.abs(CX - PRONE_X) < hw) & floor
    (rump_c, rump_rx, rump_ry), (chest_c, chest_rx, chest_ry) = PRONE_BODY
    rise = iround(q.get('rise', 0))  # the rump bobs a whole pixel as the hind feet push
    body = (ellipse((rump_c[0], rump_c[1] - rise / 2), rump_rx, rump_ry + rise / 2)
            | ellipse(chest_c, chest_rx, chest_ry)) & floor
    belly = ellipse((21.0, 58.5), 12.5, 4.5) & body
    legs = [prone_shin(k, a) for k, a in zip(PRONE_KNEES, q['kick'])]
    arms = [prone_arm(s, pw, st) for s, pw, st in zip(PRONE_SHOULDERS, PRONE_PAWS, q['paws'])]
    (far_shin, far_foot), (near_shin, near_foot), (far_arm, far_paw), (near_arm, near_paw) = (
        (limb & floor, end & floor) for limb, end in legs + arms)

    # Each piece is outlined against what is behind it; the body and the head keep
    # their shape, the limbs may grow a pixel.
    line, figure = settle([((far_shin, far_foot), None), ((near_shin, near_foot), None),
                           ((far_arm, far_paw), None), ((body,), None), ((head,), None),
                           ((near_arm, near_paw), None)], rigid=(body, head))

    def put(mask, name):
        lab[mask] = IDX[name]

    def layer(*parts):
        for mask, fill, dark in parts:
            put(mask, fill)
            put(dark_rim(mask), dark)

    layer((far_shin, 'body_lo', 'body_lo2'), (far_foot, 'paw_lo', 'paw_lo'))
    layer((near_shin, 'body', 'body_lo'), (near_foot, 'paw', 'paw_lo'))
    layer((far_arm, 'body_lo', 'body_lo2'), (far_paw, 'paw_lo', 'paw_lo'))
    layer((body, 'body', 'body_lo'))
    put(body & ~shifted(body, -1, -1) & (YS < 50) & (XS < 20), 'body_hi')
    put(belly, 'belly')
    put(joined(belly & (dark_rim(body) | ~shifted(belly, 1, 1))), 'belly_lo')
    layer((head, 'body', 'body_lo'))
    hi = head & ellipse((PRONE_X - 5.5, top + 2.5), 2.2, 1.2)
    hi |= head & ~shifted(head, -1, -1) & (YS < top + 7) & (XS < PRONE_X + 2)
    put(hi & ~dark_rim(head), 'body_hi')
    layer((near_arm, 'body', 'body_lo'), (near_paw, 'paw', 'paw_lo'))
    put(line, 'line')

    skin = head & ~dilate4(near_arm | near_paw)
    fx = PRONE_X + PRONE_FACE_U

    def face_part(rows, cx, cy):
        x0, y0 = corner(rows, cx, cy, fx)
        stamp(lab, rows, x0, y0, FACE, skin)
        return x0 + len(rows[0]) / 2, y0 + len(rows) / 2

    eye_y = top + PRONE_EYE_DY
    for side in (-1, 1):
        face_part(eye_rows(p['eyes'], p['look'], side), fx + side * EYE_U, eye_y)
    face_part(MOUTHS[p['mouth']], fx, mouth_y)
    return dict(lab=lab, body=figure, free=np.zeros_like(figure), held=np.zeros_like(figure),
                mouth=None, tint=p['tint'])


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

    # The trunk and the parcel keep their shape; the limbs may grow a pixel.
    layers = [((legs, feet, trunk), None), ((soles,), None)]
    rigid = [trunk]
    if p['parcel']:
        x0, y0 = corner(PARCEL, *rig.trunk_pt(0, 4), rig.ox)
        frame = bitmap_mask([''.join(c if c == 'o' else '.' for c in row) for row in PARCEL], x0, y0)
        rigid.append(bitmap_mask(PARCEL, x0, y0) & ~frame)
        layers.append(((rigid[-1],), frame))
    layers += [(arm, None) for arm in arms]
    line, body = settle(layers, rigid)

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
    put(joined(belly & (dark | ~shifted(belly, 1, 1))), 'belly_lo')
    hi = trunk & ellipse(rig.trunk_pt(-5.0, HB - 3.0), 2.2, 1.2)
    hi |= trunk & ~shifted(trunk, -1, -1) & (v > HB - 9) & (u < 2)
    put(hi & ~dark, 'body_hi')
    put(dilate4(trunk) & legs & ~trunk, 'body_lo2')
    put(soles, 'paw')
    put(soles & ~shifted(soles, 1, 1), 'paw_lo')
    if p['parcel']:
        stamp(lab, PARCEL, x0, y0,
              {'o': 'line', 'b': 'c3', 't': 'belly', 'd': 'body_lo2', 'w': 'white', 'k': 'code_line'})
    for a, pw in arms:
        limb = a | pw
        put(a, 'body')
        put(a & ~(shifted(limb, 1, 1) & shifted(limb, 0, 1)), 'body_lo')
        put(pw, 'paw')
        put(pw & ~shifted(pw, 1, 1), 'paw_lo')
    put(line, 'line')

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
                  *rig.face_pt(side * EYE_U + fu, EYE_V + fv))
        if p['blush']:
            face_part(["pp"], *rig.face_pt(side * (EYE_U + 2.0) + fu, EYE_V - 5.0 + fv))
    centre = face_part(MOUTHS[p['mouth']], *rig.face_pt(fu, MOUTH_V + fv))
    mouth = centre if p['mouth'] == 'eat' else None

    if p['ghost']:
        g = p['ghost']
        lab[shifted(body, 0, g) & ~body & (lab == 0)] = IDX['ghost_r']
        lab[shifted(body, 0, -g) & ~body & (lab == 0)] = IDX['ghost_c']
        body = body | shifted(body, 0, g) | shifted(body, 0, -g)

    under = {pr[0] for pr in p['props']} & {'keyboard', 'paper-held'}
    if under:
        before_props = lab.copy()
    free, held = draw_props(lab, p['props'])
    if under:
        # The paws stay in front of the paper; whole arms in front of the keyboard.
        front = np.zeros((H, W), bool)
        for a, pw in arms:
            front |= (a | pw) if 'keyboard' in under else pw
        mask = dilate4(front) & body
        lab[mask] = before_props[mask]
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
# for eating ('eat') must stay on one point in every eating animation (upright mouth).

def P(*bases, **kw):
    """A pose from BASE, then each base dict in order, then the keywords."""
    p = dict(BASE)
    for b in bases:
        p.update(b)
    p.update(kw)
    return p


def anim_idle():
    fr = []
    for t, ms in frame_times(2540):
        breath = (1 - math.cos(2 * math.pi * t / 2540)) / 2
        p = P()
        # One breath is one whole-pixel rise: chest, belly and arms move on the same
        # frame. Keep torso width fixed so it cannot protrude past the arms.
        inhale = breath > .7
        p.update(sy=1.035 if inhale else 1, belly=.5 if inhale else 0,
                 eyes='closed' if 2220 <= t < 2320 else 'open')
        fr.append((p, ms))
    return fr


def anim_idle_look():
    L = dict(look=(-1, 0), lean=-1, face=(-0.5, 0))
    R = dict(look=(1, 0), lean=1, face=(0.5, 0))
    return [
        (P(), 200), (P(L), 160), (P(L, arms=('down_out', 'down_in')), 360),
        (P(L), 280), (P(), 160), (P(R), 160), (P(R, arms=('down_in', 'down_out')), 360),
        (P(R), 280), (P(eyes='closed'), 100), (P(), 200),
    ]


def anim_idle_giggle():
    g = dict(eyes='happy', mouth='line', arms=('down_in', 'cover'), blush=True, cover_mouth=True)
    a = P(g)
    b = P(g, sy=1.02)
    c = P(g, sy=0.97)
    return [
        (P(look=(1, 0)), 220), (P(eyes='happy', mouth='smile', blush=True), 160),
        (a, 120), (b, 90), (c, 90), (b, 90), (a, 120), (b, 90), (c, 90), (a, 220),
    ]


def ha_at(x, y):
    return ('glyph', 'ha', x, y)


def anim_snack():
    chew = dict(arms=('down', 'down_in'), cheeks=1.5)
    keys = [
        (P(look=(1, 1)), 240),
        (P(look=(1, 0), arms=('down', 'reach'), lean=1), 200),
        (P(look=(1, 0), arms=('down', 'reach'), lean=1), 160),
        (P(arms=('down', 'feed'), mouth='eat'), 200),
        (P(chew, mouth='chew_a'), 150),
        (P(chew, mouth='chew_b', eyes='happy'), 150),
        (P(chew, mouth='chew_a'), 150),
        (P(mouth='line', eyes='happy'), 200),
        (P(mouth='burp', eyes='closed', sy=1.04, props=(('glyph', 'puff', 41, 18),)), 260),
        (P(mouth='smile', eyes='happy', blush=True), 300),
    ]
    fr, t = [], 0
    for pose, ms in smooth_sequence(keys, loop=True):
        if t < 800:
            if t < 440:
                u = max(0, (t - 240) / 200)
                x, y = iround(57 - 6 * u), iround(35 - 3 * u)
            else:
                u = (t - 440) / 360
                x = iround(51 - 20 * u)
                y = iround(32 + 5 * u + 3 * math.sin(math.pi * u))
            if x <= 40:
                pose['props'] = (('code-in', ';', x, y, 'c4'),)
            else:
                prop = ('glyph', 'semi', x, y, 'c4')
                body = render(pose)['body']
                free, _ = draw_props(np.zeros((H, W), np.uint8), (prop,))
                # The symbol becomes held at actual paw contact, not at a fixed frame index.
                kind = 'glyph-held' if (free & dilate8(body)).any() else 'glyph'
                pose['props'] = ((kind, *prop[1:]),)
            if t >= 560:
                pose['mouth'] = 'eat'
        fr.append((pose, ms))
        t += ms
    return fr


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
    # Short arms stay below the mouth: one paw touches the side of the chin,
    # the other rests on the belly. The feet stay planted during the lean.
    t = dict(arms=('chin', 'fold'), look=(1, -1), mouth='line')
    q = lambda dy: ('glyph', '?', 44, 14 + dy)
    d = lambda n: tuple(('glyph', '.', 44 + 3 * i, 22) for i in range(n))
    return [
        (P(t, lean=0, props=d(1)), 260),
        (P(t, lean=1, sy=1.02, props=d(1)), 220),
        (P(t, lean=1, sy=1.04, props=d(2)), 280),
        (P(t, lean=1, sy=1.04, look=(0, -1), props=d(3)), 300),
        (P(t, lean=1, sy=1.02, look=(0, -1), props=d(3)), 200),
        (P(t, lean=0, eyes='closed', props=d(3)), 120),
        (P(t, lean=-1, sy=0.98, look=(-1, -1), props=(q(0),)), 280),
        (P(t, lean=-1, sy=0.98, look=(-1, -1), props=(q(-1),)), 300),
        (P(t, lean=-1, look=(0, -1), props=(q(0),)), 280),
        (P(t, lean=0, look=(0, -1), props=(q(0),)), 220),
        (P(t, lean=0, look=(0, -1), props=d(2)), 200),
        (P(t, lean=0, props=d(1)), 180),
    ]


def food_at(p, ch, x, y, color):
    """Classify a travelling character at body contact, then inside the open mouth."""
    body = render(P(p, props=()))['body']
    glyph = bitmap_mask(CODE_FONT[ch], x, y)
    if not (glyph & ~body).any():
        kind = 'code-in'
    elif (dilate8(glyph) & dilate8(body)).any():
        kind = 'code-held'
        p['cover_mouth'] = True
    else:
        kind = 'code'
    return kind, ch, x, y, color


def reach(p, side, palm):
    """Arm spec putting the palm on canvas point `palm`, the elbow bent outward.

    The elbow follows from the shoulder and the whole-pixel palm alone, so the
    arm is redrawn only when one of them moves. Upright poses only (no `rot`).
    """
    sx, sy = Rig(p).trunk_pt(side * SHOULDER_U, SHOULDER_V)
    dx, dy = palm[0] - sx, palm[1] - sy
    d = math.hypot(dx, dy)
    if not UPPER_ARM - FOREARM < d < UPPER_ARM + FOREARM:
        raise ValueError(f'palm {palm} outside short-arm reach: {d}')
    along = (UPPER_ARM ** 2 - FOREARM ** 2 + d * d) / (2 * d)
    out = math.sqrt(UPPER_ARM ** 2 - along ** 2)
    ex = sx + (along * dx + out * side * dy) / d
    ey = sy + (along * dy - out * side * dx) / d
    eu, ev = SHOULDER_U + side * (ex - sx), SHOULDER_V - (ey - sy)
    return (eu, ev), (eu + side * (palm[0] - ex), ev - (palm[1] - ey))


# Left palm points over keys, in the order one paw works through them: back row,
# then front row. A palm at (x, y) strikes the key just below its outline, whose
# left pixel is (x - 1, y + 3). The right paw uses the mirror image, x -> 64 - x.
# All lie under or inside the shoulder: a palm outside it folds the short arm and
# throws the elbow out like a wing.
TYPING_KEYS = [(23, 46), (26, 46), (26, 48), (23, 48)]
TYPING_REST = (21, 47)       # the left paw holding the keyboard by its back corner
CODE_TOKENS = '{;}()<>[]+fn0x'
GLYPH_COLORS = CODE_COLORS[:5]   # the grey one is too faint for a lone glyph


def paw_path(strikes, frames):
    """Palm point per frame for one paw striking (frame, point) in turn, looping.

    The paw stays on the key a frame or two, lifts two pixels, travels while up
    and comes down on the next key.
    """
    path = [None] * frames
    for i, (start, a) in enumerate(strikes):
        end, b = strikes[(i + 1) % len(strikes)]
        span = (end - start) % frames or frames
        down = 1 if span <= 5 else 2
        lift = [0] * down + [1] + [2] * (span - down - 2) + [1]
        for k in range(span):
            w = min(1, max(0, (k - down) / (span - down - 1)))
            path[(start + k) % frames] = (iround_from(a[0] + (b[0] - a[0]) * w, 32),
                                          iround(a[1] + (b[1] - a[1]) * w) - lift[k])
    return path


def anim_typing(tier):
    """One paw typing while the other holds the keyboard, both paws taking turns,
    then rapid typing. Every keystroke lights its key and sends up a code glyph."""
    frames = 40
    right_keys = [(64 - x, y) for x, y in TYPING_KEYS]
    if tier == 1:
        times = [0, 4, 12, 20, 24, 32]      # tap-tap, tap, tap-tap, tap
        order = [0, 0, 1, 2, 2, 3]
        paws = {1: [(f, right_keys[k]) for f, k in zip(times, order)]}
        glyphs = [(f, (37, 42)[i % 2]) for i, f in enumerate(times)]
        life, rise = 14, 1
    else:
        step = 8 if tier == 2 else 4         # each paw's beat; the other paw is half a beat later
        paws = {side: [(f, keys[i % len(keys)])
                       for i, f in enumerate(range(0 if side < 0 else step // 2, frames, step))]
                for side, keys in ((-1, TYPING_KEYS), (1, right_keys))}
        columns = {2: {-1: (22,), 1: (39,)}, 3: {-1: (16, 24), 1: (37, 45)}}[tier]
        glyphs = sorted((f, columns[side][i % len(columns[side])])
                        for side, strikes in paws.items() for i, (f, _) in enumerate(strikes))
        life, rise = (14, 1) if tier == 2 else (7, 2)   # rapid typing: quick, short-lived glyphs
    paths = {side: paw_path(strikes, frames) for side, strikes in paws.items()}
    if tier == 1:
        paths[-1] = [TYPING_REST] * frames
    fr = []
    for f, (t, ms) in enumerate(frame_times(2000, 50)):
        p = P(mouth='grin', look=(0, 1), eyes='closed' if f in (36, 37) else 'open',
              sy=.97 if tier == 3 and f % 8 < 2 else 1.0)   # rapid typing: a dip every other stroke
        p['arms'] = tuple(reach(p, side, paths[side][f]) for side in (-1, 1))
        lit = tuple((x - 1, y + 3, f == s) for strikes in paws.values() for s, (x, y) in strikes
                    if (f - s) % frames < 2)
        props = [('keyboard', lit)]
        for i, (s, x) in enumerate(glyphs):
            age = (f - s) % frames
            if age < life:
                props.append(('code', CODE_TOKENS[i % len(CODE_TOKENS)], x, 18 - age * rise,
                              GLYPH_COLORS[i % len(GLYPH_COLORS)]))
        p['props'] = tuple(props)
        fr.append((p, ms))
    return fr


def anim_terminals(count):
    """Small >_ terminal icons respond to one or alternating pointing paws."""
    fr = []
    for t, ms in frame_times(2000, 50):
        phase = t / 2000
        cue = (1 - math.cos(2 * math.pi * phase)) / 2
        a = P(arms=('belly', 'wave'))
        b = P(arms=('wave', 'belly') if count > 1 else ('belly', 'wave_b'))
        p = between_poses(a, b, cue)
        p.update(mouth='grin', look=(-1 if count > 1 and cue > .5 else 1, -1))
        props = [('terminal', 43, iround(12 + math.sin(2 * math.pi * phase)), 'c4', phase)]
        if count > 1:
            props.append(('terminal', 7, iround(12 - math.sin(2 * math.pi * phase)), 'c1', (phase + .5) % 1))
        p['props'] = tuple(props)
        fr.append((p, ms))
    return fr


def anim_shocked():
    fr = []
    for t, ms in frame_times(1090, 50):
        phase = 2 * math.pi * t / 1090
        hop = math.sin(phase) ** 2
        sweat = iround(19 + math.sin(phase) ** 2 * 2)
        fr.append((P(eyes='wide', mouth='O', arms=('head', 'head'), face=(0, -.7),
                     x=1.5 * math.sin(3 * phase), sy=1 + .04 * hop, y=-hop,
                     props=(('glyph', '!', 26, 12), ('glyph', '?', 31, 12),
                            ('glyph', 'sweat', 12, sweat), ('glyph', 'sweat', 49, sweat))), ms))
    return fr


def between_poses(a, b, t):
    """Ease between standing poses; redraw limbs at their fixed segment lengths."""
    if t in (0, 1):
        return dict(a if t == 0 else b)
    u = t * t * (3 - 2 * t)
    p = dict(a if t < .5 else b)
    for key in ('x', 'y', 'rot', 'sy', 'lean', 'cheeks', 'belly'):
        p[key] = a[key] + (b[key] - a[key]) * u
    p['face'] = tuple(x + (y - x) * u for x, y in zip(a['face'], b['face']))
    if a['look'] != b['look']:
        p['look'] = tuple(iround(x + (y - x) * u) for x, y in zip(a['look'], b['look']))
    p['cover_mouth'] = a['cover_mouth'] or b['cover_mouth']
    p['open_paws'] = tuple(a['open_paws'][i] or b['open_paws'][i]
                          or (isinstance(aa, str) and PAWS.get(aa) == 'open')
                          or (isinstance(ab, str) and PAWS.get(ab) == 'open')
                          for i, (aa, ab) in enumerate(zip(a['arms'], b['arms'])))
    if a['legs'] != b['legs']:
        fa = LEGS[a['legs']] if isinstance(a['legs'], str) else a['legs']
        fb = LEGS[b['legs']] if isinstance(b['legs'], str) else b['legs']
        p['legs'] = tuple(tuple(x + (y - x) * u for x, y in zip(va, vb)) for va, vb in zip(fa, fb))
    if a['prone'] and b['prone']:
        qa, qb = a['prone'], b['prone']
        p['prone'] = {
            'paws': tuple(tuple(x + (y - x) * u for x, y in zip(va, vb))
                          for va, vb in zip(qa['paws'], qb['paws'])),
            'kick': tuple(x + (y - x) * u for x, y in zip(qa['kick'], qb['kick'])),
            'rise': qa['rise'] + (qb['rise'] - qa['rise']) * u,
            'nod': iround(qa['nod'] + (qb['nod'] - qa['nod']) * u),
        }
    p['arms'] = []
    for aa, ab in zip(a['arms'], b['arms']):
        ja = [(SHOULDER_U, SHOULDER_V), *(ARMS[aa] if isinstance(aa, str) else aa)]
        jb = [(SHOULDER_U, SHOULDER_V), *(ARMS[ab] if isinstance(ab, str) else ab)]
        sweeps = []
        for i in range(2):
            start = math.atan2(ja[i + 1][1] - ja[i][1], ja[i + 1][0] - ja[i][0])
            end = math.atan2(jb[i + 1][1] - jb[i][1], jb[i + 1][0] - jb[i][0])
            sweeps.append((start, (end - start + math.pi) % (2 * math.pi) - math.pi))

        def swung(w):
            joints = [(SHOULDER_U, SHOULDER_V)]
            for (start, sweep), length in zip(sweeps, (UPPER_ARM, FOREARM)):
                x, y = joints[-1]
                angle = start + sweep * w
                joints.append((x + length * math.cos(angle), y + length * math.sin(angle)))
            return tuple(joints[1:])

        def cell(k):   # the palm's pixel, rounded as Rig.arm rounds it
            hu, hv = swung(k / 32)[1]
            return iround(hu), iround(-hv)

        # One drawing of the arm for each pixel its palm visits: the elbow and the
        # palm then change on the same frame, where a free elbow would creep along
        # the arm's edge between palm steps. Both key poses stay exact.
        lo = hi = iround(u * 32)
        here = cell(lo)
        while lo > 0 and cell(lo - 1) == here:
            lo -= 1
        while hi < 32 and cell(hi + 1) == here:
            hi += 1
        if lo > 0 and hi < 32:
            k = (lo + hi) // 2      # between the keys: the middle of this pixel's span
        elif lo > 0 or (hi == 32 and u >= .5):
            k = 32                  # already on key pose b's pixel
        else:
            k = 0
        p['arms'].append(swung(k / 32))
    return p


def frame_times(total, step=60):
    """Split a duration into GIF-exact 10 ms ticks, preserving its total."""
    count = max(1, round(total / step))
    edges = [round(i * total / count / 10) * 10 for i in range(count + 1)]
    return [(a, b - a) for a, b in zip(edges, edges[1:])]


def between_props(a, b, t):
    """Move the same prop along its path; appearing and swallowed props change on the beat."""
    out = []
    for i, prop in enumerate(a if t < .5 else b):
        if i >= len(a) or i >= len(b):
            out.append(prop)
            continue
        first, last = a[i], b[i]
        if first[0] == last[0] == 'bubble':
            out.append(('bubble', *(iround(x + (y - x) * t) for x, y in zip(first[1:], last[1:]))))
        elif first[:2] == last[:2] and first[4:] == last[4:]:
            out.append((*first[:2], iround(first[2] + (last[2] - first[2]) * t),
                        iround(first[3] + (last[3] - first[3]) * t), *first[4:]))
        else:
            out.append(prop)
    return tuple(out)


def smooth_sequence(seq, loop):
    """Rasterize intermediate poses, including the final-to-first path of a loop."""
    out, i, start = [], 0, 0
    for time, ms in frame_times(sum(duration for _, duration in seq), 50):
        while time >= start + seq[i][1]:
            start += seq[i][1]
            i += 1
        a, duration = seq[i]
        b = seq[(i + 1) % len(seq)][0] if loop or i + 1 < len(seq) else a
        t = (time - start) / duration
        p = between_poses(a, b, t)
        # Blinks and mouth beats keep their authored onset, to the nearest output frame.
        for key in ('eyes', 'mouth', 'blush'):
            p[key] = a[key]
        p['props'] = between_props(a['props'], b['props'], t)
        out.append((p, ms))
    return out


def anim_celebrate():
    """Completion: a silent La mouth shape, a small hop and a green check badge."""
    la = dict(eyes='happy')
    keys = [
        (0, P()),
        (120, P(sy=.98, arms=('down_in', 'down_in'))),
        (240, P(sy=.95, arms=('down_out', 'down_out'))),
        (360, P(sy=.93,
                arms=between_poses(P(arms=('down_out', 'down_out')),
                                   P(arms=('out', 'out')), .3)['arms'])),
        (600, P(la, y=-3, arms=('out', 'out'))),
        (720, P(la, y=-4, arms=('out_up', 'out_up'))),
        (900, P(la, y=-3, arms=('out_up', 'out_up'))),
        (1080, P(la, y=-1, arms=('out', 'out'))),
        (1200, P(eyes='happy', sy=.95, arms=('out_dn', 'out_dn'))),
        (1380, P(eyes='happy', arms=('out', 'out'))),
        (1500, P(eyes='happy', sy=1.02, arms=('out', 'out'))),
        (1800, P()),
        (1860, P(eyes='closed')),
        (1920, P()),
        (2000, P()),
    ]
    # Open straight into La, using the eating mouth's depth and a wider tongue.
    # Mouth beats follow speech timing rather than the body interpolation midpoint.
    mouths = [(0, 'smile'), (60, 'grin'), (120, 'la_close'),
              (180, 'la'), (900, 'la_close'),
              (1020, 'grin'), (1140, 'smile')]
    fr, t = [], 0
    for ms in [60] * 32 + [80, 80]:
        left, right = next((a, b) for a, b in zip(keys, keys[1:]) if a[0] <= t <= b[0])
        p = between_poses(left[1], right[1], (t - left[0]) / (right[0] - left[0]))
        p['mouth'] = next(mouth for start, mouth in reversed(mouths) if t >= start)
        if 480 <= t < 1860:
            # Grow and shrink the badge without a sudden 8-to-12 px jump.
            size = max(3, iround(12 * min(1, (t - 420) / 240, (1860 - t) / 300)))
            y = iround(10 - 3 * math.sin(math.pi * (t - 480) / 1380))
            p['props'] = (('check', 32 - size // 2, y, size),)
        fr.append((p, ms))
        t += ms
    return fr


def grounded(p):
    """The pose moved up or down so its lowest pixel sits on the idle foot line."""
    bottom = int(np.nonzero(render(p)['lab'].any(axis=1))[0][-1])
    return dict(p, y=p['y'] + GROUND - 1 - bottom)


def anim_laugh_roll():
    """Three taps: laugh holding the belly, roll with kicking soles, then stand up."""
    L = dict(eyes='happy', mouth='laugh', arms=('belly', 'belly'), blush=True, face=(0, 1.5))
    R = dict(eyes='happy', mouth='roar', arms=('belly', 'belly'), face=(0, 1.0), blush=True)
    fr = []
    # Three breathing laugh beats fill the requested 1.44 s, with fresh poses
    # every 60 ms instead of holding each of four drawings for 360 ms.
    for i in range(24):
        pulse = (1 - math.cos(2 * math.pi * i / 8)) / 2
        p = between_poses(P(L, sy=.98, belly=1),
                          P(L, sy=1.05, mouth='roar', arms=('belly_up', 'belly_up')), pulse)
        if i < 3:
            p = between_poses(P(), p, i / 3)
        if 3 <= i % 12 <= 10:
            p['props'] = (ha_at(49 if i < 12 else 2, 12 - (i % 12 - 3)),)
        fr.append((p, 60))
    crouch = P(R, mouth='laugh', sy=.90)
    start = dict(fr[-1][0], props=())
    fr.extend((between_poses(start, crouch, i / 3), 60) for i in (1, 2, 3))
    for i in range(15):
        phase = i / 14
        lift = math.sin(math.pi * phase)
        rot = 22 * math.sin(2 * math.pi * phase)
        kick = 1.5 * math.sin(4 * math.pi * phase)
        feet = ((-7.2 - .8 * lift, -2.5 + lift * (8 + kick)),
                (7.2 + .8 * lift, -2.5 + lift * (8 - kick)))
        props = (ha_at(48, 10),) if 2 <= i <= 5 else (ha_at(5, 10),) if 9 <= i <= 12 else ()
        # Rock around the middle of the trunk; both soles move along arcs.
        p = P(R, sit=feet, sy=.94 + .06 * lift, rot=rot,
              x=13 * math.sin(math.radians(rot)), props=props)
        fr.append((grounded(p), 60))
    for i in range(7):
        p = between_poses(P(crouch, mouth='grin'), P(), i / 6)
        fr.append((p, 60))
    return fr


def anim_alert():
    a = dict(arms=('hip', 'wave'), mouth='grin', eyes='open')
    ex = lambda dy: (('glyph', '!', 31, 14 + dy),)
    return [
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b')), props=ex(-1)), 160),
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b'))), 160),
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b')), props=ex(-1)), 160),
        (P(a, props=ex(0)), 160), (P(dict(a, arms=('hip', 'wave_b'))), 160),
    ]


def anim_eat_paper():
    """Keep feeding one continuous sheet, with alternating paws and steady bites."""
    fr = []
    left = P(arms=('belly_up', 'belly'), mouth='eat', cover_mouth=True)
    right = P(arms=('belly', 'belly_up'), mouth='eat', cover_mouth=True)
    for t, ms in frame_times(2400, 50):
        phase = t / 2400
        pull = (1 - math.cos(6 * math.pi * phase)) / 2
        p = between_poses(left, right, pull)
        p.update(mouth='la_close' if pull > .75 else 'eat',
                 eyes='closed' if 2100 <= t < 2200 else 'open',
                 cheeks=.4 * math.sin(6 * math.pi * phase) ** 2)
        # One pixel per frame, 48 pixels per loop: an exact multiple of the
        # six-row print pattern, so the paper never resets or leaves the mouth.
        p['props'] = (('paper-held', 32, 38, 22, t // 50, math.sin(2 * math.pi * phase)),)
        fr.append((p, ms))
    return fr


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
        (P(s, eyes='shut', mouth='line'), 180),
        (P(s, eyes='sleepy', mouth='line'), 120),
        (P(s, eyes='sleepy', mouth='line', y=1, sy=.96, arms=('down_in', 'down_in')), 100),
        (P(eyes='sleepy', mouth='line', sy=.90, arms=('down_in', 'down_in')), 120),
        (P(eyes='sleepy', mouth='yawn', arms=('out', 'out')), 180),
        (P(eyes='sleepy', mouth='yawn', arms=('stretch', 'stretch'), sy=1.06, y=-1), 280),
        (P(eyes='closed', mouth='yawn', arms=('stretch', 'stretch'), sy=1.08, y=-1), 220),
        (P(eyes='sleepy', mouth='line', arms=('out_dn', 'out_dn'), sy=1.02), 160),
        (P(eyes='sleepy', mouth='line', sy=.98), 140),
        (P(eyes='closed'), 80),
        (P(), 140),
    ]


def anim_walk():
    return [
        (P(legs='step_l', lean=-1, arms=('down_out', 'down_in')), 140),
        (P(legs='lift_l', lean=-1, y=-1, arms=('down_out', 'down_in')), 120),
        (P(legs='step_l', lean=-1, arms=('down', 'down')), 120),
        (P(lean=0, sy=0.97), 120),
        (P(legs='step_r', lean=1, arms=('down_in', 'down_out')), 140),
        (P(legs='lift_r', lean=1, y=-1, arms=('down_in', 'down_out')), 120),
        (P(legs='step_r', lean=1, arms=('down', 'down')), 120),
        (P(lean=0, sy=0.97), 120),
    ]


def anim_poke(direction):
    d = direction
    return [
        (P(), 40),
        (P(eyes='squeeze', mouth='wavy', lean=3 * d, sy=0.95, x=d), 50),
        (P(eyes='squeeze', mouth='wavy', lean=5 * d, x=d), 110),
        (P(eyes='open', mouth='o', lean=3 * d), 100),
        (P(eyes='open', mouth='o', lean=-2 * d), 110),
        (P(eyes='open', mouth='smile', lean=1 * d), 110),
        (P(eyes='open', mouth='smile', lean=-1 * d), 120),
        (P(eyes='closed'), 100),
        (P(), 160),
    ]


def anim_carrying():
    """Import: grip a parcel with both short paws and take small alternating steps."""
    hold = dict(arms=('fold', 'fold'), parcel=True)
    return [
        (P(hold, legs='step_l', x=-1), 160),
        (P(hold, legs='lift_l', x=-1, y=-1), 160),
        (P(hold, legs='step_l', y=-1), 180),
        (P(hold), 160),
        (P(hold, legs='step_r', x=1), 160),
        (P(hold, legs='lift_r', x=1, y=-1), 160),
        (P(hold, legs='step_r', y=-1), 180),
        (P(hold), 160),
    ]


def anim_annoyed():
    """Six taps: puff the cheeks, put paws on hips, stamp twice, then relax."""
    glare = dict(eyes='annoyed', mouth='pout', cheeks=1.5, face=(0, -.6))
    huff = dict(glare, arms=('hip', 'hip'))
    return [
        (P(glare), 100),
        (P(huff), 120),
        (P(huff, legs='lift_r', lean=-1), 130),
        (P(huff, sy=0.95), 90),
        (P(huff), 130),
        (P(huff, legs='lift_l', lean=1), 130),
        (P(huff, sy=0.95), 90),
        (P(huff, lean=-1), 160),
        (P(huff), 180),
        (P(eyes='closed', mouth='line', arms=('down_in', 'down_in')), 120),
        (P(mouth='line'), 100),
        (P(), 180),
    ]


def anim_crawl():
    """Dragged: alternate forepaw reaches and diagonal hind-foot pushes, with a blink."""
    # Lift, reach, plant, pull. The planted paw travels back relative to the body;
    # the last pose joins the opposite half-cycle within one pixel of paw travel.
    swing = [(-2, 0), (-2, 1), (0, 2), (2, 1), (3, 0), (2, 0), (1, 0), (0, 0)]
    stance = [(0, 0), (0, 0), (-1, 0), (-1, 0), (-2, 0), (-2, 0), (-2, 0), (-2, 0)]
    lift = [-90, -68, -46, -58, -78, -90, -94, -90]
    press = [-90, -90, -92, -94, -96, -94, -92, -90]
    rise = [0, 0.5, 1, 1, 0.5, 0, 0, 0]
    nod = [0, -1, -1, 0, 1, 1, 0, 0]
    durs = [110, 90, 90, 100, 110, 120, 120, 120]
    fr = []
    for b in range(2):
        for k, ms in enumerate(durs):
            paws, kick = (stance[k], swing[k]), (lift[k], press[k])   # (far, near)
            if b:   # the far forepaw steps, with the near hind foot
                paws, kick = paws[::-1], kick[::-1]
            fr.append((P(prone=dict(paws=paws, kick=kick, rise=rise[k], nod=nod[k]),
                         look=(1, 0), eyes='closed' if b == 1 and k == 6 else 'open'), ms))
    return fr


ANIMS = {
    'idle': anim_idle, 'idle-look': anim_idle_look, 'idle-giggle': anim_idle_giggle,
    'snack': anim_snack, 'dance': anim_dance, 'thinking': anim_thinking,
    'typing': lambda: anim_typing(1), 'typing-both': lambda: anim_typing(2),
    'typing-fast': lambda: anim_typing(3), 'terminal': lambda: anim_terminals(1),
    'terminals': lambda: anim_terminals(2), 'shocked': anim_shocked,
    'celebrate': anim_celebrate, 'laugh-roll': anim_laugh_roll,
    'alert': anim_alert, 'eat-paper': anim_eat_paper, 'carrying': anim_carrying,
    'sleep': anim_sleep, 'wake': anim_wake, 'walk': anim_walk,
    'poke-left': lambda: anim_poke(1), 'poke-right': lambda: anim_poke(-1),
    'annoyed': anim_annoyed, 'crawl': anim_crawl,
}


# ---------------------------------------------------------------- pet.json

def pet_json(anims):
    return {
        'id': PACK_ID,
        'w': W, 'h': H,
        'anims': [{'key': n, 'durs': anims[n]['durs'], 'loop': n not in ONE_SHOT}
                  for n in ANIM_NAMES],
        'states': {
            'idle': ['idle'], 'thinking': ['thinking'], 'working': ['typing'],
            'juggling': ['terminal'], 'error': ['shocked'], 'attention': ['celebrate'],
            'notification': ['alert'], 'sweeping': ['eat-paper'], 'carrying': ['carrying'],
            'sleeping': ['sleep'], 'waking': ['wake'], 'roam': ['walk'],
        },
        'tiers': {
            'working': [{'min': 3, 'anim': 'typing-fast'}, {'min': 2, 'anim': 'typing-both'},
                        {'min': 1, 'anim': 'typing'}],
            'juggling': [{'min': 2, 'anim': 'terminals'}, {'min': 1, 'anim': 'terminal'}],
        },
        'idlePool': [
            {'anim': 'idle-look', 'loops': 2, 'weight': 1},
            {'anim': 'idle-giggle', 'loops': 2, 'weight': 1},
            {'anim': 'snack', 'loops': 1, 'weight': 1},
            {'anim': 'dance', 'loops': 2, 'weight': 1},
        ],
        'bonus': {},
        'reactions': {'tapLeft': 'poke-left', 'tapRight': 'poke-right', 'tickle': 'laugh-roll',
                      'annoyed': 'annoyed', 'drag': 'crawl'},
        'holds': {'attention': 1, 'error': 2, 'notification': 2, 'waking': 1,
                  'sweeping': 1},
        'faces': 'front',
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
        if name not in {'idle', 'snack', 'typing', 'typing-both', 'typing-fast', 'shocked',
                        'eat-paper', 'celebrate', 'laugh-roll', 'terminal', 'terminals'}:
            seq = smooth_sequence(seq, loop=name not in ONE_SHOT)
        metas = [render(p) for p, _ in seq]
        out[name] = dict(frames=[to_rgba(m) for m in metas], durs=[ms for _, ms in seq],
                         meta=metas, poses=[p for p, _ in seq])
    return out


def snack_mouth(anims, names=EATING):
    """The open mouth's centre over the open-mouth frames of `names`, in art pixels."""
    pts = [m['mouth'] for n in names for m in anims[n]['meta'] if m['mouth']]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return iround(float(np.median(xs))), iround(float(np.median(ys)) - 0.5)


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
    spec = pet_json(anims)
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
    for kind in ('open', 'wide', 'annoyed'):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for side in (-1, 1):
                    rows = eye_rows(kind, (dx, dy), side)
                    if sum(row.count('w') for row in rows) != 1:
                        bad.append(f'{kind} eye looking {(dx, dy)}: missing single white highlight')
    names = list(anims)
    if names != ANIM_NAMES:
        bad.append(f'animations {names} != the {len(ANIM_NAMES)} in the animation catalogue')
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
    rest = Rig(idle['poses'][0])
    fixed_head = rest.trunk(*rest.local())[:rest.head_y]
    reference = rest.arm_joints(1, 'down')
    arm_lengths = [math.dist(a, b) for a, b in zip(reference, reference[1:])]
    for n, anim in anims.items():
        for i, p in enumerate(anim['poses']):
            if p['prone']:
                continue  # The crawl solves the same two fixed segment lengths.
            rig = Rig(p)
            if not p['rot']:
                aligned = shifted(rig.trunk(*rig.local()), rig.head_y - rest.head_y,
                                  rig.head_x - rest.head_x)
                if not np.array_equal(aligned[:rest.head_y], fixed_head):
                    bad.append(f'{n} frame {i}: head outline changes after aligning its position')
            for side, spec in zip((-1, 1), p['arms']):
                joints = rig.arm_joints(side, spec)
                lengths = [math.dist(a, b) for a, b in zip(joints, joints[1:])]
                if not np.allclose(lengths, arm_lengths, atol=1e-6):
                    bad.append(f'{n} frame {i}: arm lengths {lengths} differ from front idle {arm_lengths}')
    grounds = {int(np.nonzero(f[..., 3].any(axis=1))[0][-1]) + 1 for f in idle['frames']}
    if grounds != {GROUND}:
        bad.append(f'idle: feet on lines {sorted(grounds)}, want {GROUND}')
    fur_colors = [IDX[c] for c in ('body', 'body_hi', 'body_lo', 'body_lo2', 'belly', 'belly_lo')]
    idle_arm_edges = {}
    for i, (p, fr, m) in enumerate(zip(idle['poses'], idle['frames'], idle['meta'])):
        if len(blobs8(fr[..., 3] > 0)) != 1:
            bad.append(f'idle frame {i}: has detached props')
        rig = Rig(p)
        for side, spec in zip((-1, 1), p['arms']):
            _, elbow, hand = rig.arm_joints(side, spec)
            arm, palm = rig.arm(side, spec)
            # Inspect the rendered outer contour, including one pixel outside it:
            # torso widening can otherwise poke through beside a stable arm.
            edge = dilate4(arm | palm)
            outer_x = (np.where(edge, XS, W).min(axis=1) if side < 0
                       else np.where(edge, XS, -1).max(axis=1))
            outside = edge.any(axis=1)[:, None] & (np.abs(XS - outer_x[:, None]) <= 1)
            edge_pixels = m['lab'][outside]
            key = (side, rig.head_x, rig.head_y)
            fixed_edges = idle_arm_edges.setdefault(key, edge_pixels)
            if not np.array_equal(edge_pixels, fixed_edges):
                bad.append(f'idle frame {i}: outer edge of arm {side} changes while it is still')
            for part, fixed in zip((arm, palm), rest.arm(side, 'down')):
                aligned = shifted(part, rig.head_y - rest.head_y, rig.head_x - rest.head_x)
                if not np.array_equal(aligned, fixed):
                    bad.append(f'idle frame {i}: arm {side} changes shape while breathing')
                    break
            pc = (iround_from(hand[0], rig.ox), iround(hand[1]))
            dx, dy = hand[0] - elbow[0], hand[1] - elbow[1]
            tip = (CX - pc[0]) * dx + (CY - pc[1]) * dy >= 0
            rim = tip & dilate4(palm) & ~palm
            if (rim & np.isin(m['lab'], fur_colors)).any():
                bad.append(f'idle frame {i}: yellow fur leaks past palm {side}')
    first = idle['frames'][0][..., 3] > 0
    for n in sorted(ONE_SHOT):
        last = anims[n]['frames'][-1][..., 3] > 0
        iou = (first & last).sum() / (first | last).sum()
        if iou < 0.9:
            bad.append(f'{n}: last frame is not back near idle (mask overlap {iou:.0%})')
    points = [(EATING, 'upright mouth', snack_mouth(anims))]
    for names, label, (mx, my) in points:
        for n in names:
            for x, y in (m['mouth'] for m in anims[n]['meta'] if m['mouth']):
                if abs(x - mx) > 1 or abs(y - 0.5 - my) > 1:
                    bad.append(f'{n}: open mouth at ({x}, {y}) is off {label} ({mx}, {my})')
    for i, (p, m) in enumerate(zip(anims['crawl']['poses'], anims['crawl']['meta'])):
        line = int(np.nonzero(m['body'].any(axis=1))[0][-1]) + 1
        if not GROUND <= line <= GROUND + 2:
            bad.append(f'crawl frame {i}: belly on line {line}, want {GROUND}..{GROUND + 2}')
    # Check every expression against its complete facial bitmaps. Covering the
    # mouth while giggling, chewing a glyph and the sleep bubble are intentional.
    for n, anim in anims.items():
        for i, (p, m) in enumerate(zip(anim['poses'], anim['meta'])):
            expected = np.zeros((H, W), np.uint8)
            if p['prone']:
                axis = PRONE_X + PRONE_FACE_U
                top = PRONE_TOP + p['prone'].get('nod', 0)
                eyes = [(axis + side * EYE_U, top + PRONE_EYE_DY) for side in (-1, 1)]
                mouth = (axis, top + PRONE_MOUTH_DY)
            else:
                rig = Rig(p)
                axis = rig.ox
                fu, fv = p['face']
                eyes = [rig.face_pt(side * EYE_U + fu, EYE_V + fv) for side in (-1, 1)]
                mouth = rig.face_pt(fu, MOUTH_V + fv)
            parts = [(eye_rows(p['eyes'], p['look'], side), pt) for side, pt in zip((-1, 1), eyes)]
            if not p['cover_mouth'] and not any(pr[0] in ('code-in', 'bubble') for pr in p['props']):
                parts.append((MOUTHS[p['mouth']], mouth))
            for rows, (x, y) in parts:
                stamp(expected, rows, *corner(rows, x, y, axis), FACE)
            visible = expected != 0
            if not np.array_equal(m['lab'][visible], expected[visible]):
                bad.append(f'{n} frame {i}: an eye or mouth is obscured')
    spec = json.loads(files['pet.json'])
    used = set(sum(spec['states'].values(), []))
    used |= {t['anim'] for ts in spec['tiers'].values() for t in ts}
    used |= {x['anim'] for x in spec['idlePool']} | set(spec['reactions'].values())
    used |= {n for bonus in spec['bonus'].values() for n in bonus['anims']}
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
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
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


def animated_preview(anims, name, path, zoom=4, loop_all=False):
    """Nearest-neighbour GIF at original timing; optionally loop single-play actions."""
    a = anims[name]
    frames = []
    for fr in a['frames']:
        tile = checker(W * zoom, H * zoom, 16)
        tile.alpha_composite(Image.fromarray(fr, 'RGBA').resize(tile.size, Image.NEAREST))
        frames.append(tile.convert('RGB'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    repeat = {'loop': 0} if loop_all or name not in ONE_SHOT else {}
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=a['durs'],
                   disposal=2, **repeat)
    return path


def completion_preview(anims, path):
    """Show the completion animation, followed by idle when no new task arrives."""
    spec = pet_json(anims)
    complete = anims[spec['states']['attention'][0]]
    idle = anims[spec['states']['idle'][0]]
    flow = {'frames': complete['frames'] * spec['holds']['attention'] + idle['frames'],
            'durs': complete['durs'] * spec['holds']['attention'] + idle['durs']}
    return animated_preview({'completion': flow},
                            'completion', path, zoom=3, loop_all=True)


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='verify the files on disk, write nothing')
    ap.add_argument('--preview', nargs='?', const=os.path.join(PREVIEW_DIR, f'{PACK_ID}.png'),
                    metavar='PATH', help='all frames, defaults to app/build/pet_src_preview/naiwa.png')
    ap.add_argument('--strip', nargs='*', default=[], metavar='ANIM', help='4x grid per animation')
    ap.add_argument('--gif', nargs='*', default=[], metavar='ANIM', help='4x animated GIF per animation')
    ap.add_argument('--gallery', metavar='DIR', help='all animations as looping 3x GIFs for the README')
    ap.add_argument('--completion-previews', metavar='DIR', help='completion followed by idle at 3x')
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
          f'upright mouth {snack_mouth(anims)}, sha256 {digest}')
    for line in info:
        print('  ' + line)
    if args.preview:
        print('  preview ' + preview(anims, args.preview))
    for n in args.strip:
        if n not in anims:
            problems.append(f'--strip: unknown animation {n}')
            continue
        print('  strip ' + strip(anims, n, os.path.join(PREVIEW_DIR, PACK_ID, f'{n}.png')))
    for n in args.gif:
        if n not in anims:
            problems.append(f'--gif: unknown animation {n}')
            continue
        print('  gif ' + animated_preview(anims, n, os.path.join(PREVIEW_DIR, PACK_ID, f'{n}.gif')))
    if args.gallery:
        for n in anims:
            animated_preview(anims, n, os.path.join(args.gallery, f'{n}.gif'), zoom=3, loop_all=True)
        print(f'  gallery {args.gallery}: {len(anims)} looping GIFs')
    if args.completion_previews:
        path = os.path.join(args.completion_previews, 'naiwa-attention.gif')
        print('  completion ' + completion_preview(anims, path))
    for p in problems:
        print(f'error: {p}', file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
