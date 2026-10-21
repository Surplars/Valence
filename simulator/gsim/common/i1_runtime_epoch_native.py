#!/usr/bin/env python3
"""Real I1/private-cache/Home held-epoch test; single clock, no clock switch claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
ROOT=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--iverilog',type=Path,required=True)
    p.add_argument('--vvp',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve()
    if out.exists():p.error('fresh output directory required')
    for tool in (a.iverilog,a.vvp):
        if not tool.is_file():p.error('existing native tool required: '+str(tool))
    out.mkdir(parents=True)
    tb=Path(__file__).with_name('i1_runtime_epoch_tb.sv')
    paths=sorted((ROOT/'src/main/scala').rglob('*.scala'))+[
        ROOT/'src/test/scala/platform/CommonI1RuntimeEpochMain.scala',tb,Path(__file__).resolve()]
    sources={str(x.relative_to(ROOT)):sha(x) for x in paths}
    record=dict(status='RUNNING',scope='real full I1 + private caches + Home/fabric; single clock, internal RAM; no AON CDC, clock gating, PLL, DDR or physical signoff',
        source_sha256=sources,tools={str(x.resolve()):sha(x) for x in (a.iverilog,a.vvp)},cases=[])
    def run(command,name,limit):
        start=time.monotonic()
        with (out/(name+'.log')).open('w') as log:
            r=subprocess.run([str(x) for x in command],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=limit)
        record['cases'].append(dict(name=name,command=[str(x) for x in command],returncode=r.returncode,elapsed_seconds=time.monotonic()-start))
        return r.returncode,(out/(name+'.log')).read_text()
    try:
        rtl=out/'rtl'
        rc,log=run(['mill','--no-server','IonSoC.test.runMain','platform.CommonI1RuntimeEpochNativeMain',rtl],'emit',300)
        if rc:raise RuntimeError('real fixture emission failed')
        files=sorted(rtl.glob('*.sv'))
        if not files or not any('$fatal' in x.read_text() for x in files):raise RuntimeError('missing inline assertions')
        record['rtl_sha256']={x.name:sha(x) for x in files}
        binary=out/'sim.vvp'
        rc,log=run([a.iverilog,'-g2012','-s','i1_runtime_epoch_tb','-o',binary,*files,tb],'compile',300)
        if rc:raise RuntimeError('native compile failed')
        rc,log=run([a.vvp,binary],'positive',900)
        if rc or 'I1_RUNTIME_EPOCH_PASS' not in log:raise RuntimeError('real tile/fabric epoch test failed')
        rc,log=run([a.vvp,binary,'+wrong-oracle'],'wrong-oracle',180)
        if not rc or 'independent load data oracle' not in log:raise RuntimeError('negative data oracle not rejected')
        if sources!={str(x.relative_to(ROOT)):sha(x) for x in paths}:raise RuntimeError('source drift during run')
        record['status']='PASS'
    except BaseException as e:
        record.update(status='FAIL',error=str(e));raise
    finally:
        record['logs_sha256']={x.name:sha(x) for x in out.glob('*.log')}
        (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
if __name__=='__main__':main()
