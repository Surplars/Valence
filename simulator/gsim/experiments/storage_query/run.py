#!/usr/bin/env python3
"""Compile isolated overlay classes, then export ordinary matched CPU tiles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlparse

from prepare import prepare


def read_classpath(path):
    value = path.read_text().strip()
    if not value or '\n' in value:
        raise ValueError('classpath file must contain one native path-separated line')
    for entry in value.split(os.pathsep):
        if not entry or not Path(entry).is_absolute() or not Path(entry).exists():
            raise ValueError('classpath entry must be an existing absolute path: ' + entry)
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--runtime-classpath-file', required=True, type=Path)
    p.add_argument('--compiler-classpath-file', required=True, type=Path)
    p.add_argument('--chisel-plugin', required=True, type=Path)
    p.add_argument('--java', default='java')
    p.add_argument('--rob', type=int, choices=[16, 32], default=32)
    args = p.parse_args()
    runtime = read_classpath(args.runtime_classpath_file)
    compiler = read_classpath(args.compiler_classpath_file)
    plugin = args.chisel_plugin.resolve()
    if not plugin.is_file():
        raise ValueError('missing Chisel compiler plugin')
    root = args.out.resolve()
    prepare(args.repo, root)
    commands = []

    def execute(argv):
        index = len(commands)
        commands.append(argv)
        (root / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        with (root / f'{index}.stdout').open('wb') as stdout, (root / f'{index}.stderr').open('wb') as stderr:
            result = subprocess.run(argv, cwd=args.repo.resolve(), stdout=stdout, stderr=stderr)
        (root / f'{index}.exit.json').write_text(json.dumps({'returncode': result.returncode}) + '\n')
        result.check_returncode()

    for role in ['storage', 'query']:
        classes = root / role / 'classes'
        classes.mkdir()
        sources = sorted(str(x) for x in (root / role).glob('*.scala'))
        execute([args.java, '-cp', compiler, 'scala.tools.nsc.Main', '-classpath', runtime,
                 '-Xplugin:' + str(plugin), '-language:reflectiveCalls', '-deprecation', '-feature',
                 '-Xcheckinit', '-Ymacro-annotations', '-d', str(classes)] + sources)
        effective = str(classes) + os.pathsep + runtime
        (root / role / 'classpath.txt').write_text(effective + '\n')
        loads = root / role / 'class-load.log'
        execute([args.java, '-Xlog:class+load=info:file=' + str(loads),
                 '-cp', effective, 'platform.CommonA1CapacityTileMain',
                 str(root / role / 'rtl'), str(args.rob), str(48 if args.rob == 16 else 64)])
        normal = args.repo.resolve() / 'out/IonSoC/compile.dest/classes'
        expected = {'IntegerBackend': classes, 'ParallelRecoveryAdmission': normal,
                    'RenameRob': classes if role == 'query' else normal}
        if role == 'query':
            expected['QueriedRecoveryAdmission'] = classes
        origins = {}
        for line in loads.read_text().splitlines():
            for name in expected:
                marker = 'soc.core.ooo.' + name + ' source: '
                if marker in line:
                    source = line.split(marker, 1)[1].strip()
                    origins[name] = Path(unquote(urlparse(source).path)).resolve()
        if origins != {k: v.resolve() for k, v in expected.items()}:
            raise ValueError('unexpected loaded class origins: ' + repr(origins))
        (root / role / 'CLASS_ORIGINS.json').write_text(
            json.dumps({k: str(v) for k, v in origins.items()}, indent=2) + '\n')
    dirs = [root / role / 'rtl' for role in ['storage', 'query']]
    files = [{x.name: hashlib.sha256(x.read_bytes()).hexdigest() for x in d.glob('*.sv')} for d in dirs]
    if not files[0] or files[0].keys() != files[1].keys():
        raise ValueError('export module file sets differ')
    changed = sorted(n for n in files[0] if files[0][n] != files[1][n])
    if changed != ['ParallelRecoveryAdmission.sv', 'RenameRob.sv']:
        raise ValueError('unexpected RTL changes: ' + repr(changed))
    for name in ['cpu-identity.json', 'effective-config.json', 'effective-parameters.json']:
        if (dirs[0] / name).read_bytes() != (dirs[1] / name).read_bytes():
            raise ValueError('configuration differs: ' + name)
    (root / 'EXPORT_REVIEW.json').write_text(json.dumps({
        'status': 'PASS_MATCHED_EXPORT_ONLY', 'changed_sv': changed,
        'sv_sha256': dict(zip(['storage', 'query'], files)),
        'hardware_simulation_run': False, 'physical_timing_verified': False}, indent=2) + '\n')


if __name__ == '__main__':
    main()
