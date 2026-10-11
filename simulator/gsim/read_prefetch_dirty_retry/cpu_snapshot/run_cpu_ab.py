#!/usr/bin/env python3
"""Narrow matching-board B OFF/ON adaptation; source freeze never emits or runs DUT."""
import argparse,copy,hashlib,json,os,pathlib,re,shlex,shutil,subprocess,time
HERE=pathlib.Path(__file__).resolve().parent; CAND=HERE.parent; BASE=CAND.parent
ROOT=CAND/'cpu-source'; ORIGIN=CAND/'source'; QUAL=BASE/'cpu-board-fabric-ab'; OLD=QUAL/'B/model'
LEDGER=BASE/'cpu-board-supply-ledger-r2'; HOST=HERE/'harness'; FW=BASE/'cpu-supply-f722/guest'; TOOL=BASE/'toolchain'
CXX=TOOL/'sysroot/usr/bin/clang++-19'; GSIM=TOOL/'gsim-src/build/gsim/gsim'; RECEIPT=HERE/'receipt.json'
COMMIT='f99598c3d409a9866f6d2357735ee3e97ad7cd58'; PROD='28a8b30e55fbfc7dde88dbb7ee38d4bc3b9d730e'
q=json.loads((QUAL/'receipt.json').read_text()); b=q['modes']['B']; plan=json.loads((CAND/'cpu-source-plan.json').read_text())
# Existing qualified structural typing adapter omitted by the initial five-file plan.
extra_wrapper='src/test/scala/ooo/PostedStoreBoardLineageGsim.scala'
plan['wrappers'][extra_wrapper]=q['inputs'][extra_wrapper]
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(pathlib.Path(p).read_text())
def save():RECEIPT.write_text(json.dumps(state,indent=2)+'\n')
def parse(text,prefix):return dict(w.split('=',1) for w in next(l for l in text.splitlines() if l.startswith(prefix+' ')).split()[1:])
def files(root):return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not any(x in p.parts for x in ('out','__pycache__','.git'))}
def own():return {str(p.relative_to(HERE)):sha(p) for p in sorted([*HERE.glob('*.h'),*HERE.glob('*.cpp'),HERE/'run_cpu_ab.py',*HOST.glob('*')]) if p.is_file()}
def check_map(root,values):
 for n,h in values.items():assert sha(root/n)==h,('hash drift',str(root/n))
def guard():
 check_map(ROOT,state['inputs']);assert files(ROOT)==state['inputs'],'source additions/removals';assert own()==state['host_inputs']
 check_map(FW,state['guest']);check_map(pathlib.Path('/'),state['tools']);check_map(pathlib.Path('/'),state['qualified_inputs'])
 for item in state['modes'].values():check_map(pathlib.Path('/'),item.get('reuse_dependency_sha256',{}))
 assert sha(__file__)==state['runner_sha256'];assert q['flags']==state['flags'];check_map(OLD,b['generated']);check_map(OLD,b['objects'])
def gate():
 a=load(HERE/'authorization.json');f=pathlib.Path(a['focused_receipt']);proof=load(f)
 assert a['slot_granted_by_parent'] is True and a['production_checkpoint']==PROD
 assert sha(f)==a['focused_receipt_sha256'] and proof['status'].startswith('PASS')
 assert a['cpu_source_sha256']==sha(HERE/'source-manifest.json');state['authorization']=a
 # Focused tests may have a later test-only commit, but actual production must match.
 for n,h in state['qualification_bridge'].items():
  assert sha(ORIGIN/n)==h and proof['inputs'].get(n)==h,('focused production/config drift',n)
 state['focused_bridge']={'source_head':proof['source_head'],'production_config_equal':True,'test_source_differences':[n for n,h in state['inputs'].items() if n in proof['inputs'] and proof['inputs'][n]!=h]}
