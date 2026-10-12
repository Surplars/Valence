#!/usr/bin/env python3
"""Source-bound paired lifecycle and actual ABC backend short gate, default OFF."""
import hashlib
import json
import re
import sys
from pathlib import Path
import dual_proof_credit as existing
import lane1_owner_match_host as passive

run = existing.run
TOP, HOST, ARGS, DEFINES, ANCHOR = run.MODELS['backend']
NEGATIVES = list(run.EXTRA_NEGATIVES[HOST])
run.MODELS = {
    'lifecycle': ('Lane1OwnerLifecycleGsim', 'ownerlife', [], [], 'LANE1_OWNER_LIFECYCLE_PASS'),
    'off': (TOP, 'ownerbackend', [*ARGS, '1', '1', '0', '1'], DEFINES, ANCHOR),
    'on': (TOP, 'ownerbackend', [*ARGS, '1', '1', '1', '1'], DEFINES, ANCHOR),
}
run.DEFAULT_MODELS = 'lifecycle,off,on'
run.HOST_FILES.update({
    'ownerlife': 'simulator/gsim/harness/lane1_owner_lifecycle.cpp',
    'ownerbackend': 'simulator/gsim/harness/lane1_owner_match_backend.cpp',
})
run.EXTRA_NEGATIVES = {
    'ownerlife': [
        ('--negative-high-tag', 'pure 64-bit owner equality mismatch'),
        ('--negative-valid-qualified', 'pure 64-bit owner equality mismatch'),
        ('--negative-unmasked-cancel', 'occupied-masked cancel mismatch'),
    ],
    'ownerbackend': NEGATIVES,
}
run.CONFIG_SUITES = ['ooo.Lane1OwnerMatchConfigSpec', 'ooo.TimingBatchConfigSpec']
run.EXTRA_INPUTS += ['simulator/gsim/lane1_owner_match.py', 'simulator/gsim/lane1_owner_match_host.py',
    'simulator/gsim/harness/dual_proof_credit_backend.cpp', 'fpga/next/timing-batch-abc-profile.json']

def validate_source(root):
    passive.validate(root)
    profile = json.loads((root/'fpga/next/timing-batch-abc-profile.json').read_text())['native_options']
    text = (root/'src/test/scala/ooo/Lane1OwnerBackendProfile.scala').read_text()
    frozen = re.findall(r'"(--[^"\n]+)"', text.split('val abc:', 1)[0])
    assert len(frozen) == 46 and set(frozen) == set(profile), 'published ABC options drift'
    assert '--shared-lane1-owner-match' not in profile, 'published default must remain OFF'

run.validate_source = validate_source

def audit_backend(output, side):
    model = output/side
    actual_path = model/'actual-core-parameters.json'
    actual = json.loads(actual_path.read_text())
    abc = json.loads((model/'published-abc/actual-core-parameters.json').read_text())
    assert len(actual) == len(abc) == 155, 'complete actual parameter inventory changed'
    expected = {**abc, 'speculativeRamBase': 0x80010000, 'speculativeRamBytes': 65536,
        'taggedStoreReturns': False, 'postedStoreMerge': False, 'postedPrefetchHeadOffer': False,
        'sharedLane1OwnerMatch': side == 'on'}
    assert actual == expected, 'actual backend has an unapproved published-profile difference'
    assert not abc['sharedLane1OwnerMatch'], 'published baseline unexpectedly enables sharing'
    for field, value in {'tagBits': 64, 'robEntries': 16, 'physicalRegs': 48, 'memoryEntries': 4,
        'renameWidth': 2, 'completionWidth': 2, 'commitWidth': 2, 'registeredIssueExecute': True,
        'parallelIssuePayload': True, 'lvtPhysicalRegisterFile': True, 'bankedIssuePayload': True,
        'sharedStoreOperandReads': True, 'reconstructIssueTokenIndex': False,
        'registeredPendingStoreQuery': True, 'registeredCanonicalStoreEvent': True,
        'alignedFetchPermissionStage': True, 'pendingVirtualStoreProofSlots': 2,
        'pendingStoreEarlyLoadCredits': 2}.items():
        assert actual[field] == value, (field, actual[field], value)
    log = (output/(side+'-emit.log')).read_text()
    assert f"LANE1_OWNER_MATCH shared={str(side == 'on').lower()} registered=true rawPayload=true tagBits=64" in log
    fir = (model/(TOP+'.fir')).read_text()
    headers = list(re.finditer(r'^  (?:public )?module (\w+)\s*:', fir, re.M))
    modules = {m[1]: fir[m.start():headers[i+1].start() if i+1 < len(headers) else len(fir)]
        for i, m in enumerate(headers)}
    assert 'IntegerBackend' in modules and 'RenameRob' in modules
    assert 'address : UInt<6>[14]' in modules['OwnerBankedPhysicalRegisterFile']
    assert len(re.findall(r'^    inst slots_\d+ of LoadStoreUnit(?:_\d+)?\s',
        modules['ParallelLoadStoreUnit'], re.M)) == 4
    return {'actual_core_parameters': actual, 'published_abc_parameters': abc,
        'host_exceptions': {key: {'published': abc[key], 'fixture': actual[key]} for key in
            ('speculativeRamBase', 'speculativeRamBytes', 'taggedStoreReturns', 'postedStoreMerge', 'postedPrefetchHeadOffer')},
        'declared_prf_addresses': 14, 'lsu_owners': 4,
        'prf_observability': 'The host reads architectural inspection; native board removes that unused value read.',
        'actual_parameter_sha256': run.sha(actual_path), 'fir_sha256': run.sha(model/(TOP+'.fir'))}

