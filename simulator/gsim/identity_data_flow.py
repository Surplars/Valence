#!/usr/bin/env python3
"""Two adapter-only models; external token/latency oracles and retained VM-context checks."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
import run as common


def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);args=ap.parse_args();assert re.fullmatch('[A-Za-z0-9_-]+',args.tag)
 out=common.BUILD/('identity-data-flow-'+args.tag);out.mkdir(parents=True,exist_ok=False)
 files=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'harness/identity_data_flow.cpp',common.HERE/'harness/translation_context.cpp']
 def hashes():return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
 r={'status':'RUNNING','source_sha256':hashes(),'models':{},'scope':'adapter-only; no whole-CPU IPC or timing claim'}
 (out/'freeze.json').write_text(json.dumps(r,indent=2)+'\n')
 try:
  gsim,cxx=common.setup(False)
  for flag in (0,1):
   target=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/f'flag{flag}'),'ooo.TranslationContextGsimMain','TranslationContextGsim','identity_data_flow.cpp',parameters=(flag,'pmp'),defines={'IDENTITY_FLOW':flag},timeout=120)
   log=(target/'test.log').read_text();assert f'IDENTITY_DATA_FLOW_PASS flag={flag}' in log
   cases={}
   for line in log.splitlines():
    if line.startswith('IDENTITY_CASE '):
     fields=dict(x.split('=',1) for x in line.split()[1:]);name=fields.pop('name');cases[name]={k:int(v) for k,v in fields.items()}
   assert len(cases)==16,(flag,len(cases))
   for arg,anchor in [('--inject-data','independent response data/fault/order mismatch'),('--inject-context','independent captured VM context mismatch')]:
    x=subprocess.run([target/'run',arg],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});(target/(arg[2:]+'.log')).write_text(x.stdout+x.stderr);assert x.returncode!=0 and anchor in x.stdout+x.stderr
   # Same generated adapter runs the earlier64-context independent VM oracle.
   common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DPROGRAMMABLE_PMP=1',f'-I{target}',*sorted(target.glob('TranslationContextGsim[0-9]*.cpp')),common.HERE/'harness/translation_context.cpp','-ldl','-o',target/'context-run'],log=target/'context-compile.log')
   common.run([target/'context-run'],log=target/'context.log',env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
   context=(target/'context.log').read_text();assert 'TRANSLATION_CONTEXT_PASS checked=192 epochs=32 contexts=64' in context
   x=subprocess.run([target/'context-run','--inject-mismatch'],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});(target/'context-negative.log').write_text(x.stdout+x.stderr);assert x.returncode!=0 and 'VM context independent oracle mismatch' in x.stdout+x.stderr
   r['models'][str(flag)]={'cases':cases,'context':context,'negative':'PASS'};assert hashes()==r['source_sha256'],'source drift'
   (out/'progress.json').write_text(json.dumps(r,indent=2)+'\n')
  b=r['models']['0']['cases'];c=r['models']['1']['cases']
  for name in ('bare_single_l1','bare_single_l5','u_bare','s_bare','m_satp_bypass'):
   assert c[name]['physical_latency']==b[name]['physical_latency']-1
   assert c[name]['response_latency']==b[name]['response_latency']-1
   assert c[name]['translations']==b[name]['translations']==0
  assert c['bare_dependent64']['cycles']==b['bare_dependent64']['cycles']-64
  for name in ('vm_immediate','vm_delayed','mprv_effective_s','vm_pmp_allow_snapshot','vm_pmp_deny_snapshot','vm_locked_machine_pmp','vm_atomic_outside'):
   assert c[name]==b[name],('VM path drift',name,b[name],c[name])
  r['status']='PASS'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':main()
