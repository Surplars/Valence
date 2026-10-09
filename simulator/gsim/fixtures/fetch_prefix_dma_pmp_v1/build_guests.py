#!/usr/bin/env python3
"""Fresh portable builds of the two unchanged independent guests; no simulator."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
import binding as b


def build(out, paths, versions):
    out = out.resolve()
    b.require(out.is_relative_to(b.HERE) and not out.exists(), 'fresh output inside this isolated fixture required')
    out.mkdir(parents=True)
    frozen = {str(path): b.sha(path) for path in [Path(sys.executable), *paths.values(),
              b.HERE / 'build_guests.py', b.HERE / 'binding.py', b.HERE / 'source_lock.json']}
    state = {'schema': b.GUEST_SCHEMA, 'status': 'RUNNING', 'profile': b.GUEST_PROFILE,
        'builder_sha256': b.sha(__file__), 'binding_sha256': b.sha(b.__file__),
        'toolchain': versions, 'gsim_lock': b.common.LOCK, 'cases': {},
        'limits': ['Guest assembly only. No model, functional, NEMU, performance or board claim.']}
    def save():
        (out / 'manifest.json').write_text(json.dumps(state, indent=2) + '\n')
    def guard():
        b.require(b.exact(b.preflight_sources(), b.LOCK), 'source lock changed')
        for path, digest in frozen.items():
            b.require(b.sha(path) == digest, 'builder/tool changed: ' + path)
        for case, record in state['cases'].items():
            for name, digest in record['sources'].items():
                b.require(b.sha(b.contained(out, case + '/sources/' + name)) == digest, 'copied guest changed')
            for name, digest in record['artifacts'].items():
                b.require(b.sha(b.contained(out, case + '/' + name)) == digest, 'guest artifact changed')
            for step in record['steps'].values():
                b.require(b.sha(b.contained(out, case + '/' + step['log'])) == step['log_sha256'], 'guest log changed')
    save()
    try:
        for case in b.CASES:
            root = out / case
            (root / 'sources').mkdir(parents=True)
            sources = {}
            for name, original in b.GUEST_SOURCES[case].items():
                shutil.copyfile(b.ROOT / original, root / 'sources' / name)
                sources[name] = b.sha(b.ROOT / original)
            record = {'sources': sources, 'steps': {}, 'artifacts': {}}
            state['cases'][case] = record
            for name, command in b.guest_commands(case, paths).items():
                guard()
                print('+', ' '.join(command), flush=True)
                log = root / (name + '.log')
                with log.open('x') as stream:
                    code = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT, timeout=60,
                        env={**os.environ, 'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': '0', 'PYTHONDONTWRITEBYTECODE': '1'}).returncode
                record['steps'][name] = {'command': [Path(command[0]).name, *command[1:]], 'exit': code,
                                         'log': log.name, 'log_sha256': b.sha(log)}
                save()
                b.require(code == 0, 'guest build failed: ' + case + '/' + name)
                b.clean_log(log.read_text())
                product = {'assemble': 'guest.o', 'link': 'guest.elf', 'binary': 'guest.bin'}.get(name)
                if product:
                    record['artifacts'][product] = b.sha(root / product)
                else:
                    symbols = b.guest_symbols(case, log.read_text())
                    filename, text = b.symbol_file(case, symbols)
                    (root / filename).write_text(text)
                    record['symbols'] = symbols
                    record['artifacts'][filename] = b.sha(root / filename)
                save()
                guard()
        state['status'] = b.GUEST_PASS
        save()
        b.guest_audit(out, paths, versions)
    except BaseException as error:
        state['status'] = 'FAIL'
        state['error'] = str(error)
        save()
        raise
    print(b.GUEST_PASS, out / 'manifest.json', flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    _, _, paths, versions = b.toolchain()
    build(args.out, paths, versions)


if __name__ == '__main__':
    main()
