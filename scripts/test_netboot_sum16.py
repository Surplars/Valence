#!/usr/bin/env python3
"""Native differential safety check for the exact production sum16 body."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--cc',default=os.environ.get('CC','gcc'));p.add_argument('--out',type=Path,default=Path('build/netboot-sum16-native'));p.add_argument('--dry-run',action='store_true');a=p.parse_args()
r=Path(__file__).resolve().parents[1];t=r/'fpga/firmware/tests';out=a.out.resolve()
source=(r/'fpga/firmware/netboot.c').read_text();start=source.index('static uint32_t sum16(');end=source.index('\nstatic uint16_t checksum',start)
assert source[start:end]+'\n'==(t/'sum16-candidate.inc').read_text().replace('candidate_sum16(','sum16('),'oracle must match production function exactly'
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
files=[r/'fpga/firmware/netboot.c',t/'netboot_sum16_oracle.c',t/'sum16-original.inc',t/'sum16-candidate.inc',Path(__file__).resolve()]
before={str(f.relative_to(r)):sha(f) for f in files}
flags=['-O2','-std=gnu11','-Wall','-Wextra','-Werror','-Wstrict-aliasing=2','-fstrict-aliasing','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']
commands={name:[a.cc,*flags,*extra,str(t/'netboot_sum16_oracle.c'),'-o',str(out/name)] for name,extra in [('positive',[]),('negative',['-DORACLE_NEGATIVE'])]}
if a.dry_run:print(json.dumps(commands,indent=2));raise SystemExit
out.mkdir(parents=True,exist_ok=True);results={}
for name,cmd in commands.items():
 with (out/(name+'-compile.log')).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
 with (out/(name+'.log')).open('w') as f:result=subprocess.run([str(out/name)],stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
 log=(out/(name+'.log')).read_text();results[name]={'exit':result.returncode,'command':cmd,'log_sha256':sha(out/(name+'.log')),'binary_sha256':sha(out/name)}
 expected='PASS_SUM16_ORACLE direct_cases=458976 chained_cases=196704' if name=='positive' else 'SUM16_MISMATCH pattern=0 alignment=0 length=2 initial=00000000 reference=00000000 candidate=00000001'
 assert result.returncode==(0 if name=='positive' else 1) and expected in log,log
 print(log.strip())
assert {str(f.relative_to(r)):sha(f) for f in files}==before
(out/'receipt.json').write_text(json.dumps({'sources':before,'results':results,'ASAN_OPTIONS':'detect_leaks=0'},indent=2)+'\n')
