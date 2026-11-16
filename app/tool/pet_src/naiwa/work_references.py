#!/usr/bin/env python3
"""Render four six-state design references using Naiwa's existing pixel rig.

Run from the repository root:
    python app/tool/pet_src/naiwa/work_references.py

Writes reference GIFs and a standalone comparison page under app/build only.
The selected concept can later replace the six production animations in draw.py.
"""

import argparse
import base64
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import draw as pet


FRAMES, MS = 40, 50
SLOTS = [
    ('typing', '工作 · 1 个会话', 'work', 1),
    ('typing-both', '工作 · 2 个会话', 'work', 2),
    ('typing-fast', '工作 · 3+ 个会话', 'work', 3),
    ('terminal', '子代理 · 1 个', 'agents', 1),
    ('terminals', '子代理 · 2+ 个', 'agents', 2),
    ('eat-paper', '上下文压缩', 'compress', 1),
]
CONCEPTS = {
    'a': ('A · 吃代码流水线', '接住、送嘴、咀嚼；助手投喂；长代码压成一口。',
          ['单爪接住再吃', '双爪轮流投喂', '连吃三口，鼓腮快嚼',
           '一个助手送代码', '两个助手交替送餐', '长串代码压成一口']),
    'b': ('B · 键盘指挥', '从容敲键到双爪快打；分派面板；叠页压缩。',
          ['单爪轻敲键盘', '左右交替敲键', '双爪快打，字符冒出',
           '抬爪分派一个面板', '左右调度多个面板', '多页代码压成小卡']),
    'c': ('C · 积木工坊', '搭建代码积木；把零件递给助手；长条卷成小卷。',
          ['放下一块代码积木', '双爪交替拼装', '快速搭起三块积木',
           '给一个助手递积木', '左右助手接力搬运', '把长代码卷成小卷']),
    'd': ('D · 魔法汇聚', '控制代码光球；召唤协作伙伴；收拢为一颗晶体。',
          ['指尖驱动一个光球', '双爪驱动两个光球', '三球轮转，连续施法',
           '指挥一个悬浮助手', '多助手环绕协作', '散开的代码汇成晶体']),
}


def empty():
    return np.zeros((64, 64), np.uint8)


def ease(t):
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return a + (b - a) * t


def scale_layer(lab, amount, center=(32, 50)):
    """Grow or shrink a prop around its handoff point using integer pixels."""
    if amount == 0:
        return empty()
    x = np.floor(center[0] + (pet.CX - center[0]) / amount).astype(int)
    y = np.floor(center[1] + (pet.CY - center[1]) / amount).astype(int)
    visible = (x >= 0) & (x < 64) & (y >= 0) & (y < 64)
    out = empty()
    out[visible] = lab[y[visible], x[visible]]
    return out


def rect(lab, x, y, w, h, color):
    x, y, w, h = map(pet.iround, (x, y, w, h))
    mask = (pet.XS >= x) & (pet.XS < x + w) & (pet.YS >= y) & (pet.YS < y + h)
    lab[mask] = pet.IDX[color]


def line(lab, a, b, color, radius=.55):
    lab[pet.capsule(a, b, radius)] = pet.IDX[color]


def star(lab, x, y, color, radius=1):
    x, y = pet.iround(x), pet.iround(y)
    rect(lab, x - radius, y, radius * 2 + 1, 1, color)
    rect(lab, x, y - radius, 1, radius * 2 + 1, color)


def token(lab, x, y, ch='{', color='c1', tile=False):
    kind = 'block' if tile else 'code'
    pet.draw_props(lab, ((kind, ch, pet.iround(x), pet.iround(y), color),))


def brick(lab, x, y, color='c1', w=9, h=6):
    rect(lab, x, y, w, h, 'code_line')
    rect(lab, x + 1, y + 1, w - 2, h - 2, color)
    rect(lab, x + 2, y + 1, min(3, w - 3), 1, 'white')
    rect(lab, x + w - 2, y + 2, 1, h - 3, 'tile')


