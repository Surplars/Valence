#!/usr/bin/env python3
"""Verify bound member provenance, input hashes and required coverage without execution."""
import argparse,hashlib,json,re
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(mapping,model):
    doc=json.loads(mapping.read_text());header=model/'BoardSocGsim.h';fir=model/'BoardSocGsim.fir'
    assert doc['header_sha256']==sha(header),('header hash mismatch',mapping)
    assert doc['fir_sha256']==sha(fir),('FIR hash mismatch',mapping)
    hl=header.read_text().splitlines();fl=fir.read_text().splitlines();count=0;members=set()
    for field in doc['fields']:
        if field['status']!='PROVEN':
            assert not field['required'],('required field unbound',field['target']);continue
        assert field['width']<=128,('unbounded output scalar',field['target'])
        assert '$NEXT' not in field['cpp'],('next-state sample forbidden',field['target'])
        for proof in field['proof']:
            if 'symbol' in proof:
                assert '$NEXT' not in proof['symbol']
                line=hl[proof['header_line']-1]
                assert re.search(r'\b'+re.escape(proof['symbol'])+r'(?:\[|;)',line),('member mismatch',proof)
                assert line.endswith(f"// width = {proof['width']}, lineno = {proof['fir_line']}"),('origin mismatch',proof)
                assert 0<proof['fir_line']<=len(fl)
                members.add(proof['symbol'])
            else:
                assert proof['fir']==fl[proof['fir_line']-1].strip(),('FIR expression mismatch',proof)
        count+=1
    return dict(mapping=str(mapping),proven_fields=count,exact_current_members=len(members),optional_unbound=[x['target'] for x in doc['fields'] if x['status']!='PROVEN'],status='SOURCE_PROVENANCE_PASS_NO_SIMULATION')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('mapping',nargs='+',type=Path);a=p.parse_args()
    print(json.dumps([verify(x,a.model) for x in a.mapping],indent=2))
