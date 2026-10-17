#!/usr/bin/env python3
"""Shared aligned PMP bounds: exact source preflight, optional four bounded GSIM components."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_sources():
    production = (common.ROOT / 'src/main/scala/core/ooo/mmu/PhysicalMemoryProtection.scala').read_text()
    prefix = 'package soc.core.ooo\nimport chisel3._\nimport chisel3.util._\n\n'
    body = prefix + production[production.index('/** Parallel range'):]
    mutations = json.loads((common.HERE / 'config/pmp-shared-bound-mutants.json').read_text())
    assert len(mutations) == 6 and {m['mode'] for m in mutations} == set(range(1, 7))
    for mutation in mutations:
        assert body.count(mutation['old']) == 1, mutation['name'] + ' production anchor drift'
        expected = body.replace('class PmpChecker(', f"class PmpSharedBoundMutant{mutation['mode']}(")
        expected = expected.replace(mutation['old'], mutation['new'])
        source = common.ROOT / f"src/test/scala/ooo/PmpSharedBoundMutant{mutation['mode']}.scala"
        assert source.read_text() == expected and sha(source) == mutation['source_sha256'], \
            mutation['name'] + ' is not the declared source mutant'
    assert sha(common.ROOT / 'src/test/scala/ooo/R6PmpCheckerReference.scala') == \
        'b49960ca6555c2e005fcc24c3f3566f44f78b4841c5cdc5ed2af96284dffa03b'
    assert sha(common.HERE / 'harness/pmp_csr_oracle.h') == \
        '48c801c3ca0ede889342adf8dd4142c56fa77e8d644818d2ee535ca0b9f6d7b6'
    return mutations


def verify_negative(code, text, reason, reached=None):
    assert code != 0 and reason in text and 'NEGATIVE_CONTROL_ESCAPED' not in text, (code, text[-2000:])
    if reached is not None:
        assert reached in text, ('missing reached witness', reached)
    assert not any(marker in text for marker in
                   ('ERROR: AddressSanitizer', 'runtime error:', 'UndefinedBehaviorSanitizer'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('unsafe tag')
    mutations = verify_sources()
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_SOURCE_DERIVATION_PASS', 'models': 4,
                          'source_mutants': len(mutations), 'source_controls': 11,
                          'single_candidate_contract_controls': 4, 'full_cpu': False,
                          'physical_metrics': 'UNMEASURED'}))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    source_files = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + \
        sorted((common.ROOT / 'src/test/scala').rglob('*.scala')) + [Path(__file__), common.HERE / 'run.py',
        common.HERE / 'config/pmp-shared-bound-mutants.json',
        *[common.HERE / 'harness' / name for name in
          ('pmp_shared_bounds.cpp', 'pmp_shared_contract.cpp', 'pmp_csr_publication.cpp', 'pmp_csr_oracle.h')]]
    before = {str(path.relative_to(common.ROOT)): sha(path) for path in source_files}
    receipt = {'status': 'RUNNING', 'source_sha256': before, 'controls': [],
               'full_cpu': False, 'physical_metrics': 'UNMEASURED'}

    def negative(label, command, reason, reached=None):
        result = subprocess.run(list(map(str, command)), cwd=common.ROOT, capture_output=True,
                                text=True, timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = result.stdout + result.stderr
        log = out / (label + '.log')
        log.write_text(text)
        verify_negative(result.returncode, text, reason, reached)
        receipt['controls'].append({'label': label, 'argv': list(map(str, command)),
                                    'exit': result.returncode, 'log_sha256': sha(log)})

    try:
        gsim, cxx = common.setup(False)
        matrix = common.test(gsim, cxx, args.tag + '/matrix', 'ooo.PmpSharedBoundsGsimMain',
                             'PmpSharedBoundsGsim', 'pmp_shared_bounds.cpp', defines={})
        text = (matrix / 'test.log').read_text()
        assert 'PMP_SHARED_BOUNDS_PASS' in text and 'trials=61536' in text and 'oracle_checks=430752' in text
        for mode in ('natural', 'line'):
            names = [m['name'] for m in mutations if mode == 'natural' or m['mode'] != 6]
            # Unconditional-low mutant 6 is an identity for line lastByte=63; do not claim a line control.
            for name in names:
                flag = '--' + mode + '-' + name
                negative(flag[2:], [matrix / 'run', flag], 'SHARED_BOUND_BYTE_ORACLE', 'REACHED ' + flag)
        csr = common.test(gsim, cxx, args.tag + '/csr', 'ooo.PmpCsrPublicationGsimMain',
                          'PmpCsrPublicationGsim', 'pmp_csr_publication.cpp',
                          parameters=('registered', 'entries=16'), defines={'PMP_ENTRIES': 16})
        assert 'PMP CSR publication PASS entries=16' in (csr / 'test.log').read_text()
        negative('csr-observer', [csr / 'run', '--inject-mismatch'], 'PMP publication oracle mismatch')
        for mode in ('natural', 'line'):
            contract = common.test(gsim, cxx, args.tag + '/contract-' + mode,
                                   'ooo.PmpSharedBoundsContractMain', 'PmpSharedBoundsContract',
                                   'pmp_shared_contract.cpp', parameters=(mode,),
                                   defines={'LINE_MODE': int(mode == 'line')})
            assert 'PMP_SHARED_SINGLE_CONTRACT_PASS line=' + str(int(mode == 'line')) in \
                (contract / 'test.log').read_text()
            for flag in ('--size', '--alignment'):
                reason = 'aligned line PMP checker requires a 64-byte aligned 64-byte access'
                if mode == 'natural':
                    reason = ('shared PMP endpoint high bits differ' if flag == '--size' else
                              'natural PMP checker requires an aligned access of at most eight bytes')
                negative('contract-' + mode + flag, [contract / 'run', flag], reason,
                         'REACHED contract ' + mode + ' ' + flag)
        negative('constructor-domain', ['mill', '-i', 'IonSoC.test.runMain',
                 'ooo.PmpSharedBoundsConfigMain', 'bad'],
                 'shared PMP bounds require a naturally aligned access or aligned line')
        assert {str(path.relative_to(common.ROOT)): sha(path) for path in source_files} == before
        receipt.update(status='PASS_COMPONENTS_ONLY', artifacts={str(path.relative_to(out)): sha(path)
                       for path in out.rglob('*') if path.is_file()})
    except BaseException as error:
        receipt.update(status='FAIL', error=str(error))
        raise
    finally:
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
