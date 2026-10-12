#!/usr/bin/env python3
"""Same four-site proof as the component, bound to actual inlined stage ports."""
import hashlib,importlib.util,re
from pathlib import Path
from native_graph_helpers import assignments,cone,ports,registers
ROOT=Path(__file__).resolve().parent
PINNED=ROOT/'components/registered_operands_native_audit.py'
assert hashlib.sha256(PINNED.read_bytes()).hexdigest()=='b26bf49693e947866e29562e545dd02b5311edc73a2aa9cde6e5e6bdfbf7f4c7'
spec=importlib.util.spec_from_file_location('pinned_component_operands',PINNED);component=importlib.util.module_from_spec(spec);spec.loader.exec_module(component)
tokens,concat_parts=component.tokens,component.concat_parts
RENAMES={f'incoming_{side}_hits_{producer}{suffix}':f'dispatch{side.title()}_hits_{producer}{suffix}'
 for side in ('left','right') for producer in (0,1) for suffix in ('','_1')}

def port_span(text,lane):
 pattern=r'\bIssueExecuteStage(?:_\d+)?\s+executionStages_'+str(lane)+r'\s*\('
 matches=list(re.finditer(pattern,text));assert len(matches)==1,('actual stage instance absent/ambiguous',lane)
 start=matches[0].end();end=text.index('\n  );',start)
 ports_=list(re.finditer(r'\.io_enq_bits\s*\(',text[start:end]));assert len(ports_)==1
 first=start+ports_[0].end();pos=first;depth=1
 while depth:
  depth+=(text[pos]=='(')-(text[pos]==')');pos+=1
 assert pos<=end
 return first,pos-1

def audit_integer(old,new):
 original_old,original_new=old,new;comparisons={};evidence={}
 for before,after in RENAMES.items():
  assert re.search(r'\b'+before+r'\b',new) and not re.search(r'\b'+after+r'\b',new)
  new=re.sub(r'\b'+before+r'\b',after,new)
 for name in RENAMES.values():
  pattern=r'\bwire\s+'+name+r'\s*=\s*(.*?);'
  left,right=[list(re.finditer(pattern,t,re.S)) for t in (old,new)]
  assert len(left)==len(right)==1 and tokens(left[0][1])==tokens(right[0][1]),('forwarding comparator changed',name)
  comparisons[name]=' '.join(tokens(left[0][1]));old=re.sub(pattern,'',old,count=1,flags=re.S);new=re.sub(pattern,'',new,count=1,flags=re.S)
 eq0,eq1=assignments(original_old),assignments(original_new)
 for lane in range(2):
  before=ports(original_old,r'IssueExecuteStage(?:_\d+)?',f'executionStages_{lane}')
  after=ports(original_new,r'IssueExecuteStage(?:_\d+)?',f'executionStages_{lane}')
  assert before.keys()==after.keys()
  assert {k:tokens(v) for k,v in before.items() if k!='io_enq_bits'}=={k:tokens(v) for k,v in after.items() if k!='io_enq_bits'},('other execution-stage connection changed',lane)
  left,right=concat_parts(before['io_enq_bits']),concat_parts(after['io_enq_bits'])
  assert len(left)==len(right)==13,('actual 591-bit enq field layout differs',lane)
  assert tokens(' '.join(left[:-3]+left[-1:]))==tokens(' '.join(right[:-3]+right[-1:])),('entry or forwardable changed',lane)
  for operand,pos in [('left',-3),('right',-2)]:
   match=re.fullmatch(r'(\w+)\[10\]\s*\?\s*(_physicalFile_io_data_\d+)\s*:\s*(.*)',left[pos],re.S)
   assert match,('baseline memory select absent',lane,operand)
   normalized=right[pos]
   for oldname,newname in RENAMES.items():normalized=re.sub(r'\b'+oldname+r'\b',newname,normalized)
   assert tokens(match[3])==tokens(normalized),('forwarding/stored fallback differs',lane,operand)
   assert len(re.findall(r'\?',left[pos]))-len(re.findall(r'\?',right[pos]))==1
   assert not re.search(re.escape(match[1])+r'\[10\]',right[pos])
   evidence[f'lane{lane}_{operand}']={'actual_endpoint':f'executionStages_{lane}.io_enq_bits','concat_position':pos,
    'width':64,'before':left[pos],'after':right[pos],'removed_condition':match[1]+'[10]',
    'stored_fallback':match[2],'off_cone':cone(left[pos],eq0),'on_cone':cone(right[pos],eq1)}
  first,last=port_span(old,lane)
  replacement,n=re.subn(r'\b\w+\[10\]\s*\?\s*_physicalFile_io_data_\d+\s*:\s*','',old[first:last])
  assert n==2,('not exactly two endpoint selects',lane,n)
  old=old[:first]+replacement+old[last:]
 assert tokens(old)==tokens(new),'unreviewed fullboard token change outside exact four operand sites and eight comparator relocations'
 for module,instance in [('OwnerBankedPhysicalRegisterFile','physicalFile'),('RenameRob','ledger')]:
  assert ports(original_old,module,instance)==ports(original_new,module,instance),(module,instance)
 assert registers(original_old)==registers(original_new),'backend state changed'
 return {'status':'PASS_FOUR_ACTUAL_ENQUEUE_OPERAND_SITES','removed_select_sites':4,'removed_select_width_each':64,
  'actual_enq_width':591,'actual_endpoints':['executionStages_0.io_enq_bits','executionStages_1.io_enq_bits'],
  'comparison_evidence':comparisons,'operand_evidence':evidence,'all_other_native_tokens_identical':True,
  'all_other_stage_connections_identical':True,'prf_and_ledger_connections_identical':True,
  'component_checker_sha256':hashlib.sha256(PINNED.read_bytes()).hexdigest(),
  'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
