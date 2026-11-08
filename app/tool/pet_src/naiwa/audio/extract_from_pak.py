#!/usr/bin/env python3
"""Re-extract the six Naiwa effects from the Deadlock addon pak.

    python3 extract_from_pak.py <nawa_pak50_dir.vpk> [--ffmpeg PATH] [--check]

The pak is Valve VPK v2 (`nawa_pak50_dir.vpk`, sha256 pinned below and in
sources.json). Each entry is a `vsnd_c`: a KV3 resource header followed by
MP3 frames. This script pulls the six entries out, checks each one against the
`sourceSha256` in `sources.json`, decodes the MP3 to PCM16 mono 22050 Hz with
ffmpeg, and writes `<clip id>.wav` next to this file — the inputs
`app/tool/make_pet_sounds.py` packages into `app/assets/pet_sounds/naiwa/`.

Only this step needs ffmpeg (PATH, or `--ffmpeg`); building and testing the app
stay stdlib-only. `--check` extracts and verifies without writing.

The decoded audio is bit-identical whatever ffmpeg wrote it, but the WAV's
INFO/ISFT chunk names the writer, and sources.json pins the *file* hash. The
chunk is therefore rewritten to the name the pins were made with, so a
re-extraction is byte-for-byte reproducible on a newer ffmpeg. The audio bytes
are never touched.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

HERE = Path(__file__).resolve().parent
SOURCES = HERE / 'sources.json'

MAGIC = 0x55AA1234
STORED = 0x7FFF
HEADER_V2 = 28
RATE = 22050

# The ffmpeg release the pinned WAV hashes came from; its INFO/ISFT string is
# restored after decoding so the files stay byte-identical.
ISFT = b'Lavf61.7.100'


class ExtractError(ValueError):
    pass


def read_cstr(data, off):
    end = data.index(b'\0', off)
    return data[off:end].decode('utf-8', 'replace'), end + 1


def parse_vpk(data):
    """Every entry the tree names, as dicts with their bytes read lazily."""
    magic, version = struct.unpack_from('<II', data, 0)
    if magic != MAGIC:
        raise ExtractError('not a VPK: magic %08x' % magic)
    if version != 2:
        raise ExtractError('only VPK v2 is read: version %d' % version)
    (tree_size, _data_size, _md5, _other_md5, _sig) = struct.unpack_from('<IIIII', data, 8)
    data_start = HEADER_V2 + tree_size

    entries = []
    off = HEADER_V2
    # The tree is nested — extension / path / filename, each level closed by an
    # empty string, an empty extension ending it — not a flat list of triples.
    while True:
        ext, off = read_cstr(data, off)
        if not ext:
            break
        while True:
            path, off = read_cstr(data, off)
            if not path:
                break
            while True:
                name, off = read_cstr(data, off)
                if not name:
                    break
                _crc, preload, archive, entry_off, entry_len = struct.unpack_from('<IHHII', data, off)
                off += 18
                if struct.unpack_from('<H', data, off - 2)[0] != 0xFFFF:
                    raise ExtractError('bad tree terminator')
                preload_data = data[off:off + preload]
                off += preload
                if preload_data:
                    blob = preload_data
                elif archive == STORED:
                    blob = data[data_start + entry_off:data_start + entry_off + entry_len]
                else:
                    continue  # an external archive: not this pak's business
                entries.append({'ext': ext, 'path': path, 'name': name, 'blob': blob})
    return entries


def mp3_offset(blob):
    """Where the MP3 frames start: the first FF Ex sync after the KV3 header."""
    for i in range(len(blob) - 1):
        if blob[i] == 0xFF and (blob[i + 1] & 0xE0) == 0xE0:
            return i
    return -1


def chunks(data):
    """The WAV's chunks in order, with where the body of each starts."""
    out, off = [], 12
    while off + 8 <= len(data):
        kind = data[off:off + 4]
        size = struct.unpack_from('<I', data, off + 4)[0]
        if off + 8 + size > len(data):
            raise ExtractError('truncated WAV chunk %r' % kind)
        out.append((kind, off + 8, size))
        off += 8 + size + (size % 2)
    return out


