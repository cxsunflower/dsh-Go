#!/usr/bin/env python3
"""Check the six pak effects, their provenance, the laugh's resample and rebuilding.

    python app/tool/test_make_pet_sounds.py

Uses only the standard library; does not download audio or require FFmpeg.
"""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import wave

import make_pet_sounds as tool


OUT = Path(__file__).resolve().parents[1] / 'assets' / 'pet_sounds' / 'naiwa'
INPUT = Path(__file__).parent / 'pet_src' / 'naiwa' / 'audio'
IDS = ['hahahahahahaha', 'dajiaosei', 'diu', 'andi', 'gagadilaxia', 'houla']
LAUGH = 'hahahahahahaha'
PAK_SHA256 = '093ace9eef9b133e923fd08a3d7c70472f84855df8731e704b3855349483af13'
LAUGH_SOURCE_SHA256 = '8639564ebc3d924d39ca6b9f2abc89a376d72f7e0233416c3cdde39adc84a5fc'
DURATIONS = {
    'hahahahahahaha': 25.286531,
    'dajiaosei': 1.071020,
    'diu': 1.071020,
    'andi': 1.306122,
    'gagadilaxia': 1.384490,
    'houla': 2.089796,
}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = tool.main(argv)
    return code, out.getvalue(), err.getvalue()


def wav(seconds, channels=1, rate=22050):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as clip:
        clip.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        clip.writeframes(b'\x01\x00' * round(seconds * rate) * channels)
    return buffer.getvalue()


def chunks(data):
    found, offset = {}, 12
    while offset < len(data):
        kind, size = struct.unpack('<4sI', data[offset:offset + 8])
        found[kind] = data[offset + 8:offset + 8 + size]
        if len(found[kind]) != size:
            raise AssertionError('truncated chunk')
        offset += 8 + size + (size % 2)
    return found, offset


def sounds_ms(cid):
    sounds = json.loads((OUT / 'sounds.json').read_bytes())
    return sounds['clips'][cid]['ms']