def helper(lab, x, y, color, phase):
    x, y = pet.iround(x), pet.iround(y)
    pet.stamp(lab, [
        '....o....', '....c....', '.ooooooo.', 'occccccco',
        'ocwcccwco', 'occccccco', '.ooocooo.',
        '..occco..', '.occccco.', '..oo.oo..',
    ], x, y, {'o': 'code_line', 'c': color, 'w': 'white'})
    if phase > .5:
        rect(lab, x + 2, y + 4, 1, 1, 'c4')
        rect(lab, x + 6, y + 4, 1, 1, 'c4')


def keyboard(lab, pulse, tier):
    rect(lab, 18, 49, 28, 8, 'code_line')
    rect(lab, 19, 50, 26, 6, 'tile')
    for row in range(2):
        for key in range(7):
            on = key == int(pulse * 7) % 7 or (tier > 1 and key == (int(pulse * 7) + 3) % 7)
            rect(lab, 21 + key * 3, 51 + row * 2, 2, 1, 'c4' if on else 'c6')
    rect(lab, 27, 55, 10, 1, 'c1')


def terminal(lab, x, y, w, phase, color='c4'):
    rect(lab, x, y, w, 13, 'code_line')
    rect(lab, x + 1, y + 1, w - 2, 11, 'tile')
    rect(lab, x + 2, y + 2, w - 4, 1, color)
    for row in range(3):
        width = 3 + (int(phase * 12) + row * 3) % (w - 6)
        rect(lab, x + 3, y + 5 + row * 2, width, 1, pet.CODE_COLORS[row])


def orb(lab, x, y, ch, color, radius=5):
    outer = pet.ellipse((x, y), radius, radius)
    inner = pet.ellipse((x, y), radius - 1, radius - 1)
    lab[outer] = pet.IDX[color]
    lab[inner] = pet.IDX['code_line']
    pet.stamp(lab, pet.CODE_FONT[ch], pet.iround(x - 1.5), pet.iround(y - 2.5),
              {'X': color})


def crystal(lab, x, y, size):
    mask = np.abs(pet.CX - x) + np.abs(pet.CY - y) < size
    lab[mask] = pet.IDX['c1']
    lab[mask & (pet.CX < x)] = pet.IDX['c4']
    lab[mask & (np.abs(pet.CX - x) < 1)] = pet.IDX['white']


def pose_between(arms0, arms1, t, **kw):
    return pet.P(pet.between_poses(pet.P(arms=arms0), pet.P(arms=arms1), t), **kw)


def frame(p, back, front, hands=False):
    original = pet.render(p)
    lab = back.copy()
    mask = original['lab'] != 0
    lab[mask] = original['lab'][mask]
    mask = front != 0
    lab[mask] = front[mask]
    if hands:
        rig = pet.Rig(p)
        paws = np.zeros((64, 64), bool)
        for side, spec in zip((-1, 1), p['arms']):
            paws |= rig.arm(side, spec)[1]
        mask = pet.dilate4(paws) & (original['lab'] != 0)
        lab[mask] = original['lab'][mask]
    return pet.to_rgba(dict(original, lab=lab)), lab


def eating(t, tier):
    cycle, u = divmod(t * tier, 1)
    side = -1 if tier > 1 and int(cycle) % 2 else 1
    feed = math.sin(math.pi * min(1, u / .72)) ** 2
    a = ('down_out', 'down_out')
    b = ('down_out', 'feed') if side > 0 else ('feed', 'down_out')
    p = pose_between(a, b, feed, cheeks=.8 * max(0, math.sin(math.pi * (u - .68) / .32)))
    p['mouth'] = 'eat' if .18 <= u < .7 else 'chew_b' if .7 <= u < .9 else 'grin'
    p['eyes'] = 'happy' if .7 <= u < .9 else 'open'
    p['look'] = (side, 0) if u < .18 else (0, 0)
    back, front = empty(), empty()
    if u < .68:
        v = ease(u / .68)
        x = mix(57 if side > 0 else 4, 31, v)
        y = 37 + 3 * math.sin(math.pi * v)
        prop = pet.food_at(p, '{};'[int(cycle) % 3], pet.iround(x), pet.iround(y), pet.CODE_COLORS[int(cycle) % 3])
        p['props'] = (prop,)
    if tier == 3 and .72 < u < .9:
        star(back, 10, 37 - 7 * (u - .72), 'c3')
        star(back, 54, 36 - 7 * (u - .72), 'c2')
    return p, back, front, False


