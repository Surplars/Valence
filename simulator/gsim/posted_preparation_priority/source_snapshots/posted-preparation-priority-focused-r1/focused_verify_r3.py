"""Strict runtime qualification interface. A source/config/model receipt cannot pass."""
from pathlib import Path
import hashlib,json,re
STATUS='PASS_POSTED_PREPARATION_PRIORITY_ACTUAL_FOCUSED'
CASES=('main','older_ready','newly_ready','busy_false','final_drain','long_nonhead','alias_full','alias_partial','pmp_store','unaligned_store','outside_store','atomic_store','virtual_store','strong_mmio','strong_misaligned','strong_pmp_load','irq','fence','context','recovery','token_reuse','backpressure','late_ack','dirty_release','full_owner','wrap')
CHECKS=('real_decoder_fields','main_old_fail_new_pass','oldest_age_ready_preemption','posted_busy_false_and_final_drain','physical_aliases','physical_pmp_and_exclusions','strong_load_boundaries','irq_fence_context_recovery','full_token_reuse','held_payload_backpressure','late_ack_dirty_release_full_owner','generic_off_structural_equivalence','independent_bytes_and_commits','poisoned_oracles','actual_profile_binding')
def require(value,message):
 if not value:raise AssertionError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def file(ref):
 p=Path(ref['path']);require(p.is_absolute()and p.is_file(),'missing absolute artifact')
 require(sha(p)==ref['sha256'],'artifact hash drift '+str(p));return p

