#!/usr/bin/env python3
"""Verify current source, then project only named hashes to the recorded b1bb source.

This is a source-identity bridge, not a rerun or an equivalence proof. The
separately recorded compact OFF CHIRRTL comparison supplies the bounded
original-behavior correspondence; retained CPU evidence is never relabeled.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def need(value, message):
    if not value:
        raise RuntimeError(message)


def closure(root, scopes, scala=False):
    return {p.relative_to(root).as_posix(): sha(p)
            for folder in scopes for p in sorted((root / folder).rglob('*'))
            if p.is_file() and (not scala or p.suffix == '.scala')}


def load(root, binding):
    name = binding['path']
    need(name == 'simulator/gsim/home_future_lru/source-bridge.json', 'future source bridge path changed')
    path = root / name
    need(sha(path) == binding['sha256'], 'future source bridge bytes changed')
    value = json.loads(path.read_text())
    need(value['schema'] == 'valence-future-home-source-bridge-v1' and
         value['base_commit'] == 'b1bb5d863f7ad5b034f148b18968d19e46ace75b' and
         value['base_tree'] == 'ff415366e5d26976bcdcda59d93d91680d33d45e' and
         value['default52_cpu_rerun'] is False, 'future source bridge identity changed')
    for name, row in value['changed_sources'].items():
        relative = PurePosixPath(name)
        need(not relative.is_absolute() and '..' not in relative.parts and str(relative) == name,
             'unsafe future bridge source path')
        need((root / name).is_file() and not (root / name).is_symlink() and
             sha(root / name) == row['current_sha256'], 'future bridge source changed: ' + name)
    for label, recorded in value['closures'].items():
        actual = closure(root, recorded['scope'], label == 'scala')
        need(len(actual) == recorded['current_file_count'] and digest(actual) == recorded['current_sha256'],
             'complete current source closure changed: ' + label)
        old = project(actual, value)
        need(len(old) == recorded['base_file_count'] and digest(old) == recorded['base_sha256'],
             'complete b1bb source projection changed: ' + label)
    return value


def project(fingerprints, bridge):
    result = dict(fingerprints)
    for name, row in bridge['changed_sources'].items():
        if name not in result:
            continue
        need(result[name] == row['current_sha256'], 'source projection input changed: ' + name)
        if row['base_sha256'] is None:
            del result[name]
        else:
            result[name] = row['base_sha256']
    return result
