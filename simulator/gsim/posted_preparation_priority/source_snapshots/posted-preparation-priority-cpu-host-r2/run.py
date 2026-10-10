#!/usr/bin/env python3
"""Fresh original-guest CPU proof; source-only preparation is not runtime qualification."""
import argparse
from contract import *
from model import execute,verify as verify_model,validate_measured
from parser import parse,validate_owner_trace
from canonical_trace import validate as validate_canonical
import admission_trace,dmmu_trace,unissued_trace,window_trace,proof_trace,lru_trace
from followup_bridge import verify as verify_followup_bridge
DONOR=BASE/'rob-capacity-cpu-prep-r1'
PRESERVED=('abi.hpp','copy_model_adapter.hpp','copy_adapter_logic.hpp','copy_eviction.hpp','drain.hpp','worksets_symbols.h','axi_accounting.h','canonical_model_adapter.hpp','canonical_observer.hpp','cache_window_adapter.hpp','dmmu_observer.hpp','dmmu_trace.py','admission_observer.hpp','admission_model_adapter.hpp','admission_trace.py','unissued_model_adapter.hpp','unissued_observer.hpp','unissued_trace.py','window_observer.hpp','window_trace.py','copy_lineage.py')
TRACE_ENV={'POSTED_BANDWIDTH_OWNER_TRACE':'owners','CANONICAL_OVERLAP_TRACE':'canonical','READ_PREFETCH_TRACE':'admission','D_TRANSLATION_TRACE':'dmmu','UNISSUED_STORE_TRACE':'unissued','ROB_WINDOW_TRACE':'window','MEMORY_PROOF_FRONTIER_TRACE':'proof','READY_LOAD_FRONTIER_TRACE':'readiness','STORE_PF_LRU_TRACE':'lru'}
def canonical_cases(cases):
 require(all(type(k)is int for k in cases) and len({str(k)for k in cases})==len(cases),'CASES requires unique canonical integer keys')
 return {str(k):v for k,v in cases.items()}
def read_preflight(path):
 def unique(pairs):
  require(len({k for k,v in pairs})==len(pairs),'duplicate preflight JSON key');return dict(pairs)
 return json.loads(Path(path).read_text(),object_pairs_hook=unique)
def base():
 for n in PRESERVED:require(sha(HERE/n)==sha(DONOR/n),'preserved independent oracle changed '+n)
 old=(DONOR/'host.cpp').read_text();new=(HERE/'host.cpp').read_text()
 for start,end in [('static void buffers(','struct Observed'),('static uint64_t expectedWord(uint64_t n)','int main(')]:require(old[old.index(start):old.index(end)]==new[new.index(start):new.index(end)],'independent full-word/row oracle changed')
 require(sha(ROOT/'simulator/gsim/harness/board_boot.cpp')==sha(DONOR/'source/simulator/gsim/harness/board_boot.cpp'),'DDR due32/gap1/B3/AW-blocks-R or boot oracle changed')
 files=tuple(sorted(p.name for p in HERE.iterdir()if p.is_file()and p.suffix in ('.hpp','.h','.cpp','.py')))+('guest-provenance.json','canonical-flags.json','SOURCE-PIN.json','SELECTED-SOURCE.json','PASSIVE-ABI.json','expected-profile-off.json','expected-profile-on.json','FOCUSED-GATE-CONTRACT.json','BASELINE-REFERENCE.json')
 return dict(source=source(),tools=tools(),environment=environment(),guest=guest(),files={n:sha(HERE/n)for n in files},compiler_flags=FLAGS,defines=DEFINES,cases=canonical_cases(CASES),profiles={k:expected_profile(k)for k in PROFILES})
