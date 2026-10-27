#!/usr/bin/env python3
"""Record the just-tested minimal epoch; no implicit tool installation."""
import argparse,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import a1_common_cpu_retirement as b
import gsim_initialization_epoch as e
p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True); p.add_argument('--original',type=Path,required=True); a=p.parse_args()
root=Path(__file__).resolve().parents[3]; out=a.output.resolve(); original=a.original.resolve(); src=out/'source'; patch=root/'simulator/gsim/tool_fixes/init-byte-span.patch'
names=[line.split('\t',1)[1] for line in subprocess.check_output(['git','-C',str(original),'ls-tree','-r',e.REVISION],text=True).splitlines() if line.split()[1]=='blob']
source={n:b.sha(src/n) for n in names}
binding=b.tool_binding(False); binding.update(mill=b.executable_binding('mill'),java=b.executable_binding('java'))
binding['gsim']={'path':str(src/'build/gsim/gsim'),'sha256':b.sha(src/'build/gsim/gsim'),'source':str(src),'revision':e.REVISION,'pinned_revision':e.REVISION,'working_tree_status':'archived exact pin + init-byte-span.patch; separate build','source_sha256':source,'source_manifest_sha256':b.digest_json(source),'patch_policy':'minimal two-site initialization repair; deterministic only'}
files=[patch,Path(e.__file__),Path(__file__).resolve(),root/'simulator/gsim/tool_fixes/build_init_byte_span.sh',root/'simulator/gsim/tool_fixes/INIT_BYTE_SPAN.md',out/'build.log',out/'regression.log',out/'regression/receipt.json']
reg=json.loads((out/'regression/receipt.json').read_text()); assert reg['status']=='PASS'; files.extend(map(Path,reg['fixtures']))
for result in reg['results'].values(): files.extend(out/'regression'/f for f in result['files'])
ldd=subprocess.check_output(['ldd',binding['gsim']['path']],text=True); (out/'ldd.txt').write_text(ldd); files.append(out/'ldd.txt')
for line in ldd.splitlines():
 for token in line.split():
  if token.startswith('/') and Path(token).is_file(): files.append(Path(token))
r={'status':'PASS','mode':'deterministic','randomize_init':'not qualified; separate width masking issue','revision':e.REVISION,'original_source':str(original),'original_binary':{'path':str(original/'build/gsim/gsim'),'sha256':b.sha(original/'build/gsim/gsim')},'patch':{'path':str(patch),'sha256':b.sha(patch)},'binding':binding,'artifacts_sha256':{str(f):b.sha(f) for f in files},'regression':str(out/'regression/receipt.json')}
(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n'); e.tool_binding(out/'receipt.json'); print('PASS receipt SHA256',b.sha(out/'receipt.json')); print('binary',binding['gsim']['path'],binding['gsim']['sha256'])
