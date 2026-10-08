#!/usr/bin/env python3
"""Audit frozen emitted bridge storage; not synthesis/resource/timing signoff."""
import argparse,hashlib,json,re
from pathlib import Path

def inspect(path):
    text=path.read_text();modules=re.split(r'(?m)^\s*(?:(?:public|private)\s+)?module\s+',text)
    lanes=[s for s in modules[1:] if re.match(r'TileLinkAxi4BurstBridge(?:_\d+)?\s*:',s)]
    result=[]
    for s in lanes:
        payload=re.findall(r'cmem payload : UInt<([0-9]+)>\[([0-9]+)\]',s)
        reads=len(re.findall(r'\bread\s+mport\s+\S+\s*=\s*payload\[',s))
        writes=len(re.findall(r'\bwrite\s+mport\s+\S+\s*=\s*payload\[',s))
        assert len(payload)==reads==writes==1 and not re.search(r'\breg(?:reset)?\s+(readData|writeData)\s*:',s)
        bits,depth=map(int,payload[0]);result.append({'bits':bits,'entries':depth,'read_ports':reads,'write_ports':writes})
    token=[{'bits':int(b),'entries':int(n)} for b,n in re.findall(r'cmem ram : UInt<([0-9]+)>\[([0-9]+)\]',text)]
    return {'fir_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'lanes':result,'token_memories':token,
            'slot_payload_bits':sum(r['bits']*r['entries'] for r in result),
            'token_payload_bits':sum(r['bits']*r['entries'] for r in token)}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('baseline',type=Path);ap.add_argument('candidate',type=Path);ap.add_argument('output',type=Path);args=ap.parse_args()
    a,b=inspect(args.baseline),inspect(args.candidate)
    assert len(a['lanes'])==len(b['lanes'])==4
    assert a['slot_payload_bits']==b['slot_payload_bits']==4608
    assert a['token_payload_bits']==b['token_payload_bits']==8
    report={'status':'PASS','scope':'selected 4/2/16 CHIRRTL storage shape only; no mapped LUT/FF/BRAM or timing claim',
            'baseline':a,'candidate':b}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
