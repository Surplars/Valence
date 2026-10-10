"""Explicit exact-byte donor-object provenance after a fresh actual OFF generation."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,shutil
D=Path(__file__).resolve().parent;B=D.parent;P=B/'posted-preparation-priority-cpu-prep-r1';OLD=B/'store-prefetch-lru-victim-cpu-prep-r1'
DONOR=OLD/'model-on-r1/receipt.json';DONOR_SHA='98520edab965281b7ef4c55d1b3ec0a437fa827cc64bdcc0c556d747cbdcea83'
BINDING_SHA='ef3788d95fcf3036c712170c8d48d3b7d89416dfcfd831e71081f268cb81eb44'
FLAGS=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
def need(x,m):
 if not x:raise RuntimeError(m)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def isolated(script,args):
 cmd=[sys.executable,'-B',str(script),*map(str,args)];q=subprocess.run(cmd,cwd=B,capture_output=True,text=True)
 need(q.returncode==0,'isolated original validator failed: '+q.stderr[-3000:]);return json.loads(q.stdout),dict(argv=cmd,cwd=str(B),exit=0,validator_path=str(script),validator_sha256=sha(script),stdout_sha256=hashlib.sha256(q.stdout.encode()).hexdigest())
def literal(generated,donor):
 rows={}
 for name in ('BoardSocGsim0.cpp','BoardSocGsim.h','BoardSocGsim.fir'):
  a=Path(generated)/name;b=Path(donor)/name;rows[name]=dict(new_sha256=sha(a),donor_sha256=sha(b),new_bytes=a.stat().st_size,donor_bytes=b.stat().st_size)
 return rows,all(rows[n]['new_sha256']==rows[n]['donor_sha256'] and rows[n]['new_bytes']==rows[n]['donor_bytes'] for n in ('BoardSocGsim0.cpp','BoardSocGsim.h'))
def investigate(generation,digest):
 generation=Path(generation).resolve();need(sha(generation)==digest,'generation receipt identity mismatch');g,gv=isolated(P/'generate.py',['verify','--receipt',generation,'--sha256',digest]);need(g['side']=='off','only explicit posted-preparation-priority OFF may use baseline donor');need(g['binding_sha256']==BINDING_SHA,'new generation binding differs');need({p.name for p in generation.parent.iterdir()if p.is_file()}==set(g['artifacts'])|{'receipt.json'},'generated file inventory changed')
 need(sha(DONOR)==DONOR_SHA,'baseline donor receipt drift');old,ov=isolated(OLD/'model.py',['verify','--receipt',DONOR,'--sha256',DONOR_SHA]);need(old['side']=='on'and old['compiler_flags']==FLAGS,'wrong prior frontier+LRU ON donor')
 b=read(g['binding_path']);ob=read(old['binding_path']);need(b['tools']==ob['tools']and b['tool_receipt_sha256']==ob['tool_receipt_sha256'],'object compiler/tool closure differs')
 need(b['environment']==ob['environment']and b['environment_normalization']==ob['environment_normalization'],'compiler environment differs')
 rows,equal=literal(generation.parent,DONOR.parent)
 profile=read(generation.parent/'profile.json');old_profile=read(DONOR.parent/'profile.json')
 for part in ('core','profile'):need(profile[part].pop('postedPreparationPriority') is False,'reuse only OFF new flag')
 need(profile==old_profile,'actual full profile differs beyond disabled new flag')
 return dict(schema='posted-preparation-priority-literal-object-eligibility-v1',status='PASS_LITERAL_CPP_HEADER_OBJECT_REUSE_ELIGIBLE'if equal else'LITERAL_IDENTITY_MISMATCH_NOT_REUSABLE',generation_path=str(generation),generation_sha256=digest,donor_path=str(DONOR),donor_sha256=DONOR_SHA,new_binding_sha256=BINDING_SHA,checks=rows,donor_object_sha256=old['artifacts']['BoardSocGsim0.o'],compiler_flags=FLAGS,actual_validator_invocations=[gv,ov],normalization_applied=False,raw_fir_equal=rows['BoardSocGsim.fir']['new_sha256']==rows['BoardSocGsim.fir']['donor_sha256'],historical_system_headers_bound=False,donor_is_existing_qualified_object_not_fresh_compilation=True,reuse_authority='Parent/root explicitly permits exact CPP/header + actual profile disabled-only + complete original object receipt; no historical system-header claim.',object_reuse_performed=False,new_runtime_qualified=False,checker_sha256=sha(__file__))
def reuse(eligibility,digest,out):
 need(sha(eligibility)==digest,'eligibility receipt drift');e=read(eligibility);fresh=investigate(e['generation_path'],e['generation_sha256']);need(fresh==e,'literal eligibility changed');need(e['status']=='PASS_LITERAL_CPP_HEADER_OBJECT_REUSE_ELIGIBLE','literal generated mismatch forbids object reuse');out=Path(out).resolve();need(not out.exists(),'fresh object output required');g=read(e['generation_path']);src=Path(e['generation_path']).parent
 size=sum((src/n).stat().st_size for n in g['artifacts'])+(DONOR.parent/'BoardSocGsim0.o').stat().st_size;need(size<180*1024**2,'object output cap');need(shutil.disk_usage(out.parent).free>size+700*1024**2,'object starting disk floor');out.mkdir()
 for n,h in g['artifacts'].items():need(sha(src/n)==h,'generated donor file changed');shutil.copy2(src/n,out/n)
 shutil.copy2(DONOR.parent/'BoardSocGsim0.o',out/'BoardSocGsim0.o');need(sha(out/'BoardSocGsim0.o')==e['donor_object_sha256'],'copied object changed');copied_rows,equal=literal(out,DONOR.parent);need(equal,'copied literal CPP/header/FIR differs')
 r=dict(schema='posted-preparation-priority-literal-object-model-v1',status='PASS_FRESH_GENERATION_LITERAL_DONOR_OBJECT_MODEL_ONLY',side='off',generation_path=e['generation_path'],generation_sha256=e['generation_sha256'],eligibility_path=str(Path(eligibility).resolve()),eligibility_sha256=digest,object_compiled_again=False,object_reused=True,actual_runtime=False,existing_model_receipt_modified=False,source_model_binding_sha256=BINDING_SHA,binding_path=g['binding_path'],binding_sha256=g['binding_sha256'],actual_contract=g['actual_contract'],compiler_flags=FLAGS,artifact_limit_bytes=180*1024**2,checker_sha256=sha(__file__),copied_object_origin=dict(path=str(DONOR.parent/'BoardSocGsim0.o'),sha256=e['donor_object_sha256']),artifacts={p.name:sha(p)for p in out.iterdir()if p.is_file()})
 save(out/'receipt.json',r);return dict(path=str(out/'receipt.json'),sha256=sha(out/'receipt.json'),status=r['status'])
def verify(path,digest):
 path=Path(path).resolve();need(sha(path)==digest,'object model receipt drift');r=read(path);need(r['schema']=='posted-preparation-priority-literal-object-model-v1'and r['status']=='PASS_FRESH_GENERATION_LITERAL_DONOR_OBJECT_MODEL_ONLY'and r['side']=='off'and r['actual_runtime']is False and r['object_reused']is True and r['object_compiled_again']is False,'object model scope');need(r['artifact_limit_bytes']==180*1024**2 and sum(p.stat().st_size for p in path.parent.iterdir()if p.is_file())<=r['artifact_limit_bytes'],'object artifact budget');need(r['compiler_flags']==FLAGS,'object compiler flags drift');need(r['checker_sha256']==sha(__file__),'object verifier source drift');need(sha(r['eligibility_path'])==r['eligibility_sha256'],'object eligibility drift');e=read(r['eligibility_path']);need(investigate(e['generation_path'],e['generation_sha256'])==e,'current eligibility differs');g=read(e['generation_path']);need(r['actual_contract']==g['actual_contract']and r['binding_sha256']==g['binding_sha256']and r['binding_path']==g['binding_path'],'new generation contract differs')
 for n,h in r['artifacts'].items():need(sha(path.parent/n)==h,'object artifact changed '+n)
 need({p.name for p in path.parent.iterdir()if p.is_file()}==set(r['artifacts'])|{'receipt.json'},'object file inventory changed');need(r['artifacts']['BoardSocGsim0.o']==e['donor_object_sha256'],'object donor digest differs');return r
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['check','reuse','verify']);a.add_argument('--generation');a.add_argument('--eligibility');a.add_argument('--receipt');a.add_argument('--sha256',required=True);a.add_argument('--out',type=Path);v=a.parse_args()
 if v.action=='check':r=investigate(v.generation,v.sha256);save(v.out,r)
 elif v.action=='reuse':r=reuse(v.eligibility,v.sha256,v.out)
 else:r=verify(v.receipt,v.sha256)
 print(json.dumps(r,indent=2))