def main():
    if '--models' in sys.argv:
        assert sys.argv[sys.argv.index('--models')+1] == run.DEFAULT_MODELS, 'paired gate cannot omit a model'
    run.main()
    if '--preflight-only' in sys.argv:
        return
    stage = sys.argv[1]
    out = Path(sys.argv[sys.argv.index('--output')+1]).resolve()
    path = out/'receipt.json'
    receipt = json.loads(path.read_text())
    try:
        if stage in ('emit', 'generate', 'sanitized'):
            receipt['actual_backends'] = {side: audit_backend(out, side) for side in ('off', 'on')}
            off, on = [receipt['actual_backends'][side]['actual_core_parameters'] for side in ('off', 'on')]
            assert {**off, 'sharedLane1OwnerMatch': True} == on, 'paired parameter drift'
        if stage == 'sanitized':
            negatives = [c for c in receipt['commands'] if c['expected'] == 'nonzero']
            assert len(negatives) == 13, 'three lifecycle and five controls per backend required'
            for entry in negatives:
                log = (out/(entry['label']+'.log')).read_text()
                assert re.search(r'ACTUAL_CORRUPTION count=[1-9][0-9]*', log), entry['label']
                assert not re.search(r'ERROR: AddressSanitizer|runtime error:', log), entry['label']
            logs = [(out/(side+'-sanitized-positive.log')).read_text() for side in ('off', 'on')]
            assert logs[0] == logs[1], 'OFF/ON cycle transcript or independent host result differs'
            lines = [line for line in logs[0].splitlines() if line.startswith('LANE1_BACKEND_TRACE ')]
            assert len(lines) > 100, 'missing actual cycle transcript'
            receipt['paired_backend_trace'] = {'identical': True, 'cycles_observed': len(lines),
                'sha256': hashlib.sha256('\n'.join(lines).encode()).hexdigest()}
            receipt['negative_controls'] = {'passed': 13, 'contract': 'nonzero exit, specific oracle anchor, real corruption count, sanitizer clean'}
        receipt['scope'] = 'One paired real owner lifecycle and two actual decoded ABC backends with five explicit common host exceptions.'
        receipt['limitations'] = ['No complete board execution, CPU workload performance, mapped area, placement or timing claim.',
            'Lifecycle high-tag injections enter public capture/completion inputs; live allocation tags are never seeded internally.',
            'Backend observer reads committed PRF values; declared read addresses include its inspection port.']
    except BaseException as error:
        receipt['status'] = stage.upper()+'_AUDIT_FAILED'
        receipt['error'] = str(error)
        raise
    finally:
        path.write_text(json.dumps(receipt, indent=2)+'\n')

if __name__ == '__main__':
    main()
