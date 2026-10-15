#!/usr/bin/env python3
"""Read existing pinned-GSIM graphs; scoped memory-request combinational ancestry."""
import argparse,collections,hashlib,json
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(directory):
 before=next(directory.glob('*_0AfterSplitNodes.json'));after=next(directory.glob('*_1AliasAnalysis.json'))
 g=json.loads(after.read_text());nodes={n['name']:n for n in g['nodes']};rev=collections.defaultdict(set)
 for a,b in g['edges']:rev[b].add(a)
 target='io$$memory$$request$$valid';assert nodes[target]['type']=='NODE_OUT'
 todo=collections.deque([target]);seen=set();parent={target:None}
 while todo:
  n=todo.popleft()
  if n in seen:continue
  seen.add(n)
  if nodes[n]['type']=='NODE_REG_SRC':continue
  for p in sorted(rev[n]):
   if p not in parent:parent[p]=n
   todo.append(p)
 def witness(n):
  if n not in seen:return []
  out=[]
  while n is not None:out.append(n);n=parent[n]
  return out
 return dict(pre_alias_sha256=sha(before),graph_sha256=sha(after),
  fir_sha256=sha(directory/'EthernetPacketDma.fir'),target=target,ancestor_count=len(seen),
  register_boundary='NODE_REG_SRC',txLength_in_request_cone='txLength' in seen,
  txWordCount_register_in_request_cone='txWordCount' in seen and nodes['txWordCount']['type']=='NODE_REG_SRC',
  txLength_path=witness('txLength'),txWordCount_path=witness('txWordCount'))
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for name in ['baseline','candidate','source-receipt','output']:ap.add_argument('--'+name,type=Path,required=True)
 a=ap.parse_args();receipt=json.loads(a.source_receipt.read_text())
 assert receipt['status']=='PASS_FOCUSED_TX_WORD_COUNT_AB_AND_STOP'
 b=audit(a.baseline);c=audit(a.candidate)
 for arm,item in [('baseline',b),('candidate',c)]:
  assert item['fir_sha256']==receipt['arms'][arm]['m2048-p4']['fir_sha256']
 assert b['txLength_in_request_cone'] and not b['txWordCount_register_in_request_cone']
 assert not c['txLength_in_request_cone'] and c['txWordCount_register_in_request_cone']
 result=dict(status='PASS_SCOPED_TX_COUNT_REQUEST_CONE_CUT',source_receipt_sha256=sha(a.source_receipt),
  baseline=b,candidate=c,
  limitations='direct maxFrame2048/posted4/credits4 lowered graph only; not temporal proof, mapped carry count, PPA or board qualification')
 with a.output.open('x') as h:json.dump(result,h,indent=2);h.write('\n')
 print(json.dumps(result,indent=2));print('AUDIT_SHA256',sha(a.output))
if __name__=='__main__':main()
