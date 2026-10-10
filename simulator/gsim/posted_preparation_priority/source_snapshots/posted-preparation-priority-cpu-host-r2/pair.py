#!/usr/bin/env python3
"""Strict terminal inheritance, with actual parser invocation and result digest."""
import argparse,hashlib
from contract import *
import run
from proof_controls_compressed import verify as verify_controls
PARSERS=('parser.py','canonical_trace.py','admission_trace.py','admission_trace_v1.py','dmmu_trace.py','unissued_trace.py','window_trace.py','proof_trace.py','lru_trace.py')
ORACLES=('full_buffers_and_rows','fault_trap_CSR_SP_GP','original_offer_ROI_and_flush','AXI_handshakes_conservation_and_drain','posted_full_token_owners','canonical_full_token_event_oracle','prefetch_admission','D_translation','unissued_offer_interval','ROB_PRF_load_lineage','nonzero_injected_trap_rejection')
VALIDATION_KEYS=('result','owner_trace','canonical_trace','admission_trace','dmmu_trace','unissued_trace','window_trace','proof_trace','lru_trace','boundary_join')
def digest_result(r):return hashlib.sha256(json.dumps(json.loads(json.dumps(r)),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def identity(r,side,case):
 require(r['schema']=='posted-preparation-priority-cpu-case-v1'and r['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and r['side']==side and r['case']==case and r['new_execution']is True and r['guest_changed']is False,'terminal identity mismatch')
 require(len(r['steps'])==3 and [(s['exit'],s['expected'],s['guard'])for s in r['steps']]==[(0,0,None),(0,0,None),(1,1,None)],'actual trap negative missing')
 require(all(r['checks'].get(k)=='PASS'for k in ORACLES),'original CPU oracle missing')
def artifacts(r,folder,storage=None):
 actual={x.name for x in folder.iterdir()if x.is_file()and x.name!='receipt.json'}
 archived={}
 if storage is not None:
  import raw_storage
  archived=raw_storage.verify(storage,folder/'receipt.json')['members']
 require(actual|set(archived)==set(r['artifacts'])and actual<=set(r['artifacts']),'terminal artifact inventory changed')
 require({f'{prefix}.{name}.jsonl'for prefix in('positive','trap-negative')for name in run.TRACE_ENV.values()}|{'positive.window.jsonl.lifetimes.jsonl'}<=actual|set(archived),'required raw trace missing')
 for n,h in r['artifacts'].items():
  require((sha(folder/n)if n in actual else archived[n]['logical_sha256'])==h,'terminal raw/artifact drift '+n)
 return len(actual|set(archived))
def measurement(r,folder,side,case,pins):
 path=folder/'validation.resources.json';require(r['measurement_path']==str(path)and sha(path)==r['measurement_sha256'],'parser execution record changed');m=read(path)
 request=dict(stage='validate',out=str(folder),side=side,case=case,measurement=str(path))
 require(m['status']=='PASS'and m['stage']=='validate'and exact(m['actual_request'],request)and exact(json.loads(m['actual_stdin_text']),request),'parser actual invocation differs')
 require(hashlib.sha256(m['actual_stdin_text'].encode()).hexdigest()==m['actual_stdin_sha256'],'parser stdin digest changed')
 require(m['actual_process_argv']==[sys.executable,'-B',str(HERE/'stage_measure.py')]and exact(m['resources'],r['stage_resources'])and m['resources']['fresh_process']is True,'parser process/resources differs')
 keys=list(VALIDATION_KEYS)+(['original_lru_on_reproduction']if side=='off'and case in (19,21) else[])
 require(digest_result({k:r[k]for k in keys})==m['result_sha256'],'executed parser result digest mismatch')
 require(m['parser_code_sha256']=={n:pins['base']['files'][n]for n in PARSERS},'executed parser source mismatch')
 return dict(path=str(path),sha256=sha(path),actual_process_argv=m['actual_process_argv'],actual_stdin_sha256=m['actual_stdin_sha256'],result_sha256=m['result_sha256'],parser_code_sha256=m['parser_code_sha256'])
def one(path,digest,side,case,controls=None,storage=None):
 path=Path(path).resolve();require(sha(path)==digest,'terminal receipt pin changed');r=read(path);folder=path.parent;identity(r,side,case)
 p=run.check(r['pins_path'],r['pins_sha256']);count=artifacts(r,folder,storage)
 primary=run.parse((folder/'positive.log').read_text(),'on',case);require(exact(primary,r['result'])and exact(primary,r['positive_terminal_primary']),'independent primary reparse differs')
 require(r['steps'][0]['argv']==run.command(side,Path(p['models'][side]['receipt']).parent,folder/'host'),'actual host/model link differs')
 for i,s in enumerate(r['steps']):
  require(sha(s['log'])==s['log_sha256']and sha(s['measurement_path'])==s['measurement_sha256'],'native log/resources changed')
  m=read(s['measurement_path']);require(m['status']=='PASS'and exact(m['resources'],s['stage_resources']),'native stage incomplete')
  require(m['actual_request']['cmd']==s['argv']and m['actual_request']['expected']==s['expected'],'native invocation identity changed')
  if i:
   prefix='positive'if i==1 else'trap-negative';want=[str(folder/'host'),str(HERE/'guest.bin'),str(case),str(case+1)]+(['--inject-trap']if i==2 else[])
   require(s['argv']==want and m['actual_request']['extra_env']=={k:str(folder/(prefix+'.'+v+'.jsonl'))for k,v in run.TRACE_ENV.items()},'actual guest/stimulus/trace invocation changed')
 require('independent worksets trap order mismatch'in(folder/'trap-negative.log').read_text(),'trap negative wrong reason')
 require(r['checks']['cross_interval_boundary_join']=='UNKNOWN'and r['boundary_join']['status']=='UNKNOWN_NOT_RECONSTRUCTED','unknown endpoint fabricated')
 l=r['lru_trace'];require(l['status']=='PASS_ACTUAL_REGISTERED_REPLACEMENT_POLICY_AND_BUS'and l['policy']is True and l['all_candidate_history_verified']and l['admission_identity_joined'],'fixed LRU qualification missing')
 measured=measurement(r,folder,side,case,p)
 gate=r['focused']
 if side=='on':require(exact(run.focus(gate['path'],gate['sha256'],gate['contract_path'],gate['contract_sha256']),gate),'actual prerequisite composition changed')
 else:require(gate is None and r['original_lru_on_reproduction']['complete_result_equal'] and r['original_lru_on_reproduction']['original_raw_traces_equal'],'OFF qualification must exactly reproduce baseline')
 control=None
 if case==21:
  require(controls is not None,'seven actual proof controls required for each side');verify_controls(controls,path);control=dict(path=str(Path(controls).resolve()),sha256=sha(controls))
 return r,p,dict(path=str(path),sha256=digest,parser_execution=measured,all_artifacts_hashed=count,proof_controls=control,raw_storage=None if storage is None else dict(path=str(Path(storage).resolve()),sha256=sha(storage)))
def build(off,off_sha,on,on_sha,controls=None,storage=None,case=19):
 require(case in (19,21),'only original COPY case pairs');controls=controls or {}
 storage=storage or {}
 a,pa,ea=one(off,off_sha,'off',case,controls.get('off'),storage.get('off'));b,pb,eb=one(on,on_sha,'on',case,controls.get('on'),storage.get('on'))
 require(exact(pa['base'],pb['base']) and pa['preflight_path']==pb['preflight_path'] and pa['preflight_sha256']==pb['preflight_sha256'],'cross-side source/tool/host/guest/preflight closure differs')
 require(set(pa['models']) in ({'off'},{'off','on'}) and set(pb['models'])=={'off','on'},'OFF-first binding may only extend to complete pair')
 for side, model in pa['models'].items():
  newer=pb['models'][side]
  require(all(exact(model[k],newer[k]) for k in ('receipt','sha256','smoke')),'previously bound actual model or smoke changed while extending pair')
  require(model['header_syntax']['argv']==newer['header_syntax']['argv'],'actual header ABI command changed while extending pair')
 pair_profiles(pa['base']['profiles']['off'],pa['base']['profiles']['on'])
 x,y=a['result'],b['result'];require(x['row'][:5]==y['row'][:5]and x['row'][7:]==y['row'][7:],'cross-side guest workload shape differs')
 gain=y['ticks']<x['ticks']and y['ticks']+y['flush_tail']<x['ticks']+x['flush_tail'];structure=b['proof_trace']['witness_count']>0
 status=('PASS_CASE19_NET_GAIN'if gain else'NO_CASE19_NET_GAIN')if case==19 else('PASS_CASE21_GAIN_AND_STRUCTURE'if gain and structure else'NO_CASE21_GAIN_AND_STRUCTURE')
 return dict(schema='posted-preparation-priority-immutable-terminal-pair-v1',status=status,case=case,functional_status='PASS_BOTH_ORIGINAL_BYTE_FAULT_CSR_DRAIN_AND_NEGATIVES',performance_status='GAIN'if gain else'NO_GAIN',structural_status='STRUCTURAL_WITNESS_PRESENT'if structure else'STRUCTURAL_WITNESS_ABSENT',pins_sha256=b['pins_sha256'],pins_path=b['pins_path'],off_pins_sha256=a['pins_sha256'],off_binding_extended_only_by_new_on_model=not exact(pa,pb),side_evidence={'off':ea,'on':eb},same_source_tools_hosts_and_models=True,focused=b['focused'],measurements={s:dict(ticks=r['result']['ticks'],flush_tail=r['result']['flush_tail'],total=r['result']['ticks']+r['result']['flush_tail'],axi=r['result']['axi'],roi=r['result']['roi'],tail=r['result']['tail'],proof=r['proof_trace']['summary'],witnesses=r['proof_trace']['witness_count'],unknown=len(r['proof_trace']['unknown']))for s,r in [('off',a),('on',b)]},roi_gain=x['ticks']-y['ticks'],total_gain=x['ticks']+x['flush_tail']-y['ticks']-y['flush_tail'],permitted_followup_cases=[21,18,6,0]if case==19 and gain else[],baseline_reproduced=a['original_lru_on_reproduction'],boundary_join='UNKNOWN_NOT_RECONSTRUCTED',new_DUT_execution=False,raw_parsers_reexecuted=False,parser_results_inherited_with_actual_invocation_and_result_digest=True,analyzer_sha256=sha(__file__))
def verify(path):
 g=read(path);require(g['schema']=='posted-preparation-priority-immutable-terminal-pair-v1'and g['analyzer_sha256']==sha(__file__),'pair schema/analyzer changed');e=g['side_evidence']
 actual=build(e['off']['path'],e['off']['sha256'],e['on']['path'],e['on']['sha256'],{s:e[s]['proof_controls']['path']for s in('off','on')if e[s]['proof_controls'] is not None},{s:e[s]['raw_storage']['path']for s in('off','on')if e[s]['raw_storage']is not None},g['case']);require(exact(g,actual),'closed pair inputs/results changed');return g
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for n in('off','off-sha','on','on-sha','out'):p.add_argument('--'+n,required=True)
 p.add_argument('--proof-controls-off');p.add_argument('--proof-controls-on');p.add_argument('--case',type=int,choices=(19,21),default=19);p.add_argument('--off-raw-storage');a=p.parse_args();r=build(a.off,a.off_sha,a.on,a.on_sha,{'off':a.proof_controls_off,'on':a.proof_controls_on},{'off':a.off_raw_storage}if a.off_raw_storage else{},a.case);save(a.out,r,True);print(json.dumps(r,indent=2))