def verify(path,digest,*,production_head,tool_receipt_sha256):
 path=Path(path);require(sha(path)==digest,'focused aggregate drift');r=read(path)
 require(r['schema']=='posted-preparation-priority-focused-v1'and r['status']==STATUS,'focused actual runtime not complete')
 require(r['production_head']==production_head and r['tool_receipt_sha256']==tool_receipt_sha256,'focused source/tool binding differs')
 require(r['DUT_executed']is True and r['raw_instruction_decode']is True and r['real_backend_cache']is True,'focused fixture is not actual raw-decoder backend/cache')
 require(set(r['checks'])==set(CHECKS)and all(v=='PASS'for v in r['checks'].values()),'focused check set incomplete')
 require(set(r['sides'])=={'off','on'},'actual OFF/ON pair required')
 profiles={}
 results={}
 for side,detail in r['sides'].items():
  profiles[side]=read(file(detail['profile']))
  binary=file(detail['binary']); host=file(detail['host_source'])
  core=profiles[side]['core'];cache=profiles[side]['cache']
  for k,v in {'robEntries':64,'physicalRegs':64,'memoryEntries':4,'memoryProofFrontier':True,'preparedStoreLookahead':True,'postedStoreMerge':True,'postedPrefetchHeadOffer':True,'precheckedDataRequestFlow':False,'translatedResponseEmptyFlow':False,'postedPreparationPriority':side=='on'}.items():require(core[k]==v,'actual focused core profile '+k)
  for k,v in {'storePrefetchLruVictim':True,'postedPrefetchCoexistence':True,'storeNextLinePrefetch':True,'storePrefetchMruInsertion':True,'prefetchCandidateCycles':1}.items():require(cache[k]==v,'actual focused cache profile '+k)
  for item in detail['model_artifacts']:file(item)
  require(detail['model_artifacts'],'no actual model artifacts')
  require(set(detail['cases'])==set(CASES),'mandatory actual case matrix incomplete')
  results[side]={}
  for name,case in detail['cases'].items():
   step=read(file(case['step']))
   require(step['argv']==[str(binary),'--case',name,'--trace',str(file(case['trace']))],'positive command identity differs')
   require(step['log']==case['log']['path'] and step['log_sha256']==case['log']['sha256'] and step['exit_code']==0 and step['guard']is None,'positive step/log receipt differs')
   require(step['binary_sha256']==sha(binary) and step['binary_unchanged']is True and step['host_unchanged']is True and step['host_sha256']==sha(host) and step['production_head']==production_head and step['tool_receipt_sha256']==tool_receipt_sha256,'runtime source/tool identity drift')
   log=file(case['log']).read_text();require(case['exit_code']==0 and case['guard']is None,'case did not exit cleanly')
   rows=[x for x in log.splitlines()if x.startswith('POSTED_PREPARATION_CASE ')]
   require(len(rows)==1 and 'POSTED_PREPARATION_FOCUSED_PASS'in log,'actual runtime terminal anchors missing')
   row=dict(x.split('=',1)for x in rows[0].split()[1:]);require(row.pop('name')==name,'case identity mismatch')
   metrics={k:int(v)for k,v in row.items()};require(metrics==case['metrics'],'case metrics differ from actual log')
   require(metrics['enabled']==(side=='on')and metrics['witness']>0 and metrics['decoder_checks']>0,'zero/incorrect actual witness')
   require(metrics['bytes']>0 and metrics['requests']==metrics['responses'],'independent byte or accepted response drain missing')
   require(metrics['posted_members']==metrics['posted_drained'],'posted full-token members not drained')
   file(case['trace']);results[side][name]=metrics
  expected_failures={'data':'POSTED_PREPARATION_FAIL posted refill differs from independent original backing bytes',
    'token':'POSTED_PREPARATION_FAIL event has no exact live full-token owner',
    'timing':'POSTED_PREPARATION_FAIL '+('OFF did not miss first legal head stage'if side=='off'else'ON missed first legal head start edge')}
  negatives=detail['negative_controls'];require(len(negatives)==3 and {x['name']for x in negatives}==set(expected_failures),'duplicate or missing poison controls')
  for negative in negatives:
   text=file(negative['log']).read_text();name=negative['name'];step=read(file(negative['step']))
   require(step['argv']==[str(binary),'--case','main','--trace',str(file(negative['trace'])),'--inject-'+name],'poison command identity differs')
   require(step['log']==negative['log']['path'] and step['log_sha256']==negative['log']['sha256'],'poison step/log receipt differs')
   require(step['binary_sha256']==sha(binary) and step['binary_unchanged']is True and step['host_unchanged']is True and step['host_sha256']==sha(host) and step['production_head']==production_head and step['tool_receipt_sha256']==tool_receipt_sha256,'poison source/tool identity drift')
   failures=[x for x in text.splitlines()if x.startswith('POSTED_PREPARATION_FAIL ')]
   require(negative['exit_code']==step['exit_code']==1 and negative['guard']is None and step['guard']is None and failures==[expected_failures[name]]and'POSTED_PREPARATION_FOCUSED_PASS'not in text,'poisoned oracle not rejected by the exact independent boundary')
 require(r['sides']['off']['host_source']['sha256']==r['sides']['on']['host_source']['sha256'],'OFF/ON runtime used different host source')
 a=json.loads(json.dumps(profiles['off']));b=json.loads(json.dumps(profiles['on']))
 a['core']['postedPreparationPriority']=b['core']['postedPreparationPriority']=False
 a['profile']['postedPreparationPriority']=b['profile']['postedPreparationPriority']=False
 require(a==b,'OFF/ON full constructor products differ beyond candidate flag')
 for name in CASES:
  off,on=results['off'][name],results['on'][name]
  for metric in ('byte_digest','retire_digest','retired','traps','cancelled'):
   require(off[metric]==on[metric],name+' architectural OFF/ON metric differs: '+metric)
 off,on=results['off']['main'],results['on']['main']
 require(off['contested']>=2 and off['stage_a']>=2 and off['first_start']>off['first_legal']>0,'OFF missing old-failure witness')
 require(on['contested']>=2 and on['stage_s']>=2 and on['first_start']==on['first_legal']>0,'ON missing first legal head-edge witness')
 require(on['busy_load_blocks']>0 and off['busy_load_blocks']>0,'posted ordinary-load block not observed')
 for side,rows in results.items():
  require(rows['main']['verified_target_pmp']==1 and rows['main']['physical_store_contract']==1,'main lacks independent legal target authority')
  nr=rows['newly_ready'];require(0<nr['first_older_ready']<=nr['first_older_stage']<=nr['first_older_ready']+1,'older-ready first legal stage missed')
  bf=rows['busy_false'];require(bf['raw_competition']>=3 and bf['raw_stage_a']>=2 and bf['raw_stage_s']<=1 and bf['busy_before_store']==0,'busy-false independent selection witness missing')
  require(rows['final_drain']['drain_selection_witness']==1,'final-drain next-stage restoration missing')
  require(rows['token_reuse']['staged_aba_witness']==1,'staged full-token ABA witness missing')
  require(rows['backpressure']['retirement_hold_witness']>0,'completed-head retirement backpressure not exercised')
  require(rows['atomic_store']['atomic_bypasses']==1,'actual atomic bypass absent')
  for name in ('fence','context'):require(rows[name]['boundary_waits']>0 and rows[name]['boundary_retired']==1,'raw system boundary drain witness missing')
  for name in ('late_ack','dirty_release'):require(rows[name]['owner_writebacks']>0 and rows[name]['owner_writeback_completions']==rows[name]['owner_writebacks'],'dirty full-owner writeback drain missing')
  require(rows['late_ack']['max_release_delay']>=200,'held actual ReleaseAck witness missing')
 structural=read(file(r['generic_off']))
 require(structural['status']=='PASS_GENERIC_OFF_STRUCTURAL_EQUIVALENCE'and structural['baseline_head']=='7c5191ed205f9716bc137c09c4ad993afc7755de'and structural['candidate_head']==production_head,'generic OFF structural proof not bound')
 require(structural['comparison']=='exact_semantic_structure'and structural['raw_byte_equality_claimed']is False,'invalid normalized-byte equality claim')
 require(structural['production_body_equal']is True and structural['ports_equal']is True and structural['state_equal']is True,'OFF control/state/ports changed')
 for artifact in structural['artifacts']:file(artifact)
 return {'status':STATUS,'DUT_executed':True,'checks':{k:'PASS'for k in CHECKS},'cases_per_side':len(CASES),'production_head':production_head,'tool_receipt_sha256':tool_receipt_sha256}
