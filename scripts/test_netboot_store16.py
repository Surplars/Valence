#!/usr/bin/env python3
import pathlib,subprocess,json,hashlib,os,shutil,time
import argparse
p=argparse.ArgumentParser();p.add_argument('--cc',default=os.environ.get('CC','gcc'));p.add_argument('--out',type=pathlib.Path,default=pathlib.Path('build/netboot-store16-native'));p.add_argument('--dry-run',action='store_true');args=p.parse_args()
R=pathlib.Path(__file__).resolve().parents[1];S=R/'fpga/firmware/tests';D=args.out.resolve()
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
production=R/'fpga/firmware/netboot_board.c';source=production.read_text();a=source.index('static int store(');b=source.index('\nstatic int prepare_verify',a)
assert source[a:b]+'\n'==(S/'store16-candidate.inc').read_text().replace('candidate_store(','store('),'exact production body required'
# Pin the independent reference body, not unrelated board clock/transport code.
# The exact production body is still checked against the candidate above.
assert sha(S/'store16-original.inc')=='0dc8a534b99a7f45246d14dc5bbd63a6832771221791277f83812cc583665c82','original store identity'

inputs={str(q):sha(q) for q in [production,S/'netboot_store16_oracle.c',S/'store16-original.inc',S/'store16-candidate.inc',R/'fpga/firmware/netboot_copy.h',pathlib.Path(__file__).resolve()]}
if args.dry_run:print(json.dumps({'cc':args.cc,'out':str(D),'sources':inputs,'positive_cases':393408,'range_cases':20,'guard_page_cases':130,'modes':[0,1]},indent=2));raise SystemExit
D.mkdir(parents=True,exist_ok=True)
cc=shutil.which(args.cc);assert cc;flags=['-O2','-std=gnu11','-Wall','-Wextra','-Werror','-Wstrict-aliasing=2','-fstrict-aliasing','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']
commands=[]
for mode,name,extra in [(mode,name,extra) for mode in [0,1] for name,extra in [('positive',[]),('negative',['-DORACLE_NEGATIVE'])]]:
 kind=name; name=f'mode{mode}-{name}'
 extra=[f'-DNETBOOT_STORE16_PACKING={mode}',*extra]
 cmd=[cc,*flags,*extra,str(S/'netboot_store16_oracle.c'),'-o',str(D/name)];commands.append(cmd)
 with (D/(name+'-compile.log')).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True,cwd=D)
 cmd=[str(D/name)];commands.append(cmd);start=time.monotonic()
 with (D/(name+'.log')).open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=180,cwd=D)
 log=(D/(name+'.log')).read_text()
 if kind=='positive':assert r.returncode==0 and 'PASS_STORE16_ORACLE cases=393408 range_cases=20 guard_page_cases=130' in log,log
 else:assert r.returncode==1 and 'STORE16_MISMATCH source_alignment=0 destination_alignment=0 length=8 reason=bytes' in log,log
 (D/(name+'-run.json')).write_text(json.dumps({'exit':r.returncode,'seconds':time.monotonic()-start,'command':cmd,'ASAN_OPTIONS':'detect_leaks=0'},indent=2)+'\n')
 print(f'mode={mode} '+log.strip(),flush=True)
assert {p:sha(p) for p in inputs}==inputs
(D/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
libs=[cc]
(D/'RECEIPT.json').write_text(json.dumps({'inputs':inputs,'tools':{p:sha(p) for p in libs},'files':{p.name:sha(p) for p in D.iterdir() if p.is_file()},'free':shutil.disk_usage(R).free},indent=2)+'\n')
