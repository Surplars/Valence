#!/usr/bin/env python3
"""Compile the actual probe body against narrow MMIO/driver-core test doubles.
Not Linux execution: allocation/provider/DT wrappers are mocks; transaction core
and probe control flow are the production sources. No hardware access.
"""
import pathlib
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent

def body(source, name, kind="int"):
    start = source.index("static " + kind + " " + name + "(")
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/types.h>
#include "valence_cpu_rate_transaction.h"
#define GFP_KERNEL 0
#define IS_ERR(p) false
#define PTR_ERR(p) (-1)
#define dev_err_probe(d,r,...) (r)
#define dev_warn(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_info(...) ((void)0)
struct device { int unused; };
struct device_attribute { int unused; };
struct platform_device { struct device dev; };
struct resource { unsigned long start, size; };
struct valence_clockmon {
 void *rate, *perf; int lock; bool cpu_control,cpu_armed,cpu_starting; bool fabric_boot_enabled,fabric_attempted,rate_fault;
 unsigned cpu_lanes; u32 cpu_boot_hz,fabric_boot_hz; int cpu_last_result,cpu_control_error,fabric_last_result;
 struct vcpu_transaction cpu_transaction,fabric_transaction;
};
static struct valence_clockmon object;
static u64 regs[32]; static unsigned writes, pauses, mode, clocks, group, calls;
static unsigned int privileged=1;
#define CAP_SYS_ADMIN 0
static bool capable(int cap){return privileged;}
static void *dev_get_drvdata(void *d){return &object;}
static int kstrtouint(const char *s,unsigned int base,unsigned int *v){
 char *end; unsigned long n=strtoul(s,&end,base);
 if(end==s || (*end && *end!='\n') || n>0xffffffffUL)return -EINVAL;
 *v=n;return 0;
}
static int kstrtou32(const char *s,unsigned int base,u32 *v){return kstrtouint(s,base,v);}
static int vcm_group;
static int vcm_hardware_profile(void *d){return mode!=9 ? 1 : -ENODEV;}
static struct resource rate={0x10080800,0x100},perf={0x10080900,0x200};
static struct resource *platform_get_resource_byname(void *p,int t,const char *s)
{ return !strcmp(s,"rate")?&rate:&perf; }
#define IORESOURCE_MEM 0
static unsigned long resource_size(struct resource *r){return r->size;}
static void *devm_kzalloc(void *d,unsigned long n,int g){memset(&object,0,sizeof(object));return &object;}
static void *devm_ioremap_resource(void *d,struct resource *r){return regs;}
static void mutex_init(int *m){*m=0;}
static void mutex_lock(int *m){assert(!*m);*m=1;}
static void mutex_unlock(int *m){assert(*m);*m=0;}
#define vcm_validate_profile mock_vcm_validate
static int mock_vcm_validate(vcm_read_fn r,void *p,unsigned lanes){return 0;}
static void platform_set_drvdata(void *d,void *p){}
static int vcm_register_clocks(void *d,void *p){clocks++;return mode==4?-ENOMEM:0;}
static int devm_device_add_group(void *d,void *p){group++;return mode==5?-ENOMEM:0;}
static u64 vcm_read(void *p,unsigned off){assert(off<0x100);return regs[off/8];}
static void write_cpu(void *p,unsigned off,u64 v){
 assert(object.lock && clocks && group);
 assert(off==0x30 || off==0); writes++;
 if(mode==6 && off==0x30)return;
 regs[off/8]=v;if(!off){regs[2]|=1;regs[11]=1;}
}
static void pause_cpu(void *p){
 pauses++;
 if(mode==8 || pauses<2)return;
 regs[2]=1282;regs[11]=0;regs[10]++;regs[1]=regs[4]=regs[0];
 if(mode==7){regs[1]=regs[4]=50000000;regs[3]=16;regs[2]&=~256ULL;}
}
static u64 now_cpu(void *p){return pauses*100ULL;}
static u64 vcm_fabric_read(void *p,unsigned off){assert(off<0x80);return regs[16+off/8];}
static void vcm_fabric_write(void *p,unsigned off,u64 v){assert(0 && "old CPU test must never write fabric");}
static int vcm_cpu_control_config(void *d,struct valence_clockmon *p){
 struct vcpu_io io={p,vcm_read,write_cpu,pause_cpu,now_cpu}; int r;
 p->cpu_boot_hz=mode==0?50000000:125000000;
 if(mode==0)return 0;
 r=vcpu_initialize(&io,&p->cpu_transaction);
 if(!r){struct vcpu_io f={p,vcm_fabric_read,vcm_fabric_write,pause_cpu,now_cpu};
 r=vcpu_initialize_limit(&f,&p->fabric_transaction,250000000);}
 if(!r)p->cpu_control=true;
 return r;
}
#define vcm_cpu_write write_cpu
#define vcm_cpu_pause pause_cpu
#define vcm_cpu_now_us now_cpu
#define lockdep_assert_held(m) do { assert(*(m)); calls++; } while(0)

