#!/usr/bin/env python3
"""Short source-bound rank-1 PRF-ID equivalence and real backend gate."""
import hashlib
import json
import re
import sys
from pathlib import Path
import lane1_owner_match as previous

run = previous.run
FIELD = 'directRank1MemorySourceIds'
TOP, HOST, ARGS, DEFINES, ANCHOR = run.MODELS['on']
run.MODELS = {
    'boundary': ('Rank1PrfAddressPairGsim', 'rank1boundary', [], [], 'RANK1_PRF_ADDRESS_PAIR_PASS'),
    'off': (TOP, HOST, [*ARGS, '0'], DEFINES, ANCHOR),
    'on': (TOP, HOST, [*ARGS, '1'], DEFINES, ANCHOR),
}
BOUNDARY_ONLY = '--boundary-only' in sys.argv
if BOUNDARY_ONLY:
    sys.argv.remove('--boundary-only')
    run.MODELS = {'boundary': run.MODELS['boundary']}
else:
    run.MODELS = {name: run.MODELS[name] for name in ('off', 'on')}
run.DEFAULT_MODELS = ','.join(run.MODELS)
run.HOST_FILES['rank1boundary'] = 'simulator/gsim/harness/rank1_prf_address_pair.cpp'
run.EXTRA_NEGATIVES = {HOST: list(previous.NEGATIVES), 'rank1boundary': [
    ('--mutate-raw-index0', 'RANK1_PRF_ORACLE candidate source ID'),
    ('--mutate-source', 'RANK1_PRF_ORACLE candidate source ID'),
    ('--mutate-data', 'RANK1_PRF_ORACLE candidate PRF data'),
    ('--mutate-address', 'RANK1_PRF_ORACLE candidate prepared payload'),
    ('--mutate-owner', 'RANK1_PRF_ORACLE candidate selector owner'),
    ('--mutate-immediate', 'RANK1_PRF_ORACLE candidate guarded immediate'),
    ('--mutate-invalid-request', 'RANK1_PRF_ORACLE candidate request validity'),
    ('--mutate-invalid-completion', 'RANK1_PRF_ORACLE candidate completion validity'),
    ('--mutate-invalid-capture', 'RANK1_PRF_ORACLE candidate captured payload including invalid'),
]}
# Boundary controls are frozen here with the independent host before execution.
run.CONFIG_SUITES = ['ooo.Rank1MemorySourceIdsConfigSpec', 'ooo.Lane1OwnerMatchConfigSpec', 'ooo.TimingBatchConfigSpec']
run.EXTRA_INPUTS += ['simulator/gsim/prf_address_clear.py', 'fpga/next/timing-batch-abc-lane1-owner-profile.json']


def validate_source(root):
    previous.validate_source(root)
    source = (root/'src/main/scala/core/ooo/IntegerBackend.scala').read_text()
    assert source.count('val directSourceIds = p.directRank1MemorySourceIds && rank == 1') == 1
    assert 'val source1 = if (directSourceIds) entry.renamed.source1' in source
    assert 'val source2 = if (directSourceIds) entry.renamed.source2' in source
    assert 'else Mux(valid, entry.renamed.source1, 0.U)' in source
    assert 'else Mux(valid, entry.renamed.source2, 0.U)' in source
    assert '--direct-rank1-memory-source-ids' not in json.loads(
        (root/'fpga/next/timing-batch-abc-lane1-owner-profile.json').read_text())['native_options']

run.validate_source = validate_source


