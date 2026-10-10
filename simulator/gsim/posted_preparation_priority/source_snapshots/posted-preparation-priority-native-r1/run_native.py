#!/usr/bin/env python3
"""Fresh native OFF/ON exports, using an immutable, source-bound shared classpath."""
import argparse,copy,gzip,hashlib,importlib.util,json,os,re,shutil,signal,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;SOURCE=BASE/'posted-preparation-priority-implementation-r1/source';DONOR=BASE/'posted-preparation-priority-cpu-prep-r1';MIB=1024**2
COMMIT='aa37b6a00666ee9be4284ea1793cd376c0775344';TREE='1944bce144fd9019ee4fc261e236f2a7d61f0d6d'
FIRTOOL_OPTIONS=['--format=fir','--split-verilog','--strip-debug-info','--disable-all-randomization','--default-layer-specialization=disable']
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,j):Path(p).write_text(json.dumps(j,indent=2,sort_keys=True)+'\n')
def inv(p):return {str(f.relative_to(p)):sha(f) for f in sorted(p.rglob('*')) if f.is_file()}
def size(p):return sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) if p.exists() else 0
def load(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def diffs(a,b,path=''):
 if isinstance(a,dict) and isinstance(b,dict):return sum((diffs(a.get(k),b.get(k),path+'/'+k) for k in sorted(set(a)|set(b))),[])
 return [] if a==b else [{'path':path,'off':a,'on':b}]
def source_guard(plan):
 require(sha(HERE/'source-freeze.json')==plan['source_freeze_sha256'],'source freeze drift')
 frozen=read(HERE/'source-freeze.json')
 for n,h in frozen['sources'].items():require(sha(SOURCE/n)==h,'source drift '+n)
 actual={str(p.relative_to(SOURCE)) for p in SOURCE.rglob('*') if p.is_file() and p.relative_to(SOURCE).parts[0] not in ['.git','out']}
 require(actual==set(frozen['sources']),'source inventory drift')
 for n,h in plan['helpers'].items():require(sha(HERE/n)==h,'helper drift '+n)
 for n,h in plan['tools'].items():require(sha(n)==h,'tool drift '+n)
def prepare():
 require(not (HERE/'plan.json').exists(),'fresh plan required')
 profiles={s:read(HERE/f'expected-profile-{s}.json') for s in ['off','on']};delta=diffs(profiles['off'],profiles['on'])
 require(delta==[{'path':'/core/postedPreparationPriority','off':False,'on':True},{'path':'/profile/postedPreparationPriority','off':False,'on':True}],'unrelated profile differences')
 for p in profiles.values():require(tuple(len(p[k]) for k in ['core','profile','cache'])==(140,32,11),'profile arity')
 flags=read(HERE/'canonical-flags.json');require(set(flags['on'])-set(flags['off'])=={'--posted-preparation-priority'} and set(flags['off'])<=set(flags['on']),'option drift')
 ts=read(BASE/'toolchain/tool-receipt.json');tools={ts['files'][k]['path']:ts['files'][k]['sha256'] for k in ['mill_dist','mill_wrapper','firtool']}
 helpers=[str(p.relative_to(HERE)) for p in sorted(HERE.rglob('*')) if p.is_file() and (p.suffix in ['.py','.scala'] or p.name.startswith(('expected-profile','canonical-flags')))]
 p=dict(schema='posted-preparation-priority-native-plan-v1',status='PREPARED_NO_JAVA_OR_NATIVE_RUN',production_commit=COMMIT,production_tree=TREE,source_freeze_sha256=sha(HERE/'source-freeze.json'),helpers={n:sha(HERE/n) for n in helpers},tools=tools,profile_differences=delta,expected_profiles=profiles,canonical_flags=flags,limits=dict(minimum_free_bytes=700*MIB,output_cap_bytes=64*MIB,seconds_per_stage=1800,log_cap_bytes=4*MIB),donor_selected_manifest_sha256='5816b66c2d24348dce31b9ec08bf676b7e1f1eefbd1f95b2c33c085b70666753',donor_compiled_binding_sha256=sha(DONOR/'compiled-classpath-r1.json'),GSIM=False,Clang=False,mapped_PPA_STA=False,production_source_edited=False,compiled_output_copied=False)
 source_guard(p);save(HERE/'plan.json',p);print(json.dumps({'status':p['status'],'plan_sha256':sha(HERE/'plan.json')}))
def paths(p):
 values=read(p)['value'];require(isinstance(values,list),'classpath manifest schema')
 result=[]
 for x in values:
  m=re.fullmatch(r'(?:qref:v1|ref:v0):[^:]+:(/.+)',x);require(m is not None,'classpath reference schema');q=Path(m[1]);require(q.exists() or q.name in ['resources','compile-resources'],'missing non-resource classpath '+str(q));result.append(q)
 return result
def bind_runtime(plan):
 compiled_path=DONOR/'compiled-classpath-r1.json';require(sha(compiled_path)==plan['donor_compiled_binding_sha256'],'donor compiled binding changed');compiled=read(compiled_path)
 require(compiled['source_manifest_sha256']==plan['donor_selected_manifest_sha256'] and compiled['source_binding_sha256']=='ef3788d95fcf3036c712170c8d48d3b7d89416dfcfd831e71081f268cb81eb44','compiled source binding mismatch')
 absent_compile_worker_files=[]
 for n,h in {**compiled['class_files'],**compiled['files']}.items():
  if not Path(n).exists() and str(Path(n)).startswith(str(DONOR/'source/out/mill.javalib.JvmWorkerModule/internalWorker.dest')+'/'):
   absent_compile_worker_files.append(n)
  else:require(sha(n)==h,'donor compilation artifact changed '+n)
 save(HERE/'execution/donor-compiled-binding.json',compiled)
 manifest=DONOR/'SELECTED-SOURCE.json';require(sha(manifest)==plan['donor_selected_manifest_sha256'],'donor source manifest changed');d=read(manifest);f=read(HERE/'source-freeze.json')
 require(d['source_commit']==COMMIT and d['source_before_overlays']==f['sources'],'donor production inventory differs')
 for n,h in d['files'].items():require(sha(DONOR/'source'/n)==h,'donor source changed '+n)
 helpers=['src/test/scala/ooo/'+n for n in ['CanonicalVirtualStoreActualParamsMain.scala','StorePrefetchLruVictimProfiles.scala','MemoryProofFrontierExactGsim.scala','PostedPrefetchBoardProfiles.scala']]
 for n in list(d['production_main_files'])+helpers:require(d['files'][n]==f['sources'][n],'donor native constructor source differs '+n)
 cpfiles={n:DONOR/'source/out/IonSoC/test'/n for n in ['runClasspath.json','scalaCompilerClasspath.json','scalacPluginClasspath.json']}
 classpaths={n:paths(p) for n,p in cpfiles.items()};allpaths=set(sum(classpaths.values(),[]));files={};directories={};absent=[]
 for p in allpaths:
  if not p.exists():absent.append(str(p))
  elif p.is_file():files[str(p)]=sha(p)
  else:
   directories[str(p)]=inv(p)
   for n,h in directories[str(p)].items():files[str(p/n)]=h
 for n,h in files.items():
  if n.endswith('.class'):require(compiled['class_files'].get(n)==h,'actual runtime class differs from compiled binding '+n)
 require(not set(absent_compile_worker_files)&set(files),'absent worker cache unexpectedly required at runtime')
 j=dict(schema='posted-preparation-priority-native-runtime-binding-v1',source_commit=COMMIT,source_manifest_sha256=sha(manifest),matched_production_files=len(d['production_main_files']),matched_native_test_helpers=helpers,classpath_manifests={n:{'path':str(p),'sha256':sha(p)}for n,p in cpfiles.items()},classpaths={n:[str(x)for x in v]for n,v in classpaths.items()},runtime_files=files,runtime_directories=directories,absent_resource_paths=sorted(absent),all_main_bytes_equal=True,passive_cpu_test_overlays=d['passive_overlays'],source_out_edited=False,excluded_absent_compile_worker_cache_files=absent_compile_worker_files)
 save(HERE/'execution/runtime-binding.json',j);return j
def runtime_guard(r):
 for p in r['absent_resource_paths']:require(not Path(p).exists(),'absent classpath resource appeared '+p)
 for p,files in r['runtime_directories'].items():require(inv(Path(p))==files,'classpath directory inventory changed '+p)
 for p,h in r['runtime_files'].items():require(sha(p)==h,'shared runtime changed '+p)
 for v in r['classpath_manifests'].values():require(sha(v['path'])==v['sha256'],'classpath changed')
def sample(pgid):
 rows=[]
 for d in Path('/proc').iterdir():
  if not d.name.isdigit():continue
  try:
   st=(d/'stat').read_text().rsplit(')',1)[1].split()
   if int(st[2])!=pgid:continue
   x=(d/'status').read_text();m=re.search(r'^VmRSS:\s+(\d+)',x,re.M);rows.append({'pid':int(d.name),'rss_kib':int(m[1])if m else 0})
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
 return {'processes':rows,'group_rss_kib':sum(x['rss_kib']for x in rows)}
def stage(label,cmd,plan,state,runtime=None,input_gzip=None):
 source_guard(plan)
 if runtime:runtime_guard(runtime)
 out=HERE/'execution';log=out/(label+'.log');trace=out/(label+'.resources.jsonl');start=time.monotonic();peak=0;reason=None;maxbytes=0;feeder=None
 print('RUN '+label,flush=True)
 with log.open('x')as f,trace.open('x')as t:
  p=subprocess.Popen(cmd,cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT,stdin=subprocess.PIPE if input_gzip else None,start_new_session=True)
  if input_gzip:
   import threading
   def feed():
    try:
     with gzip.open(input_gzip,'rb')as z:shutil.copyfileobj(z,p.stdin,1024**2)
    except BrokenPipeError:pass
    finally:p.stdin.close()
   feeder=threading.Thread(target=feed);feeder.start()
  while True:
   b=size(out);maxbytes=max(maxbytes,b);row={'elapsed_seconds':time.monotonic()-start,'output_bytes':b,**sample(p.pid)};t.write(json.dumps(row)+'\n');t.flush();peak=max(peak,row['group_rss_kib'])
   if shutil.disk_usage(HERE).free<plan['limits']['minimum_free_bytes']:reason='disk_floor'
   elif b>plan['limits']['output_cap_bytes']:reason='output_cap'
   elif time.monotonic()-start>plan['limits']['seconds_per_stage']:reason='wall_timeout'
   elif log.stat().st_size>plan['limits']['log_cap_bytes']:reason='log_cap'
   if reason or p.poll()is not None:break
   time.sleep(1)
  if reason:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.wait(timeout=8)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
  p.wait()
  if feeder:feeder.join(timeout=5)
 rec=dict(label=label,command=cmd,cwd=str(SOURCE),exit=p.returncode,guard=reason,elapsed_seconds=time.monotonic()-start,observed_peak_process_group_rss_kib=peak,observed_peak_output_bytes=maxbytes,log_sha256=sha(log),resource_sha256=sha(trace),stdin_gzip_sha256=sha(input_gzip)if input_gzip else None)
 state['steps'].append(rec);save(out/'receipt.json',state);require(p.returncode==0 and reason is None,'stage failed '+label+': '+str(reason));print('PASS '+label,flush=True)
def audit_profile(side,plan):
 out=HERE/'execution'/side;p=read(out/'profile.json');a=read(out/'actual-parameters.json');require(p==plan['expected_profiles'][side],'all-field profile drift '+side)
 require(a['entryProfile']==p['profile']and a['expectedCore']==p['core'],'actual entry/core drift')
 require(a['allActualParametersEqualExpected']is True and a['hardwareMutation']is False and a['qualificationInherited']is False,'actual audit flags')
 require(a['topClass']=='soc.core.ooo.FpgaNextSocTop','native top mismatch');require(set(a['canonicalOptions'])==set(plan['canonical_flags'][side]),'actual options drift')
 for key,group,count in [('coreParameters','core',6),('cacheConcurrency','cache',3),('ddrParameters','ddr',2)]:
  require(len(a[key])==count and len({x['instancePath']for x in a[key]})==count,'constructor inventory '+key);require(all(x['values']==p[group]for x in a[key]),'constructor values '+key)
 return a
def run(slot):
 require(slot,'coordinator must grant serial Java/native slot');plan=read(HERE/'plan.json');source_guard(plan);out=HERE/'execution';require(not out.exists(),'fresh execution required');require(shutil.disk_usage(HERE).free>800*MIB,'insufficient starting disk reserve')
 tokens=os.environ.get('JAVA_TOOL_OPTIONS','').split();require('-Xmx4g'in tokens and '-XX:ActiveProcessorCount=2'in tokens,'activate pinned constrained toolchain')
 out.mkdir();state=dict(schema='posted-preparation-priority-native-execution-v1',status='RUNNING',plan_sha256=sha(HERE/'plan.json'),steps=[],GSIM=False,Clang=False,mapped_PPA_STA=False);save(out/'receipt.json',state)
 try:
  r=bind_runtime(plan);cp=r['classpaths'];classes=out/'fixture-classes';classes.mkdir();java=shutil.which('java');require(java,'java unavailable')
  compilecmd=[java,'-cp',os.pathsep.join(cp['scalaCompilerClasspath.json']),'scala.tools.nsc.Main','-classpath',os.pathsep.join(cp['runClasspath.json']),'-d',str(classes),'-Xplugin:'+os.pathsep.join(p for p in cp['scalacPluginClasspath.json'] if Path(p).name.startswith('chisel-plugin_')),str(HERE/'fixture/PostedPreparationPriorityNativeProfiles.scala')]
  stage('fixture-compile',compilecmd,plan,state,r)
  fixtureclasses=inv(classes);require(fixtureclasses,'no native fixture classes');save(out/'fixture-class-binding.json',fixtureclasses)
  classpath=os.pathsep.join([str(classes)]+cp['runClasspath.json']);firtool=read(BASE/'toolchain/tool-receipt.json')['files']['firtool']['path']
  for side in ['off','on']:
   dest=out/side;cmd=[java,'-Dchisel.project.root='+str(SOURCE),'-cp',classpath,'ooo.PostedPreparationPriorityNativeMain',str(dest),side];stage(side+'-constructors',cmd,plan,state,r);audit_profile(side,plan)
   fir=dest/'FpgaNextSocTop.fir';raw=fir.read_bytes();firsha=hashlib.sha256(raw).hexdigest();z=dest/'FpgaNextSocTop.fir.gz'
   temporary=dest/'FpgaNextSocTop.fir.gz.tmp'
   with temporary.open('xb')as f:
    with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0)as g:g.write(raw)
    f.flush();os.fsync(f.fileno())
   restored=gzip.decompress(temporary.read_bytes())
   require(restored==raw and hashlib.sha256(restored).hexdigest()==firsha,'FIR CRC/byte/SHA verification failed')
   require(size(out)<=plan['limits']['output_cap_bytes'],'output cap before atomic compression publish')
   require(not z.exists(),'compressed FIR destination exists');temporary.replace(z)
   directory_fd=os.open(dest,os.O_DIRECTORY)
   try:os.fsync(directory_fd)
   finally:os.close(directory_fd)
   require(sha(fir)==firsha,'raw FIR changed before verified archival');fir.unlink();del raw,restored
   (dest/'rtl').mkdir();stage(side+'-native',[firtool,'-',*FIRTOOL_OPTIONS,'-o',str(dest/'rtl')],plan,state,r,z)
   receipt=dict(schema='posted-preparation-priority-native-export-v1',status='PASS_RTL_EXPORT_ONLY',git_head=COMMIT,git_tree=TREE,source_sha256=read(HERE/'source-freeze.json')['sources'],profile=dict(lsu_entries=4,rob_entries=64,physical_registers=64,memory_proof_frontier=True,store_prefetch_lru_victim=True,posted_preparation_priority=side=='on'),full_profile=read(dest/'profile.json'),actual_parameters_sha256=sha(dest/'actual-parameters.json'),fir_sha256=firsha,fir_bytes=len(gzip.decompress(z.read_bytes())),compressed_fir_sha256=sha(z),compressed_fir_lossless_verified=True,rtl_sha256={'rtl/'+k:v for k,v in inv(dest/'rtl').items()},plan_sha256=sha(HERE/'plan.json'),qualification='Native elaboration/lowering only; no mapped PPA/STA');save(dest/'receipt.json',receipt)
  runtime_guard(r);source_guard(plan);require(inv(classes)==fixtureclasses,'fixture compiled classes drift');state['status']='PASS_FRESH_NATIVE_PAIR_EXPORT_ONLY';save(out/'receipt.json',state)
 except BaseException as e:state['status']='FAIL';state['error']=str(e);raise
 finally:save(out/'receipt.json',state)
 print(json.dumps({'status':state['status']}))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','run']);ap.add_argument('--slot-granted',action='store_true');a=ap.parse_args();prepare()if a.action=='prepare'else run(a.slot_granted)
