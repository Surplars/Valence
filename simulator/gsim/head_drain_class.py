#!/usr/bin/env python3
"""Independent head-drain source gate using the official serial 1 MiB GSIM split flow."""
import json
import re
import sys
from pathlib import Path
import pending_store_proof_integration as run

run.MODELS = {
    'decode': ('HeadDrainDecodeGsim', 'headdrain_decode', [], [], 'GSIM_HEAD_DRAIN_DECODE: PASS'),
    'pair': ('HeadDrainBackendPairGsim', 'headdrain_pair', [], [], 'HEAD_DRAIN_BACKEND_PAIR_PASS'),
}
run.DEFAULT_MODELS = 'decode,pair'
run.CONFIG_SUITES = ['ooo.HeadDrainClassSpec']
run.HOST_FILES.update({
    'headdrain_decode': 'simulator/gsim/harness/head_drain_decode.cpp',
    'headdrain_pair': 'simulator/gsim/harness/head_drain_backend_pair.cpp',
})
mutation_names = [
    'pmp-disabled', 'pmp-cfg2-8', 'pmp-reserved-funct3', 'pmp-8-upper-bound', 'pmp-16-upper-bound',
    'satp-zero-csrrw', 'satp-zero-csrrwi', 'satp-zero-csrrs', 'satp-reserved-funct3', 'vm-disabled',
    'mret', 'sret', 'sfence-operands', 'sfence-malformed-rd', 'sfence-malformed-funct3',
    'fence-i-broad', 'fence-other-funct3', 'fp-nonmatch', 'compressed-expanded',
    'compressed-original-poison', 'uncompressed-expanded-poison',
]
run.EXTRA_NEGATIVES = {
    'headdrain_decode': [('--mutate=' + name, 'head-drain-class-mismatch') for name in mutation_names],
    'headdrain_pair': [('--mutate-observed-class', 'HEAD_DRAIN_ROW_ORACLE'),
        ('--mutate-pause-gate', 'HEAD_DRAIN_PAUSE_ORACLE')],
}
run.EXTRA_INPUTS += [
    'simulator/gsim/head_drain_class.py', 'simulator/gsim/harness/head_drain_oracle.h',
    'fpga/next/timing-batch-owner-row-profile.json',
]

def validate_source(root):
    p = (root / 'src/main/scala/core/ooo/OooParams.scala').read_text()
    b = (root / 'src/main/scala/core/ooo/IntegerBackend.scala').read_text()
    assert 'predecodedHeadDrain: Boolean = false' in p
    assert b.count('classes(renamed.bits.token.index) := HeadDrainClass(') == 1
    assert 'val drainFetch = if (p.predecodedHeadDrain) headPending && headDrainClasses.get(head)' in b
    assert 'else pmpHead || returnHead || vmHead || fenceIHead' in b
    profile = json.loads((root / 'fpga/next/timing-batch-owner-row-profile.json').read_text())
    options = profile['native_options']
    assert len(options) == len(set(options)) == 52
    assert '--future-home-way-reservation' not in options and '--eager-fetch-prefix-select' not in options

run.validate_source = validate_source

def legacy_core_fields(actual):
    """Project only the explicit appended false field for the preserved160-field gate."""
    assert len(actual) == 161 and actual.get('retirementIntent') is False
    legacy = {name: value for name, value in actual.items() if name != 'retirementIntent'}
    assert len(legacy) == 160
    return legacy

def main():
    run.main()
    if '--preflight-only' in sys.argv:
        return
    out = Path(sys.argv[sys.argv.index('--output') + 1]).resolve()
    path = out / 'receipt.json'
    receipt = json.loads(path.read_text())
    receipt['scope'] = 'Independent decode catalog and actual matched default52 OFF/ON backend pair.'
    receipt['limitations'] = [
        'Already-decoded backend inputs; no whole frontend, CPU, board, native resource, or timing qualification.',
        'No memory/translation service responses in paired fixture; held requests are compared.',
        'Test-only oracle/observations retain old decode and shadow state; never use fixture for production resource claims.',
        'Combined ASan+UBSan with halt on error; per-process leak checking disabled under ptrace.',
        'Historical results are not relabeled; current entrypoints check the appended profile/core fields explicitly.',
    ]
    try:
        if 'pair' in receipt['models'] and sys.argv[1] in ('emit', 'generate', 'sanitized'):
            off = json.loads((out / 'pair/actual-core-off.json').read_text())
            on = json.loads((out / 'pair/actual-core-on.json').read_text())
            legacy_off, legacy_on = legacy_core_fields(off), legacy_core_fields(on)
            assert not legacy_off['predecodedHeadDrain']
            assert {**legacy_off, 'predecodedHeadDrain': True} == legacy_on
            assert {**off, 'predecodedHeadDrain': True} == on
            profile = json.loads((run.ROOT / 'fpga/next/timing-batch-owner-row-profile.json').read_text())
            assert (out / 'pair/native-options.txt').read_text().splitlines() == profile['native_options']
            receipt['actual_parameters'] = {'off': off, 'on': on, 'only_delta': 'predecodedHeadDrain'}
        if sys.argv[1] == 'sanitized':
            negatives = [c for c in receipt['commands'] if c['expected'] == 'nonzero']
            expected = sum(len(run.EXTRA_NEGATIVES[run.MODELS[m][1]]) for m in receipt['models'])
            assert len(negatives) == expected
            for command in negatives:
                log = (out / (command['label'] + '.log')).read_text()
                assert not re.search(r'ERROR: AddressSanitizer|runtime error:', log)
                if command['label'].startswith('decode-'):
                    assert 'fired=1' in log and 'head-drain-class-mismatch' in log
                else:
                    assert 'ACTUAL_CORRUPTION count=1' in log
            receipt['negative_controls'] = {'passed': len(negatives), 'observed_output_mutations': True}
    except BaseException as error:
        receipt['status'] = sys.argv[1].upper() + '_AUDIT_FAILED'
        receipt['error'] = str(error)
        raise
    finally:
        path.write_text(json.dumps(receipt, indent=2) + '\n')

if __name__ == '__main__':
    main()
