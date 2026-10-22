import pathlib,hashlib,subprocess,json,time,sys
root=pathlib.Path.cwd();out=root/'out/cmu-frequency-r21'
paths=sorted((root/'src/main/scala').rglob('*.scala'))+sorted((root/'src/main/resources').rglob('*.sv'))+sorted((root/'src/test/scala').rglob('*.scala'))+[root/'build.mill']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def source():return{str(p.relative_to(root)):sha(p)for p in paths}
name,mode=sys.argv[1:];rtl=out/(name+'-rtl');assert not rtl.exists();before=source();cmd=['mill','-i','IonSoC.test.runMain','ip.FixedSourceManagedGmacMain',str(rtl),mode];t=time.monotonic()
with(out/(name+'-emission.log')).open('w')as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
rec=dict(status='PASS_EMIT_ONLY' if r.returncode==0 and source()==before else 'FAIL',command=cmd,returncode=r.returncode,seconds=time.monotonic()-t,source_sha256=before,rtl_sha256={p.name:sha(p)for p in sorted(rtl.glob('*.sv'))})
(out/(name+'-emission.json')).write_text(json.dumps(rec,indent=2)+'\n');print(rec['status'],name,len(rec['rtl_sha256']),rec['seconds'],flush=True)
if rec['status']!='PASS_EMIT_ONLY':print((out/(name+'-emission.log')).read_text()[-10000:]);sys.exit(1)
