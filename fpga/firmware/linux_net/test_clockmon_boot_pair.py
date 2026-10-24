#!/usr/bin/env python3
"""Actual production probe/config/CPU/fabric bodies with bounded kernel/MMIO mocks.
No Linux load, FPGA timing, native MMCM or board qualification is inferred.
"""
import pathlib
import subprocess
import tempfile
import unittest
from test_clockmon_cpu_probe import HARNESS, body
HERE = pathlib.Path(__file__).resolve().parent

class BootPairTest(unittest.TestCase):
    def test_actual_production_boot_pair(self):
        src = (HERE/'valence_clockmon.c').read_text()
        h = HARNESS.replace('struct device { int unused; };', 'struct device_node { int kind; }; struct device { struct device_node *of_node; };')
        h = h.replace('return mode!=9 ? 1 : -ENODEV;', 'return mode!=20 ? 1 : -ENODEV;')
        h = h.replace('clocks++;return mode==4?-ENOMEM:0;', 'clocks++;if(mode==25)regs[26]++;return mode==4?-ENOMEM:0;')
        h = h.replace('return mode==4?-ENOMEM:0;', 'return mode==7?-ENOMEM:0;').replace('return mode==5?-ENOMEM:0;', 'return mode==8?-ENOMEM:0;')
        start = h.index('static void write_cpu(')
        end = h.index('#define vcm_cpu_write', start)
        h = h[:start] + r'''
static unsigned bank_writes[2], request_bank[4], request_count;
static void write_bank(unsigned d,unsigned off,u64 value){
 assert(object.lock && clocks && group && (off==0 || off==0x30));
 if(d)assert(object.cpu_starting && object.fabric_boot_enabled && object.fabric_attempted);
 writes++;bank_writes[d]++;
 if(mode==16 && d && off==0x30)return;
 regs[d*16+off/8]=value;
 if(!off){assert(request_count<4);request_bank[request_count++]=d;regs[d*16+2]|=1;regs[d*16+11]=1;}
}
static void write_cpu(void *p,unsigned off,u64 v){write_bank(0,off,v);}
static u64 vcm_fabric_read(void *p,unsigned off){assert(off<0x80);return regs[16+off/8];}
static unsigned warnings;
#define WARN_ON(x) ((x) ? (++warnings,1) : 0)
static void writeq(u64 value,void *address){
 unsigned off=(unsigned)((char*)address-(char*)regs);
 assert(off==0x80 || off==0xb0);write_bank(1,off-0x80,value);
}
static void pause_cpu(void *p){
 pauses++;
 for(unsigned d=0;d<2;d++){
  u64 *b=regs+16*d;if(!(b[2]&1))continue;
  if((mode==4 && !d)||(mode==6 && d))continue;
  b[2]=1282;b[11]=0;b[10]++;b[1]=b[4]=b[0];
  if((mode==3 && !d)||(mode==5 && d)){b[1]=b[4]=50000000;b[3]=16;b[2]&=~256ULL;}
 }
}
static u64 now_cpu(void *p){return pauses*100ULL;}
#define IS_ENABLED(c) 0
static struct device_node cpu_node={1},cpus_node={2},uart_node={3};
static struct device_node *of_find_node_by_path(const char *s){
 if(!strcmp(s,"/cpus/cpu@0"))return &cpu_node;
 if(!strcmp(s,"/cpus"))return &cpus_node;
 if(!strcmp(s,"/soc/serial@10000000"))return &uart_node;
 return NULL;
}
static void of_node_put(struct device_node *n){}
static bool of_device_is_compatible(struct device_node *n,const char *s){return n==&cpu_node && !strcmp(s,"openion,valence-i1");}
static bool of_device_is_available(struct device_node *n){return mode==14;}
static bool pair_requested(void){return mode>=2 && mode!=20;}
static bool of_property_read_bool(struct device_node *n,const char *s){
 if(!strcmp(s,"openion,cpu-rate-control"))return mode!=0 && mode!=11;
 if(!strcmp(s,"openion,cpu-clock-observer-only"))return true;
 if(!strcmp(s,"openion,i1-boot-pair-125"))return pair_requested() && mode!=12;
 return false;
}
static void *of_find_property(struct device_node *n,const char *s,void *len){
 if(!strcmp(s,"openion,cpu-boot-hz"))return (void*)1;
 if(!strcmp(s,"openion,fabric-boot-hz") && pair_requested())return (void*)1;
 return NULL;
}
static int of_property_read_u32(struct device_node *n,const char *s,u32 *v){
 if(!strcmp(s,"timebase-frequency")){*v=250000000;return 0;}
 if(!strcmp(s,"openion,cpu-boot-hz")){*v=mode==13?50000000:125000000;return 0;}
 if(!strcmp(s,"openion,fabric-boot-hz")){*v=mode==15?100000000:125000000;return 0;}
 return -EINVAL;
}
static int vcm_cpu_observer_topology(struct device_node *n){return 0;}
''' + h[end:]
        functions = '\n'.join(body(src, n, k) for n, k in (
            ('vcm_fabric_write','void'),('vcm_fabric_owned_locked','int'),('vcm_fabric_boot_locked','int'),
            ('vcm_cpu_set_locked','int'),('cpu_arm_store','ssize_t'),
            ('cpu_target_hz_store','ssize_t'),('vcm_cpu_control_config','int'),('vcm_probe','int')))
        main = r'''
int main(void){
 struct platform_device dev={0};
 for(mode=0;mode<=25;mode++){
  memset(regs,0,sizeof(regs));writes=pauses=clocks=group=calls=request_count=0;
  bank_writes[0]=bank_writes[1]=0;
  for(unsigned d=0;d<2;d++){
   u64 *b=regs+16*d;b[15]=0x4352000300000002ULL;b[7]=0x000080033e200a0aULL;
   b[8]=0x30;b[5]=50000000;b[14]=250000000;b[13]=10000000;b[12]=d?250000000:300000000;
   b[0]=b[1]=b[4]=50000000;b[6]=0x14280a;b[2]=1026;
  }
  if(mode==9)regs[26]=2;
  if(mode==10)regs[28]=300000000;
  if(mode==17)regs[24]=0x10;
  if(mode==18)regs[17]=125000000;
  if(mode==19)regs[22]^=1;
  if(mode==21)regs[27]=1;
  if(mode==22)regs[18]|=0x800;
  if(mode==23)regs[19]=1;
  if(mode==24)regs[10]=2;
  int r=vcm_probe(&dev);
  if(mode==20){assert(r==-ENODEV && !writes && !clocks && !group);continue;}
  if(mode==7 || mode==8){assert(r==-ENOMEM && !writes);continue;}
  assert(!r && !object.cpu_starting && !object.cpu_armed);
  if(mode==25){
   assert(!writes && object.rate_fault && object.cpu_last_result==-EIO && object.fabric_last_result==-EPERM);
   assert(!object.fabric_transaction.actual_hz);continue;
  }
  if(mode==0 || (mode>=9 && mode<=15) || mode>=17){
   assert(!writes && !object.cpu_control && !object.fabric_attempted);
   if(mode)assert(object.cpu_control_error);
   continue;
  }
  if(mode==1){assert(writes==2 && !bank_writes[1] && !object.fabric_boot_enabled);continue;}
  assert(object.fabric_boot_enabled && bank_writes[0]==2);
  if(mode==3 || mode==4){
   assert(!bank_writes[1] && !object.fabric_attempted && object.fabric_last_result==-ECANCELED);
   assert(object.fabric_transaction.actual_hz==50000000);
   assert(object.cpu_transaction.actual_hz==(mode==3?50000000:0));
  }else{
   assert(object.fabric_attempted && request_bank[0]==0);
   if(mode==16){assert(bank_writes[1]==1 && request_count==1);}
   else{assert(bank_writes[1]==2 && request_count==2 && request_bank[1]==1);}
   if(mode==2){
    assert(!object.rate_fault && !object.fabric_last_result && object.fabric_transaction.actual_hz==125000000);
    unsigned old=writes;
    assert(cpu_arm_store(&dev.dev,NULL,"1",1)==1);
    assert(cpu_target_hz_store(&dev.dev,NULL,"50000000",8)==-EPERM && writes==old);
    assert(cpu_target_hz_store(&dev.dev,NULL,"125000000",9)==9 && writes==old);
    object.cpu_starting=true;mutex_lock(&object.lock);assert(vcm_fabric_boot_locked(&object)==-EPERM);mutex_unlock(&object.lock);object.cpu_starting=false;
    assert(writes==old);
    /* Actual production writer refuses non-startup and non-target addresses. */
    warnings=0;vcm_fabric_write(&object,0,50000000);assert(warnings==1 && writes==old);
    object.cpu_starting=true;vcm_fabric_write(&object,0x38,0);object.cpu_starting=false;
    assert(warnings==2 && writes==old);
    /* Even equal-Hz foreign completion invalidates the shared owner. */
    regs[26]++;assert(cpu_target_hz_store(&dev.dev,NULL,"125000000",9)==-EIO && writes==old);
   }else{
    assert(object.rate_fault && object.fabric_last_result<0 && object.fabric_transaction.poisoned);
    assert(object.fabric_transaction.actual_hz==(mode==6?0:50000000));
    unsigned old=writes;assert(cpu_arm_store(&dev.dev,NULL,"1",1)==-EIO && writes==old);
   }
  }
 }
 puts("CLOCKMON_BOOT_PAIR_PASS actual_config_probe CPU_then_fabric no_runtime_fabric forbidden_50_125 preflight fallback unknown_global_poison registration_zero_writes");
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);(p/'test.c').write_text(h+'\n'+functions+'\n'+main)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                            '-I',str(HERE),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)

if __name__ == '__main__':
    unittest.main()
