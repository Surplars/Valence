#!/usr/bin/env python3
"""Short bounded proof/credit gate: tiny components plus one real decoded 2/2 backend."""
import json, re, sys
from pathlib import Path
import pending_store_proof_integration as run
run.MODELS={
    'credit1':('BoundedEarlyLoadCreditGsim','credit1',['1'],['EARLY_LOAD_CREDITS=1'],'EARLY_CREDIT_PASS capacity=1'),
    'credit2':('BoundedEarlyLoadCreditGsim','credit2',['2'],['EARLY_LOAD_CREDITS=2'],'EARLY_CREDIT_PASS capacity=2'),
    'rows_only':('PendingStoreProofBankGsim','control',['2','1'],['PENDING_STORE_SLOTS=2','EARLY_LOAD_CREDITS=1'],'PROOF_CREDIT_CONTROL_PASS'),
    'credits_only':('PendingStoreProofBankGsim','control',['1','2'],['PENDING_STORE_SLOTS=1','EARLY_LOAD_CREDITS=2'],'PROOF_CREDIT_CONTROL_PASS'),
    'joint':('PendingStoreProofBankGsim','control',['2','2'],['PENDING_STORE_SLOTS=2','EARLY_LOAD_CREDITS=2'],'PROOF_CREDIT_CONTROL_PASS'),
    'backend':('PendingStoreProofBackendGsim','dualbackend',['1','1','1','2','2'],
        ['PENDING_STORE_ENABLED=1','BOUND_HEAD_STORE_OVERLAP=1','PENDING_READY_STORE_BYPASS=1','EARLY_LOAD_CREDITS=2'],'DUAL_BACKEND_PASS'),
}
run.DEFAULT_MODELS=','.join(run.MODELS)
run.HOST_FILES={
    'credit1':'simulator/gsim/harness/bounded_early_load_credit.cpp',
    'credit2':'simulator/gsim/harness/bounded_early_load_credit.cpp',
    'control':'simulator/gsim/harness/dual_proof_credit_controls.cpp',
    'dualbackend':'simulator/gsim/harness/dual_proof_credit_backend.cpp',
}
run.EXTRA_NEGATIVES={
    'credit':[
        ('--mutate-tag','independent full-token obligation mismatch'),
        ('--mutate-free','pre-edge free capacity mismatch'),
        ('--wrong-consume','consumption requires exactly one'),
        ('--wrong-cancel','only an unconsumed exact offer'),
        ('--duplicate-reserve','cannot reserve a second early-load responsibility'),
        ('--duplicate-consume','consumption requires exactly one'),
        ('--consume-and-cancel','only an unconsumed exact offer'),
        ('--duplicate-live','at most one live LSU slot'),
        ('--turnover-reserve','pre-edge free entry'),
        ('--capacity-overflow','pre-edge free entry'),
    ],
    'control':[('--mutate-full-tag','independent full-tuple oracle mismatch')],
    'dualbackend':[
        ('--mutate-data','independent execution data mismatch'),
        ('--mutate-frozen-pa','bound store failed frozen physical handoff'),
        ('--mutate-local-ack','memory retirement before actual response and completion'),
        ('--mutate-store-error','physical error lost exact completion cause/original VA'),
        ('--mutate-retirement','fault/killed/duplicate retirement'),
    ],
}
run.EXTRA_NEGATIVES['credit2']=run.EXTRA_NEGATIVES.pop('credit')
run.EXTRA_NEGATIVES['credit1']=[(flag, 'early-load reserve requires a pre-edge free entry'
    if flag=='--duplicate-reserve' else anchor) for flag,anchor in run.EXTRA_NEGATIVES['credit2']]
run.EXTRA_INPUTS=['simulator/gsim/dual_proof_credit_resume.py','simulator/gsim/dual_proof_credit.py','simulator/gsim/pending_store_proof_integration.py',
    'simulator/gsim/harness/pending_store_proof_bank.cpp','simulator/gsim/harness/bound_head_store_overlap_backend.cpp']
if __name__=='__main__':
    run.main()
    if len(sys.argv)>1 and sys.argv[1]=='sanitized':
        out=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
        path=out/'receipt.json';receipt=json.loads(path.read_text())
        negative=[c for c in receipt['commands'] if c['expected']=='nonzero']
        try:
            assert negative, 'no negative controls executed'
            for command in negative:
                log=(out/(command['label']+'.log')).read_text(errors='replace')
                assert re.search(r'ACTUAL_CORRUPTION count=[1-9][0-9]*',log), command['label']
            receipt['negative_evidence']={'status':'PASS','controls':len(negative),
                'contract':'Every expected-failure process has nonzero exit, specific oracle/assertion anchor and nonzero injected-event count.'}
            receipt['scope']='Two bounded credit capacities, three small proof/credit controls and one actual real-decoder rows2/credits2 LSU4 backend.'
            receipt['limitations']=['No whole-board, workload speedup, Vivado, routed timing or full regression claim.',
                'Synthetic controls isolate actual component availability/certificate vetoes; only real backend establishes accepted starts.',
                'All-one backend is tied to saved baseline/default source correspondence, not freshly executed here.',
                'Combined ASan+UBSan; detect_leaks=0 because LSan is unavailable under ptrace.']
        except BaseException as error:
            receipt['status']='SANITIZED_FAILED_NEGATIVE_EVIDENCE';receipt['error']=str(error)
            path.write_text(json.dumps(receipt,indent=2)+'\n');raise
        path.write_text(json.dumps(receipt,indent=2)+'\n')
