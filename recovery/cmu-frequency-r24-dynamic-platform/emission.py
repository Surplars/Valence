"""Source-bound explicit emission, shared Mill slot must be held by caller."""
import pathlib, hashlib, subprocess, json, time, sys
root = pathlib.Path.cwd()
out = root / 'out/cmu-frequency-r24'
name, emitter, *extra = sys.argv[1:]
rtl = out / (name + '-rtl')
assert not rtl.exists()
paths = sorted((root/'src/main/scala').rglob('*.scala')) + sorted((root/'src/main/resources').rglob('*.sv')) + sorted((root/'src/test/scala').rglob('*.scala')) + [root/'build.mill']
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def sources(): return {str(p.relative_to(root)): sha(p) for p in paths}
before = sources()
cmd = ['mill', '-i', 'IonSoC.test.runMain', emitter, str(rtl), *extra]
t = time.monotonic()
with (out/(name+'-emission.log')).open('w') as log:
    result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=180)
record = dict(status='PASS_EMIT_ONLY' if result.returncode == 0 and sources() == before else 'FAIL',
              command=cmd, returncode=result.returncode, seconds=time.monotonic()-t,
              source_sha256=before, rtl_sha256={p.name: sha(p) for p in sorted(rtl.glob('*.sv'))})
(out/(name+'-emission.json')).write_text(json.dumps(record, indent=2)+'\n')
print(record['status'], name, len(record['rtl_sha256']), flush=True)
if record['status'] != 'PASS_EMIT_ONLY':
    print((out/(name+'-emission.log')).read_text()[-8000:])
    sys.exit(1)