def feeding_helpers(t, tier):
    phase = t * tier
    side = 1 if int(phase) % 2 == 0 else -1
    u = phase % 1
    p = pose_between(('catch', 'catch'), ('feed', 'feed'), (1 - math.cos(2 * math.pi * u)) / 2)
    p.update(mouth='eat' if .38 < u < .8 else 'grin', eyes='happy' if u > .8 else 'open')
    back, front = empty(), empty()
    for s in ([1] if tier == 1 else [-1, 1]):
        helper(back, 51 if s > 0 else 4, 14 + math.sin(2 * math.pi * t + s), 'c2' if s > 0 else 'c1', u)
    if .1 <= u < .8:
        v = ease((u - .1) / .7)
        edge = 55 if side > 0 else 6
        x = mix(edge, 31, ease((v - .4) / .6))
        y = mix(25, 39, ease(v / .4)) - 2 * ease((v - .4) / .6)
        p['props'] = (pet.food_at(p, '[' if side > 0 else ']', pet.iround(x), pet.iround(y), 'c2' if side > 0 else 'c1'),)
    return p, back, front, False


def food_compression(t):
    p = pose_between(('reach', 'reach'), ('feed', 'feed'), math.sin(math.pi * t) ** 2)
    p.update(mouth='eat' if .55 < t < .85 else 'grin', eyes='happy' if t > .82 else 'open')
    back, front = empty(), empty()
    if t < .58:
        width = mix(27, 7, ease(t / .58))
        x0 = 32 - width / 2
        rect(front, x0, 46, width, 7, 'code_line')
        rect(front, x0 + 1, 47, width - 2, 5, 'c3')
        for j in range(3):
            x = 32 + (j - 1) * width * .27
            rect(front, x, 48, 2, 2, pet.CODE_COLORS[j])
    elif t < .85:
        v = ease((t - .58) / .27)
        p['props'] = (pet.food_at(p, '{', 31, pet.iround(mix(46, 37, v)), 'c3'),)
    if t >= .85:
        p.update(mouth='chew_b' if t < .94 else 'grin', eyes='happy' if t < .94 else 'open',
                 cheeks=.7 * math.sin(math.pi * (t - .85) / .15))
    front = scale_layer(front, ease(t / .12))
    return p, back, front, True


def typing(t, tier):
    u = t * (tier + 1)
    tap = (1 - math.cos(2 * math.pi * u)) / 2
    arms0 = ('belly_up', 'belly') if tier > 1 else ('belly', 'belly_up')
    arms1 = ('belly', 'belly_up') if tier > 1 else ('belly', 'belly')
    p = pose_between(arms0, arms1, tap, sy=1 + .012 * tap,
                     mouth='grin', look=(0, 1), eyes='closed' if .89 < t < .94 else 'open')
    back, front = empty(), empty()
    keyboard(front, (u % 1), tier)
    for j in range(tier):
        v = (t + j / tier) % 1
        if .08 < v < .86:
            token(back, 21 + j * 9, 21 - 14 * v, '{[;'[j], pet.CODE_COLORS[j])
    return p, back, front, True


def directing(t, tier):
    tap = (1 - math.cos(2 * math.pi * t)) / 2
    p = pose_between(('down', 'wave'), ('wave', 'down') if tier > 1 else ('down', 'wave_b'), tap,
                     mouth='grin', look=(-1 if tap > .5 and tier > 1 else 1, -1))
    back, front = empty(), empty()
    if tier == 1:
        terminal(back, 36, 7, 20, t)
        star(back, 50, 25 + 2 * tap, 'c4')
    else:
        terminal(back, 5, 7, 20, t, 'c1')
        terminal(back, 39, 7, 20, (t + .5) % 1, 'c2')
        star(back, 11 if tap > .5 else 52, 25, 'c5')
    return p, back, front, False


