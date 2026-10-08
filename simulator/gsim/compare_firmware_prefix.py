#!/usr/bin/env python3
"""Compare completed fixed endpoints without claiming firmware boot completion."""
import argparse,hashlib,json,struct
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def validate(path):
    record=json.loads(path.read_text());assert record['status']=='COMPLETE_FIXED_ENDPOINT_PREFIX'
    assert record['endpoint_cycles']==1000000 and record['snapshot']['cycles']==1000000 and not record['complete_uboot_pass']
    parent=Path(record['model_receipt']);assert sha(parent)==record['model_receipt_sha256']
    assert json.loads(parent.read_text())['status'].startswith('PASS_FPGA_NEXT_BOARD')
    for p,digest in {**record['inputs'],**record['model_artifacts']}.items():assert sha(Path(p))==digest,p
    for name,digest in record['artifacts'].items():assert sha(path.parent/name)==digest,name
    data=(path.parent/'retired.trace').read_bytes();assert len(data)==24*record['snapshot']['commits']
    assert hashlib.sha256(data).hexdigest()==record['retirement_trace_sha256']
    pcHash=14695981039346656037;last=None;n=0
    for cycle,lane,pc in struct.iter_unpack('<QQQ',data):
        assert record['snapshot']['observation_begin']<=cycle<1000000 and lane<2 and not(pc&1)
        assert last is None or (cycle,lane)>last
        last=(cycle,lane);n+=1
        for b in range(8):pcHash=((pcHash^((pc>>(8*b))&255))*1099511628211)&((1<<64)-1)
        lastPc=pc
    assert n==record['snapshot']['commits'] and lastPc==record['snapshot']['last_pc']
    assert pcHash==record['snapshot']['pc_trace_fnv1a64']
    return record,data

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--reference',type=Path,required=True);ap.add_argument('--selected',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    a,x=validate(args.reference.resolve());b,y=validate(args.selected.resolve())
    assert a['guest_sha256']==b['guest_sha256']=='5addbabefc52bc37a40a62a64f7d819b57dc09f1cb5af094434d598f33023504'
    assert a['elf_sha256']==b['elf_sha256']=='613b842f33007118c4a795ebf56dbd0b981b814b3f5c42e8eea0eb960e1b94bc'
    assert [v for v in a['build_command'] if v.startswith('-D')]==[v for v in b['build_command'] if v.startswith('-D')]
    def sources(r):return {Path(k).name:v for k,v in r['inputs'].items()}
    sa,sb=sources(a),sources(b)
    for name in sa.keys()&sb.keys():
        if name!='run.py':assert sa[name]==sb[name],name
    equality={'retirement_event_trace':x==y,'snapshot':a['snapshot']==b['snapshot'],'trap_histogram':a['trap_lines']==b['trap_lines'],
        'backing_digest_and_sentinel':a['backing_lines']==b['backing_lines']}
    result={'status':'MATCHED_BOUNDED_FIRMWARE_PREFIX' if all(equality.values()) else 'BOUNDED_PREFIX_DIFFERENCE',
        'reference':{'receipt':str(args.reference.resolve()),'sha256':sha(args.reference),'wall_seconds':a['seconds']},
        'selected':{'receipt':str(args.selected.resolve()),'sha256':sha(args.selected),'wall_seconds':b['seconds']},
        'equality':equality,'fixed_endpoint':1000000,'guest_sha256':a['guest_sha256'],'retirement_trace_sha256':a['retirement_trace_sha256'],
        'reference_snapshot':a['snapshot'],'selected_snapshot':b['snapshot'],'trap_lines':a['trap_lines'],'backing_lines':a['backing_lines'],
        'complete_uboot_pass':False,'limits':a['limits'],
        'comparison_source':{'path':str(Path(__file__).resolve()),'sha256':sha(Path(__file__).resolve())}}
    if x!=y:
        for index,(left,right) in enumerate(zip(struct.iter_unpack('<QQQ',x),struct.iter_unpack('<QQQ',y))):
            if left!=right:result['first_trace_difference']={'record':index,'reference':left,'selected':right};break
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'receipt':str(args.output.resolve()),'sha256':sha(args.output),'equality':equality},indent=2))
if __name__=='__main__':main()
