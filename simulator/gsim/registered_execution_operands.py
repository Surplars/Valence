#!/usr/bin/env python3
"""Source-bound narrow registered-execution operand component/backend gate."""
import hashlib,json,re,sys
from pathlib import Path
import pending_store_proof_integration as run
import lane1_owner_match as previous
import registered_execution_operands_host as observer

FIELD='directRegisteredExecutionOperands'
BOUNDARY_ONLY='--boundary-only' in sys.argv
if BOUNDARY_ONLY:sys.argv.remove('--boundary-only')
TOP='RegisteredExecutionOperandsBackendGsim'
run.MODELS={
 'boundary':('RegisteredExecutionOperandPairGsim','execboundary',[],[],'REGISTERED_EXECUTION_OPERAND_PAIR_PASS'),
 'off':(TOP,'execbackend',['0'],['PENDING_STORE_ENABLED=1','BOUND_HEAD_STORE_OVERLAP=1','PENDING_READY_STORE_BYPASS=1','EARLY_LOAD_CREDITS=2'],'DUAL_BACKEND_PASS'),
 'on':(TOP,'execbackend',['1'],['PENDING_STORE_ENABLED=1','BOUND_HEAD_STORE_OVERLAP=1','PENDING_READY_STORE_BYPASS=1','EARLY_LOAD_CREDITS=2'],'DUAL_BACKEND_PASS'),
}
run.MODELS={k:run.MODELS[k] for k in (['boundary'] if BOUNDARY_ONLY else ['off','on'])}
run.DEFAULT_MODELS=','.join(run.MODELS)
run.HOST_FILES.update({'execboundary':'simulator/gsim/harness/registered_execution_operand_pair.cpp',
 'execbackend':'simulator/gsim/harness/registered_execution_operands_backend.cpp'})
run.CONFIG_SUITES=['ooo.RegisteredExecutionOperandConfigSpec']
run.EXTRA_NEGATIVES={'execbackend':list(previous.NEGATIVES),'execboundary':[('--mutate-store-exclusion','valid offer must be nonmemory'), ('--mutate-load-priority','all offered payload bits'), ('--mutate-store-forwarding','unchanged shared store preparation'), ('--mutate-valid-payload','all offered payload bits'), ('--mutate-invalid-held','all stored payload bits including invalid held output')]}
run.EXTRA_INPUTS += ['simulator/gsim/registered_execution_operands.py','simulator/gsim/registered_execution_operands_host.py',
 'simulator/gsim/harness/lane1_owner_match_backend.cpp','simulator/gsim/harness/dual_proof_credit_backend.cpp',
 'fpga/next/timing-batch-abc-lane1-owner-profile.json']

def validate_source(root):
    observer.validate(root)
    source=(root/'src/main/scala/core/ooo/IntegerBackend.scala').read_text()
    assert source.count('if (p.directRegisteredExecutionOperands)')==2
    assert source.count('incoming.left := (if (p.directRegisteredExecutionOperands) issueOperandValue(source1, storedLeft)')==1
    assert source.count('incoming.right := (if (p.directRegisteredExecutionOperands) issueOperandValue(source2, storedRight)')==1
    assert 'val dispatchLeft = Mux(dispatchEntry.request.memory, storedLeft, issueOperandValue(source1, storedLeft))' in source
    assert 'val dispatchRight = Mux(dispatchEntry.request.memory, storedRight, issueOperandValue(source2, storedRight))' in source
run.validate_source=validate_source

def audit_backend(out,side):
    path=out/side/'actual-core-parameters.json'; actual=json.loads(path.read_text())
    abc=json.loads((out/side/'published-abc/actual-core-parameters.json').read_text())
    assert len(actual)==len(abc)==157
    expected={**abc,'speculativeRamBase':0x80010000,'speculativeRamBytes':65536,
      'taggedStoreReturns':False,'postedStoreMerge':False,'postedPrefetchHeadOffer':False,
      'sharedLane1OwnerMatch':True,'directRank1MemorySourceIds':True,FIELD:side=='on'}
    assert actual==expected,'unapproved core parameter drift'
    return {'actual':actual,'host_exceptions':['speculativeRamBase','speculativeRamBytes','taggedStoreReturns','postedStoreMerge','postedPrefetchHeadOffer'],
      'parameter_sha256':run.sha(path)}

def main():
    if '--models' in sys.argv:assert sys.argv[sys.argv.index('--models')+1]==run.DEFAULT_MODELS
    run.main()
    if '--preflight-only' in sys.argv:return
    stage=sys.argv[1];out=Path(sys.argv[sys.argv.index('--output')+1]).resolve();path=out/'receipt.json'
    receipt=json.loads(path.read_text())
    try:
        if not BOUNDARY_ONLY and stage in ('emit','generate','sanitized'):
            receipt['actual_backends']={s:audit_backend(out,s) for s in ('off','on')}
            off,on=[receipt['actual_backends'][s]['actual'] for s in ('off','on')]
            assert {**off,FIELD:True}==on
        if stage=='sanitized':
            negatives=[c for c in receipt['commands'] if c['expected']=='nonzero']
            assert len(negatives)==(len(run.EXTRA_NEGATIVES['execboundary']) if BOUNDARY_ONLY else 10)
            for entry in negatives:
                text=(out/(entry['label']+'.log')).read_text()
                assert re.search(r'ACTUAL_CORRUPTION count=[1-9][0-9]*',text)
                assert not re.search(r'ERROR: AddressSanitizer|runtime error:',text)
            if not BOUNDARY_ONLY:
                logs=[(out/(s+'-sanitized-positive.log')).read_text() for s in ('off','on')]
                assert logs[0]==logs[1],'paired cycle/state/input/architectural transcript differs'
                lines=[l for l in logs[0].splitlines() if l.startswith('EXECUTION_STAGE_TRACE ')]
                assert len(lines)>200
                receipt['paired_backend_trace']={'identical':True,'lane_samples':len(lines),
                    'all_591_held_bits_including_invalid':True,'all_valid_input_bits':True,
                    'sha256':hashlib.sha256('\n'.join(lines).encode()).hexdigest()}
            receipt['negative_controls']={'passed':len(negatives),'contract':'nonzero exit, named oracle anchor, actual corruption, sanitizer clean'}
        receipt['scope']='Real registered input/stage component proof and paired decoded backend with five explicit inherited fixture exceptions.'
        receipt['limitations']=['No whole CPU/board, mapped timing/area, or rank51-path claim.',
          'Only invalid combinational enq operand bits may differ; every held payload bit is compared unconditionally.']
    except BaseException as error:
        receipt['status']=stage.upper()+'_AUDIT_FAILED';receipt['error']=str(error);raise
    finally:path.write_text(json.dumps(receipt,indent=2)+'\n')
if __name__=='__main__':main()