def page_compression(t):
    squeeze = math.sin(math.pi * t) ** 2
    p = pose_between(('out_dn', 'out_dn'), ('belly', 'belly'), squeeze, mouth='smile')
    back, front = empty(), empty()
    v = ease(min(t / .62, 1))
    if t < .9:
        for j in range(3):
            width = mix(19, 8, v)
            x = 32 - width / 2 + (j - 1) * mix(7, 0, v)
            y = mix(44 + j * 4, 49, v)
            rect(front, x, y, width, 6, 'code_line')
            rect(front, x + 1, y + 1, width - 2, 4, 'belly')
            rect(front, x + 2, y + 2, width - 4, 1, pet.CODE_COLORS[j])
        if t > .65:
            star(back, 51, 42, 'c4', 2 if t < .77 else 1)
    front = scale_layer(front, ease(t / .14) * (1 - ease((t - .8) / .1)))
    return p, back, front, True


def building(t, tier):
    cycle, u = divmod(t * tier, 1)
    side = -1 if int(cycle) % 2 else 1
    p = pose_between(('reach', 'reach'), ('belly', 'belly'), math.sin(math.pi * u) ** 2,
                     mouth='grin', look=(side if u < .3 else 0, 1))
    back, front = empty(), empty()
    for j in range(int(cycle)):
        brick(front, 20 + 8 * j, 49, pet.CODE_COLORS[j])
    v = ease(min(1, u / .6))
    x = mix(65 if side > 0 else -10, 20 + 8 * int(cycle), v)
    y = mix(45, 49, v) - 4 * math.sin(math.pi * v)
    brick(front, x, y, pet.CODE_COLORS[int(cycle) % 3])
    front = pet.shifted(front, 0, pet.iround(60 * ease((t - .85) / .15)))
    rect(front, 18, 55, 28, 2, 'tile')
    return p, back, front, True


def brick_helpers(t, tier):
    cycle, u = divmod(t * tier, 1)
    side = -1 if tier == 1 or int(cycle) % 2 == 0 else 1
    a = ('belly', 'belly')
    b = ('out_dn', 'belly') if side < 0 else ('belly', 'out_dn')
    p = pose_between(a, b, math.sin(math.pi * u) ** 2, look=(side, 0), mouth='grin')
    back, front = empty(), empty()
    for s in ([-1] if tier == 1 else [-1, 1]):
        helper(back, 2 if s < 0 else 53, 49 + .6 * math.sin(2 * math.pi * t), 'c1' if s < 0 else 'c2', u)
    if u < .82:
        v = ease(u / .82)
        brick(front, mix(28, 3 if side < 0 else 53, v), 45 - 3 * math.sin(math.pi * v),
              'c1' if side < 0 else 'c2', w=7, h=5)
    return p, back, front, True


def scroll_compression(t):
    squeeze = math.sin(math.pi * t) ** 2
    p = pose_between(('out_dn', 'out_dn'), ('belly', 'belly'), squeeze, mouth='grin')
    back, front = empty(), empty()
    if t < .88:
        width = mix(29, 8, ease(t / .65))
        x = 32 - width / 2
        rect(front, x, 46, width, 9, 'code_line')
        rect(front, x + 1, 47, width - 2, 7, 'belly')
        for j in range(2):
            rect(front, x + 2, 49 + j * 2, max(1, width - 7), 1, pet.CODE_COLORS[j])
        rect(front, x + width - 5, 46, 5, 9, 'code_line')
        rect(front, x + width - 4, 47, 3, 7, 'c3')
        rect(front, x + width - 3, 48, 1, 5, 'belly')
    front = scale_layer(front, ease(t / .14) * (1 - ease((t - .78) / .1)))
    return p, back, front, True


