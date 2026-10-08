#!/usr/bin/env python3
"""Qualify the inherited I-cache held-hit correction separately from data packing."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
import run as common

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);a=ap.parse_args()
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',
        common.HERE/'config/toolchain.json',common.ROOT/'build.mill',common.HERE/'harness/instruction_line_cache.cpp',
        common.HERE/'harness/instruction_hit_stability.cpp']
    def hashes(): return {str(p.relative_to(common.ROOT)):sha(p) for p in paths}
    report={'status':'RUNNING','source_sha256':hashes(),'cases':{},'packing_enabled':False,
        'fix_commit':'dec7d8e','scope':'held-response correctness and first-cycle/II behavior; no physical timing claim'}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    try:
        gsim,cxx=common.setup(False)
        for words,prefetch in ((2,False),(2,True),(4,True)):
            name=f'packet{words}-prefetch{int(prefetch)}'
            parameters=('prefetch' if prefetch else 'off',words,'lines=512','--banked-cache-tags','compact-tags',
                '--ram-base=2149580800','--ram-bytes=2147483648')
            defines={'PACKET_WORDS':words,'CACHE_LINES':512,'CACHE_BASE':'2149580800ULL','COMPACT_TAG_TEST':1}
            if prefetch: defines['PREFETCH_ENABLED']=1
            d=common.test(gsim,cxx,f'{a.tag}/{name}','ooo.InstructionLineCacheGsimMain',
                'InstructionLineCacheGsim','instruction_hit_stability.cpp',parameters=parameters,defines=defines)
            initial_sha=sha(d/'run')
            neg=subprocess.run([d/'run','--bypass-hit-snapshot'],capture_output=True,text=True,timeout=60,env=env)
            (d/'broken-snapshot.log').write_text(neg.stdout+neg.stderr)
            assert neg.returncode!=0 and 'held-hit immutable byte oracle mismatch' in neg.stderr
            assert sha(d/'run')==initial_sha
            report['cases'][name]={'parameters':parameters,'defines':defines,'log':(d/'test.log').read_text(),
                'broken_snapshot_negative':'PASS','model_directory':str(d.relative_to(common.ROOT)),
                'artifacts_sha256':{p.name:sha(p) for p in d.iterdir() if p.is_file()}}
            (out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
            assert hashes()==report['source_sha256'],'source drift'
        report['status']='PASS'
    except BaseException as error: report['status']='FAIL';report['error']=str(error);raise
    finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
