#!/usr/bin/env python3
"""Fresh current-source OFF closure after useful ON19 screen; no unequal object reuse."""
from pathlib import Path
import argparse,importlib.util,json,os,sys
import run as r
HERE=r.HERE;MODEL=HERE/'model-off-split';UNSPLIT=HERE/'model-off';CASE=HERE/'case19-off'
r.MODEL=MODEL
read=r.read;save=r.save;sha=r.sha;need=r.need

def freeze():
 p=r.verify();need(read(HERE/'case19/qualification.json')['status']=='PASS_SCOPED_ORIGINAL_ORACLES','ON19 pending')
 need(read(HERE/'case19/qualification.json')['tick_gain']>0,'no gain, do not expand')
 fs=[Path(__file__),HERE/'pins.json',HERE/'supplemental-transitive-closure-r1.json',HERE/'generate-off.receipt.json',HERE/'actual-abi-off.json',HERE/'case19/qualification.json',HERE/'case19-on-archive-receipt.json',HERE/'rv64gc/qualification.json',HERE/'rv64gc/rv64gc.bin',HERE/'rv64gc/step2.receipt.json',r.BASE/'memory-state-reuse-cpu-split-20261011-r1/header_identity.py']
 fs += [UNSPLIT/n for n in ['BoardSocGsim.fir','BoardSocGsim.h','profile.json','actual-parameters.json']]
 need(not(HERE/'off-pins.json').exists(),'fresh off freeze');save(HERE/'off-pins.json',{'schema':'distinct-way-release-fresh-off-v1','files':{str(f):sha(f)for f in fs},'original_pins_sha256':sha(HERE/'pins.json'),'compiler_flags':r.FLAGS,'cpp_max_size_KB':4096,'raw_case_cap_bytes':p['case_cap_bytes'],'source_head':p['head'],'scope':'Current-source OFF original same guest/profile actual execution; ON source unchanged'})

def verify():
 p=r.verify();q=read(HERE/'off-pins.json')
 for f,h in q['files'].items():need(sha(f)==h,'off bound input changed '+f)
 for f,v in read(HERE/'supplemental-transitive-closure-r1.json')['transitive_files'].items():need(sha(f)==v['sha256'],'transitive input changed')
 return p