class Effects(unittest.TestCase):
    def test_six_named_clips_at_gain_one_without_pitch_variation(self):
        sounds = json.loads((OUT / 'sounds.json').read_bytes())
        self.assertEqual(sounds['schema'], 1)
        self.assertEqual(sounds['id'], 'naiwa')
        self.assertEqual(list(sounds['clips']), IDS)
        for cid, clip in sounds['clips'].items():
            self.assertEqual(clip['file'], f'{cid}.wav')
            self.assertEqual((clip['gain'], clip['vary']), (1.0, 0.0))
            self.assertGreater(clip['ms'], 0)
            self.assertNotRegex(cid, r'[^a-z0-9-]')

    def test_cue_mapping_matches_the_design(self):
        sounds = json.loads((OUT / 'sounds.json').read_bytes())
        self.assertEqual(sounds['cues'], {
            'laugh': [LAUGH], 'laugh-point': [LAUGH],
            'laugh-roll': [LAUGH], 'laugh-belly': [LAUGH],
            'poke-left': ['dajiaosei'], 'poke-right': ['diu'],
            'wake': ['andi'], 'prone-eat': ['gagadilaxia'],
            'alert': ['houla'],
        })
        for silent in ('@bite', '@drop', 'idle', 'sleep', 'thinking', 'snack', 'guichu'):
            self.assertNotIn(silent, sounds['cues'])

    def test_five_effects_are_byte_copies_and_only_the_laugh_is_resampled(self):
        provenance = json.loads((INPUT / 'sources.json').read_bytes())
        for cid in IDS:
            with self.subTest(cid=cid):
                source = (INPUT / f'{cid}.wav').read_bytes()
                asset = (OUT / f'{cid}.wav').read_bytes()
                self.assertEqual(hashlib.sha256(source).hexdigest(), provenance[cid]['pcmSha256'])
                if cid != LAUGH:
                    self.assertEqual(asset, source)
                    self.assertIsNone(provenance[cid]['resample'])

    def test_the_laugh_keeps_all_25_286_531_seconds_at_11025_hz(self):
        source = (INPUT / f'{LAUGH}.wav').read_bytes()
        asset = (OUT / f'{LAUGH}.wav').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), LAUGH_SOURCE_SHA256)
        src_chunks, src_end = chunks(source)
        out_chunks, out_end = chunks(asset)
        self.assertEqual(src_end, len(source))
        self.assertEqual(out_end, len(asset))
        self.assertEqual([k for k in src_chunks if k != b'data'], [k for k in out_chunks if k != b'data'])
        for kind, body in out_chunks.items():
            if kind != b'data' and kind != b'fmt ':
                self.assertEqual(body, src_chunks[kind], kind)
        self.assertEqual(struct.unpack('<HHIIHH', out_chunks[b'fmt ']), (1, 1, 11025, 22050, 2, 16))
        self.assertEqual(len(out_chunks[b'data']), 557568)
        self.assertEqual(struct.unpack('<I', asset[4:8])[0], len(asset) - 8)
        with wave.open(io.BytesIO(asset)) as clip:
            self.assertEqual((clip.getnchannels(), clip.getsampwidth(), clip.getframerate()), (1, 2, 11025))
            self.assertEqual(clip.getnframes(), 278784)
            self.assertAlmostEqual(clip.getnframes() / 11025, 25.2865306122, places=9)
        self.assertEqual(sounds_ms(LAUGH), 25287)

    def test_wav_headers_duration_and_budgets(self):
        total = 0
        for cid in IDS:
            with self.subTest(cid=cid):
                data = (OUT / f'{cid}.wav').read_bytes()
                self.assertEqual(struct.unpack('<4sI4s', data[:12]), (b'RIFF', len(data) - 8, b'WAVE'))
                found, end = chunks(data)
                self.assertEqual(end, len(data))
                rate = 11025 if cid == LAUGH else 22050
                self.assertEqual(struct.unpack('<HHIIHH', found[b'fmt ']), (1, 1, rate, rate * 2, 2, 16))
                self.assertEqual(len(found[b'data']) % 2, 0)
                self.assertLessEqual(len(found[b'data']), 1_000_000)
                seconds = len(found[b'data']) / (rate * 2)
                self.assertGreaterEqual(seconds, 0.05)
                self.assertAlmostEqual(seconds, DURATIONS[cid], places=5)
                total += len(data)
        self.assertLessEqual(total + (OUT / 'sounds.json').stat().st_size, 1_500_000)

    def test_clip_ms_is_the_clip_length(self):
        for cid in IDS:
            self.assertEqual(sounds_ms(cid), round(DURATIONS[cid] * 1000), cid)

    def test_provenance_names_the_pak_and_its_entries(self):
        provenance = json.loads((INPUT / 'sources.json').read_bytes())
        self.assertEqual(sorted(provenance), sorted(IDS))
        for cid in IDS:
            entry = provenance[cid]
            with self.subTest(cid=cid):
                self.assertEqual(entry['pak'], 'nawa_pak50_dir.vpk')
                self.assertEqual(entry['pakSha256'], PAK_SHA256)
                self.assertTrue(entry['pakEntry'].startswith('sounds/abilities/dynamo/'))
                self.assertTrue(entry['pakEntry'].endswith('.vsnd_c'))
                self.assertNotIn(cid, entry['pakEntry'], 'the asset name never leaks into the source path')
        self.assertIn('11025', provenance[LAUGH]['resample'])
        self.assertIn('1,000,000', provenance[LAUGH]['resample'])


