#!/usr/bin/env python3
"""Verify complete authored fixtures without compiling or running a DUT."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST_SHA256 = "588a89a538435eb8623e75c86de598ac20fcb1b6c31b0f4880d37ba2ca1d9637"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate():
    raw = (HERE / 'fixture-manifest.json').read_bytes()
    if digest(raw) != MANIFEST_SHA256:
        raise RuntimeError('fixture manifest changed')
    manifest = json.loads(raw)
    for root, field in ((HERE, 'fixture_files'), (ROOT, 'shared_source_sha256')):
        for name, expected in manifest[field].items():
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or digest((root / path).read_bytes()) != expected:
                raise RuntimeError('fixture source changed: ' + name)
    host = json.loads((HERE / 'posted_join_observation/host-manifest.json').read_bytes())
    prefix = HERE / 'posted_join_observation'
    actual = {p.relative_to(prefix / 'host').as_posix() for p in (prefix / 'host').rglob('*') if p.is_file()}
    expected = {n.removeprefix('host/') for n in host['files'] if n.startswith('host/')}
    if actual != expected or len(actual) != 18:
        raise RuntimeError('complete corrected host inventory differs')
    for name, value in host['files'].items():
        if digest((prefix / name).read_bytes()) != value:
            raise RuntimeError('corrected host or original COPY guest changed')
    return manifest


def authored_guest_check():
    spec = importlib.util.spec_from_file_location('directed_guest_author', HERE / 'directed/prepare_guest.py')
    author = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(author)
    with tempfile.TemporaryDirectory(prefix='young-seal-authored-') as temporary:
        author.OUT = Path(temporary)
        with contextlib.redirect_stdout(io.StringIO()):
            author.main()
        for name in ('guest.bin', 'guest-manifest.json', 'guest_inputs.h'):
            if (author.OUT / name).read_bytes() != (HERE / 'directed' / name).read_bytes():
                raise RuntimeError('independently authored guest output differs: ' + name)


def negative_controls():
    original = Path.read_bytes
    checked = []
    for name in ('fixture-manifest.json', 'posted_join_observation/host/posted_join_observation.h',
                 'posted_join_observation/host/tagged_board_oracle.h',
                 'posted_join_observation/guest/guest.bin', 'directed/guest_inputs.h'):
        target = HERE / name
        def changed(path):
            raw = original(path)
            return raw + b'changed' if path == target else raw
        with mock.patch.object(Path, 'read_bytes', changed):
            try:
                validate()
            except RuntimeError:
                checked.append(name)
            else:
                raise AssertionError('negative fixture mutation accepted: ' + name)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    manifest = validate()
    authored_guest_check()
    controls = negative_controls() if args.self_test else []
    print(json.dumps({'status': 'PASS_EXACT_FIXTURE_CLOSURE', 'host_files': 18,
                      'directed_inputs': 7, 'authored_guest_outputs_equal': 3,
                      'negative_controls': controls, 'cpu_simulations': 0}, indent=2))


if __name__ == '__main__':
    main()
