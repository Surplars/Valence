#!/usr/bin/env python3
"""Small canonical consumer gate using the existing source-bound execution runner."""
import hashlib
import json
import sys
from pathlib import Path
import pending_store_proof_integration as run
import lane1_owner_match as inherited

boundary = '--boundary-only' in sys.argv
if boundary:
    sys.argv.remove('--boundary-only')
run.MODELS = {
    'boundary': ('CanonicalStoreOwnerMapGsim', 'canonicalmap', [], [], 'CANONICAL_OWNER_MAP_PASS'),
    'off': ('CanonicalStoreOwnerMapBackendGsim', 'canonicalbackend', ['0'],
        ['PENDING_STORE_ENABLED=1', 'BOUND_HEAD_STORE_OVERLAP=1', 'PENDING_READY_STORE_BYPASS=1',
         'EARLY_LOAD_CREDITS=2'], 'DUAL_BACKEND_PASS'),
    'on': ('CanonicalStoreOwnerMapBackendGsim', 'canonicalbackend', ['1'],
        ['PENDING_STORE_ENABLED=1', 'BOUND_HEAD_STORE_OVERLAP=1', 'PENDING_READY_STORE_BYPASS=1',
         'EARLY_LOAD_CREDITS=2'], 'DUAL_BACKEND_PASS'),
}
run.MODELS = {k: run.MODELS[k] for k in (['boundary'] if boundary else ['off', 'on'])}
run.DEFAULT_MODELS = ','.join(run.MODELS)
run.HOST_FILES.update({
    'canonicalmap': 'simulator/gsim/harness/canonical_store_owner_map.cpp',
    'canonicalbackend': 'simulator/gsim/harness/canonical_store_owner_map_backend.cpp',
})
run.EXTRA_NEGATIVES = {'canonicalbackend': list(inherited.NEGATIVES),
    'canonicalmap': [('--mutate-map', 'candidate consumer map mismatch')]}
run.EXTRA_INPUTS += ['simulator/gsim/canonical_store_owner_map.py',
    'simulator/gsim/harness/canonical_store_oracle.h', 'simulator/gsim/harness/lane1_owner_match_backend.cpp',
    'simulator/gsim/harness/gsim_model_storage.h']


def validate(root):
    production = (root / 'src/main/scala/core/ooo/integration/IntegerBackend.scala').read_text()
    params = (root / 'src/main/scala/core/ooo/config/OooParams.scala').read_text()
    assert params.count('sharedCanonicalStoreOwnerMatch: Boolean = false') == 1
    assert '!sharedCanonicalStoreOwnerMatch || canonicalVirtualStoreOverlap' in params
    assert production.count('val shareCanonicalStoreOwnerMatch = p.sharedCanonicalStoreOwnerMatch') == 1
    assert 'shareCanonicalStoreOwnerMatch: Boolean' not in production
    assert production.count('if (shareCanonicalStoreOwnerMatch)') == 1
    assert 'issueEntries(index).renamed.token.asUInt === token.asUInt' in production
    host = root / 'simulator/gsim/harness/lane1_owner_match_backend.cpp'
    assert hashlib.sha256(host.read_bytes()).hexdigest() == 'e3e59ad7bd92b2867e4ff790643dcb7d007480dde42703a405b89cf8aed7bbbb'


run.validate_source = validate

if __name__ == '__main__':
    run.main()
    if '--preflight-only' not in sys.argv and sys.argv[1] == 'sanitized':
        out = Path(sys.argv[sys.argv.index('--output') + 1])
        path = out / 'receipt.json'
        receipt = json.loads(path.read_text())
        if boundary:
            log = (out / 'boundary-sanitized-positive.log').read_text()
            assert log.count('CANONICAL_OWNER_MAP_PASS ') == 4
            receipt['cases'] = 'C OFF/ON and reconstructed index OFF/ON in one real-tracker model'
        else:
            logs = [(out / (side + '-sanitized-positive.log')).read_text() for side in ('off', 'on')]
            assert logs[0] == logs[1], 'paired backend cycle and owner history differs'
            params = [json.loads((out / side / 'actual-core-parameters.json').read_text()) for side in ('off', 'on')]
            assert params[0]['sharedCanonicalStoreOwnerMatch'] is False
            assert params[1]['sharedCanonicalStoreOwnerMatch'] is True
            comparable = [{k: v for k, v in p.items() if k != 'sharedCanonicalStoreOwnerMatch'} for p in params]
            assert comparable[0] == comparable[1], 'core parameter drift beyond the explicit owner-map option'
            receipt['paired_transcript_sha256'] = hashlib.sha256(logs[0].encode()).hexdigest()
            receipt['map_observations'] = logs[0].count('CANONICAL_OWNER_MAP_TRACE ')
        receipt['scope'] = 'Canonical consumer map only; high tags are boundary inputs and backend tags allocate naturally.'
        receipt['limitations'] = ['No FullCPU or board run, native export, synthesis, placement or timing qualification.']
        path.write_text(json.dumps(receipt, indent=2) + '\n')
