#!/usr/bin/env python3
"""One real decoded rows2/credits2 backend gate after the combined production compile.

Reuses the existing independent dual-credit host and five actual corruption controls.
Does not qualify the complete tagged-return maxperf board or routed timing.
"""
import json,re,sys
from pathlib import Path
import dual_proof_credit as existing
run=existing.run
top,host,args,defines,anchor=run.MODELS['backend']
run.MODELS={'backend':(top,host,[*args,'1','1'],defines,anchor)}
run.DEFAULT_MODELS='backend'
run.CONFIG_SUITES=['ooo.TimingBatchConfigSpec']
run.EXTRA_INPUTS=[*run.EXTRA_INPUTS,'simulator/gsim/timing_batch_backend.py']
if __name__=='__main__':
    run.main()
    if '--preflight-only' in sys.argv:
        sys.exit(0)
    stage=sys.argv[1]
    out=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
    receipt=out/'receipt.json';r=json.loads(receipt.read_text())
    if stage=='emit':
        assert 'PENDING_BACKEND_QUERY_STAGE registered=true proofRows=2 credits=2' in (out/'backend-emit.log').read_text(), \
            'actual emitted backend did not report registered query activation'
        assert 'PENDING_BACKEND_CANONICAL_STAGE backend=true adapter=true' in (out/'backend-emit.log').read_text(), \
            'actual canonical producer/backend stage modes differ'
    if stage=='sanitized':
        negatives=[c for c in r['commands'] if c['expected']=='nonzero']
        assert len(negatives)==5,'expected five independent backend corruption controls'
        for command in negatives:
            assert re.search(r'ACTUAL_CORRUPTION count=[1-9][0-9]*',(out/(command['label']+'.log')).read_text()),command['label']
        r['negative_evidence']={'status':'PASS','controls':5,'contract':'Specific oracle anchor, nonzero exit and actual injected-event count.'}
    r['scope']='One actual fresh-compiled decoded rows2/credits2 LSU4 backend with explicit query and paired canonical event/lifecycle stages. No full tagged-return maxperf board claim.'
    r['limitations']=['Production classes must come from the combined candidate compile, including IntegerBackend and OooParams.',
        'No whole-board, CPU workload performance, native placement or timing qualification.']
    receipt.write_text(json.dumps(r,indent=2)+'\n')