def command(side,folder,out=None,syntax=False):
 args=[tools()['files']['clang']['path'],*FLAGS,*DEFINES,*geometry(side),'-DPREFETCH_CANDIDATE_CYCLES=1','-DMEMORY_PROOF_FRONTIER_ON=1','-DSTORE_PF_LRU_VICTIM_ON=1','-DPOSTED_PREPARATION_PRIORITY_ON='+str(int(side=='on')),'-I'+str(folder),str(HERE/'host.cpp'),'-I'+str(ROOT/'simulator/gsim/harness')]
 return args+(['-fsyntax-only']if syntax else[str(folder/'BoardSocGsim0.o'),'-ldl','-o',str(out)])
def preflight(out):
 out=Path(out).resolve();require(not out.exists(),'fresh preflight namespace');out.mkdir();b=base();r=dict(status='RUNNING',base=b,steps=[],DUT_executed=False)
 try:
  cc=b['tools']['files']['clang']['path']
  for name in ('test_roi','test_capacity','test_copy_eviction','axi_accounting_test','test_edges','test_copy_adapter','test_canonical_observer','test_dmmu','test_unissued','test_admission','test_window','test_lru_victim','test_staging_owner'):
   folder=out/name;folder.mkdir();r['steps'].append(execute([cc,*FLAGS,*geometry('off'),'-DPREFETCH_CANDIDATE_CYCLES=1','-DMEMORY_PROOF_FRONTIER_ON=1',str(HERE/(name+'.cpp')),'-o',str(folder/name)],folder/'build.log',120,cwd=HERE))
   env={}
   if name=='test_dmmu':env={'D_TRANSLATION_TRACE':str(folder/'dmmu.jsonl')}
   if name=='test_unissued':env={'UNISSUED_STORE_TRACE':str(folder/'fixture.jsonl')}
   if name=='test_admission':env={'READ_PREFETCH_TRACE':str(folder/'fixture.jsonl')}
   if name=='test_window':env={'ROB_WINDOW_TRACE':str(folder/'fixture.jsonl')}
   r['steps'].append(execute([str(folder/name)],folder/'fixture.log',30,cwd=HERE,extra_env=env))
  for name in ('test_parser','test_owner_trace','test_profile','test_window_trace','test_lru_trace','test_compressed_controls','test_terminal_pair','test_raw_storage'):
   r['steps'].append(execute([sys.executable,'-B',str(HERE/(name+'.py'))],out/(name+'.log'),60,cwd=HERE))
  require(exact(b,base()),'host/source inputs drift during preflight');r['status']='PASS_FROZEN_HOST_ONLY_NO_DUT_EXECUTION'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:save(out/'receipt.json',r)
 return dict(status=r['status'],receipt=str(out/'receipt.json'),sha256=sha(out/'receipt.json'))
def check_preflight(path):
 r=read_preflight(path);require(r['status']=='PASS_FROZEN_HOST_ONLY_NO_DUT_EXECUTION'and r['DUT_executed']is False and exact(r['base'],base()),'preflight pending/drift')
 for st in r['steps']:require(st['exit']==0 and st['guard']is None and sha(st['log'])==st['log_sha256'],'preflight failed/changed')
 return r

def focus(path,digest,contract_path,contract_digest):
 # The coordinator owns the eventual actual focused aggregate schema/verifier.
 # A source manifest, config PASS or model-only build cannot satisfy this gate.
 template=read(HERE/'FOCUSED-GATE-CONTRACT.json')
 require(contract_path is not None and contract_digest is not None,'coordinator focused contract receipt required')
 require(sha(contract_path)==contract_digest,'focused contract pin drift');c=read(contract_path)
 require(set(c['required_checks'])==set(template['required_checks']),'focused required scope changed')
 require(all(c[k]==template[k]for k in ('status','pass_status','verifier_path','verifier_sha256')),'focused pinned verifier contract changed')
 require(c['status']=='DEFINED_ACTUAL_FOCUSED_AGGREGATE','focused runtime aggregate contract remains pending')
 require(sha(path)==digest,'focused aggregate hash drift')
 vp=Path(c['verifier_path']);require(sha(vp)==c['verifier_sha256'],'focused verifier not pinned')
 v=load('memory_frontier_actual_focused_verifier',vp)
 checked=v.verify(Path(path),digest,production_head=read(SOURCE_PIN)['production_source_head'],tool_receipt_sha256=TOOL_SHA)
 require(checked['status']==c['pass_status'] and checked['DUT_executed']is True and set(checked['checks'])==set(c['required_checks']) and all(x=='PASS'for x in checked['checks'].values()),'actual focused evidence incomplete')
 return dict(path=str(Path(path).resolve()),sha256=digest,verification=checked,contract_path=str(Path(contract_path).resolve()),contract_sha256=contract_digest)

