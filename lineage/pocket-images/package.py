#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package immutable Pocket system files independently of the host APK.

The initial bootstrap is a checksum-pinned existing image, not a claim to have
rebuilt Android from source. A materialized root plus its exported input lock
can independently reproduce the same image archive.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import urllib.parse
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
PREFIX = 'assets/api28-rootfs/'
LIMIT = 2 * 1024**3


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)+'\n').encode()


def safe_path(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or '\0' in name or str(path) != name or
            path.parts[0] not in ('system', 'vendor') or '..' in path.parts or
            len(path.parts) < 2):
        raise ValueError('Unsafe image path: '+name)
    return name


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def archive_entry(name, data, mode):
    entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | mode) << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    return entry, data


def package(recipe, output, base_url, *, apk=None, root=None, inputs=None):
    if recipe.get('archive', {}).get('zlib_version', zlib.ZLIB_VERSION) != zlib.ZLIB_VERSION:
        raise ValueError('Archive compressor differs from the recipe pin')
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1')) or parsed.query or parsed.fragment:
        raise ValueError('Use an immutable HTTPS release URL (loopback HTTP is for tests only)')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    members = {}
    if apk:
        if digest_file(apk) != recipe['bootstrap']['sha256']:
            raise ValueError('Bootstrap APK differs from its pinned SHA-256')
        with zipfile.ZipFile(apk) as source:
            for entry in source.infolist():
                if not entry.filename.startswith(PREFIX):
                    continue
                if not entry.filename.endswith('.payload') or entry.is_dir():
                    raise ValueError('Unexpected bootstrap image entry')
                name = safe_path(entry.filename[len(PREFIX):-8])
                if name in members or entry.file_size < 0 or entry.file_size > LIMIT:
                    raise ValueError('Duplicate or oversized image entry')
                # Match DirectImage's established extraction contract, including
                # executable helpers/scripts under system/etc/pocket-magisk.
                # APK ZipInfo modes do not reliably retain these permissions.
                mode = 0o755
                members[name] = (source.read(entry), mode)
        provenance = recipe['bootstrap']
    else:
        lock = json.loads(Path(inputs).read_text())
        if lock['recipe'] != recipe:
            raise ValueError('Input lock belongs to a different recipe')
        for name, spec in lock['entries'].items():
            safe_path(name); path = Path(root)/name
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != Path(root).parent):
                raise ValueError('Input image must contain regular files only')
            data = path.read_bytes()
            if len(data) != spec['size'] or hashlib.sha256(data).hexdigest() != spec['sha256']:
                raise ValueError('Input differs from lock: '+name)
            members[name] = (data, spec['mode'])
        provenance = lock['provenance']
    if not members or sum(len(data) for data, _ in members.values()) > LIMIT:
        raise ValueError('Image is empty or exceeds unpacked size limit')
    for required in ('system/bin/pocket-init-api28', 'system/bin/pocket-loader',
                     'system/build.prop', 'system/usr/keychars/Virtual.kcm'):
        if required not in members:
            raise ValueError('Missing required image file: '+required)
    if b'ro.build.version.sdk=28\n' not in members['system/build.prop'][0]:
        raise ValueError('Image is not Android API 28')
    entries = {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'crc32': zlib.crc32(data), 'mode': mode}
               for name, (data, mode) in sorted(members.items())}
    manifest = {key: recipe[key] for key in ('profile', 'sdk', 'abi', 'runtime', 'version')}
    manifest.update(schema=1, entries=entries, provenance=provenance)
    metadata = encode(manifest)
    name = 'pocket-api28-arm64-'+recipe['version']+'.zip'
    archive = output/name
    temporary = archive.with_suffix('.zip.part')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as target:
        info, data = archive_entry('pocket-image.json', metadata, 0o644)
        target.writestr(info, data, compresslevel=1)
        for path, (data, mode) in sorted(members.items()):
            info, data = archive_entry(path, data, mode)
            target.writestr(info, data, compresslevel=1)
    temporary.replace(archive)
    descriptor = {key: manifest[key] for key in ('profile', 'sdk', 'abi', 'runtime', 'version')}
    descriptor.update(url=base_url.rstrip('/')+'/'+name, bytes=archive.stat().st_size,
                      sha256=digest_file(archive), unpacked_bytes=sum(v['size'] for v in entries.values()),
                      manifest_sha256=hashlib.sha256(metadata).hexdigest(), manifest=manifest)
    (output/'pocket-images.json').write_bytes(encode({'schema': 1, 'images': [descriptor]}))
    (output/'image-inputs.lock.json').write_bytes(encode({'recipe': recipe, 'provenance': provenance, 'entries': entries}))
    (output/'SHA256SUMS').write_text(descriptor['sha256']+'  '+name+'\n')
    return descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--apk', type=Path)
    group.add_argument('--rootfs', type=Path)
    parser.add_argument('--inputs-lock', type=Path)
    parser.add_argument('--recipe', type=Path, default=HERE/'recipe.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    if args.rootfs and not args.inputs_lock:
        parser.error('--rootfs requires --inputs-lock')
    result = package(json.loads(args.recipe.read_text()), args.output, args.base_url,
                     apk=args.apk, root=args.rootfs, inputs=args.inputs_lock)
    print(json.dumps({k: v for k, v in result.items() if k != 'manifest'}, indent=2))


if __name__ == '__main__':
    main()
