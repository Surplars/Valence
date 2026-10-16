#!/usr/bin/env python3
"""Exact-width mapped queue boundary comparison; no placed timing claim."""
import argparse, collections, hashlib, json, os, subprocess
from pathlib import Path
import run as common

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True);ap.add_argument('--no-wide-lut',action='store_true');ap.add_argument('--firtool',type=Path,required=True);ap.add_argument('--yosys',type=Path,required=True);ap.add_argument('--sv2v',type=Path,required=True);a=ap.parse_args()
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    sources=sorted((common.ROOT/"src").rglob("*.scala"))+[Path(__file__),common.HERE/"run.py"]
    before={str(p.relative_to(common.ROOT)):sha(p) for p in sources}
    results={}
    for mode in ('0','1'):
        d=out/mode;d.mkdir()
        common.run(['mill','-i','IonSoC.test.runMain','ooo.MirroredRequestQueueMapMain',d,mode],log=d/'elaborate.log')
        common.run([a.firtool,d/'MirroredRequestQueueMap.fir','--verilog','--disable-layers=Verification','-o',d/'queue.sv'],log=d/'firtool.log')
        with (d/'queue.v').open('w') as f:subprocess.run([str(a.sv2v),str(d/'queue.sv')],stdout=f,check=True)
        common.run([a.yosys,'-Q','-T','-p',f'read_verilog {d}/queue.v; hierarchy -top MirroredRequestQueueMap; chformal -remove; synth_xilinx -family xcu -top MirroredRequestQueueMap -flatten -noiopad {"-nowidelut" if a.no_wide_lut else ""}; write_json {d}/mapped.json; stat'],log=d/'yosys.log')
        common.run([a.yosys,'-Q','-T','-p',f'read_verilog {d}/queue.v; hierarchy -top MirroredRequestQueueMap; chformal -remove; prep -top MirroredRequestQueueMap -flatten; memory_map; opt; sat -seq 2 -set-at 1 reset 1 -prove-skip 1 -prove io_count 0 -prove io_deq_valid 0 -prove io_enq_ready 1 -verify'],log=d/'reset-proof.log')
        m=json.loads((d/'mapped.json').read_text())['modules']['MirroredRequestQueueMap'];drivers={}
        for name,c in m['cells'].items():
            for port,direction in c['port_directions'].items():
                if direction=='output':
                    for b in c['connections'][port]:drivers[b]=(name,c['type'])
        bits=m['ports']['io_deq_bits']['bits'];types=collections.Counter(drivers.get(b,('',str(b)))[1] for b in bits)
        if mode=='1':
            selected=set(range(486,670))|{139}
            assert all(drivers[b][1] in ('FDRE','FDSE','FDCE','FDPE') for i,b in enumerate(bits) if i in selected),'selected head is not registered'
            assert sum(types[t] for t in ('FDRE','FDSE','FDCE','FDPE'))==185,'projection width differs'
        results[mode]=dict(width=len(bits),payload_output_driver_types=dict(types),cells=dict(collections.Counter(c['type'] for c in m['cells'].values())),mapped_sha256=sha(d/'mapped.json'))
    assert before=={str(p.relative_to(common.ROOT)):sha(p) for p in sources}
    (out/'receipt.json').write_text(json.dumps(dict(status='PASS_MAPPED_QUEUE_BOUNDARY_ONLY',modes=results,source_sha256=before,tools={str(p):sha(p) for p in (a.firtool,a.yosys,a.sv2v)},reset_proof='Yosys sequential SAT: asserted reset overrides unconstrained push/pop, count=0 valid=0 ready=1 next cycle',physical_timing='UNMEASURED',downstream_store_and_PMP_cone='NOT_INCLUDED'),indent=2)+'\n')
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
