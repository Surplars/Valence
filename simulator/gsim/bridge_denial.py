#!/usr/bin/env python3
"""Oversize TL denial/drain checks, independent of AXI buffer depth; bridge only."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
import run as common


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);ap.add_argument('--dry-run',action='store_true');args=ap.parse_args()
    cases=[(s,8,3) for s in (1,2,4,8)]+[(4,16,3),(4,8,4)]
    if args.dry_run: print(json.dumps(cases));return
    assert args.tag.replace('-','').isalnum()
    out=common.BUILD/('bridge-denial-'+args.tag);out.mkdir(parents=True,exist_ok=False)
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'harness/tilelink_axi4_outstanding.cpp']
    def hashes():return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report={'status':'RUNNING','source_sha256':hashes(),'cases':{},'scope':'bridge-only; no CPU/physical timing claim'}
    try:
        gsim,cxx=common.setup(False)
        for slots,burst,sizebits in cases:
            name=f's{slots}-b{burst}-z{sizebits}'
            target=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/name),'ooo.TileLinkAxi4OutstandingGsimMain',
                'TileLinkAxi4Bridge','tilelink_axi4_outstanding.cpp',parameters=(slots,burst,sizebits),
                defines={'MAX_BURST_BEATS':burst,'TL_SIZE_BITS':sizebits},timeout=180)
            log=(target/'test.log').read_text();assert 'OUTSTANDING_ALL_PASS' in log
            negatives=[('--bad-last','AXI read ID or RLAST mismatch'),
                ('--bad-id','AXI read ID or RLAST mismatch' if slots==1 else 'AXI R response has no live read owner'),
                ('--inject-data','independent TL data oracle mismatch')]
            if burst<16:negatives.append(('--bad-write-control','TL write burst changed control fields'))
            entry={'log':log,'negative':{}}
            for flag,anchor in negatives:
                r=subprocess.run([target/'run',flag],capture_output=True,text=True,timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                text=r.stdout+r.stderr;(target/(flag[2:]+'.log')).write_text(text)
                assert r.returncode!=0 and anchor in text,(name,flag,text[-1000:]);entry['negative'][flag]='PASS'
            report['cases'][name]=entry
            assert hashes()==report['source_sha256'],'source drift'
            (out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
        report['status']='PASS'
    except BaseException as e:
        report['status']='FAIL';report['error']=str(e);raise
    finally:
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
