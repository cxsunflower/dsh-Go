#!/usr/bin/env python3
"""Package the six Naiwa effects taken from the Deadlock addon pak.

    python app/tool/make_pet_sounds.py [--out DIR] [--check]

The inputs in app/tool/pet_src/naiwa/audio/ are already PCM16 mono 22050 Hz
WAVs decoded from the addon's compiled sounds; sources.json pins the pak, each
entry, and its SHA-256. Five clips are byte-for-byte copies. The laugh keeps
its full 25.286531 s: its recording scores the whole laugh animation. Its
1,115,214 decoded PCM bytes would exceed SoundPool's one-megabyte limit, so
only that clip is resampled to 11025 Hz mono PCM16 by this file's
standard-library linear interpolation; every other clip stays at 22050 Hz.
Every clip plays at gain 1 and rate 1; `ms` is its own length, rounded to the
nearest millisecond, so a reaction keeps its pose until the recording ends.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import wave


DEFAULT_OUT = Path(__file__).resolve().parents[1] / 'assets' / 'pet_sounds' / 'naiwa'
INPUT = Path(__file__).resolve().parent / 'pet_src' / 'naiwa' / 'audio'
MAX_BYTES = 1_500_000
# SoundPool truncates decoded samples above one MB.
MAX_PCM_BYTES = 1_000_000
RATE = 22050
LAUGH_ID = 'hahahahahahaha'
LAUGH_RATE = 11025

# clip id → the cues it serves. The laugh's four poses share one recording;
# `wake` is the waking state's animation, `alert` the notification state's.
CLIPS = {
    'hahahahahahaha': ('laugh', 'laugh-point', 'laugh-roll', 'laugh-belly'),
    'dajiaosei': ('poke-left',),
    'diu': ('poke-right',),
    'andi': ('wake',),
    'gagadilaxia': ('prone-eat',),
    'houla': ('alert',),
}
IDS = list(CLIPS)
CUES = {cue: [cid] for cid, cues in CLIPS.items() for cue in cues}
MAX_SECONDS = {cid: (30.0 if cid == LAUGH_ID else 2.5) for cid in IDS}


class BuildError(ValueError):
    pass


def wav_chunks(data):
    """The WAV's chunks in order as (kind, body), and where it ends."""
    found, offset = [], 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise BuildError('truncated WAV chunk header')
        kind, size = struct.unpack('<4sI', data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + size]
        if len(body) != size:
            raise BuildError('truncated WAV chunk')
        found.append((kind, body))
        offset += 8 + size + (size % 2)
    if offset != len(data):
        raise BuildError('trailing bytes after the last WAV chunk')
    return found


def resample_wav(data, rate):
    """The same chunks with `fmt` and `data` at [rate], mono PCM16.

    The source's frame count F yields `round(F * rate / RATE)` output frames.
    Output frame i maps evenly onto the source's whole span,
    `i * (F - 1) / (count - 1)`, and reads it with linear interpolation:
    `a + (b - a) * fraction`, where `a` and `b` are the source samples either
    side and `fraction` is their fraction of a frame. Both ends map to source
    frames 0 and F - 1, so the duration stays F / RATE (25.286531 s here).
    Header and metadata chunks (LIST included) are kept; RIFF and chunk sizes
    are rewritten. Deterministic, standard library only, no re-encode.
    """
    chunks = wav_chunks(data)
    fmt = next((body for kind, body in chunks if kind == b'fmt '), None)
    pcm = next((body for kind, body in chunks if kind == b'data'), None)
    if fmt is None or pcm is None:
        raise BuildError('WAV has no fmt or data chunk')
    if len(fmt) < 16:
        raise BuildError('fmt chunk is too short')
    tag, channels, source_rate, _, _, bits = struct.unpack('<HHIIHH', fmt[:16])
    if (tag, channels, bits, source_rate) != (1, 1, 16, RATE):
        raise BuildError('expected PCM16 mono 22050 Hz')
    if len(pcm) % 2:
        raise BuildError('odd PCM byte count')
    source = struct.unpack(f'<{len(pcm) // 2}h', pcm)
    if not source:
        raise BuildError('empty PCM')
    if rate != source_rate // 2:
        raise BuildError(f'only a half-rate 11025 Hz copy is supported, not {rate}')
    last = len(source) - 1
    count = round(len(source) * rate / source_rate)
    if count < 2:
        raise BuildError('too few frames to resample')
    out = []
    for i in range(count):
        position = i * last / (count - 1)
        at = min(int(position), last)
        after = min(at + 1, last)
        sample = source[at] + (source[after] - source[at]) * (position - at)
        out.append(round(sample))
    body = struct.pack(f'<{count}h', *out)
    fmt = fmt[:4] + struct.pack('<I', rate) + struct.pack('<I', rate * 2) + fmt[12:]
    rebuilt = bytearray(b'RIFF\0\0\0\0WAVE')
    for kind, chunk in chunks:
        if kind == b'fmt ':
            chunk = fmt
        elif kind == b'data':
            chunk = body
        rebuilt += kind + struct.pack('<I', len(chunk)) + chunk
        if len(chunk) % 2:
            rebuilt += b'\0'
    struct.pack_into('<I', rebuilt, 4, len(rebuilt) - 8)
    return bytes(rebuilt), count / rate


