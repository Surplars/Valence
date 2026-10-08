#!/usr/bin/env python3
"""Read-only binding of integrated RTL source to an explicitly locked Git commit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def verify_dev_sources(repo, commit, manifest):
    repo = Path(repo).resolve()
    expected = json.loads(Path(manifest).read_text())
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise RuntimeError('supply the full confirmed dev commit SHA')
    git = lambda *args: subprocess.check_output(['git', '-C', str(repo), *args])
    if git('rev-parse', 'HEAD').decode().strip() != commit:
        raise RuntimeError('existing checkout HEAD is not the confirmed dev commit')
    expected_scala = {p for p in expected if p.startswith('src/main/scala/')}
    tracked = set(git('ls-tree', '-r', '--name-only', commit, 'src/main/scala').decode().splitlines())
    actual = {p.relative_to(repo).as_posix() for p in (repo / 'src/main/scala').rglob('*.scala')}
    if {p for p in tracked if p.endswith('.scala')} != expected_scala or actual != expected_scala:
        raise RuntimeError('production Scala inventory differs from exported source')
    for name, digest in expected.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("unsafe source manifest path: " + name)
        path = repo / relative
        linked = any(repo.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts) + 1))
        if linked or not path.is_file():
            raise RuntimeError('missing or linked source: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('working source differs from export: ' + name)
        if hashlib.sha256(git('show', commit + ':' + name)).hexdigest() != digest:
            raise RuntimeError('committed source differs from export: ' + name)
    return {'status': 'PASS', 'commit': commit, 'source_files': len(expected),
            'manifest_sha256': hashlib.sha256(Path(manifest).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    print(json.dumps(verify_dev_sources(args.repo, args.commit,
        Path(__file__).with_name('integrated-source-sha256.json')), indent=2))


if __name__ == '__main__':
    main()
