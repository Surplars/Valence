#!/usr/bin/env python3
"""Actual producer and production ROB-owner wiring, frozen old maps, short sanitized qualification."""
import hashlib
import pending_store_proof_integration as run
REFERENCE='src/test/scala/ooo/FrozenPendingStoreRobMapping.scala'
REFERENCE_SHA='6c7a302503525328cd83a6fb39f266592bf5558b65b733b1a808d34e9f5ae086'
def validate_source(root):
    assert hashlib.sha256((root/REFERENCE).read_bytes()).hexdigest()==REFERENCE_SHA, 'frozen full-token reference drift'
run.MODELS={
    'pair1':('PendingStoreRobMappingGsim','robmap1',['1'],['PENDING_STORE_SLOTS=1'],'ROB_MAP_PASS slots=1'),
    'pair2':('PendingStoreRobMappingGsim','robmap2',['2'],['PENDING_STORE_SLOTS=2'],'ROB_MAP_PASS slots=2'),
}
run.DEFAULT_MODELS='pair1,pair2'
run.HOST_FILES={stem:'simulator/gsim/harness/pending_store_rob_mapping.cpp' for stem in ['robmap1','robmap2']}
controls=['producer-valid','index','producer-full-token','owner-tag','owner-va','owner-size','owner-mask','clear','consume','live-clear','proof-tag']
run.EXTRA_NEGATIVES={stem:[('--mutate-'+control,'cycle parity mismatch') for control in controls+(['wrong-row'] if stem=='robmap2' else [])] for stem in ['robmap1','robmap2']}
run.EXTRA_INPUTS=['simulator/gsim/pending_store_rob_mapping.py','simulator/gsim/pending_store_proof_integration.py',
    'simulator/gsim/prepare_pending_store_rob_mapping_cache.py']
run.validate_source=validate_source
if __name__=='__main__':run.main()
