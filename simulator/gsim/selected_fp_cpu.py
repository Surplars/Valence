#!/usr/bin/env python3
"""One selected-v2 FP composition model against source-locked qualified R5 oracles."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
import run as common

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def bind_executed_vectors(qualified, fpu):
    """Bind relocated executable inputs; archived absolute paths are provenance only."""
    expected = {}
    for recorded, digest in qualified.get('vectors', {}).items():
        name = Path(recorded).name
        if name not in {'vectors.txt', 'memory-vectors.txt'} or name in expected:
            raise RuntimeError('ambiguous or unexpected qualified vector identity: ' + name)
        expected[name] = digest
    if set(expected) != {'vectors.txt', 'memory-vectors.txt'}:
        raise RuntimeError('qualified vector inventory is incomplete')
    bound = {}
    for name, digest in expected.items():
        path = (fpu / name).resolve()
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError('executed qualified vector changed or missing: ' + name)
        bound[str(path)] = digest
    return bound


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True)
    ap.add_argument('--qualified',required=True,type=Path);ap.add_argument('--fpu-qualified',required=True,type=Path)
    ap.add_argument('--build-run',action='store_true');args=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):ap.error('invalid output tag')
    files=sorted((common.ROOT/'src').rglob('*.scala'))+sorted((common.ROOT/'third_party/berkeley-hardfloat/src/main/scala').rglob('*.scala'))
    files += [common.ROOT/'build.mill',common.ROOT/'.mill-version',Path(__file__).resolve(),common.HERE/'run.py']
    files += [common.HERE/'harness'/n for n in ('protected_head_full_cpu.cpp','protected_head_memory_cpu.cpp','protected_head_payload.h')]
    before={str(p.relative_to(common.ROOT)):sha(p) for p in files}
    if not args.build_run:print(json.dumps({'status':'PREFLIGHT_ONLY','inputs':len(before),'profile':'FpgaNextConfig.Selected','test_local_aperture_bytes':4096}));return
    out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    prior=args.qualified.resolve();qualified=json.loads((prior/'receipt.json').read_text());assert qualified['status']=='PASS_PROTECTED_HEAD_ABLATION'
    fpu=args.fpu_qualified.resolve();fp=json.loads((fpu/'receipt.json').read_text());assert fp['status']=='PASS_FUNCTIONAL_RESOURCE_CANDIDATE'
    for name,digest in before.items():
        if name.startswith('third_party/') and fp['source_sha256'].get(name)!=digest:raise RuntimeError('qualified HardFloat dependency changed')
        if name.startswith('simulator/gsim/harness/') and qualified['inputs'].get(name)!=digest:raise RuntimeError('qualified independent oracle source changed')
    if sha(fpu/'receipt.json') != qualified.get('vector_receipt_sha256'):
        raise RuntimeError('qualified FPU receipt does not match behavior proof')
    vectors = bind_executed_vectors(qualified, fpu)
    state={'status':'RUNNING','inputs':before,'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'qualified_behavior_receipt':str(prior/'receipt.json'),'qualified_behavior_sha256':sha(prior/'receipt.json'),
        'qualified_fpu_receipt_sha256':sha(fpu/'receipt.json'),'vectors':vectors,'historical_vector_paths':qualified['vectors'],'cases':{},'negatives':{},
        'profile':'FpgaNextConfig.Selected.coreParams','test_local_aperture':{'base':'0x80010000','bytes':4096},
        'limits':['CPU with external instruction/data fixtures; not a whole-board or PPA result','No new optimization; combined selected profile composition gate']}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    try:
        gsim,cxx=common.setup(False);model=out/'model';model.mkdir()
        common.run(['mill','-i','IonSoC.test.runMain','ooo.SelectedFpCpuGsimMain',model],log=out/'emit.log')
        fir=model/'FloatingPointCpuGsim.fir';common.run([gsim,'--threads=1','--dir='+str(model),fir],log=out/'generate.log')
        flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all'];objects=[]
        for source in sorted(model.glob('FloatingPointCpuGsim[0-9]*.cpp')):
            obj=source.with_suffix('.o');common.run([cxx,*flags,'-I'+str(model),'-c',source,'-o',obj],log=out/(source.stem+'-compile.log'));objects.append(obj)
        for case,harness,vector,defines in [('numeric','protected_head_full_cpu.cpp','vectors.txt',[]),('memory','protected_head_memory_cpu.cpp','memory-vectors.txt',['-DFP_MEMORY=1'])]:
            binary=out/('run-'+case)
            common.run([cxx,*flags,*defines,'-I'+str(model),common.HERE/'harness'/harness,*objects,'-ldl','-o',binary],log=out/(case+'-link.log'))
            log=out/(case+'.log');common.run([binary,fpu/vector],log=log,env=env,timeout=300);text=log.read_text();state['cases'][case]=text;print(text,flush=True)
            if text!=qualified['cases']['shared'][case]:raise RuntimeError('selected composition changed qualified '+case+' behavior/cycles')
            for mutation,extra,delta,rejection in [('owner',[],{'PROTECTED_OWNER_NEGATIVE':'1'},'protected head oracle: full-token owner diverged'),
                ('architectural',['--inject-mismatch'],{},'independent integer result/flags readback' if case=='numeric' else 'commit value/metadata')]:
                negative=subprocess.run([str(binary),str(fpu/vector),*extra],env={**env,**delta},capture_output=True,text=True,timeout=120)
                (out/(case+'-negative-'+mutation+'.log')).write_text(negative.stdout+negative.stderr)
                if negative.returncode!=1 or rejection not in negative.stdout+negative.stderr:raise RuntimeError('negative did not reject '+case+'/'+mutation)
                state['negatives'][case+'/'+mutation]='PASS'
        state['status']='PASS_SELECTED_V2_FP_COMPOSITION'
    except Exception as error:state['status']='FAIL';state['error']=str(error);raise
    finally:
        if any(sha(common.ROOT/n)!=v for n,v in before.items()):state['status']='FAIL_SOURCE_CHANGED'
        state['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps({'status':state['status'],'receipt':str(out/'receipt.json')}))
if __name__=='__main__':main()
