#!/usr/bin/env python3
"""Exact native delta: four operand selects; only comparator names/order may move."""
import argparse,hashlib,json,re
from pathlib import Path
from native_graph_helpers import ports,registers,assignments,cone

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tokens(s):return re.findall(r'''"(?:\\.|[^"\\])*"|[A-Za-z_]\w*|\d+'[s]?[bdhoBDHO][a-fA-F0-9_xzXZ]+|\d+|[^\s]''',s)
def inventory(root):return {p.name:sha(p) for p in root.glob('*.sv')}
def concat_parts(expr):
 assert expr.startswith('{') and expr.endswith('}')
 pieces=[];begin=1;depth=0
 for i,ch in enumerate(expr[1:-1],1):
  if ch in '({[':depth+=1
  elif ch in ')}]':depth-=1
  elif ch==',' and depth==0:pieces.append(expr[begin:i].strip());begin=i+1
 pieces.append(expr[begin:-1].strip());assert depth==0
 return pieces

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root.resolve()
 off,on=[root/s/'rtl' for s in ('off','on')];oldmap,newmap=inventory(off),inventory(on)
 assert oldmap.keys()==newmap.keys()
 changed=sorted(n for n in oldmap if oldmap[n]!=newmap[n]);assert changed==['IntegerBackend.sv'],changed
 old,new=[(r/'IntegerBackend.sv').read_text() for r in (off,on)]
 original_new=new
 renames={f'incoming_{side}_hits_{producer}{suffix}':f'dispatch{side.title()}_hits_{producer}{suffix}'
  for side in ('left','right') for producer in (0,1) for suffix in ('','_1')}
 comparison_evidence={}
 for before,after in renames.items():
  assert re.search(r'\b'+before+r'\b',new) and not re.search(r'\b'+after+r'\b',new)
  new=re.sub(r'\b'+before+r'\b',after,new)
 for name in renames.values():
  pattern=r'\bwire\s+'+name+r'\s*=\s*(.*?);'
  left,right=[re.search(pattern,t,re.S) for t in (old,new)]
  assert left and right and tokens(left[1])==tokens(right[1]),('forwarding comparison changed',name)
  comparison_evidence[name]=' '.join(tokens(left[1]))
  old=re.sub(pattern,'',old,count=1,flags=re.S);new=re.sub(pattern,'',new,count=1,flags=re.S)
 # Names are normalized; the only permitted functional edit removes the outer
 # memory?stored:forwarded term of each local registered operand copy.
 evidence={}
 beforeeq=assignments((off/'IntegerBackend.sv').read_text());aftereq=assignments(original_new)
 for lane in range(2):
  target=f'executionStages_{lane}_io_enq_bits'
  left,right=concat_parts(beforeeq[target]),concat_parts(aftereq[target])
  assert len(left)==len(right)==13
  assert tokens(' '.join(left[:-3]+left[-1:]))==tokens(' '.join(right[:-3]+right[-1:])), 'entry/forwardable changed'
  for operand,pos in [('left',-3),('right',-2)]:
   match=re.match(r'(\w+)\[10\]\s*\?\s*(_physicalFile_io_data_\d+)\s*:\s*(.*)',left[pos],re.S)
   assert match,('missing baseline memory select',lane,operand,left[pos])
   normalized=right[pos]
   for oldname,newname in renames.items():normalized=re.sub(r'\b'+oldname+r'\b',newname,normalized)
   assert tokens(match[3])==tokens(normalized),('forwarding/stored fallback changed',lane,operand)
   assert len(re.findall(r'\?',left[pos]))-len(re.findall(r'\?',right[pos]))==1
   # Memory bit remains in the entry, but not as the extra operand data select.
   assert not re.search(re.escape(match[1])+r'\[10\]',right[pos])
   evidence[f'lane{lane}_{operand}']={'before':left[pos],'after':right[pos],
    'removed_condition':match[1]+'[10]','stored_fallback':match[2],
    'width':64,'forwarding_expression_identical_after_identifier_rename':True,
    'off_cone':cone(left[pos],beforeeq),'on_cone':cone(right[pos],aftereq)}
  pattern=r'\bwire\s+\[590:0\]\s+'+target+r'\s*=\s*(.*?);'
  m=re.search(pattern,old,re.S);assert m
  replacement,n=re.subn(r'\b\w+\[10\]\s*\?\s*_physicalFile_io_data_\d+\s*:\s*','',m[1])
  assert n==2
  old=old[:m.start(1)]+replacement+old[m.end(1):]
 assert tokens(old)==tokens(new),'unreviewed native token change outside four selects and identical comparator relocation'
 state={};interfaces={}
 for name in oldmap:
  left,right=[(r/name).read_text() for r in (off,on)]
  assert registers(left)==registers(right),('state differs',name)
  sig=lambda t:tokens(t[t.index('module '):t.index(');')+2])
  assert sig(left)==sig(right),('module ports differ',name)
  state[name]={'declarations':len(registers(left)),'bits':sum(registers(left).values())}
  interfaces[name]=hashlib.sha256(' '.join(sig(left)).encode()).hexdigest()
 for module,instance in [('OwnerBankedPhysicalRegisterFile','physicalFile'),('RenameRob','ledger')]+[(r'IssueExecuteStage(?:_\d+)?',f'executionStages_{i}') for i in range(2)]:
  assert ports((off/'IntegerBackend.sv').read_text(),module,instance)==ports(original_new,module,instance),(module,instance)
 result={'status':'PASS_NATIVE_REGISTERED_OPERAND_SELECT_REMOVAL','native_modules':len(oldmap),'changed_modules':changed,
  'removed_select_sites':len(evidence),'removed_select_width_each':64,'scala_assignment_sites':2,'lanes':2,
  'native_exact_delta':'four memory-class operand selects only; eight identical ALU-hit wires renamed and relocated',
  'forwarding_comparators_before':len(comparison_evidence),'forwarding_comparators_after':len(comparison_evidence),
  'comparison_evidence':comparison_evidence,'operand_evidence':evidence,
  'all_other_native_tokens_identical_after_reviewed_normalization':True,'all_module_ports_identical':True,
  'prf_port_connections_identical':True,'ledger_and_stage_connections_identical':True,'all_declared_state_identical':True,
  'state':state,'interfaces':interfaces,'files':{'off':oldmap,'on':newmap},'audit_sha256':sha(__file__),
  'limitations':['Native RTL only; no mapped LUT, delay, slack, area or rank51 causal claim.',
   'Observer fixture uses five explicit inherited backend profile exceptions; no complete CPU/board qualification.',
   'Memory metadata remains in the entry; real forwarding, completion-credit and scheduling dependencies remain.']}
 (root/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
if __name__=='__main__':main()
