#!/usr/bin/env python3
"""Actual driver counter events, exact numeric MMIO oracle, and negative controls.
No kernel/RTL/board performance claim. Counter export is exercised from source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import test_posted_rx_driver as rx
import test_posted_tx_driver as tx

HERE=Path(__file__).resolve().parent
WRAPPERS=r'''
static unsigned mmio_reads,mmio_writes;
static u64 counted_read(void *base,unsigned off){++mmio_reads;return vg_read(base,off);}
static void counted_write(void *base,unsigned off,u64 value){++mmio_writes;vg_write(base,off,value);}
#define vg_read counted_read
#define vg_write counted_write
static void reset_measure(void){mmio_reads=mmio_writes=clock_reads=0;}
typedef long ssize_t;
struct device { int unused; };struct device_attribute { int unused; };
static struct net_device *dev_get_drvdata(struct device *d){(void)d;return &device;}
static int sysfs_emit(char *buf,const char *fmt,...){va_list ap;va_start(ap,fmt);int n=vsnprintf(buf,4096,fmt,ap);va_end(ap);return n;}
'''
CASES=r'''
int main(void){unsigned cases=0;
 start_tx(4,4,true);reset_measure();
 assert(!vg_napi_poll(&state.napi,0)&&state.poll_budget_zero==1&&state.tx_poll_no_owner==1&&!state.tx_poll_pending_no_completion&&!state.tx_reclaimed&&!state.tx_poll_wakes&&mmio_reads==1&&!mmio_writes&&!clock_reads);++cases;
 reset_measure();assert(!vg_napi_poll(&state.napi,8)&&state.poll_budget_zero==1&&state.tx_poll_no_owner==2&&!state.poll_rx_budget_exit&&!state.poll_rx_time_exit&&mmio_reads==2&&mmio_writes==1&&clock_reads==1);++cases;
 start_tx(4,4,true);struct sk_buff s=make_skb(64,true);reset_measure();assert(!vg_xmit(&s,&device)&&!state.tx_full_stops&&!mmio_reads&&mmio_writes==3&&!clock_reads);
 reset_measure();assert(!vg_napi_poll(&state.napi,0)&&state.tx_poll_pending_no_completion==1&&!state.tx_poll_no_owner&&!state.tx_reclaimed&&mmio_reads==1&&!mmio_writes&&!clock_reads);++cases;
 tx_complete(false);reset_measure();assert(!vg_napi_poll(&state.napi,0)&&state.tx_reclaimed==1&&!state.tx_poll_wakes&&mmio_reads==4&&mmio_writes==1&&!clock_reads);++cases;
 start_tx(4,4,true);for(unsigned i=0;i<4;++i){s=make_skb(64+i,true);assert(!vg_xmit(&s,&device)&&state.tx_full_stops==(i==3));}
 assert(device.queue_stopped);s=make_skb(64,false);assert(vg_xmit(&s,&device)==NETDEV_TX_BUSY&&state.tx_full_stops==1);++cases;
 for(unsigned i=0;i<4;++i)tx_complete(false);reset_measure();assert(!vg_napi_poll(&state.napi,0)&&state.tx_reclaimed==4&&state.tx_poll_wakes==1&&!device.queue_stopped&&mmio_reads==12&&mmio_writes==4&&!clock_reads);
 assert(!vg_napi_poll(&state.napi,0)&&state.tx_poll_wakes==1&&state.tx_poll_no_owner==1);++cases;
 start_tx(4,4,true);for(unsigned i=0;i<4;++i){s=make_skb(64+i,true);assert(!vg_xmit(&s,&device));}tx_complete(true);assert(!vg_napi_poll(&state.napi,0)&&state.tx_reclaimed==1&&state.tx_poll_wakes==1&&device.stats.tx_errors==1);++cases;
 start_tx(4,4,true);device.queue_stopped=true;for(unsigned i=0;i<4;++i){s=make_skb(64+i,true);assert(!vg_xmit(&s,&device));}assert(!state.tx_full_stops);s=make_skb(64,false);assert(vg_xmit(&s,&device)==NETDEV_TX_BUSY&&!state.tx_full_stops);++cases;
 start_tx(4,4,true);for(unsigned i=0;i<4;++i){s=make_skb(64+i,true);assert(!vg_xmit(&s,&device));tx_complete(false);}device.carrier=false;assert(!vg_napi_poll(&state.napi,0)&&state.tx_reclaimed==4&&!state.tx_poll_wakes&&device.queue_stopped);++cases;
 start_tx(4,4,true);s=make_skb(64,true);assert(!vg_xmit(&s,&device));tx_complete(false);tx_wrong_address=true;
 assert(!vg_napi_poll(&state.napi,0)&&state.faulted&&!state.tx_reclaimed&&!state.tx_poll_pending_no_completion&&!state.tx_poll_wakes&&!state.tx_full_stops);++cases;
 start_tx(4,4,true);tx_reset=true;assert(!vg_napi_poll(&state.napi,0)&&state.faulted&&state.tx_poll_no_owner==1&&!state.tx_poll_pending_no_completion&&!state.tx_poll_wakes);++cases;
 start_tx(4,4,true);assert(!vg_stop(&device));reset_measure();assert(!vg_napi_poll(&state.napi,0)&&state.poll_budget_zero==1&&!state.tx_poll_no_owner&&!state.tx_poll_pending_no_completion&&!state.tx_poll_wakes&&!state.tx_full_stops&&!mmio_reads&&!mmio_writes&&!clock_reads);++cases;
 for(unsigned limit=1;limit<=4;++limit){start_tx(4,4,true);for(unsigned i=0;i<limit;++i)complete_frame(64+i,false,true);time_step=2000000;
  /* budget one coincides with elapsed deadline; budget has priority. */
  reset_measure();assert(vg_napi_poll(&state.napi,limit)==(int)limit);
  assert(state.poll_rx_budget_exit==(limit==1)&&state.poll_rx_time_exit==(limit!=1)&&clock_reads==(limit==1?1:2));++cases;
 }
 start_tx(4,4,true);for(unsigned i=0;i<4;++i)complete_frame(64+i,false,true);reset_measure();assert(vg_napi_poll(&state.napi,4)==4&&state.poll_rx_budget_exit==1&&!state.poll_rx_time_exit&&mmio_reads==13&&mmio_writes==12&&clock_reads==4);++cases;
 start_tx(4,4,true);fail_alloc=true;complete_frame(64,false,false);assert(vg_napi_poll(&state.napi,8)==1&&state.rx_alloc_fail==1&&device.stats.rx_dropped==1);++cases;
 start_tx(4,4,true);complete_frame(3,false,false);assert(vg_napi_poll(&state.napi,8)==1&&!state.rx_alloc_fail&&device.stats.rx_errors==1);++cases;
 start_tx(4,4,true);stopped=true;assert(!vg_napi_poll(&state.napi,8)&&state.faulted&&!state.poll_rx_budget_exit&&!state.poll_rx_time_exit&&!state.rx_alloc_fail);++cases;
 start_tx(1,1,false);s=make_skb(64,true);assert(!vg_xmit(&s,&device)&&state.tx_full_stops==1);assert(!vg_napi_poll(&state.napi,0)&&state.tx_poll_pending_no_completion==1);tx_status=2;assert(!vg_napi_poll(&state.napi,0)&&state.tx_reclaimed==1&&state.tx_poll_wakes==1);++cases;
 /* Existing sysfs prefix survives; appended counters are read with no MMIO/clock. */
 char buf[4096];struct device dev;struct device_attribute attr;reset_measure();int n=napi_status_show(&dev,&attr,buf);
 assert(n>0&&n<4096&&!strncmp(buf,"irq=",4)&&strstr(buf,"tx_completion_peak=0 poll_budget_zero=2 poll_rx_budget_exit=0 poll_rx_time_exit=0 tx_reclaimed=1 tx_poll_no_owner=0 tx_poll_pending_no_completion=1 tx_full_stops=1 tx_poll_wakes=1 rx_alloc_fail=0\n"));
 const char *old_fields[]={"irq=","interrupts=","napi_polls=","rx_work=","empty_polls=","running=","configured=","faulted=","rx_mode=","rx_slots=","rx_dma_bytes=","posted_owned=","rx_max_batch=","rx_completion_peak=","mac_rx_slots=","dma_memory_credits=","tx_mode=","tx_slots=","tx_dma_bytes=","tx_owned=","tx_max_batch=","tx_completion_peak="};
 const char *cursor=buf;for(unsigned i=0;i<sizeof old_fields/sizeof old_fields[0];++i){const char *found=strstr(cursor,old_fields[i]);assert(found);cursor=found+strlen(old_fields[i]);}
 assert(!mmio_reads&&!mmio_writes&&!clock_reads);++cases;
 printf("NAPI_COUNTERS_DRIVER_PASS cases=%u exact_mmio=1 exclusive_exits=1 full_stop_transition=1 wake_stopped_only=1 fault_ifdown=1 sysfs_export=1\n",cases);return 0;
}
'''

def harness(source):
    stubs=rx.STUBS.replace('static u64 vg_read(', 'static u64 vg_read_rx(').replace('static void vg_write(', 'static void vg_write_rx(')
    stubs=stubs.replace('static void dma_free_coherent(', 'static void dma_free_coherent_rx(')
    stubs=stubs.replace('tx_errors; } stats;', 'tx_errors,tx_dropped; } stats;')
    stubs=stubs.replace('unsigned rx_slots,rx_hw_slots,tx_length,rx_max_batch;', 'unsigned rx_slots,rx_hw_slots,tx_length,rx_max_batch,mac_rx_slots,dma_credits;')
    names=('vg_queue_read','vg_queue_write','vg_queue_publish','vg_queue_consume','vg_queue_fault','vg_tx_space','vg_arm_rx','vg_configure','vg_irq','vg_napi_poll','vg_xmit','vg_open','vg_stop','napi_status_show')
    defs='\n'.join(x for x in source.splitlines() if re.match(r'#define (?:G_|D_|FRAME_BYTES)',x))
    prefix='static void *netdev_priv(struct net_device *d){assert(d==&device);return &state;}\n'
    return stubs+tx.EXTRA+WRAPPERS+defs+'\n'+prefix+'\n'.join(rx.function(source,n) for n in names)+tx.CASES.split('int main(int argc')[0]+CASES

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--cc',default='cc');a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    source=(HERE/'valence_gmac.c').read_text()
    variants={'candidate':source,
              'double_exit':source.replace('p->poll_rx_budget_exit++;','p->poll_rx_budget_exit++; p->poll_rx_time_exit++;'),
              'wake_attempts':source.replace('if (netif_queue_stopped(ndev)) p->tx_poll_wakes++;','p->tx_poll_wakes++;'),
              'fake_idle_pending':source.replace('p->tx_poll_no_owner++;','p->tx_poll_no_owner++; p->tx_poll_pending_no_completion++;'),
              'missing_full_stop':source.replace('if (!netif_queue_stopped(ndev)) p->tx_full_stops++;','(void)0;')}
    results={}
    for name,variant in variants.items():
        if name!='candidate':assert variant!=source
        c=a.out/(name+'.c');exe=a.out/name;c.write_text(harness(variant))
        subprocess.run([a.cc,'-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-Wno-unused-function','-I'+str(HERE),str(c),'-o',str(exe)],check=True)
        r=subprocess.run([exe],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=30)
        (a.out/(name+'.log')).write_text(r.stdout+r.stderr)
        if name=='candidate':assert r.returncode==0,r.stderr
        else:assert r.returncode!=0 and 'Assertion' in r.stderr,r.stderr
        results[name]={'exit_code':r.returncode,'stdout':r.stdout,'expected_failure':name!='candidate'}
    (a.out/'receipt.json').write_text(json.dumps({'driver_sha256':hashlib.sha256(source.encode()).hexdigest(),'results':results},indent=2)+'\n')
    print(results['candidate']['stdout'],end='');print('Independent counter negative controls: 4/4 rejected')

if __name__=='__main__':main()