def check_smoke(path,side,model):
 r=read(path);require(r['schema']=='posted-preparation-priority-rv64gc-smoke-v1' and r['status']=='PASS_FRESH_PROFILE_RV64GC_SHORT_WITH_REAL_NEGATIVE' and r['side']==side and r['model_sha256']==sha(model),'new-profile RV64GC smoke not qualified')
 require(exact(r['source'],source()) and len(r['steps'])==5,'RV64GC source/steps mismatch')
 for name,h in r['artifacts'].items():require(sha(Path(path).parent/name)==h,'smoke artifact drift '+name)
 for i,st in enumerate(r['steps']):require(st['exit']==st['expected']==(1 if i==4 else 0) and st['guard']is None and sha(st['log'])==st['log_sha256'],'smoke command failed/changed')
 require('RV64GC_BOARD_PASS'in Path(r['steps'][3]['log']).read_text() and 'firmware independent anchor/context failure'in Path(r['steps'][4]['log']).read_text(),'fresh smoke positive/real negative anchor missing')
 return dict(path=str(Path(path).resolve()),sha256=sha(path))
def bind(preflight,models,smokes,out):
 pre=check_preflight(preflight);validated={};pair_profiles(expected_profile('off'),expected_profile('on'))
 for side,path in models.items():
  path=Path(path).resolve();m=verify_model(path,sha(path));require(m['side']==side,'model side mismatch')
  st=execute(command(side,path.parent,syntax=True),Path(out).with_suffix('.'+side+'.header.log'),120,cwd=HERE)
  validated[side]=dict(receipt=str(path),sha256=sha(path),header_syntax=st,smoke=check_smoke(smokes[side],side,path))
 require(set(validated)in ({'off'},{'off','on'}),'OFF baseline or separate OFF/ON models required')
 r=dict(schema='posted-preparation-priority-cpu-pins-v1',status='PINNED_NOT_EXECUTED',base=pre['base'],preflight_path=str(Path(preflight).resolve()),preflight_sha256=sha(preflight),focused=None,models=validated,first_case=19,followup_cases=[21,0,18,6],guest_changed=False,runtime_qualification_inherited=False)
 save(out,r,True);return dict(status=r['status'],path=str(out),sha256=sha(out))
def check(path,digest):
 require(sha(path)==digest,'runtime pins drift');p=read(path)
 require(p['schema']=='posted-preparation-priority-cpu-pins-v1'and p['status']=='PINNED_NOT_EXECUTED'and exact(p['base'],base()),'runtime source/tools/host drift')
 require(sha(p['preflight_path'])==p['preflight_sha256'],'preflight hash drift');check_preflight(p['preflight_path'])
 for side,m in p['models'].items():
  verify_model(m['receipt'],m['sha256']);require(exact(check_smoke(m['smoke']['path'],side,m['receipt']),m['smoke']),'smoke receipt drift');st=m['header_syntax'];require(st['argv']==command(side,Path(m['receipt']).parent,syntax=True)and st['exit']==0 and st['guard']is None and sha(st['log'])==st['log_sha256'],'actual generated header syntax not qualified')
 return p

