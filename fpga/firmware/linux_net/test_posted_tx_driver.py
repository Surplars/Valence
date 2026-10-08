#!/usr/bin/env python3
"""Actual TX/RX/NAPI/IRQ driver bodies with independent numeric TX MMIO oracle.
No kernel build, scheduler, hardware, board throughput, or permanent lost-IRQ recovery claim.
"""
import argparse,hashlib,json,os,re,subprocess,tempfile
from pathlib import Path
import test_posted_rx_driver as rx
HERE=Path(__file__).resolve().parent

EXTRA=r'''
typedef int netdev_tx_t;
#define NETDEV_TX_OK 0
#define NETDEV_TX_BUSY 1
static unsigned skb_freed,tx_posts,tx_pops,tx_count,tx_completed,tx_depth,tx_head,tx_tail,tx_ids[16],tx_sizes[16];
static bool tx_owned[16],tx_bad[16],tx_enabled,tx_stopped,tx_reset,tx_wrong_address,tx_wrong_order,tx_wrong_length;
static bool copy_fail,negative_payload,tx_inject_on_unmask;
static unsigned char tx_buffers[16][2048],tx_snapshot[16][2048];
static u64 tx_stage_address,tx_stage_length,tx_last_fence;
static unsigned tx_expected_head,tx_expected_tail,tx_legacy_starts;
static struct { unsigned n;unsigned char bytes[2048]; } tx_expected[256];
static void tx_compare(unsigned slot,unsigned n){
 if(negative_payload)tx_buffers[slot][0]^=1;
 if(tx_expected_head>=tx_expected_tail||n!=tx_expected[tx_expected_head].n||memcmp(tx_buffers[slot],tx_expected[tx_expected_head].bytes,n)){
  fputs("TX independent payload mismatch\n",stderr);abort();
 }
 ++tx_expected_head;
}
static void tx_complete(bool bad){
 assert(tx_completed<tx_count);unsigned slot=tx_ids[(tx_head+tx_completed)%tx_depth];
 assert(tx_owned[slot]);if(memcmp(tx_buffers[slot],tx_snapshot[slot],tx_sizes[slot])){fputs("owned TX buffer changed before completion\n",stderr);abort();}
 tx_bad[slot]=bad;++tx_completed;
}
static int skb_copy_bits(struct sk_buff *s,unsigned start,void *p,unsigned n){assert(!start&&n==s->len);if(copy_fail)return -1;memcpy(p,s->data,n);return 0;}
static void dev_kfree_skb_any(struct sk_buff *s){(void)s;++skb_freed;}
static void netif_trans_update(struct net_device *d){(void)d;}
static u64 vg_read(void *base,unsigned off){
 if(base!=&dma_base||off<0xe0)return vg_read_rx(base,off);
 switch(off){
 case 0xe0:assert(tx_completed);return tx_wrong_address?0xdeadbeef:state.tx_pool[tx_ids[(tx_head+(tx_wrong_order?1:0))%tx_depth]].address;
 case 0xe8:{assert(tx_completed);unsigned slot=tx_ids[tx_head];return tx_bad[slot]?65536:tx_sizes[slot]+tx_wrong_length;}
 case 0xf0:return tx_enabled|((u64)tx_stopped<<1);
 case 0xf8:{if(tx_reset)return 0;unsigned active=tx_count>tx_completed;return tx_count-tx_completed-active|((u64)tx_completed<<8)|((u64)active<<16)|((u64)tx_stopped<<17)|((u64)tx_enabled<<18);}
 default:assert(!"unknown TX read");return 0;
 }
}
static void vg_write(void *base,unsigned off,u64 value){
 if(base==&dma_base&&off==8&&value&&tx_inject_on_unmask){tx_inject_on_unmask=false;tx_complete(false);}
 if(base==&dma_base&&off==0x18){tx_stage_length=value;return;}
 if(base==&dma_base&&off==0x20&&value==3){assert(!tx_enabled&&publish_fences&&!(tx_status&1));tx_compare(0,tx_stage_length);tx_status=1;++tx_legacy_starts;return;}
 if(base!=&dma_base||off<0xe0){vg_write_rx(base,off,value);return;}
 switch(off){
 case 0xe0:tx_stage_address=value;break;
 case 0xe8:tx_stage_length=value;break;
 case 0xf0:
  if(value==1){assert(!tx_enabled&&!tx_count&&!(tx_status&3));tx_enabled=true;tx_stopped=false;}
  else if(value==2){assert(tx_enabled&&!tx_count);tx_enabled=false;tx_stopped=false;}
  else if(value==4){assert(tx_enabled&&!tx_stopped&&tx_count<tx_depth&&tx_stage_length&&tx_stage_length<=2048&&publish_fences>tx_last_fence);
   unsigned slot=16;for(unsigned i=0;i<state.tx_slots;++i)if(state.tx_pool[i].address==tx_stage_address)slot=i;
   assert(slot<16&&!tx_owned[slot]);tx_compare(slot,tx_stage_length);memcpy(tx_snapshot[slot],tx_buffers[slot],tx_stage_length);
   tx_owned[slot]=true;tx_sizes[slot]=tx_stage_length;tx_ids[tx_tail]=slot;tx_tail=(tx_tail+1)%tx_depth;++tx_count;++tx_posts;tx_last_fence=publish_fences;}
  else if(value==8){assert(tx_completed&&consume_fences);unsigned slot=tx_ids[tx_head];assert(tx_owned[slot]);tx_owned[slot]=false;memset(tx_buffers[slot],0xdd,2048);tx_head=(tx_head+1)%tx_depth;--tx_count;--tx_completed;++tx_pops;}
  else assert(!"unsupported TX command in driver");break;
 default:assert(!"unknown TX write");
 }
}
static void dma_free_coherent(void *d,unsigned n,void *p,dma_addr_t a){
 for(unsigned i=0;i<state.tx_slots;++i)if(a==state.tx_pool[i].address)assert(!tx_owned[i]&&!(tx_status&1));
 dma_free_coherent_rx(d,n,p,a);
}
static void setup_tx(unsigned slots,unsigned hardware,bool posted){
 reset_case(4,4);state.posted_tx=posted;state.tx_slots=slots;state.tx_hw_slots=hardware;
 free(state.tx_pool);state.tx_pool=calloc(slots,sizeof(*state.tx_pool));assert(state.tx_pool);
 for(unsigned i=0;i<slots;++i){state.tx_pool[i].address=0x80220000ULL+4096*i;state.tx_pool[i].data=tx_buffers[i];}
 state.tx_buffer=tx_buffers[0];state.tx_address=state.tx_pool[0].address;
 tx_posts=tx_pops=tx_count=tx_completed=tx_head=tx_tail=skb_freed=tx_expected_head=tx_expected_tail=tx_legacy_starts=0;
 tx_depth=hardware;tx_enabled=tx_stopped=tx_reset=tx_wrong_address=tx_wrong_order=tx_wrong_length=copy_fail=tx_inject_on_unmask=false;
 tx_stage_address=tx_stage_length=tx_last_fence=0;memset(tx_owned,0,sizeof tx_owned);
}
'''
CASES=r'''
static void start_tx(unsigned slots,unsigned hardware,bool posted){
 setup_tx(slots,hardware,posted);struct vgq_ops ops={&state,vg_queue_read,vg_queue_write,vg_queue_publish,vg_queue_consume};vgq_u64 addresses[16];
 for(unsigned i=0;i<4;++i)addresses[i]=state.rx_pool[i].address;assert(!vgq_init(&state.rx_ring,ops,4,2048,addresses));
 if(posted){for(unsigned i=0;i<slots;++i)addresses[i]=state.tx_pool[i].address;assert(!vgt_init(&state.tx_ring,ops,slots,2048,addresses));}
 vg_configure(&state.configure.work);assert(state.configured&&enabled&&count==4&&mac_stop==0&&tx_enabled==posted);
}
static struct sk_buff make_skb(unsigned length,bool expect){
 struct sk_buff s={.len=length};for(unsigned i=0;i<length&&i<2048;++i)s.data[i]=17*tx_expected_tail+13*i+31;
 if(expect){assert(tx_expected_tail<256&&length<=2048);tx_expected[tx_expected_tail].n=length;memcpy(tx_expected[tx_expected_tail++].bytes,s.data,length);}return s;
}
int main(int argc,char **argv){(void)argv;negative_payload=argc>1;unsigned cases=0;
 const struct{u64 cap;unsigned slots;}caps[]={{0,0},{4,0},{0x1000004,1},{0x2000004,2},{0x3000004,0},{0x4000004,4},{0x8000004,8},{0x10000004,16},{0x20000004,0},{0x4000003,0}};
 for(unsigned i=0;i<sizeof caps/sizeof caps[0];++i){assert(vgt_cap_slots(caps[i].cap)==caps[i].slots);++cases;}
 for(unsigned slots=1;slots<=16;slots*=2){
  start_tx(slots,slots,true);
  for(unsigned batch=0;batch<3;++batch){unsigned stop_before=stops;
   for(unsigned i=0;i<slots;++i){struct sk_buff s=make_skb(63+i+batch,true);assert(vg_xmit(&s,&device)==0);assert(stops==stop_before+(i+1==slots));}
   struct sk_buff busy=make_skb(64,false);unsigned freed_before=skb_freed;assert(vg_xmit(&busy,&device)==1&&skb_freed==freed_before&&tx_count==slots);
   unsigned wake_before=wakes;for(unsigned i=0;i<slots;++i)tx_complete(false);
   assert(vg_napi_poll(&state.napi,0)==0&&tx_count==0&&state.tx_ring.owned==0&&wakes>wake_before&&!completes);
  }
  assert(device.stats.tx_packets==3*slots&&state.tx_max_batch==slots&&tx_posts==tx_pops&&tx_expected_head==tx_expected_tail);++cases;
 }
 start_tx(3,4,true);for(unsigned i=0;i<3;++i){struct sk_buff s=make_skb(68+i,true);assert(!vg_xmit(&s,&device));}for(unsigned i=0;i<3;++i)tx_complete(false);assert(vg_napi_poll(&state.napi,8)==0&&tx_pops==3);++cases;
 start_tx(4,4,true);struct sk_buff s=make_skb(101,true);assert(!vg_xmit(&s,&device));tx_complete(true);assert(!vg_napi_poll(&state.napi,0)&&device.stats.tx_errors==1&&!device.stats.tx_packets&&!tx_count);++cases;
 for(unsigned kind=0;kind<3;++kind){start_tx(4,4,true);copy_fail=kind==2;struct sk_buff bad=make_skb(kind==0?3:kind==1?2049:64,false);assert(!vg_xmit(&bad,&device)&&device.stats.tx_dropped==1&&skb_freed==1&&!tx_count);++cases;}
 for(unsigned kind=0;kind<5;++kind){start_tx(4,4,true);for(unsigned i=0;i<2;++i){struct sk_buff s=make_skb(90+i,true);assert(!vg_xmit(&s,&device));tx_complete(false);}tx_wrong_address=kind==0;tx_wrong_order=kind==1;tx_wrong_length=kind==2;tx_stopped=kind==3;tx_reset=kind==4;assert(!vg_napi_poll(&state.napi,0)&&state.faulted&&!tx_pops&&state.tx_ring.owned==3&&!irq_enable);++cases;}
 start_tx(4,4,true);s=make_skb(111,true);assert(!vg_xmit(&s,&device));assert(vgt_post(&state.tx_ring,0,111)<0&&vgt_release(&state.tx_ring,0)<0);tx_complete(false);struct vgq_completion c;assert(vgt_peek(&state.tx_ring,&c)==1&&vgt_release(&state.tx_ring,1)<0&&!tx_pops);assert(!vgt_release(&state.tx_ring,0));++cases;
 start_tx(4,4,true);for(unsigned i=0;i<2;++i){s=make_skb(120+i,true);assert(!vg_xmit(&s,&device));}tx_complete(false);tx_inject_on_unmask=true;assert(!vg_napi_poll(&state.napi,8)&&tx_completed==1&&irq_enable==3);assert(vg_irq(1,&device)==IRQ_HANDLED&&!irq_enable);assert(!vg_napi_poll(&state.napi,0)&&!tx_count);++cases;
 start_tx(4,4,true);s=make_skb(99,true);assert(!vg_xmit(&s,&device));tx_complete(false);/* Omit IRQ delivery; a later poll must find retained completion. */assert(!vg_napi_poll(&state.napi,0)&&tx_pops==1);++cases;
 start_tx(4,4,true);for(unsigned i=0;i<4;++i){s=make_skb(80+i,true);assert(!vg_xmit(&s,&device));}complete_frame(65,false,true);for(unsigned i=0;i<4;++i)tx_complete(false);assert(vg_napi_poll(&state.napi,1)==1&&delivered==1&&tx_pops==4&&count==4);++cases;
 start_tx(4,4,true);for(unsigned i=0;i<4;++i){s=make_skb(88+i,true);assert(!vg_xmit(&s,&device));}tx_complete(false);assert(!vg_stop(&device)&&tx_count==4&&state.tx_ring.owned==15&&!freed);for(unsigned i=1;i<4;++i)tx_complete(false);unsigned old_posts=tx_posts;assert(!vg_open(&device));device.carrier=true;vg_configure(&state.configure.work);assert(tx_posts==old_posts&&tx_count==4);assert(!vg_napi_poll(&state.napi,0)&&!tx_count&&tx_pops==4);++cases;
 start_tx(1,1,false);s=make_skb(77,true);assert(!vg_xmit(&s,&device)&&tx_legacy_starts==1&&state.tx_pending);struct sk_buff b=make_skb(77,false);unsigned before=skb_freed;assert(vg_xmit(&b,&device)==1&&skb_freed==before);tx_status=2;assert(!vg_napi_poll(&state.napi,0)&&!state.tx_pending&&device.stats.tx_packets==1);++cases;
 setup_tx(4,4,true);cleanup_buffers(&state);assert(freed==8&&metadata_freed==2);++cases;
 setup_tx(1,1,false);state.configured=true;s=make_skb(93,true);assert(!vg_xmit(&s,&device)&&state.ever_armed);cleanup_buffers(&state);assert(!freed&&metadata_freed==2&&(tx_status&1));++cases;
 puts("POSTED_TX_DRIVER_MMIO_PASS selected_pool=1 copy_before_post=1 fifo=1 batch_wake=1 full_busy_keeps_skb=1 tx_only_budget=1 irq_rearm=1 reset_stop_pinned=1 ifdown_pinned=1 legacy=1");printf("cases=%u\n",cases);return 0;
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cc',default='cc');ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    source=(HERE/'valence_gmac.c').read_text()
    stubs=rx.STUBS.replace('static u64 vg_read(', 'static u64 vg_read_rx(').replace('static void vg_write(', 'static void vg_write_rx(')
    stubs=stubs.replace('static void dma_free_coherent(', 'static void dma_free_coherent_rx(')
    stubs=stubs.replace('tx_errors; } stats;', 'tx_errors,tx_dropped; } stats;')
    names=('vg_queue_read','vg_queue_write','vg_queue_publish','vg_queue_consume','vg_queue_fault','vg_tx_space','vg_arm_rx','vg_configure','vg_irq','vg_napi_poll','vg_xmit','vg_open','vg_stop')
    defs='\n'.join(x for x in source.splitlines() if re.match(r'#define (?:G_|D_|FRAME_BYTES)',x))
    prefix='static void *netdev_priv(struct net_device *d){assert(d==&device);return &state;}\n'
    start=source.index('free_buffers:')+len('free_buffers:');end=source.index('free_net:',start)
    cleanup='static void cleanup_buffers(struct vgmac *p){void *dev=NULL;unsigned int i;'+source[start:end]+'p->rx_pool=NULL;p->tx_pool=NULL;}\n'
    body=stubs+EXTRA+'\n'+defs+'\n'+prefix+'\n'.join(rx.function(source,n) for n in names)+cleanup+CASES
    a.out.mkdir(parents=True,exist_ok=False);c=a.out/'harness.c';c.write_text(body)
    command=[a.cc,'-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-Wno-unused-function','-I'+str(HERE),str(c),'-o',str(a.out/'run')]
    subprocess.run(command,check=True)
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    result=subprocess.run([a.out/'run'],capture_output=True,text=True,env=env,timeout=30);(a.out/'test.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    negative=subprocess.run([a.out/'run','--inject-payload'],capture_output=True,text=True,env=env,timeout=30);(a.out/'negative.log').write_text(negative.stdout+negative.stderr)
    assert negative.returncode and 'TX independent payload mismatch' in negative.stderr
    receipt={'status':'passed','scope':__doc__,'summary':result.stdout,'negative_payload_oracle':True,'driver_sha256':hashlib.sha256(source.encode()).hexdigest(),'tx_header_sha256':hashlib.sha256((HERE/'valence_tx_queue.h').read_bytes()).hexdigest(),'harness_sha256':hashlib.sha256(body.encode()).hexdigest()}
    (a.out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(result.stdout,end='')
if __name__=='__main__':main()
