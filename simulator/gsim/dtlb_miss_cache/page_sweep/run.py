#!/usr/bin/env python3
"""Portable full-CPU page-sweep against existing model objects. Never builds a DUT."""
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
if not __debug__:raise RuntimeError('Run oracle checks without Python -O')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2)+'\n')
def checked(cmd):subprocess.run(list(map(str,cmd)),check=True)
def verify_guests(path):
 m=json.loads((path/'guest-manifest.json').read_text())
 for r in m['variants']:assert sha(path/(r['name']+'.bin'))==r['binary_sha256'],'guest changed'
 assert sha(path/'cpu_sv39_symbols.h')==m['symbols_sha256'],'guest symbols changed'
 return m
def fields(text,prefix):
 line=next(l for l in text.splitlines() if l.startswith(prefix));out={}
 for k,v in re.findall(r'(\w+)=([^ ]+)',line):
  try:out[k]=int(v)
  except ValueError:
   try:out[k]=float(v)
   except ValueError:out[k]=v
 return out
ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='stage',required=True)
b=sub.add_parser('guests');b.add_argument('--cross-prefix',required=True);b.add_argument('--output',type=Path,required=True)
l=sub.add_parser('link');l.add_argument('--model',type=Path,required=True);l.add_argument('--repo-root',type=Path,default=ROOT);l.add_argument('--cxx',required=True);l.add_argument('--host-flags',type=Path,required=True,help='JSON compiler flag array, or receipt containing host_flags');l.add_argument('--guests',type=Path,required=True);l.add_argument('--output',type=Path,required=True)
r=sub.add_parser('run');r.add_argument('--guests',type=Path,required=True);r.add_argument('--binary-dir',type=Path,required=True);r.add_argument('--expect-l2',type=int,choices=[0,64],required=True);r.add_argument('--output',type=Path,required=True);r.add_argument('--timeout',type=int,default=180)
a=ap.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
if a.stage=='guests':
 source=(HERE/'page_sweep.S').read_text();assert source.count('li t2, 4160')==1
 bad=a.output/'bad_stride.S';bad.write_text(source.replace('li t2, 4160','li t2, 4168'))
 rows=[];normal_symbols=None
 for name,src in [('guest',HERE/'page_sweep.S'),('bad_stride',bad)]:
  elf=a.output/(name+'.elf');binary=a.output/(name+'.bin')
  cmd=[a.cross_prefix+'gcc','-march=rv64im_zicsr_zifencei','-mabi=lp64','-mno-relax','-nostdlib','-nostartfiles','-Wl,--no-relax','-T',HERE/'guest.ld',src,'-o',elf]
  checked(cmd);checked([a.cross_prefix+'objcopy','-O','binary',elf,binary])
  symbols={v[2]:int(v[0],16) for line in subprocess.check_output([a.cross_prefix+'nm','-n',str(elf)],text=True).splitlines() if len(v:=line.split())==3 and v[2].startswith('bw_')}
  assert set(symbols)=={'bw_begin','bw_end','bw_drain','bw_done'}
  if normal_symbols is None:normal_symbols=symbols
  else:assert symbols==normal_symbols,'negative guest moved ROI markers'
  (a.output/(name+'.disasm')).write_text(subprocess.check_output([a.cross_prefix+'objdump','-d',str(elf)],text=True))
  rows.append({'name':name,'command':list(map(str,cmd)),'source_sha256':sha(src),'binary_sha256':sha(binary),'symbols':symbols})
 header=a.output/'cpu_sv39_symbols.h';header.write_text(''.join(f'#define {k.upper()} {v}ULL\n' for k,v in normal_symbols.items()))
 save(a.output/'guest-manifest.json',{'status':'ASSEMBLED_NOT_EXECUTED','variants':rows,'symbols_sha256':sha(header),'toolchain':subprocess.check_output([a.cross_prefix+'gcc','--version'],text=True).splitlines()[0],'scope':'controlled assembly guest, not production C or GCC13.2 binary'})
