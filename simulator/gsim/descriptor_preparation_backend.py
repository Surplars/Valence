#!/usr/bin/env python3
"""Focused current f36471e registered-descriptor A/B backend and stage contract validation. Existing pinned GSIM only."""
import argparse, hashlib, json, os, re, subprocess, time, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--gsim',type=Path,required=True)
    ap.add_argument('--modes',nargs='+',choices=['baseline','descriptor'],default=['baseline','descriptor'])
    ap.add_argument('--jobs',type=int,choices=[1,2,3,4],default=2)
    ap.add_argument('--reuse-from',type=Path)
    a=ap.parse_args(); os.nice(10)
    assert a.modes==['baseline','descriptor'], 'paired baseline then descriptor qualification required'
    assert a.reuse_from is None, 'fresh current A/B model objects required'
    assert sha(a.gsim)=='f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116', 'unqualified GSIM binary'
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'JAVA_TOOL_OPTIONS':'-XX:ActiveProcessorCount='+str(a.jobs),
         'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    inputs={p.relative_to(ROOT).as_posix():sha(p) for p in ROOT.glob('src/**/*.scala')}
    for pattern in ['fpga/next/**/*.json','simulator/gsim/**/*.h','simulator/gsim/**/*.hpp']:
        inputs.update({p.relative_to(ROOT).as_posix():sha(p) for p in ROOT.glob(pattern) if p.is_file()})
    inputs['build.mill']=sha(ROOT/'build.mill')
    for name in ['simulator/gsim/descriptor_preparation_backend.py','simulator/gsim/harness/pool_bare_preparation.cpp','simulator/gsim/harness/preparation_descriptor.cpp','simulator/gsim/harness/preparation_descriptor_reset.cpp','simulator/gsim/harness/preparation_source_lifetime.cpp','simulator/gsim/harness/proof_control_scenarios.cpp',
                 'simulator/gsim/harness/preselected_redirect_lifecycle.cpp',
                 'simulator/gsim/harness/proof_control_block_new.cpp',
                 'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp',
                 'simulator/gsim/ready_store_query77/ready_store_query77_reference.h']:
        inputs[name]=sha(ROOT/name)
    receipt=dict(status='RUNNING',source_inputs=inputs,gsim_sha256=sha(a.gsim),commands=[],arms={},
                 physical_results=False,route=False,state_bits_added=276)
    receipt['tool_bindings']={k:dict(path=str(v),sha256=sha(Path(v))) for k,v in {'gsim':a.gsim,'cxx':os.environ['GSIM_CXX'],'mill':shutil.which('mill')}.items()}
    def save(): (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(label,cmd,negative=None):
        assert all(sha(ROOT/n)==v for n,v in inputs.items()),'source drift'
        start=time.monotonic(); log=out/(label+'.log')
        with log.open('x') as f:
            p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
        t=log.read_text(errors='replace')
        receipt['commands'].append(dict(label=label,argv=list(map(str,cmd)),exit=p.returncode,seconds=round(time.monotonic()-start,3),sha256=sha(log)))
        save()
        if negative:
            if p.returncode==0 or negative not in t: raise RuntimeError('negative control failed '+label+'\n'+t[-3000:])
        elif p.returncode: raise RuntimeError(label+'\n'+t[-6000:])
        print(label,'PASS',flush=True);return t
    save()
    try:
        selector=out/'selector'
        run('selector-emit',['mill','-i','-j',a.jobs,'IonSoC.test.runMain','ooo.PreparationDescriptorGsimMain',selector])
        run('selector-generate',[a.gsim,'--threads=1','--dir='+str(selector),selector/'PreparationDescriptorGsim.fir'])
        selector_sources=sorted(selector.glob('PreparationDescriptorGsim*.cpp'))
        assert selector_sources
        run('selector-compile',[os.environ['GSIM_CXX'],'-std=c++20','-O1','-g0','-fsanitize=address,undefined',
            '-I'+str(selector),ROOT/'simulator/gsim/harness/preparation_descriptor.cpp',*selector_sources,'-ldl','-o',selector/'check'])
        run('selector-positive',[selector/'check'])
        run('selector-negative',[selector/'check','--mutate-control'],'independent descriptor reservation mismatch')
        run('selector-q-exclusion-negative',[selector/'check','--omit-q-reservation'],'independent descriptor reservation mismatch')
        lifetime=out/'lifetime'
        run('lifetime-emit',['mill','-i','-j',a.jobs,'IonSoC.test.runMain','ooo.PreparationSourceLifetimeGsimMain',lifetime])
        run('lifetime-generate',[a.gsim,'--threads=1','--dir='+str(lifetime),lifetime/'PreparationSourceLifetimeGsim.fir'])
        run('lifetime-compile',[os.environ['GSIM_CXX'],'-std=c++20','-O1','-g0','-fsanitize=address,undefined',
            '-I'+str(lifetime),ROOT/'simulator/gsim/harness/preparation_source_lifetime.cpp',*sorted(lifetime.glob('PreparationSourceLifetimeGsim*.cpp')),'-ldl','-o',lifetime/'check'])
        run('lifetime-positive',[lifetime/'check'])
        run('lifetime-reserve-negative',[lifetime/'check','--reserve'],'preparation source illegally reserved again')
        run('lifetime-write-negative',[lifetime/'check','--write'],'preparation source illegally written again')

        source=(ROOT/'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp').read_text()
        anchor='    void check(bool ok,const std::string &why) const'
        fields=r'''
    bool expectedTimerIrq=false;
    uint64_t c1SystemRedirects=0,descriptorRawCycles=0,descriptorSavedCycles=0;
    uint64_t c1Binds=0,c1SystemWait=0,c1Irq=0,c1Evict=0,c1Queries=0;
    ~Bench() {
        std::cout << "C1_METRICS cycles=" << cycle << " retired=" << retired << " accepted=" << accepted
          << " physical=" << physicalCount << " responses=" << responseCount << "\n";
        std::cout << "C1_COVERAGE binds=" << c1Binds << " system_wait=" << c1SystemWait
          << " irq_drain=" << c1Irq << " evict=" << c1Evict << " queries=" << c1Queries << "\n";
        std::cout << "DESCRIPTOR_COVERAGE raw=" << descriptorRawCycles << " saved=" << descriptorSavedCycles << "\n";
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
        descriptorRawCycles += dut.get_io$$descriptorValid() && !dut.get_io$$descriptorSaved();
        descriptorSavedCycles += dut.get_io$$descriptorValid() && dut.get_io$$descriptorSaved();
        std::cout << "DESCRIPTOR_STAGE cycle=" << cycle << " valid=" << uint64_t(dut.get_io$$poolStageValid())
          << " index=" << uint64_t(dut.get_io$$poolStageIndex())
          << " token_index=" << uint64_t(dut.get_io$$poolStageToken$$index())
          << " tag=" << uint64_t(dut.get_io$$poolStageToken$$tag())
          << " address=" << uint64_t(dut.get_io$$poolStageAddress())
          << " data=" << uint64_t(dut.get_io$$poolStageData())
          << " size=" << uint64_t(dut.get_io$$poolStageSize()) << "\n";
        if(!dut.get_io$$poolStageValid())
            check(!dut.get_io$$poolStageToken$$index() && !dut.get_io$$poolStageToken$$tag() &&
              !dut.get_io$$poolStageAddress() && !dut.get_io$$poolStageData() && !dut.get_io$$poolStageSize(),
              "invalid preparation stage must expose defined zero payload bytes");

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
        bare_source=source
        anchor='    Tables tables; Bytes actual, expected;'
        assert bare_source.count(anchor)==1
        bare_source=bare_source.replace(anchor,'    bool independentBare=false;\n'+anchor)
        anchor='e.pa=tables.physical(e.address)'
        assert bare_source.count(anchor)==1
        bare_source=bare_source.replace(anchor,'e.pa=independentBare?e.address:tables.physical(e.address)')
        (out/'bare_backend.cpp').write_text(bare_source)

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
                previous=json.loads((a.reuse_from/'receipt.json').read_text())
                assert previous['gsim_sha256']==receipt['gsim_sha256']
                assert all(previous['source_inputs'].get(n)==v for n,v in inputs.items() if n.endswith('.scala'))
                assert all(c['exit']==0 for c in previous['commands'] if c['label'].startswith(mode+'-compile-'))
                directory.mkdir()
                for p in (a.reuse_from/mode).iterdir():
                    if p.suffix in ('.fir','.h','.cpp','.o') or p.name=='actual-core.json': shutil.copy2(p,directory/p.name)
                reused=True
            else:
                run(mode+'-emit',['mill','-i','-j',a.jobs,'IonSoC.test.runMain','ooo.DescriptorPreparationBackendMain',directory,mode])
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
            for label,driver,args in [('ready',host,['on']),('lifecycle',life,[]),('controls',scenario,[]),('block-new',block,[]),('bare',ROOT/'simulator/gsim/harness/pool_bare_preparation.cpp',[])]:
                binary=directory/label
                run(mode+'-'+label+'-link',[os.environ.get('GSIM_CXX','clang++-19'),*flags,driver,*objs,'-ldl','-o',binary])
                logs[label]=run(mode+'-'+label,[binary,*args])
            run(mode+'-data-negative',[directory/'ready','on','--mutate-data'],'independent execution data mismatch')
            run(mode+'-retirement-negative',[directory/'lifecycle','--mutate-retirement'],'fault/killed/duplicate retirement')
            run(mode+'-bare-negative',[directory/'bare','--mutate-bare-address'],'independent bare resident address mismatch')
            if mode=='descriptor':
                run('descriptor-reset-link',[os.environ['GSIM_CXX'],*flags,ROOT/'simulator/gsim/harness/preparation_descriptor_reset.cpp',*objs,'-ldl','-o',directory/'active-reset'])
                run('descriptor-active-reset',[directory/'active-reset'])

            metrics[mode]={k:re.findall(r'^C1_METRICS .*$',v,re.M) for k,v in logs.items()}
            receipt['arms'][mode]['metrics']=metrics[mode]
            receipt['arms'][mode]['stage_traces']={k:re.findall(r'^DESCRIPTOR_STAGE .*$',v,re.M) for k,v in logs.items()}
            assert all(receipt['arms'][mode]['stage_traces'].values())
            receipt['arms'][mode]['stage_coverage']={k:dict(samples=len(ts),invalid=sum(' valid=0 ' in t for t in ts),valid=sum(' valid=1 ' in t for t in ts)) for k,ts in receipt['arms'][mode]['stage_traces'].items()}
            assert sum(x['invalid'] for x in receipt['arms'][mode]['stage_coverage'].values())>0
            assert sum(x['valid'] for x in receipt['arms'][mode]['stage_coverage'].values())>0
            for name in ['actual-profile','actual-backend-arguments','read-inventory']:
                receipt['arms'][mode][name]=json.loads((directory/(name+'.json')).read_text())
            receipt['arms'][mode]['coverage']={k:re.findall(r'^(?:C1_COVERAGE|DESCRIPTOR_COVERAGE) .*$',v,re.M) for k,v in logs.items()}
            receipt['arms'][mode]['emitted_and_model_sha256']={p.name:sha(p) for p in directory.iterdir() if p.is_file()}
            save()
        if 'baseline' in metrics and 'descriptor' in metrics:
            assert {k:[re.sub(r'cycles=\d+ ', '',x) for x in v] for k,v in metrics['baseline'].items()}=={k:[re.sub(r'cycles=\d+ ', '',x) for x in v] for k,v in metrics['descriptor'].items()},('descriptor changed accepted/retired/physical totals',metrics)
            assert receipt['arms']['baseline']['actual_core']==receipt['arms']['descriptor']['actual_core']
            assert receipt['arms']['descriptor']['fir_register_declarations']==receipt['arms']['baseline']['fir_register_declarations']+2, 'descriptor payload and valid registers only'
            b,c=receipt['arms']['baseline'],receipt['arms']['descriptor']
            receipt['phase_cost']={k:dict(baseline=b['metrics'][k],descriptor=c['metrics'][k]) for k in b['metrics']}
            receipt['same_cycle_trace_equivalence']=False
            assert b['actual-profile']==c['actual-profile'] and b['read-inventory']==c['read-inventory']
            ba,ca=b['actual-backend-arguments'],c['actual-backend-arguments']
            assert {k for k in ba if ba[k]!=ca[k]}=={'registeredMemoryPreparationDescriptor'} and not ba['registeredMemoryPreparationDescriptor'] and ca['registeredMemoryPreparationDescriptor']

        assert all(sha(ROOT/n)==v for n,v in inputs.items()),'source drift after final command'
        receipt['generated_driver_sha256']={p.name:sha(p) for p in out.glob('*.cpp')}
        receipt['status']='PASS_CURRENT_DESCRIPTOR_BACKEND';save();print(receipt['status'],flush=True)
    except BaseException as e:
        receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__': main()
