#!/usr/bin/env python3
"""Audit normalized fixed-profile frontend payload CE dependencies, not physical timing."""
import argparse,hashlib,json,re
from pathlib import Path
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(path, override=None):
 text=path.read_text() if override is None else override
 equations={}
 for match in re.finditer(r'^\s*(?:(?:wire|logic|automatic logic)\s+(?:\[[^\]]+\]\s*)*)?(?:assign\s+)?([A-Za-z_$][\w$]*)\s*=\s*(.*?);',text,re.M|re.S):
  name,expr=match.groups()
  if name in equations and equations[name]!=expr:raise ValueError('ambiguous combinational assignment: '+name)
  equations[name]=expr
 registers=set(re.findall(r'^\s*reg\s+(?:\[[^\]]+\]\s*)*([\w$]+)',text,re.M))
 ports=set(re.findall(r'\bio_\w+',text.split(');',1)[0]))
 internals=set(re.findall(r'^\s*(?:wire|logic|automatic logic)\s+(?:\[[^\]]+\]\s*)*([\w$]+)',text,re.M))
 def leaves(expr,visited=frozenset()):
  result=set()
  expr=re.sub(r"\b\d+'[sS]?[hHdDbBoO][0-9a-fA-F_xXzZ?]+",'',expr)
  for name in re.findall(r'[A-Za-z_$][\w$]*',expr):
   if name in visited:raise ValueError('combinational cycle: '+name)
   if name in equations and name not in registers:result |= leaves(equations[name],visited|{name})
   else:
    if name not in registers and name not in ports:raise ValueError('unresolved internal alias: '+name)
    result.add(name)
  return result
 groups=[]
 for match in re.finditer(r'^    if \(([^\n]+)\) begin\n((?:(?!^    end).)*?)^    end',text,re.M|re.S):
  condition,body=match.groups()
  targets=re.findall(r'^      (words_\d+_\d+) <= io_memory_response_bits;',body,re.M)
  if targets:
   if re.search(r'\bif\b|\belse\b|\bbegin\b|\bend\b',body):raise ValueError('nested payload block')
   groups.append({'targets':targets,'condition':condition,'dependencies':sorted(leaves(condition))})
 targets=[n for g in groups for n in g['targets']]
 declared=sorted(n for n in registers if re.fullmatch(r'words_\d+_\d+',n))
 assert sorted(targets)==declared and len(targets)==32
 assert len(re.findall(r'words_\d+_\d+ <=',text))==32
 valid=[]
 for match in re.finditer(r'^\s*(valid_\d+_\d+) <=\s*(.*?);',text,re.M|re.S):
  name,expr=match.groups()
  if expr=="1'h0":continue
  dep=leaves(expr)
  assert 'io_invalidate' in dep and 'pendingStale' in dep, name+' lost validity gating'
  valid.append(name)
 assert sorted(valid)==sorted(n for n in registers if re.fullmatch(r'valid_\d+_\d+',n)) and len(valid)==32
 return {'sv_sha256':hashlib.sha256(text.encode()).hexdigest(),'validity_gates_checked':len(valid),'groups':groups,'word_payload_bits':32*64,
  'invalidate_dependent_groups':sum('io_invalidate' in g['dependencies'] for g in groups),
  'pending_stale_dependent_groups':sum('pendingStale' in g['dependencies'] for g in groups)}

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--baseline',type=Path,required=True)
 parser.add_argument('--candidate',type=Path,required=True)
 parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args()
 base,new=args.baseline,args.candidate
 a,b=audit(base),audit(new)
 assert a['invalidate_dependent_groups']==32 and b['invalidate_dependent_groups']==0
 assert a['pending_stale_dependent_groups']==32 and b['pending_stale_dependent_groups']==32
 mutant=new.read_text().replace('_GEN_12 =', '_GEN_12 = {48{io_invalidate}} &', 1)
 assert mutant != new.read_text()
 assert audit(new,mutant)['invalidate_dependent_groups']==32
 unresolved=new.read_text().replace('_GEN_12 =', '_GEN_12_missing =', 1)
 try:
  audit(new,unresolved)
  raise AssertionError('missing packed alias was not rejected')
 except ValueError as error:
  assert 'unresolved internal alias: _GEN_12' in str(error)
 valid_mutant=new.read_text().replace('automatic logic _GEN_65 = ~pendingStale & ~io_invalidate;', 'automatic logic _GEN_65 = ~io_invalidate;', 1)
 assert valid_mutant!=new.read_text()
 try:
  audit(new,valid_mutant)
  raise AssertionError('validity mutation was not rejected')
 except AssertionError as error:
  assert 'lost validity gating' in str(error)
 for result in (a,b):
  sets={}
  for group in result['groups']:
   members=group.pop('dependencies')
   identity=hashlib.sha256(json.dumps(members,separators=(',',':')).encode()).hexdigest()
   sets[identity]=members
   group['dependency_set']=identity
  result['dependency_sets']=sets
 r={'status':'PASS_SCOPED_NORMALIZED_SV_CE_DEPENDENCY','baseline':a,'candidate':b,
  'script_sha256':digest(Path(__file__)),'negative_controls':['packed_alias_invalidate_detected','missing_alias_rejected','lost_validity_stale_gate_rejected'],
  'limits':['Only combinational dependencies inside normalized SynchronousFetch; registers are timing boundaries','Valid installation still contains stale/invalidate gating; behavior is independently tested','No mapped FPGA fanout, setup/hold or routed path claim']}
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps(r,indent=2)+'\n')
 print(r['status'],a['invalidate_dependent_groups'],'->',b['invalidate_dependent_groups'])

if __name__ == "__main__":
 main()