elif a.stage=='link':
 g=a.guests.resolve();verify_guests(g);m=a.model.resolve();header=m/'BoardSocGsim.h';objects=sorted(m.glob('BoardSocGsim[0-9]*.o'));assert objects,'existing native model objects required'
 assert 'board$platform$physicalData_walkers_1$state' in header.read_text(),'D-service observation absent in supplied model'
 host=a.repo_root.resolve()/'simulator/gsim/combined_board_bandwidth/host'
 for f in ['harness/board_boot.cpp','tagged_board_probe.h','supply_ledger.h']:assert (host/f).is_file(),f
 # Reject shadow headers so includes bind to the explicitly selected real model.
 assert not any((d/'BoardSocGsim.h').exists() for d in [HERE,g,host,host/'harness']),'shadow generated model header'
 flags=json.loads(a.host_flags.read_text());flags=flags['host_flags'] if isinstance(flags,dict) else flags
 assert isinstance(flags,list) and all(isinstance(f,str) for f in flags)
 binary=a.output/'page-sweep';cmd=[a.cxx,*flags,*['-I'+str(d) for d in [g,m,host,host/'harness']],str(HERE/'page_sweep.cpp'),*map(str,objects),'-ldl','-o',str(binary)]
 checked(cmd)
 save(a.output/'link-receipt.json',{'command':cmd,'source_sha256':sha(HERE/'page_sweep.cpp'),'binary_sha256':sha(binary),'model_header_sha256':sha(header),'objects':{p.name:sha(p) for p in objects},'guest_manifest_sha256':sha(g/'guest-manifest.json'),'host_flags':flags,'DUT_compiled':False})
else:
 g=a.guests.resolve();verify_guests(g);b=a.binary_dir.resolve();receipt=json.loads((b/'link-receipt.json').read_text());assert sha(b/'page-sweep')==receipt['binary_sha256'];assert sha(g/'guest-manifest.json')==receipt['guest_manifest_sha256']
 rows=[];records=[]
 cases=[(f'read{n}',n,'guest.bin',None,None) for n in [16,17,32]]+[
  ('negative-read-data',16,'guest.bin','--inject-read','CPU read data mismatch'),
  ('negative-total-count',16,'guest.bin','--inject-total-count','whole-program architectural memory instruction count'),
  ('negative-selected-offset',16,'bad_stride.bin',None,'CPU store address/data mismatch against guest workload')]
 for name,pages,guest,inject,rejection in cases:
  cmd=[str(b/'page-sweep'),str(g/guest),'1','0',str(pages),'128']+([inject] if inject else []);log=a.output/(name+'.log');start=time.monotonic()
  with log.open('w') as f:p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=a.timeout,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
  text=log.read_text()
  if rejection:assert p.returncode==1 and rejection in text,(name,text)
  else:
   assert p.returncode==0 and 'CPU_SV39_PASS' in text,(name,text)
   d=fields(text,'CPU_SV39_RESULT');mmu=fields(text,'MMU_SERVICE_OBSERVATION');cache=fields(text,'BOARD_IPC name=S_mode_page_sweep_ROI')
   assert d['loads']==pages*128 and d['stores']==0 and d['total_loads']==4+pages*129 and d['total_stores']==1
   assert d['useful_bytes']==pages*8*128 and d['selected_stride']==4160
   assert cache['read_miss']==cache['write_miss']==0
   misses=0 if pages==16 else pages*128
   assert mmu['roi_d_walk_entries']==(0 if a.expect_l2 else misses)
   assert mmu['roi_d_l2_hits']==(misses if a.expect_l2 else 0)
   assert d['ar']==(0 if a.expect_l2 else misses)
   rows.append({'pages':pages,'result':d,'roi_cache':cache,'mmu':mmu,'cold':fields(text,'PAGE_SWEEP_COLD'),'cold_cache':fields(text,'BOARD_IPC name=cold_boot_plus_one_pass_warmup'),'pass':fields(text,'CPU_SV39_PASS')})
  records.append({'name':name,'command':cmd,'exit':p.returncode,'expected_rejection':rejection,'seconds':time.monotonic()-start,'log_sha256':sha(log)})
  save(a.output/'results.json',{'status':'RUNNING','expected_l2_entries':a.expect_l2,'rows':rows,'records':records})
 save(a.output/'results.json',{'status':'PASS_FULLCPU_PAGE_SWEEP','expected_l2_entries':a.expect_l2,'rows':rows,'records':records,'scope':'controlled assembly at model 100MHz cycle conversion; not production C or board result'})
print('PASS',a.stage)