def recorded(cid, provenance):
    """Verify provenance and playback limits; return the WAV bytes and seconds."""
    path = INPUT / f'{cid}.wav'
    if not path.is_file():
        raise BuildError(f'{cid}: {path} is missing')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != provenance['pcmSha256']:
        raise BuildError(f'{cid}: PCM checksum mismatch')
    with wave.open(io.BytesIO(data)) as clip:
        if (clip.getnchannels(), clip.getsampwidth(), clip.getframerate(), clip.getcomptype()) != (1, 2, RATE, 'NONE'):
            raise BuildError(f'{cid}: expected PCM16 mono 22050 Hz')
        frames = clip.getnframes()
        if len(clip.readframes(frames)) != frames * 2:
            raise BuildError(f'{cid}: truncated PCM')
    if frames != provenance['frames']:
        raise BuildError(f'{cid}: frame count mismatch')
    seconds = frames / RATE
    if cid == LAUGH_ID:
        if provenance.get('resample') is None:
            raise BuildError(f'{cid}: sources.json must record the 11025 Hz resample')
        data, seconds = resample_wav(data, LAUGH_RATE)
        frames = round(seconds * LAUGH_RATE)
    elif provenance.get('resample') is not None:
        raise BuildError(f'{cid}: only the laugh is resampled')
    if frames * 2 > MAX_PCM_BYTES:
        raise BuildError(f'{cid}: decoded PCM exceeds SoundPool storage')
    if not 0.05 <= seconds <= MAX_SECONDS[cid]:
        raise BuildError(f'{cid}: {seconds:.3f} s is outside 0.05..{MAX_SECONDS[cid]} s')
    return data, seconds


def build():
    """Return ({filename: bytes}, report lines), without writing anything."""
    sources = json.loads((INPUT / 'sources.json').read_text(encoding='utf-8'))
    if sorted(sources) != sorted(IDS):
        raise BuildError(f'sources.json lists {sorted(sources)}, not {sorted(IDS)}')
    files, report = {}, []
    clips = {}
    for cid in IDS:
        entry = sources[cid]
        if entry.get('cue') != list(CLIPS[cid]):
            raise BuildError(f'{cid}: cue mapping mismatch')
        data, seconds = recorded(cid, entry)
        files[f'{cid}.wav'] = data
        clips[cid] = {
            'file': f'{cid}.wav',
            'gain': 1.0,
            'vary': 0.0,
            'ms': round(seconds * 1000),
        }
        report.append(f'  {cid:16} {seconds:6.3f} s  {len(data):7} bytes  {entry["pakEntry"]}')
    sounds = {
        'schema': 1,
        'id': 'naiwa',
        'name': '奶蛙技能音效',
        'author': 'github.com/cxsunflower',
        'license': 'Valve《Deadlock》addon 资源，再分发许可未确认，仅本地包；见 ASSETS.md',
        'source': 'Deadlock addon nawa_pak50_dir.vpk（citadel_addons/naiwa）; 逐条来源与校验见 '
                  'app/tool/pet_src/naiwa/audio/sources.json; 笑声整段 25.286531 s，'
                  '为绕开 SoundPool 单段上限降到 11025 Hz，其余仍 22050 Hz',
        'clips': clips,
        'cues': CUES,
    }
    files['sounds.json'] = (json.dumps(sounds, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    total = sum(map(len, files.values()))
    if total > MAX_BYTES:
        raise BuildError(f'the set is {total} bytes, over {MAX_BYTES}')
    report.insert(0, f'naiwa: {len(IDS)} effects, {len(CUES)} cues, {total} bytes')
    return files, report


def made_here(name):
    return name.endswith('.wav') or name == 'sounds.json'


def stale(out_dir, files):
    out_dir = Path(out_dir)
    have = {p.name for p in out_dir.iterdir() if made_here(p.name)} if out_dir.is_dir() else set()
    problems = []
    for name, data in sorted(files.items()):
        if name not in have:
            problems.append(f'{name}: missing')
        elif (out_dir / name).read_bytes() != data:
            problems.append(f'{name}: out of date')
    problems.extend(f'{name}: not made by this tool' for name in sorted(have - files.keys()))
    return problems


def write(out_dir, files):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Retire effects this set no longer has while leaving unrelated files alone.
    for path in out_dir.iterdir():
        if path.is_file() and made_here(path.name) and path.name not in files:
            path.unlink()
    for name, data in files.items():
        (out_dir / name).write_bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--check', action='store_true', help='compare all generated bytes without writing')
    args = parser.parse_args(argv)
    try:
        files, report = build()
        if args.check:
            problems = stale(args.out, files)
            if problems:
                print('\n'.join(f'stale: {p}' for p in problems), file=sys.stderr)
                print('rerun: python app/tool/make_pet_sounds.py', file=sys.stderr)
                return 1
            print(f'naiwa: {len(files)} files up to date in {args.out}')
        else:
            write(args.out, files)
            print('\n'.join(report))
    except (OSError, ValueError, KeyError, wave.Error, EOFError, struct.error) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
