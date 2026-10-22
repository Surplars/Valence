from pathlib import Path
import subprocess,json,time,hashlib
root=Path.cwd();out=root/'out/cmu-frequency-r21';target=out/'default-r3';assert not target.exists()
paths=sorted((root/'src/main/scala').rglob('*.scala'))+sorted((root/'src/main/resources').rglob('*.sv'))+sorted((root/'src/test/scala').rglob('*.scala'))+[root/'build.mill']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before={str(p.relative_to(root)):sha(p)for p in paths}
compile_cmd=['mill','-i','IonSoC.test.compile'];ct=time.monotonic()
with(out/'compile-final.log').open('w')as f:cr=subprocess.run(compile_cmd,stdout=f,stderr=subprocess.STDOUT)
(out/'compile-final-receipt.json').write_text(json.dumps(dict(command=compile_cmd,exit=cr.returncode,seconds=time.monotonic()-ct,source_sha256=before),indent=2)+'\n')
assert cr.returncode==0
cmd=['mill' ,'-i','IonSoC.test.runMain','platform.CommonMachinePlatformMain',str(target),'i1','--clock-profile=performance300-static','--vivado-memories','--compile-receipt='+str(out/'compile-final-receipt.json')]
t=time.monotonic()
with(out/'default-r3.log').open('w')as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
ref=root/'out/cmu-frequency-r16/default-performance';old={p.name:sha(p)for p in ref.glob('*.sv')};new={p.name:sha(p)for p in target.glob('*.sv')};changed=[n for n in old if old[n]!=new.get(n)]
rec=dict(status='PASS_EMIT_ONLY'if r.returncode==0 else 'FAILED',command=cmd,returncode=r.returncode,seconds=time.monotonic()-t,reference=str(ref),source_sha256=before,source_unchanged=before=={str(p.relative_to(root)):sha(p)for p in paths},same_inventory=old.keys()==new.keys(),byte_identical=len(old)-len(changed),total=len(old),changed=changed,reference_sha256=old,current_sha256=new)
(out/'default-r3-comparison.json').write_text(json.dumps(rec,indent=2)+'\n');print({k:v for k,v in rec.items()if not k.endswith('sha256')})