def step(label,argv,expected=0,anchor=None,cwd=ROOT):
 guard();original_label=label;attempt=0;log=HERE/(label+'.log')
 while log.exists():
  attempt+=1;label=original_label+'-retry-'+str(attempt);log=HERE/(label+'.log')
 start=time.monotonic();print('START',label,flush=True)
 with log.open('x') as f:p=subprocess.run(list(map(str,argv)),cwd=cwd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
 text=log.read_text();state['commands'].append({'name':label,'runner_sha256':sha(__file__),'argv':list(map(str,argv)),'cwd':str(cwd),'exit':p.returncode,'expected':expected,'binary_sha256':sha(argv[0]) if pathlib.Path(argv[0]).name=='run' else None,'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
 assert p.returncode==expected and (anchor is None or anchor in text),(label,p.returncode,text[-5000:]);return text
def constructor(model,on):
 expected=load(OLD/'profile.json');expected['profile']['readPrefetchDirtyRetry']=on;expected['cache']['readPrefetchDirtyRetry']=on
 assert load(model/'profile.json')==expected,'complete actual profile drift'
 fabric=load(OLD/'actual-fabric.json');fabric['cache']['readPrefetchDirtyRetry']=on
 assert load(model/'actual-fabric.json')==fabric,'complete actual fabric drift'
 assert (model/'assembly-contract.json').read_bytes()==(OLD/'assembly-contract.json').read_bytes(),'assembly bytes drift'
 assert (model/'options.txt').read_text().splitlines()==b['options']+(['--read-prefetch-dirty-retry'] if on else [])
def summarize_origins(work):
 result={}; lines={}
 for text in (work/'supply-events.tsv').read_text().splitlines():
  w=text.split('\t'); kind=w[0]
  if kind not in ['CANDIDATE','ALLOC','CONSUME','WB_CAPTURE']:continue
  v=list(map(int,w[1:]));region=v[1]
  if kind=='CANDIDATE':origin='store' if v[3] else 'read';pa=v[2]
  elif kind=='CONSUME':origin='store' if v[2] else 'read';pa=v[3]
  else:
   origin=('store' if v[6] else 'read') if v[5] else 'demand';pa=v[4] if kind=='ALLOC' else v[7]
  key=f'{region}:{origin}:{kind}';result[key]=result.get(key,0)+1
  line=f'{region}:{origin}:{pa:#x}';entry=lines.setdefault(line,{});entry[kind]=entry.get(kind,0)+1
 path=work/'origin-line-counts.json';path.write_text(json.dumps(lines,indent=2)+'\n')
 return {'events_by_region_origin_kind':result,'line_counts_sha256':sha(path),'classification':'origin captured at allocation, retained through WB; no late store-token recheck'}
def partial_reuse(model,m):
 assert state['authorization'].get('off_tu_reuse_granted') is True
 assert m['generated']['BoardSocGsim.h']==b['generated']['BoardSocGsim.h']
 units=sorted(model.glob('BoardSocGsim[0-9]*.cpp'))
 assert set(m['generated'])==set(b['generated'])
 same=[p for p in units if sha(p)==b['generated'][p.name]]
 assert same and len(same)<len(units)
 for p in units:
  assert re.findall(r'^#include.*$',p.read_text(),re.M)==['#include "BoardSocGsim.h"']
 probe=same[0];deps=[]
 for kind,directory in [('qualified-current',OLD),('new',model)]:
  text=step('off-'+kind+'-include-dependencies',[CXX,*state['flags'],'-I'+str(directory),'-M','-MT','unit',directory/probe.name])
  paths={str(pathlib.Path(x).resolve()) for x in shlex.split(text.replace('\\\n',' ').split(':',1)[1])}
  paths-={str((directory/probe.name).resolve()),str((directory/'BoardSocGsim.h').resolve())};deps.append(paths)
 assert deps[0]==deps[1],'transitive include path drift'
 m['reuse_dependency_sha256']={p:sha(p) for p in sorted(deps[0])}
 m['reuse_dependency_scope']='Current compiler-resolved transitive includes identical for old/new source paths. Original receipt did not record historical system header hashes; no retrospective historical hash claim. Reuse explicitly authorized in this same toolchain environment.'
 m['translation_units']={}
 for p in same:
  obj=p.with_suffix('.o');assert sha(OLD/obj.name)==b['objects'][obj.name];shutil.copy2(OLD/obj.name,obj)
  m['translation_units'][p.name]={'object':obj.name,'provenance':'REUSED_BYTE_IDENTICAL_TU','cpp_sha256':sha(p),'header_sha256':sha(model/'BoardSocGsim.h'),'object_sha256':sha(obj),'original_qualified_receipt_sha256':sha(QUAL/'receipt.json')}
 save();return {p.name for p in same}
def flags(mode,model):return [*state['flags'],'-DREAD_PREFETCH_DIRTY_RETRY='+str(int(mode=='on')),'-I'+str(model),'-I'+str(FW),'-I'+str(HOST)]
ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['freeze','host-syntax','emit','generate','compile','run']);ap.add_argument('--mode',choices=['off','on']);ap.add_argument('--case',choices=['sv39','bare']);a=ap.parse_args()
if a.stage=='freeze':
 assert not RECEIPT.exists();assert b['status']=='COPY_TWO_MODES_PASS' and len(b['objects'])==34
 assert sha(OLD/'profile.json')==plan['existing_B_profile_sha256'];assert sha(OLD/'actual-fabric.json')==plan['existing_B_fabric_sha256']
 assert subprocess.check_output(['git','-C',str(ORIGIN),'diff',PROD,COMMIT,'--','src/main']).strip()==b''
 tree=subprocess.check_output(['git','-C',str(ORIGIN),'ls-tree','-r',COMMIT],text=True).splitlines()
 tracked=[line.split('\t',1)[1] for line in tree if line.split()[1]=='blob']
 wrapper_changes={};
 for n in tracked:
  if n in plan['wrappers']:continue
  expected=subprocess.check_output(['git','-C',str(ORIGIN),'show',COMMIT+':'+n]);assert (ROOT/n).read_bytes()==expected,('tracked source drift',n)
 for n,h in plan['wrappers'].items():
  origin=pathlib.Path(plan['wrapper_source'])/n;assert sha(origin)==h
  expected=origin.read_bytes()
  if n.endswith('CpuMatchingBoardProfileGsimMain.scala'):
   expected=expected.replace(b'"--line-read-channel", "--split-prefetch-tracking",',b'"--line-read-channel", "--split-prefetch-tracking", "--read-prefetch-dirty-retry",')
  assert (ROOT/n).read_bytes()==expected;wrapper_changes[n]={'origin_sha256':h,'prepared_sha256':sha(ROOT/n)}
 sources=files(ROOT);(HERE/'source-manifest.json').write_text(json.dumps(sources,indent=2)+'\n')
 required=[QUAL/'receipt.json',QUAL/'f6b0-production-binding.json',QUAL/'service-controls-receipt.json',LEDGER/'receipt.json',CAND/'cpu-source-plan.json',HERE/'source-manifest.json',OLD/'profile.json',OLD/'actual-fabric.json',OLD/'assembly-contract.json',OLD/'options.txt']
 required += [pathlib.Path(n) if pathlib.Path(n).is_absolute() else BASE/'matching-board-fabric/source'/n for n in q['inputs']]
 required += [LEDGER/n for n in load(LEDGER/'receipt.json')['observer_sources']]
 for n,h in q['inputs'].items():assert sha(pathlib.Path(n) if pathlib.Path(n).is_absolute() else BASE/'matching-board-fabric/source'/n)==h
 for n,h in q['guest'].items():assert sha(FW/n)==h
 for n,h in q['tools'].items():assert sha(n)==h
 tools={**q['tools'],**{str(p.resolve()):sha(p.resolve()) for p in [TOOL/'activate.sh',TOOL/'bin/mill',TOOL/'firtool-1.135.0/firtool',TOOL/'jdk21/bin/java']}}
 state={'status':'SOURCE_FROZEN_NO_DUT_EMISSION','source_commit':COMMIT,'production_checkpoint':PROD,'inputs':sources,'qualification_bridge':{n:h for n,h in sources.items() if n.startswith(('src/main/','fpga/next/')) or n in ['build.mill','.mill-version','.mill-jvm-opts','simulator/gsim/fpga_next_board.py']},'production':{n:h for n,h in sources.items() if n.startswith('src/main/')},'wrappers':wrapper_changes,'host_inputs':own(),'runner_sha256':sha(__file__),'tools':tools,'guest':q['guest'],'flags':q['flags'],'qualified_inputs':{str(p):sha(p) for p in sorted(set(required))},'commands':[],'modes':{m:{'status':'FROZEN','options':b['options']+(['--read-prefetch-dirty-retry'] if m=='on' else []),'cases':{}} for m in ['off','on']},'contract':'Full matching B profile and actual fabric; only new profile/cache readPrefetchDirtyRetry boolean differs. Original guest and independent R32/B32 DDR unchanged. OFF original 105 fields and exact AXI trace must match. ON functional/oracle equivalence, performance/traffic can differ. Actual fabric productionCommit is historical wrapper metadata; source provenance is bound separately. No native physical/CDC qualification.'}
 save();guard();print(state['status']);raise SystemExit
state=load(RECEIPT);guard()
try:
 if a.stage=='host-syntax':
  for mode in ['off','on']:step(mode+'-prepared-host-syntax',[CXX,*flags(mode,OLD),'-fsyntax-only',HERE/'cpu_passive_bandwidth.cpp'])
  state['host_syntax']='PASS_USING_EXISTING_REAL_B_HEADER_ONLY'
 else:
  gate();assert a.mode;mode=a.mode;m=state['modes'][mode];model=HERE/mode/'model'
  if a.stage=='emit':
   assert m['status']=='FROZEN';model.mkdir(parents=True,exist_ok=True);assert not (model/'BoardSocGsim.fir').exists()
   step(mode+'-emit',['mill','-i','IonSoC.test.runMain','ooo.CpuMatchingBoardProfileGsimMain',model,*m['options']]);constructor(model,mode=='on')
   m['emitted']={p.name:sha(p) for p in model.iterdir() if p.is_file()};m['status']='EMITTED_FULL_CONSTRUCTOR_MATCH'
  elif a.stage=='generate':
   assert m['status']=='EMITTED_FULL_CONSTRUCTOR_MATCH';check_map(model,m['emitted']);constructor(model,mode=='on')
   step(mode+'-generate',[GSIM,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/'BoardSocGsim.fir'])
   units=sorted(model.glob('BoardSocGsim[0-9]*.cpp'));assert len(units)>1
   m['generated']={p.name:sha(p) for p in [model/'BoardSocGsim.h',*units]};m['status']='GENERATED'
   if mode=='off':
    same=m['generated']==b['generated'];m['qualified_B_comparison']={'header_and_all_split_cpp_byte_identical':same,'fir_byte_identical':sha(model/'BoardSocGsim.fir')==sha(OLD/'BoardSocGsim.fir'),'actual_parameters_match_except_new_false_fields':True,'qualified_receipt_sha256':sha(QUAL/'receipt.json'),'no_semantic_normalization':True}
    if same:
     check_map(OLD,b['objects']);m['objects']=dict(b['objects']);m['object_directory']=str(OLD);m['object_provenance']='REUSED_ALL_34_QUALIFIED_B_OBJECTS_AFTER_EXACT_GENERATED_BYTE_IDENTITY';m['status']='OBJECTS_READY'
  elif a.stage=='compile':
   assert m['status'] in ['GENERATED','OBJECTS_READY'];check_map(model,m['generated']);constructor(model,mode=='on')
   step(mode+'-actual-host-syntax',[CXX,*flags(mode,model),'-fsyntax-only',HERE/'cpu_passive_bandwidth.cpp'])
   if m['status']=='GENERATED':
    reused=partial_reuse(model,m) if mode=='off' and state['authorization'].get('off_tu_reuse_granted') else set()
    for i,p in enumerate(sorted(model.glob('BoardSocGsim[0-9]*.cpp'))):
     if p.name in reused:continue
     step(mode+'-compile-'+str(i),[CXX,*state['flags'],'-I'+str(model),'-c',p,'-o',p.with_suffix('.o')])
     m.setdefault('translation_units',{})[p.name]={'object':p.with_suffix('.o').name,'provenance':'FRESH_OFFICIAL_SPLIT_TU','cpp_sha256':sha(p),'header_sha256':sha(model/'BoardSocGsim.h'),'object_sha256':sha(p.with_suffix('.o'))}
    m['objects']={p.name:sha(p) for p in sorted(model.glob('*.o'))};m['object_directory']=str(model);m['object_provenance']='MIXED_EXACT_TU_REUSE_NEW_BINARY_NOT_ORIGINAL_MODEL_BYTE_IDENTITY' if reused else 'FRESH_OFFICIAL_GSIM_SPLIT_SERIAL_COMPILE';m['status']='OBJECTS_READY'
   for stem in ['passive','ledger']:
    binary=HERE/mode/('test-'+stem);control_flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DREAD_PREFETCH_DIRTY_RETRY='+str(int(mode=='on'))]
    step(mode+'-'+stem+'-control-build',[CXX,*control_flags,HERE/(stem+'_negative.cpp'),'-o',binary]);step(mode+'-'+stem+'-positive',[binary],anchor='PASS',cwd=HERE/mode)
    tests=['invalid-payload','sum','history','phase','pa','source','bucket'] if stem=='passive' else ['dirty','token','reserved','wb','pa','ack-block','payload','posted-pa','posted-duplicate','posted-generation','posted-missing-install']
    for test in tests:step(mode+'-'+stem+'-negative-'+test,[binary,'--'+test],1,'FAIL',cwd=HERE/mode)
   check_map(pathlib.Path(m['object_directory']),m['objects']);objects=[pathlib.Path(m['object_directory'])/n for n in sorted(m['objects'])]
   step(mode+'-host-link',[CXX,*flags(mode,model),HERE/'cpu_passive_bandwidth.cpp',*objects,'-o',HERE/mode/'run']);m['binary_sha256']=sha(HERE/mode/'run');m['status']='HOST_CONTROLS_PASS'
  elif a.stage=='run':
   assert m['status']=='HOST_CONTROLS_PASS';assert sha(HERE/mode/'run')==m['binary_sha256'];check_map(model,m['generated']);check_map(pathlib.Path(m['object_directory']),m['objects'])
   for vm,name in [(1,'sv39'),(0,'bare')]:
    if a.case and name!=a.case:continue
    work=HERE/mode/name;work.mkdir(exist_ok=True);argv=[HERE/mode/'run',FW/'guest.bin',vm,2,65536,2]
    prior=next((c for c in reversed(state['commands']) if c['name']==mode+'-'+name and c['argv']==list(map(str,argv)) and c['exit']==0 and c['cwd']==str(work) and c.get('binary_sha256')==m['binary_sha256']),None)
    if prior:
     log=HERE/(prior['name']+'.log');assert sha(log)==prior['log_sha256'];text=log.read_text();assert 'CPU_SV39_PASS' in text
     m.setdefault('reparsed_existing_successful_runtime',{})[name]={'log_sha256':sha(log),'reason':'Only duration-dependent fabric.samples was removed from immutable comparison; no DUT or host change, no rerun.','validator_sha256':sha(__file__)}
    else:text=step(mode+'-'+name,argv,anchor='CPU_SV39_PASS',cwd=work)
    row={k:parse(text,p) for k,p in [('result','CPU_SV39_RESULT'),('perf','BOARD_IPC'),('oracle','CPU_SV39_PASS'),('fabric','FABRIC_IDLE_PASS')]};ref=b['cases'][name]
    if mode=='off':
     assert all(row[k]==ref[k] for k in row),'OFF original 105 fields changed';row['exact_original_field_count']=sum(len(row[k]) for k in row)
     if name=='sv39':assert sha(work/'axi-events.tsv')==sha(LEDGER/'axi-events.tsv'),'OFF exact original AXI trace drift'
    else:
     for k in ['mode','op','bytes','reps','retired','pc_hash','loads','stores','lsu_capacity']:assert row['result'][k]==ref['result'][k],('functional drift',name,k)
     assert row['oracle']==ref['oracle'],'golden byte/reply oracle drift'
     assert {k:v for k,v in row['fabric'].items() if k!='samples'}=={k:v for k,v in ref['fabric'].items() if k!='samples'},'fabric service/ownership contract drift'
     assert int(row['fabric']['samples'])>int(row['result']['cycles'])+int(row['result']['clean_tail']),'fabric samples do not cover workload'
    row['origins']=summarize_origins(work);row['counts']=parse(text,'PASSIVE_SUPPLY_COUNTS');row['ledger']=parse(text,'LEDGER_PASS');row['traffic_regions']=[parse(l,'LEDGER_TOTAL') for l in text.splitlines() if l.startswith('LEDGER_TOTAL ')];row['raw']={n:sha(work/n) for n in ['supply-events.tsv','axi-events.tsv']}
    row['comparison']={k:{'B':int(ref['result'][k]),mode:int(row['result'][k]),'delta':int(row['result'][k])-int(ref['result'][k])} for k in ['cycles','clean_tail','ar','aw','r_beats','w_beats','pf_candidates','pf_allocated','pf_useful']}
    m['cases'][name]=row;save();print(mode,name,'PASS',row['comparison'],flush=True)
   for injection,anchor in [('read','CPU read data mismatch'),('memory','final copied/stored memory mismatch'),('trap','unexpected CPU trap cause')]:
    work=HERE/mode/('negative-'+injection);work.mkdir();step(mode+'-negative-'+injection,[HERE/mode/'run',FW/'guest.bin',1,2,4096,1,'--inject-'+injection],1,anchor,cwd=work)
   m['status']='COPY_TWO_MODES_AND_NEGATIVE_CONTROLS_PASS'
 state.pop('failure',None);guard();save();print('STAGE_PASS',a.stage,a.mode,flush=True)
except Exception as e:
 state['failure']={'stage':a.stage,'mode':a.mode,'error':str(e)};save();raise