class Rebuild(unittest.TestCase):
    def test_checked_in_assets_match_repeatable_build(self):
        files, _ = tool.build()
        self.assertEqual(files, tool.build()[0])
        self.assertEqual({p.name for p in OUT.iterdir()}, set(files))
        for name, data in files.items():
            self.assertEqual((OUT / name).read_bytes(), data, name)
        self.assertEqual(run(['--check'])[0], 0)
        for data in (files['sounds.json'], (INPUT / 'sources.json').read_bytes()):
            self.assertNotIn(b'\r', data)
            self.assertTrue(data.endswith(b'\n'))

    def test_check_reports_damage_and_generation_removes_retired_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(run(['--out', tmp])[0], 0)
            (folder / f'{LAUGH}.wav').write_bytes(b'changed')
            (folder / 'houla.wav').unlink()
            (folder / 'haha-big.wav').write_bytes(b'obsolete effect')
            (folder / 'notes.txt').write_bytes(b'keep')
            code, _, err = run(['--out', tmp, '--check'])
            self.assertEqual(code, 1)
            for problem in (f'{LAUGH}.wav: out of date', 'houla.wav: missing',
                            'haha-big.wav: not made by this tool'):
                self.assertIn(problem, err)
            self.assertEqual((folder / f'{LAUGH}.wav').read_bytes(), b'changed')
            self.assertEqual(run(['--out', tmp])[0], 0)
            self.assertEqual(run(['--out', tmp, '--check'])[0], 0)
            self.assertFalse((folder / 'haha-big.wav').exists())
            self.assertEqual((folder / 'notes.txt').read_bytes(), b'keep')

    def test_check_never_creates_a_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing'
            code, _, err = run(['--out', str(missing), '--check'])
            self.assertEqual(code, 1)
            self.assertIn('sounds.json: missing', err)
            self.assertFalse(missing.exists())

    def test_rejects_corrupt_input_or_wrong_provenance(self):
        cases = [
            ('dajiaosei', 'checksum', 'PCM checksum mismatch'),
            ('dajiaosei', 'format', 'expected PCM16 mono'),
            ('dajiaosei', 'truncated', 'truncated PCM'),
            (LAUGH, 'frames', 'frame count mismatch'),
            ('houla', 'long', 'outside 0.05..2.5 s'),
            (LAUGH, 'cue', 'cue mapping mismatch'),
        ]
        for cid, kind, message in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / 'inputs'
                shutil.copytree(INPUT, folder)
                manifest = json.loads((folder / 'sources.json').read_bytes())
                path = folder / f'{cid}.wav'
                if kind == 'cue':
                    manifest[cid]['cue'] = ['poke-left']
                elif kind == 'frames':
                    manifest[cid]['frames'] += 1
                else:
                    data = path.read_bytes()
                    if kind == 'checksum':
                        data = data[:-1] + bytes([data[-1] ^ 1])
                    elif kind == 'format':
                        data = wav(1, channels=2)
                    elif kind == 'truncated':
                        data = data[:-2]
                    else:
                        seconds = 2.6
                        data = wav(seconds)
                        manifest[cid]['frames'] = round(seconds * 22050)
                    path.write_bytes(data)
                    if kind != 'checksum':
                        manifest[cid]['pcmSha256'] = hashlib.sha256(data).hexdigest()
                (folder / 'sources.json').write_text(json.dumps(manifest), encoding='utf-8')
                with mock.patch.object(tool, 'INPUT', folder), self.assertRaisesRegex(tool.BuildError, message):
                    tool.build()

    def test_rejects_missing_inputs_or_a_wrong_clip_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'inputs'
            shutil.copytree(INPUT, folder)
            (folder / 'gagadilaxia.wav').unlink()
            with mock.patch.object(tool, 'INPUT', folder), self.assertRaisesRegex(tool.BuildError, 'gagadilaxia'):
                tool.build()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'inputs'
            shutil.copytree(INPUT, folder)
            manifest = json.loads((folder / 'sources.json').read_bytes())
            manifest.pop('houla')
            (folder / 'sources.json').write_text(json.dumps(manifest), encoding='utf-8')
            with mock.patch.object(tool, 'INPUT', folder), self.assertRaisesRegex(tool.BuildError, 'sources.json lists'):
                tool.build()

    def test_rejects_over_budget_set(self):
        with mock.patch.object(tool, 'MAX_BYTES', 1000), self.assertRaisesRegex(tool.BuildError, 'over 1000'):
            tool.build()
        with mock.patch.object(tool, 'MAX_PCM_BYTES', 1000), self.assertRaisesRegex(tool.BuildError, 'SoundPool storage'):
            tool.build()


class Resample(unittest.TestCase):
    def test_half_rate_linear_interpolation_keeps_chunks_and_the_length(self):
        source = wav(1.0)
        source = source[:44] + b'\x00\x00\xff\x7f\x00\x00\x00\x80' + source[52:]
        resampled, seconds = tool.resample_wav(source, 11025)
        src_chunks, _ = chunks(source)
        out_chunks, end = chunks(resampled)
        self.assertEqual(end, len(resampled))
        self.assertEqual(struct.unpack('<I', resampled[4:8])[0], len(resampled) - 8)
        self.assertEqual(out_chunks[b'fmt '], src_chunks[b'fmt '][:4] + b'\x11\x2b\x00\x00' + b'\x22\x56\x00\x00' + src_chunks[b'fmt '][12:])
        self.assertEqual(len(out_chunks[b'data']), 22050)
        self.assertEqual(out_chunks[b'data'][:2], b'\x00\x00')
        self.assertEqual(out_chunks[b'data'][-2:], b'\x01\x00')
        self.assertEqual(seconds, 1.0)

    def test_refuses_a_rate_that_is_not_half_the_source(self):
        with self.assertRaisesRegex(tool.BuildError, 'half-rate'):
            tool.resample_wav(wav(1.0), 16000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
