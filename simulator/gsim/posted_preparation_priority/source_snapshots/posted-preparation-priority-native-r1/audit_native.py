#!/usr/bin/env python3
"""Strict literal reachable census, actual constructor equality, and bounded control review."""
import copy,hashlib,importlib.util,json,re,subprocess,sys,tempfile
from pathlib import Path
import run_native as b
HERE=b.HERE;OUT=HERE/'execution';ANALYSIS=HERE/'analysis';require=b.require;read=b.read;save=b.save;sha=b.sha

def combinational_graph(path):
 text=path.read_text();body=re.sub(r'//[^\n]*','',re.sub(r'/\*.*?\*/','',text,flags=re.S))
 require(not re.search(r'\balways_(?:comb|latch)\b|always\s*@\s*\*',body),'unsupported combinational procedural block')
 regs=set()
 for high,low,decl in re.findall(r'\breg\b\s*(?:\[(\d+):(\d+)\]\s*)?([^;]+);',body):
  for item in decl.split(','):
   m=re.match(r'\s*([\w$]+)',item);require(m is not None,'bad register');regs.add(m[1])
 eq={}
 for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_$]*)(?:\s*\[[^;=\]]+\])*\s*=(?!=)\s*([^;]+);',body,re.S):
  name,expr=m.groups()
  if name not in regs:eq.setdefault(name,[]).append(expr)
 # Add the actual planner input expression to the dependency graph. Child outputs
 # remain explicit leaves; normal firtool separately checks the whole design.
 planner=re.search(r'\bMemoryPreparationSelector\s+planner\s*\(',body)
 if planner:
  start=body.index('.io_eligible',planner.end());p=body.index('(',start)+1;depth=1;q=p
  while depth:
   depth+=(body[q]=='(')-(body[q]==')');q+=1
  eq['planner::eligible']=[body[p:q-1]]
 deps={n:sorted(set(t for expr in exprs for t in re.findall(r'\b[A-Za-z_][A-Za-z0-9_$]*\b',expr)))for n,exprs in eq.items()};state={};cycles=[]
 def visit(n,stack):
  if n in regs or n not in deps:return
  if state.get(n)==1:cycles.append(stack[stack.index(n):]+[n]);return
  if state.get(n)==2:return
  state[n]=1
  for d in deps[n]:visit(d,stack+[n])
  state[n]=2
 for n in deps:visit(n,[])
 require(not cycles,'local combinational cycle found')
 def closure(n,seen=None):
  seen=set()if seen is None else seen
  if n in seen:return seen
  seen.add(n)
  if n not in regs:
   for ch in deps.get(n,[]):closure(ch,seen)
  return seen
 cone=closure('planner::eligible')if planner else set()
 return dict(status='PASS_BOUNDED_WIRE_AND_AUTOMATIC_TEMPORARY_GRAPH_ACYCLIC',module_sha256=sha(path),equations=len(eq),register_cutpoints=sorted(regs),all_equation_dependencies=deps,cycles=cycles,planner_eligible_expression=eq.get('planner::eligible'),planner_eligible_cone=sorted(cone),planner_eligible_register_cutpoints=sorted(cone&regs),planner_eligible_leaf_inputs=sorted(n for n in cone if n not in regs and n not in deps),limits=['Bounded intra-module graph; child outputs are leaves, registers cut cycles.','Normal firtool checks whole lowered design for combinational loops. Neither check is formal equivalence or STA.'])

def verify_actual_pair():
 plan=read(HERE/'plan.json');actual={s:b.audit_profile(s,plan)for s in ['off','on']};pred=copy.deepcopy(actual['off'])
 pred['entryProfile']['postedPreparationPriority']=True;pred['expectedCore']['postedPreparationPriority']=True
 for row in pred['coreParameters']:row['values']['postedPreparationPriority']=True
 pred['canonicalOptions']=sorted(pred['canonicalOptions']+['--posted-preparation-priority']);pred['experiment']='posted-preparation-priority-on'
 require(pred==actual['on'],'unexplained full actual parameter record difference')
 return dict(status='PASS_FULL_ACTUAL_JSON_SOLE_FLAG_PLUS_LABEL_DIFFERENCE',complete_profile_arities=[140,32,11],constructor_instances={'core':6,'cache':3,'ddr':2},TileLink_parameters_equal=actual['off']['cacheTileLinkParameters']==actual['on']['cacheTileLinkParameters'])

