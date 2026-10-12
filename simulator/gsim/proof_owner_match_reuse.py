#!/usr/bin/env python3
"""Small paired actual-bank qualification; exact old body plus production candidate."""
import hashlib
from pathlib import Path
import pending_store_proof_integration as run
PUBLIC_BASE='cbd94b45805fbe22f659da270646b246675d0a3f'
REFERENCE='src/test/scala/ooo/ReferencePendingVirtualStoreProof.scala'
REFERENCE_BODY_SHA='7d1a0ea99e7de286a3a2ee27a961240198e9081b8fbf715152e68f7dfcbfbdee'
def validate_source(root):
    # The frozen original body is part of the test sources, so a shallow clone
    # does not need a cloud-only review commit or an extra history fetch.
    ref=(root/REFERENCE).read_text()
    actual=ref[ref.index('class ReferencePendingVirtualStoreProof('):].replace(
        'class ReferencePendingVirtualStoreProof(', 'class PendingVirtualStoreProof(', 1).rstrip()
    assert hashlib.sha256(actual.encode()).hexdigest()==REFERENCE_BODY_SHA, \
        'reference is not the exact frozen published old bank body with class-only rename'
run.MODELS={
 'pair1':('ProofOwnerMatchPairGsim','pair',['1'],['PENDING_STORE_SLOTS=1'],'OWNER_PAIR_PASS slots=1'),
 'pair2':('ProofOwnerMatchPairGsim','pair2',['2'],['PENDING_STORE_SLOTS=2'],'OWNER_PAIR_PASS slots=2'),
}
run.DEFAULT_MODELS='pair1,pair2'
run.HOST_FILES={'pair':'simulator/gsim/harness/proof_owner_match_pair.cpp','pair2':'simulator/gsim/harness/proof_owner_match_pair.cpp'}
controls=['owner-tag','owner-va','owner-size','owner-mask','clear','consume','live-clear','proof-tag']
run.EXTRA_NEGATIVES={s:[('--mutate-'+c,'cycle parity mismatch') for c in controls+(['wrong-row'] if s=='pair2' else [])] for s in ['pair','pair2']}
run.EXTRA_INPUTS=['simulator/gsim/proof_owner_match_reuse.py','simulator/gsim/pending_store_proof_integration.py']
run.validate_source=validate_source
if __name__=='__main__':run.main()
