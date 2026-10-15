#!/usr/bin/env python3
"""Stage source only. Never compile, generate guests/bindings/models, or run a DUT."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(root, name):
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError('repository-relative path required: ' + name)
    return path


def initialize(text):
    before = '#include <cstdint>\n'
    anchor = '        observer = initialObserver;'
    if text.count(before) != 1 or text.count(anchor) != 1:
        raise ValueError('initialization anchors changed')
    body = '''        // GSIM uses a uint32_t element count as a byte count in its constructor.
        // Restore deterministic zero initialization without changing generated code.
        static_assert(std::is_trivially_copyable_v<SBoardSocGsim>);
        std::memset(dut.get(), 0, sizeof(*dut));
        dut->cycles = 0;
        dut->LOG_START = 1;
        dut->LOG_END = 0;
        dut->activateAll();
'''
    return text.replace(before, before + '#include <cstring>\n#include <type_traits>\n').replace(anchor, body + anchor)


def verify(root):
    manifest = json.loads((HERE / 'inputs.json').read_text())
    sources = []
    for record in [*manifest['host_inputs'].values(), *manifest['held_inputs'].values(), *manifest['matched_repository_inputs'].values()]:
        sources.append((resolve(root, record['source']), record['sha256']))
    for name, digest in manifest['component_inputs'].items():
        sources.append((HERE / name, digest))
    for name, digest in manifest['repository_generator_identities'].items():
        sources.append((resolve(root, name), digest))
    sources.append((root / 'simulator/gsim/harness/board_boot.cpp', manifest['initialization']['common_after']))
    for path, digest in sources:
        if sha(path) != digest:
            raise ValueError('source identity mismatch: ' + str(path))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--repository', type=Path, default=HERE.parents[2])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.repository.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(HERE):
        raise ValueError('fresh output outside package source required')
    manifest = verify(root)
    output.mkdir(parents=True)
    groups = {'host': manifest['host_inputs'], 'held': manifest['held_inputs'],
              'auxiliary': {name: record for name, record in manifest['matched_repository_inputs'].items()
                            if name.startswith(('nemu/', 'pmp/'))},
              'resolvers': {name: record for name, record in manifest['matched_repository_inputs'].items()
                            if name.startswith('held/binding_memory')}}
    for group, records in groups.items():
        for name, record in records.items():
            source, target = resolve(root, record['source']), resolve(output / group, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if record.get('transform'):
                target.write_text(initialize(source.read_text()))
            else:
                shutil.copyfile(source, target)
            if sha(target) != record.get('staged_sha256', record['sha256']):
                raise ValueError('staged identity mismatch: ' + name)
    for name in manifest['component_inputs']:
        target = output / 'component' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / name, target)
    # A single host root owns the quoted harness/board_boot.cpp include.
    # No second include tree, generated guest or old binding is copied.
    receipt = {'status': 'SOURCE_ONLY_STAGED_NOT_RUNTIME_QUALIFIED',
               'manifest_sha256': sha(HERE / 'inputs.json'),
               'files': {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()},
               'generated_guests': False, 'generated_bindings': False, 'models_executed': False,
               'fullcpu_runtime_blockers': manifest['unresolved_qualified_inputs']}
    (output / 'staging.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(receipt['status'])


if __name__ == '__main__':
    main()
