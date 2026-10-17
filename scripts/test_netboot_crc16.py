#!/usr/bin/env python3
from pathlib import Path
import subprocess,json,hashlib,os,shutil,time
import argparse
p=argparse.ArgumentParser();p.add_argument('--cc',default=os.environ.get('CC','gcc'));p.add_argument('--out',type=Path,default=Path('build/netboot-crc16-native'));p.add_argument('--dry-run',action='store_true');args=p.parse_args()
R=Path(__file__).resolve().parents[1];S=R/'fpga/firmware';T=S/'tests';D=args.out.resolve()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=(S/'crc32.c').read_text();at=source.index('uint32_t firmware_crc_update(')
assert source[at:]==(T/'crc16-candidate.inc').read_text(),'production/oracle mismatch'
original=source[:at]+(T/'crc16-original.inc').read_text()
assert hashlib.sha256(original.encode()).hexdigest()=='dd2c907c9857744e74a6685b41298d2bc996121331c003c87aab78f1208f9900','reference identity'
inputs={str(x):sha(x) for x in [S/'crc32.c',S/'crc32.h',T/'crc16-original.inc',T/'crc16-candidate.inc',T/'netboot_crc16_oracle.c',Path(__file__).resolve()]}
if args.dry_run:
 print(json.dumps({'out':str(D),'cc':args.cc,'sources':inputs,'flags':'ASan+UBSan strict aliasing; original/candidate mode3; preprocess modes0/1/2','cases':328640+525792},indent=2));raise SystemExit
D.mkdir(parents=True,exist_ok=True);(D/'reference.c').write_text(original)
cc=shutil.which(args.cc);assert cc;flags=['-O2','-std=gnu11','-Wall','-Wextra','-Werror','-Wstrict-aliasing=2','-fstrict-aliasing','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer'];commands=[];modeproof={}
for mode in [0,1,2]:
 outputs=[]
 for arm in ['sum16','crc16']:
  cmd=[cc,'-E','-P','-I'+str(S),'-DFIRMWARE_CRC_MODE='+str(mode),str(D/'reference.c' if arm=='sum16' else S/'crc32.c')];commands.append(cmd);outputs.append(subprocess.check_output(cmd))
 assert outputs[0]==outputs[1],mode
 modeproof[mode]={'preprocessed_bytes':len(outputs[0]),'sha256':hashlib.sha256(outputs[0]).hexdigest()}
for name,arm in [('reference','sum16'),('candidate','crc16')]:
 cmd=[cc,*flags,'-I'+str(S),'-DFIRMWARE_CRC_MODE=3','-Dfirmware_crc_update='+name+'_crc_update','-c',str(D/'reference.c' if arm=='sum16' else S/'crc32.c'),'-o',str(D/(name+'.o'))];commands.append(cmd)
 with (D/(name+'-compile.log')).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
for name,extra in [('positive',[]),('negative',['-DORACLE_NEGATIVE'])]:
 cmd=[cc,*flags,*extra,str(T/'netboot_crc16_oracle.c'),str(D/'reference.o'),str(D/'candidate.o'),'-o',str(D/name)];commands.append(cmd)
 with (D/(name+'-compile.log')).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
 cmd=[str(D/name)];commands.append(cmd);start=time.monotonic()
 with (D/(name+'.log')).open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=180)
 log=(D/(name+'.log')).read_text()
 if name=='positive':assert r.returncode==0 and 'PASS_CRC16_ORACLE direct_cases=328640 chained_cases=525792' in log,log
 else:assert r.returncode==1 and 'CRC16_MISMATCH pattern=0 alignment=0 length=2 initial=00000000 reference=00000000 candidate=00000001 bitwise=00000000' in log,log
 (D/(name+'-run.json')).write_text(json.dumps({'exit':r.returncode,'seconds':time.monotonic()-start,'command':cmd,'ASAN_OPTIONS':'detect_leaks=0'},indent=2)+'\n');print(log.strip(),flush=True)
assert {p:sha(p) for p in inputs}==inputs
(D/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
libs=[cc]
(D/'RECEIPT.json').write_text(json.dumps({'inputs':inputs,'tools':{p:sha(p) for p in libs},'unchanged_modes':modeproof,'files':{p.name:sha(p) for p in D.iterdir() if p.is_file()},'free':shutil.disk_usage(R).free},indent=2)+'\n')