def actual():
 p=read(MODEL/'profile.json');need(p==read(HERE/'expected-profile-off.json'),'OFF full profile mismatch')
 for n in ['BoardSocGsim.fir','profile.json','actual-parameters.json']:need(sha(MODEL/n)==sha(UNSPLIT/n),'OFF original emission byte drift')
 import profile_abi
 result=profile_abi.verify_actual(MODEL,p)
 sp=importlib.util.spec_from_file_location('off_split_header',r.BASE/'memory-state-reuse-cpu-split-20261011-r1/header_identity.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
 result['split_header_identity']=m.verify(UNSPLIT/'BoardSocGsim.h',MODEL/'BoardSocGsim.h')
 save(HERE/'actual-abi-off-split.json',result);return result

def smoke(p):
 out=HERE/'rv64gc-off';need(not out.exists(),'fresh OFF smoke');out.mkdir()
 old=read(HERE/'rv64gc/step2.receipt.json')['argv'];command=[]
 for word in old:
  if word.endswith('.o'):continue
  word=word.replace(str(HERE/'model-on'),str(MODEL)).replace(str(HERE/'rv64gc/smoke'),str(out/'smoke'));command.append(word)
 at=command.index('-ldl');command[at:at]=[str(f.with_suffix('.o'))for f in r.units()]
 steps=[r.execute('link',command,180,out=out)]
 for label,extra,code in [('positive',[],0),('negative',['--inject-mismatch'],1)]:steps.append(r.execute(label,[str(out/'smoke'),str(HERE/'rv64gc/rv64gc.bin'),*extra],180,code,out=out))
 need('RV64GC_BOARD_PASS'in(out/'positive.log').read_text()and'firmware independent anchor/context failure'in(out/'negative.log').read_text(),'OFF GC anchors')
 save(out/'qualification.json',{'status':'PASS_FRESH_OFF_RV64GC_AND_REAL_NEGATIVE','steps':steps,'guest_sha256':sha(HERE/'rv64gc/rv64gc.bin'),'artifacts':r.inventory(out)})

def case(p,force_full):
 need(read(HERE/'rv64gc-off/qualification.json')['status']=='PASS_FRESH_OFF_RV64GC_AND_REAL_NEGATIVE','off GC pending')
 for f,h in read(HERE/'off-model-images.json').items():need(sha(f)==h,'OFF model changed')
 need(not CASE.exists(),'fresh OFF19');CASE.mkdir();steps=[]
 for label in ['positive','trap-negative']:
  env={k:str(CASE/(label+'.'+v+'.jsonl'))for k,v in r.TRACE_ENV.items()}
  steps.append(r.execute(label,[str(MODEL/'host'),str(r.DONOR/'guest.bin'),'19','20']+(['--inject-trap']if label=='trap-negative'else[]),1800,1 if label=='trap-negative'else 0,env,out=CASE,initial=r.FLOOR+p['case_cap_bytes']if label=='positive'else r.FLOOR+32*r.MIB))
  if label=='positive':
   from parser import parse
   result=parse((CASE/'positive.log').read_text(),'on',19);print(json.dumps({'status':'FRESH_OFF_PRIMARY_PASS_RAW_PENDING','ticks':result['ticks'],'flush_tail':result['flush_tail']}),flush=True)
  else:need('independent worksets trap order mismatch'in(CASE/'trap-negative.log').read_text(),'OFF trap rejection reason')
 old=read(r.DONOR/'case19-on-r1/receipt.json');raw={n:v['sha256']for n,v in p['baseline_raw'].items()};raw.update({n:old['artifacts'][n]for n in ['positive.log','trap-negative.log']})
 differences={n:{'original':h,'fresh_off':sha(CASE/n)}for n,h in raw.items()if sha(CASE/n)!=h}
 save(CASE/'raw-comparison.json',{'all_equal':not differences,'differences':differences,'original':raw,'original_receipt_sha256':sha(r.DONOR/'case19-on-r1/receipt.json')})
 if differences or force_full:
  steps.append(r.execute('validate',[sys.executable,'-B',str(Path(__file__)),'validate'],1800,out=CASE));validation=read(CASE/'validation.json')
 else:validation={k:v for k,v in old.items()if k in ['result','owner_trace','canonical_trace','admission_trace','dmmu_trace','unissued_trace','window_trace','proof_trace','lru_trace','boundary_join']}
 need(validation['result']==result and result==old['result'],'current OFF no longer reproduces historical complete result')
 save(CASE/'qualification.json',{'status':'PASS_FRESH_OFF_EXACT_ORIGINAL_CPU_AND_RAW'if not differences else'PASS_FRESH_OFF_ORIGINAL_ORACLES_WITH_RAW_DIFFERENCES','result':result,'validation':validation,'raw_equal':not differences,'full_parser_executed':bool(differences or force_full),'steps':steps,'off_pins_sha256':sha(HERE/'off-pins.json'),'artifacts':r.inventory(CASE),'runtime_executed':True,'object_reused':False})
 need(not differences,'OFF raw differed despite result equality; inspect before pair gate')
 on=read(HERE/'case19/qualification.json');save(HERE/'fresh-pair-case19-qualification.json',{'status':'PASS_FRESH_CURRENT_SOURCE_OFF_ON_CASE19','source_head':p['head'],'source_tree':p['tree'],'off_receipt_sha256':sha(CASE/'qualification.json'),'on_receipt_sha256':sha(HERE/'case19/qualification.json'),'off_ticks':result['ticks'],'on_ticks':on['result']['ticks'],'off_flush':result['flush_tail'],'on_flush':on['result']['flush_tail'],'kernel_ticks_saved':result['ticks']-on['result']['ticks'],'guest_changed':False,'only_treatment_field':'distinctWayRelease','unequal_generated_objects_reused':False,'historical_off_exact_raw':True,'cross_interval_boundary_join':'UNKNOWN_INHERITED_SCOPE'});print(json.dumps(read(HERE/'fresh-pair-case19-qualification.json')))

def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['freeze','generate','abi','compile','host','smoke','case','validate']);a.add_argument('--slot-granted',action='store_true');a.add_argument('--force-full-parse',action='store_true');x=a.parse_args()
 if x.phase=='freeze':freeze();return
 p=verify()
 if x.phase not in ['abi','validate']:need(x.slot_granted,'serial coordinator slot required')
 if x.phase=='generate':
  MODEL.mkdir()
  for n in ['BoardSocGsim.fir','profile.json','actual-parameters.json']:os.link(UNSPLIT/n,MODEL/n)
  r.execute('off-split-generate',[p['tools']['gsim']['path'],'--threads=1','--cpp-max-size-KB=4096','--dir='+str(MODEL),str(MODEL/'BoardSocGsim.fir')],900);actual()
 elif x.phase=='abi':actual();r.execute('off-header-syntax',r.host_command(p,True),120)
 elif x.phase=='compile':
  actual();r.passed('off-header-syntax');steps=[]
  for i,f in enumerate(r.units()):steps.append(r.execute('off-compile-tu-'+str(i),[p['tools']['clang']['path'],*r.FLAGS,'-I'+str(MODEL),'-c',str(f),'-o',str(f.with_suffix('.o'))],1800))
  save(HERE/'off-compile.receipt.json',{'status':'PASS_SERIAL_ALL_TRANSLATION_UNITS','steps':steps,'off_pins_sha256':sha(HERE/'off-pins.json'),'artifacts':r.model_files()})
 elif x.phase=='host':
  q=read(HERE/'off-compile.receipt.json');need(q['status']=='PASS_SERIAL_ALL_TRANSLATION_UNITS','OFF compile incomplete')
  for f,h in q['artifacts'].items():need(sha(f)==h,'OFF compile artifact changed')
  r.execute('off-host',r.host_command(p),180);save(HERE/'off-model-images.json',r.inventory(MODEL))
 elif x.phase=='smoke':smoke(p)
 elif x.phase=='case':case(p,x.force_full_parse)
 elif x.phase=='validate':
  s=importlib.util.spec_from_file_location('original_cpu_runner',r.DONOR/'run.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);save(CASE/'validation.json',m.validate_output(CASE,'on',19))
 verify()
if __name__=='__main__':main()