def audit_backend(output, side):
    model = output/side
    actual_path = model/'actual-core-parameters.json'
    actual = json.loads(actual_path.read_text())
    abc = json.loads((model/'published-abc/actual-core-parameters.json').read_text())
    assert len(actual) == len(abc) == 156, 'complete actual parameter inventory changed'
    expected = {**abc, 'speculativeRamBase': 0x80010000, 'speculativeRamBytes': 65536,
        'taggedStoreReturns': False, 'postedStoreMerge': False, 'postedPrefetchHeadOffer': False,
        'sharedLane1OwnerMatch': True, FIELD: side == 'on'}
    assert actual == expected, 'actual backend has an unapproved published47-profile difference'
    assert not abc[FIELD] and not abc['sharedLane1OwnerMatch'], 'generic ABC preset changed'
    for field, value in {'tagBits': 64, 'robEntries': 16, 'physicalRegs': 48, 'memoryEntries': 4,
        'renameWidth': 2, 'completionWidth': 2, 'commitWidth': 2, 'registeredIssueExecute': True,
        'parallelIssuePayload': True, 'lvtPhysicalRegisterFile': True, 'bankedIssuePayload': True,
        'sharedStoreOperandReads': True, 'reconstructIssueTokenIndex': False,
        'registeredPendingStoreQuery': True, 'registeredCanonicalStoreEvent': True,
        'alignedFetchPermissionStage': True, 'pendingVirtualStoreProofSlots': 2,
        'pendingStoreEarlyLoadCredits': 2, 'registeredMemoryAddress': True,
        'parallelMemoryPreparation': True, 'parallelMemoryPayload': True,
        'compactMemoryOperandSelect': True, 'memoryProofFrontier': False}.items():
        assert actual[field] == value, (field, actual[field], value)
    log = (output/(side+'-emit.log')).read_text()
    assert 'LANE1_OWNER_MATCH shared=true registered=true rawPayload=true tagBits=64' in log
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
        'shared_lane1_owner_match_retained': True, 'declared_prf_addresses': 14, 'lsu_owners': 4,
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
        if not BOUNDARY_ONLY and stage in ('emit', 'generate', 'sanitized'):
            receipt['actual_backends'] = {side: audit_backend(out, side) for side in ('off', 'on')}
            off, on = [receipt['actual_backends'][side]['actual_core_parameters'] for side in ('off', 'on')]
            assert {**off, FIELD: True} == on, 'paired parameter drift'
        if stage == 'sanitized':
            negatives = [c for c in receipt['commands'] if c['expected'] == 'nonzero']
            assert len(negatives) == (len(run.EXTRA_NEGATIVES['rank1boundary']) if BOUNDARY_ONLY else 10), 'missing oracle controls'
            for entry in negatives:
                log = (out/(entry['label']+'.log')).read_text()
                assert re.search(r'ACTUAL_CORRUPTION count=[1-9][0-9]*', log), entry['label']
                assert not re.search(r'ERROR: AddressSanitizer|runtime error:', log), entry['label']
            if not BOUNDARY_ONLY:
                logs = [(out/(side+'-sanitized-positive.log')).read_text() for side in ('off', 'on')]
                assert logs[0] == logs[1], 'OFF/ON cycle transcript or independent host result differs'
                lines = [line for line in logs[0].splitlines() if line.startswith('LANE1_BACKEND_TRACE ')]
                assert len(lines) > 100, 'missing actual cycle transcript'
                receipt['paired_backend_trace'] = {'identical': True, 'cycles_observed': len(lines),
                    'sha256': hashlib.sha256('\n'.join(lines).encode()).hexdigest()}
            receipt['negative_controls'] = {'passed': len(negatives),
                'contract': 'nonzero exit, specific oracle anchor, real corruption count, sanitizer clean'}
        receipt['scope'] = ('One paired real selector/payload/PRF fixture.' if BOUNDARY_ONLY else
            'Two actual decoded published47 backends with five explicit common host exceptions.')
        receipt['limitations'] = ['No complete board execution, CPU workload performance, mapped area, placement or timing claim.',
            'Boundary lifecycle is fixture-local; accepted request/completion/retirement behavior is established by the separate actual backend.',
            'Backend observer reads committed PRF values; declared read addresses include its inspection port.']
    except BaseException as error:
        receipt['status'] = stage.upper()+'_AUDIT_FAILED'
        receipt['error'] = str(error)
        raise
    finally:
        path.write_text(json.dumps(receipt, indent=2)+'\n')

if __name__ == '__main__':
    main()