def magic_work(t, tier):
    pulse = (1 - math.cos(2 * math.pi * t * tier)) / 2
    p = pose_between(('out', 'out_up'), ('out_up', 'out') if tier > 1 else ('out', 'wave'),
                     pulse, mouth='grin', look=(0, -1), sy=1 + .02 * pulse)
    back, front = empty(), empty()
    for j in range(tier):
        phase = 2 * math.pi * (t + j / tier)
        x = 32 + (10 if tier == 1 else 19) * math.cos(phase)
        y = 13 + 4 * math.sin(phase)
        orb(back, x, y, '{[;'[j], pet.CODE_COLORS[j])
    for side in (-1, 1):
        star(back, 9 if side < 0 else 55, 28 - 3 * pulse, 'c4')
    return p, back, front, False


def magic_agents(t, tier):
    pulse = (1 - math.cos(2 * math.pi * t)) / 2
    p = pose_between(('wave', 'out_up'), ('out_up', 'wave'), pulse,
                     mouth='grin', look=(1 if t < .5 else -1, -1))
    back, front = empty(), empty()
    count = 1 if tier == 1 else 3
    for j in range(count):
        angle = 2 * math.pi * (t + j / count)
        x = 28 + 21 * math.cos(angle)
        y = 10 + 5 * math.sin(angle)
        helper(back, x, y, pet.CODE_COLORS[j], (t + j / count) % 1)
    star(back, 10, 27, 'c4')
    star(back, 54, 27, 'c1')
    return p, back, front, False


def magic_compression(t):
    squeeze = math.sin(math.pi * t) ** 2
    p = pose_between(('out', 'out'), ('out_up', 'out_up'), squeeze, mouth='grin', look=(0, -1))
    back, front = empty(), empty()
    if t < .6:
        v = ease(t / .6)
        for j, start in enumerate(((10, 12), (50, 12), (32, 5))):
            x, y = mix(start[0], 32, v), mix(start[1], 14, v)
            token(back, x - 1, y - 2, '{[;'[j], pet.CODE_COLORS[j])
    elif t < .91:
        size = 5 * min(1, (t - .56) / .1, (.96 - t) / .12)
        crystal(back, 32, 14, size)
        star(back, 21, 13, 'c4', 1)
        star(back, 43, 13, 'c1', 1)
    back = scale_layer(back, ease(t / .12), center=(32, 14))
    return p, back, front, False


DESIGNS = {
    'a': {'work': eating, 'agents': feeding_helpers, 'compress': food_compression},
    'b': {'work': typing, 'agents': directing, 'compress': page_compression},
    'c': {'work': building, 'agents': brick_helpers, 'compress': scroll_compression},
    'd': {'work': magic_work, 'agents': magic_agents, 'compress': magic_compression},
}


def validate_face(p, lab, label):
    rig = pet.Rig(p)
    fu, fv = p['face']
    expected = empty()
    parts = [(pet.eye_rows(p['eyes'], p['look'], side),
              rig.trunk_pt(side * pet.EYE_U + fu, pet.EYE_V + fv)) for side in (-1, 1)]
    if not p['cover_mouth'] and not any(x[0] == 'code-in' for x in p['props']):
        parts.append((pet.MOUTHS[p['mouth']], rig.trunk_pt(fu, pet.MOUTH_V + fv)))
    for rows, (x, y) in parts:
        pet.stamp(expected, rows, *pet.corner(rows, x, y, rig.ox), pet.FACE)
    mask = expected != 0
    assert np.array_equal(expected[mask], lab[mask]), f'{label}: face obscured'
    for side, spec in zip((-1, 1), p['arms']):
        shoulder, elbow, hand = rig.arm_joints(side, spec)
        assert abs(math.dist(shoulder, elbow) - pet.UPPER_ARM) < 1e-6
        assert abs(math.dist(elbow, hand) - pet.FOREARM) < 1e-6


