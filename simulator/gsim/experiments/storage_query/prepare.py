#!/usr/bin/env python3
"""Generate exact-source test overlays; never edit production sources/classes."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply_exact(source, patch):
    """Single-file unified diff with exact line positions and context, no fuzz."""
    original = source.splitlines(keepends=True)
    lines = patch.splitlines(keepends=True)
    assert lines[0].startswith('--- ') and lines[1].startswith('+++ ')
    result, pos, i = [], 0, 2
    while i < len(lines):
        match = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@\n', lines[i])
        if not match:
            raise ValueError('unsupported patch header')
        start, old_count, new_start, new_count = map(int, match.groups())
        if start - 1 < pos:
            raise ValueError('overlapping patch')
        result.extend(original[pos:start - 1])
        pos = start - 1
        if len(result) != new_start - 1:
            raise ValueError('new line position mismatch')
        consumed = produced = 0
        i += 1
        while i < len(lines) and not lines[i].startswith('@@ '):
            line = lines[i]
            if line[0] not in ' +-':
                raise ValueError('unsupported patch line')
            if line[0] in ' -':
                if pos >= len(original) or original[pos] != line[1:]:
                    raise ValueError('patch context mismatch')
                pos += 1
                consumed += 1
            if line[0] in ' +':
                result.append(line[1:])
                produced += 1
            i += 1
        if (consumed, produced) != (old_count, new_count):
            raise ValueError('patch line count mismatch')
    return ''.join(result + original[pos:])


def prepare(repo, output):
    repo, output = repo.resolve(), output.resolve()
    # Even an empty existing directory is refused. No shared source/out writes.
    if output.exists() or not output.is_relative_to(repo / 'build'):
        raise ValueError('output must be a fresh directory below repository build/')
    identity = json.loads((HERE / 'base_hashes.json').read_text())
    for group, root in [('base_sources', repo), ('assets', HERE)]:
        for name, expected in identity[group].items():
            if digest((root / name).read_bytes()) != expected:
                raise ValueError('source drift: ' + name)
    backend = (repo / 'src/main/scala/core/ooo/integration/IntegerBackend.scala').read_text()
    ledger = (repo / 'src/main/scala/core/ooo/retire/RenameRob.scala').read_text()
    storage = apply_exact(backend, (HERE / 'storage-backend.patch').read_text())
    query = apply_exact(ledger, (HERE / 'query-ledger.patch').read_text())
    outputs = {'storage/IntegerBackend.scala': storage,
               'query/IntegerBackend.scala': storage,
               'query/RenameRob.scala': query,
               'query/QueriedRecoveryAdmission.scala': (HERE / 'QueriedRecoveryAdmission.scala').read_text()}
    for name, content in outputs.items():
        if digest(content.encode()) != identity['expected_outputs'][name]:
            raise ValueError('generated source mismatch: ' + name)
    output.mkdir(parents=True)
    for name, content in outputs.items():
        path = output / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content.encode())
    (output / 'IDENTITY.json').write_text(json.dumps(identity, indent=2) + '\n')
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=HERE.parents[3])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.repo, args.out)
    print('PASS: exact-source storage/query overlays prepared; no compile or RTL emitted')


if __name__ == '__main__':
    main()
