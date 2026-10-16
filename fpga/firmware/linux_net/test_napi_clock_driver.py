#!/usr/bin/env python3
"""Actual NAPI driver body: clock counts and deadline boundaries, with mutations.
Host fake MMIO only; no kernel timing or board throughput claim.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import test_posted_rx_driver as rx

HERE = Path(__file__).resolve().parent
CASES = r'''
int main(void) {
 unsigned cases=0;
 start(4,4);complete_frame(64,false,true);state.tx_pending=true;state.tx_length=123;tx_status=2;
 assert(vg_napi_poll(&state.napi,0)==0&&clock_reads==0&&completed==1&&!completes&&!irq_enable&&device.stats.tx_packets==1);++cases;
 for(unsigned budget=1;budget<=4;++budget){
  start(4,4);for(unsigned i=0;i<budget;++i)complete_frame(64+i,false,true);
  assert(vg_napi_poll(&state.napi,budget)==(int)budget&&clock_reads==budget&&delivered==budget&&!completes&&!irq_enable);++cases;
 }
 start(4,4);assert(vg_napi_poll(&state.napi,8)==0&&clock_reads==1&&completes==1&&irq_enable==3);++cases;
 /* Below, exactly at, and above the 2ms deadline; retained work is not lost. */
 for(unsigned delta=1999999;delta<=2000001;++delta){
  start(4,4);complete_frame(64,false,true);complete_frame(65,false,true);time_step=delta;
  assert(vg_napi_poll(&state.napi,8)==8&&!completes&&!irq_enable);
  assert(delivered==(delta<2000000?2:1)&&clock_reads==(delta<2000000?3:2));++cases;
 }
 start(4,4);complete_frame(64,false,true);time_step=1999999;
 assert(vg_napi_poll(&state.napi,8)==1&&clock_reads==2&&completes==1&&irq_enable==3);++cases;
 start(4,4);stopped=true;assert(vg_napi_poll(&state.napi,8)==0&&state.faulted&&!pops&&!irq_enable&&clock_reads==1);++cases;
 start(4,4);assert(!vg_stop(&device));assert(vg_napi_poll(&state.napi,0)==0&&!clock_reads&&!irq_enable&&!completes&&count==4);++cases;
 start(4,4);complete_frame(64,false,true);inject_on_unmask=true;
 assert(vg_napi_poll(&state.napi,8)==1&&completed==1&&irq_enable==3&&clock_reads==2);
 assert(vg_irq(1,&device)==IRQ_HANDLED&&!irq_enable);assert(vg_napi_poll(&state.napi,8)==1&&delivered==2);++cases;
 printf("NAPI_CLOCK_DRIVER_PASS cases=%u budget0=1 exact_budget=1 deadline_boundary=1 empty_rx=1 tx_only=1 fault=1 ifdown=1 irq_rearm=1\n",cases);
 return 0;
}
'''

def harness(source):
    names = ('vg_queue_read','vg_queue_write','vg_queue_publish','vg_queue_consume',
             'vg_queue_fault','vg_tx_space','vg_arm_rx','vg_configure','vg_irq',
             'vg_napi_poll','vg_open','vg_stop')
    defs = '\n'.join(x for x in source.splitlines() if re.match(r'#define (?:G_|D_|FRAME_BYTES)', x))
    prefix = 'static void *netdev_priv(struct net_device *d){assert(d==&device);return &state;}\n'
    return rx.STUBS + defs + '\n' + prefix + '\n'.join(rx.function(source,n) for n in names) + rx.CASES.split('int main(void)')[0] + CASES

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--cc',default='cc')
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    source=(HERE/'valence_gmac.c').read_text()
    variants={'candidate':source,
              'budget0_clock':source.replace('budget ? ktime_get_ns() + VG_NAPI_TIME_NS : 0','ktime_get_ns() + VG_NAPI_TIME_NS'),
              'full_budget_clock':source.replace('if (work >= budget) {', 'if ((void)ktime_get_ns(), work >= budget) {'),
              'missing_deadline':source.replace('vgq_poll_yield(work, budget, ktime_get_ns(), deadline)','vgq_poll_yield(work, budget, ktime_get_ns(), deadline + 1000000000ULL)')}
    results={}
    for name,variant in variants.items():
        if name!='candidate':assert variant!=source
        c=a.out/(name+'.c');exe=a.out/name;c.write_text(harness(variant))
        subprocess.run([a.cc,'-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                        '-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-Wno-unused-function',
                        '-I'+str(HERE),str(c),'-o',str(exe)],check=True)
        r=subprocess.run([exe],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=30)
        (a.out/(name+'.log')).write_text(r.stdout+r.stderr)
        if name=='candidate':assert r.returncode==0,r.stderr
        else:assert r.returncode!=0 and 'Assertion' in r.stderr,r.stderr
        results[name]={'exit_code':r.returncode,'stdout':r.stdout,'expected_failure':name!='candidate'}
    (a.out/'receipt.json').write_text(json.dumps(results,indent=2)+'\n')
    print(results['candidate']['stdout'],end='');print('Independent negative controls: 3/3 rejected')

if __name__=='__main__':main()
