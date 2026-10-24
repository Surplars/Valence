#!/usr/bin/env python3
"""Execute real SBI handoff and production CMU admission against delivered DTB.

libfdt is the pinned OpenSBI source, not a synthetic DT or a default-disabled
UART mock. MMIO uses independent cold-state values; this does not test a board.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import tempfile
import zipfile
from test_clockmon_cpu_probe import body
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
C = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libfdt.h>
#include "valence_cpu_rate_transaction.h"
#include "valence_sbi_console_handoff.h"
#define IS_ENABLED(x) 0
struct device_node { int off; };
struct device { struct device_node *of_node; };
struct valence_clockmon {
 bool cpu_control, fabric_boot_enabled;
 u32 cpu_boot_hz, fabric_boot_hz;
 struct vcpu_transaction cpu_transaction, fabric_transaction;
};
struct of_phandle_args { struct device_node *np; int args_count; u32 args[8]; };
static unsigned char blob[65536], original[65536];
static struct device_node nodes[65536];
static u64 regs[32];
static unsigned writes, cases;
static struct device_node *node_at(int off){
 if(off<0)return NULL;
 assert(off<65536); nodes[off].off=off;return &nodes[off];
}
static struct device_node *of_find_node_by_path(const char *s){return node_at(fdt_path_offset(blob,s));}
static void of_node_put(struct device_node *n){(void)n;}
static bool of_device_is_compatible(struct device_node *n,const char *s){return !fdt_node_check_compatible(blob,n->off,s);}
static bool of_device_is_available(struct device_node *n){
 int len;const char *s=fdt_getprop(blob,n->off,"status",&len);
 return !s || (len==5 && !memcmp(s,"okay",5)) || (len==3 && !memcmp(s,"ok",3));
}
static const void *of_find_property(struct device_node *n,const char *s,void *unused){
 (void)unused;return fdt_getprop(blob,n->off,s,NULL);
}
static bool of_property_read_bool(struct device_node *n,const char *s){return of_find_property(n,s,NULL)!=NULL;}
static int of_property_read_u32(struct device_node *n,const char *s,u32 *v){
 int len;const fdt32_t *p=fdt_getprop(blob,n->off,s,&len);
 if(!p || len!=4)return -EINVAL;
 *v=fdt32_to_cpu(*p);return 0;
}
static struct device_node *next_clock_node(struct device_node *n){
 int off=n?n->off:-1;
 while((off=fdt_next_node(blob,off,NULL))>=0)
  if(fdt_getprop(blob,off,"clocks",NULL))return node_at(off);
 return NULL;
}
#define for_each_node_with_property(n,p) for(n=next_clock_node(NULL);n;n=next_clock_node(n))
static int of_parse_phandle_with_args(struct device_node *n,const char *prop,const char *cells,int wanted,struct of_phandle_args *a){
 int len,at=0,count=0;const fdt32_t *v=fdt_getprop(blob,n->off,prop,&len);
 if(!v || len%4)return -EINVAL;
 while(at<len/4){
  int off=fdt_node_offset_by_phandle(blob,fdt32_to_cpu(v[at++]));u32 nr;
  struct device_node *provider=node_at(off);
  if(!provider || of_property_read_u32(provider,cells,&nr) || nr>8 || nr>(unsigned)(len/4-at))return -EINVAL;
  if(count++==wanted){a->np=provider;a->args_count=nr;for(unsigned j=0;j<nr;j++)a->args[j]=fdt32_to_cpu(v[at+j]);return 0;}
  at+=(int)nr;
 }
 return -ENOENT;
}
static int of_count_phandle_with_args(struct device_node *n,const char *prop,const char *cells){
 struct of_phandle_args a;int i=0,r;
 while(!(r=of_parse_phandle_with_args(n,prop,cells,i,&a)))i++;
 return r==-ENOENT ? i : r;
}
static int of_property_match_string(struct device_node *n,const char *prop,const char *s){return fdt_stringlist_search(blob,n->off,prop,s);}
static u64 vcm_read(void *p,unsigned off){(void)p;assert(off<128 && !(off&7));return regs[off/8];}
static u64 vcm_fabric_read(void *p,unsigned off){(void)p;assert(off<128 && !(off&7));return regs[16+off/8];}
static void vcm_cpu_write(void *p,unsigned off,u64 v){(void)p;(void)off;(void)v;writes++;}
static void vcm_fabric_write(void *p,unsigned off,u64 v){vcm_cpu_write(p,off,v);}
static void vcm_cpu_pause(void *p){(void)p;}
static u64 vcm_cpu_now_us(void *p){(void)p;return 0;}
static void cold(void){
 memset(regs,0,sizeof(regs));writes=0;
 for(unsigned d=0;d<2;d++){
  u64 *b=regs+d*16;b[15]=0x4352000300000002ULL;b[7]=0x000080033e200a0aULL;b[8]=0x30;
  b[5]=b[0]=b[1]=b[4]=50000000;b[14]=250000000;b[13]=10000000;b[12]=d?250000000:300000000;
  b[6]=0x14280a;b[2]=1026;
 }
}
'''
MAIN = r'''
static int config(struct valence_clockmon *p){
 struct device dev={of_find_node_by_path("/soc/clock-monitor@10080800")};
 assert(dev.of_node);memset(p,0,sizeof(*p));cases++;
 return vcm_cpu_control_config(&dev,p);
}
static void reset_blob(void){memcpy(blob,original,sizeof(blob));cold();}
static int uart(void){return fdt_path_offset(blob,"/soc/serial@10000000");}
static void mark(void){assert(!fdt_setprop(blob,uart(),"openion,sbi-console-exclusive",NULL,0));}
static void fixed(void){reset_blob();mark();assert(!valence_sbi_console_handoff(blob));}
int main(int argc,char **argv){
 assert(argc==2 || argc==3);FILE *f=fopen(argv[1],"rb");assert(f);unsigned char input[65536];
 size_t n=fread(input,1,sizeof(input),f);fclose(f);assert(n>40 && !fdt_check_header(input));
 assert(!fdt_open_into(input,original,sizeof(original)));struct valence_clockmon p;
 reset_blob();assert(of_device_is_available(node_at(uart())));
 assert(config(&p)==-EINVAL && !writes && p.cpu_boot_hz==125000000 && p.fabric_boot_hz==50000000);
 assert(p.cpu_transaction.actual_hz==50000000 && p.fabric_transaction.actual_hz==50000000);
 puts("DELIVERED_DT_REPRODUCED EINVAL cpu_target125 fabric_target50 no_writes");
 /* Unmarked firmware retains the old tree, and therefore cannot bypass gate. */
 assert(!valence_sbi_console_handoff(blob));assert(config(&p)==-EINVAL && !writes);
 fixed();assert(!of_device_is_available(node_at(uart())));
 assert(!config(&p) && p.cpu_control && p.fabric_boot_enabled && p.cpu_boot_hz==125000000 && p.fabric_boot_hz==125000000 && !writes);
 /* Reject altered hardware state rather than relax it while fixing the DT. */
 for(unsigned domain=0;domain<2;domain++){
  fixed();regs[domain*16+10]=1;assert(config(&p)==-EBUSY && !writes);
  fixed();regs[domain*16+6]^=1;assert(config(&p)==-EBUSY && !writes);
  fixed();regs[domain*16+8]=0x10;assert(config(&p)==-EBUSY && !writes);
 }
 /* Every relevant static admission dependency comes from the actual DT. */
 fixed();assert(!fdt_setprop_u32(blob,fdt_path_offset(blob,"/cpus"),"timebase-frequency",50000000));assert(config(&p)==-ENODEV && !writes);
 fixed();assert(!fdt_setprop_string(blob,fdt_path_offset(blob,"/cpus/cpu@0"),"compatible","openion,orbital-a1"));assert(config(&p)==-ENODEV && !writes);
 fixed();assert(!fdt_delprop(blob,fdt_path_offset(blob,"/soc/clock-monitor@10080800"),"openion,cpu-clock-observer-only"));assert(config(&p)==-EINVAL && !writes);
 fixed();assert(!fdt_setprop_u32(blob,fdt_path_offset(blob,"/soc/clock-monitor@10080800"),"openion,fabric-boot-hz",50000000));assert(config(&p)==-EINVAL && !writes);
 fixed();assert(!fdt_delprop(blob,fdt_path_offset(blob,"/soc/clock-monitor@10080800"),"openion,i1-boot-pair-125"));assert(config(&p)==-EINVAL && !writes);
 fixed();assert(!fdt_setprop_string(blob,fdt_path_offset(blob,"/soc/clock-controller@10080000"),"clock-names","not-cpu-rate"));assert(config(&p)==-EOPNOTSUPP && !writes);
 /* Exact production order: tight pack, checked +4KiB expansion, handoff. */
 reset_blob();mark();assert(!fdt_pack(blob));
 unsigned char tight[65536];memcpy(tight,blob,sizeof(tight));
 assert(valence_sbi_console_handoff(blob)==-FDT_ERR_NOSPACE);
 assert(!memcmp(tight,blob,sizeof(tight)));
 assert(!fdt_open_into(blob,blob,fdt_totalsize(blob)+4096));
 assert(!valence_sbi_console_handoff(blob));
 assert(!config(&p) && p.fabric_boot_enabled && !writes);
 /* Handoff fails closed on wrong serial target/shape, never touches hardware. */
 reset_blob();mark();assert(!fdt_setprop_string(blob,fdt_path_offset(blob,"/chosen"),"stdout-path","/soc/ethernet@10040000"));assert(valence_sbi_console_handoff(blob)<0);
 reset_blob();mark();assert(!fdt_setprop_string(blob,uart(),"status","disabled"));assert(valence_sbi_console_handoff(blob)<0);
 reset_blob();mark();assert(!fdt_setprop_u32(blob,uart(),"openion,sbi-console-exclusive",1));assert(valence_sbi_console_handoff(blob)<0);
 reset_blob();mark();assert(!fdt_setprop_string(blob,uart(),"compatible","wrong"));assert(valence_sbi_console_handoff(blob)<0);
 if(argc==3){
  f=fopen(argv[2],"rb");assert(f);n=fread(input,1,sizeof(input),f);fclose(f);assert(n>40 && !fdt_check_header(input));
  assert(!fdt_open_into(input,blob,sizeof(blob)));cold();
  assert(of_device_is_available(node_at(uart())));
  assert(config(&p)==-EINVAL && !writes);
  assert(fdt_getprop(blob,uart(),"openion,sbi-console-exclusive",NULL));
  assert(!valence_sbi_console_handoff(blob));
  assert(!of_device_is_available(node_at(uart())));
  assert(!config(&p) && p.cpu_control && p.fabric_boot_enabled && !writes);
  puts("ACTUAL_CANDIDATE_DTB_HANDOFF_ADMISSION_PASS");
 }
 printf("FINAL_DTB_PRODUCTION_ADMISSION_PASS cases=%u real_libfdt real_handoff real_config zero_MMIO_writes\n",cases);
 return 0;
}
'''
def properties(data):
    header=struct.unpack('>10I',data[:40])
    assert header[0]==0xd00dfeed and header[1]<=len(data)
    strings=data[header[3]:header[3]+header[8]]
    at=header[2]; stack=[]; result={}
    while True:
        token=struct.unpack_from('>I',data,at)[0];at+=4
        if token==1:
            end=data.index(0,at);stack.append(data[at:end].decode());at=(end+4)&~3
            result['/'+ '/'.join(stack[1:])]={}
        elif token==2: stack.pop()
        elif token==3:
            size,name=struct.unpack_from('>II',data,at);at+=8
            key=strings[name:strings.index(0,name)].decode()
            result['/'+ '/'.join(stack[1:])][key]=data[at:at+size];at=(at+size+3)&~3
        elif token==4: pass
        elif token==9: return result
        else: raise AssertionError('unexpected FDT token')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--delivery',type=Path,required=True)
    ap.add_argument('--opensbi',type=Path,required=True)
    ap.add_argument('--candidate-dtb',type=Path)
    args=ap.parse_args()
    with zipfile.ZipFile(args.delivery) as z:
        dtb=z.read('i1/valence-vl100.dtb'); prefix=z.read('i1.prefix'); config=z.read('i1/linux.config').decode()
        assert dtb in prefix, 'source DTB differs from actual delivered prefix'
        forbidden=['CPU_FREQ','SMP','SUSPEND','HIBERNATION','CPU_IDLE','OF_OVERLAY','MODULE_UNLOAD','DEVMEM']
        assert all(f'CONFIG_{n}=y' not in config and f'CONFIG_{n}=m' not in config for n in forbidden)
        assert 'CONFIG_HVC_RISCV_SBI=y' in config and 'CONFIG_RISCV_SBI=y' in config
    if args.candidate_dtb:
        candidate=properties(args.candidate_dtb.read_bytes())
        expected=properties(dtb)
        expected['/soc/serial@10000000']['openion,sbi-console-exclusive']=b''
        assert candidate==expected, 'candidate initial DT changed beyond explicit SBI ownership marker'
    src=(HERE/'valence_clockmon.c').read_text()
    funcs=body(src,'vcm_cpu_observer_topology')+'\n'+body(src,'vcm_cpu_control_config')
    lib=args.opensbi.resolve()/'lib/utils/libfdt'
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)
        # Host-only portability definitions replace OpenSBI's string/type ABI,
        # not any libfdt parser/mutator code or the tested handoff function.
        (p/'host_env.h').write_text('''#define LIBFDT_ENV_H
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <limits.h>
#include <endian.h>
typedef uint16_t fdt16_t;
typedef uint32_t fdt32_t;
typedef uint64_t fdt64_t;
#define fdt16_to_cpu(x) be16toh(x)
#define cpu_to_fdt16(x) htobe16(x)
#define fdt32_to_cpu(x) be32toh(x)
#define cpu_to_fdt32(x) htobe32(x)
#define fdt64_to_cpu(x) be64toh(x)
#define cpu_to_fdt64(x) htobe64(x)
''')
        (p/'input.dtb').write_bytes(dtb);(p/'test.c').write_text(C+funcs+MAIN)
        subprocess.run(['cc','-std=c11','-D_DEFAULT_SOURCE','-Wall','-Wextra','-Werror','-include',str(p/'host_env.h'),'-I',str(lib),'-I',str(HERE),'-I',str(ROOT/'fpga/firmware/debian_rootfs'),str(p/'test.c'),*[str(x) for x in sorted(lib.glob('*.c'))],'-o',str(p/'test')],check=True)
        subprocess.run([str(p/'test'),str(p/'input.dtb')]+([str(args.candidate_dtb.resolve())] if args.candidate_dtb else []),check=True)
    print(json.dumps({'delivery_dtb_sha256':hashlib.sha256(dtb).hexdigest(),'production_config_sha256':hashlib.sha256(funcs.encode()).hexdigest(),'handoff_sha256':hashlib.sha256((ROOT/'fpga/firmware/debian_rootfs/valence_sbi_console_handoff.h').read_bytes()).hexdigest(),'board_verified':False}))
if __name__=='__main__':main()
