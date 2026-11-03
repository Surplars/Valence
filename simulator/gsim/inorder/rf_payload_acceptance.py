#!/usr/bin/env python3
"""Independent RF collision/hold/reset gate for the unowned-payload RTL optimization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import run as common
ROOT=Path(__file__).resolve().parents[3]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'build') or os.environ.get('VALENCE_WORK_ROOT')!=str(ROOT):
        parser.error('source local env; fresh repository build/ output required')
    files=[ROOT/'src/main/scala/core/inorder/SynchronousRegisterFile.scala',
           ROOT/'src/test/scala/inorder/FiveStageMain.scala',
           ROOT/'simulator/gsim/harness/five_stage_register_file.cpp',Path(__file__).resolve()]
    frozen={str(p.relative_to(ROOT)):sha(p) for p in files}
    output.mkdir(parents=True)
    receipt=dict(status='RUNNING',source_sha256=frozen,commands=[],samples=[])
    gsim,cxx=common.setup(False)
    paths=[Path(v.split(':',3)[3]) for v in json.loads((ROOT/'out/OrbitalI1/test/runClasspath.json').read_text())['value']]
    runtime=os.pathsep.join(str(p) for p in paths if p.exists())
    def save():(output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(cmd,folder,log,negative=False):
        cmd=list(map(str,cmd));receipt['commands'].append(dict(argv=cmd,log=str(folder/log)));save()
        with (folder/log).open('w') as stream:
            result=subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                                  env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(folder/log).read_text()
        if negative:
            if result.returncode==0 or 'independent synchronous RF oracle mismatch' not in text:
                raise RuntimeError('RF negative not independently rejected')
        elif result.returncode:raise RuntimeError('RF gate failed: '+str(folder/log))
        return text
    try:
        for width in [32,64]:
            folder=output/str(width);folder.mkdir()
            run(['java','-cp',runtime,'inorder.FiveStageRegisterFileMain',folder,width],folder,'emit.log')
            top='SynchronousRegisterFile'
            run([gsim,'--threads=1','--dir='+str(folder),folder/(top+'.fir')],folder,'generate.log')
            cpp=sorted(folder.glob(top+'[0-9]*.cpp'))
            run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                 '-DDUT_XLEN='+str(width),'-I'+str(folder),*cpp,files[2],'-o',folder/'run'],folder,'compile.log')
            text=run([folder/'run'],folder,'positive.log')
            if 'FIVE_STAGE_RF_PASS' not in text:raise RuntimeError('missing RF completion')
            run([folder/'run','--inject'],folder,'negative.log',True)
            receipt['samples'].append(dict(width=width,summary=text.strip(),negative_rejected=True));save()
            print(text.strip(),flush=True)
        for name,digest in frozen.items():
            if sha(ROOT/name)!=digest:raise RuntimeError('source drift: '+name)
        receipt['status']='PASS_RF_UNOWNED_PAYLOAD_INDEPENDENT_ARRAY_COLLISION_HOLD_RESET'
    except BaseException as error:
        receipt.update(status='FAIL',error=repr(error));raise
    finally:save()
    print(json.dumps(dict(status=receipt['status'],receipt=str(output/'receipt.json'))))


if __name__=='__main__':main()
