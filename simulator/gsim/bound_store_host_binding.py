#!/usr/bin/env python3
"""Narrow semantic binding for exactly three temporary-named fields used by the frozen host."""
import argparse, hashlib, json, re
from pathlib import Path
ROOTS=[
 ('board.platform.platformRouter','_io_memory_request_valid_T_2','io.memory.request.valid','board$platform$platformRouter$_io_memory_request_valid_T_2'),
 ('board.platform.privateCache','_posted_io_refill_valid_T','posted.io.refill.valid','board$platform$privateCache$_posted_io_refill_valid_T'),
 ('board.platform.privateCache.posted','_io_refill_ready_T_22','io.refill.ready','board$platform$privateCache$posted$_io_refill_ready_T_22')]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fir(path):
 modules={};current=None
 for number,raw in enumerate(path.read_text().splitlines(),1):
  line=raw.split(' @[')[0].strip()
  match=re.match(r'(?:public )?(?:module|extmodule) (\S+)\s*:',line)
  if match:current=modules.setdefault(match[1],{'nodes':{},'instances':{},'connects':[]});continue
  if current is None:continue
  match=re.match(r'inst (\S+) of (\S+)',line)
  if match:current['instances'][match[1]]=match[2]
  match=re.match(r'node (\S+) = (.*)',line)
  if match:
   assert match[1] not in current['nodes'];current['nodes'][match[1]]={'expression':match[2],'line':number,'raw':raw.strip()}
  match=re.match(r'connect ([^,]+), (.*)',line)
  if match:current['connects'].append((match[1],match[2],number))
 return modules
def binding(model):
 modules=fir(model/'BoardSocGsim.fir');cpp={p.name:p.read_text()for p in sorted(model.glob('BoardSocGsim[0-9]*.cpp'))};header=(model/'BoardSocGsim.h').read_text();result={}
 for path,name,sink,field in ROOTS:
  module='BoardSocGsim'
  for instance in path.split('.'):module=modules[module]['instances'][instance]
  info=modules[module];assert name in info['nodes'];closure={};pending=[name]
  while pending:
   node=pending.pop()
   if node in closure:continue
   row=info['nodes'][node];closure[node]=row
   pending.extend(t for t in re.findall(r'[A-Za-z_$][A-Za-z0-9_$]*',row['expression'])if t in info['nodes'] and t not in closure)
  sinks=[(lhs,rhs,line)for lhs,rhs,line in info['connects']if lhs==sink];assert sinks and sinks[-1][1]==name,(path,sink,sinks)
  definitions=[]
  for unit,text in cpp.items():
   for match in re.finditer(r'^\s*'+re.escape(field)+r'\s*=\s*([^;]+);',text,re.M):definitions.append({'unit':unit,'expression':match[1],'line':text[:match.start()].count('\n')+1})
  assert len(definitions)==1,(field,definitions)
  declarations=re.findall(r'^([^\n]*\b'+re.escape(field)+r';) // width = (\d+),.*$',header,re.M);assert len(declarations)==1 and declarations[0][1]=='1'
  result[field]={'instance_path':path,'fir_module':module,'node':name,'sink':sink,'sink_connections':sinks,'transitive_nodes':closure,'cpp_assignment':definitions[0],'header_declaration':declarations[0]}
 return result
def verify(model, reference, host):
 old=json.loads(Path(reference).read_text());new=binding(Path(model))
 assert old['status']=='PASS_EXACT_DEFINITION_AND_HANDSHAKE_BINDING'
 assert set(new)==set(old['fields'])
 for field,n in new.items():
  b=old['fields'][field]['baseline']
  assert all(b[k]==n[k] for k in ('instance_path','fir_module','node','sink')),(field,'binding identity')
  assert [(a,b) for a,b,_ in b['sink_connections']]==[(a,b) for a,b,_ in n['sink_connections']],(field,'ordered sinks')
  assert {k:v['expression'] for k,v in b['transitive_nodes'].items()}=={k:v['expression'] for k,v in n['transitive_nodes'].items()},(field,'FIR closure')
  assert b['cpp_assignment']['expression']==n['cpp_assignment']['expression'],(field,'generated definition')
  assert list(b['header_declaration'])==list(n['header_declaration']),(field,'declaration')
 for name,digest in old['host_sha256'].items():assert sha(Path(host)/name)==digest,('observer host drift',name)
 boot=(Path(host)/'harness/board_boot.cpp').read_text()
 indices=[boot.index(s) for s in old['sampling_schedule']];assert indices==sorted(indices),'sampling schedule drift'
 return {'status':'PASS_EXACT_DEFINITION_AND_HANDSHAKE_BINDING','reference_sha256':sha(reference),'fields':new}
