#!/usr/bin/env python3
"""Verify the byte-identical OoO directory migration against its pinned source tree.

Run on the migration commit. Later functional changes should fail this historical
identity check; this is not a permanent hardware-qualification or CI claim.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'src/main/scala/core/ooo/'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    manifest = json.loads((ROOT / 'docs/ooo-layout-migration.json').read_text())
    rows = manifest['files']
    before = manifest['base_tree']
    assert git('cat-file', '-t', before).decode().strip() == 'tree'
    # The public commit may not be downloaded in a local tree-equivalent checkout.
    public = subprocess.run(['git', 'cat-file', '-e', manifest['base_commit']], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if public.returncode == 0:
        assert git('rev-parse', manifest['base_commit'] + '^{tree}').decode().strip() == before
    old = {row['old'] for row in rows}
    new = {row['new'] for row in rows}
    assert len(rows) == len(old) == len(new) == 149
    tracked = git('ls-tree', '-r', '--name-only', before, BASE).decode().splitlines()
    assert old == {name for name in tracked if name.endswith('.scala')}
    assert new == {str(p.relative_to(ROOT)) for p in (ROOT / BASE).rglob('*.scala')}
    for row in rows:
        content = (ROOT / row['new']).read_bytes()
        assert content == git('show', before + ':' + row['old']), row['new']
        assert hashlib.sha256(content).hexdigest() == row['sha256'], row['new']
        assert not (ROOT / row['old']).exists(), row['old']
        assert b'package soc.core.ooo\n' in content, row['new']
    # The relocation cannot affect other production Scala files or resources.
    other = git('ls-tree', '-r', '--name-only', before, 'src/main', 'third_party').decode().splitlines()
    for name in other:
        if name in old or name.endswith('/AGENTS.md'):
            continue
        path = ROOT / name
        if path.is_file():
            assert path.read_bytes() == git('show', before + ':' + name), name
        else:
            raise AssertionError('missing production input: ' + name)
    changed = git('diff', '--name-only', before).decode().splitlines()
    for name in changed:
        path = ROOT / name
        if path.suffix == '.py' and path.is_file():
            parsed = ast.parse(path.read_text(), filename=name)
            for node in ast.walk(parsed):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and node.value.startswith(BASE) and node.value.endswith('.scala')):
                    assert (ROOT / node.value).is_file(), (name, node.lineno, node.value)
    for name in ('floating_point_cpu.py', 'floating_point_full.py', 'floating_point_memory.py'):
        source = (ROOT / 'simulator/gsim' / name).read_text()
        assert '"src/main/scala/core/ooo").rglob("*.scala")' in source, name
    print('PASS: 149 byte-identical moves; package/API unchanged; no other production input changes; recursive inventories; Python syntax/current literal paths')


if __name__ == '__main__':
    main()
