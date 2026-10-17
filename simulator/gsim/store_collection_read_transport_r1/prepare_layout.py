#!/usr/bin/env python3
"""Verify frozen sources and reconstruct relative test paths; never build/run hardware."""
import argparse,hashlib,json,shutil
from pathlib import Path
P=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--dry-run',action='store_true')
a=p.parse_args();out=a.output.resolve()
b=json.loads((P/'TESTED_SOURCE_BINDINGS.json').read_text())
for n,v in b.items():
 f=P/n;assert f.stat().st_size==v['bytes'] and hashlib.sha256(f.read_bytes()).hexdigest()==v['sha256'],n
mapping={}
for n in b:
 if n.startswith('source/'):
  mapping[n]='store-full-line-progress-stagec-r1/'+n
 elif n.startswith('host/'):
  group=n.split('/')[1];task={'queue':'stagec','store':'components','translation':'translation','lsu':'backend'}[group]
  suffix='host-lsu' if group=='lsu' else 'host'
  mapping[n]=f'store-full-line-progress-{task}-r1/{suffix}/'+Path(n).name
 elif n=='config/selected.json':
  mapping[n]='ethernet-mac-cpu-line275-r1/model/actual-combined-timing-repair-gsim.json'
 elif n.startswith('fixtures/'):
  group={'CollectionReadStoreGsim.scala':'components','CollectionReadTranslationGsim.scala':'translation'}.get(Path(n).name,'stagec')
  mapping[n]=f'store-full-line-progress-{group}-r1/source/'+Path(n).name
 elif n.startswith('baseline/'):
  mapping[n]='off-source/'+Path(n).name
assert len(set(mapping.values()))==len(mapping)
if not a.dry_run:
 assert not out.exists(),'preserve existing output';out.mkdir(parents=True)
 for src,dst in mapping.items():
  q=out/dst;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(P/src,q)
  assert hashlib.sha256(q.read_bytes()).hexdigest()==b[src]['sha256']
print(json.dumps({'mode':'dry-run' if a.dry_run else 'source-layout-only','files':mapping,'bytes':sum(b[n]['bytes'] for n in mapping)},indent=2))
