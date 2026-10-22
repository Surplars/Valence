#!/usr/bin/env python3
"""Actual platform/CMU/epoch with production SV backend and test-only MMCM primitives.
Not vendor primitive, STA, board, or production software-frequency qualification.
"""
import argparse, hashlib, json, os, re, signal, subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--rtl', type=Path, required=True)
p.add_argument('--emission', type=Path, required=True)
p.add_argument('--guest', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--tb', type=Path, required=True)
a=p.parse_args(); a.out=a.out.resolve(); a.out.mkdir(parents=True,exist_ok=False)
sha=lambda x: hashlib.sha256(Path(x).read_bytes()).hexdigest()
native=ROOT.parent/'native-tools'; iv=native/'bin/iverilog'; vvp=native/'root/usr/bin/vvp'
rtl=sorted(a.rtl.resolve().glob('*.sv')); backend=ROOT/'fpga/common/dynamic'
back=[backend/(n+'.sv')for n in ['behavioral_primitives','native_clock_gate','native_clock_drp','native_dynamic_clock_domain']]
phy=ROOT/'simulator/cdc/rtl8211f_pin_model.sv'
source_paths=sorted((ROOT/'src/main/scala').rglob('*.scala'))+sorted((ROOT/'src/main/resources').rglob('*.sv'))+sorted((ROOT/'src/test/scala').rglob('*.scala'))+[ROOT/'build.mill']
emission=json.loads(a.emission.read_text())
assert emission['status']=='PASS_EMIT_ONLY' and emission['returncode']==0
assert all(sha(f)==emission['source_sha256'][str(f.relative_to(ROOT))]for f in source_paths)
assert {f.name:sha(f)for f in rtl}==emission['rtl_sha256']
extra=back+[phy,a.tb.resolve(),Path(__file__).resolve(),ROOT/'simulator/gsim/common/dynamic_roundtrip.S',ROOT/'simulator/gsim/common/i1_runtime_network.ld']
frozen={str(f):sha(f)for f in source_paths+extra+rtl+list(a.guest.resolve().iterdir())if f.is_file()}
record=dict(status='RUNNING',scope=__doc__,head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    emission=dict(path=str(a.emission.resolve()),sha256=sha(a.emission)),source_and_rtl_sha256=frozen,
    cases=[],tools={},test_only_allowed_hz=[50000000,100000000],production_allowed_points=[],
    phy_policy_wait_cycles=[256,512],fixed_mdio_source_hz=125000000,physical_qualified=False,
    native_case_wall_seconds=300,wall_scope='Root-approved r24 first normal loop and necessary narrow reruns; no DUT/guest/protocol timeout change')
active=None
def terminate(signum,frame):
    global active
    if active is not None and active.poll() is None:
        os.killpg(active.pid,signal.SIGKILL);active.wait()
    raise KeyboardInterrupt(str(signum))
signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGINT,terminate)
def run(name,cmd,limit):
    global active
    start=time.monotonic();timed=False;log=a.out/(name+'.log')
    with log.open('wb')as f:
        active=subprocess.Popen([str(c)for c in cmd],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        try: active.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            timed=True;os.killpg(active.pid,signal.SIGKILL);active.wait()
    r=dict(name=name,command=[str(c)for c in cmd],exit=active.returncode,seconds=time.monotonic()-start,
           timeout=timed,reaped=active.poll()is not None,log=log.name,log_sha256=sha(log))
    record['cases'].append(r);active=None
    (a.out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    if timed or r['exit']!=0:raise RuntimeError(name+' failed: '+log.read_text()[-3500:])
    return log.read_text()
def check():
    assert all(sha(f)==h for f,h in frozen.items()),'Source, guest or emitted RTL drift'
    assert all(sha(f)==h for f,h in record['tools'].items()),'Tool drift'
try:
    for tool in [iv,native/'root/usr/bin/iverilog',vvp,native/'root/usr/lib/x86_64-linux-gnu/ivl/ivl',native/'root/usr/lib/x86_64-linux-gnu/ivl/ivlpp',native/'root/usr/lib/x86_64-linux-gnu/ivl/vvp.tgt']:record['tools'][str(tool)]=sha(tool)
    run('iverilog-version',[iv,'-V'],30);run('vvp-version',[vvp,'-V'],30)
    definitions=['-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1']
    pre=a.out/'preprocessed.sv';run('preprocess',[iv,*definitions,'-E','-o',pre,*rtl],180)
    pretext=pre.read_text();assert '$fatal' in pretext and 'rate receipt preceded local response or lost its owner' in pretext
    record['production_assertion_sites']=pretext.count('$fatal');record['preprocessed_sha256']=sha(pre)
    binary=a.out/'roundtrip.vvp'
    run('compile',[iv,*definitions,'-s','dynamic_roundtrip_tb','-o',binary,*rtl,*back,phy,a.tb.resolve()],180)
    record['binary_sha256']=sha(binary)
    symbols={parts[2]:int(parts[0],16)for line in (a.guest/'guest-symbols.log').read_text().splitlines()if len(parts:=line.split())==3}
    # The exact emitted readmemh targets must be these frozen banks, not an unbound replacement.
    for i in range(2):assert str((a.guest/f'bank{i}.hex').resolve())in '\n'.join(f.read_text()for f in rtl)
    text=run('normal',[vvp,'-i',binary,f'+done_pc={symbols["guest_done"]:x}',f'+fail_pc={symbols["guest_fail"]:x}'],300)
    assert 'ROUNDTRIP_PASS'in text,'Missing ordinary completion oracle'
    assert sha(binary)==record['binary_sha256'];check()
    record['status']='PASS_NORMAL_BEHAVIORAL_PLATFORM_ONLY'
except BaseException as exc:
    record.update(status='FAIL',error=repr(exc));raise
finally:
    record['logs_sha256']={f.name:sha(f)for f in a.out.glob('*.log')}
    (a.out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],a.out,flush=True)
