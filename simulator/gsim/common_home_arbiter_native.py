#!/usr/bin/env python3
"""Four-state cold-start proof of actual Home arbitration plus the original RR negative control.

Uses already compiled test classes and explicitly selected installed native tools.
No DUT assertion is removed and no register is forced or randomized.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from bringup import Guard, classpath_manifest, verify_classpath_unchanged
import run as common


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--classpath',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    for tool in ('java','firtool','iverilog','vvp'):
        p.add_argument('--'+tool,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    cp,manifest=classpath_manifest(a.classpath,'ooo.CommonHomeArbiterGsimMain')
    guard=Guard(a.output)
    sources=[common.ROOT/'src/main/scala/core/ooo/cache/MixedCoherentLineHome.scala',
        common.ROOT/'src/test/scala/ooo/CommonHomeArbiterGsim.scala',
        common.HERE/'harness/common_home_arbiter.sv',Path(__file__)]
    hashes=lambda: {str(f.relative_to(common.ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    report={'status':'RUNNING','source_sha256':hashes(),'classpath':manifest,'cases':{},
        'scope':'Actual production Home arbiter control/payload in four-state RTL; old RR cold-start negative; no full Home/CPU/CDC/timing claim'}
    try:
        for mode in ('fixed','legacy'):
            target=a.output/mode;target.mkdir()
            guard.run(mode+'-emit',[a.java,'-Xmx1g','-XX:ActiveProcessorCount=2',f'-Dchisel.project.root={common.ROOT}',
                '-cp',cp,'ooo.CommonHomeArbiterGsimMain',target,mode])
            rtl=target/'CommonHomeArbiterGsim.sv'
            guard.run(mode+'-lower',[a.firtool,target/'CommonHomeArbiterGsim.fir','--disable-all-randomization',
                '--strip-debug-info','--verification-flavor=if-else-fatal','--default-layer-specialization=enable',
                '--lowering-options=disallowLocalVariables,disallowPackedArrays','-o',rtl])
            header=re.search(r'module CommonHomeArbiterGsim\((.*?)\);',rtl.read_text(),re.S).group(1)
            header=re.sub(r'//[^\n]*','',header)
            direction=width='';decl=[];init=[]
            for entry in header.split(','):
                entry=entry.strip();m=re.match(r'(input|output)\s*(\[[^]]+\])?\s*(\w+)$',entry)
                if m:direction,width,name=m.group(1),m.group(2) or '',m.group(3)
                else:
                    assert re.fullmatch(r'\w+',entry),entry
                    name=entry
                decl.append(f"    {'reg' if direction=='input' else 'wire'} {width} {name};")
                if direction=='input':init.append(f"        {name}='0;")
            (target/'signals.svh').write_text('\n'.join(decl)+"\n    CommonHomeArbiterGsim dut (.*);\n")
            (target/'initialize.svh').write_text('\n'.join(init)+'\n')
            binary=target/'run.vvp'
            guard.run(mode+'-compile',[a.iverilog,'-g2012','-s','tb','-I',target,'-o',binary,rtl,
                common.HERE/'harness/common_home_arbiter.sv'])
            results={}
            for first in ('first_a','first_e'):
                log=guard.run(mode+'-'+first,[a.vvp,binary,'+'+first],expected=0 if mode=='fixed' else 1)
                anchor='COMMON_HOME_ARBITER_4STATE_PASS' if mode=='fixed' else f'four-state {first[-1].upper()} selected ready mismatch'
                assert anchor in log,log
                results[first]=log
            report['cases'][mode]={'log':results,'rtl_sha256':hashlib.sha256(rtl.read_bytes()).hexdigest()}
        verify_classpath_unchanged(manifest)
        assert hashes()==report['source_sha256'],'source drift during proof'
        report['status']='PASS_FIXED_AND_OLD_NEGATIVE'
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));raise
    finally:
        report['commands']=guard.records
        (a.output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'])

if __name__=='__main__':main()
