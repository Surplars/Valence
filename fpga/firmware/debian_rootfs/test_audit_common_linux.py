#!/usr/bin/env python3
"""Fast negative controls for the independent Common Linux content auditor."""
import importlib.util
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import audit_common_linux as audit

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent/'linux_net'),str(HERE.parent)]
spec=importlib.util.spec_from_file_location('network_builder',HERE.parent/'linux_net/build_image.py')
net=importlib.util.module_from_spec(spec)
spec.loader.exec_module(net)


def fixture(cpu='i1'):
    # Derive a test input, never expected values, from the legacy generator.
    text=net.network_dts(0x80000000,True)
    text=text.replace('timebase-frequency = <100000000>','timebase-frequency = <250000000>')
    text=text.replace('clock-frequency = <100000000>','clock-frequency = <50000000>')
    text=text.replace('rv64imafdc_zicsr_zifencei"','rv64imafdc_zicsr_zifencei_svade"')
    text=text.replace('"zifencei";','"zifencei", "svade";')
    if cpu=='i1': text=text.replace('openion,orbital-a1','openion,valence-i1')
    text=text.replace('0x10080000 0x0 0x1000','0x10080000 0x0 0x800')
    text=text.replace('        cmu0:', '''        clockmon0: clockmon@10080800 {
            #clock-cells = <1>;
            compatible = "openion,valence-clock-monitor-v1";
            reg = <0 0x10080800 0 0x100>, <0 0x10080900 0 0x200>;
            reg-names = "rate", "perf";
        };
        cmu0:''')
    if cpu=='i1':
        text=text.replace('compatible = "openion,valence-cmu-v1";', 'compatible = "openion,valence-cmu-v1"; clocks = <&clockmon0 0>; clock-names = "cpu-rate";')
    if cpu=='a1':
        text=text.replace('clockmon@10080800 {','clockmon@10080800 { status = "disabled";')
    return text


def module(release='6.12.0'):
    blob=bytearray(64)
    blob[:6]=b'\x7fELF\x02\x01'
    struct.pack_into('<H',blob,18,243)
    return bytes(blob)+b'\0vermagic='+release.encode()+b' riscv\0'


