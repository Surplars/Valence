"""Host-only config/DT/time checks; do not claim PHY or DMA board qualification."""
from pathlib import Path
import shutil
import re
import subprocess
import sys
import tempfile
import unittest
import build_image as b

class ImageTests(unittest.TestCase):
    def test_gc_clock_phy_and_dma_discovery(self):
        text = b.network_dts()
        for value in ('rv64imafdc_zicsr_zifencei', 'timebase-frequency = <100000000>',
                      'serial0:460800n8', 'ethernet0 = &gmac0', 'dma-coherent;',
                      'phy-mode = "rgmii-rxid"', 'ethernet-phy@1 { reg = <1>',
                      '0x10040000', '0x10002000'):
            self.assertIn(value, text)
        self.assertNotIn('192.168.137', text)
        self.assertNotIn('rgmii-id"', text)
        b.validate_dts(text)

    def test_openion_identity_and_stable_compatible(self):
        text = b.network_dts()
        for value in ('OpenIon Valence VL100 / Orbital-A1', 'openion,valence-vl100',
                      'openion,valence-ddr50', '"openion,orbital-a1", "riscv"'):
            self.assertIn(value, text)
        names = (b.HERE / 'valence_driver_names.h').read_text()
        self.assertIn('VALENCE_VENDOR "OpenIon"', names)
        self.assertIn('VALENCE_GMAC_DRIVER "valence-gmac"', names)
        self.assertIn('VALENCE_AIA_DRIVER "valence-aia"', names)
        for source, identifier, compatible in (('valence_gmac.c', 'VALENCE_GMAC_DRIVER',
                'openion,valence-native-gmac-v1'), ('valence_aia.c', 'VALENCE_AIA_DRIVER',
                'openion,valence-aia-csr-v1')):
            code = (b.HERE / source).read_text()
            self.assertIn('.name = ' + identifier, code)
            self.assertIn('MODULE_AUTHOR(VALENCE_VENDOR)', code)
            self.assertIn(compatible, code)

    def test_gmac_ram_aperture_matches_memory_with_optional_platform_drivers(self):
        for memory_bytes in (0x20000000, 0x40000000, 0x80000000):
            for platform_drivers in (False, True):
                with self.subTest(memory_bytes=memory_bytes, platform_drivers=platform_drivers):
                    text = b.network_dts(memory_bytes, platform_drivers)
                    mac = text.split('gmac0: ethernet@10040000 {', 1)[1].split('mdio {', 1)[0]
                    self.assertEqual(mac.count('openion,ram-base'), 1)
                    self.assertEqual(mac.count('openion,ram-bytes'), 1)
                    self.assertIn('openion,ram-base = /bits/ 64 <0x80200000>;', mac)
                    self.assertIn(f'openion,ram-bytes = /bits/ 64 <{hex(memory_bytes)}>;', mac)
                    self.assertIn(f'reg = <0x0 0x80200000 0x0 0x{memory_bytes:x}>;', text)

    def test_manifest_queue_policy_matches_driver_defaults_without_runtime_claim(self):
        code = (b.HERE / 'valence_gmac.c').read_text()
        policy = b.NETWORK_QUEUE_POLICY
        for direction in ('rx', 'tx'):
            default = re.search(r'static unsigned int ' + direction + r'_queue_slots = (\d+);', code)
            self.assertIsNotNone(default)
            self.assertEqual(policy[direction + '_requested_slots_default'], int(default[1]))
        self.assertEqual(policy['requested_slots_range'], [1, 16])
        self.assertEqual(policy['legacy_slots_each_direction'], 1)
        self.assertEqual(policy['dma_buffer_bytes_each'], 2048)
        self.assertTrue(policy['selected_slots_capped_by_hardware'])
        self.assertFalse(policy['runtime_selected_slots_verified'])
        self.assertNotIn("'single_descriptor_each_direction': True", (b.HERE / 'build_image.py').read_text())

    def test_modern_isa_discovery_rejects_missing_or_false_extensions(self):
        text = b.network_dts()
        self.assertIn('riscv,isa-base = "rv64i";', text)
        for extension in b.ISA_EXTENSIONS:
            self.assertIn('"' + extension + '"', text)
        for missing in ('riscv,isa-base', 'riscv,isa-extensions'):
            invalid = '\n'.join(line for line in text.splitlines() if missing not in line)
            with self.assertRaises(RuntimeError):
                b.validate_dts(invalid)
        for before, after in (('"f", ', ''), ('"d", ', ''),
                              ('"rv64i"', '"rv32i"'), ('"zifencei"', '"v"')):
            with self.assertRaises(RuntimeError):
                b.validate_dts(text.replace(before, after))

    def test_timestamp_bootargs_and_init_stages(self):
        self.assertIn('printk.time=1', b.BOOTARGS)
        with self.assertRaises(RuntimeError):
            b.validate_dts(b.network_dts().replace(' printk.time=1', ''))
        init = (b.HERE / 'init').read_text()
        for marker in ('/proc/uptime', 'Loading native GMAC driver',
                       'GMAC module loaded; configuring network', 'Network configuration finished',
                       'VALENCE_LINUX_INIT_OK', 'Starting interactive shell'):
            self.assertIn(marker, init)

    def test_exact_embedded_dtb_is_required(self):
        dtb = b'\xd0\x0d\xfe\xedvalidated-test-dtb'
        b.validate_embedded_dtb(b'opensbi-prefix' + dtb + b'kernel', dtb)
        for image in (b'no-dtb', dtb + dtb):
            with self.assertRaises(RuntimeError):
                b.validate_embedded_dtb(image, dtb)

    def test_fail_closed_configs(self):
        required = ('64BIT', 'MMU', 'RISCV_SBI', 'HVC_RISCV_SBI', 'FPU', 'NET', 'INET',
                    'PACKET', 'NETDEVICES', 'PHYLIB', 'OF_MDIO', 'REALTEK_PHY', 'MODULES', 'HZ_250',
                    'NO_HZ_IDLE', 'IRQ_TIME_ACCOUNTING', 'IRQ_DOMAIN', 'OF_IRQ',
                    'RISCV_ISA_FALLBACK', 'PRINTK_TIME', 'CMDLINE_FORCE')
        good = '\n'.join('CONFIG_' + name + '=y' for name in required)
        good += '\nCONFIG_CMDLINE="' + b.BOOTARGS + '"'
        b.validate_config(good)
        for name in required:
            with self.assertRaises(RuntimeError):
                b.validate_config(good.replace('CONFIG_' + name + '=y', ''))
        for unsafe in ('CONFIG_SMP=y', 'CONFIG_MODULE_UNLOAD=y', 'CONFIG_HZ_PERIODIC=y',
                       'CONFIG_HZ_1000=y', 'CONFIG_IPV6=y'):
            with self.assertRaises(RuntimeError):
                b.validate_config(good + '\n' + unsafe)
        with self.assertRaises(RuntimeError):
            b.validate_config(good.replace(' printk.time=1', ''))

    def test_no_ip_in_driver_and_editable_interfaces(self):
        self.assertNotIn('192.168.137', (b.HERE / 'valence_gmac.c').read_text())
        interfaces = (b.HERE / 'interfaces').read_text()
        self.assertIn('address 192.168.137.30', interfaces)
        self.assertIn('gateway 192.168.137.1', interfaces)

    def test_real_time_function_preserves_fractional_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / 'main.c'
            main.write_text('#include "coremark.h"\n#include <math.h>\nint main(void) {\n'
                'double s=time_in_secs(11825000000ULL);\n'
                'return fabs(s-11.825)>1e-12 || fabs(1100.0/s-93.0232558139535)>1e-9; }\n')
            binary = root / 'test-time'
            subprocess.run(['gcc', '-O2', '-I' + str(b.HERE / 'coremark_port'),
                '-I' + str(b.COREMARK_SOURCE), b.HERE / 'coremark_port/core_portme.c',
                main, '-o', binary], check=True)
            subprocess.run([binary], check=True)

    def test_shell_scripts_parse(self):
        for name in ('init', 'net-test', 'udhcpc.script', 'net-status', 'boot-time'):
            subprocess.run(['sh', '-n', b.HERE / name], check=True)

    def test_compiled_irq_phandles_and_no_fake_standard_imsic(self):
        # A cleaned build tree is normal; do not depend on one dated image.
        dtc = shutil.which('dtc') or b.ROOT / 'simulator/build/linux/scripts/dtc/dtc'
        self.assertTrue(Path(dtc).is_file(), 'dtc is required for compiled DT validation')
        with tempfile.TemporaryDirectory() as directory:
            dts, dtb = Path(directory) / 'board.dts', Path(directory) / 'board.dtb'
            dts.write_text(b.network_dts())
            subprocess.run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts], check=True)
            b.validate_dtb(dtc, dtb)
            for before, after in (('&valence_aia 6 4', '&valence_aia 5 4'),
                                  ('&cpu0_intc 9', '&cpu0_intc 5'),
                                  ('&valence_aia 6 4', '&valence_aia 6 1')):
                dts.write_text(b.network_dts().replace(before, after))
                subprocess.run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts], check=True)
                with self.assertRaises(RuntimeError):
                    b.validate_dtb(dtc, dtb)
        with self.assertRaises(RuntimeError):
            b.validate_dts(b.network_dts().replace('"openion,valence-aia-csr-v1"', '"riscv,imsics"'))

    def test_irq_napi_source_contract_and_loader_order(self):
        driver = (b.HERE / 'valence_gmac.c').read_text()
        for api in ('request_irq(', 'napi_schedule_irqoff(', 'napi_complete_done(',
                    'napi_gro_receive(', 'synchronize_irq(', 'napi_disable('):
            self.assertIn(api, driver)
        self.assertNotIn('msecs_to_jiffies(1)', driver)
        self.assertNotIn('netif_rx(', driver)
        self.assertIn('work < budget', driver)
        self.assertIn('vgq_poll_yield(work, budget, ktime_get_ns(), deadline)', driver)
        queue = (b.HERE / 'valence_rx_queue.h').read_text()
        self.assertIn('budget && work && (work >= budget || now >= deadline)', queue)
        self.assertIn('valence_rx_queue.h', (b.HERE / 'build_image.py').read_text())
        irq = (b.HERE / 'valence_aia.c').read_text()
        setup = irq.split('static int va_program_source(', 1)[1].split('static int va_set_type(', 1)[0]
        self.assertLess(setup.index('writel(mode, p->leaf + A_SOURCE(source))'),
                        setup.index('writel(source, p->leaf + A_TARGET(source))'))
        self.assertIn('readl(p->leaf + A_TARGET(source)) != source', setup)
        self.assertIn('writel(VA_SELFTEST_SOURCE, p->leaf + A_GENMSI)', irq)
        self.assertIn('writel(VA_SELFTEST_SOURCE, p->leaf + A_SETIPNUM)', irq)
        self.assertIn('p->selftest_irqs != 2', irq)
        init = (b.HERE / 'init').read_text()
        self.assertLess(init.index('insmod /lib/modules/valence_aia.ko'),
                        init.index('insmod /lib/modules/valence_gmac.ko'))
        self.assertIn('ready=1 faulted=0', init)
        self.assertIn('initcall_debug', b.BOOTARGS)
        self.assertIn('initramfs_async=0', b.BOOTARGS)

    def test_shared_c_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            main, binary = Path(directory) / 'policy.c', Path(directory) / 'policy'
            main.write_text('#include <assert.h>\n#include "valence_irq_policy.h"\n'
                'int main(void) {\n'
                'assert(va_claim_valid((6UL<<16)|6));\n'
                'assert(!va_claim_valid(0)); assert(!va_claim_valid((6UL<<16)|7));\n'
                'assert(!va_claim_valid((32UL<<16)|32));\n'
                'assert(va_retrigger_level(1U<<6,6,1U<<6));\n'
                'assert(!va_retrigger_level(1U<<6,6,0));\n'
                'assert(!va_retrigger_level(0,6,1U<<6));\n'
                'assert(!va_retrigger_level(~0U,32,~0U));\n'
                'for(int r=0;r<2;r++) for(int c=0;c<2;c++) for(int f=0;f<2;f++)\n'
                'assert(vg_irq_allowed(r,c,f)==(r&&c&&!f));\n'
                'assert(VG_NAPI_WEIGHT==8 && VA_CLAIM_BUDGET==64); return 0; }\n')
            subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                '-I' + str(b.HERE), main, '-o', binary], check=True)
            subprocess.run([binary], check=True)

    def test_net_bench_both_directions_host_loopback(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'net-bench'
            subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', b.HERE / 'net_bench.c', '-o', binary], check=True)
            for direction in ('tx', 'rx'):
                with self.subTest(direction=direction):
                    server = subprocess.Popen([sys.executable, b.HERE / 'net_bench_peer.py',
                        '--bind', '127.0.0.1', '--port', '0', '--once'],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    try:
                        first = server.stdout.readline()
                        self.assertTrue(first.startswith('LISTEN '), first)
                        port = first.split()[1].rsplit(':', 1)[1]
                        client = subprocess.run([binary, direction, '127.0.0.1', port, '1'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
                        self.assertEqual(client.returncode, 0, client.stdout)
                        self.assertIn('NET BENCH PASS', client.stdout)
                        output, _ = server.communicate(timeout=5)
                        self.assertEqual(server.returncode, 0, output)
                        self.assertIn('verified=1048576', output)
                        self.assertIn('PASS', output)
                    finally:
                        if server.poll() is None:
                            server.terminate()
                            server.wait(timeout=5)
                        server.stdout.close()

    def test_cpio_rejects_invalid_payload(self):
        from stage_firmware import cpio_files
        def entry(name, data):
            raw_name = name.encode() + b'\0'
            fields = [1, 0o120777, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(raw_name), 0]
            result = b'070701' + ''.join(f'{x:08x}' for x in fields).encode() + raw_name
            result += bytes((-len(result)) % 4)
            result += data
            return result + bytes((-len(result)) % 4)
        valid = entry('sbin/ip', b'/bin/busybox\0') + entry('TRAILER!!!', b'')
        self.assertEqual(cpio_files(valid)['sbin/ip'], b'/bin/busybox\0')
        for data in (b'', b'bad-header', b'070701'):
            with self.assertRaises((RuntimeError, ValueError)):
                cpio_files(data)

if __name__ == '__main__':
    unittest.main()
