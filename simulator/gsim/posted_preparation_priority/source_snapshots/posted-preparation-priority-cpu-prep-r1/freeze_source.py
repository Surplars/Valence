"""Copy one explicitly frozen production export and overlay only passive test sources."""
import argparse,hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def inv(root):return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.relative_to(root).parts[0] not in ('.git','out')}
def save(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def run(source,identity,freeze,freeze_sha):
 source=Path(source).resolve();freeze=Path(freeze).resolve()
 assert sha(freeze)==freeze_sha,'author freeze receipt changed'
 assert not (H/'source').exists(),'fresh selected source required'
 before=inv(source);shutil.copytree(source,H/'source',ignore=shutil.ignore_patterns('.git','out','__pycache__'));after=inv(source)
 assert before==after==inv(H/'source'),'source changed during copying or excluded unexpected inputs'
 overlays={}
 for p in sorted((H/'overlays').rglob('*')):
  if p.is_file():
   rel=str(p.relative_to(H/'overlays'));dest=H/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);overlays[rel]=sha(dest)
 files=inv(H/'source');main={n:h for n,h in files.items() if n.startswith('src/main/')}
 assert main=={n:h for n,h in before.items() if n.startswith('src/main/')},'production bytes changed'
 m=dict(schema='posted-preparation-priority-selected-source-v1',production_head=identity,source_commit=identity,source_export=str(source),source_freeze_path=str(freeze),source_freeze_sha256=freeze_sha,source_before_overlays=before,production_main_files=main,passive_overlays=overlays,files=files,production_edited=False)
 save(H/'SELECTED-SOURCE.json',m)
 pin=dict(schema='posted-preparation-priority-cpu-source-pin-v1',source_commit=identity,production_source_head=identity,selected_source_manifest_sha256=sha(H/'SELECTED-SOURCE.json'),source_freeze_path=str(freeze),source_freeze_sha256=freeze_sha,runtime_allowed=False,model_execution_owner='/root/optimize_cpu_memory_supply/prepare_preparation_priority_cpu',host_execution_owner='/root/optimize_cpu_memory_supply/prepare_preparation_priority_cpu')
 save(H/'SOURCE-PIN.json',pin)
 host=H.parent/'posted-preparation-priority-cpu-host-r1'
 for n in ['SELECTED-SOURCE.json','SOURCE-PIN.json']:shutil.copy2(H/n,host/n)
 return dict(status='FROZEN_CPU_SOURCE_ONLY',production_head=identity,production_files=len(main),all_files=len(files),overlays=overlays,selected_manifest_sha256=sha(H/'SELECTED-SOURCE.json'))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--identity',required=True);p.add_argument('--freeze',required=True);p.add_argument('--freeze-sha256',required=True);a=p.parse_args();print(json.dumps(run(a.source,a.identity,a.freeze,a.freeze_sha256),indent=2))