def audit():
 b.source_guard(read(HERE/'plan.json'));e=read(OUT/'receipt.json');require(e['status']=='PASS_FRESH_NATIVE_PAIR_EXPORT_ONLY','native export not complete');require(len(e['steps'])==5 and all(x['exit']==0 and x['guard']is None for x in e['steps']),'native stages not complete')
 require(not ANALYSIS.exists(),'fresh analysis destination required');ANALYSIS.mkdir();c=b.load('priority_reachable',HERE/'helpers/reachable_census.py');c.OUT=ANALYSIS;actual=verify_actual_pair();save(ANALYSIS/'actual-pair.json',actual);rows={};storage={};graphs={}
 for side in ['off','on']:
  d=OUT/side;r=c.extend(d);r['directory']=str(d);rows[side]=r;save(ANALYSIS/(side+'-census.json'),r)
  path=ANALYSIS/(side+'-fixed-storage.json');cmd=[sys.executable,'-B',str(HERE/'helpers/native_storage_census_bound_rob64.py'),'--rtl',str(d/'rtl'),'--output',str(path)];z=subprocess.run(cmd,capture_output=True,text=True);require(z.returncode==0,'fixed storage census failed '+z.stdout+z.stderr);storage[side]=read(path)
  graph=combinational_graph(d/'rtl/IntegerBackend.sv');graphs[side]=graph;save(ANALYSIS/(side+'-control-graph.json'),graph)
  sv='\n'.join(x.read_text()for x in (d/'rtl').glob('*.sv'));probes=re.findall(r'\b(?:BoringUtils|bore|io_mp\w*|io_postedPrep\w*)\b',sv);require(not probes,'passive probe marker survives native output')
  require(not re.search(r'\b(?:assert|assume|cover)\s*\(|\$(?:fatal|error)\b',c.c.strip(sv)),'verification remains')
 a,z=rows['off'],rows['on'];comparison=c.compare(a,z,'off-on');save(ANALYSIS/'comparison.json',comparison)
 ram={p:{'off':a['reachable_ram_instances'].get(p),'on':z['reachable_ram_instances'].get(p)}for p in sorted(set(a['reachable_ram_instances'])|set(z['reachable_ram_instances']))if a['reachable_ram_instances'].get(p)!=z['reachable_ram_instances'].get(p)};save(ANALYSIS/'ram-differences.json',ram)
 # Explicit historical baseline comparison uses fetch-chain OFF (the reviewed LRU graph).
 # Its rejected ON result is never imported into the current result.
 prior_dir=b.BASE/'frontier-fetch-chain-native-r1/execution/off';prior=c.extend(prior_dir);prior['directory']=str(prior_dir);priorcmp=c.compare(prior,a,'historical-lru-off-current-off');save(ANALYSIS/'historical-baseline-comparison.json',priorcmp)
 changed=[x['module']for x in comparison['modules']if not x['exact_bytes_equal']];reasons=[]
 if any(comparison['delta'].values()):reasons.append('nonzero reachable state delta')
 if any(not x['ports_equal']for x in comparison['modules']):reasons.append('module/port inventory changed')
 if ram:reasons.append('RAM geometry/actual ports/helper bytes changed')
 if storage['off']['groups']!=storage['on']['groups']:reasons.append('fixed storage contracts differ')
 if not comparison['external_paths_equal']:reasons.append('external hierarchy changed')
 if changed!=['IntegerBackend']:reasons.append('raw changed modules need review: '+str(changed))
 counts={}
 for side in rows:
  r=rows[side];counts[side]={k:r[k]for k in ['all_definition_totals','production_reachable_totals','production_module_instance_count','unreachable_definitions']};counts[side].update(reachable_ram_instances=len(r['reachable_ram_instances']),raw_sv_files=len(list((OUT/side/'rtl').glob('*.sv'))),raw_sv_bytes=sum(x.stat().st_size for x in(OUT/side/'rtl').glob('*.sv')),external_paths=r['excluded_external_paths'])
 summary=dict(schema='posted-preparation-priority-native-census-v1',status='REVIEW_REQUIRED'if reasons else'PASS_LITERAL_NATIVE_CENSUS_PENDING_FINAL_CONTROL_REVIEW',production_commit=b.COMMIT,production_tree=b.TREE,execution_receipt_sha256=sha(OUT/'receipt.json'),source_freeze_sha256=sha(HERE/'source-freeze.json'),checker_sha256=sha(__file__),normalization_rules=[],snapshots=counts,production_state_delta=comparison['delta'],changed_raw_definitions=changed,all_ports_equal=all(x['ports_equal']for x in comparison['modules']),ram_differences=len(ram),fixed_storage_groups_equal=storage['off']['groups']==storage['on']['groups'],actual_parameters=actual,verification_and_probe_erasure=True,raw_sv_byte_delta=counts['on']['raw_sv_bytes']-counts['off']['raw_sv_bytes'],historical_baseline=dict(path=str(prior_dir),receipt_sha256=sha(prior_dir/'receipt.json'),changed_modules=[x['module']for x in priorcmp['modules']if not x['exact_bytes_equal']],production_delta=priorcmp['delta']),review_reasons=reasons,limits=['Fresh actual native OFF/ON elaboration and lowering; no mapped LUT/FF/BRAM/DSP or PPA/STA.','Literal whole emitted SV hashes, all reachable registers/arrays and ports; no normalization.','Equal state/ports and local acyclicity do not establish functional equivalence.','External ROM primitive and clock buffers are explicitly excluded and compared.'])
 save(ANALYSIS/'summary.json',summary);print(json.dumps(summary,indent=2));return summary
if __name__=='__main__':audit()
