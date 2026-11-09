#!/usr/bin/env python3
"""Isolated actual-RTL full-input recovery-query proofs and boundary negative control."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse

from prepare import HERE, digest
from run import read_classpath


def sha(path):
    return digest(Path(path).read_bytes())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--runtime-classpath-file', required=True, type=Path)
    p.add_argument('--compiler-classpath-file', required=True, type=Path)
    p.add_argument('--chisel-plugin', required=True, type=Path)
    p.add_argument('--query-classes', required=True, type=Path)
    p.add_argument('--java', default='java')
    p.add_argument('--sv2v', required=True)
    p.add_argument('--yosys', required=True)
    p.add_argument('--timeout-seconds', type=float, help='optional per-command timeout; default: no automatic kill')
    args = p.parse_args()
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        p.error('--timeout-seconds must be positive')
    repo, root, query = args.repo.resolve(), args.out.resolve(), args.query_classes.resolve()
    if root.exists() or not root.is_relative_to(repo / 'build'):
        p.error('output must be fresh and below repository build/')
    runtime = read_classpath(args.runtime_classpath_file)
    compiler = read_classpath(args.compiler_classpath_file)
    plugin = args.chisel_plugin.resolve()
    if not plugin.is_file() or not query.is_dir():
        p.error('plugin/query classes missing')
    expected = json.loads((HERE / 'base_hashes.json').read_text())
    sources = {}
    for name, wanted in expected['base_sources'].items():
        if sha(repo / name) != wanted:
            raise ValueError('production source drift: ' + name)
        sources[name] = wanted
    for name, wanted in expected['expected_outputs'].items():
        if name.startswith('query/'):
            path = query.parent / Path(name).name
            if sha(path) != wanted:
                raise ValueError('query overlay source drift: ' + str(path))
            sources[name] = wanted
    # Accept only a completed public run.py export, not an arbitrary class folder.
    export_root = query.parent.parent
    export_review = export_root / 'EXPORT_REVIEW.json'
    origins_file = query.parent / 'CLASS_ORIGINS.json'
    if query.name != 'classes' or query.parent.name != 'query':
        raise ValueError('query classes must be the public runner query/classes output')
    export_identity = json.loads(export_review.read_text())
    if export_identity['status'] != 'PASS_MATCHED_EXPORT_ONLY':
        raise ValueError('query export did not pass its matched-export gate')
    actual_sv = {x.name: sha(x) for x in (query.parent / 'rtl').glob('*.sv')}
    if actual_sv != export_identity['sv_sha256']['query']:
        raise ValueError('query export RTL manifest drift')
    previous_origins = json.loads(origins_file.read_text())
    for cls in ['IntegerBackend', 'RenameRob', 'QueriedRecoveryAdmission']:
        if Path(previous_origins[cls]).resolve() != query:
            raise ValueError('query export class provenance mismatch: ' + cls)
    commands = json.loads((export_root / 'commands.json').read_text())
    compile_command = commands[2]
    for name in ['IntegerBackend.scala', 'RenameRob.scala', 'QueriedRecoveryAdmission.scala']:
        if str(query.parent / name) not in compile_command:
            raise ValueError('query compile provenance missing source: ' + name)
    provenance = [export_review, origins_file, export_root / 'commands.json']
    for index in range(4):
        receipt = export_root / (str(index) + '.exit.json')
        if json.loads(receipt.read_text())['returncode'] != 0:
            raise ValueError('query export command failed')
        provenance.append(receipt)
    fixture = HERE / 'RecoveryQueryFormalMain.scala'
    checker = HERE / 'check_counterexample.py'
    for path in [fixture, checker, Path(__file__).resolve()]:
        sources[path.name] = sha(path)
    tools = {}
    for name in ['java', 'sv2v', 'yosys']:
        resolved = shutil.which(getattr(args, name))
        if not resolved:
            raise ValueError('missing tool: ' + name)
        tools[name] = {'path': str(Path(resolved).resolve()), 'sha256': sha(resolved)}
    root.mkdir(parents=True)
    classes = root / 'classes'
    classes.mkdir()
    classfiles = {str(x.relative_to(query)): sha(x) for x in sorted(query.rglob('*.class'))}
    if not classfiles:
        raise ValueError('query class directory is empty')
    binding = {'query_export_provenance_sha256': {str(x): sha(x) for x in provenance},
               'source_sha256': sources, 'query_classes': classfiles, 'tools': tools,
               'plugin_sha256': sha(plugin), 'runtime_classpath': runtime,
               'compiler_classpath': compiler, 'timeout_seconds': args.timeout_seconds,
               'normal_helper_classes': {str(x.relative_to(repo)): sha(x) for x in
                   (repo / 'out/IonSoC/compile.dest/classes/soc/core/ooo').glob('ParallelRecoveryAdmission*.class')}}
    if not binding['normal_helper_classes']:
        raise ValueError('normal helper classes missing')
    binding['dependency_files_sha256'] = {x: sha(x) for x in sorted(set(
        (runtime + os.pathsep + compiler).split(os.pathsep))) if Path(x).is_file()}
    (root / 'BINDING.json').write_text(json.dumps(binding, indent=2) + '\n')
    result = {'status': 'RUNNING', 'proofs': {}, 'scope': 'component combinational full-input only; not CPU sequential equivalence'}

    def save():
        (root / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')

    def execute(name, argv, allow_nonzero=False):
        started = time.monotonic()
        receipt = {'argv': list(map(str, argv)), 'status': 'RUNNING'}
        (root / (name + '.started.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        with (root / (name + '.stdout')).open('wb') as stdout, (root / (name + '.stderr')).open('wb') as stderr:
            try:
                command = subprocess.run(receipt['argv'], cwd=repo, stdout=stdout, stderr=stderr,
                                         timeout=args.timeout_seconds)
                receipt.update(status='COMPLETE', exit=command.returncode)
            except subprocess.TimeoutExpired:
                receipt.update(status='UNKNOWN_TIMEOUT', exit=None)
        receipt.update(seconds=time.monotonic() - started,
                       stdout_sha256=sha(root / (name + '.stdout')),
                       stderr_sha256=sha(root / (name + '.stderr')))
        (root / (name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        if receipt['status'] == 'UNKNOWN_TIMEOUT':
            result['status'] = 'UNKNOWN_TIMEOUT'
            save()
            raise RuntimeError('UNKNOWN_TIMEOUT: ' + name)
        if receipt['exit'] != 0 and not allow_nonzero:
            raise RuntimeError('command failed: ' + name)
        return receipt

    save()
    try:
        for tool, flag in [('java', '-version'), ('sv2v', '--version'), ('yosys', '-V')]:
            execute('version-' + tool, [tools[tool]['path'], flag])
        cp = str(query) + os.pathsep + runtime
        execute('compile', [tools['java']['path'], '-cp', compiler, 'scala.tools.nsc.Main',
                            '-classpath', cp, '-Xplugin:' + str(plugin), '-language:reflectiveCalls',
                            '-deprecation', '-feature', '-Xcheckinit', '-Ymacro-annotations',
                            '-d', classes, fixture])
        for rows, mode in [(16, 'normal'), (32, 'normal'), (16, 'negative')]:
            name = f'{rows}-{mode}'
            dest = root / name
            dest.mkdir()
            loadlog = dest / 'class-load.log'
            execute(name + '-emit', [tools['java']['path'], '-Xlog:class+load=info:file=' + str(loadlog),
                    '-cp', str(classes) + os.pathsep + cp, 'soc.core.ooo.RecoveryQueryFormalMain', dest, rows, mode])
            wanted = {'ParallelRecoveryAdmission': repo / 'out/IonSoC/compile.dest/classes',
                      'QueriedRecoveryAdmission': query, 'RecoveryQueryFormalMain': classes,
                      'RecoveryQueryFormal': classes}
            if mode == 'negative':
                wanted['BoundaryLeQueriedRecoveryAdmission'] = classes
            origins = {}
            for line in loadlog.read_text().splitlines():
                for cls in wanted:
                    marker = 'soc.core.ooo.' + cls + ' source: '
                    if marker in line:
                        origins[cls] = Path(unquote(urlparse(line.split(marker, 1)[1].strip()).path)).resolve()
            if origins != wanted:
                raise ValueError('actual class origin mismatch: ' + repr(origins))
            (dest / 'CLASS_ORIGINS.json').write_text(json.dumps({k: str(v) for k, v in origins.items()}, indent=2) + '\n')
            sv = sorted(dest.glob('*.sv'))
            if not sv:
                raise ValueError('no generated SV')
            execute(name + '-sv2v', [tools['sv2v']['path'], *sv])
            verilog = dest / 'combined.v'
            verilog.write_bytes((root / (name + '-sv2v.stdout')).read_bytes())
            # Quoted Yosys paths permit spaces; reject embedded quotes/newlines.
            if any(c in str(dest) for c in ['"', '\n', '\r']):
                raise ValueError('unsupported Yosys path characters')
            script = (f'read_verilog "{verilog}"\nhierarchy -top RecoveryQueryFormal\n'
                      'proc\nflatten\nopt\ncheck\n'
                      f'sat -verify -prove io_equal 1 -show-inputs -show-outputs -dump_json "{dest / "counterexample.json"}"\n')
            (dest / 'prove.ys').write_text(script)
            receipt = execute(name + '-sat', [tools['yosys']['path'], '-s', dest / 'prove.ys'], allow_nonzero=True)
            log = (root / (name + '-sat.stdout')).read_text()
            proof = ('PASS' if receipt['exit'] == 0 and 'SUCCESS!' in log and not (dest / 'counterexample.json').exists() else
                     'COUNTEREXAMPLE' if receipt['exit'] == 1 and 'FAIL!' in log and (dest / 'counterexample.json').exists() else 'UNKNOWN')
            result['proofs'][name] = {'status': proof, 'exit': receipt['exit'], 'sv_sha256': {x.name: sha(x) for x in sv}}
            save()
            if proof != ('PASS' if mode == 'normal' else 'COUNTEREXAMPLE'):
                raise RuntimeError('unexpected proof outcome: ' + name + ' ' + proof)
            if mode == 'negative':
                execute('negative-review', [sys.executable, checker, '--counterexample', dest / 'counterexample.json',
                                            '--out', dest / 'COUNTEREXAMPLE_REVIEW.json'])
        # Check classes and sources did not change while proofs ran.
        if classfiles != {str(x.relative_to(query)): sha(x) for x in sorted(query.rglob('*.class'))}:
            raise ValueError('query classes changed during run')
        for name, wanted_hash in expected['base_sources'].items():
            if sha(repo / name) != wanted_hash:
                raise ValueError('production source changed during run: ' + name)
        for name, wanted_hash in expected['expected_outputs'].items():
            if name.startswith('query/') and sha(query.parent / Path(name).name) != wanted_hash:
                raise ValueError('query source changed during run: ' + name)
        for path in [fixture, checker, Path(__file__).resolve()]:
            if sha(path) != sources[path.name]:
                raise ValueError('proof source changed during run: ' + path.name)
        for name, wanted_hash in binding['normal_helper_classes'].items():
            if sha(repo / name) != wanted_hash:
                raise ValueError('normal helper class changed during run: ' + name)
        result['status'] = 'PASS_TWO_FULL_INPUT_PROOFS_AND_PRECISE_NEGATIVE'
        save()
    except Exception as error:
        if result['status'] != 'UNKNOWN_TIMEOUT':
            result['status'] = 'FAILED' if all(x['status'] != 'UNKNOWN' for x in result['proofs'].values()) else 'UNKNOWN'
        result['error'] = str(error)
        save()
        raise


if __name__ == '__main__':
    main()
