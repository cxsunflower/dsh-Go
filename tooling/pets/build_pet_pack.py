#!/usr/bin/env python3
"""Packages a pet pack as an installable zip (docs/design/pets.md §3.6).

    python3 tooling/pets/build_pet_pack.py --src app/assets/pets/naiwa --out naiwa.zip

`--src` is either a source folder as `app/tool/make_pet_pack.py` writes it
(`app/assets/pets/<id>/`: pack.json plus one PNG per animation) or a source
tree `app/tool/pet_src/<id>/` (pet.json plus `sheets/`), which is converted to
the shipped layout first with that tool's own converter. Only data goes in.

The zip is deterministic: entries in name order, fixed timestamps, no extra
fields. Its bytes and the pet pack digest are the same for the same input, on
every machine and run.

The digest is the companion pack's recipe, byte for byte
(`runtimeDigest()` in app/lib/companion/companion_pack.dart, and
`tooling/companion/build-pack.mjs`): sha256 over every file except pack.json,
names sorted, each contributing `name\\0sha256hex\\n`.

A pack that would be refused on install (`unsupported_file`, `bad_path`,
`too_big`) fails here instead, so a bad source never produces a zip.
"""

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib

MAX_BYTES = 32 * 1024 * 1024           # unpacked limit (pets.md §3.6 allows 48 MB)
MAX_FILES = 256
MAX_DOWNLOAD = 64 * 1024 * 1024        # compressed size limit, mirrors Dart

NAME_CHARS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-')
ID_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789-')
# Windows device names cannot be stored as files (the app writes the pack to
# disk), so a path segment naming one is refused as well.
RESERVED = re.compile(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)', re.IGNORECASE)


class PackError(Exception):
    pass


def check(cond, message):
    if not cond:
        raise PackError(message)


def safe_path(name):
    """The install-time path rule: ASCII segments, no `.`/`..`, no separators
    other than `/`."""
    if not name or '\\' in name or name.startswith('/') or '\x00' in name:
        return False
    return all(part and part not in ('.', '..') and set(part) <= NAME_CHARS
               and not part.startswith('.')
               and not RESERVED.match(part) and not part.endswith('.')
               for part in name.split('/'))


def allowed(name):
    """The pack layout rule: pack.json and sounds.json at the root, PNGs at the
    root (shipped layout) or under sheets/, WAVs under sounds/."""
    if name in ('pack.json', 'sounds.json'):
        return True
    ext = os.path.splitext(name)[1].lower()
    if name.startswith('sheets/'):
        return ext == '.png'
    if name.startswith('sounds/'):
        return ext == '.wav'
    return '/' not in name and ext == '.png'


def digest(hashes):
    """sha256 over sorted `name\\0sha256hex\\n` (companion's runtimeDigest)."""
    out = hashlib.sha256()
    for name in sorted(hashes):
        out.update(f'{name}\0{hashes[name]}\n'.encode('utf-8'))
    return out.hexdigest()


def digest_hashes(files):
    """name -> file bytes, as the digest sees them."""
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items() if name != 'pack.json'}


def read_pack(src):
    """(id, {relative name: bytes}) for a source or built pack folder."""
    if not os.path.isdir(src):
        raise PackError(f'{src}: not a folder')
    with tempfile.TemporaryDirectory(prefix='pet-pack-build-') as tmp:
        if os.path.isfile(os.path.join(src, 'pet.json')):
            built = convert_source(src, tmp)
            return read_pack(built)
        return _read_folder(src)


