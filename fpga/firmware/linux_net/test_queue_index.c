/* Exhaustive legal ring-index equivalence; caller validation is unchanged. */
#include <assert.h>
#include <stdio.h>
#include "valence_tx_queue.h"
static vgq_u64 read_zero(void *p, unsigned int offset) { (void)p; (void)offset; return 0; }
static void write_noop(void *p, unsigned int offset, vgq_u64 value) { (void)p; (void)offset; (void)value; }
static void fence_noop(void *p) { (void)p; }
int main(void)
{
 unsigned slots, start, i, cases=0;
 struct vgq_ring rx;
 struct vgt_ring tx;
 struct vgq_ops ops={0,read_zero,write_noop,fence_noop,fence_noop};
 vgq_u64 addresses[16];
 for(i=0;i<16;i++) addresses[i]=0x80200000ULL+i*2048;
 for(slots=1;slots<=16;slots++) {
  assert(!vgq_init(&rx,ops,slots,2048,addresses));
  assert(!vgt_init(&tx,ops,slots,2048,addresses));
  assert(vgq_post(&rx,0)==-1 && vgt_post(&tx,0,64)==-1);
  rx.enabled=tx.enabled=true;
  assert(vgq_post(&rx,slots)==-1 && vgt_post(&tx,slots,64)==-1);
  assert(vgt_post(&tx,0,0)==-1 && vgt_post(&tx,0,2049)==-1);
  for(i=0;i<slots;i++) {
   assert(!vgq_post(&rx,i) && !vgt_post(&tx,i,64));
   assert(rx.tail==(i+1)%slots && tx.tail==(i+1)%slots);
   assert(vgq_post(&rx,i)==-1 && vgt_post(&tx,i,64)==-1);
  }
  assert(rx.tail==0 && tx.tail==0);
 }
 assert(vgq_init(&rx,ops,0,2048,addresses)==-1);
 assert(vgq_init(&rx,ops,17,2048,addresses)==-1);
 assert(vgt_init(&tx,ops,0,2048,addresses)==-1);
 assert(vgt_init(&tx,ops,17,2048,addresses)==-1);
 assert(vgq_init(&rx,ops,1,0,addresses)==-1);
 assert(vgq_init(&rx,ops,1,16385,addresses)==-1);
 addresses[1]=addresses[0];
 assert(vgq_init(&rx,ops,2,2048,addresses)==-1);
 addresses[0]++;
 assert(vgq_init(&rx,ops,1,2048,addresses)==-1);
 for (slots=1; slots<=VGQ_MAX_SLOTS; slots++)
  for(start=0; start<slots; start++) {
   unsigned current=start;
   for(i=0; i<slots*64; i++) {
    unsigned expected=(current+1)%slots;
    current=vgq_next(current,slots);
    assert(current==expected && current<slots);
    cases++;
   }
   assert(current==start);
  }
 puts("QUEUE_INDEX_PASS slots=1..16 all_indices 64_wraps_each");
 printf("transitions=%u\n",cases);
 return 0;
}
