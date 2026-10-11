#!/usr/bin/env python3
"""Official split GSIM recovery; immutable production/FIR; serial unchanged Clang flags."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,signal,subprocess,sys,time
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
SOURCE=BASE/'memory-state-reuse-implementation-20261011-r1/source'
NATIVE=BASE/'memory-state-reuse-native-20261011-r1';FOCUSED=BASE/'memory-state-reuse-focused-20261011-r1'
DONOR=BASE/'posted-preparation-priority-cpu-host-r2';MODEL=HERE/'model-on-on-split-r1';CLASSES=BASE/'memory-state-reuse-cpu-20261011-r1/fixture-classes'
ORIGINAL=BASE/'memory-state-reuse-cpu-20261011-r1';SMOKE=BASE/'memory-state-reuse-gsim-split-smoke-20261011-r1'
FLAGS=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
TRACE_ENV={'POSTED_BANDWIDTH_OWNER_TRACE':'owners','CANONICAL_OVERLAP_TRACE':'canonical','READ_PREFETCH_TRACE':'admission','D_TRANSLATION_TRACE':'dmmu','UNISSUED_STORE_TRACE':'unissued','ROB_WINDOW_TRACE':'window','MEMORY_PROOF_FRONTIER_TRACE':'proof','READY_LOAD_FRONTIER_TRACE':'readiness','STORE_PF_LRU_TRACE':'lru'}
sys.path.insert(0,str(DONOR));import contract as original_contract
_monitor_spec=importlib.util.spec_from_file_location('memory_reuse_cpu_resource_monitor',BASE/'frontier-fetch-chain-cpu-prep-r1/resource_monitor.py')
_monitor=importlib.util.module_from_spec(_monitor_spec);_monitor_spec.loader.exec_module(_monitor);samples=_monitor.samples
read=lambda p:json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def need(x,m):
 if not x:raise RuntimeError(m)
def save(p,r):Path(p).write_text(json.dumps(r,indent=2)+'\n')
def inventory(p):return {str(f.resolve()):sha(f)for f in sorted(Path(p).rglob('*'))if f.is_file()}
def source_inputs():
 fs=[Path(__file__),HERE/'header_identity.py',HERE/'cpu_profile_abi.py',HERE/'test_resource_index.cpp',HERE/'unissued_guard_fixture.hpp',*sorted((HERE/'fixture').glob('*.scala')),*sorted((HERE/'host').glob('*'))]
 fs += [BASE/'posted-preparation-priority-cpu-prep-r1'/n for n in ('contract.py','model.py','profile_abi.py','resource_monitor.py')]
 fs += [BASE/'frontier-fetch-chain-cpu-prep-r1/resource_monitor.py',Path(read(NATIVE/'plan.json')['java']),original_contract.ROOT/'simulator/gsim/posted_cpu/verify_model.py',original_contract.ROOT/'simulator/gsim/posted_board_lineage/profile_check.py',BASE/'same-set-prefetch-admission-observer-20261011-r1/case19-on-r1/receipt.json']
 fs += [ORIGINAL/'pins.json',ORIGINAL/'run.py',ORIGINAL/'compile.receipt.json',ORIGINAL/'compile-sigkill-diagnosis-r1.json',ORIGINAL/'elab.receipt.json',ORIGINAL/'generate.receipt.json',ORIGINAL/'fixture-compile.receipt.json',ORIGINAL/'model-on-on-r1/BoardSocGsim.fir',ORIGINAL/'model-on-on-r1/BoardSocGsim.h',ORIGINAL/'model-on-on-r1/profile.json',ORIGINAL/'model-on-on-r1/actual-parameters.json',HERE/'official-split-smoke.json']
 fs += [f for f in DONOR.iterdir()if f.is_file()and f.suffix in('.py','.h','.hpp','.cpp')]
 fs += [DONOR/'guest.bin',DONOR/'PASSIVE-ABI.json',DONOR/'pair-runtime-pins-r1.json',BASE/'posted-preparation-priority-cpu-prep-r1/canonical-flags.json',SOURCE/'simulator/gsim/harness/board_boot.cpp',SOURCE/'simulator/gsim/harness/rv64gc_board.cpp',SOURCE/'simulator/gsim/harness/board_ddr_multiid.h',SOURCE/'simulator/gsim/harness/board_ddr_benchmark.h',SOURCE/'fpga/firmware/rv64gc_smoke.S',SOURCE/'fpga/firmware/sample_app.ld',NATIVE/'source-freeze.json',NATIVE/'execution/runtime-binding.json',NATIVE/'expected-profile-on-on.json',FOCUSED/'qualification-summary.json',FOCUSED/'raw-manifest-r1.json',BASE/'toolchain/tool-receipt.json']
 for case in(19,21):fs.extend([DONOR/f'case{case}-on-r1/receipt.json',DONOR/f'case{case}-on-r1/positive.log'])
 return {str(f.resolve()):sha(f)for f in fs}
def baseline_raw_resolution():
 result={}
 alias_receipt=BASE/'same-set-prefetch-admission-observer-20261011-r1/case19-on-r1/receipt.json'
 need(sha(alias_receipt)=='322a57467b57bc489b72c447b973d309c69b4dadc8b5d325ee2a8257622d2bbe','successor alias receipt mismatch')
 alias=read(alias_receipt);need(alias['status']=='PASS_PASSIVE_SAME_SET_ADMISSION_GATE'and alias['primary_equal'],'successor raw alias not qualified')
 for case in(19,21):
  receipt=DONOR/f'case{case}-on-r1/receipt.json';r=read(receipt);aliases={}
  for name,h in r['artifacts'].items():
   if not name.startswith(('positive.','trap-negative.'))or not name.endswith('.jsonl'):continue
   locations=[BASE/'same-set-prefetch-admission-observer-20261011-r1'/f'case{case}-on-r1'/name,DONOR/f'case{case}-on-r1'/name]
   found=next((f for f in locations if f.is_file()and sha(f)==h),None)
   aliases[name]={'original_expected_sha256':h,'verified_local_alias':str(found)if found else None,'read_required_for_exact_digest_comparison':False}
  result[str(case)]={'successor_alias_receipt':str(alias_receipt)if case==19 else None,'successor_alias_receipt_sha256':sha(alias_receipt)if case==19 else None,'successor_original_raw_sha256':alias['all_original_raw_equal']if case==19 else None,'receipt_path':str(receipt),'receipt_sha256':sha(receipt),'raw':aliases,'missing_local_raw_policy':'Use original pinned artifact hash; do not open a recycled original path or restore duplicate gigabytes. Any needed content must resolve to a verified alias or authorized archived member.'}
 return result
def freeze():
 need(not (HERE/'pins.json').exists(),'fresh freeze required')
 need(sha(HERE/'host/host.cpp')==sha(DONOR/'host.cpp'),'original CPU host changed')
 changed=[f.name for f in(HERE/'host').iterdir()if sha(f)!=sha(DONOR/f.name)]
 need(changed==['unissued_model_adapter.hpp'],'unexpected host diff '+str(changed))
 need(read(FOCUSED/'qualification-summary.json')['status']=='PASS_FOCUSED_CPU_PENDING','actual focused gate missing')
 tools=read(BASE/'toolchain/tool-receipt.json')['files'];cache=BASE/'toolchain/env/cache/coursier/https/repo.maven.apache.org/maven2'
 compiler=cache/'org/scala-lang/scala-compiler/2.13.17/scala-compiler-2.13.17.jar';plugin=cache/'org/chipsalliance/chisel-plugin_2.13.17/7.3.0/chisel-plugin_2.13.17-7.3.0.jar'
 save(HERE/'pins.json',{'schema':'memory-reuse-board-inputs-v1','source_head':'3969476cad0775f5b6de405502a4e6822f566311','files':source_inputs(),'extra_tools':{str(compiler):sha(compiler),str(plugin):sha(plugin),str(Path(tools['riscv_gcc']['path']).with_name('riscv64-unknown-elf-objcopy')):sha(Path(tools['riscv_gcc']['path']).with_name('riscv64-unknown-elf-objcopy'))},'compiler':str(compiler),'plugin':str(plugin),'java':read(NATIVE/'plan.json')['java'],'tools':tools,'expected_ticks':{'19':[380840,5572],'21':[345578,5565]},'cases':[19,21],'model_budget_bytes':384*1024**2,'official_gsim_cpp_max_size_KB':4096,'split_parent_pins_sha256':sha(ORIGINAL/'pins.json'),'upstream_failed_compile_sha256':sha(ORIGINAL/'compile.receipt.json'),'case_budget_bytes':int(1.1*1024**3),'floor_bytes':700*1024**2,'historical_raw_resolution':baseline_raw_resolution()})
 return {'pins':str(HERE/'pins.json'),'sha256':sha(HERE/'pins.json')}
def verify():
 p=read(HERE/'pins.json');need(sha(ORIGINAL/'pins.json')==p['split_parent_pins_sha256']=='a86fdd52a84151e1432116630a66ec4860dafed93e6387bd81e0d59da44fbc7d','upstream frozen identity changed')
 smoke=read(HERE/'official-split-smoke.json');need(smoke['status']=='PASS_OFFICIAL_FORCED_SPLIT_AND_ORIGINAL_BEHAVIOR','official split smoke incomplete')
 for path,h in smoke['files'].items():need(sha(path)==h,'small split evidence changed')
 need(subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()==p['source_head'],'production source head changed')
 need(source_inputs()==p['files'],'frozen inputs changed')
 for name,h in read(NATIVE/'source-freeze.json')['files'].items():need(sha(SOURCE/name)==h,'production source file changed '+name)
 historical=read(DONOR/'pair-runtime-pins-r1.json')
 for name,h in historical['base']['files'].items():need(sha(DONOR/name)==h,'historical input identity changed '+name)
 for name,h in historical['base']['guest'].items():need(sha(DONOR/name)==h,'historical guest identity changed '+name)
 old_model=historical['models']['on'];need(sha(old_model['receipt'])==old_model['sha256'],'historical model receipt identity changed')
 for f,h in p['extra_tools'].items():need(sha(f)==h,'compiler/plugin changed')
 for x in p['tools'].values():need(sha(x['path'])==x['sha256'],'pinned tool changed')
 b=read(NATIVE/'execution/runtime-binding.json')
 for f in b['absent_resources']:need(not Path(f).exists(),'new unbound runtime resource '+f)
 for f,h in b['files'].items():need(sha(f)==h,'runtime dependency changed')
 for d,items in b['directories'].items():need({str(Path(f).relative_to(d)):h for f,h in inventory(d).items()}==items,'runtime classes changed')
 return p

def execution_environment(p,extra=None):
 # Offline direct tools need no dynamic proxy/options or host include injection.
 env={k:v for k,v in os.environ.items()if k not in ('CPATH','CPLUS_INCLUDE_PATH','C_INCLUDE_PATH','LIBRARY_PATH','CXXFLAGS','CPPFLAGS','LDFLAGS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH')}
 env.update({'PATH':':'.join([str(Path(p['java']).parent),str(Path(p['tools']['riscv_gcc']['path']).parent),str(Path(p['tools']['clang']['path']).parent),'/usr/bin','/bin']),'JAVA_HOME':str(Path(p['java']).parent.parent),'JAVA_TOOL_OPTIONS':'-Dfile.encoding=UTF-8','LD_LIBRARY_PATH':str(BASE/'toolchain/env/sysroot/usr/lib/x86_64-linux-gnu'),'ASAN_OPTIONS':'detect_leaks=0','CHISEL_FIRTOOL_PATH':str(BASE/'toolchain/env/firtool-1.135.0'),'LC_ALL':'C.UTF-8',**(extra or{})})
 return env

def model_artifacts():
 return {str(f):sha(f)for f in MODEL.glob('*')if f.is_file()and f.suffix in('.fir','.cpp','.h','.o','.json')or f.is_file()and f.name=='host'}if MODEL.exists()else{}

def execute(label,argv,seconds,expected=0,env=None,initial=1100*1024**2,out=None):
 p=verify();folder=out or HERE;log=folder/(label+'.log');receipt=folder/(label+'.receipt.json');rs=folder/(label+'.resources.jsonl')
 need(not log.exists()and not receipt.exists(),'fresh stage required '+label);need(shutil.disk_usage(HERE).free>=initial,'insufficient pre-reserved disk budget')
 before=time.monotonic();peak=0;guard=None;model_before=model_artifacts();child_env=execution_environment(p,env)
 with log.open('x')as f,rs.open('x')as stats:
  child=subprocess.Popen(argv,cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,env=child_env)
  print(json.dumps({'started':label,'pid':child.pid,'argv':argv}),flush=True)
  while child.poll()is None:
   row={'seconds':time.monotonic()-before,**samples(child.pid)};peak=max(peak,row['observed_process_tree_RSS_KiB']);stats.write(json.dumps(row)+'\n');stats.flush()
   if row['seconds']>seconds:guard='wall_timeout'
   elif shutil.disk_usage(HERE).free<700*1024**2:guard='700MiB_disk_floor'
   elif log.stat().st_size>32*1024**2:guard='32MiB_log_cap'
   elif MODEL.exists()and sum(x.stat().st_size for x in MODEL.iterdir()if x.is_file())>p['model_budget_bytes']:guard='384MiB_split_model_budget'
   elif out is not None and sum(x.stat().st_size for x in out.iterdir()if x.is_file())>p['case_budget_bytes']:guard='1.1GiB_case_budget'
   if guard:os.killpg(child.pid,signal.SIGTERM);child.wait();break
   time.sleep(1)
 r={'label':label,'argv':argv,'environment':env or{},'fixed_environment':{k:child_env[k]for k in ('PATH','JAVA_HOME','JAVA_TOOL_OPTIONS','LD_LIBRARY_PATH','ASAN_OPTIONS','CHISEL_FIRTOOL_PATH','LC_ALL')},'model_inputs':model_before,'model_outputs':model_artifacts(),'pins_sha256':sha(HERE/'pins.json'),'seconds':time.monotonic()-before,'peak_RSS_KiB':peak,'exit':child.returncode,'expected':expected,'guard':guard,'log_sha256':sha(log)};save(receipt,r);verify();need(child.returncode==expected and guard is None,'stage failed '+label);return r

def actual():
 p=read(MODEL/'profile.json');need(p==read(NATIVE/'expected-profile-on-on.json'),'actual board differs from frozen complete native profile')
 a=read(MODEL/'actual-parameters.json');need(a['entryProfile']==p['profile']and a['expectedCore']==p['core'],'entry actual audit mismatch')
 for k,part,n in [('coreParameters','core',6),('ddrParameters','ddr',2),('cacheConcurrency','cache',3)]:
  need(len(a[k])==n and all(x['values']==p[part]for x in a[k]),'actual constructor mismatch '+k)
 spec=importlib.util.spec_from_file_location('resource_cpu_profile_abi',HERE/'cpu_profile_abi.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 result=mod.verify_actual(MODEL,p)
 spec=importlib.util.spec_from_file_location('strict_split_header',HERE/'header_identity.py');identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
 result['official_split_header_identity']=identity.verify(ORIGINAL/'model-on-on-r1/BoardSocGsim.h',MODEL/'BoardSocGsim.h')
 save(HERE/'actual-abi.json',result);return result

def units():
 fs=sorted(MODEL.glob('BoardSocGsim[0-9]*.cpp'),key=lambda x:int(x.stem.removeprefix('BoardSocGsim')))
 need([f.name for f in fs]==['BoardSocGsim'+str(i)+'.cpp'for i in range(len(fs))],'noncontiguous official TU set');return fs
def objects():return [f.with_suffix('.o')for f in units()]

def host_command(p,syntax=False):
 return [p['tools']['clang']['path'],*FLAGS,*original_contract.DEFINES,*original_contract.geometry('on'),'-DPREFETCH_CANDIDATE_CYCLES=1','-DMEMORY_PROOF_FRONTIER_ON=1','-DSTORE_PF_LRU_VICTIM_ON=1','-DPOSTED_PREPARATION_PRIORITY_ON=1','-DRECONSTRUCT_ISSUE_TOKEN_INDEX=1','-I'+str(MODEL),'-I'+str(SOURCE/'simulator/gsim/harness'),str(HERE/'host/host.cpp')]+(['-fsyntax-only']if syntax else[*[str(f)for f in objects()],'-ldl','-o',str(MODEL/'host')])

def passed_step(name,folder=HERE):
 if name in ('fixture-compile','elab'):
  r=read(ORIGINAL/(name+'.receipt.json'));need(r['pins_sha256']==sha(ORIGINAL/'pins.json')and r['exit']==r['expected']==0 and r['guard']is None and sha(ORIGINAL/(name+'.log'))==r['log_sha256'],'upstream emission gate changed')
  for f,h in r.get('model_outputs',{}).items():need(sha(f)==h,'upstream emission artifact changed')
  return r
 if name=='compile':
  r=read(HERE/'compile.receipt.json');need(r['pins_sha256']==sha(HERE/'pins.json')and r['status']=='PASS_SERIAL_ALL_TRANSLATION_UNITS','split compile aggregate mismatch')
  need(r['units']==[str(f)for f in units()],'translation unit set changed')
  for st in r['steps']:passed_step(st)
  for f,h in r['model_outputs'].items():need(sha(f)==h,'compiled split artifact changed')
  return r
 r=read(folder/(name+'.receipt.json'))
 need(r['pins_sha256']==sha(HERE/'pins.json')and r['exit']==r['expected']and r['guard']is None and sha(folder/(name+'.log'))==r['log_sha256'],'required stage not qualified '+name)
 for f,h in r.get('model_outputs',{}).items():need(sha(f)==h,'stage model artifact changed '+f)
 return r

def smoke(p):
 actual();passed_step('compile');passed_step('header-syntax');out=HERE/'rv64gc';need(not out.exists(),'fresh GC namespace');out.mkdir();image=out/'rv64gc.bin'
 ts=p['tools'];f=SOURCE/'fpga/firmware';h=SOURCE/'simulator/gsim/harness';objcopy=str(Path(ts['riscv_gcc']['path']).with_name('riscv64-unknown-elf-objcopy'))
 commands=[
 [ts['riscv_gcc']['path'],'-march=rv64gc','-mabi=lp64d','-mcmodel=medany','-mno-relax','-nostdlib','-nostartfiles','-Wl,--no-relax','-Wl,--build-id=none','-Wl,--defsym=BOARD_RAM_BYTES=2147483648','-Wl,--defsym=BOARD_MONITOR_BASE=4294934528','-T',str(f/'sample_app.ld'),str(f/'rv64gc_smoke.S'),'-o',str(image.with_suffix('.elf'))],
 [objcopy,'-O','binary',str(image.with_suffix('.elf')),str(image)],
 [ts['clang']['path'],*FLAGS,*original_contract.DEFINES,*original_contract.geometry('on'),'-I'+str(MODEL),str(h/'rv64gc_board.cpp'),'-I'+str(h),*[str(f)for f in objects()],'-ldl','-o',str(out/'smoke')],
 [str(out/'smoke'),str(image)],[str(out/'smoke'),str(image),'--inject-mismatch']]
 steps=[execute('step'+str(i),cmd,300,1 if i==4 else 0,initial=730*1024**2,out=out)for i,cmd in enumerate(commands)]
 need(image.stat().st_size<16384 and 'RV64GC_BOARD_PASS'in(out/'step3.log').read_text()and 'firmware independent anchor/context failure'in(out/'step4.log').read_text(),'original GC positive/negative anchors absent')
 save(out/'qualification.json',{'status':'PASS_ACTUAL_JOINT_ON_RV64GC_AND_NEGATIVE','pins_sha256':sha(HERE/'pins.json'),'steps':steps,'artifacts':inventory(out)})

def run_case(p,case,force_full_parse=False):
 actual();need((HERE/'model-images.json').exists(),'compiled model not frozen')
 for name in ('fixture-compile','elab','generate','tiny-build','tiny-run','tiny-bad-index','tiny-stale-tag','tiny-bad-class','header-syntax','compile','host'):passed_step(name)
 sm=read(HERE/'rv64gc/qualification.json');need(sm['status']=='PASS_ACTUAL_JOINT_ON_RV64GC_AND_NEGATIVE'and sm['pins_sha256']==sha(HERE/'pins.json'),'new model GC gate incomplete')
 for i in range(5):passed_step('step'+str(i),HERE/'rv64gc')
 for f,h in read(HERE/'model-images.json').items():need(sha(f)==h,'model image changed')
 if case==21:need(read(HERE/'case19/qualification.json')['status']=='PASS_EXACT_ORIGINAL_CPU_AND_RAW','case19 exact closure required')
 out=HERE/f'case{case}';need(not out.exists(),'fresh CPU namespace required');out.mkdir()
 steps=[]
 for label in('positive','trap-negative'):
  env={k:str(out/(label+'.'+v+'.jsonl'))for k,v in TRACE_ENV.items()}
  steps.append(execute(label,[str(MODEL/'host'),str(DONOR/'guest.bin'),str(case),str(case+1)]+(['--inject-trap']if label=='trap-negative'else[]),1800,1 if label=='trap-negative'else 0,env,initial=int(1.8*1024**3)if label=='positive'else 730*1024**2,out=out))
  if label=='trap-negative':need('independent worksets trap order mismatch'in(out/'trap-negative.log').read_text(),'negative failed for wrong reason')
 baseline=read(DONOR/f'case{case}-on-r1/receipt.json')
 historical=read(DONOR/'pair-runtime-pins-r1.json')
 need(baseline['pins_sha256']==sha(DONOR/'pair-runtime-pins-r1.json')and baseline['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and baseline['case']==case and baseline['side']=='on','historical qualification identity changed')
 parsers=('run.py','parser.py','canonical_trace.py','admission_trace.py','dmmu_trace.py','unissued_trace.py','window_trace.py','proof_trace.py','lru_trace.py','admission_trace_v1.py','copy_lineage.py')
 for name in parsers:need(sha(DONOR/name)==historical['base']['files'][name],'original parser changed '+name)
 raw={name:h for name,h in baseline['artifacts'].items()if name.startswith(('positive.','trap-negative.'))and name.endswith('.jsonl')and '.resources.'not in name and '.lifetimes.'not in name}
 need(len(raw)==18,'historical raw set differs from 18 original sidecars')
 for name in ('positive.log','trap-negative.log'):raw[name]=baseline['artifacts'][name]
 differences={name:{'expected':h,'actual':sha(out/name)}for name,h in raw.items()if sha(out/name)!=h}
 save(out/'raw-comparison.json',{'all_equal':not differences,'differences':differences,'expected':raw,'original_receipt_sha256':sha(DONOR/f'case{case}-on-r1/receipt.json'),'parser_identity':{n:sha(DONOR/n)for n in parsers}})
 from parser import parse
 result=parse((out/'positive.log').read_text(),'on',case)
 if differences or force_full_parse:
  steps.append(execute('validate',[sys.executable,str(HERE/'run.py'),'validate','--case',str(case)],900,initial=730*1024**2,out=out))
  need(not differences,'raw equality failed; full original parsers completed, explain differences before qualification')
 need(result==baseline['result'],'complete CPU result differs from qualified original')
 need([result['ticks'],result['flush_tail']]==p['expected_ticks'][str(case)],'kernel/flush cycles differ')
 save(out/'qualification.json',{'status':'PASS_EXACT_ORIGINAL_CPU_AND_RAW','case':case,'steps':steps,'pins_sha256':sha(HERE/'pins.json'),'original_receipt_sha256':sha(DONOR/f'case{case}-on-r1/receipt.json'),'original_raw_sha256':raw,'result':result,'artifacts':inventory(out),'forced_full_parser_executed':force_full_parse,'validation_reuse':'Same 18 raw sidecars, exact stdout and original parser identities; historical parsed certificate reused. New DUT, raw host oracle, ABI controls and trap negative all actually executed.','cross_interval_boundary_join':'UNKNOWN, inherited scope; no reconstruction'})
 return {'case':case,'status':'PASS_EXACT_ORIGINAL_CPU_AND_RAW','ticks':result['ticks'],'flush_tail':result['flush_tail']}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('phase',choices=['freeze','tiny','generate','abi','layout','compile','host','smoke','case','validate']);ap.add_argument('--slot-granted',action='store_true');ap.add_argument('--case',type=int,choices=[19,21]);ap.add_argument('--force-full-parse',action='store_true');x=ap.parse_args()
 if x.phase=='freeze':print(json.dumps(freeze()));return
 p=verify();cp=read(NATIVE/'execution/runtime-binding.json')['paths'];java=p['java'];cc=p['tools']['clang']['path']
 if x.phase not in('tiny','abi','layout','validate'):need(x.slot_granted,'coordinator slot not granted')
 if x.phase=='tiny':
  execute('tiny-build',[cc,*FLAGS,*original_contract.geometry('on'),'-DRECONSTRUCT_ISSUE_TOKEN_INDEX=1',str(HERE/'test_resource_index.cpp'),'-o',str(HERE/'test-resource-index')],120,initial=730*1024**2)
  execute('tiny-run',[str(HERE/'test-resource-index')],30,env={'UNISSUED_STORE_TRACE':str(HERE/'tiny-unissued.jsonl')},initial=730*1024**2)
  for mode,message in [('bad-index','fixed queue index outside active geometry'),('stale-tag','unissued live full-token mismatch'),('bad-class','unissued live immutable owner changed')]:
   execute('tiny-'+mode,[str(HERE/'test-resource-index'),'--'+mode],30,1,env={'UNISSUED_STORE_TRACE':str(HERE/('tiny-'+mode+'.jsonl'))},initial=730*1024**2)
   text=(HERE/('tiny-'+mode+'.log')).read_text();need(message in text and 'runtime error:'not in text and 'AddressSanitizer'not in text,'decoder negative rejected for wrong reason '+mode)
 elif x.phase=='generate':
  passed_step('fixture-compile');passed_step('elab');need(not MODEL.exists(),'fresh official split namespace');MODEL.mkdir()
  (MODEL/'BoardSocGsim.fir').symlink_to(ORIGINAL/'model-on-on-r1/BoardSocGsim.fir')
  for name in ('profile.json','actual-parameters.json'):shutil.copy2(ORIGINAL/'model-on-on-r1'/name,MODEL/name)
  execute('generate',[p['tools']['gsim']['path'],'--threads=1','--cpp-max-size-KB=4096','--dir='+str(MODEL),str(MODEL/'BoardSocGsim.fir')],900)
  need(len(units())>1,'official split failed to produce multiple TUs');actual()
 elif x.phase=='abi':actual();execute('header-syntax',host_command(p,True),120,initial=730*1024**2)
 elif x.phase=='layout':
  actual();passed_step('header-syntax')
  spec=importlib.util.spec_from_file_location('strict_split_header',HERE/'header_identity.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h);probe=HERE/'layout-probe.cpp';probe.write_text(h.layout_probe(ORIGINAL/'model-on-on-r1/BoardSocGsim.h'))
  for kind,folder in [('original',ORIGINAL/'model-on-on-r1'),('split',MODEL)]:
   execute('layout-'+kind+'-build',[cc,*FLAGS,'-I'+str(folder),str(probe),'-o',str(HERE/('layout-'+kind))],180,initial=730*1024**2)
   execute('layout-'+kind+'-run',[str(HERE/('layout-'+kind))],30,initial=730*1024**2)
  need((HERE/'layout-original-run.log').read_bytes()==(HERE/'layout-split-run.log').read_bytes(),'actual layout differs')
 elif x.phase=='compile':
  actual();passed_step('generate');passed_step('tiny-build');passed_step('tiny-run');passed_step('header-syntax');passed_step('layout-original-run');passed_step('layout-split-run')
  need((HERE/'layout-original-run.log').read_bytes()==(HERE/'layout-split-run.log').read_bytes(),'actual state size/alignment/offset changed')
  steps=[]
  for i,f in enumerate(units()):
   label='compile-tu-'+str(i);execute(label,[cc,*FLAGS,'-I'+str(MODEL),'-c',str(f),'-o',str(f.with_suffix('.o'))],1800);steps.append(label)
  save(HERE/'compile.receipt.json',{'status':'PASS_SERIAL_ALL_TRANSLATION_UNITS','pins_sha256':sha(HERE/'pins.json'),'units':[str(f)for f in units()],'flags':FLAGS,'steps':steps,'model_outputs':model_artifacts()})
 elif x.phase=='host':actual();passed_step('compile');execute('host',host_command(p),180);save(HERE/'model-images.json',inventory(MODEL))
 elif x.phase=='smoke':smoke(p)
 elif x.phase=='case':need(x.case is not None,'case required');print(json.dumps(run_case(p,x.case,x.force_full_parse)))
 elif x.phase=='validate':
  need(x.case is not None,'case required');spec=importlib.util.spec_from_file_location('unchanged_original_cpu_runner',DONOR/'run.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  save(HERE/f'case{x.case}/validation.json',mod.validate_output(HERE/f'case{x.case}','on',x.case))
if __name__=='__main__':main()
