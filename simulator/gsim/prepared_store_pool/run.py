#!/usr/bin/env python3
"""Focused production-selector GSIM/SAT/mapping replay; no downloads or full regression."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from control_depth import inspect as inspect_control_depth

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    'src/main/scala/core/ooo/' + name + '.scala' for name in
    ('lsu/ResidentMemoryPreparationSelector', 'issue/CircularIssueSelector', 'lsu/PreparedStorePool',
     'integration/IntegerBackend', 'config/OooParams')
] + ['src/test/scala/ooo/PreparedStorePoolGsim.scala', 'simulator/gsim/harness/prepared_store_pool.cpp']
INPUTS = ['pair/PreparedStorePoolGsim.fir'] + [
    f'{variant}/{module}.sv' for variant in ('old', 'new')
    for module in ('CircularIssueSelector', 'ResidentMemoryPreparationSelector', 'PreparedStorePoolSelector')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def executable(value):
    resolved = shutil.which(value)
    if not resolved:
        raise ValueError('Executable not found: ' + value)
    # Preserve argv[0]: resolving clang++ to clang changes its C++ link mode.
    return os.path.abspath(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('gsim', 'yosys', 'sv2v', 'cxx', 'firtool'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--mill', default='mill')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--reuse-inputs', type=Path,
        help='Previous output containing receipt.json with matching source and input artifact hashes')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_hashes = {p: sha(ROOT / p) for p in SOURCES}
    receipt = {'schema': 'prepared-store-pool-replay-v1', 'status': 'RUNNING',
        'source_sha256': source_hashes, 'runner_sha256': sha(__file__),
        'analyzer_sha256': sha(Path(__file__).with_name('control_depth.py')),
        'physicalTiming': 'unverified', 'sequentialFormal': False,
        'formalObjective': 'io_equivalent == 1; arbitrary ROB16 inputs, headMask derived from head',
        'stateBitsAdded': 0, 'readPortsAdded': 0, 'latencyDelta': 0, 'mapping': {}}
    tools = {}

    def run(argv, log, expected=None, timeout=300):
        result = subprocess.run(list(map(str, argv)), cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, timeout=timeout)
        (out / log).write_bytes(result.stdout)
        receipt.setdefault('commands', []).append({'argv': list(map(str, argv)),
            'log': log, 'returncode': result.returncode})
        if expected is None:
            if result.returncode != 0:
                raise RuntimeError(f'Command failed ({result.returncode}): {log}')
        elif result.returncode == 0 or expected not in result.stdout.decode(errors='replace'):
            raise RuntimeError('Expected rejection missing: ' + log)
        return result.stdout

    def yosys(command, log, expected=None):
        return run([tools['yosys'], '-Q', '-T', '-p', command], log, expected)

    def verilog(path):
        return 'read_verilog "' + str(path).replace('"', '\\"') + '"; '

    try:
        tools = {name: executable(getattr(args, name)) for name in
            ('gsim', 'yosys', 'sv2v', 'cxx', 'firtool')}
        receipt['tools'] = {name: {'path': path, 'sha256': sha(path)} for name, path in tools.items()}
        for directory in ('pair', 'old', 'new'):
            (out / directory).mkdir()
        if args.reuse_inputs:
            previous = args.reuse_inputs.resolve()
            prior = json.loads((previous / 'receipt.json').read_text())
            if any(prior['source_sha256'].get(p) != h for p, h in source_hashes.items()):
                raise RuntimeError('Reused inputs are bound to different source hashes')
            for name in INPUTS:
                if sha(previous / name) != prior['artifacts'].get(name):
                    raise RuntimeError('Reused input artifact hash mismatch: ' + name)
                shutil.copyfile(previous / name, out / name)
            receipt['reuseInputs'] = {'path': str(previous), 'receipt_sha256': sha(previous / 'receipt.json')}
        else:
            mill = executable(args.mill)
            for kind, main_class, params in [
                ('pair', 'PreparedStorePoolGsimMain', []),
                ('old', 'PreparedStorePoolAreaMain', ['false']),
                ('new', 'PreparedStorePoolAreaMain', ['true'])]:
                run([mill, '-i', 'IonSoC.test.runMain', 'ooo.' + main_class, out / kind, *params],
                    kind + '/elaborate.log', timeout=600)
        receipt['input_sha256'] = {name: sha(out / name) for name in INPUTS}
        for kind, top, driver in [('pair', 'PreparedStorePoolGsim', 'prepared_store_pool')]:
            directory = out / kind
            run([tools['gsim'], '--threads=1', '--dir=' + str(directory), directory / (top + '.fir')],
                kind + '/generate.log')
            run([tools['cxx'], '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-I' + str(directory),
                *sorted(directory.glob(top + '[0-9]*.cpp')),
                ROOT / ('simulator/gsim/harness/' + driver + '.cpp'), '-ldl', '-o', directory / 'run'],
                kind + '/compile.log')
            print(run([directory / 'run'], kind + '/test.log').decode(), end='', flush=True)
        for kind, flag, message, log in [
            ('pair', '--inject-mismatch', 'prepared pool independent oracle mismatch', 'negative-oracle'),
            ('pair', '--invalid-issued', "accepted memory start must name the caller's exact live resident", 'negative-owner')]:
            run([out / kind / 'run', flag], f'{kind}/{log}.log', expected=message)
        run([tools['firtool'], out / INPUTS[0], '--disable-all-randomization', '--strip-debug-info',
             '--disable-layers=Verification', '--verilog', '-o', out / 'pair/design.sv'], 'pair/firtool.log')
        (out / 'pair/design.v').write_bytes(run([tools['sv2v'], '-D', 'SYNTHESIS',
            out / 'pair/design.sv'], 'pair/sv2v.log'))
        prepare = 'hierarchy -top PreparedStorePoolGsim; proc; flatten; opt; '
        proof = prepare + 'sat -verify -prove io_equivalent 1 -show-inputs'
        yosys(verilog(out / 'pair/design.v') + proof, 'pair/formal.log')
        design = (out / 'pair/design.v').read_text()
        equation = next(line for line in design.splitlines() if 'assign io_equivalent =' in line)
        match = re.search(r'(\w+) == (\w+)', equation)
        if not match:
            raise RuntimeError('Mutation anchor missing')
        mutated = equation.replace(match[0], '(' + match[1] + " ^ 27'd1) == " + match[2], 1)
        (out / 'pair/design-mutated.v').write_text(design.replace(equation, mutated, 1))
        yosys(verilog(out / 'pair/design-mutated.v') + proof,
            'pair/formal-mutated.log', 'proof did fail')
        yosys(verilog(out / 'pair/design.v') + prepare + 'sat -verify -prove io_equivalent 0 -show-inputs',
            'pair/formal-negative.log', 'proof did fail')
        for mode, extra in [('default', ''), ('lut6', ' -nowidelut')]:
            receipt['mapping'][mode] = {}
            for variant in ('old', 'new'):
                directory = out / variant
                (directory / 'design.v').write_bytes(run([tools['sv2v'], '-D', 'SYNTHESIS',
                    directory / 'CircularIssueSelector.sv', directory / 'ResidentMemoryPreparationSelector.sv',
                    directory / 'PreparedStorePoolSelector.sv'],
                    variant + '/sv2v.log'))
                log = f'{variant}/mapping-xcup-{mode}.log'
                mapped = directory / f'mapped-xcup-{mode}.json'
                yosys(verilog(directory / 'design.v') + 'synth_xilinx -family xcup '
                    '-top PreparedStorePoolSelector -flatten -noiopad -noclkbuf' + extra +
                    '; stat; ltp -noff; write_json "' + str(mapped) + '"', log)
                cells = collections.Counter(c['type'] for c in json.loads(mapped.read_text())[
                    'modules']['PreparedStorePoolSelector']['cells'].values())
                cells.pop('$scopeinfo', None)
                control = inspect_control_depth(json.loads(mapped.read_text())['modules']['PreparedStorePoolSelector'])
                receipt['mapping'][mode][variant] = {'family': 'xcup', 'cells': dict(cells), 'control': control,
                    'lutCount': sum(n for t, n in cells.items() if t.startswith('LUT')),
                    'longestCellPath': int(re.search(r'Longest topological path.*length=(\d+)',
                        (out / log).read_text())[1])}
        if (any(sha(ROOT / p) != h for p, h in source_hashes.items()) or sha(__file__) != receipt['runner_sha256'] or
                sha(Path(__file__).with_name('control_depth.py')) != receipt['analyzer_sha256']):
            raise RuntimeError('Source changed during replay')
        if any(sha(out / p) != h for p, h in receipt['input_sha256'].items()):
            raise RuntimeError('Input changed during replay')
        receipt['status'] = 'PASS_PREPARED_STORE_POOL_END_TO_END'
        print(receipt['status'], flush=True)
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        receipt['artifacts'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
