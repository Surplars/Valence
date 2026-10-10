#!/usr/bin/env python3
"""Existing short RV64GC image against each NEW exact Board model; no historical FP pass."""
import argparse
from contract import *
from model import execute
def verify_model(path,digest):
 directory=BASE/'posted-preparation-priority-cpu-object-r1';require(sha(directory/'VERIFIER-PINS.json')=='65931c61ae4032058c4d234555349985dd5bcb40274adcd205fbd964f0a97842','object verifier pins changed');require(sha(directory/'verify_model.py')==read(directory/'VERIFIER-PINS.json')['verify_model.py'],'object dispatch changed')
 q=subprocess.run([sys.executable,'-B',str(BASE/'posted-preparation-priority-cpu-object-r1/verify_model.py'),'--receipt',str(path),'--sha256',digest],cwd=BASE,capture_output=True,text=True)
 require(q.returncode==0,'isolated object verifier failed: '+q.stderr[-2000:]);return json.loads(q.stdout)

def plan(folder,image,side):
 ts=tools()['files'];f=ROOT/'fpga/firmware';h=ROOT/'simulator/gsim/harness'
 return [
  [ts['riscv_gcc']['path'],'-march=rv64gc','-mabi=lp64d','-mcmodel=medany','-mno-relax','-nostdlib','-nostartfiles','-Wl,--no-relax','-Wl,--build-id=none','-Wl,--defsym=BOARD_RAM_BYTES=2147483648','-Wl,--defsym=BOARD_MONITOR_BASE=4294934528','-T',str(f/'sample_app.ld'),str(f/'rv64gc_smoke.S'),'-o',str(image.with_suffix('.elf'))],
  [str(Path(ts['riscv_gcc']['path']).with_name('riscv64-unknown-elf-objcopy')),'-O','binary',str(image.with_suffix('.elf')),str(image)],
  [ts['clang']['path'],*FLAGS,*DEFINES,*geometry(side),'-I'+str(folder),str(h/'rv64gc_board.cpp'),'-I'+str(h),str(folder/'BoardSocGsim0.o'),'-ldl','-o',str(image.parent/'smoke')],
  [str(image.parent/'smoke'),str(image)],
  [str(image.parent/'smoke'),str(image),'--inject-mismatch']]

def run(model,digest,out,slot):
 require(slot,'coordinator heavy slot required');m=verify_model(model,digest);out=Path(out).resolve();require(not out.exists(),'fresh smoke namespace');out.mkdir()
 image=out/'rv64gc.bin';cmds=plan(Path(model).resolve().parent,image,m['side']);objcopy=Path(cmds[1][0]);require(objcopy.is_file(),'pinned toolchain objcopy unavailable')
 before=source();r=dict(schema='posted-preparation-priority-rv64gc-smoke-v1',runner_path=str(Path(__file__).resolve()),runner_sha256=sha(__file__),status='RUNNING',model_receipt=str(Path(model).resolve()),model_sha256=digest,side=m['side'],performance_qualification=False,focused_gate_not_required_for_short_smoke=True,source=before,objcopy_sha256=sha(objcopy),steps=[],existing_guest_source_unchanged=True,historical_runtime_inherited=False)
 try:
  for i,cmd in enumerate(cmds):
   expected=1 if i==4 else 0;r['steps'].append(execute(cmd,out/f'step{i}.log',300,cwd=HERE,expected=expected));save(out/'receipt.json',r)
  require((out/'rv64gc.bin').stat().st_size<16384,'existing short GC image bound')
  require('RV64GC_BOARD_PASS'in(out/'step3.log').read_text(),'missing fresh RV64GC positive anchor')
  require('firmware independent anchor/context failure'in(out/'step4.log').read_text(),'misa mutation failed for wrong reason')
  require(exact(before,source())and sha(objcopy)==r['objcopy_sha256']and sha(__file__)==r['runner_sha256'],'smoke inputs changed');verify_model(model,digest)
  r['status']='PASS_FRESH_PROFILE_RV64GC_SHORT_WITH_REAL_NEGATIVE'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:r['artifacts']={p.name:sha(p)for p in out.iterdir()if p.is_file()and p.name!='receipt.json'};save(out/'receipt.json',r)
 return dict(status=r['status'],path=str(out/'receipt.json'),sha256=sha(out/'receipt.json'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--slot-granted',action='store_true');a=p.parse_args();print(json.dumps(run(a.model,a.sha256,a.out,a.slot_granted),indent=2))
if __name__=='__main__':main()
