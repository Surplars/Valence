#!/usr/bin/env python3
"""Bounded full-record queue parity and independent owner oracle; no board/STA."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
import run as common

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--gsim',type=Path,required=True);ap.add_argument('--tag',required=True);a=ap.parse_args()
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    files=[common.ROOT/p for p in ('src/main/scala/ip/bus/MirroredHeadQueue.scala','src/main/scala/core/ooo/platform/bus/RegisteredRequestQueue.scala','src/test/scala/ooo/MirroredRequestQueueGsim.scala','simulator/gsim/harness/mirrored_request_queue.cpp','simulator/gsim/mirrored_request_queue.py')]
    files += sorted((common.ROOT/"src").rglob("*.scala")) + [common.HERE/"run.py", common.HERE/"config/toolchain.json"]
    before={str(p.relative_to(common.ROOT)):sha(p) for p in files};cxx,_=common.compiler();results=[]
    for depth in (2,3,4,5,16):
        model=common.test(a.gsim,cxx,a.tag+'/depth-'+str(depth),'ooo.MirroredRequestQueueGsimMain','MirroredRequestQueueGsim','mirrored_request_queue.cpp',parameters=(str(depth),),defines={'QUEUE_DEPTH':depth},timeout=120)
        assert 'MIRRORED_REQUEST_QUEUE_PASS' in (model/'test.log').read_text()
        if depth==4:
            r=subprocess.run([str(model/'run'),'--corrupt-sidecar'],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
            (model/'negative.log').write_text(r.stdout+r.stderr)
            assert r.returncode!=0 and 'mirrored queue complete owner payload parity' in r.stdout+r.stderr
        results.append({'depth':depth,'log_sha256':sha(model/'test.log')})
    assert before=={str(p.relative_to(common.ROOT)):sha(p) for p in files}
    (out/'receipt.json').write_text(json.dumps(dict(status='PASS_QUEUE_COMPONENT_ONLY',source_sha256=before,gsim_sha256=sha(a.gsim),cases=results,full_adapter_and_physical_timing='UNVERIFIED'),indent=2)+'\n')
if __name__=='__main__':main()
