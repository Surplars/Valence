#!/usr/bin/env python3
"""Bounded shared nearby-word PMP proof. No new clock or permission policy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import run as common
import shared_fetch_pmp_structure


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--build-run', action='store_true')
    a = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        ap.error('unsafe tag')
    if not a.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','models':8,'synthesis':False,'physical_qualification':False}))
        return
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    files = sorted((common.ROOT/'src').rglob('*.scala'))
    files += [common.ROOT/'build.mill', common.ROOT/'.mill-version', common.HERE/'run.py',
        common.HERE/'config/toolchain.json', common.HERE/'shared_fetch_pmp.py', common.HERE/'nearby_word_math.py',
        common.HERE/'shared_fetch_pmp_structure.py',
        common.HERE/'harness/nearby_word_relations.cpp', common.HERE/'harness/pmp_checker.cpp']
    before={str(p.relative_to(common.ROOT)):sha(p) for p in files}
    receipt={'status':'RUNNING','inputs':before,'cases':{},'synthesis':False,'physical_qualification':False}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    try:
        common.run(['python3','-B',common.HERE/'nearby_word_math.py'],log=out/'mathematical-model.log')
        common.SOURCE=Path(os.environ.get('VALENCE_GSIM_SOURCE',str(common.SOURCE))).resolve()
        gsim,cxx=common.setup(False)
        receipt['toolchain'] = {**json.loads((common.BUILD/'toolchain-used.json').read_text()),
            'gsim_binary_sha256':sha(gsim), 'gsim_source':str(common.SOURCE), 'cxx':str(cxx)}
        cases=[]
        for width,offset in ((8,2),(8,4),(62,2),(62,4)):
            cases.append((f'raw-{width}-{offset}','soc.core.ooo.NearbyWordRelationsGsimMain','NearbyWordRelationsGsim',
                'nearby_word_relations.cpp',(str(width),str(offset)),{'WORD_WIDTH':width,'MAX_OFFSET':offset},
                'independent nearby-word ordering mismatch'))
        for packet_width in (2,4):
            for selected in (False,True):
                name=f'packet-{packet_width}-'+('shared' if selected else 'baseline')
                parameters=('packet','word-span','balanced','width='+str(packet_width))
                if selected:parameters+=('shared-relations',)
                cases.append((name,'ooo.PmpCheckerGsimMain','PmpCheckerGsim','pmp_checker.cpp',parameters,
                    {'PACKET_WIDTH':packet_width},'PMP oracle mismatch'))
        for name,emitter,top,harness,parameters,defines,anchor in cases:
            model=common.test(gsim,cxx,a.tag+'/'+name,emitter,top,harness,parameters=parameters,defines=defines)
            negative=subprocess.run([model/'run','--inject-mismatch'],capture_output=True,text=True,timeout=120,env=env)
            (model/'negative.log').write_text(negative.stdout+negative.stderr)
            if negative.returncode!=1 or anchor not in negative.stdout+negative.stderr:
                raise RuntimeError('negative control did not reject intended mismatch: '+name)
            receipt['cases'][name]={'status':'PASS','log':(model/'test.log').read_text(),
                'negative_exit':negative.returncode,'negative_anchor':anchor,'emitter':emitter,
                'parameters':list(parameters),'defines':defines,
                'artifacts':{p.relative_to(out).as_posix():sha(p) for p in model.iterdir()
                             if p.is_file() and (p.suffix in ('.fir','.h','.cpp','.log') or p.name=='run')}}
            (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        for width in (2,4):
            if receipt['cases'][f'packet-{width}-baseline']['log']!=receipt['cases'][f'packet-{width}-shared']['log']:
                raise RuntimeError('matched packet oracle coverage/counters changed')
        receipt['structure'] = shared_fetch_pmp_structure.report(out)
        (out/'structure.json').write_text(json.dumps(receipt['structure'],indent=2)+'\n')
        # Compile actual source mutants into private class overlays. Never edit
        # passed source/classes and never replace the independent policy oracle.
        def classpath(key):
            values=json.loads((common.ROOT/'out/IonSoC/test'/(key+'.json')).read_text())['value']
            result=[value.split(':',3)[3] for value in values]
            # Mill retains optional resource roots in the Java classpath even
            # when a module has no resources. Preserve that exact classpath,
            # while still requiring every dependency JAR and compiled class root.
            optional = {common.ROOT / module / resource
                for module in ('', 'third_party/berkeley-hardfloat')
                for resource in ('compile-resources', 'src/main/resources', 'src/test/resources')}
            missing = [Path(value) for value in result if not Path(value).exists()]
            if not result or any(path not in optional for path in missing):
                raise RuntimeError('missing exact compiled classpath: '+key)
            if missing:
                receipt.setdefault('absent_optional_classpath_resources',{})[key]=list(map(str,missing))
            return result
        cp=':'.join(classpath('runClasspath')); compiler_cp=':'.join(classpath('scalaCompilerClasspath'))
        plugin=next(p for p in classpath('scalacPluginClasspath') if 'chisel-plugin' in p)
        java=shutil.which('java')
        if not java:raise RuntimeError('Java runtime unavailable for isolated mutation compile')
        mutation_cases=[
            ('reverse-priority','PacketFetchPmp.scala','val first = PmpFetchPriority.first(facts)',
             'val first = PmpFetchPriority.first(facts.reverse)','ooo.PmpCheckerGsimMain','PmpCheckerGsim',
             'pmp_checker.cpp',('packet','word-span','balanced','width=2','shared-relations'),
             {'PACKET_WIDTH':2},'PMP oracle mismatch'),
            ('drop-high-wrap','NearbyWordRelations.scala','private val highWrap = high.andR',
             'private val highWrap = false.B','soc.core.ooo.NearbyWordRelationsGsimMain','NearbyWordRelationsGsim',
             'nearby_word_relations.cpp',('8','2'),{'WORD_WIDTH':8,'MAX_OFFSET':2},'independent nearby-word ordering mismatch')]
        for name,filename,old,new,emitter,top,harness,parameters,defines,anchor in mutation_cases:
            directory=out/('mutant-'+name);directory.mkdir();classes=directory/'classes';classes.mkdir()
            source=(common.ROOT/'src/main/scala/core/ooo'/filename).read_text()
            if source.count(old)!=1:raise RuntimeError('mutation anchor drift: '+name)
            mutated=directory/filename;mutated.write_text(source.replace(old,new))
            common.run([java,'-cp',compiler_cp,'scala.tools.nsc.Main','-classpath',cp,'-Xplugin:'+plugin,
                '-language:reflectiveCalls','-d',classes,mutated],log=directory/'compile-overlay.log')
            model=directory/'model';model.mkdir()
            common.run([java,'-cp',str(classes)+':'+cp,emitter,model,*parameters],log=directory/'elaborate.log')
            common.run([gsim,'--threads=1','--dir='+str(model),model/(top+'.fir')],log=directory/'generate.log')
            common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                *['-D'+k+'='+str(v) for k,v in defines.items()],'-I'+str(model),
                *sorted(model.glob(top+'[0-9]*.cpp')),common.HERE/'harness'/harness,'-ldl','-o',model/'run'],
                log=directory/'compile.log')
            result=subprocess.run([model/'run'],capture_output=True,text=True,timeout=120,env=env)
            (directory/'test.log').write_text(result.stdout+result.stderr)
            if result.returncode!=1 or anchor not in result.stdout+result.stderr:
                raise RuntimeError('actual source mutation not caught: '+name)
            receipt.setdefault('source_mutations',{})[name]={'status':'REJECTED_AS_EXPECTED',
                'exit':result.returncode,'anchor':anchor,'mutant_sha256':sha(mutated),
                'log_sha256':sha(directory/'test.log'),'generated_fir_sha256':sha(model/(top+'.fir'))}
        if before!={str(p.relative_to(common.ROOT)):sha(p) for p in files}:
            raise RuntimeError('source drift during PMP proof')
        receipt['status']='PASS_SHARED_PMP_MODULE_ONLY'
        receipt['limits']=['No full-core integration or routed FPGA timing/resource result',
            'Small mathematical model is distinct from actual GSIM RTL tests',
            'No permission, address width, state, packet latency or priority policy change']
    except BaseException as error:
        receipt['status']='FAIL';receipt['error']=str(error)
        raise
    finally:
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(receipt['status']+' '+str(out/'receipt.json'),flush=True)


if __name__=='__main__':main()