def normalize_isft(data):
    """[data] with ffmpeg's writer name put back to [ISFT]."""
    for kind, body, size in chunks(data):
        if kind != b'LIST':
            continue
        # LIST INFO/ISFT <len> <text> — a small, fixed shape.
        at = data[body:body + size].find(b'ISFT')
        if at < 0:
            continue
        text_at = body + at + 4 + 4
        end = data.index(b'\0', text_at)
        old = data[text_at:end]
        if old == ISFT:
            return data
        if len(old) != len(ISFT):
            raise ExtractError('ISFT is %r, not the pinned length' % old)
        return data[:text_at] + ISFT + data[end:]
    return data


def decode(ffmpeg, mp3, out):
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(mp3),
           '-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_s16le', str(out)]
    done = subprocess.run(cmd, capture_output=True)
    if done.returncode != 0:
        raise ExtractError('ffmpeg: %s' % done.stderr.decode('utf-8', 'replace').strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('vpk')
    parser.add_argument('--ffmpeg', default=os.environ.get('FFMPEG') or shutil.which('ffmpeg'))
    parser.add_argument('--check', action='store_true', help='verify only; write nothing')
    args = parser.parse_args()

    if not args.ffmpeg:
        raise SystemExit('ffmpeg not found: put it on PATH, set FFMPEG, or use --ffmpeg')

    sources = json.loads(SOURCES.read_text(encoding='utf-8'))
    data = Path(args.vpk).read_bytes()
    print('pak %s  %d bytes  sha256 %s' % (Path(args.vpk).name, len(data), hashlib.sha256(data).hexdigest()))

    entries = parse_vpk(data)
    by_name = {}
    for entry in entries:
        key = '%s.%s' % (entry['name'], entry['ext'])
        by_name.setdefault(key, []).append(entry)

    work = Path(tempfile.mkdtemp(prefix='naiwa-audio-'))
    try:
        for cid, pinned in sources.items():
            key = pinned['pakEntry'].rsplit('/', 1)[-1]
            found = by_name.get(key) or []
            if len(found) != 1:
                raise ExtractError('%s: %d pak entries named %s' % (cid, len(found), key))
            blob = found[0]['blob']
            blob_sha = hashlib.sha256(blob).hexdigest()
            if blob_sha != pinned['sourceSha256']:
                raise ExtractError('%s: vsnd_c sha256 %s, wanted %s' % (cid, blob_sha, pinned['sourceSha256']))
            at = mp3_offset(blob)
            if at < 0:
                raise ExtractError('%s: no MP3 frames in the entry' % cid)
            mp3 = work / ('%s.mp3' % cid)
            mp3.write_bytes(blob[at:])
            out = work / ('%s.wav' % cid)
            decode(args.ffmpeg, mp3, out)
            wav = normalize_isft(out.read_bytes())
            shas = hashlib.sha256(wav).hexdigest()
            with wave.open(io.BytesIO(wav)) as clip:
                if (clip.getnchannels(), clip.getsampwidth(), clip.getframerate(), clip.getcomptype()) != (1, 2, RATE, 'NONE'):
                    raise ExtractError('%s: not PCM16 mono 22050 Hz' % cid)
                frames = clip.getnframes()
            if len(wav) != pinned['bytes'] or frames != pinned['frames']:
                raise ExtractError('%s: %d bytes / %d frames, wanted %d / %d' % (
                    cid, len(wav), frames, pinned['bytes'], pinned['frames']))
            if shas != pinned['pcmSha256']:
                raise ExtractError('%s: WAV sha256 %s, wanted %s' % (cid, shas, pinned['pcmSha256']))
            print('  %-16s %7d bytes  %6.3f s  vsnd %s  wav %s' % (
                cid, len(wav), frames / RATE, blob_sha[:16], shas[:16]))
            if not args.check:
                (HERE / ('%s.wav' % cid)).write_bytes(wav)
        print('six effects verified%s' % ('' if not args.check else ' (nothing written)'))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    try:
        main()
    except ExtractError as err:
        print('✗ %s' % err, file=sys.stderr)
        raise SystemExit(1)
