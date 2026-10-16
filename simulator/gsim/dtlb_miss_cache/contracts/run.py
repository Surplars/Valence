#!/usr/bin/env python3
"""Portable existing-model native MMU contracts. Never builds or modifies a DUT model."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE='50cb0c5d4b17318904d6cf818ad23829821d5d93'
if not __debug__:raise RuntimeError('Run contract checks without Python -O')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
def verify_guests(directory):
 manifest=json.loads((directory/'guest-manifest.json').read_text())
 for row in manifest['variants']:assert sha(directory/(row['name']+'.bin'))==row['binary_sha256'],'guest binary drift'
 for name,digest in manifest['headers'].items():assert sha(directory/name)==digest,'guest symbols drift'
 return manifest
def checked(cmd,**kw):subprocess.run(list(map(str,cmd)),check=True,**kw)
ap=argparse.ArgumentParser(description=__doc__)
sub=ap.add_subparsers(dest='stage',required=True)
b=sub.add_parser('guests');b.add_argument('--output',type=Path,required=True);b.add_argument('--cross-prefix',default=os.environ.get('CROSS_COMPILE','riscv64-unknown-elf-'))
l=sub.add_parser('link');l.add_argument('--repo-root',type=Path,default=ROOT);l.add_argument('--model',type=Path,required=True);l.add_argument('--guests',type=Path,required=True);l.add_argument('--output',type=Path,required=True);l.add_argument('--host-flags',type=Path,required=True,help='JSON array of compiler flags or existing receipt with host_flags');l.add_argument('--cxx',default=os.environ.get('CXX','clang++'))
t=sub.add_parser('run');t.add_argument('--guests',type=Path,required=True);t.add_argument('--binaries',type=Path,required=True);t.add_argument('--output',type=Path,required=True);t.add_argument('--expect-l2',type=int,choices=[0,64],required=True);t.add_argument('--timeout',type=int,default=180)
a=ap.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
if a.stage=='guests':
 rows=[];allperm=[]
 for case,name,source,prefix in [(None,'context_remap','context_remap.S','CTX_')]+[(i,'permission-'+n,'permission_revoke.S','PERM_') for i,n in enumerate(['sum','mxr','pmp'])]:
  elf=a.output/(name+'.elf');binary=a.output/(name+'.bin')
  cmd=[a.cross_prefix+'gcc','-march=rv64im_zicsr_zifencei','-mabi=lp64','-mno-relax','-nostdlib','-nostartfiles','-Wl,--no-relax','-T',HERE/'guest.ld']
  if case is not None:cmd.append('-DCASE='+str(case))
  cmd += [HERE/source,'-o',elf];checked(cmd);checked([a.cross_prefix+'objcopy','-O','binary',elf,binary])
  symbols={v[2]:int(v[0],16) for line in subprocess.check_output([a.cross_prefix+'nm','-n',str(elf)],text=True).splitlines() if len(v:=line.split())==3 and v[2].startswith(prefix)}
  (a.output/(name+'.disasm')).write_text(subprocess.check_output([a.cross_prefix+'objdump','-d',str(elf)],text=True))
  if case is None:(a.output/'context_symbols.h').write_text('#pragma once\n'+''.join(f'static constexpr uint64_t {k}=0x{v:x}ULL;\n' for k,v in symbols.items()))
  else:allperm.append(symbols)
  rows.append({'name':name,'argv':list(map(str,cmd)),'source_sha256':sha(HERE/source),'binary_sha256':sha(binary),'symbols':symbols})
 keys=['PERM_PROBE','PERM_FAULT','PERM_HANDLER','PERM_DONE','PERM_FAIL']
 (a.output/'permission_symbols.h').write_text('#pragma once\n'+''.join('static constexpr uint64_t '+k+'[3]={'+','.join(f'0x{s[k]:x}ULL' for s in allperm)+'};\n' for k in keys))
 save(a.output/'guest-manifest.json',{'status':'ASSEMBLED_NOT_EXECUTED','variants':rows,'headers':{n:sha(a.output/n) for n in ['context_symbols.h','permission_symbols.h']}})
elif a.stage=='link':
 m=a.model.resolve();g=a.guests.resolve();verify_guests(g);header=m/'BoardSocGsim.h';objects=sorted(m.glob('BoardSocGsim[0-9]*.o'));assert objects,'existing native model objects required'
 # Bind to the supplied actual model, never to a copied historical generated header.
 text=header.read_text()
 for f in ['state','saved$$virtualAddress','saved$$rootPpn','saved$$asid','savedResponse$$physicalAddress']:
  assert ' board$platform$physicalData_walkers_1$'+f+';' in text,'source-bound D-service observation missing: '+f
 flags=json.loads(a.host_flags.read_text());flags=flags['host_flags'] if isinstance(flags,dict) else flags
 assert isinstance(flags,list) and all(isinstance(x,str) for x in flags)
 host=a.repo_root.resolve()/'simulator/gsim/combined_board_bandwidth/host';assert (host/'harness/board_boot.cpp').is_file()
 assert not any((d/'BoardSocGsim.h').exists() for d in [HERE,g,host,host/'harness']),'shadow generated model header'
 records=[]
 for name in ['context_remap','permission_revoke']:
  cmd=[a.cxx,*flags,*['-I'+str(p) for p in [g,host,host/'harness',m]],str(HERE/(name+'.cpp')),*map(str,objects),'-ldl','-o',str(a.output/name)]
  checked(cmd);records.append({'name':name,'argv':cmd,'source_sha256':sha(HERE/(name+'.cpp')),'binary_sha256':sha(a.output/name)})
 save(a.output/'link-receipt.json',{'base_rtl_commit':BASE,'records':records,'model_header_sha256':sha(header),'objects':{p.name:sha(p) for p in objects},'guest_manifest_sha256':sha(g/'guest-manifest.json'),'host_flags':flags,'model_not_built_by_this_script':True})
else:
 g=a.guests.resolve();verify_guests(g);bins=a.binaries.resolve();link=json.loads((bins/'link-receipt.json').read_text())
 for row in link['records']:assert sha(bins/row['name'])==row['binary_sha256']
 assert sha(g/'guest-manifest.json')==link['guest_manifest_sha256']
 records=[]
 cases=[('context',bins/'context_remap',[g/'context_remap.bin'],'NATIVE_CONTEXT_DATA_PASS','NATIVE_L2_CONTEXT_PASS','missing actual target L2 hit coverage')]+[(n,bins/'permission_revoke',[g/('permission-'+n+'.bin'),i],'NATIVE_PERMISSION_DATA_PASS','NATIVE_L2_PERMISSION_PASS','missing actual target L2 permission coverage') for i,n in enumerate(['sum','mxr','pmp'])]
 for name,binary,args,data_anchor,pass_anchor,coverage_fail in cases:
  injections=['normal','data','stale'] if name=='context' else ['normal','cause']
  if a.expect_l2:injections.append('coverage')
  for injection in injections:
   cmd=[str(binary),*map(str,args)]+([] if injection=='normal' else ['--inject-'+injection]);log=a.output/(name+'-'+injection+'.log')
   with log.open('w') as f:p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=a.timeout,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
   text=log.read_text()
   if injection=='normal' and a.expect_l2:assert p.returncode==0 and pass_anchor in text,(name,text)
   elif injection=='normal':assert p.returncode==1 and data_anchor in text and coverage_fail in text,(name,text)
   else:
    expected={'data':'physical response does not match independent PA data','stale':'independent new-PA sentinel oracle','cause':'wrong precise permission trap cause/PC/tval','coverage':coverage_fail}[injection]
    assert p.returncode==1 and expected in text,(name,injection,text)
   records.append({'case':name,'injection':injection,'argv':cmd,'exit':p.returncode,'log_sha256':sha(log)})
   save(a.output/'results.json',{'status':'RUNNING','expected_l2_entries':a.expect_l2,'records':records})
 save(a.output/'results.json',{'status':'PASS_NATIVE_CONTRACTS' if a.expect_l2 else 'PASS_BASELINE_FUNCTIONAL_AND_EXPECTED_COVERAGE_REJECTION','expected_l2_entries':a.expect_l2,'records':records,'atomic_covered':False,'physical_timing_qualified':False})
print('PASS',a.stage)