'''
MAIN = r'''
int main(void){
 struct platform_device dev;
 for(mode=0;mode<=9;mode++){
  memset(regs,0,sizeof(regs));writes=pauses=clocks=group=calls=0;
  regs[15]=0x4352000300000002ULL;regs[7]=0x000080033e200a0aULL;
  regs[8]=0x30;regs[5]=50000000;regs[14]=250000000;
  regs[13]=10000000;regs[12]=300000000;
  regs[0]=regs[1]=regs[4]=50000000;regs[6]=0x14280a;regs[2]=1026;
  memcpy(regs+16,regs,16*sizeof(u64));regs[16+12]=250000000;
  if(mode==2)regs[10]=2;
  if(mode==3)regs[1]=125000000;
  int r=vcm_probe(&dev);
  if(mode==9){assert(r==-ENODEV && !writes && !clocks && !group);continue;}
  if(mode==4 || mode==5){assert(r==-ENOMEM && !writes);continue;}
  assert(!r && clocks==1 && group==1 && !object.cpu_starting && !object.cpu_armed);
  if(mode==0 || mode==2 || mode==3){
   assert(!writes && !calls && !object.cpu_control);
   if(mode)assert(object.cpu_control_error && object.cpu_transaction.poisoned);
  }else{
   assert(calls>=1);
   if(mode==1){
    assert(writes==2 && !object.cpu_transaction.poisoned && object.cpu_transaction.actual_hz==125000000);
    assert(cpu_target_hz_store(&dev.dev,NULL,"50000000",8)==-EPERM && writes==2);
    privileged=0;assert(cpu_arm_store(&dev.dev,NULL,"1",1)==-EPERM);privileged=1;
    assert(cpu_arm_store(&dev.dev,NULL,"0",1)==-EINVAL);
    object.cpu_starting=true;assert(cpu_arm_store(&dev.dev,NULL,"1",1)==-EAGAIN);object.cpu_starting=false;
    assert(cpu_arm_store(&dev.dev,NULL,"1",1)==1 && writes==2);
    assert(cpu_target_hz_store(&dev.dev,NULL,"100000000",9)==-EINVAL && writes==2);
    assert(cpu_target_hz_store(&dev.dev,NULL,"50000000",8)==8 && writes==4);
   }
   else assert(object.cpu_transaction.poisoned && object.cpu_last_result<0);
   if(mode==7)assert(object.cpu_transaction.actual_hz==50000000);
   if(mode==8)assert(!object.cpu_transaction.actual_hz && pauses==1000);
  }
 }
 puts("CLOCKMON_ACTUAL_PROBE_PASS default_zero_writes prelinux_readonly_degrade boot_once registration_failure fallback unknown_poison");
}
'''
class ProbeTest(unittest.TestCase):
    def test_actual_probe_flow(self):
        src = (HERE/'valence_clockmon.c').read_text()
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);(p/'test.c').write_text(HARNESS+'\n'+body(src,'vcm_fabric_owned_locked')+'\n'+body(src,'vcm_fabric_boot_locked')+'\n'+body(src,'vcm_cpu_set_locked')+'\n'+body(src,'cpu_arm_store','ssize_t')+'\n'+body(src,'cpu_target_hz_store','ssize_t')+'\n'+body(src,'vcm_probe')+'\n'+MAIN)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-I',str(HERE),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)
if __name__=='__main__': unittest.main()
