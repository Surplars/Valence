#!/usr/bin/env python3
"""Necessary Sv39 companion using the already qualified distinct-way ON model."""
from pathlib import Path
import argparse,importlib.util,json,sys
import run as r
HERE=r.HERE;CASE=HERE/'case21';read=r.read;sha=r.sha;save=r.save;need=r.need
BASE_VERIFY=r.verify
MANIFEST=r.BASE/'closed-priority-case21-on-positive-archive-r1/SCOPE.json'
OLD_RECEIPT=r.DONOR/'case21-on-r1/receipt.json'
RETRY=r.BASE/'memory-state-reuse-cpu-case21-retry-20261011-r1/contract.json'
def freeze():
 p=BASE_VERIFY();need(read(HERE/'fresh-pair-case19-qualification.json')['status']=='PASS_FRESH_CURRENT_SOURCE_OFF_ON_CASE19','current-source pair gate pending')
 old=read(OLD_RECEIPT);need(old['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and old['case']==21,'original Sv39 receipt identity')
 manifest=read(MANIFEST);entries={Path(x['path']).name:x for x in manifest['entries']};raw={}
 for n,h in old['artifacts'].items():
  if not(n.startswith(('positive.','trap-negative.'))and n.endswith('.jsonl'))or'.resources.'in n or'.lifetimes.'in n:continue
  if n.startswith('positive.'):
   e=entries[n];need(e['sha256']==h,'original21 manifest/hash mismatch');raw[n]={'sha256':h,'bytes':e['size'],'original_manifest_path':str(MANIFEST)}
  else:
   f=r.DONOR/'case21-on-r1'/n;need(sha(f)==h,'original21 negative changed');raw[n]={'sha256':h,'bytes':f.stat().st_size,'original_file':str(f)}
 need(len(raw)==18,'original21 raw set');c=read(RETRY)
 need(sum(v['bytes']for n,v in raw.items()if n.startswith('positive.'))==c['expected_positive_nine_raw_bytes']==1417448926,'positive21 size drift')
 need(sum(v['bytes']for n,v in raw.items()if n.startswith('trap-negative.'))==c['expected_negative_nine_raw_bytes']==12230682,'negative21 size drift')
 expected=sum(v['bytes']for v in raw.values())+c['optional_original_derived_lifetime_bytes'];cap=c['output_cap_bytes'];need(expected==1464074471 and cap-expected==146538265,'case21 explicit margin changed')
 files=[Path(__file__),HERE/'pins.json',HERE/'model-images.json',HERE/'fresh-pair-case19-qualification.json',HERE/'supplemental-transitive-closure-r1.json',OLD_RECEIPT,MANIFEST,RETRY,HERE/'rv64gc/qualification.json']
 need(not(HERE/'case21-contract.json').exists(),'fresh21 contract');save(HERE/'case21-contract.json',{'schema':'distinct-way-release-sv39-companion-v1','files':{str(f):sha(f)for f in files},'case':r.original.CASES[21],'raw':raw,'expected_with_derived_bytes':expected,'output_cap_bytes':cap,'margin_bytes':cap-expected,'current_authorized_cap_GiB':1.5,'floor_bytes':r.FLOOR,'admission_bytes':cap+r.FLOOR,'bound_reason':'Original full raw manifest + original derived lifetime size +146538265B metadata/margin; cap1610612736B is1.5GiB, not inherited case19 cap','on_model_reused_byte_exact':True,'host_reused_byte_exact':True,'new_DUT_execution_required':True})
def verify():
 p=BASE_VERIFY();c=read(HERE/'case21-contract.json')
 for f,h in c['files'].items():need(sha(f)==h,'case21 binding changed '+f)
 for f,v in read(HERE/'supplemental-transitive-closure-r1.json')['transitive_files'].items():need(sha(f)==v['sha256'],'transitive change')
 for f,h in read(HERE/'model-images.json').items():need(sha(f)==h,'ON model changed')
 p=dict(p);p['case_budget_bytes']=c['output_cap_bytes'];p['case_cap_bytes']=c['output_cap_bytes'];return p
# Same guarded runner, now using the explicitly frozen case21 budget and closure.
r.verify=verify

def case(force_full):
 p=verify();c=read(HERE/'case21-contract.json');need(not CASE.exists(),'fresh21 execution');CASE.mkdir();steps=[]
 for label in ['positive','trap-negative']:
  env={k:str(CASE/(label+'.'+v+'.jsonl'))for k,v in r.TRACE_ENV.items()}
  steps.append(r.execute(label,[str(r.MODEL/'host'),str(r.DONOR/'guest.bin'),'21','22']+(['--inject-trap']if label=='trap-negative'else[]),1800,1 if label=='trap-negative'else 0,env,out=CASE,initial=c['admission_bytes']if label=='positive'else r.FLOOR+32*r.MIB))
  if label=='positive':
   from parser import parse
   result=parse((CASE/'positive.log').read_text(),'on',21);print(json.dumps({'status':'SV39_PRIMARY_PASS_RAW_PENDING','ticks':result['ticks'],'flush_tail':result['flush_tail']}),flush=True)
  else:need('independent worksets trap order mismatch'in(CASE/'trap-negative.log').read_text(),'Sv39 negative rejected incorrectly')
 old=read(OLD_RECEIPT);raw={n:v['sha256']for n,v in c['raw'].items()};raw.update({n:old['artifacts'][n]for n in ['positive.log','trap-negative.log']});differences={n:{'original':h,'new':sha(CASE/n)}for n,h in raw.items()if sha(CASE/n)!=h};save(CASE/'raw-comparison.json',{'all_equal':not differences,'differences':differences,'expected':raw})
 if differences or force_full:
  steps.append(r.execute('validate',[sys.executable,'-B',str(Path(__file__)),'validate'],1800,out=CASE));validation=read(CASE/'validation.json')
 else:validation={k:v for k,v in old.items()if k in ['result','owner_trace','canonical_trace','admission_trace','dmmu_trace','unissued_trace','window_trace','proof_trace','lru_trace','boundary_join']}
 need(validation['result']==result,'Sv39 primary mismatch');save(CASE/'qualification.json',{'status':'PASS_DISTINCT_WAY_SV39_ORIGINAL_ORACLES','case':21,'result':result,'validation':validation,'raw_equal':not differences,'full_parser_executed':bool(differences or force_full),'case21_contract_sha256':sha(HERE/'case21-contract.json'),'original_receipt_sha256':sha(OLD_RECEIPT),'steps':steps,'artifacts':r.inventory(CASE),'original_ticks':old['result']['ticks'],'tick_gain':old['result']['ticks']-result['ticks'],'guest_changed':False,'new_execution':True,'cross_interval_boundary_join':'UNKNOWN_INHERITED_SCOPE'});print(json.dumps({'status':'PASS_DISTINCT_WAY_SV39_ORIGINAL_ORACLES','ticks':result['ticks'],'flush_tail':result['flush_tail'],'tick_gain':old['result']['ticks']-result['ticks']}))
def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['freeze','case','validate']);a.add_argument('--slot-granted',action='store_true');a.add_argument('--force-full-parse',action='store_true');x=a.parse_args()
 if x.phase=='freeze':freeze();return
 verify()
 if x.phase=='case':need(x.slot_granted,'coordinator slot required');case(x.force_full_parse)
 else:
  s=importlib.util.spec_from_file_location('original_cpu_runner',r.DONOR/'run.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);save(CASE/'validation.json',m.validate_output(CASE,'on',21))
 verify()
if __name__=='__main__':main()