def convert_source(src, out_root):
    """Runs app/tool/make_pet_pack.py for a pet_src folder (pet.json plus
    sheets/) and returns the folder it wrote."""
    here = os.path.dirname(os.path.abspath(__file__))
    app = os.path.dirname(os.path.dirname(here))
    tool = os.path.join(app, 'tool', 'make_pet_pack.py')
    check(os.path.isfile(tool), f'{tool}: make_pet_pack.py not found')
    pack_id = os.path.basename(os.path.normpath(src))
    parent = os.path.dirname(os.path.normpath(src))
    result = subprocess.run(
        [sys.executable, tool, '--src', parent, '--out', out_root, '--preview', '', '--only', pack_id],
        cwd=app, capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    out = os.path.join(out_root, pack_id)
    if result.returncode != 0 or not os.path.isdir(out):
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['no output']
        raise PackError(f'{src}: make_pet_pack.py failed ({detail[0]}); '
                        f'build app/assets/pets/{pack_id} first or add the pack to its PACKS')
    return out


def _read_folder(src):
    files = {}
    for root, dirs, names in os.walk(src):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, src).replace(os.sep, '/')
            if rel.startswith('.'):
                continue
            if not os.path.isfile(path):
                raise PackError(f'{rel}: not a regular file')
            with open(path, 'rb') as fh:
                files[rel] = fh.read()
    check('pack.json' in files, f'{src}: no pack.json (run make_pet_pack.py first for pet_src sources)')
    try:
        manifest = json.loads(files['pack.json'].decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackError(f'pack.json: {error}') from None
    check(isinstance(manifest, dict), 'pack.json: not an object')
    pack_id = manifest.get('id')
    check(isinstance(pack_id, str) and pack_id and set(pack_id) <= ID_CHARS, 'pack.json: id needs [a-z0-9-]+')
    check(manifest.get('schema') == 1, 'pack.json: schema must be 1')
    return pack_id, files


def validate(files):
    check(len(files) <= MAX_FILES, f'{len(files)} files, at most {MAX_FILES}')
    total = 0
    for name, data in files.items():
        check(safe_path(name), f'{name}: unsafe path')
        check(allowed(name), f'{name}: not a pack data file')
        total += len(data)
    check(total <= MAX_BYTES, f'{total} bytes unpacked, at most {MAX_BYTES}')
    return total


def make_zip(files):
    """The byte format of tooling/companion/build-pack.mjs: local headers in
    name order, fixed DOS time 0x00210000, UTF-8 names, then the central
    directory and the end record."""
    parts, central = [], []
    offset = 0
    for name in sorted(files):
        encoded = name.encode('utf-8')
        data = files[name]
        deflated = _deflate_raw(data)
        if len(deflated) >= len(data):
            method, body = 0, data
        else:
            method, body = 8, deflated
        crc = zlib.crc32(data) & 0xFFFFFFFF
        head = struct.pack('<HHHIIIIHH', 20, 0x0800, method, 0x00210000, crc,
                           len(body), len(data), len(encoded), 0)
        local = struct.pack('<I', 0x04034B50) + head + encoded + body
        central.append(struct.pack('<IHHHHHHIIIHHHHHII', 0x02014B50, 20, 20, 0x0800, method,
                                   0x0000, 0x0021, crc, len(body), len(data), len(encoded),
                                   0, 0, 0, 0, 0, offset) + encoded)
        parts.append(local)
        offset += len(local)
    directory = b''.join(central)
    end = struct.pack('<IHHHHIIH', 0x06054B50, 0, 0, len(files), len(files),
                      len(directory), offset, 0)
    return b''.join([*parts, directory, end])


def _deflate_raw(data):
    """Raw deflate (no zlib wrapper), as build-pack.mjs's deflateRawSync."""
    encoder = zlib.compressobj(9, zlib.DEFLATED, -15)
    return encoder.compress(data) + encoder.flush()


def build(src, out):
    pack_id, files = read_pack(src)
    total = validate(files)
    zip_bytes = make_zip(files)
    check(len(zip_bytes) <= MAX_DOWNLOAD, f'{len(zip_bytes)} bytes zipped, download cap {MAX_DOWNLOAD}')
    directory = os.path.dirname(os.path.abspath(out))
    os.makedirs(directory, exist_ok=True)
    with open(out, 'wb') as fh:
        fh.write(zip_bytes)
    return {
        'id': pack_id,
        'out': out,
        'files': len(files),
        'bytes': total,
        'zipbytes': len(zip_bytes),
        'sha256': digest(digest_hashes(files)),
        'zip_sha256': hashlib.sha256(zip_bytes).hexdigest(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--src', required=True, help='a pack folder (assets/pets/<id>) or pet_src/<id>')
    ap.add_argument('--out', required=True, help='the .zip to write')
    args = ap.parse_args(argv)
    try:
        result = build(args.src, args.out)
    except PackError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    print(f'id              {result["id"]}')
    print(f'pack            {result["out"]}')
    print(f'files           {result["files"]}')
    print(f'bytes           {result["bytes"]} unpacked, {result["zipbytes"]} zipped')
    print(f'zip sha256      {result["zip_sha256"]}')
    print(f'pack sha256     {result["sha256"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
