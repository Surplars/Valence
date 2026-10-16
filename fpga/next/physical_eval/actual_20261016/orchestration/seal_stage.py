from pathlib import Path
import datetime,hashlib,json,sys
root=Path(sys.argv[1]);stage=sys.argv[2];dcp=Path(sys.argv[3]);pid=int(sys.argv[4])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
pkg=root/'package/combined-timing-repair-transfer-r1'
assert dcp.is_file() and dcp.resolve().is_relative_to(root.resolve())
files={str(p.relative_to(root)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in (root/'orchestration').iterdir() if p.is_file()}
receipt={'schema':'valence-external-diagnostic-stage-v1','stage':stage,'vivadoPid':pid,
 'sealedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'cpuCommit':'50cb0c5d4b17318904d6cf818ad23829821d5d93','networkCommit':'7dc9cea2dfc45d1921664efa2dc7c2fc894572ee',
 'transferManifestSha256':sha(pkg/'transfer-manifest.json'),
 'dependencyContractSha256':sha(root/'valence-actual-local-dependencies-20261016-r1.json'),
 'checkpoint':{'path':str(dcp),'bytes':dcp.stat().st_size,'sha256':sha(dcp)},
 'orchestration':files,'routeExecuted':False,'bitstreamGenerated':False,'physicalSignoff':False}
assert stage.replace('_','').isalnum()
path=dcp.with_name(dcp.stem+'.'+stage+'.receipt.json')
with path.open('x',encoding='utf-8') as f:json.dump(receipt,f,indent=2);f.write('\n')
print(json.dumps({'receipt':str(path),'sha256':sha(path),'stage':stage,'checkpointSha256':receipt['checkpoint']['sha256']}))
