#!/usr/bin/env python3
"""Exact paired native upper-bank WE delta; no timing or mapped area claim."""
import argparse,hashlib,json,re,difflib
from pathlib import Path
from native_graph_helpers import assignments,cone,ports,registers

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def clean(s):return re.sub(r'//[^\n]*|/\*.*?\*/','',s,flags=re.S)
def tokens(s):return re.findall(r"[A-Za-z_]\w*|\d+'[s]?[bdhoBDHO][a-fA-F0-9_xzXZ]+|\d+|[^\s]",clean(s))
def audit_slot(old, new, failure_diff=None):
 eq0,eq1=map(assignments,(old,new));banks={};normalizations={}
 inline_first='payloadWrite' not in eq1
 if inline_first:assert 'payloadWrite' in eq0
 rename_new,rename_old='_continuedPayloadWrite_T','_io_tl_a_ready_T_1'
 decoder_rename=rename_new in eq1 and rename_old not in eq1
 if decoder_rename:
  assert rename_old in eq0 and tokens(eq1[rename_new])==tokens(eq0[rename_old]), 'changed collection state decode'
  normalizations['identical_decoder_rename']={rename_new:rename_old}

 collect_name=rename_new if decoder_rename else rename_old
 assert tokens(eq1[collect_name])==tokens("state == 4'h1"), 'upper event collection decoder changed'
 assert tokens(eq1['io_axi_r_ready_0'])==tokens("state == 4'h3"), 'upper event read decoder changed'
 expected_event=collect_name+' & io_tl_a_valid & ~writeError | io_axi_r_ready_0 & io_axi_r_valid'
 assert tokens(eq1['continuedPayloadWrite'])==tokens(expected_event), 'upper continued/read event changed'
 event_proof={'actual':eq1['continuedPayloadWrite'],'expected':expected_event,
  'collect_state_decode':eq1[collect_name],'read_state_decode':eq1['io_axi_r_ready_0']}
 required_direct={'io_tl_a_bits_address','io_tl_a_bits_size','io_tl_a_bits_opcode'}
 for i in range(8):
  p0,p1=[ports(s,'payloadBanks_2x72',f'payloadBanks_{i}_ext') for s in (old,new)]
  assert p0.keys()==p1.keys()
  assert {k:v for k,v in p0.items() if k!='W0_en'}=={k:v for k,v in p1.items() if k!='W0_en'},('bank connections changed',i)
  before,after=cone(p0['W0_en'],eq0),cone(p1['W0_en'],eq1)
  if i==0:
   expected=p0['W0_en']
   if inline_first:
    expected=re.sub(r'\bpayloadWrite\b','('+eq0['payloadWrite']+')',expected)
    normalizations['unchanged_payloadWrite_expression_inlined_only_into_bank0']=True
   assert tokens(expected)==tokens(p1['W0_en']),'bank0 changed'

  else:
   old_decode=("payloadWriteIndex[2:0] == 3'h"+str(i)) if i<7 else '(&(payloadWriteIndex[2:0]))'
   expected_old='payloadWrite & '+old_decode
   assert tokens(p0['W0_en'])==tokens(expected_old), ('unexpected old bank decode',i,p0['W0_en'])
   expected_new=re.sub(r'\bpayloadWriteIndex\b','index',re.sub(r'\bpayloadWrite\b','continuedPayloadWrite',expected_old))
   assert tokens(p1['W0_en'])==tokens(expected_new), ('upper bank decode changed',i,p1['W0_en'],expected_new)
   assert required_direct<=set(before['leaves']),('baseline first-request cone absent',i,before)
   assert set(after['leaves'])=={'state','io_tl_a_valid','writeError','io_axi_r_valid','index'},('unexpected upper WE leaves',i,after)
   assert not {'payloadWriteIndex','payloadWrite','inWindow','isRead'}&set(after['nodes']),('first event survived upper WE',i)
   assert re.search(r'\bindex\[2:0\]',p1['W0_en']),('upper bank decoder does not use retained index',i,p1)
  banks[str(i)]={'before':p0,'after':p1,'enable_before':before,'enable_after':after,
   'data_before':cone(p0['W0_data'],eq0),'data_after':cone(p1['W0_data'],eq1),
   'row_before':cone(p0['W0_addr'],eq0),'row_after':cone(p1['W0_addr'],eq1)}
 # Remove only the seven explicitly permitted enable-expression differences.
 norm0,norm1=old,new
 if decoder_rename:norm1=re.sub(r'\b'+rename_new+r'\b',rename_old,norm1)
 if inline_first:
  definition=r'\bwire\s+payloadWrite\s*=\s*.*?;'
  norm0,n=re.subn(definition,'',norm0,count=1,flags=re.S);assert n==1

 for i in range(1,8):
  pattern=r'(payloadBanks_2x72\s+payloadBanks_'+str(i)+r'_ext\s*\([\s\S]*?\.W0_en\s*\()(.*?)(\),)'
  norm0,n0=re.subn(pattern,lambda m:m[1]+'REVIEWED_UPPER_BANK_ENABLE'+m[3],norm0,count=1)
  norm1,n1=re.subn(pattern,lambda m:m[1]+'REVIEWED_UPPER_BANK_ENABLE'+m[3],norm1,count=1)
  assert n0==n1==1
 if inline_first:
  # After upper enables are abstracted, the old net has exactly one functional use.
  assert len(re.findall(r'\bpayloadWrite\b',norm0))==1
  norm0=re.sub(r'\bpayloadWrite\b','('+eq0['payloadWrite']+')',norm0)
 normalized_eq1=assignments(norm1)
 extra=sorted(set(normalized_eq1)-set(eq0));assert extra, 'new local expression unexpectedly missing'

 for name in extra:
  assert name in set().union(*(set(banks[str(i)]['enable_after']['nodes']) for i in range(1,8))),('extra logic outside upper WE',name)
  pattern=r'\bwire\s*(?:\[[^\]]+\]\s*)*'+re.escape(name)+r'\s*=\s*.*?;'
  norm1,n=re.subn(pattern,'',norm1,count=1,flags=re.S);assert n==1,('not simple new local wire',name)
 if tokens(norm0)!=tokens(norm1):
  if failure_diff is not None: Path(failure_diff).write_text(''.join(difflib.unified_diff(norm0.splitlines(True),norm1.splitlines(True))))
  raise AssertionError('unreviewed native token change beyond seven WE expressions and their local wires')
 return {"bank_connections":banks,"new_local_wires":{n:eq1[n] for n in extra},"all_other_native_tokens_identical":True,"reviewed_optimizer_normalizations":normalizations,"exact_continued_event_proof":event_proof,"exact_upper_bank_decodes_proven":list(range(1,8))}
