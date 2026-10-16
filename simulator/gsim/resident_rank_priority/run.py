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

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    'src/main/scala/core/ooo/' + name + '.scala' for name in
    ('ResidentMemoryPreparationSelector', 'CircularIssueSelector', 'RegisteredRobHeadMask',
     'IntegerBackend', 'OooParams')
] + [
    'src/test/scala/ooo/ResidentLateExclusionGsim.scala',
    'src/test/scala/ooo/RegisteredHeadSelectionGsim.scala',
    'simulator/gsim/harness/resident_late_exclusion.cpp',
    'simulator/gsim/harness/registered_head_selection.cpp',
]
INPUTS = ['selector/ResidentLateExclusionGsim.fir', 'head/RegisteredHeadSelectionGsim.fir'] + [
    f'{variant}/{module}.sv' for variant in ('old', 'new')
    for module in ('CircularIssueSelector', 'ResidentMemoryPreparationSelector')]


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
    receipt = {'schema': 'resident-rank-priority-replay-v1', 'status': 'RUNNING',
        'source_sha256': source_hashes, 'runner_sha256': sha(__file__),
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
        for directory in ('selector', 'head', 'old', 'new'):
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
                ('selector', 'ResidentLateExclusionGsimMain', []),
                ('head', 'RegisteredHeadSelectionGsimMain', []),
                ('old', 'ResidentPriorityAreaMain', ['false']),
                ('new', 'ResidentPriorityAreaMain', ['true'])]:
                run([mill, '-i', 'IonSoC.test.runMain', 'ooo.' + main_class, out / kind, *params],
                    kind + '/elaborate.log', timeout=600)
        receipt['input_sha256'] = {name: sha(out / name) for name in INPUTS}
        for kind, top, driver in [('selector', 'ResidentLateExclusionGsim', 'resident_late_exclusion'),
                                  ('head', 'RegisteredHeadSelectionGsim', 'registered_head_selection')]:
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
            ('selector', '--inject-mismatch', 'resident late exclusion independent oracle mismatch', 'negative-oracle'),
            ('selector', '--invalid-issued', "accepted memory start must name the caller's exact live resident", 'negative-owner'),
            ('head', '--inject-mismatch', 'registered head independent oracle mismatch', 'negative-oracle')]:
            run([out / kind / 'run', flag], f'{kind}/{log}.log', expected=message)
        run([tools['firtool'], out / INPUTS[0], '--disable-all-randomization', '--strip-debug-info',
             '--disable-layers=Verification', '--verilog', '-o', out / 'selector/design.sv'], 'selector/firtool.log')
        (out / 'selector/design.v').write_bytes(run([tools['sv2v'], '-D', 'SYNTHESIS',
            out / 'selector/design.sv'], 'selector/sv2v.log'))
        prepare = 'hierarchy -top ResidentLateExclusionGsim; proc; flatten; opt; '
        proof = prepare + 'sat -verify -prove io_equivalent 1 -show-inputs'
        yosys(verilog(out / 'selector/design.v') + proof, 'selector/formal.log')
        design = (out / 'selector/design.v').read_text()
        original = '(candidate_1 == candidate_2)'
        if design.count(original) != 1:
            raise RuntimeError('Mutation anchor missing or ambiguous')
        (out / 'selector/design-mutated.v').write_text(
            design.replace(original, "((candidate_1 ^ 27'd1) == candidate_2)"))
        yosys(verilog(out / 'selector/design-mutated.v') + proof,
            'selector/formal-mutated.log', 'proof did fail')
        yosys(verilog(out / 'selector/design.v') + prepare + 'sat -verify -prove io_equivalent 0 -show-inputs',
            'selector/formal-negative.log', 'proof did fail')
        for mode, extra in [('default', ''), ('lut6', ' -nowidelut')]:
            receipt['mapping'][mode] = {}
            for variant in ('old', 'new'):
                directory = out / variant
                (directory / 'design.v').write_bytes(run([tools['sv2v'], '-D', 'SYNTHESIS',
                    directory / 'CircularIssueSelector.sv', directory / 'ResidentMemoryPreparationSelector.sv'],
                    variant + '/sv2v.log'))
                log = f'{variant}/mapping-xcup-{mode}.log'
                mapped = directory / f'mapped-xcup-{mode}.json'
                yosys(verilog(directory / 'design.v') + 'synth_xilinx -family xcup '
                    '-top ResidentMemoryPreparationSelector -flatten -noiopad -noclkbuf' + extra +
                    '; stat; ltp -noff; write_json "' + str(mapped) + '"', log)
                cells = collections.Counter(c['type'] for c in json.loads(mapped.read_text())[
                    'modules']['ResidentMemoryPreparationSelector']['cells'].values())
                cells.pop('$scopeinfo', None)
                receipt['mapping'][mode][variant] = {'family': 'xcup', 'cells': dict(cells),
                    'lutCount': sum(n for t, n in cells.items() if t.startswith('LUT')),
                    'longestCellPath': int(re.search(r'Longest topological path.*length=(\d+)',
                        (out / log).read_text())[1])}
        if any(sha(ROOT / p) != h for p, h in source_hashes.items()) or sha(__file__) != receipt['runner_sha256']:
            raise RuntimeError('Source changed during replay')
        if any(sha(out / p) != h for p, h in receipt['input_sha256'].items()):
            raise RuntimeError('Input changed during replay')
        receipt['status'] = 'PASS_RESIDENT_RANK_PRIORITY_END_TO_END'
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
