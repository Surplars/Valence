#!/usr/bin/env python3
"""Fresh original/repaired GSIM emissions; deterministic seeded byte-span regression."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser()
    for k in ('original','repaired','cxx','output'): p.add_argument('--'+k, required=True)
    a=p.parse_args(); out=Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    fixtures=Path(__file__).resolve().parent/'fixtures'; results={}
    for label, tool in [('original',a.original),('repaired',a.repaired)]:
        model=out/label; model.mkdir()
        commands=[[tool,'--threads=1',f'--dir={model}',str(fixtures/'InitByteSpan.fir')]]
        def run(cmd,name,expected=0):
            r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=os.environ,timeout=120)
            (model/name).write_text(r.stdout)
            if r.returncode!=expected: raise RuntimeError(f'{name}: exit {r.returncode}, expected {expected}: {r.stdout}')
            if 'runtime error:' in r.stdout or 'Sanitizer' in r.stdout: raise RuntimeError(r.stdout)
            return r.stdout
        run(commands[0],'generate.log')
        header=(model/'InitByteSpan.h').read_text()
        assert 'tailRam' in header and '[64]' in header
        cmd=[a.cxx,'-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',f'-I{model}',*map(str,sorted(model.glob('*.cpp'))),str(fixtures/'InitByteSpan.cpp'),'-o',str(model/'test')]
        commands.append(cmd); run(cmd,'compile.log')
        result=run([str(model/'test')],'run.log',2 if label=='original' else 0)
        if label=='original': assert 'tail=165' in result
        else: assert 'uncleared=0 tail=0' in result
        results[label]={'tool':str(Path(tool).resolve()),'tool_sha256':sha(Path(tool)),'commands':commands,'result':result,'files':{str(f.relative_to(out)):sha(f) for f in model.iterdir() if f.is_file()}}
    receipt={'status':'PASS','mode':'deterministic; RANDOMIZE_INIT not qualified','results':results,'fixtures':{str(f):sha(f) for f in [fixtures/'InitByteSpan.fir',fixtures/'InitByteSpan.cpp',Path(__file__).resolve()]}}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__': main()
