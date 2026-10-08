#!/usr/bin/env python3
"""Actual driver RX/NAPI/IRQ/config/ifdown bodies with independent numeric MMIO.

No kernel, RTL, or board execution claim. Kernel allocation/scheduling are stubs;
all queue ownership, register ordering, copies and policy calls are real source.
"""
import argparse, hashlib, json, re, shutil, subprocess, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent

def function(source,name):
    m=re.search(r'^static[^\n]*\b'+name+r'\(',source,re.M);assert m,name
    a=source.index('{',m.start());n=1;b=a+1
    while n:n+=(source[b]=='{')-(source[b]=='}');b+=1
    return source[m.start():b]

STUBS=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "valence_rx_queue.h"
#include "valence_tx_queue.h"
#include "valence_irq_policy.h"
#define BIT_ULL(n) (1ULL<<(n))
#define READ_ONCE(x) (x)
#define container_of(ptr,type,member) ((type *)((char *)(ptr)-offsetof(type,member)))
#define ETH_HLEN 14
#define CHECKSUM_NONE 0
#define IRQ_HANDLED 1
typedef uint64_t u64;
typedef int irqreturn_t;
typedef uint64_t dma_addr_t;
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
struct napi_struct { bool enabled; };
struct sk_buff { unsigned len,protocol,ip_summed; unsigned char data[2048]; };
struct net_device { bool carrier; void *phydev; struct { unsigned rx_packets,rx_bytes,rx_errors,rx_dropped,tx_packets,tx_bytes,tx_errors; } stats; };
struct vg_rx_buffer { void *data; dma_addr_t address; };
struct vgmac {
 struct net_device *ndev; void *mac,*dma; struct delayed_work configure;struct napi_struct napi;
 int lock,irq;void *tx_buffer,*rx_buffer;struct vg_rx_buffer *rx_pool,*tx_pool;struct vgq_ring rx_ring;struct vgt_ring tx_ring;
 unsigned tx_slots,tx_hw_slots,tx_max_batch;bool posted_tx;
 unsigned rx_slots,rx_hw_slots,tx_length,rx_max_batch;bool posted_rx,ever_armed;dma_addr_t tx_address,rx_address;u64 hw_address;
 u64 interrupts,napi_polls,rx_work,empty_polls;bool running,address_set,configured,tx_pending,faulted;
};
static struct vgmac state;static struct net_device device;static int mac_base,dma_base;
static unsigned char buffers[16][2048];
static unsigned depth,head,tail,count,completed,ids[16],lengths[16];static bool errors[16],owned[16];
static bool enabled,stopped,reset_status,wrong_address,wrong_order,fail_alloc,inject_on_unmask;
static u64 stage_address,stage_capacity,irq_enable,legacy_status,legacy_length,tx_status;
static unsigned posts,pops,capacity_writes,publish_fences,consume_fences,completes,schedules,wakes,stops,freed,metadata_freed;
static unsigned retries,phy_stops,phy_starts,expected_head,expected_tail,delivered,generation;
static u64 time_now,time_step,mac_stop,mac_control,mac_cap;
static struct { unsigned n;unsigned char bytes[2048]; } expected[256];
static void vg_configure(struct work_struct *work);
static int vg_napi_poll(struct napi_struct *napi,int budget);
static void spin_lock_bh(int *p){assert(!*p);*p=1;}
static void spin_unlock_bh(int *p){assert(*p);*p=0;}
static void netif_stop_queue(struct net_device *d){(void)d;++stops;}
static void netif_wake_queue(struct net_device *d){(void)d;++wakes;}
static bool netif_carrier_ok(struct net_device *d){return d->carrier;}
static void netif_carrier_off(struct net_device *d){d->carrier=false;}
static void netif_start_queue(struct net_device *d){(void)d;}
static void netdev_err(struct net_device *d,const char *fmt,...){(void)d;(void)fmt;}
static void dev_warn(void *d,const char *fmt,...){(void)d;(void)fmt;}
static void dma_wmb(void){++publish_fences;}
static void dma_rmb(void){++consume_fences;}
static u64 ktime_get_ns(void){u64 result=time_now;time_now+=time_step;return result;}
static struct delayed_work *to_delayed_work(struct work_struct *w){return container_of(w,struct delayed_work,work);}
static unsigned msecs_to_jiffies(unsigned n){return n;}
static void schedule_delayed_work(struct delayed_work *w,unsigned n){(void)w;assert(n==0||n==100);++retries;}
static void cancel_delayed_work_sync(struct delayed_work *w){(void)w;}
static void synchronize_irq(int n){(void)n;}
static void napi_schedule(struct napi_struct *n){(void)n;++schedules;}
static void napi_schedule_irqoff(struct napi_struct *n){(void)n;++schedules;}
static bool napi_complete_done(struct napi_struct *n,unsigned work){assert(n->enabled);(void)work;++completes;return true;}
static void napi_enable(struct napi_struct *n){n->enabled=true;}
static void napi_disable(struct napi_struct *n){n->enabled=false;}
static void phy_stop(void *p){(void)p;++phy_stops;}
static void phy_start(void *p){(void)p;++phy_starts;}
static int vg_delays(struct net_device *d){(void)d;return 0;}
static struct sk_buff *napi_alloc_skb(struct napi_struct *n,unsigned bytes){assert(n->enabled&&bytes<=2048);return fail_alloc?NULL:calloc(1,sizeof(struct sk_buff));}
static void *skb_put(struct sk_buff *s,unsigned n){assert(s->len+n<=2048);void *p=s->data+s->len;s->len+=n;return p;}
static unsigned eth_type_trans(struct sk_buff *s,struct net_device *d){(void)s;(void)d;return 0x800;}
static void napi_gro_receive(struct napi_struct *n,struct sk_buff *s){
 assert(n->enabled&&expected_head<expected_tail);assert(s->len==expected[expected_head].n);
 assert(!memcmp(s->data,expected[expected_head].bytes,s->len));++expected_head;++delivered;free(s);
}
static void dma_free_coherent(void *d,unsigned n,void *p,dma_addr_t a){
 (void)d;(void)p;assert(n==2048);for(unsigned i=0;i<state.rx_slots;++i)if(a==state.rx_pool[i].address)assert(!owned[i]);++freed;
}
static void kfree(void *p){free(p);++metadata_freed;}
static bool irq_level(void){return ((irq_enable&2)&&completed)||((irq_enable&1)&&(tx_status&2));}
static void complete_frame(unsigned bytes,bool bad,bool deliver){
 assert(completed<count);unsigned slot=ids[(head+completed)%depth];lengths[slot]=bytes;errors[slot]=bad;
 for(unsigned b=0;b<2048;++b)buffers[slot][b]=(unsigned char)(generation*71+slot*13+b);++generation;
 if(deliver){assert(bytes>=14&&bytes<=2048&&expected_tail<256);expected[expected_tail].n=bytes;memcpy(expected[expected_tail++].bytes,buffers[slot],bytes);}++completed;
}
static u64 vg_read(void *base,unsigned off){
 assert(off<256&&!(off&7));
 if(base==&mac_base){switch(off){case 8:return mac_cap;case 0x28:return 0;case 0x90:return mac_stop;case 0x10:return mac_control;default:return 0;}}
 switch(off){
 case 0x28:return tx_status;case 0x48:return legacy_status;case 0x50:return legacy_length;
 case 0xb8:return enabled;case 0xc0:{if(reset_status)return 0;unsigned active=count>completed;return (count-completed-active)|((u64)completed<<8)|((u64)active<<16)|((u64)stopped<<17);}
 case 0xc8:assert(completed);return wrong_address?0xdeadbeef:state.rx_pool[ids[(head+(wrong_order?1:0))%depth]].address;
 case 0xd0:{assert(completed);unsigned i=ids[head];return lengths[i]|((u64)errors[i]<<16);}default:return 0;
 }
}
static void vg_write(void *base,unsigned off,u64 value){
 assert(off<256&&!(off&7));
 if(base==&mac_base){if(off==0x90){assert(mac_cap&(1ULL<<8));assert((enabled&&count)||legacy_status&1);mac_stop=value;}
  if(off==0x10){assert((enabled&&count)||legacy_status&1);mac_control=value;}return;}
 switch(off){
 case 8:irq_enable=value;if(value&&inject_on_unmask){inject_on_unmask=false;complete_frame(65,false,true);}break;
 case 0x20:assert(value==2);tx_status=0;break;
 case 0x40:assert(!(legacy_status&1));if(value==2)legacy_status=0;else {assert(value==3&&!enabled&&publish_fences);legacy_status=1;}break;
 case 0xa0:stage_address=value;break;
 case 0xa8:stage_capacity=value;++capacity_writes;break;
 case 0xb8:assert(value<=1&&!count);enabled=value;stopped=false;break;
 case 0xb0:{assert(value==1&&enabled&&!stopped&&count<depth&&stage_capacity==2048&&publish_fences>posts);
  unsigned slot=16;for(unsigned i=0;i<state.rx_slots;++i)if(state.rx_pool[i].address==stage_address)slot=i;
  assert(slot<16&&!owned[slot]);owned[slot]=true;ids[tail]=slot;tail=(tail+1)%depth;++count;++posts;break;}
 case 0xd8:{assert(value==1&&completed&&consume_fences);unsigned slot=ids[head];assert(owned[slot]);
  owned[slot]=false;memset(buffers[slot],0xee,2048);head=(head+1)%depth;--count;--completed;++pops;break;}
 default:assert(!"unexpected DMA write");
 }
}
static void reset_case(unsigned slots,unsigned hardware){
 if(state.rx_pool)free(state.rx_pool);if(state.tx_pool)free(state.tx_pool);memset(&state,0,sizeof state);memset(&device,0,sizeof device);memset(owned,0,sizeof owned);
 state.ndev=&device;state.mac=&mac_base;state.dma=&dma_base;state.running=true;state.address_set=true;state.posted_rx=true;state.rx_slots=slots;state.rx_hw_slots=hardware;state.napi.enabled=true;
 state.rx_pool=calloc(slots,sizeof(*state.rx_pool));assert(state.rx_pool);for(unsigned i=0;i<slots;++i){state.rx_pool[i].address=0x80200000ULL+i*4096;state.rx_pool[i].data=buffers[i];}
 state.rx_buffer=buffers[0];state.rx_address=state.rx_pool[0].address;state.tx_buffer=(void *)1;state.tx_address=0x80220000;state.tx_slots=1;state.tx_pool=calloc(1,sizeof(*state.tx_pool));assert(state.tx_pool);state.tx_pool[0].data=state.tx_buffer;state.tx_pool[0].address=state.tx_address;device.carrier=true;
 depth=hardware;head=tail=count=completed=0;enabled=stopped=reset_status=wrong_address=wrong_order=fail_alloc=inject_on_unmask=false;
 posts=pops=capacity_writes=publish_fences=consume_fences=completes=schedules=wakes=stops=freed=metadata_freed=retries=phy_stops=phy_starts=expected_head=expected_tail=delivered=generation=0;
 time_now=time_step=irq_enable=legacy_status=legacy_length=tx_status=0;mac_stop=3;mac_control=0;mac_cap=1ULL<<8;
}
'''

CASES=r'''
static void start(unsigned slots,unsigned hardware){
 reset_case(slots,hardware);vgq_u64 address[16];for(unsigned i=0;i<slots;++i)address[i]=state.rx_pool[i].address;
 struct vgq_ops ops={&state,vg_queue_read,vg_queue_write,vg_queue_publish,vg_queue_consume};
 assert(!vgq_init(&state.rx_ring,ops,slots,2048,address));vg_configure(&state.configure.work);
 assert(state.configured&&state.ever_armed&&count==slots&&posts==slots&&capacity_writes==1&&enabled&&mac_stop==0&&mac_control==15);
}
int main(void){unsigned cases=0;
 const struct { u64 cap;unsigned slots; } caps[]={{0,0},{1,0},{2,0},{3,0},
  {0x103,1},{0x203,2},{0x303,0},{0x403,4},{0x803,8},{0x1003,16},
  {0x2003,0},{0xff03,0},{0x402,0},{0x401,0},{0x100403,4}};
 for(unsigned i=0;i<sizeof caps/sizeof caps[0];++i){assert(vgq_cap_slots(caps[i].cap)==caps[i].slots);++cases;}

 for(unsigned slots=1;slots<=16;slots*=2){
  start(slots,slots);for(unsigned i=0;i<slots;++i)complete_frame(63+i,false,true);
  assert(vg_napi_poll(&state.napi,slots)==(int)slots&&delivered==slots&&pops==slots&&posts==2*slots&&count==slots&&capacity_writes==1);
  assert(vg_napi_poll(&state.napi,8)==0&&irq_enable==3&&completes==1);++cases;
 }
 start(3,4);for(unsigned i=0;i<3;++i)complete_frame(67+i,false,true);assert(vg_napi_poll(&state.napi,8)==3&&delivered==3);++cases;
 start(4,4);for(unsigned i=0;i<4;++i)complete_frame(64,false,true);assert(vg_napi_poll(&state.napi,2)==2&&completed==2&&!completes&&!irq_enable);assert(vg_napi_poll(&state.napi,8)==2&&completed==0&&completes==1);++cases;
 start(4,4);complete_frame(64,false,true);complete_frame(65,false,true);time_step=2100000;assert(vg_napi_poll(&state.napi,8)==8&&delivered==1&&completed==1&&!completes);time_step=0;time_now=0;assert(vg_napi_poll(&state.napi,8)==1);++cases;
 start(4,4);complete_frame(64,false,true);state.tx_pending=true;state.tx_length=123;tx_status=2;assert(vg_napi_poll(&state.napi,0)==0&&!state.tx_pending&&device.stats.tx_packets==1&&completed==1&&!completes);assert(vg_napi_poll(&state.napi,8)==1);++cases;
 start(4,4);fail_alloc=true;complete_frame(64,false,false);assert(vg_napi_poll(&state.napi,8)==1&&device.stats.rx_dropped==1&&count==4);++cases;
 for(unsigned kind=0;kind<3;++kind){start(4,4);complete_frame(kind==0?3:kind==1?2049:64,kind==2,false);assert(vg_napi_poll(&state.napi,8)==1&&device.stats.rx_errors==1&&!delivered&&count==4);++cases;}
 for(unsigned fault=0;fault<4;++fault){start(4,4);complete_frame(64,false,false);wrong_address=fault==0;wrong_order=fault==1;stopped=fault==2;reset_status=fault==3;assert(vg_napi_poll(&state.napi,8)==0&&state.faulted&&!pops&&state.rx_ring.owned==15&&!irq_enable);++cases;}
 start(4,4);assert(vgq_post(&state.rx_ring,0)<0&&!pops&&posts==4);assert(vgq_release(&state.rx_ring,0,true)<0);complete_frame(64,false,false);struct vgq_completion c;assert(vgq_peek(&state.rx_ring,&c)==1);assert(vgq_release(&state.rx_ring,1,true)<0&&!pops);++cases;
 start(4,4);complete_frame(64,false,true);irq_enable=3;assert(irq_level());assert(vg_irq(1,&device)==IRQ_HANDLED&&!irq_enable&&schedules==2);inject_on_unmask=true;assert(vg_napi_poll(&state.napi,8)==1&&irq_level()&&completed==1);assert(vg_irq(1,&device)==IRQ_HANDLED);assert(vg_napi_poll(&state.napi,8)==1&&delivered==2);++cases;
 start(4,4);complete_frame(64,false,true);irq_enable=3;assert(irq_level());/* Deliberately omit delivery of the interrupt. */assert(vg_napi_poll(&state.napi,8)==1&&delivered==1);++cases;
 start(4,4);complete_frame(64,false,true);assert(!vg_stop(&device)&&!state.running&&!state.napi.enabled&&state.rx_ring.owned==15&&count==4&&!freed);unsigned old_posts=posts,old_schedules=schedules;assert(vg_irq(1,&device)==IRQ_HANDLED&&schedules==old_schedules);assert(!vg_open(&device));device.carrier=true;vg_configure(&state.configure.work);assert(posts==old_posts&&state.rx_ring.owned==15);assert(vg_napi_poll(&state.napi,8)==1&&count==4);++cases;
 reset_case(1,1);state.posted_rx=false;vg_configure(&state.configure.work);assert(legacy_status==1&&mac_stop==0&&state.ever_armed);++cases;
 reset_case(1,1);state.posted_rx=false;mac_cap=0;vg_configure(&state.configure.work);assert(legacy_status==1&&mac_stop==3);++cases;
 reset_case(4,4);cleanup_buffers(&state);assert(freed==5&&metadata_freed==2);++cases;
 start(4,4);cleanup_buffers(&state);assert(!freed&&metadata_freed==2&&count==4);++cases;
 puts("POSTED_RX_DRIVER_MMIO_PASS ownership=1 copy_before_pop=1 fifo=1 budget=1 irq_rearm=1 dropped_irq=1 full_queue=1 reset_stop_fault=1 ifdown_pinned=1 legacy=1");printf("cases=%u\n",cases);return 0;
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cc',default='cc');ap.add_argument('--out',type=Path);args=ap.parse_args()
    source=(HERE/'valence_gmac.c').read_text();defs='\n'.join(x for x in source.splitlines() if re.match(r'#define (?:G_|D_|FRAME_BYTES)',x))
    names=('vg_queue_read','vg_queue_write','vg_queue_publish','vg_queue_consume','vg_queue_fault','vg_tx_space','vg_arm_rx','vg_configure','vg_irq','vg_napi_poll','vg_open','vg_stop')
    funcs='\n'.join(function(source,n) for n in names)
    # IRQ source uses netdev_priv; return exactly the one test device's private state.
    prefix='static void *netdev_priv(struct net_device *d){assert(d==&device);return &state;}\n'
    a=source.index('free_buffers:')+len('free_buffers:');b=source.index('free_net:',a)
    cleanup='static void cleanup_buffers(struct vgmac *p){void *dev=NULL;unsigned int i;'+source[a:b]+'p->rx_pool=NULL;p->tx_pool=NULL;}\n'
    c=STUBS+'\n'+defs+'\n'+prefix+funcs+'\n'+cleanup+CASES
    with tempfile.TemporaryDirectory(prefix='vgmac-posted-') as td:
        p=Path(td);(p/'test.c').write_text(c)
        command=[args.cc,'-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-I'+str(HERE),str(p/'test.c'),'-o',str(p/'run')]
        subprocess.run(command,check=True);r=subprocess.run([p/'run'],capture_output=True,text=True,env={**__import__('os').environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=30)
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        print(r.stdout,end='')
        if args.out:
            args.out.mkdir(parents=True,exist_ok=False);(args.out/'harness.c').write_text(c);(args.out/'test.log').write_text(r.stdout+r.stderr)
            (args.out/'receipt.json').write_text(json.dumps({'status':'passed','scope':__doc__,'driver_sha256':hashlib.sha256(source.encode()).hexdigest(),'queue_header_sha256':hashlib.sha256((HERE/'valence_rx_queue.h').read_bytes()).hexdigest(),'compiler':args.cc,'summary':r.stdout},indent=2)+'\n')
if __name__=='__main__':main()