def build():
    result = {}
    for concept, funcs in DESIGNS.items():
        result[concept] = {}
        for name, _, kind, tier in SLOTS:
            frames = []
            for i in range(FRAMES):
                fn = funcs[kind]
                p, back, front, hands = fn(i / FRAMES) if kind == 'compress' else fn(i / FRAMES, tier)
                rgba, lab = frame(p, back, front, hands)
                validate_face(p, lab, f'{concept}/{name}/{i}')
                assert set(np.unique(rgba[..., 3])) <= {0, 255}
                assert not np.any(rgba[rgba[..., 3] == 0])
                frames.append(rgba)
            result[concept][name] = dict(frames=frames, durs=[MS] * FRAMES)
    return result


def fonts(size):
    return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', size)


def overview_frames(concept, anims):
    title, subtitle, labels = CONCEPTS[concept]
    result = []
    for i in range(FRAMES):
        page = Image.new('RGB', (744, 616), '#f5f5f1')
        pen = ImageDraw.Draw(page)
        pen.text((24, 14), title, font=fonts(26), fill='#202a32')
        pen.text((24, 51), subtitle, font=fonts(15), fill='#57616a')
        for j, (name, label, _, _) in enumerate(SLOTS):
            x, y = 16 + j % 3 * 244, 87 + j // 3 * 258
            pen.rounded_rectangle((x, y, x + 232, y + 246), radius=12, fill='#ffffff', outline='#e2e5e1')
            pen.text((x + 14, y + 9), label, font=fonts(16), fill='#29363b')
            tile = pet.checker(192, 192, 12)
            tile.alpha_composite(Image.fromarray(anims[name]['frames'][i], 'RGBA').resize((192, 192), Image.Resampling.NEAREST))
            page.paste(tile.convert('RGB'), (x + 20, y + 32))
            pen.text((x + 12, y + 224), labels[j], font=fonts(14), fill='#596870')
        result.append(page)
    return result


