#!/usr/bin/env python3
"""Serial exact-source tagged-return focused gate; official GSIM, no tool installation."""
import argparse, json, os, re, shutil, tarfile, time
from pathlib import Path
import bound_store_replay_common as portable
ROOT=Path(__file__).resolve().parents[2]
MODELS={'chainoff':('TaggedStoreReturnChainGsim',['0'],0,'tagged_store_return_chain.cpp'),
        'chainon':('TaggedStoreReturnChainGsim',['1'],1,'tagged_store_return_chain.cpp'),
        'boundaryoff':('TaggedStoreReturnBoundaryGsim',[],0,'tagged_store_return_boundary.cpp'),
        'boundaryon':('TaggedStoreReturnBoundaryGsim',['tagged'],1,'tagged_store_return_boundary.cpp'),
        'postedoff':('TaggedPostedReturnHomeGsim',['0'],0,'tagged_posted_return_home.cpp'),
        'postedon':('TaggedPostedReturnHomeGsim',['1'],1,'tagged_posted_return_home.cpp')}
FLAGS=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
def inputs():
    extra=[Path(__file__),ROOT/'simulator/gsim/harness/board_ddr_multiid.h',ROOT/'simulator/gsim/harness/tagged_posted_return_home.cpp']
    extra+=list((ROOT/'simulator/gsim/harness').glob('tagged_store_return_*'))
    return portable.source_inputs(ROOT,extra)