class AuditTests(unittest.TestCase):
    def test_both_profiles(self):
        for cpu in ('i1','a1'):
            result=audit.audit_dts(fixture(cpu),cpu)
            self.assertEqual(result['ram_end_exclusive'],'0x100200000')
            self.assertFalse(result['board_verified'])

    def test_a1_optional_extension_must_be_disabled(self):
        with self.assertRaises(RuntimeError):
            audit.audit_dts(fixture('a1').replace('status = "disabled";', 'status = "okay";'),'a1')

    def test_mutations_fail(self):
        original=fixture()
        cases=[('250000000','50000000'),('0x80200000 0x0 0x80000000','0x80000000 0x0 0x80000000'),
               ('0x80000000>','0x7fe00000>'),('0xfff78000','0xfff70000'),
               ('7372800','50000000'),('&valence_aia 6 4','&valence_aia 5 4'),
               ('&valence_aia 4 4','&valence_aia 6 4'),('cpu0_intc 7','cpu0_intc 3'),
               ('openion,valence-aia-csr-v1','riscv,plic0'),
               ('0x10080000 0x0 0x800','0x10080000 0x0 0x1000'),
               ('svade"','svpbmt"')]
        for old,new in cases:
            with self.subTest(old=old):
                self.assertIn(old,original)
                with self.assertRaises(RuntimeError): audit.audit_dts(original.replace(old,new),'i1')
        for device in ('gpio','i2c','spi','mmc','usb','nvme','watchdog'):
            with self.subTest(device=device),self.assertRaises(RuntimeError):
                audit.audit_dts(original+'\n'+device+'@1234 { status="okay"; };','i1')

    def test_kernel_config_feature_and_owner_checks(self):
        names=('64BIT MMU RISCV_SBI FPU MODULES IRQ_DOMAIN OF_IRQ SERIAL_8250 '
               'SERIAL_OF_PLATFORM NET INET PHYLIB OF_MDIO REALTEK_PHY COMMON_CLK '
               'DMA_ENGINE DMA_VIRTUAL_CHANNELS DMA_OF VALENCE_CMU VALENCE_DMA '
               'BLK_DEV_INITRD DEVTMPFS PROC_FS SYSFS HVC_RISCV_SBI').split()
        config='\n'.join('CONFIG_'+name+'=y' for name in names)+'\nCONFIG_VALENCE_SOC=m'
        audit.audit_config(config,'sbi')
        for name in names:
            with self.subTest(feature=name),self.assertRaises(RuntimeError):
                audit.audit_config(config.replace('CONFIG_'+name+'=y',''),'sbi')
        for name in ('SMP','RISCV_ISA_V','RISCV_ISA_ZICBOM','MODULE_UNLOAD'):
            with self.subTest(forbidden=name),self.assertRaises(RuntimeError):
                audit.audit_config(config+'\nCONFIG_'+name+'=y','sbi')

    def test_all_six_actual_modules(self):
        entries={'usr/lib/modules/6.12.0/extra/'+n+'.ko':module() for n in audit.MODULES}
        startup='\n'.join('modprobe '+n for n in audit.MODULES)
        self.assertEqual(len(audit.audit_modules(entries,'6.12.0',startup)),6)
        for n in audit.MODULES:
            with self.subTest(module=n),self.assertRaises(RuntimeError):
                audit.audit_modules(entries,'6.12.0',startup.replace('modprobe '+n+'\n','').replace('modprobe '+n,''))
        entries['usr/lib/modules/6.12.0/extra/valence_dma.ko']=module('6.11.0')
        with self.assertRaises(RuntimeError): audit.audit_modules(entries,'6.12.0',startup)

    def test_packed_ordered_insmod_list(self):
        entries={'lib/modules/6.12.0/extra/'+n+'.ko':module() for n in audit.MODULES}
        hashes=''.join(hashlib.sha256(data).hexdigest()+'  /'+name+'\n' for name,data in entries.items())
        entries['etc/valence/modules.sha256']=hashes.encode()
        entries['etc/valence/modules.load']=('\n'.join(audit.MODULES)+'\n').encode()
        entries['init']=b'''sha256sum -c /etc/valence/modules.sha256
compatible_enabled openion,valence-clock-monitor-v1
# SKIP_UNSUPPORTED is checked separately by the rootfs behavioral tests.
while read module; do
insmod "/lib/modules/$release/extra/$module.ko"
done < /etc/valence/modules.load
'''
        audit.audit_modules(entries,'6.12.0','')
        entries['etc/valence/modules.load']=b'valence_soc\n'
        with self.assertRaises(RuntimeError):audit.audit_modules(entries,'6.12.0','')
        entries['etc/valence/modules.load']=('\n'.join(audit.MODULES)+'\n').encode()
        entries['etc/valence/modules.sha256']=hashes.replace(hashes[:64],'0'*64).encode()
        with self.assertRaises(RuntimeError):audit.audit_modules(entries,'6.12.0','')

    def test_payload_entry_not_ram_base(self):
        image=bytearray(256)
        image[0x30:0x38]=b'RISCV\0\0\0'; image[0x38:0x3c]=b'RSC\x05'
        struct.pack_into('<QQQ',image,8,0x200000,len(image),0)
        firmware=bytes(0x200000)+bytes(image)
        audit.audit_image(bytes(image),firmware)
        with self.assertRaises(RuntimeError): audit.audit_image(bytes(image),bytes(image))
        struct.pack_into('<Q',image,16,0x80000000)
        with self.assertRaises(RuntimeError): audit.audit_image(bytes(image),firmware)

    def test_dtc_string_cells(self):
        text=fixture().replace('current-speed = <460800>;', r'current-speed = "", "\a\b";')
        text=text.replace('/bits/ 64 <0x80200000>', '<0 0x80200000>')
        text=text.replace('/bits/ 64 <0x80000000>', '<0 0x80000000>')
        audit.audit_dts(text,'i1')

    def test_numeric_phandles(self):
        text=fixture().replace('compatible = "riscv,cpu-intc";', 'compatible = "riscv,cpu-intc"; phandle = <1>;')
        text=text.replace('compatible = "openion,valence-aia-csr-v1";',
                          'compatible = "openion,valence-aia-csr-v1"; phandle = <2>;')
        text=text.replace('&cpu0_intc','0x1').replace('&valence_aia','0x2')
        audit.audit_dts(text,'i1')


if __name__=='__main__': unittest.main()
