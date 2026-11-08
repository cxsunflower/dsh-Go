#!/usr/bin/env python3
"""Checks tooling/pets/build_pet_pack.py (docs/design/pets.md §3.6).

    python3 tooling/pets/test_build_pet_pack.py

Standard library only. Every expected value is computed here from the recipe,
never copied from the tool's own output.
"""

import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pet_pack as tool  # noqa: E402


def good_manifest(pack_id='naiwa'):
    return {
        'schema': 1,
        'id': pack_id,
        'name': '奶蛙',
        'author': 'github.com/cxsunflower',
        'canvas': {'w': 8, 'h': 8},
        'contentBox': {'x': 0, 'y': 0, 'w': 8, 'h': 8},
        'animations': {
            'idle': {
                'sheet': 'idle.png',
                'frameW': 8,
                'frameH': 8,
                'cols': 1,
                'box': {'x': 0, 'y': 0, 'w': 8, 'h': 8},
                'frames': [{'i': 0, 'ms': 100}],
            },
        },
        'states': {'idle': ['idle']},
    }


def write_pack(root, files, manifest=None):
    os.makedirs(root, exist_ok=True)
    data = {**files}
    data['pack.json'] = json.dumps(manifest or good_manifest(), ensure_ascii=False).encode('utf-8')
    for name, body in data.items():
        path = os.path.join(root, name.replace('/', os.sep))
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(body)
    return data


