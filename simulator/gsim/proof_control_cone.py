#!/usr/bin/env python3
"""Single-cycle functional dependency audit of actual fixed-GSIM lowered graphs.

REG_DST assignment trees contain data and conditional/hold enables together.
Stop at REG_SRC, so this does not call a sequential influence a combinational path.
Assertions, test observers and dead aliases are not register-write targets.
"""
import argparse,collections,hashlib,json,re
from pathlib import Path

PATTERNS={
 'reserveSystem':r'^backend\$(?:reserveSystem|_reserveSystem_\w+)$',
 'headTrapRequest':r'^backend\$(?:headTrapRequest|_headTrapRequest_\w+)$',
 'accepted_clear':r'^backend\$(?:proofOwnerClear|_proofOwnerClear_\w+)$|^backend\$ledger\$io\$\$(?:commit|renamed)\$\$valid|^backend\$ledger\$io\$\$(?:recoveryAccepted|headTrap\$\$accepted|headSystem\$\$accepted)',
 'actual_start':r'^backend\$(?:memoryIssued|_memoryIssued_T(?:_\d+)?)$|^backend\$lsu\$io\$\$start\$\$(?:valid|ready)$',
 'generic_capacity':r'^backend\$lsu\$(?:capacity|io\$\$candidateIssueAvailable)$',
 'generic_bound_store':r'boundHeadStoreOverlap|^backend\$lsu\$io\$\$start\$\$bits\$\$canonicalStoreEpoch\$\$valid$',
 'prefetch_busy':r'^io\$\$(?:control\$\$prefetchBusy|externalPrefetchBusy)$|^backend\$io\$\$externalPrefetchBusy$',
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(directory,inject=False):
 before=next(directory.glob('*_0AfterSplitNodes.json'));after=next(directory.glob('*_1AliasAnalysis.json'))
 initial=json.loads(before.read_text());graph=json.loads(after.read_text())
 nodes={n['name']:n for n in graph['nodes']};aliases={}
 for n in initial['nodes']:
  trees=n.get('assignTrees',[])
  if len(trees)!=1:continue
  tree=trees[0];items={x['id']:x for x in tree['nodes']};root=items[tree['root']]
  if root.get('op')=='OP_EMPTY' and root.get('node')!=n['name'] and not root.get('children'):
   aliases[n['name']]=root.get('node')
 def representative(name):
  seen=set()
  while name not in nodes and name in aliases and name not in seen:
   seen.add(name);name=aliases[name]
  return name if name in nodes else None
 forbidden={k:set() for k in PATTERNS}
 for name in {n['name'] for n in initial['nodes']}|set(nodes):
  for kind,pattern in PATTERNS.items():
   if re.search(pattern,name):
    resolved=representative(name)
    if resolved:forbidden[kind].add(resolved)
 rev=collections.defaultdict(set)
 for a,b in graph['edges']:rev[b].add(a)
 targets=sorted(n for n,x in nodes.items() if 'backend$pendingStoreProof$' in n and x['type']=='NODE_REG_DST')
 assert targets,'missing real bank register-write targets'
 required=['state','bound','records','selectedValid','translatedValid','loadValid']
 for family in required:assert any('$'+family in n for n in targets),('missing register family',family)
 if inject:
  assert forbidden['prefetch_busy'],'missing negative source'
  rev[targets[0]].add(next(iter(forbidden['prefetch_busy'])))
 def walk(starts):
  todo=collections.deque(starts);seen=set();parent={n:None for n in starts}
  while todo:
   n=todo.popleft()
   if n in seen:continue
   seen.add(n)
   if nodes[n]['type']=='NODE_REG_SRC':continue
   for source in sorted(rev[n]):
    assert source in nodes,('edge to missing node',source)
    if source not in parent:parent[source]=n
    todo.append(source)
  return seen,parent
 seen,parent=walk(targets)
 hits={k:sorted(v&seen) for k,v in forbidden.items()}
 witnesses={}
 for kind,names in hits.items():
  if names:
   path=[];n=names[0]
   while n is not None:path.append(n);n=parent[n]
   witnesses[kind]=path
 per_target={}
 for target in targets:
  ancestry,_=walk([target]);per_target[target]=dict(ancestors=len(ancestry),
    forbidden={k:sorted(v&ancestry) for k,v in forbidden.items() if v&ancestry})
 return dict(graph_sha256=sha(after),pre_alias_sha256=sha(before),register_write_targets=targets,
   target_count=len(targets),register_boundary='NODE_REG_SRC',
   functional_scope='all bank REG_DST assignment-tree data/conditional/hold inputs, including query/load valids',
   graph_nodes=len(nodes),ancestor_count=len(seen),forbidden_hits=hits,witnesses=witnesses,
   per_target=per_target,raw_input_leaves=sorted(n for n in seen if nodes[n]['type']=='NODE_INP'),
   register_read_boundaries=sorted(n for n in seen if nodes[n]['type']=='NODE_REG_SRC'))
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True)
 ap.add_argument('--output',type=Path,required=True);ap.add_argument('--source-root',type=Path,required=True)
 ap.add_argument('--source-receipt',type=Path,required=True)
 a=ap.parse_args();receipt=json.loads(a.source_receipt.read_text());inputs=receipt['source_inputs']
 checked={n:v for n,v in inputs.items() if n.startswith('src/main/scala/')}
 assert all(sha(a.source_root/n)==v for n,v in checked.items()),'production source differs from verified backend receipt'
 baseline=audit(a.baseline);candidate=audit(a.candidate);negative=audit(a.candidate,True)
 assert baseline['forbidden_hits']['prefetch_busy'],'baseline negative failed to detect real cache busy feedback'
 assert baseline['forbidden_hits']['reserveSystem'] and baseline['forbidden_hits']['accepted_clear']
 assert not any(candidate['forbidden_hits'].values()),('forbidden functional reentry',candidate['witnesses'])
 assert negative['forbidden_hits']['prefetch_busy'],'injected edge negative did not fail'
 result=dict(status='PASS_SCOPED_FUNCTIONAL_CONE_AUDIT',production_sources_checked=len(checked),
   source_receipt_sha256=sha(a.source_receipt),candidate=candidate,baseline_negative=baseline,
   injected_edge_negative_rejected=True,
   limitations='combinational structural audit of emitted backend graph; no temporal proof, mapped timing, CDC or board qualification')
 with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps(dict(status=result['status'],targets=candidate['target_count'],
   forbidden_hits=candidate['forbidden_hits'],baseline_categories=[k for k,v in baseline['forbidden_hits'].items() if v],
   injected_edge_negative_rejected=True,receipt_sha256=sha(a.output)),indent=2))
if __name__=='__main__':main()
