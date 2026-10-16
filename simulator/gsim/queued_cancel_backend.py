#!/usr/bin/env python3
"""One pinned reconstructed-backend queued-cancel scenario; test-only external backpressure."""
import argparse, hashlib, json, os, shutil, subprocess, tarfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
COMMIT = 'd69f4cd2d1e3160853ae22904b795ea9a4c704de'
OVERLAY = 'src/test/scala/ooo/QueuedCancelBackendGsim.scala'
HOST = 'simulator/gsim/harness/queued_cancel_backend.cpp'
ORACLES = ['simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp',
           'simulator/gsim/ready_store_query77/ready_store_query77_reference.h']
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(root):
    paths = [*root.glob('src/**/*.scala'), *root.glob('third_party/**/*.scala'),
        root/'build.mill', root/'.mill-version', root/'.mill-jvm-opts', *[root/n for n in ORACLES]]
    return {str(p.relative_to(root)): sha(p) for p in sorted(paths)}
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--gsim',type=Path,required=True)
    ap.add_argument('--reuse-run',type=Path,help='Reuse source-identical completed model stages after a failed host test')
    a=ap.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False);os.nice(10)
    gsim=a.gsim.resolve();previous=None
    if a.reuse_run:
        a.reuse_run=a.reuse_run.resolve()
        previous=json.loads((a.reuse_run/'receipt.json').read_text())
        assert previous['status']=='FAILED_PRESERVE_EVIDENCE'
        assert previous['source_commit']==COMMIT and previous['gsim_sha256']==sha(gsim)
        root=a.reuse_run/'source';archive=a.reuse_run/'source.tar'
        assert inventory(root)==previous['source_inputs'] and sha(root/OVERLAY)==sha(ROOT/OVERLAY)
    else:
        root=o/'source';root.mkdir();archive=o/'source.tar'
        with archive.open('xb') as f:subprocess.run(['git','archive',COMMIT],cwd=ROOT,stdout=f,check=True)
        with tarfile.open(archive) as f:f.extractall(root,filter='data')
        assert not (root/OVERLAY).exists()
        shutil.copy2(ROOT/OVERLAY,root/OVERLAY)
    driver=o/'queued_cancel_backend.cpp';shutil.copy2(ROOT/HOST,driver)
    frozen=inventory(root)
    receipt=dict(status='RUNNING',source_commit=COMMIT,source_inputs=frozen,
        archive_sha256=sha(archive),observer_sha256=sha(root/OVERLAY),driver_sha256=sha(driver),
        runner_sha256=sha(Path(__file__)),gsim_sha256=sha(gsim),commands=[],reused_artifacts=[],
        previous_receipt_sha256=sha(a.reuse_run/'receipt.json') if previous else None,
        stimulus='Ready/valid hold at existing external backend-memory boundary; response path unchanged',
        exclusions=['posted cache merge/ACK','board','timing','Linux','full regression'])
    env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0',UBSAN_OPTIONS='halt_on_error=1')
    def save():(o/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(label,cmd,negative=None):
        assert inventory(root)==frozen and sha(driver)==receipt['driver_sha256'],'source drift'
        log=o/(label+'.log');start=time.monotonic()
        with log.open('x') as f:p=subprocess.run(list(map(str,cmd)),cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
        text=log.read_text(errors='replace')
        receipt['commands'].append(dict(label=label,command=list(map(str,cmd)),exit=p.returncode,
            seconds=round(time.monotonic()-start,3),log_sha256=sha(log)));save()
        assert p.returncode==(1 if negative else 0) and (not negative or negative in text),label+'\n'+text[-8000:]
        print(label,'PASS',flush=True);return text
    def completed(label):
        return previous and any(c['label']==label and c['exit']==0 for c in previous['commands'])
    def reuse(label,files):
        assert files and all(p.is_file() for p in files)
        receipt['reused_artifacts'].append(dict(label=label,files={str(p):sha(p) for p in files}));save()
        print(label,'REUSED_SOURCE_IDENTICAL',flush=True)
    save()
    try:
        d=(a.reuse_run if previous else o)/'model';top='ReadyStoreQuery77BackendGsim'
        if completed('emit'):reuse('emit',[d/(top+'.fir'),d/'actual-core.json'])
        else:run('emit',['mill','-i','-j','2','IonSoC.test.runMain','ooo.QueuedCancelBackendMain',d])
        if completed('generate'):reuse('generate',sorted(d.glob('*.cpp'))+sorted(d.glob('*.h')))
        else:run('generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(d),d/(top+'.fir')])
        flags=['clang++-19','-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-I'+str(d),'-I'+str(root/'simulator/gsim/ready_store_query77')]
        objects=[]
        for i,p in enumerate(sorted(d.glob(top+'[0-9]*.cpp'))):
            obj=p.with_suffix('.o')
            if completed('compile-'+str(i)):reuse('compile-'+str(i),[p,obj])
            else:run('compile-'+str(i),[*flags,'-c',p,'-o',obj])
            objects.append(obj)
        assert objects
        binary=d/'run';run('link',[*flags,driver,*objects,'-ldl','-o',binary])
        receipt['positive']=run('positive',[binary])
        run('retained-handle-negative',[binary,'--mutate-retained-handle'],negative='independent retained queued-handle oracle mismatch')
        receipt['actual_core']=json.loads((d/'actual-core.json').read_text())
        receipt['fir_sha256']=sha(d/(top+'.fir'))
        receipt['status']='PASS_REAL_FIFO_QUEUED_CANCEL_PHYSICAL_DRAIN';save()
    except BaseException as e:
        receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__':main()
