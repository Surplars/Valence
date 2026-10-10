#!/usr/bin/env python3
"""Actual-candidate trace mutation controls, run only after a new positive trace exists."""
import argparse,copy
from contract import *
import proof_trace

def verify(folder,out):
 folder=Path(folder);out=Path(out);require(not out.exists(),'fresh proof control namespace');out.mkdir()
 r=read(folder/'receipt.json');require(r['side']=='on' and r['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN','new candidate functional result required')
 raw=folder/'positive.proof.jsonl';require(sha(raw)==r['artifacts'][raw.name],'original candidate trace drift')
 rows=[proof_trace.decode(x)for x in raw.open()];n=sum(x['event']=='result'and x['inserted']for x in rows);require(n>0,'positive inserted proofs needed; no fake zero-mutation control')
 report=[]
 for name,change in [('same_index_new_tag',lambda x:x.__setitem__('tag',(x['tag']+1)%2**64)),('wrong_index',lambda x:x.__setitem__('index',x['index']^1)),('wrong_epoch',lambda x:x.__setitem__('epoch',(x['epoch']+1)%2**32)),('wrong_pa_line',lambda x:x.__setitem__('pa',x['pa']^64)),('permission_not_allowed',lambda x:x.__setitem__('allowed',0)),('not_inserted_owner',lambda x:x.__setitem__('ownermatches',0)),('acceptance_not_next_edge',lambda x:x.__setitem__('accepted_cycle',x['cycle']))]:
  edited=copy.deepcopy(rows)
  for x in edited:
   if x['event']=='result'and x['inserted']:change(x)
  p=out/(name+'.jsonl');p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n'for x in edited))
  try:proof_trace.validate(p,folder/'positive.canonical.jsonl',(folder/'positive.log').read_text(),r['result'],r['window_trace'])
  except RuntimeError as e:report.append(dict(name=name,mutation_count=n,rejected=True,reason=str(e),sha256=sha(p)))
  else:raise RuntimeError('proof control escaped '+name)
 result=dict(status='PASS_ACTUAL_TRACE_IDENTITY_PERMISSION_EDGE_NEGATIVES',source_trace_sha256=sha(raw),candidate_receipt_sha256=sha(folder/'receipt.json'),DUT_reexecuted=False,controls=report);save(out/'receipt.json',result,True);return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--case',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(verify(a.case,a.out),indent=2))
