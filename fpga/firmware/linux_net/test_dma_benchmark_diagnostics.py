#!/usr/bin/env python3
"""Compile the actual benchmark store/callback under fault-injection host stubs.
Does not emulate the FPGA, kernel ABI, DMA engine or prove board operation.
"""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).parent
source=(root/'valence_dma.c').read_text()
body=source[source.index('struct vbench {'):source.index('static ssize_t benchmark_show')]
body+=source[source.index('static ssize_t benchmark_store'):source.index('static DEVICE_ATTR_RW(benchmark)')]
pre=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
typedef unsigned long long u64;
typedef uintptr_t dma_addr_t;
typedef int dma_cookie_t;
struct device { void *data; };
struct device_attribute { int unused; };
struct mutex { int locked; };
struct completion { int done; };
struct dma_chan { int unused; };
enum dmaengine_tx_result { DMA_TRANS_NOERROR, DMA_TRANS_WRITE_FAILED };
struct dmaengine_result { enum dmaengine_tx_result result; };
struct dma_async_tx_descriptor { void (*callback_result)(void *, const struct dmaengine_result *); void *callback_param; };
enum { OK, REQUEST, ALLOC_SRC, ALLOC_DST, PREP, SUBMIT, TIMEOUT_STOP, TIMEOUT_PIN, RESULT, MISMATCH };
static int scenario, allocs, frees, releases, syncs, issues, terms, error_logs;
static u64 tick;
static struct dma_chan channel;
static struct device dma_device;
static struct dma_async_tx_descriptor descriptor;
static void *src, *dst;
static size_t transfer_bytes;
#define GFP_KERNEL 0
#define DMA_PREP_INTERRUPT 1
#define DMA_CTRL_ACK 2
#define NSEC_PER_SEC 1000000000ULL
#define dev_get_drvdata(d) ((d)->data)
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define dev_err(...) ((void)++error_logs)
#define dev_info(...) ((void)0)
static int mutex_trylock(struct mutex *m) { if(m->locked)return 0; m->locked=1;return 1; }
static void mutex_unlock(struct mutex *m) { assert(m->locked);m->locked=0; }
static void complete(struct completion *c) { c->done=1; }
static void reinit_completion(struct completion *c) { c->done=0; }
static u64 ktime_get_ns(void) { return ++tick; }
static struct dma_chan *dma_request_chan(struct device *d,const char *n) { return scenario==REQUEST?(void*)(intptr_t)-EIO:&channel; }
static struct device *dmaengine_get_dma_device(struct dma_chan *c) { return &dma_device; }
static void *dma_alloc_coherent(struct device *d,size_t n,dma_addr_t *addr,int flags) { ++allocs; if((scenario==ALLOC_SRC&&allocs==1)||(scenario==ALLOC_DST&&allocs==2))return NULL;void *p=malloc(n);assert(p);*addr=(uintptr_t)p;return p; }
static void dma_free_coherent(struct device *d,size_t n,void *p,dma_addr_t addr) { ++frees;free(p); }
static void dma_wmb(void) {}
static void dma_rmb(void) {}
static struct dma_async_tx_descriptor *dmaengine_prep_dma_memcpy(struct dma_chan *c,dma_addr_t dest,dma_addr_t source,size_t n,int flags) {src=(void*)source;dst=(void*)dest;transfer_bytes=n;return scenario==PREP?NULL:&descriptor;}
static int dmaengine_submit(struct dma_async_tx_descriptor *d) { return scenario==SUBMIT?-EIO:1; }
static int dma_submit_error(int c) {return c<0?c:0;}
static void dma_async_issue_pending(struct dma_chan *c) { ++issues;if(scenario==TIMEOUT_STOP||scenario==TIMEOUT_PIN)return;if(scenario!=MISMATCH)memcpy(dst,src,transfer_bytes);struct dmaengine_result r={scenario==RESULT?DMA_TRANS_WRITE_FAILED:DMA_TRANS_NOERROR};descriptor.callback_result(descriptor.callback_param,&r); }
static int msecs_to_jiffies(int n) {return n;}
static int wait_for_completion_timeout(struct completion *c,int timeout) {return c->done;}
static int dmaengine_terminate_sync(struct dma_chan *c) {++terms;return scenario==TIMEOUT_PIN?-EBUSY:0;}
static void dmaengine_synchronize(struct dma_chan *c) {++syncs;}
static void dma_release_channel(struct dma_chan *c) {++releases;}
static void cond_resched(void) {}
static u64 div64_u64(u64 a,u64 b) {return a/b;}
'''
post=r'''
static void reset(int s) {scenario=s;allocs=frees=releases=syncs=issues=terms=error_logs=0;tick=0;}
int main(void) {
 const char *stages[]={"complete","request_chan","allocate","allocate","prepare","submit","wait","wait","verify","verify"};
 const char *reasons[]={"pass","channel_request","source_allocation","destination_allocation","prepare_rejected","submit_error","timeout_stopped","timeout_pinned","completion_result","data_mismatch"};
 int errors[]={0,-EIO,-ENOMEM,-ENOMEM,-EINVAL,-EIO,-ETIMEDOUT,-ETIMEDOUT,-EIO,-EIO};
 for(int s=OK;s<=MISMATCH;s++) {
  reset(s);struct vbench p={0};struct device dev={&p};
  ssize_t ret=benchmark_store(&dev,NULL,"16 2\n",5);
  assert(ret==(errors[s]?errors[s]:5));assert(p.last_errno==errors[s]);assert(p.run_sequence==1);
  assert(!strcmp(p.last_stage,stages[s]));assert(!strcmp(p.last_reason,reasons[s]));assert(!p.lock.locked);
  if(s==REQUEST)assert(allocs==0&&releases==0&&issues==0&&p.ns==0);
  if(s==ALLOC_SRC||s==ALLOC_DST)assert(allocs==2&&frees==1&&releases==1&&issues==0);
  if(s==PREP||s==SUBMIT)assert(frees==2&&releases==1&&issues==0&&p.ns==0);
  if(s==SUBMIT)assert(p.last_cookie==-EIO);
  if(s==TIMEOUT_PIN) {
   assert(p.faulted&&p.source&&p.destination&&p.chan&&frees==0&&releases==0&&syncs==0&&terms==1);
   int n=allocs;ret=benchmark_store(&dev,NULL,"16 2\n",5);
   assert(ret==-EIO&&p.run_sequence==2&&p.last_errno==-EIO&&!strcmp(p.last_reason,"fault_latched"));
   assert(allocs==n&&frees==0&&releases==0&&issues==1);
   free(p.source);free(p.destination); /* test harness teardown only */
  }else assert(!p.chan&&!p.source&&!p.destination&&!p.faulted);
  if(s==TIMEOUT_STOP)assert(terms==1&&frees==2&&releases==1);
  if(s==RESULT||s==MISMATCH)assert(p.ns>0&&p.last_result==(s==RESULT?DMA_TRANS_WRITE_FAILED:DMA_TRANS_NOERROR));
  if(s==OK)assert(p.last_iteration==2&&p.rate>0&&issues==2&&p.last_result==0);
 }
 reset(OK);struct vbench p={0};struct device dev={&p};
 assert(benchmark_store(&dev,NULL,"7 1\n",4)==-EINVAL);assert(p.run_sequence==0&&error_logs==1&&allocs==0);
 p.lock.locked=1;assert(benchmark_store(&dev,NULL,"16 1\n",5)==-EBUSY);assert(p.run_sequence==0&&error_logs==2&&allocs==0&&p.lock.locked);
 puts("PASS: actual benchmark_store host fault injection, 13 cases; no kernel/hardware claim");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(pre+body+post)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-parameter','-Wno-sign-compare','-Werror','-fsanitize=address,undefined','-g',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
