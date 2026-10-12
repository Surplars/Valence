#!/usr/bin/env python3
"""Narrow semantic binding for all seven temporary-named fields used by the frozen host."""
import argparse, hashlib, json, re
from pathlib import Path
ROOTS=[
 ('board.platform.coherentHome.probe.sendQueue','_io_deq_valid_T','io.deq.valid','board$platform$coherentHome$probe$sendQueue$_io_deq_valid_T'),
 ('board.platform.core.core.core.backend.systemUnit','_io_fenceIFlush_T','io.fenceIFlush','board$platform$core$core$core$backend$systemUnit$_io_fenceIFlush_T'),
 ('board.platform.privateCache.engine.sendQueue','_do_deq_T','do_deq','board$platform$privateCache$engine$sendQueue$_do_deq_T'),
 ('board.platform.privateCache.engine.sendQueue','_io_deq_valid_T','io.deq.valid','board$platform$privateCache$engine$sendQueue$_io_deq_valid_T'),
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
def main():
 p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--baseline-host',type=Path,required=True);p.add_argument('--candidate-host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 old=binding(a.baseline);new=binding(a.candidate);rows={}
 for field,b in old.items():
  n=new[field]
  same={'instance_path':b['instance_path']==n['instance_path'],'fir_module':b['fir_module']==n['fir_module'],'sink':b['sink']==n['sink'],'ordered_sink_connections':[(lhs,rhs)for lhs,rhs,line in b['sink_connections']]==[(lhs,rhs)for lhs,rhs,line in n['sink_connections']],'transitive_node_definitions':{k:v['expression']for k,v in b['transitive_nodes'].items()}=={k:v['expression']for k,v in n['transitive_nodes'].items()},'cpp_assignment':b['cpp_assignment']['expression']==n['cpp_assignment']['expression'],'one_bit_declaration':b['header_declaration']==n['header_declaration']}
  assert all(same.values()),('temporary field semantics require review',field,same)
  rows[field]={'checks':same,'baseline':b,'candidate':n}
 hostfiles=('harness/board_boot.cpp','cpu_passive_bandwidth.cpp','supply_ledger.h','adoption_ledger.h')
 host={n:sha(a.baseline_host/n)for n in hostfiles};assert host=={n:sha(a.candidate_host/n)for n in hostfiles}
 boot=(a.candidate_host/'harness/board_boot.cpp').read_text();schedule=['ddr.drive(*dut, cycles);','fabric.drive(*dut,cycles);','dut->step();','fabric.sample(*dut,cycles);','if (observer) observer(*dut, observerContext);','ddr.sample(*dut);']
 indices=[boot.index(s)for s in schedule];assert indices==sorted(indices)
 report={'schema':'compact-proof-temporary-host-semantic-binding-v1','status':'PASS_EXACT_DEFINITION_AND_HANDSHAKE_BINDING','fields':rows,'host_sha256':host,'sampling_schedule':schedule,'semantics':['Router field is actual memory request valid, used for demand-miss gating.','Posted refill is the conjunction of actual posted refill valid and ready in the frozen supply/adoption host.','Observer samples the same combinational evaluation after dut->step and before ddr.sample; both callsite and observer host bytes are unchanged.'],'fir_sha256':{'baseline':sha(a.baseline/'BoardSocGsim.fir'),'candidate':sha(a.candidate/'BoardSocGsim.fir')},'limits':['Narrow equivalence check for these seven temporary fields and their local FIR node dependencies; explicit named host fields retain the existing contract.','No dynamic regression, model rebuild or performance equivalence assertion.']}
 a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(report['status'],len(rows),'fields')
if __name__=='__main__':main()
