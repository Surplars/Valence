#!/usr/bin/env python3
"""Run one immutable linked host with per-launch image binding and scoped output."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,time
HERE=Path(__file__).resolve().parent;MODEL=HERE/'model-on-on-r1'
CASES=['main','older_ready','newly_ready','busy_false','final_drain','long_nonhead','alias_full','alias_partial','pmp_store','unaligned_store','outside_store','atomic_store','virtual_store','strong_mmio','strong_misaligned','strong_pmp_load','irq','fence','context','recovery','token_reuse','backpressure','late_ack','dirty_release','full_owner','wrap','reuse_widths','reuse_frontier','reuse_kill']
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--host',default='host-r1');a.add_argument('--attempt',required=True);a.add_argument('--case',choices=CASES);a.add_argument('--negative');x=a.parse_args()
 binary=MODEL/x.host;assert binary.is_file();pins={str(p):sha(p)for p in [binary,HERE/'memory_state_reuse.cpp',HERE/'memory_state_oracle.h',HERE/'memory_proof_frontier_exact_reference.h',HERE/'state_abi.h',MODEL/'profile.json',MODEL/'PostedPreparationPriorityGsim.h']}
 manifest={'schema':'memory-state-reuse-runtime-batch-v1','pins':pins,'started_unix':time.time(),'cases':[],'positive_cases':CASES if x.case is None else[x.case],'negative':x.negative}
 out=HERE/('batch-'+x.attempt+'.json');assert not out.exists();out.write_text(json.dumps(manifest,indent=2)+'\n')
 for case in manifest['positive_cases']:
  assert all(sha(p)==h for p,h in pins.items()),'batch input drift';assert shutil.disk_usage(HERE).free>700*1024**2
  log=HERE/('case-'+x.attempt+'-'+case+'.log');assert not log.exists()
  argv=[str(binary),'--case',case]+(['--inject-'+x.negative]if x.negative else[]);started=time.monotonic()
  with log.open('x')as f:
   r=subprocess.run(argv,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
  unchanged=all(sha(p)==h for p,h in pins.items())
  entry={'case':case,'argv':argv,'binary_sha256':pins[str(binary)],'exit':r.returncode,'expected':1 if x.negative else 0,'seconds':time.monotonic()-started,'log':str(log),'log_sha256':sha(log),'inputs_unchanged':unchanged}
  manifest['cases'].append(entry);out.write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(entry),flush=True)
  assert r.returncode==entry['expected'] and unchanged,'runtime failed'
 manifest['status']='PASS_EXECUTION_PENDING_WITNESS_REVIEW';manifest['ended_unix']=time.time();out.write_text(json.dumps(manifest,indent=2)+'\n')
if __name__=='__main__':main()
