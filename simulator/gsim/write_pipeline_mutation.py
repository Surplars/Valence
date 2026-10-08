#!/usr/bin/env python3
"""Required-failing RTL ownership mutation, derived from a frozen passing FIR.
The original RTL/source is never edited. This bypasses all four new retirement
qualifiers in a separate generated model and must reproduce stale-token failure.
"""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import run as common

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--tag',required=True)
    args=ap.parse_args(); original=args.input.resolve();out=common.BUILD/('write-pipeline-mutation-'+args.tag)
    out.mkdir(parents=True,exist_ok=False)
    text=original.read_text()
    mutated,count=re.subn(r'(    connect dispatchRetired\[[0-3]\], )_dispatchRetired_T_[0-9]+',r'\g<1>UInt<1>(0h1)',text)
    assert count==4,('expected four selected-slot qualifiers',count)
    fir=out/'TileLinkAxi4Bridge.fir';fir.write_text(mutated)
    report={'status':'RUNNING','original_fir':str(original),'original_sha256':sha(original),
        'mutated_sha256':sha(fir),'mutation':'force four dispatchRetired bits to true; original source and FIR unchanged'}
    try:
        gsim=common.SOURCE/'build/gsim/gsim';cxx,_=common.compiler()
        common.run([gsim,'--threads=1',f'--dir={out}',fir],log=out/'generate.log')
        exe=out/'run';common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-I'+str(out),*sorted(out.glob('TileLinkAxi4Bridge[0-9]*.cpp')),
            common.HERE/'harness/tilelink_axi4_write_pipeline.cpp','-ldl','-o',exe],log=out/'compile.log')
        result=subprocess.run([exe,'--denied-tail'],capture_output=True,text=True,timeout=120,
            env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        output=result.stdout+result.stderr;(out/'negative.log').write_text(output)
        assert result.returncode!=0 and 'write data FIFO lost its live owner' in output,output
        assert sha(original)==report['original_sha256'],'original FIR drift'
        report.update(status='PASS',negative_returncode=result.returncode,negative_log=output)
    except BaseException as e:report.update(status='FAIL',error=str(e));raise
    finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
