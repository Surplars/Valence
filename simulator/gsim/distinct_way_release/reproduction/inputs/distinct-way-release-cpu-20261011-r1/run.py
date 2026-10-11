#!/usr/bin/env python3
"""Exact original Bare COPY, one candidate option, official GSIM split, serial Clang."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,re,shutil,signal,subprocess,sys,time
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
SOURCE=BASE/'distinct-way-release-implementation-20261011-r1/source'
FOCUS=SOURCE.parent/'focused-r2/receipt.json'
DONOR=BASE/'posted-preparation-priority-cpu-host-r2'
OLD=BASE/'posted-preparation-priority-cpu-prep-r1/model-on-r1'
RAW=BASE/'same-set-prefetch-admission-observer-20261011-r1/case19-on-r1'
MODEL=HERE/'model-on';CLASSES=HERE/'fixture-classes';MIB=1024**2;FLOOR=700*MIB
sys.path.insert(0,str(DONOR));import contract as original
FLAGS=original.FLAGS
TRACE_ENV={'POSTED_BANDWIDTH_OWNER_TRACE':'owners','CANONICAL_OVERLAP_TRACE':'canonical','READ_PREFETCH_TRACE':'admission','D_TRANSLATION_TRACE':'dmmu','UNISSUED_STORE_TRACE':'unissued','ROB_WINDOW_TRACE':'window','MEMORY_PROOF_FRONTIER_TRACE':'proof','READY_LOAD_FRONTIER_TRACE':'readiness','STORE_PF_LRU_TRACE':'lru'}
read=original.read;sha=original.sha;save=original.save;need=original.require
spec=importlib.util.spec_from_file_location('distinct_resources',BASE/'frontier-fetch-chain-cpu-prep-r1/resource_monitor.py');monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
def inventory(folder):return {str(p.resolve()):sha(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}
def git(*args):return subprocess.check_output(['git',*args],cwd=SOURCE,text=True).strip()
def freeze():
 need(not (HERE/'pins.json').exists(),'fresh freeze only');focus=read(FOCUS)
 need(focus['status']=='PASS_FRESH_REAL_CACHE_MIXED_HOME_C_BEFORE_E','focused gate missing')
 need(git('rev-parse','HEAD')==focus['source']['head']=='e8c1504da785486d761f213a5e8589a00ba0618c' and not git('status','--porcelain'),'production changed')
 cp=[s.split(':',3)[3] for s in read(SOURCE/'out/IonSoC/test/runClasspath.json')['value']]
 files={};dirs={};absent=[]
 for s in cp:
  p=Path(s)
  if p.is_file():files[s]=sha(p)
  elif p.is_dir():dirs[s]=inventory(p)
  else:absent.append(s)
 fixture=inventory(HERE/'fixture'); tools=read(BASE/'toolchain/tool-receipt.json')['files']
 cache=BASE/'toolchain/env/cache/coursier/https/repo.maven.apache.org/maven2'
 compiler=cache/'org/scala-lang/scala-compiler/2.13.17/scala-compiler-2.13.17.jar'
 plugin=cache/'org/chipsalliance/chisel-plugin_2.13.17/7.3.0/chisel-plugin_2.13.17-7.3.0.jar'
 historical=read(DONOR/'pair-runtime-pins-r1.json');baseline=read(DONOR/'case19-on-r1/receipt.json')
 need(baseline['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN' and baseline['pins_sha256']==sha(DONOR/'pair-runtime-pins-r1.json'),'baseline not terminal/pinned')
 old=historical['models']['on'];need(old['sha256']==sha(old['receipt']),'historical model receipt drift')
 for n,h in read(old['receipt'])['artifacts'].items():need(sha(OLD/n)==h,'old model artifact drift '+n)
 for n,h in historical['base']['files'].items():need(sha(DONOR/n)==h,'old host/parser drift '+n)
 for n,h in historical['base']['guest'].items():need(sha(DONOR/n)==h,'old guest drift '+n)
 raw={n:{'path':str(RAW/n),'sha256':h,'bytes':(RAW/n).stat().st_size} for n,h in baseline['artifacts'].items() if n.startswith(('positive.','trap-negative.')) and n.endswith('.jsonl') and '.resources.'not in n and '.lifetimes.'not in n}
 need(len(raw)==18,'baseline raw set');need(all(sha(v['path'])==v['sha256']for v in raw.values()),'baseline raw bytes drift')
 raw_bytes=sum(x['bytes']for x in raw.values());case_cap=((raw_bytes*115//100+32*MIB+MIB-1)//MIB)*MIB
 inputs={**fixture,**{str(p):sha(p)for p in [Path(__file__),HERE/'expected-profile-off.json',HERE/'expected-profile-on.json',FOCUS,BASE/'toolchain/tool-receipt.json',compiler,plugin,DONOR/'pair-runtime-pins-r1.json',DONOR/'case19-on-r1/receipt.json',OLD/'receipt.json',RAW/'receipt.json']}}
 for p in DONOR.iterdir():
  if p.is_file()and p.suffix in('.py','.h','.hpp','.cpp'):inputs[str(p)]=sha(p)
 for name in ('guest.bin','guest.elf','kernel.bin'):inputs[str(DONOR/name)]=sha(DONOR/name)
 for name in ('board_boot.cpp','rv64gc_board.cpp','board_ddr_multiid.h','board_ddr_benchmark.h'):
  f=SOURCE/'simulator/gsim/harness'/name;need(sha(f)==sha(original.ROOT/'simulator/gsim/harness'/name),'production host dependency changed '+name);inputs[str(f)]=sha(f)
 save(HERE/'pins.json',{'schema':'distinct-way-release-original-cpu-v1','head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'production_files':focus['source']['files'],'files':inputs,'runtime':{'paths':cp,'files':files,'directories':dirs,'absent':absent},'tools':tools,'java':focus['java'],'compiler':str(compiler),'plugin':str(plugin),'canonical_flags':read(BASE/'posted-preparation-priority-cpu-prep-r1/canonical-flags.json')['on'],'guest':historical['base']['guest'],'case':historical['base']['cases']['19'],'baseline_raw':raw,'baseline_raw_bytes':raw_bytes,'case_cap_bytes':case_cap,'cap_derivation':'sum of exact original 18 sidecars +15% +32MiB, rounded up MiB','model_cap_bytes':384*MIB,'floor_bytes':FLOOR,'official_cpp_max_size_KB':4096})
 return {'status':'PINNED_ORIGINAL_INPUTS','case_cap_bytes':case_cap,'baseline_raw_bytes':raw_bytes}
def verify():
 p=read(HERE/'pins.json');need(git('rev-parse','HEAD')==p['head']and not git('status','--porcelain'),'production head/worktree drift')
 for n,h in p['production_files'].items():need(sha(SOURCE/n)==h,'source byte drift '+n)
 for n,h in p['files'].items():need(sha(n)==h,'input changed '+n)
 for v in p['tools'].values():need(sha(v['path'])==v['sha256'],'tool changed')
 need(sha(p['java']['path'])==p['java']['sha256'],'JDK changed')
 for n,h in p['runtime']['files'].items():need(sha(n)==h,'runtime jar changed')
 for n,items in p['runtime']['directories'].items():need(inventory(n)==items,'runtime directory changed '+n)
 for n in p['runtime']['absent']:need(not Path(n).exists(),'runtime resource appeared')
 return p
def environment(p,extra=None):
 env={k:v for k,v in os.environ.items() if k not in('CPATH','CPLUS_INCLUDE_PATH','C_INCLUDE_PATH','LIBRARY_PATH','CXXFLAGS','CPPFLAGS','LDFLAGS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH')}
 env.update({'PATH':':'.join([str(Path(p['java']['path']).parent),str(Path(p['tools']['riscv_gcc']['path']).parent),str(Path(p['tools']['clang']['path']).parent),'/usr/bin','/bin']),'JAVA_HOME':str(Path(p['java']['path']).parents[1]),'JAVA_TOOL_OPTIONS':'-Dfile.encoding=UTF-8','LD_LIBRARY_PATH':str(BASE/'toolchain/env/sysroot/usr/lib/x86_64-linux-gnu'),'ASAN_OPTIONS':'detect_leaks=0','CHISEL_FIRTOOL_PATH':str(BASE/'toolchain/env/firtool-1.135.0'),'LC_ALL':'C.UTF-8',**(extra or{})});return env
def model_files():return {str(f):sha(f)for folder in[MODEL,HERE/'model-off']if folder.exists()for f in folder.iterdir()if f.is_file()}
def execute(label,argv,seconds,expected=0,extra=None,out=HERE,initial=FLOOR+64*MIB):
 p=verify();log=out/(label+'.log');receipt=out/(label+'.receipt.json');need(not log.exists()and not receipt.exists(),'fresh stage '+label);need(shutil.disk_usage(HERE).free>=initial,'disk reservation missing')
 started=time.monotonic();peak=0;guard=None;before=model_files()
 with log.open('x')as f,(out/(label+'.resources.jsonl')).open('x')as stats:
  child=subprocess.Popen(list(map(str,argv)),cwd=SOURCE,env=environment(p,extra),stdout=f,stderr=subprocess.STDOUT,start_new_session=True);print(json.dumps({'started':label,'pid':child.pid}),flush=True)
  while child.poll() is None:
   row={'seconds':time.monotonic()-started,**monitor.samples(child.pid)};peak=max(peak,row['observed_process_tree_RSS_KiB']);stats.write(json.dumps(row)+'\n');stats.flush()
   if row['seconds']>seconds:guard='wall_timeout'
   elif shutil.disk_usage(HERE).free<FLOOR:guard='700MiB_disk_floor'
   elif log.stat().st_size>32*MIB:guard='log_cap'
   elif MODEL.exists() and sum(f.stat().st_size for f in MODEL.iterdir() if f.is_file())>p['model_cap_bytes']:guard='model_cap'
   elif out.name.startswith('case')and sum(f.stat().st_size for f in out.iterdir()if f.is_file())>p['case_cap_bytes']:guard='case19_manifest_plus_margin'
   if guard:
    os.killpg(child.pid,signal.SIGTERM)
    try:child.wait(timeout=8)
    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    break
   time.sleep(1)
 r={'label':label,'argv':list(map(str,argv)),'cwd':str(SOURCE),'environment':extra or{},'fixed_environment':{k:environment(p)[k]for k in('PATH','JAVA_HOME','JAVA_TOOL_OPTIONS','LD_LIBRARY_PATH','ASAN_OPTIONS','CHISEL_FIRTOOL_PATH','LC_ALL')},'pins_sha256':sha(HERE/'pins.json'),'model_inputs':before,'model_outputs':model_files(),'seconds':time.monotonic()-started,'peak_RSS_KiB':peak,'exit':child.returncode,'expected':expected,'guard':guard,'log_sha256':sha(log)}
 save(receipt,r);need(child.returncode==expected and guard is None,'stage failed '+label);need(not re.search(original.SANITIZERS,log.read_text()),'sanitizer failed '+label);verify();return r
def passed(label,out=HERE):
 r=read(out/(label+'.receipt.json'));need(r['pins_sha256']==sha(HERE/'pins.json')and r['exit']==r['expected']and r['guard']is None and sha(out/(label+'.log'))==r['log_sha256'],'stage not passed '+label);return r
def actual(side):
 folder=HERE/('model-'+side);p=read(folder/'profile.json');need(p==read(HERE/('expected-profile-'+side+'.json')),'full actual profile changed')
 a=read(folder/'actual-parameters.json');need(a['entryProfile']==p['profile']and a['expectedCore']==p['core']and a['allActualParametersEqualExpected'],'actual audit mismatch')
 for k,part,n in [('coreParameters','core',6),('ddrParameters','ddr',2),('cacheConcurrency','cache',3)]:need(len(a[k])==n and all(x['values']==p[part]for x in a[k]),'actual constructor mismatch '+k)
 need(len(p['core'])==140 and 'reconstructIssueTokenIndex'not in p['core']and 'sharedMemoryAddressState'not in p['core'],'resource flags polluted baseline')
 import profile_abi
 r=profile_abi.verify_actual(folder,p);save(HERE/('actual-abi-'+side+'.json'),r);return r
def units():
 fs=sorted(MODEL.glob('BoardSocGsim[0-9]*.cpp'),key=lambda p:int(p.stem.removeprefix('BoardSocGsim')));need([p.name for p in fs]==['BoardSocGsim'+str(i)+'.cpp'for i in range(len(fs))]and len(fs)>1,'official split TU set');return fs
def host_command(p,syntax=False):
 return [p['tools']['clang']['path'],*FLAGS,*original.DEFINES,*original.geometry('on'),'-DPREFETCH_CANDIDATE_CYCLES=1','-DMEMORY_PROOF_FRONTIER_ON=1','-DSTORE_PF_LRU_VICTIM_ON=1','-DPOSTED_PREPARATION_PRIORITY_ON=1','-I'+str(MODEL),str(DONOR/'host.cpp'),'-I'+str(SOURCE/'simulator/gsim/harness')]+(['-fsyntax-only']if syntax else[*[str(x.with_suffix('.o'))for x in units()],'-ldl','-o',str(MODEL/'host')])
def smoke(p):
 out=HERE/'rv64gc';need(not out.exists(),'fresh smoke');out.mkdir();f=SOURCE/'fpga/firmware';h=SOURCE/'simulator/gsim/harness';image=out/'rv64gc.bin';ts=p['tools'];objcopy=str(Path(ts['riscv_gcc']['path']).with_name('riscv64-unknown-elf-objcopy'))
 commands=[[ts['riscv_gcc']['path'],'-march=rv64gc','-mabi=lp64d','-mcmodel=medany','-mno-relax','-nostdlib','-nostartfiles','-Wl,--no-relax','-Wl,--build-id=none','-Wl,--defsym=BOARD_RAM_BYTES=2147483648','-Wl,--defsym=BOARD_MONITOR_BASE=4294934528','-T',str(f/'sample_app.ld'),str(f/'rv64gc_smoke.S'),'-o',str(image.with_suffix('.elf'))],[objcopy,'-O','binary',str(image.with_suffix('.elf')),str(image)],[ts['clang']['path'],*FLAGS,*original.DEFINES,*original.geometry('on'),'-I'+str(MODEL),str(h/'rv64gc_board.cpp'),'-I'+str(h),*[str(x.with_suffix('.o'))for x in units()],'-ldl','-o',str(out/'smoke')],[str(out/'smoke'),str(image)],[str(out/'smoke'),str(image),'--inject-mismatch']]
 steps=[execute('step'+str(i),a,300,1 if i==4 else 0,out=out)for i,a in enumerate(commands)]
 need('RV64GC_BOARD_PASS'in(out/'step3.log').read_text()and'firmware independent anchor/context failure'in(out/'step4.log').read_text(),'smoke anchors');save(out/'qualification.json',{'status':'PASS_ACTUAL_RV64GC_AND_NEGATIVE','steps':steps,'artifacts':inventory(out)})
def case(p,force_full=False):
 actual('on');passed('host');need(read(HERE/'rv64gc/qualification.json')['status']=='PASS_ACTUAL_RV64GC_AND_NEGATIVE','smoke gate pending')
 for f,h in read(HERE/'model-images.json').items():need(sha(f)==h,'compiled model changed')
 out=HERE/'case19';need(not out.exists(),'fresh case19');out.mkdir();steps=[]
 for label in ['positive','trap-negative']:
  env={k:str(out/(label+'.'+v+'.jsonl'))for k,v in TRACE_ENV.items()}
  steps.append(execute(label,[str(MODEL/'host'),str(DONOR/'guest.bin'),'19','20']+(['--inject-trap']if label=='trap-negative'else[]),1800,1 if label=='trap-negative'else 0,env,out=out,initial=FLOOR+p['case_cap_bytes']if label=='positive'else FLOOR+32*MIB))
  if label=='positive':
   from parser import parse
   result=parse((out/'positive.log').read_text(),'on',19);print(json.dumps({'status':'POSITIVE_PRIMARY_PASS_RAW_PENDING','ticks':result['ticks'],'flush_tail':result['flush_tail']}),flush=True)
  else:need('independent worksets trap order mismatch'in(out/'trap-negative.log').read_text(),'trap negative reason')
 baseline=read(DONOR/'case19-on-r1/receipt.json');raw={n:v['sha256']for n,v in p['baseline_raw'].items()};raw.update({n:baseline['artifacts'][n]for n in ['positive.log','trap-negative.log']});differences={n:{'original':h,'new':sha(out/n)}for n,h in raw.items()if sha(out/n)!=h}
 save(out/'raw-comparison.json',{'all_equal':not differences,'differences':differences,'original':raw})
 if differences or force_full:
  steps.append(execute('validate',[sys.executable,'-B',str(HERE/'run.py'),'validate'],1800,out=out));validation=read(out/'validation.json')
 else:validation={k:v for k,v in baseline.items() if k in ['result','owner_trace','canonical_trace','admission_trace','dmmu_trace','unissued_trace','window_trace','proof_trace','lru_trace','boundary_join']}
 need(validation['result']==result,'validation primary differs');status='PASS_SCOPED_ORIGINAL_ORACLES'
 save(out/'qualification.json',{'status':status,'steps':steps,'pins_sha256':sha(HERE/'pins.json'),'result':result,'validation':validation,'raw_equal':not differences,'original_ticks':baseline['result']['ticks'],'tick_gain':baseline['result']['ticks']-result['ticks'],'artifacts':inventory(out),'full_parser_executed':bool(differences or force_full),'cross_interval_boundary_join':'UNKNOWN_INHERITED_SCOPE'})
 return {'status':status,'ticks':result['ticks'],'flush_tail':result['flush_tail'],'tick_gain':baseline['result']['ticks']-result['ticks']}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('phase',choices=['freeze','fixture','elab','generate','abi','compile','host','smoke','case','validate','baseline']);ap.add_argument('--side',choices=['off','on'],default='on');ap.add_argument('--slot-granted',action='store_true');ap.add_argument('--force-full-parse',action='store_true');x=ap.parse_args()
 if x.phase=='freeze':print(json.dumps(freeze()));return
 p=verify();cp=p['runtime']['paths'];java=p['java']['path'];cc=p['tools']['clang']['path'];folder=HERE/('model-'+x.side)
 if x.phase not in ['abi','baseline','validate']:need(x.slot_granted,'coordinator slot required')
 if x.phase=='fixture':
  CLASSES.mkdir();execute('fixture-compile',[java,'-Xmx2g','-XX:ActiveProcessorCount=2','-cp',':'.join([p['compiler'],*cp]),'scala.tools.nsc.Main','-classpath',':'.join(cp),'-Xplugin:'+p['plugin'],'-d',str(CLASSES),*[str(f)for f in sorted((HERE/'fixture').glob('*.scala'))]],600);save(HERE/'fixture-classes.json',inventory(CLASSES))
 elif x.phase=='elab':
  passed('fixture-compile');need(inventory(CLASSES)==read(HERE/'fixture-classes.json'),'fixture changed');folder.mkdir();options=p['canonical_flags']+(['--distinct-way-release']if x.side=='on'else[]);execute('elab-'+x.side,[java,'-Xmx2g','-XX:ActiveProcessorCount=2','-Dchisel.project.root='+str(SOURCE),'-cp',':'.join([str(CLASSES),*cp]),'ooo.DistinctWayReleaseCpuGsimMain',str(folder),x.side,*sorted(options)],900)
 elif x.phase=='generate':
  passed('elab-'+x.side);execute('generate-'+x.side,[p['tools']['gsim']['path'],'--threads=1',*(['--cpp-max-size-KB=4096']if x.side=='on'else[]),'--dir='+str(folder),str(folder/'BoardSocGsim.fir')],900);actual(x.side)
 elif x.phase=='baseline':
  actual('off');old=read(OLD/'receipt.json');eq={n:sha(folder/n)==old['artifacts'][n] for n in ['BoardSocGsim.h','BoardSocGsim0.cpp']};save(HERE/'baseline-byte-closure.json',{'exact_generated_equal':all(eq.values()),'equality':eq,'old_receipt':str(OLD/'receipt.json'),'old_receipt_sha256':sha(OLD/'receipt.json'),'old_object_sha256':sha(OLD/'BoardSocGsim0.o'),'new_generated':{n:sha(folder/n)for n in eq},'object_reused':False,'historical_result':str(DONOR/'case19-on-r1/receipt.json')});print(json.dumps(eq))
 elif x.phase=='abi':actual('on');execute('header-syntax',host_command(p,True),120)
 elif x.phase=='compile':
  actual('on');passed('generate-on');passed('header-syntax');steps=[]
  for i,f in enumerate(units()):
   label='compile-tu-'+str(i);steps.append(execute(label,[cc,*FLAGS,'-I'+str(MODEL),'-c',str(f),'-o',str(f.with_suffix('.o'))],1800))
  save(HERE/'compile.receipt.json',{'status':'PASS_SERIAL_ALL_TRANSLATION_UNITS','pins_sha256':sha(HERE/'pins.json'),'flags':FLAGS,'steps':steps,'artifacts':model_files()})
 elif x.phase=='host':need(read(HERE/'compile.receipt.json')['status']=='PASS_SERIAL_ALL_TRANSLATION_UNITS','compile pending');execute('host',host_command(p),180);save(HERE/'model-images.json',inventory(MODEL))
 elif x.phase=='smoke':passed('host');smoke(p)
 elif x.phase=='case':print(json.dumps(case(p,x.force_full_parse)))
 elif x.phase=='validate':
  s=importlib.util.spec_from_file_location('original_cpu_runner',DONOR/'run.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);save(HERE/'case19/validation.json',m.validate_output(HERE/'case19','on',19))
if __name__=='__main__':main()
