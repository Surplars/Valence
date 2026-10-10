"""Fresh audited FIR/header/CPP only, before any literal object reuse decision."""
from contract import *
import model,argparse
SCHEMA='posted-preparation-priority-board-generation-v1'
def generate(binding,digest,side,out,slot):
 require(slot,'coordinator Java/generation slot required');b=model.check_binding(binding,digest);out=Path(out).resolve();require(not out.exists(),'fresh generation output required');out.mkdir()
 r=dict(schema=SCHEMA,status='RUNNING',side=side,binding_path=str(Path(binding).resolve()),binding_sha256=digest,steps=[],actual_runtime=False,object_compiled=False,object_reused=False,artifact_limit_bytes=180*1024**2)
 try:
  for i,cmd in enumerate(model.plan(side,out,b)[:2]):
   r['steps'].append(model.execute(cmd,out/('step'+str(i)+'.log'),1800,artifact_limit_bytes=r['artifact_limit_bytes']));save(out/'receipt.json',r)
   if i==0:profile(read(out/'profile.json'),side);audit(read(out/'actual-parameters.json'),read(out/'profile.json'),side)
  require({p.name for p in out.glob('BoardSocGsim[0-9]*.cpp')}=={'BoardSocGsim0.cpp'},'unexpected translation units');r['actual_contract']=header_and_fir(out,side);model.check_binding(binding,digest);r['status']='PASS_FRESH_ACTUAL_BOARD_GENERATION_ONLY'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:r['artifacts']={p.name:sha(p)for p in out.iterdir()if p.is_file()and p.name!='receipt.json'};save(out/'receipt.json',r)
 return dict(status=r['status'],path=str(out/'receipt.json'),sha256=sha(out/'receipt.json'))
def verify(path,digest):
 path=Path(path).resolve();require(sha(path)==digest,'generation receipt pin mismatch');r=read(path);b=model.check_binding(r['binding_path'],r['binding_sha256']);out=path.parent
 require(r['schema']==SCHEMA and r['status']=='PASS_FRESH_ACTUAL_BOARD_GENERATION_ONLY'and r['actual_runtime']is False and r['object_compiled']is False and r['object_reused']is False,'generation not terminal')
 require(len(r['steps'])==2 and not list(out.glob('*.o')),'generation scope changed')
 for n,h in r['artifacts'].items():require(sha(out/n)==h,'generated artifact drift '+n)
 for s,cmd in zip(r['steps'],model.plan(r['side'],out,b)[:2]):require(s['argv']==cmd and s['cwd']==str(ROOT)and s['exit']==0 and s['guard']is None and sha(s['log'])==s['log_sha256']and sha(s['resource_log'])==s['resource_log_sha256'],'generation command/resource drift')
 require(exact(r['actual_contract'],header_and_fir(out,r['side'])),'actual generation contract drift');return r
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['run','verify']);p.add_argument('--binding',type=Path);p.add_argument('--sha256',required=True);p.add_argument('--side',choices=PROFILES);p.add_argument('--out',type=Path);p.add_argument('--slot-granted',action='store_true');p.add_argument('--receipt',type=Path);a=p.parse_args();r=generate(a.binding,a.sha256,a.side,a.out,a.slot_granted)if a.action=='run'else verify(a.receipt,a.sha256);print(json.dumps(r,indent=2))
