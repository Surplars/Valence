import copy
import importlib.util
from pathlib import Path
import sys
import unittest
import shutil
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('common_test_builder',HERE/'build_image.py')
b=importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class CommonProfileTests(unittest.TestCase):
    def test_both_profiles(self):
        for cpu in ('i1','a1'):
            t=b.common.device_tree(b.net,cpu,b.net.BOOTARGS)
            b.common.validate(t,cpu)
            self.assertIn('timebase-frequency = <250000000>',t)
            self.assertIn('clock-frequency = <50000000>',t)
            self.assertIn('"svade"',t)
            self.assertIn('reg-names = "rate", "perf"',t)
    def test_shared_abi_only_identity_differs(self):
        i=b.common.device_tree(b.net,'i1',b.net.BOOTARGS)
        a=b.common.device_tree(b.net,'a1',b.net.BOOTARGS)
        expected=i.replace('I1','A1').replace('openion,valence-i1','openion,orbital-a1')
        expected=expected.replace('\n            clocks = <&clockmon0 0>;\n            clock-names = \"cpu-rate\";', '')
        expected=expected.replace('reg-names = \"rate\", \"perf\";\n            status = \"okay\";', 'reg-names = \"rate\", \"perf\";\n            status = \"disabled\";')
        self.assertEqual(expected,a)
        with self.assertRaises(RuntimeError):b.common.validate(i.replace('openion,valence-i1','openion,orbital-a1'),'a1')
    def test_mutations_fail(self):
        t=b.common.device_tree(b.net,'i1',b.net.BOOTARGS)
        for old,new in [('250000000','100000000'),('50000000','125000000'),
                        ('7372800','1843200'),('460800','115200'),
                        ('0x80000000','0x20000000'),('0xfff78000','0xfff79000'),
                        ('0x10080000 0x0 0x800','0x10080000 0x0 0x1000'),
                        ('0x10080900 0x0 0x200','0x10080800 0x0 0x300'),
                        ('&valence_aia 6 4','&valence_aia 5 4'),
                        ('&valence_aia 4 4','&valence_aia 3 4'),
                        ('openion,valence-i1','openion,orbital-a1')]:
            with self.subTest(old=old),self.assertRaises(RuntimeError):
                b.common.validate(t.replace(old,new),'i1')
    def test_old_record_rejected(self):
        for r in ({},{'common_platform':{}}):
            with self.assertRaises(RuntimeError):b.common.check_record(r)
        r={'common_platform':copy.deepcopy(b.common.CONTRACT)}
        b.common.check_record(r)
        r['common_platform']['timebase_hz']=100000000
        with self.assertRaises(RuntimeError):b.common.check_record(r)
    def test_compiled_dtb(self):
        self.assertIsNotNone(shutil.which('dtc'), 'source cloud build env: dtc required')
        with tempfile.TemporaryDirectory() as directory:
            for cpu in b.common.CPUS:
                p=Path(directory)/cpu
                p.with_suffix('.dts').write_text(b.common.device_tree(b.net,cpu,b.net.BOOTARGS))
                subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',str(p)+'.dtb',str(p)+'.dts'],check=True)
                decoded=subprocess.check_output(['dtc','-q','-I','dtb','-O','dts',str(p)+'.dtb'],text=True)
                b.common.validate(decoded,cpu)
    def test_explicit_i1_boot125(self):
        t=b.common.device_tree(b.net,'i1',b.net.BOOTARGS,boot_cpu_hz=125000000)
        b.common.validate(t,'i1',125000000)
        self.assertIn('openion,cpu-boot-hz = <125000000>',t)
        self.assertIn('clock-frequency = <50000000>',t)
        for old,new in [('openion,cpu-rate-control;', ''),
                        ('openion,cpu-clock-observer-only;', ''),
                        ('openion,cpu-boot-hz = <125000000>', 'openion,cpu-boot-hz = <195000000>')]:
            with self.assertRaises(RuntimeError):b.common.validate(t.replace(old,new),'i1',125000000)
        with self.assertRaises(RuntimeError):b.common.validate(t,'i1')
        for cpu,hz in [('a1',125000000),('i1',195000000),('i1',0)]:
            with self.assertRaises(RuntimeError):b.common.device_tree(b.net,cpu,b.net.BOOTARGS,boot_cpu_hz=hz)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'i1.dts';p.write_text(t)
            subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',str(p)+'.dtb',str(p)],check=True)
            decoded=subprocess.check_output(['dtc','-q','-I','dtb','-O','dts',str(p)+'.dtb'],text=True)
            b.common.validate(decoded,'i1',125000000)
    def test_explicit_i1_boot_pair(self):
        t=b.common.device_tree(b.net,'i1',b.net.BOOTARGS,boot_cpu_hz=125000000,boot_fabric_hz=125000000)
        b.common.validate(t,'i1',125000000,125000000)
        for old,new in [('openion,i1-boot-pair-125;', ''),('openion,fabric-boot-hz = <125000000>','openion,fabric-boot-hz = <155000000>')]:
            with self.assertRaises(RuntimeError):b.common.validate(t.replace(old,new),'i1',125000000,125000000)
        with self.assertRaises(RuntimeError):b.common.validate(t,'i1',125000000)
        for cpu,chz,fhz,console in [('a1',125000000,125000000,'sbi'),('i1',50000000,125000000,'sbi'),('i1',125000000,155000000,'sbi'),('i1',125000000,125000000,'uart-irq')]:
            with self.assertRaises(RuntimeError):b.common.device_tree(b.net,cpu,b.net.BOOTARGS,console,chz,fhz)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'pair.dts';p.write_text(t)
            subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',str(p)+'.dtb',str(p)],check=True)
            decoded=subprocess.check_output(['dtc','-q','-I','dtb','-O','dts',str(p)+'.dtb'],text=True)
            b.common.validate(decoded,'i1',125000000,125000000)
    def test_a1_runtime_explicit_identity(self):
        t=b.common.device_tree(b.net,'a1-runtime',b.net.BOOTARGS)
        self.assertIn(b.common.A1_CAPABILITY,t)
        self.assertIn(b.common.A1_MONITOR,t)
        self.assertIn('openion,orbital-a1',t)
        self.assertNotIn('openion,cpu-rate-control',t)
        for cpu in ('a1','i1'):
            with self.assertRaises(RuntimeError):b.common.validate(t,cpu)
        for token in (b.common.A1_CAPABILITY,b.common.A1_MONITOR):
            with self.assertRaises(RuntimeError):b.common.validate(t.replace(token,'wrong'),'a1-runtime')
        with self.assertRaises(RuntimeError):b.common.device_tree(b.net,'a1-runtime',b.net.BOOTARGS,boot_cpu_hz=125000000)
        with self.assertRaises(RuntimeError):b.common.device_tree(b.net,'a1-runtime',b.net.BOOTARGS,boot_fabric_hz=125000000)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'a1runtime.dts';p.write_text(t)
            subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',str(p)+'.dtb',str(p)],check=True)
            decoded=subprocess.check_output(['dtc','-q','-I','dtb','-O','dts',str(p)+'.dtb'],text=True)
            b.common.validate(decoded,'a1-runtime')
    def test_a1_contract_strict(self):
        c=dict(schema=1,platform='CommonMachinePlatform',emitter='CommonA1DynamicMain',experimentalA1Runtime=True,
               cpu_telemetry_descriptor='0x544d002000000002',fabric_telemetry_descriptor='0x544d002000000001',
               source_commit='a'*40,receipt_sha256='b'*64,hardware_scope='experimental-model-only',
               physical_qualified=False,board_verified=False,production_default=False,
               boot_cpu_hz=50000000,boot_fabric_hz=50000000,timer_hz=250000000,
               root_compatible=b.common.A1_CAPABILITY,cpu_compatible='openion,orbital-a1',
               monitor_compatible=b.common.A1_MONITOR,retirement_lanes=2,
               rate_mmio_base='0x10080800',rate_mmio_size='0x100',
               perf_mmio_base='0x10080900',perf_mmio_size='0x200',not_a_bitstream_identity=True)
        b.common.validate_a1_hardware_contract(c)
        for key in c:
            invalid=dict(c);del invalid[key]
            with self.assertRaises(RuntimeError):b.common.validate_a1_hardware_contract(invalid)
        for key,value in [('physical_qualified',True),('experimentalA1Runtime',1),('boot_cpu_hz',125000000),('cpu_telemetry_descriptor','0x544d002000000001')]:
            invalid=dict(c);invalid[key]=value
            with self.assertRaises(RuntimeError):b.common.validate_a1_hardware_contract(invalid)
    def test_six_modules(self):
        self.assertEqual(set(b.MODULES), {'valence_'+n+'.ko' for n in
                         ('soc','aia','gmac','cmu','dma','clockmon')})
    def test_legacy_unchanged(self):
        t=b.net.network_dts()
        self.assertIn('timebase-frequency = <100000000>',t)
        self.assertNotIn('clock-monitor@',t)
    def test_unknown_cpu(self):
        with self.assertRaises(RuntimeError):b.common.device_tree(b.net,'unknown',b.net.BOOTARGS)

if __name__=='__main__':unittest.main()