def main():
    global ROOT
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['freeze','config','emit','generate','build','run'])
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--models',default=','.join(MODELS))
    ap.add_argument('--reuse-models-from',type=Path)
    portable.add_paths(ap,ROOT);a=ap.parse_args();ROOT=a.source_root.resolve()
    tools=portable.tool_paths(a,ap);out=a.output.resolve();names=a.models.split(',')
    assert all(n in MODELS for n in names) and len(names)==len(set(names))
    if portable.preflight(a,inputs(),tools):return
    if a.stage=='freeze':
        out.mkdir(parents=True,exist_ok=False)
        sources=inputs()
        r={'status':'FROZEN','schema':'tagged-return-chain-v1','source_commit':portable.source_revision(ROOT),
           'inputs':sources,'tools':portable.tool_binding(tools),'flags':FLAGS,'commands':[],
           'scope':'paired real LSU/requestQ/SB/DRB/DTA/two routers/cache/home; 2/1 SB/router; posted/fallback and FP-domain cache/home transport',
           'limitations':['MemoryOperation authority premise, not integrated ROB/decoder proof.',
             'No board or FP backend execution qualification; posted/fallback separately exercise actual cache/home transport.']}
        with tarfile.open(out/'source-checkpoint.tar.gz','w:gz') as archive:
            for source in sources: archive.add(ROOT/source,arcname=source)
        r['checkpoint_sha256']=portable.sha(out/'source-checkpoint.tar.gz')
        if a.reuse_models_from:
            old=a.reuse_models_from.resolve();previous=json.loads((old/'receipt.json').read_text())
            assert previous['tools']==r['tools'] and previous['flags']==r['flags'],'reused tool/flag drift'
            qualification='src/test/scala/ooo/TaggedPostedStoreBufferElaboration.scala'
            hardware=lambda mapping:{k:v for k,v in mapping.items() if k!=qualification and (k.endswith('.scala') or k in ('build.mill','.mill-version','.mill-jvm-opts'))}
            r['reused_model_source_exclusion']={'path':qualification,'reason':'standalone emit-only checker; defines no hardware modules and is not referenced by simulated tops','old_sha256':previous['inputs'].get(qualification),'new_sha256':sources.get(qualification)}
            assert hardware(previous['inputs'])==hardware(sources),'reused hardware source drift'
            reused={}
            for name in names:
                if not (old/name).is_dir(): continue
                shutil.copytree(old/name,out/name)
                reused.update({str(p.relative_to(out)):portable.sha(p) for p in (out/name).rglob('*') if p.is_file()})
            r['reused_models']={'source':str(old),'receipt_sha256':portable.sha(old/'receipt.json'),'artifacts':reused}

        (out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
        print('TAGGED_RETURN_SOURCE_FROZEN',out);return
    r=json.loads((out/'receipt.json').read_text())
    assert r['inputs']==inputs(),'source drift requires fresh freeze'
    assert r['tools']==portable.tool_binding(tools),'tool drift'
    def save(): (out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def run(label,args,marker=None,negative=False,corruption=False):
        assert r['inputs']==inputs(),'source drift';portable.check_tools(r['tools'])
        log=out/(label+'.log');assert not log.exists(),'preserve prior result; new freeze required'
        started=time.monotonic()
        import subprocess
        with log.open('x') as f:
            process=subprocess.Popen(portable.command_args(args,tools),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'})
            _,status,usage=os.wait4(process.pid,0);process.returncode=os.waitstatus_to_exitcode(status)
        text=log.read_text(errors='replace')
        step={'label':label,'command':list(map(str,args)),'exit':process.returncode,
              'elapsed_seconds':round(time.monotonic()-started,3),'peak_rss_KiB':usage.ru_maxrss,
              'log_sha256':portable.sha(log),'negative_control':negative,'mutation_required':corruption}
        r['commands'].append(step);save();print(label,process.returncode,step['elapsed_seconds'],flush=True)
        assert (process.returncode!=0 if negative else process.returncode==0) and (not marker or marker in text) and (not corruption or re.search(r'ACTUAL_CORRUPTION count=[1-9]',text)),(step,text[-7000:])
    try:
        if a.stage=='config':
            run('config',[tools['mill'],'-i','-j','1','IonSoC.test.runMain','ooo.TaggedStoreReturnNamespaceCheckMain'],'TAGGED_RETURN_NAMESPACE_PASS')
            run('posted-sb-elaboration',[tools['mill'],'-i','-j','1','IonSoC.test.runMain','ooo.TaggedPostedStoreBufferElaborationMain',out/'posted-sb'],'TAGGED_POSTED_STORE_BUFFER_ELABORATION_PASS')
        else:
            for name in names:
                top,parameters,tagged,host=MODELS[name];model=out/name
                if a.stage=='emit':
                    model.mkdir(exist_ok=False)
                    run(name+'-emit',[tools['mill'],'-i','-j','1','IonSoC.test.runMain','ooo.'+top+'Main',model,*parameters])
                elif a.stage=='generate':run(name+'-generate',[tools['gsim'],'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(top+'.fir')])
                elif a.stage=='build':
                    flags=FLAGS+['-I'+str(model),'-DTAGGED_STORE_RETURNS='+str(tagged)]
                    hostfile=ROOT/'simulator/gsim/harness'/host
                    run(name+'-syntax',[tools['cxx'],*flags,'-fsyntax-only',hostfile])
                    sources=sorted(model.glob(top+'[0-9]*.cpp'));assert sources;objects=[]
                    for i,source in enumerate(sources):
                        obj=source.with_suffix('.o');objects.append(obj)
                        if obj.exists():
                            assert r.get('reused_models',{}).get('artifacts',{}).get(str(obj.relative_to(out)))==portable.sha(obj),'unbound reused object'
                            r['commands'].append({'label':name+'-compile-'+str(i),'status':'REUSED_IDENTICAL_MODEL_OBJECT','sha256':portable.sha(obj)});save()
                        else:run(name+'-compile-'+str(i),[tools['cxx'],*flags,'-c',source,'-o',obj])
                    run(name+'-link',[tools['cxx'],*flags,hostfile,*objects,'-ldl','-o',model/'run'])
                else:
                    binary=model/'run';marker='TAGGED_CHAIN_PASS' if name.startswith('chain') else ('TAGGED_POSTED_RETURN_PASS' if name.startswith('posted') else 'TAGGED_STORE_RETURN_BOUNDARY_PASS')
                    run(name+'-positive',[binary],marker)
                    if name=='chainon':
                        negatives={'generation':'completion changed high ROB generation','owner':'cache independent byte/owner mismatch',
                            'stale':'unknown or stale return handle','duplicate':'duplicate or unaccepted cache response',
                            'early':'store success before actual SRAM write'}
                        for mode,reason in negatives.items():run(name+'-negative-'+mode,[binary,'--mutate-'+mode],reason,True,True)
                    if name=='postedon':
                        for mode,reason in {'owner':'unknown or stale tagged owner','posted-token':'posted ACK lost exact full token, context or ticket','fallback-ticket':'fallback ACK lost exact full token or ticket'}.items():run(name+'-negative-'+mode,[binary,'--mutate-'+mode],reason,True,True)
                    if name.startswith('boundary'):
                        for mode in ('local-ack','router-response'):run(name+'-negative-'+mode,[binary,'--corrupt-'+mode],'ACTUAL_CORRUPTION',True,True)
                        if tagged:
                            for mode,reason in [('sb','StoreBuffer return lost its direct or ordered drain owner'),('router','router memory return lost its exact owner')]:run(name+'-illegal-external-'+mode,[binary,'--invalid-'+mode+'-return'],reason,True)
        r.setdefault('completed',[]).append({'stage':a.stage,'models':names});r['status']=a.stage.upper()+'_PASS';save()
    except BaseException as e:r['status']=a.stage.upper()+'_FAIL';r['error']=str(e);save();raise
if __name__=='__main__':main()
