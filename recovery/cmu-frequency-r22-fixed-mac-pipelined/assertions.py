from pathlib import Path
import sys,json
sys.path.insert(0,'simulator/cdc')
from test_runtime_epoch_boundary import sha,run,tool_chain
root=Path.cwd();out=root/'out/cmu-frequency-r22';iv=root.parent/'native-tools/bin/iverilog';records={}
required=['fixed MAC receipt must consume the exact outstanding command','fixed MAC TX close requires completed upstream producers','fixed MAC park requires real upstream held and no unaccepted CSR offer','Pending RAM response must retain source-visible slot ownership','Stalled response must re-read its still-owned RAM address']
for name,directory,sites in [('real',out/'test-r1-rtl',23),('boundary',out/'boundary-r1-rtl',6)]:
 target=out/(name+'-enabled-assertions.sv');assert not target.exists();files=sorted(directory.glob('*.sv'));cmd=[str(iv),'-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-E','-o',str(target),*map(str,files)];r=run(cmd,out/(name+'-assertions.log'),30);content=target.read_text();assert r['returncode']==0 and content.count('$fatal')==sites
 for message in required:assert message in content
 records[name]=dict(command=cmd,result=r,source_sha256={str(p):sha(p)for p in files},preprocessed_sha256=sha(target),inline_fatal_sites=sites,required_assertions=required)
(out/'enabled-assertions-verification.json').write_text(json.dumps(records,indent=2)+'\n');print({k:v['inline_fatal_sites']for k,v in records.items()})
