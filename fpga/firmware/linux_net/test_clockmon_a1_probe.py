#!/usr/bin/env python3
"""Execute actual profile/probe bodies with identity and mapping-count mocks."""
import pathlib
import subprocess
import tempfile
import unittest
from test_clockmon_cpu_probe import HARNESS, body
HERE = pathlib.Path(__file__).resolve().parent
class A1ProbeTest(unittest.TestCase):
    def test_actual_a1_readonly_profile(self):
        src = (HERE / 'valence_clockmon.c').read_text()
        self.assertIn('vcm_validate_profile(vcm_read, p, p->cpu_lanes)', body(src, 'rate_status_show', 'ssize_t'))
        self.assertIn('vcm_read_snapshot_profile(vcm_read, p, &snapshot, 4, p->cpu_lanes)', body(src, 'snapshot_show', 'ssize_t'))
        h = HARNESS.replace('struct device { int unused; };', 'struct device_node { int unused; }; struct device { struct device_node *of_node; };')
        h = h.replace('static int vcm_hardware_profile(void *d){return mode!=9 ? 1 : -ENODEV;}', '')
        h = h.replace('static void *devm_ioremap_resource(void *d,struct resource *r){return regs;}', 'static unsigned mappings; static void *devm_ioremap_resource(void *d,struct resource *r){mappings++;return regs;}')
        h = h.replace('static int vcm_cpu_control_config(void *d,struct valence_clockmon *p){', 'static int vcm_cpu_control_config(void *d,struct valence_clockmon *p){ assert(0 && "A1 must not enter write config");')
        h += r'''
static struct device_node node;
static struct device_node *of_find_node_by_path(const char *path){return mode==1 ? NULL : &node;}
static void of_node_put(struct device_node *n){}
static bool of_machine_is_compatible(const char *s){assert(!strcmp(s,"openion,valence-a1-runtime-v2"));return mode!=4;}
static bool of_device_is_compatible(struct device_node *n,const char *s){
 if(!strcmp(s,"openion,valence-i1"))return mode==2;
 if(!strcmp(s,"openion,orbital-a1"))return mode!=3;
 if(!strcmp(s,"openion,valence-a1-runtime-clock-monitor-v2"))return mode!=5;
 if(!strcmp(s,"openion,valence-clock-monitor-v1"))return mode==5;
 assert(0);return false;
}
static void *of_find_property(struct device_node *n,const char *s,void *unused){
 const char *props[]={"openion,cpu-rate-control","openion,cpu-clock-observer-only","openion,cpu-boot-hz","openion,fabric-boot-hz","openion,i1-boot-pair-125"};
 for(unsigned i=0;i<5;i++)if(!strcmp(s,props[i]))return mode==6+i ? &node : NULL;
 assert(0);return NULL;
}
'''
        main = r'''
int main(void){
 struct platform_device dev={{&node}};
 for(mode=0;mode<11;mode++){
  mappings=writes=clocks=group=0;memset(&object,0,sizeof(object));
  int r=vcm_probe(&dev);
  if(!mode){assert(!r && mappings==2 && clocks==1 && group==1 && object.cpu_lanes==2);
   assert(!object.cpu_control && !object.cpu_armed && !object.fabric_boot_enabled);
   assert(object.cpu_boot_hz==50000000 && object.fabric_boot_hz==50000000);
   assert(cpu_arm_store(&dev.dev,NULL,"1",1)==-EOPNOTSUPP);
   assert(cpu_target_hz_store(&dev.dev,NULL,"125000000",9)==-EPERM);
  }else assert(r<0 && !mappings && !clocks && !group);
  assert(!writes);
 }
 puts("CLOCKMON_A1_PROBE_PASS explicit_triple_identity old_A1_rejected_before_MMIO all_write_properties_rejected readonly_no_writes");
}
'''
        funcs = ['vcm_fabric_owned_locked','vcm_fabric_boot_locked','vcm_cpu_set_locked']
        code = h + '\n' + '\n'.join(body(src,n) for n in funcs)
        code += '\n' + body(src,'cpu_arm_store','ssize_t') + '\n' + body(src,'cpu_target_hz_store','ssize_t')
        code += '\n' + body(src,'vcm_hardware_profile') + '\n' + body(src,'vcm_probe') + main
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d); (p/'test.c').write_text(code)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function','-I',str(HERE),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)
if __name__ == '__main__': unittest.main()
