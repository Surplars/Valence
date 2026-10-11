#!/usr/bin/env python3
"""Case21-only retry after an undersized output cap; immutable tested model and oracle."""
from pathlib import Path
import argparse,importlib.util,json,os,shutil,signal,subprocess,sys,time
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
ORIGINAL=BASE/'memory-state-reuse-cpu-split-20261011-r1'
spec=importlib.util.spec_from_file_location('frozen_split_runner',ORIGINAL/'run.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
sha=old.sha;read=old.read;need=old.need;save=old.save;OUT=HERE/'case21'
def verify():
 c=read(HERE/'contract.json');need(sha(__file__)==c['wrapper_sha256'],'retry wrapper changed')
 for f,h in c['files'].items():need(sha(f)==h,'retry dependency changed '+f)
 need(c['output_cap_bytes']==int(1.5*1024**3)and c['admission_bytes']==int(2.2*1024**3)and c['floor_bytes']==700*1024**2,'approved budget changed')
 p=old.verify();need(sha(ORIGINAL/'pins.json')==c['model_pins_sha256']=='d02a4816bd2e016ad7f694afa6a0158fc06e6374ab55325dd32bfe960c01ad62','actual model identity changed');old.actual()
 for name in ['fixture-compile','elab','generate','tiny-build','tiny-run','tiny-bad-index','tiny-stale-tag','tiny-bad-class','header-syntax','compile','host']:old.passed_step(name)
 for i in range(5):old.passed_step('step'+str(i),ORIGINAL/'rv64gc')
 need(read(ORIGINAL/'rv64gc/qualification.json')['status']=='PASS_ACTUAL_JOINT_ON_RV64GC_AND_NEGATIVE','GC gate missing')
 need(read(ORIGINAL/'case19/qualification.json')['status']=='PASS_EXACT_ORIGINAL_CPU_AND_RAW','case19 gate missing')
 for f,h in read(ORIGINAL/'model-images.json').items():need(sha(f)==h,'model image changed')
 return c,p
def execute(label,argv,expected,env=None):
 c,p=verify();need(shutil.disk_usage(HERE).free >= (c['admission_bytes']if label=='positive'else c['floor_bytes']+30*1024**2),'retry disk admission')
 log=OUT/(label+'.log');receipt=OUT/(label+'.receipt.json');stats=OUT/(label+'.resources.jsonl');need(not log.exists()and not receipt.exists(),'fresh retry stage required')
 before=time.monotonic();peak=0;guard=None;childenv=old.execution_environment(p,env);inputs=old.model_artifacts()
 with log.open('x')as f,stats.open('x')as s:
  child=subprocess.Popen(argv,cwd=old.SOURCE,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,env=childenv);print(json.dumps({'started':label,'pid':child.pid,'argv':argv}),flush=True)
  while child.poll()is None:
   row={'seconds':time.monotonic()-before,**old.samples(child.pid)};peak=max(peak,row['observed_process_tree_RSS_KiB']);s.write(json.dumps(row)+'\n');s.flush()
   if row['seconds']>(900 if label == 'validate' else 1800):guard='wall_timeout'
   elif shutil.disk_usage(HERE).free<c['floor_bytes']:guard='700MiB_disk_floor'
   elif log.stat().st_size>32*1024**2:guard='32MiB_log_cap'
   elif sum(x.stat().st_size for x in OUT.iterdir()if x.is_file())>c['output_cap_bytes']:guard='1.5GiB_case21_budget'
   if guard:os.killpg(child.pid,signal.SIGTERM);child.wait();break
   time.sleep(1)
 r={'label':label,'argv':argv,'environment':env or{},'fixed_environment':{k:childenv[k]for k in ['PATH','JAVA_HOME','JAVA_TOOL_OPTIONS','LD_LIBRARY_PATH','ASAN_OPTIONS','CHISEL_FIRTOOL_PATH','LC_ALL']},'model_inputs':inputs,'model_outputs':old.model_artifacts(),'model_pins_sha256':c['model_pins_sha256'],'retry_contract_sha256':sha(HERE/'contract.json'),'output_cap_bytes':c['output_cap_bytes'],'admission_bytes':c['admission_bytes'],'floor_bytes':c['floor_bytes'],'seconds':time.monotonic()-before,'peak_RSS_KiB':peak,'exit':child.returncode,'expected':expected,'guard':guard,'log_sha256':sha(log)};save(receipt,r);verify();need(child.returncode==expected and guard is None,'retry stage failed '+label);return r

def validate():
 spec=importlib.util.spec_from_file_location('unchanged_original_cpu_runner',old.DONOR/'run.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);save(OUT/'validation.json',m.validate_output(OUT,'on',21))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--slot-granted',action='store_true');ap.add_argument('--validate',action='store_true');ap.add_argument('--force-full-parse',action='store_true');x=ap.parse_args();c,p=verify()
 if x.validate:validate();return
 need(x.slot_granted,'coordinator slot required');need(not OUT.exists(),'fresh case21 retry directory required');need(shutil.disk_usage(HERE).free>=c['admission_bytes'],'case21 retry admission');OUT.mkdir();steps=[]
 for label in ['positive','trap-negative']:
  env={k:str(OUT/(label+'.'+v+'.jsonl'))for k,v in old.TRACE_ENV.items()};argv=[str(old.MODEL/'host'),str(old.DONOR/'guest.bin'),'21','22']+(['--inject-trap']if label=='trap-negative'else[])
  steps.append(execute(label,argv,1 if label=='trap-negative'else 0,env))
  if label=='trap-negative':need('independent worksets trap order mismatch'in(OUT/'trap-negative.log').read_text(),'negative failed for wrong reason')
 baseline=read(old.DONOR/'case21-on-r1/receipt.json');historical=read(old.DONOR/'pair-runtime-pins-r1.json')
 need(baseline['pins_sha256']==sha(old.DONOR/'pair-runtime-pins-r1.json')and baseline['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and baseline['case']==21 and baseline['side']=='on','historical qualification changed')
 parsers=('run.py','parser.py','canonical_trace.py','admission_trace.py','dmmu_trace.py','unissued_trace.py','window_trace.py','proof_trace.py','lru_trace.py','admission_trace_v1.py','copy_lineage.py')
 for name in parsers:need(sha(old.DONOR/name)==historical['base']['files'][name],'original parser changed '+name)
 raw={n:h for n,h in baseline['artifacts'].items()if n.startswith(('positive.','trap-negative.'))and n.endswith('.jsonl')and '.resources.'not in n and '.lifetimes.'not in n};need(len(raw)==18,'raw set changed')
 for name in ['positive.log','trap-negative.log']:raw[name]=baseline['artifacts'][name]
 differences={n:{'expected':h,'actual':sha(OUT/n)}for n,h in raw.items()if sha(OUT/n)!=h};save(OUT/'raw-comparison.json',{'all_equal':not differences,'differences':differences,'expected':raw,'original_receipt_sha256':sha(old.DONOR/'case21-on-r1/receipt.json'),'parser_identity':{n:sha(old.DONOR/n)for n in parsers}})
 from parser import parse
 result=parse((OUT/'positive.log').read_text(),'on',21)
 if differences or x.force_full_parse:
  steps.append(execute('validate',[sys.executable,str(Path(__file__).resolve()),'--validate'],0));need(not differences,'raw equality failed; full original parsers completed, explain differences')
 need(result==baseline['result'],'complete original CPU result differs');need([result['ticks'],result['flush_tail']]==[345578,5565],'kernel/flush differs')
 save(OUT/'qualification.json',{'status':'PASS_EXACT_ORIGINAL_CPU_AND_RAW','case':21,'steps':steps,'model_pins_sha256':c['model_pins_sha256'],'retry_contract_sha256':sha(HERE/'contract.json'),'original_receipt_sha256':sha(old.DONOR/'case21-on-r1/receipt.json'),'original_raw_sha256':raw,'result':result,'artifacts':old.inventory(OUT),'forced_full_parser_executed':x.force_full_parse,'validation_reuse':'Same18raw sidecars, exactstdout and originalparser identities; historical parsed certificate reused. Actual samejointON model/host and original trapnegative executed.','cross_interval_boundary_join':'UNKNOWN, inherited scope; no reconstruction'})
 print(json.dumps({'status':'PASS_EXACT_ORIGINAL_CPU_AND_RAW','case':21,'ticks':result['ticks'],'flush_tail':result['flush_tail']}),flush=True)
if __name__=='__main__':main()
