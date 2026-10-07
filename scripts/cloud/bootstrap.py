#!/usr/bin/env python3
"""Install the cloud checker's pinned tools locally; never changes system settings."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ENV = ROOT / 'simulator/build/cloud-env'
LOCK = json.loads((HERE / 'downloads.lock.json').read_text())


def checked(args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT, **kwargs)


def fetch(item):
    name, spec = item
    target = ENV / spec.get('cache_path', 'downloads/' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(target.name + '.partial')
        checked(['curl', '-fSL', '--retry', '2', '--max-time', '240', spec['url'], '-o', temporary])
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != spec['sha256']:
            raise RuntimeError(f'Download hash mismatch: {name}')
        temporary.rename(target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != spec['sha256']:
        raise RuntimeError(f'Existing file hash mismatch: {target}')
    return name, target


def main():
    for directory in ('bin', 'downloads', 'sysroot', 'home', 'cache', 'logs'):
        (ENV / directory).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        files = dict(pool.map(fetch, LOCK['artifacts'].items()))
    for name, path in files.items():
        if name.endswith('.deb'):
            checked(['dpkg-deb', '-x', path, ENV / 'sysroot'])
    shutil.copyfile(files['mill-1.1.7'], ENV / 'bin/mill-dist')
    (ENV / 'bin/mill').write_text('#!/usr/bin/env bash\nexec bash "$(dirname -- "$0")/mill-dist" "$@"\n')
    (ENV / 'bin/mill').chmod(0o755)
    checked(['git', 'submodule', 'update', '--init', '--depth', '1', 'NEMU'])
    reference = json.loads((ROOT / 'simulator/gsim/config/reference-lock.json').read_text())
    revision = subprocess.check_output(['git', '-C', ROOT / 'NEMU', 'rev-parse', 'HEAD'], text=True).strip()
    if revision != reference['revision']:
        raise RuntimeError('NEMU checkout differs from reference-lock.json')
    for name, expected in reference['resources'].items():
        source = files[Path(name).name]
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'NEMU resource mismatch: {name}')
        destination = ROOT / 'NEMU/resource' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise RuntimeError(f'Refusing to overwrite changed resource: {destination}')
        shutil.copyfile(source, destination)
    print('Tools prepared. Source scripts/cloud/env.sh, then run make gsim-setup and make compile.')


if __name__ == '__main__':
    main()