def validate_output(out,side,case):
 out=Path(out);text=(out/'positive.log').read_text();r={};r['result']=parse(text,'on',case)
 r['owner_trace']=validate_owner_trace(out/'positive.owners.jsonl',r['result'],64)
 r['canonical_trace']=validate_canonical(out/'positive.canonical.jsonl',text,'on',r['result']['roi']['cycles'],64)
 r['admission_trace']=admission_trace.validate(out/'positive.admission.jsonl',text,r['result'])
 r['dmmu_trace']=dmmu_trace.validate(out/'positive.dmmu.jsonl',text,r['result'])
 r['unissued_trace']=unissued_trace.validate(out/'positive.unissued.jsonl',text,r['result'],None,64,64)
 a,b=r['result']['roi']['begin_offer'],r['result']['roi']['end_offer']
 require(r['unissued_trace']['summary']['roi_first']==a and r['unissued_trace']['summary']['roi_end']==b,'unissued exact primary offer interval')
 r['window_trace']=window_trace.validate(out/'positive.window.jsonl',out/'positive.canonical.jsonl',text,r['result'],64,64)
 r['proof_trace']=proof_trace.validate(out/'positive.proof.jsonl',out/'positive.canonical.jsonl',text,r['result'],r['window_trace'])
 r['lru_trace']=lru_trace.validate(out/'positive.lru.jsonl',text,r['result'],'on',out/'positive.admission.jsonl')
 # Both policy sides retain the actual frontier proof path and full typed oracle.
 if side=='off' and case in (19,21):
  old=read(HERE/'BASELINE-REFERENCE.json')[str(case)];require(sha(old['source_receipt'])==old['source_receipt_sha256'],'baseline receipt drift');require(exact(r['result'],old['result']),'new preparation-priority OFF does not exactly reproduce original frontier+LRU-ON complete result')
  for name,h in old['raw_sha256'].items():require(sha(out/name)==h,'new OFF original passive trace differs '+name)
  r['original_lru_on_reproduction']=dict(ticks=old['result']['ticks'],flush_tail=old['result']['flush_tail'],complete_result_equal=True,original_raw_traces_equal=True,new_execution=True)
 r['boundary_join']=dict(status='UNKNOWN_NOT_RECONSTRUCTED',offer_window=[a,b],legacy_canonical_phase_window=[a+1,b+1],end_offer_edge_raw_sample=None,one_cycle_shift_not_used_to_fabricate_missing_sample=True)
 return r

