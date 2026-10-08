#!/usr/bin/env python3
"""Protected-head RAM read sharing: integrated-profile FP and precise-memory A/B."""
import argparse, hashlib, json, os, re, subprocess, shutil
from pathlib import Path
import run as common
from issue_storage_census import census

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def inputs():
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',common.HERE/'issue_storage_census.py']
    paths+=sorted((common.HERE/'harness').glob('protected_head*'))
    return {str(p.relative_to(common.ROOT)):sha(p) for p in paths}
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);ap.add_argument('--vectors-root',type=Path,required=True)
    ap.add_argument('--build-run',action='store_true');ap.add_argument('--reuse-dedicated',type=Path);ap.add_argument('--reuse-shared',type=Path);a=ap.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',a.tag):ap.error('invalid tag')
    before=inputs()
    if not a.build_run:print(json.dumps({'status':'PREFLIGHT_ONLY','inputs':len(before)}));return
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    vectors=a.vectors_root.resolve();prior=json.loads((vectors/'receipt.json').read_text())
    if prior['status']!='PASS_FUNCTIONAL_RESOURCE_CANDIDATE' or sha(vectors/'vectors.txt')!=prior['vector_sha256']:
        raise RuntimeError('qualified numerical vectors required')
    state={'status':'RUNNING','inputs':before,'vector_receipt_sha256':sha(vectors/'receipt.json'),
        'vectors':{str(vectors/n):sha(vectors/n) for n in ('vectors.txt','memory-vectors.txt')},'cases':{},'negative':{},'census':{},
        'limits':['External fixture memory, not full SoC physical qualification','No mapped resource or timing claim']}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    try:
        common.run(['mill','-i','IonSoC.test.testOnly','ooo.ProtectedHeadPayloadSpec'],log=out/'contracts.log')
        gsim,cxx=common.setup(False);flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
        for shared in (False,True):
            label='shared' if shared else 'dedicated';model=out/label;model.mkdir()
            fir=model/'FloatingPointCpuGsim.fir';lower=model/'lowered.mlir'
            reuse=a.reuse_shared if shared else a.reuse_dedicated
            if reuse:
                previous=reuse.resolve();locked=json.loads((previous/'receipt.json').read_text())
                # A prior fixture failure does not invalidate its generated model.
                # Reuse only when every current Scala source exactly matches and
                # every model artifact is bound by the old receipt. Harnesses are
                # relinked and all functional/negative tests run afresh below.
                for name,digest in before.items():
                    if name.endswith('.scala') and locked['inputs'].get(name)!=digest:raise RuntimeError('reused model Scala source mismatch: '+name)
                reused={}
                for path in (previous/label).iterdir():
                    if path.name.startswith('FloatingPointCpuGsim') and path.suffix in ('.fir','.h','.cpp','.o') or path.name=='lowered.mlir':
                        name=str(path.relative_to(previous));digest=sha(path)
                        if locked['artifacts'].get(name)!=digest:raise RuntimeError('reused artifact hash mismatch: '+name)
                        shutil.copy2(path,model/path.name);reused[name]=digest
                state['reused_'+label]={'receipt':str(previous/'receipt.json'),'receipt_sha256':sha(previous/'receipt.json'),'artifacts':reused,'prior_status':locked['status']}
                objects=sorted(model.glob('FloatingPointCpuGsim[0-9]*.o'))
                if not objects or not lower.exists():raise RuntimeError('incomplete source-locked object reuse')
            else:
                common.run(['mill','-i','IonSoC.test.runMain','ooo.ProtectedHeadPayloadGsimMain',model,label],log=model/'emit.log')
                common.run(['firtool',fir,'--ir-fir','--disable-all-randomization','-o',lower],log=model/'lower.log')
                common.run([gsim,'--threads=1','--dir='+str(model),fir],log=model/'generate.log')
                objects=[]
                for source in sorted(model.glob('FloatingPointCpuGsim[0-9]*.cpp')):
                    obj=source.with_suffix('.o');common.run([cxx,*flags,'-I'+str(model),'-c',source,'-o',obj],log=model/(source.stem+'-compile.log'));objects.append(obj)
            state['census'][label]=census(lower.read_text())
            rows={}
            for case,harness,vector,defines,anchor in (
                ('numeric','protected_head_full_cpu.cpp','vectors.txt',[],'FP_FULL_CPU_PASS'),
                ('memory','protected_head_memory_cpu.cpp','memory-vectors.txt',['-DFP_MEMORY=1'],'FP_MEMORY_PASS')):
                binary=model/('run-'+case)
                common.run([cxx,*flags,*defines,'-I'+str(model),common.HERE/'harness'/harness,*objects,'-ldl','-o',binary],log=model/(case+'-link.log'))
                log=model/(case+'.log');common.run([binary,vectors/vector],log=log,env=env,timeout=300)
                rows[case]=log.read_text();print(rows[case],flush=True)
                if anchor not in rows[case]:raise RuntimeError('missing fixture pass')
                for mutation,extra,mutationEnv,rejection in (
                    ('owner',[],{'PROTECTED_OWNER_NEGATIVE':'1'},'protected head oracle: full-token owner diverged'),
                    ('architectural',['--inject-mismatch'],{},'independent integer result/flags readback' if case=='numeric' else 'commit value/metadata')):
                    negative=subprocess.run([str(binary),str(vectors/vector),*extra],env={**env,**mutationEnv},capture_output=True,text=True,timeout=120)
                    text=negative.stdout+negative.stderr;(model/(case+'-negative-'+mutation+'.log')).write_text(text)
                    if negative.returncode!=1 or rejection not in text:raise RuntimeError('negative did not reject '+case+'/'+mutation)
                    state['negative'][label+'/'+case+'/'+mutation]='PASS'
            state['cases'][label]=rows
        if state['cases']['shared']!=state['cases']['dedicated']:raise RuntimeError('read sharing changed fixture cycles/retirements')
        for label,wants in [('dedicated',{'pc':8,'instruction':4,'expandedInstruction':2}),('shared',{'pc':7,'instruction':3,'expandedInstruction':1})]:
            modules=state['census'][label]['modules'];bank=next(v for k,v in modules.items() if k.startswith('BankedIssuePayload'))
            for name,ports in wants.items():
                memories=[m for m in bank['memories'] if m['name'].startswith(name+'Bank')]
                if len(memories)!=2 or any(m['read_ports']!=ports or m['write_ports']!=1 for m in memories):
                    raise RuntimeError('unexpected '+label+' '+name+' memory ports: '+str(memories))
        state['status']='PASS_PROTECTED_HEAD_ABLATION'
    except Exception as error:state['status']='FAIL';state['error']=str(error);raise
    finally:
        if inputs()!=before:state['status']='FAIL_SOURCE_CHANGED'
        state['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps({'status':state['status'],'receipt':str(out/'receipt.json')}))
if __name__=='__main__':main()
