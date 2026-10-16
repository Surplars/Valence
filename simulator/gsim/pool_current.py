#!/usr/bin/env python3
"""Focused independent current-profile pool/lifecycle validation. Existing pinned GSIM only."""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--gsim',type=Path,required=True)
    ap.add_argument('--modes',nargs='+',choices=['baseline','pool'],default=['baseline','pool'])
    ap.add_argument('--jobs',type=int,choices=[1,2,3,4],default=2)
    ap.add_argument('--reuse-from',type=Path)
    a=ap.parse_args(); os.nice(10)
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'JAVA_TOOL_OPTIONS':'-XX:ActiveProcessorCount='+str(a.jobs),
         'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    inputs={p.relative_to(ROOT).as_posix():sha(p) for p in ROOT.glob('src/**/*.scala')}
    for name in ['simulator/gsim/pool_current.py','simulator/gsim/harness/proof_control_scenarios.cpp',
                 'simulator/gsim/harness/preselected_redirect_lifecycle.cpp',
                 'simulator/gsim/harness/proof_control_block_new.cpp',
                 'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp',
                 'simulator/gsim/ready_store_query77/ready_store_query77_reference.h']:
        inputs[name]=sha(ROOT/name)
    receipt=dict(status='RUNNING',source_inputs=inputs,gsim_sha256=sha(a.gsim),commands=[],arms={},
                 physical_results=False,route=False,state_bits_added=0)
    def save(): (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(label,cmd,negative=None):
        assert all(sha(ROOT/n)==v for n,v in inputs.items()),'source drift'
        start=time.monotonic(); log=out/(label+'.log')
        with log.open('x') as f:
            p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
        t=log.read_text(errors='replace')
        receipt['commands'].append(dict(label=label,exit=p.returncode,seconds=round(time.monotonic()-start,3),sha256=sha(log)))
        save()
        if negative:
            if p.returncode==0 or negative not in t: raise RuntimeError('negative control failed '+label+'\n'+t[-3000:])
        elif p.returncode: raise RuntimeError(label+'\n'+t[-6000:])
        print(label,'PASS',flush=True);return t
    save()
    try:
        source=(ROOT/'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp').read_text()
        anchor='    void check(bool ok,const std::string &why) const'
        fields=r'''
    bool expectedTimerIrq=false;
    uint64_t c1SystemRedirects=0;
    uint64_t c1Binds=0,c1SystemWait=0,c1Irq=0,c1Evict=0,c1Queries=0;
    ~Bench() {
        std::cout << "C1_METRICS cycles=" << cycle << " retired=" << retired << " accepted=" << accepted
          << " physical=" << physicalCount << " responses=" << responseCount << "\n";
        std::cout << "C1_COVERAGE binds=" << c1Binds << " system_wait=" << c1SystemWait
          << " irq_drain=" << c1Irq << " evict=" << c1Evict << " queries=" << c1Queries << "\n";
    }
'''
        assert source.count(anchor)==1
        source=source.replace(anchor,fields+anchor)
        anchor='        if(reset){dut.resetAll();++cycle;return{};}'
        observe=r'''
        c1Binds += dut.get_io$$shadow$$actualMask()!=0;
        c1SystemWait += dut.get_io$$shadow$$systemPending() && !dut.get_io$$shadow$$reserveSystem();
        c1Irq += dut.get_io$$shadow$$irqDrain(); c1Evict += dut.get_io$$shadow$$evict();
        c1Queries += dut.get_io$$queryValid();
'''
        assert source.count(anchor)==1;source=source.replace(anchor,anchor+observe)
        old=r'''            const auto&e=entries.at(live.front());check(t==live.front()&&e.fault&&dut.get_io$$trap$$bits$$cause()==(e.store?7:5)&&dut.get_io$$trap$$bits$$tval()==e.address,
                "late memory fault lost exact owner/cause/original VA");'''
        new=r'''            const auto&e=entries.at(live.front());
            if(expectedTimerIrq) {
                check(t==live.front() && dut.get_io$$trap$$bits$$cause()==((1ULL<<63)|7) &&
                    dut.get_io$$trap$$bits$$tval()==0 && !dut.get_io$$lsuStart(),
                    "independent timer IRQ precise owner/cause/launch mismatch");
            } else {
                check(t==live.front()&&e.fault&&dut.get_io$$trap$$bits$$cause()==(e.store?7:5)&&dut.get_io$$trap$$bits$$tval()==e.address,
                    "late memory fault lost exact owner/cause/original VA");
            }'''
        assert source.count(old)==1;source=source.replace(old,new)
        old='''                predicted=architectural;for(auto k:live){const auto&keep=entries.at(k);if(keep.writes&&keep.rd)predicted[keep.rd]=keep.expected;}
            }
        }
#define COMMIT'''
        new='''                predicted=architectural;for(auto k:live){const auto&keep=entries.at(k);if(keep.writes&&keep.rd)predicted[keep.rd]=keep.expected;}
            } else if(e.system) {
                check(dut.get_io$$redirect$$bits$$target()==e.inst.pc+4,
                    "independent sequential system redirect target mismatch");
                auto at=std::find(live.begin(),live.end(),t);check(at==live.begin(),"system redirect is not exact live head");
                for(auto i=at+1;i!=live.end();++i){entries.at(*i).killed=true;++killCount;}
                live.erase(at+1,live.end());++c1SystemRedirects;
                predicted=architectural;for(auto k:live){const auto&keep=entries.at(k);if(keep.writes&&keep.rd)predicted[keep.rd]=keep.expected;}
            }
        }
#define COMMIT'''
        assert source.count(old)==1;source=source.replace(old,new)
        host=out/'observed_backend.cpp';host.write_text(source)
        life=out/'observed_lifecycle.cpp'
        life.write_text((ROOT/'simulator/gsim/harness/preselected_redirect_lifecycle.cpp').read_text().replace(
            '#include "ready_store_query77_backend.cpp"','#include "observed_backend.cpp"'))
        scenario=out/'proof_control_scenarios.cpp'
        scenario.write_text((ROOT/'simulator/gsim/harness/proof_control_scenarios.cpp').read_text())
        block=out/'proof_control_block_new.cpp'
        block.write_text((ROOT/'simulator/gsim/harness/proof_control_block_new.cpp').read_text())
        metrics={}
        for mode in a.modes:
            directory=out/mode
            reused=False
            if a.reuse_from and (a.reuse_from/mode).exists():
                import shutil
                previous=json.loads((a.reuse_from/'receipt.json').read_text())
                assert previous['gsim_sha256']==receipt['gsim_sha256']
                assert all(previous['source_inputs'].get(n)==v for n,v in inputs.items() if n.endswith('.scala'))
                assert all(c['exit']==0 for c in previous['commands'] if c['label'].startswith(mode+'-compile-'))
                directory.mkdir()
                for p in (a.reuse_from/mode).iterdir():
                    if p.suffix in ('.fir','.h','.cpp','.o') or p.name=='actual-core.json': shutil.copy2(p,directory/p.name)
                reused=True
            else:
                run(mode+'-emit',['mill','-i','-j',a.jobs,'IonSoC.test.runMain','ooo.PoolCurrentBackendMain',directory,mode])
            top='ReadyStoreQuery77BackendGsim'
            fir=(directory/(top+'.fir')).read_text()
            # Raw register declarations are a structural state audit, not mapped FF resources.
            receipt['arms'][mode]={'fir_register_declarations':len(re.findall(r'^\s+reg(?:reset)?\s',fir,re.M)),
                'actual_core':json.loads((directory/'actual-core.json').read_text())}
            receipt['arms'][mode]['reused_model_from']=str(a.reuse_from/mode) if reused else None
            if not reused:
                run(mode+'-generate',[a.gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(directory),directory/(top+'.fir')])
            flags=['-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                   '-I'+str(directory),'-I'+str(out),'-I'+str(ROOT/'simulator/gsim/ready_store_query77')]
            objs=[]
            for i,p in enumerate(sorted(directory.glob(top+'[0-9]*.cpp'))):
                obj=p.with_suffix('.o')
                if not reused: run(mode+'-compile-'+str(i),[os.environ.get('GSIM_CXX','clang++-19'),*flags,'-c',p,'-o',obj])
                assert obj.exists();objs.append(obj)
            assert objs
            logs={}
            for label,driver,args in [('ready',host,['on']),('lifecycle',life,[]),('controls',scenario,[]),('block-new',block,[])]:
                binary=directory/label
                run(mode+'-'+label+'-link',[os.environ.get('GSIM_CXX','clang++-19'),*flags,driver,*objs,'-ldl','-o',binary])
                logs[label]=run(mode+'-'+label,[binary,*args])
            run(mode+'-data-negative',[directory/'ready','on','--mutate-data'],'independent execution data mismatch')
            run(mode+'-retirement-negative',[directory/'lifecycle','--mutate-retirement'],'fault/killed/duplicate retirement')
            metrics[mode]={k:re.findall(r'^C1_METRICS .*$',v,re.M) for k,v in logs.items()}
            receipt['arms'][mode]['metrics']=metrics[mode]
            receipt['arms'][mode]['coverage']={k:re.findall(r'^C1_COVERAGE .*$',v,re.M) for k,v in logs.items()}
            save()
        if 'baseline' in metrics and 'pool' in metrics:
            assert metrics['baseline']==metrics['pool'],('pool changed cycles/traffic',metrics)
            assert receipt['arms']['baseline']['actual_core']==receipt['arms']['pool']['actual_core']
            assert receipt['arms']['baseline']['fir_register_declarations']==receipt['arms']['pool']['fir_register_declarations']
        receipt['status']='PASS_CURRENT_POOL_BACKEND';save();print(receipt['status'],flush=True)
    except BaseException as e:
        receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__': main()