class DigestTest(unittest.TestCase):
    def test_recipe_matches_companion_runtime_digest(self):
        # runtimeDigest() in app/lib/companion/companion_pack.dart: names
        # sorted, `name\0sha256hex\n` joined, then sha256. Recomputed here by
        # hand from the two entries so the known value below is independent.
        files = {'sheets/idle.png': b'abc', 'sounds/x.wav': b'def'}
        hashes = tool.digest_hashes({**files, 'pack.json': b'{}'})
        self.assertEqual(hashes, {
            'sheets/idle.png': hashlib.sha256(b'abc').hexdigest(),
            'sounds/x.wav': hashlib.sha256(b'def').hexdigest(),
        })
        joined = (f'sheets/idle.png\x00{hashlib.sha256(b"abc").hexdigest()}\n'
                  f'sounds/x.wav\x00{hashlib.sha256(b"def").hexdigest()}\n')
        self.assertEqual(tool.digest(hashes), hashlib.sha256(joined.encode()).hexdigest())
        self.assertEqual(
            tool.digest({'b': '0' * 64, 'a': '1' * 64}),
            hashlib.sha256(f'a\x00{"1" * 64}\nb\x00{"0" * 64}\n'.encode()).hexdigest(),
            'sorted by name, not insertion order',
        )

    def test_pack_json_is_outside_the_digest(self):
        a = tool.digest_hashes({'pack.json': b'{"v":1}', 'sheets/idle.png': b'png'})
        b = tool.digest_hashes({'pack.json': b'{"v":2}', 'sheets/idle.png': b'png'})
        self.assertEqual(tool.digest(a), tool.digest(b))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pet-pack-test-')
        self.root = self.tmp.name
        self.src = os.path.join(self.root, 'src')
        self.out = os.path.join(self.root, 'out.zip')

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, files=None, manifest=None):
        data = write_pack(self.src, files or {'sheets/idle.png': b'\x89PNG idle'}, manifest)
        return tool.build(self.src, self.out), data

    def test_zip_reads_back_and_digest_covers_everything_but_pack_json(self):
        result, data = self.build({'sheets/idle.png': b'\x89PNG idle', 'sounds/a.wav': b'RIFF'})
        with zipfile.ZipFile(self.out) as archive:
            self.assertEqual(archive.namelist(), ['pack.json', 'sheets/idle.png', 'sounds/a.wav'])
            for name, body in data.items():
                self.assertEqual(archive.read(name), body, name)
            self.assertIsNone(archive.testzip())
        expected = tool.digest({
            'sheets/idle.png': hashlib.sha256(b'\x89PNG idle').hexdigest(),
            'sounds/a.wav': hashlib.sha256(b'RIFF').hexdigest(),
        })
        self.assertEqual(result['sha256'], expected)
        self.assertEqual(result['files'], 3)

    def test_two_runs_are_byte_identical(self):
        write_pack(self.src, {'sheets/idle.png': b'pixels', 'sounds/a.wav': b'RIFF'})
        first = tool.build(self.src, self.out)
        with open(self.out, 'rb') as fh:
            first_bytes = fh.read()
        second = tool.build(self.src, self.out)
        with open(self.out, 'rb') as fh:
            second_bytes = fh.read()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual(first['zip_sha256'], second['zip_sha256'])
        # No wall-clock time anywhere: DOS date 0 and the fixed 0x0021 time.
        self.assertIn(struct.pack('<H', 0x0021), first_bytes)

    def test_stored_when_deflate_does_not_help(self):
        result, _ = self.build({'sheets/idle.png': b'\x00\x01'})
        with zipfile.ZipFile(self.out) as archive:
            info = archive.getinfo('sheets/idle.png')
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.read(info), b'\x00\x01')
        self.assertTrue(result['zipbytes'] > 0)

    def test_entry_order_does_not_depend_on_write_order(self):
        write_pack(self.src, {'sounds/z.wav': b'z', 'sheets/a.png': b'a'})
        tool.build(self.src, self.out)
        with open(self.out, 'rb') as fh:
            first = fh.read()
        for name in ('sheets/a.png', 'sounds/z.wav'):
            os.remove(os.path.join(self.src, name.replace('/', os.sep)))
        write_pack(self.src, {'sheets/a.png': b'a', 'sounds/z.wav': b'z'})
        tool.build(self.src, self.out)
        with open(self.out, 'rb') as fh:
            self.assertEqual(fh.read(), first)

    def test_refuses_paths_the_installer_refuses(self):
        for bad in ('../escape.png', '/abs.png', 'sheets\\win.png', 'sheets/a b.png', 'sheets/CON.png',
                    'sheets/.hidden.png'):
            with self.subTest(path=bad), tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, 'src')
                # Write around the path rules to reach the validator itself.
                manifest = good_manifest()
                os.makedirs(os.path.join(src, 'sheets'), exist_ok=True)
                with open(os.path.join(src, 'pack.json'), 'w', encoding='utf-8') as fh:
                    json.dump(manifest, fh)
                files = {'sheets/idle.png': b'x', bad: b'x'}
                with self.assertRaises(tool.PackError):
                    tool.validate(files)

    def test_refuses_code_and_unknown_files(self):
        for bad in ('puppet.js', 'sheets/x.js', 'sounds/x.mp3', 'lib/libfoo.so', 'deep/x.json'):
            with self.subTest(file=bad):
                with self.assertRaises(tool.PackError):
                    tool.validate({'pack.json': b'{}', bad: b'x'})

    def test_refuses_oversized_and_too_many(self):
        with self.assertRaises(tool.PackError):
            tool.validate({**{'pack.json': b'{}'}, **{f'f{i}.png': b'x' for i in range(tool.MAX_FILES + 1)}})
        with self.assertRaises(tool.PackError):
            tool.validate({'pack.json': b'{}', 'big.png': b'\x00' * (tool.MAX_BYTES + 1)})

    def test_manifest_checks(self):
        for manifest in ({**good_manifest(), 'schema': 2}, {**good_manifest(), 'id': 'Bad Id'}):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, 'src')
                write_pack(src, {'sheets/idle.png': b'x'}, manifest)
                with self.assertRaises(tool.PackError):
                    tool.build(src, os.path.join(tmp, 'out.zip'))
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src')
            os.makedirs(src)
            with self.assertRaises(tool.PackError):
                tool.build(src, os.path.join(tmp, 'out.zip'))

    def test_folder_without_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'src', 'sheets'))
            with open(os.path.join(tmp, 'src', 'sheets', 'idle.png'), 'wb') as fh:
                fh.write(b'x')
            with self.assertRaises(tool.PackError):
                tool.build(os.path.join(tmp, 'src'), os.path.join(tmp, 'out.zip'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