def write_page(out, all_anims):
    cards, images = [], []
    for concept, anims in all_anims.items():
        title, subtitle, labels = CONCEPTS[concept]
        for j, (name, label, _, _) in enumerate(SLOTS):
            strip = Image.fromarray(np.concatenate(anims[name]['frames'], axis=1), 'RGBA')
            buffer = io.BytesIO()
            strip.save(buffer, format='PNG')
            images.append('data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode())
            cards.append(f'<article data-style="{concept}" data-slot="{j}"><div class="tag">{title}</div>'
                         f'<h2>{label}</h2><canvas width="256" height="256" data-image="{len(images)-1}"></canvas>'
                         f'<p>{labels[j]}</p></article>')
    import json
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>奶蛙 · 工作动画四版参考</title><style>
:root{color-scheme:light;font:15px/1.5 system-ui,"Microsoft YaHei",sans-serif;color:#253238;background:#f3f4ef}*{box-sizing:border-box}
body{margin:0;padding:32px;max-width:1480px;margin-inline:auto}h1{margin:4px 0;font-size:30px;letter-spacing:-1px}.lead{color:#667267;max-width:860px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}button,select{font:inherit;border:1px solid #cad2c6;border-radius:8px;padding:9px 14px;background:white;color:#253238;cursor:pointer}
button.active{background:#254b3c;color:white;border-color:#254b3c}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
article{background:white;border:1px solid #dde3d7;border-radius:14px;padding:16px;text-align:center}article[hidden]{display:none}.tag{font-size:13px;color:#427053}h2{font-size:17px;margin:5px 0 10px}p{margin:10px 0 0}canvas{width:100%;max-width:256px;aspect-ratio:1;image-rendering:pixelated;background:conic-gradient(#edf0e9 25%,#f8faf4 0 50%,#edf0e9 0 75%,#f8faf4 0) 0 0/24px 24px}
input[type=range]{width:200px;accent-color:#254b3c}.hint{font-size:13px;color:#69776c}.controls{position:sticky;top:0;background:#f3f4eff5;padding:1px 0 7px;z-index:2;backdrop-filter:blur(8px)}
@media(max-width:1000px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:720px){body{padding:16px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:25px}}
</style><h1>奶蛙 · 工作动画四版参考</h1><p class="lead">每版覆盖工作 1／2／3+ 档、子代理 1／2+ 档、上下文压缩，共 24 段。选择同一状态可横向比较 A—D；选择一整套可查看六个动作。</p>
<div class="controls"><div class="bar" id="styles"><button data-v="all" class="active">四版对比</button><button data-v="a">A 吃代码</button><button data-v="b">B 键盘指挥</button><button data-v="c">C 积木工坊</button><button data-v="d">D 魔法汇聚</button></div>
<div class="bar"><label>状态 <select id="slot"><option value="all">全部六个状态</option><option value="0" selected>工作 · 1 个会话</option><option value="1">工作 · 2 个会话</option><option value="2">工作 · 3+ 个会话</option><option value="3">子代理 · 1 个</option><option value="4">子代理 · 2+ 个</option><option value="5">上下文压缩</option></select></label><button id="play">暂停</button><label>速度 <select id="speed"><option value=".5">0.5× 慢放</option><option value="1" selected>1×</option><option value="1.5">1.5×</option></select></label><input id="scrub" type="range" min="0" max="39" value="0" aria-label="逐帧查看"><span id="counter" class="hint"></span></div></div>
<main class="grid">CARDS</main><p class="hint">无声 · 64×64 原生像素 · 每段 40 帧 / 2 秒循环 · 参考方案，等待选择后应用到宠物包</p><script>
const sources=IMAGES, pics=sources.map(src=>{const img=new Image();img.src=src;return img}),cards=[...document.querySelectorAll('article')];
const slot=document.querySelector('#slot'),scrub=document.querySelector('#scrub'),play=document.querySelector('#play'),speed=document.querySelector('#speed');let style='all',playing=true,time=0,last=performance.now();
function filter(){cards.forEach(c=>c.hidden=!( (style==='all'||c.dataset.style===style)&&(slot.value==='all'||c.dataset.slot===slot.value)));}
document.querySelectorAll('[data-v]').forEach(b=>b.onclick=()=>{style=b.dataset.v;document.querySelectorAll('[data-v]').forEach(x=>x.classList.toggle('active',x===b));slot.value=style==='all'?'0':'all';filter()});slot.onchange=filter;
play.onclick=()=>{playing=!playing;play.textContent=playing?'暂停':'播放'};scrub.oninput=()=>{playing=false;play.textContent='播放';time=Number(scrub.value)*50};
function tick(now){if(playing)time=(time+(now-last)*Number(speed.value))%2000;last=now;const i=Math.floor(time/50)%40;scrub.value=i;document.querySelector('#counter').textContent=`${i+1} / 40 帧`;
cards.forEach(card=>{if(card.hidden)return;const c=card.querySelector('canvas'),ctx=c.getContext('2d'),pic=pics[Number(c.dataset.image)];ctx.imageSmoothingEnabled=false;ctx.clearRect(0,0,256,256);if(pic.complete&&pic.naturalWidth)ctx.drawImage(pic,i*64,0,64,64,0,0,256,256)});requestAnimationFrame(tick)}filter();requestAnimationFrame(tick);
</script></html>'''.replace('CARDS', ''.join(cards)).replace('IMAGES', json.dumps(images))
    (out / 'work-references.html').write_text(html, encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(pet.PREVIEW_DIR) / 'naiwa')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    all_anims = build()
    for concept, anims in all_anims.items():
        for name in anims:
            pet.animated_preview(anims, name, str(args.out / f'work-reference-{concept}-{name}.gif'), zoom=4, loop_all=True)
        overview = overview_frames(concept, anims)
        overview[0].save(args.out / f'work-reference-{concept}.gif', save_all=True, append_images=overview[1:], duration=MS, loop=0, disposal=2)
        overview[12].save(args.out / f'work-reference-{concept}.png')
        print(f'{concept.upper()}: 6 animations, {FRAMES} frames each, {FRAMES * MS} ms, face / arm / alpha checks passed')
    write_page(args.out, all_anims)
    print(args.out / 'work-references.html')


if __name__ == '__main__':
    main()