def run(path,digest,side,case,out,slot,followup_gate=None,focused=None,focused_sha=None,focused_contract=None,focused_contract_sha=None):
 require(slot,'coordinator heavy slot required');require(side in PROFILES and case in CASES,'unsupported original singleton');p=check(path,digest)
 require(side in p['models'],'selected side not bound')
 gate=None
 followup=None
 gate=focus(focused,focused_sha,focused_contract,focused_contract_sha) if side=='on' else None
 if case!=19:
  require(followup_gate is not None,'case19 measured net gain gate required before controls')
  followup=verify_followup_bridge(followup_gate,p,digest,case)
 out=Path(out).resolve();require(not out.exists(),'fresh runtime namespace');out.mkdir();folder=Path(p['models'][side]['receipt']).parent
 r=dict(schema='posted-preparation-priority-cpu-case-v1',status='RUNNING',side=side,case=case,pins_path=str(Path(path).resolve()),pins_sha256=digest,steps=[],guest_changed=False,new_execution=True,model_rebuilt=False,focused=gate,followup_bridge=followup)
 try:
  r['steps'].append(execute(command(side,folder,out/'host'),out/'link.log',1800,cwd=HERE));save(out/'receipt.json',r)
  for name in ('positive','trap-negative'):
   env={k:str(out/(name+'.'+v+'.jsonl'))for k,v in TRACE_ENV.items()}
   cmd=[str(out/'host'),str(HERE/'guest.bin'),str(case),str(case+1)]+(['--inject-trap']if name=='trap-negative'else[])
   r['steps'].append(execute(cmd,out/(name+'.log'),1800,cwd=HERE,expected=1 if name=='trap-negative'else 0,extra_env=env));save(out/'receipt.json',r)
   if name=='positive':
    r['positive_terminal_primary']=parse((out/'positive.log').read_text(),'on',case);save(out/'receipt.json',r)
    print(json.dumps(dict(stage='POSITIVE_NATIVE_AND_PRIMARY_ORACLE_PASS',side=side,case=case,ticks=r['positive_terminal_primary']['ticks'],flush_tail=r['positive_terminal_primary']['flush_tail'],full_raw_validation='PENDING')),flush=True)
    r.update(validate_measured(out,side,case))
   else:require('independent worksets trap order mismatch'in(out/'trap-negative.log').read_text(),'trap negative rejected for wrong reason')
  check(path,digest)
  if side=='on':require(exact(focus(focused,focused_sha,focused_contract,focused_contract_sha),gate),'focused gate drift during runtime')
  elif case in (19,21):require(r['original_lru_on_reproduction']['complete_result_equal'] and r['original_lru_on_reproduction']['original_raw_traces_equal'],'OFF baseline reproduction required')
  r['status']='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'
  r['checks']={k:'PASS'for k in ('full_buffers_and_rows','fault_trap_CSR_SP_GP','original_offer_ROI_and_flush','AXI_handshakes_conservation_and_drain','posted_full_token_owners','canonical_full_token_event_oracle','prefetch_admission','D_translation','unissued_offer_interval','ROB_PRF_load_lineage','nonzero_injected_trap_rejection')}
  r['checks']['cross_interval_boundary_join']='UNKNOWN';r['checks']['new_frontier_structural_effect']=r['proof_trace']['status']
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:r['artifacts']={f.name:sha(f)for f in out.iterdir()if f.is_file()and f.name!='receipt.json'};save(out/'receipt.json',r)
 return dict(status=r['status'],path=str(out/'receipt.json'),sha256=sha(out/'receipt.json'),ticks=r['result']['ticks'],flush_tail=r['result']['flush_tail'],structural=r['proof_trace']['status'])
def main():
 a=argparse.ArgumentParser();sub=a.add_subparsers(dest='action',required=True)
 q=sub.add_parser('preflight');q.add_argument('--out',type=Path,required=True)
 q=sub.add_parser('bind')
 for n in ('preflight','off','smoke-off','out'):q.add_argument('--'+n,type=Path,required=True)
 for n in ('on','smoke-on'):q.add_argument('--'+n,type=Path)
 for name in ('check','run'):
  q=sub.add_parser(name);q.add_argument('--pins',type=Path,required=True);q.add_argument('--sha256',required=True)
  if name=='run':
   q.add_argument('--side',choices=PROFILES,required=True);q.add_argument('--case',type=int,choices=CASES,required=True);q.add_argument('--out',type=Path,required=True);q.add_argument('--slot-granted',action='store_true');q.add_argument('--followup-gate',type=Path);q.add_argument('--focused',type=Path);q.add_argument('--focused-sha256');q.add_argument('--focused-contract',type=Path);q.add_argument('--focused-contract-sha256')
 q=a.parse_args()
 if q.action=='preflight':r=preflight(q.out)
 elif q.action=='bind':r=bind(q.preflight,{'off':q.off,**({'on':q.on}if q.on else{})},{'off':q.smoke_off,**({'on':q.smoke_on}if q.on else{})},q.out)
 elif q.action=='check':check(q.pins,q.sha256);r={'status':'PASS_RUNTIME_BINDING'}
 else:r=run(q.pins,q.sha256,q.side,q.case,q.out,q.slot_granted,q.followup_gate,q.focused,q.focused_sha256,q.focused_contract,q.focused_contract_sha256)
 print(json.dumps(r,indent=2))
if __name__=='__main__':main()
