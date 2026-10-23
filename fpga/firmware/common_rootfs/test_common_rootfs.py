#!/usr/bin/env python3
"""Focused source/package/init tests; no board, mounts, kernel or module execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('common_rootfs_builder', HERE / 'build_rootfs.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def module_elf(name='valence_soc', release='test-release', depends=''):
    names = b'\0.shstrtab\0.modinfo\0'
    info = f'name={name}\0vermagic={release} preempt riscv \0depends={depends}\0'.encode()
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<HH', header, 16, 1, 243)
    table = 64 + len(names) + len(info)
    struct.pack_into('<Q', header, 40, table)
    struct.pack_into('<HHH', header, 58, 64, 3, 1)
    sections = b'\0' * 64
    sections += struct.pack('<IIQQQQIIQQ', 1, 3, 0, 0, 64, len(names), 0, 0, 1, 0)
    sections += struct.pack('<IIQQQQIIQQ', 11, 1, 0, 0, 64 + len(names), len(info), 0, 0, 1, 0)
    return bytes(header) + names + info + sections


def fixture_kernel(root):
    (root / 'linux').mkdir(); (root / 'module').mkdir()
    (root / 'linux/.config').write_text('CONFIG_64BIT=y\nCONFIG_VALENCE_SOC=m\n')
    modules = {}
    for name in b.PRIORITY:
        path = root / 'module' / (name + '.ko')
        path.write_bytes(module_elf(name))
        modules[path.name] = b.sha(path)
    record = dict(stage='kernel_and_modules_ready', init_system='busybox', console_profile='sbi',
        common_platform=dict(cpu_profiles=['i1', 'a1'], cpu_hz=50000000,
                             fabric_hz=50000000, timebase_hz=250000000),
        linux_version='test-release', modules=modules, config_sha256=b.sha(root / 'linux/.config'),
        module_vermagic={n: 'test-release preempt riscv' for n in modules},
        module_dependencies={n: [] for n in modules})
    b.write_json(root / 'kernel-build.json', record)
    return record


class CommonRootfsTests(unittest.TestCase):
    def test_exact_module_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x.ko'; p.write_bytes(module_elf(depends='valence_aia'))
            self.assertEqual(b.module_metadata(p), dict(name='valence_soc',
                vermagic='test-release preempt riscv', depends='valence_aia'))
            for bad in (b'not ELF', module_elf().replace(b'RISC-V', b'x')):
                if bad == module_elf():
                    continue
                p.write_bytes(bad)
                with self.assertRaises(RuntimeError): b.module_metadata(p)
            data = bytearray(module_elf()); struct.pack_into('<H', data, 18, 62); p.write_bytes(data)
            with self.assertRaises(RuntimeError): b.module_metadata(p)

    def test_kernel_inventory_hash_release_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); record = fixture_kernel(root)
            _, modules, order = b.validate_kernel(root)
            self.assertEqual(set(modules), set(b.PRIORITY))
            self.assertLess(order.index('valence_clockmon'), order.index('valence_cmu'))
            self.assertLess(order.index('valence_aia'), order.index('valence_dma'))
            path = root / 'module/valence_dma.ko'; path.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'): b.validate_kernel(root)
            path.write_bytes(module_elf('valence_dma', release='wrong'))
            record['modules'][path.name] = b.sha(path); b.write_json(root / 'kernel-build.json', record)
            with self.assertRaisesRegex(RuntimeError, 'vermagic mismatch'): b.validate_kernel(root)

    def test_reject_missing_module_or_hidden_in_tree_module(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); record = fixture_kernel(root)
            del record['modules']['valence_clockmon.ko']; b.write_json(root / 'kernel-build.json', record)
            with self.assertRaisesRegex(RuntimeError, 'inventory'): b.validate_kernel(root)
            record['modules']['valence_clockmon.ko'] = b.sha(root / 'module/valence_clockmon.ko')
            config = root / 'linux/.config'; config.write_text('CONFIG_USB=m\n')
            record['config_sha256'] = b.sha(config); b.write_json(root / 'kernel-build.json', record)
            with self.assertRaisesRegex(RuntimeError, 'Uninventoried'): b.validate_kernel(root)

    def test_unknown_or_cyclic_dependency_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); record = fixture_kernel(root)
            path = root / 'module/valence_aia.ko'
            path.write_bytes(module_elf('valence_aia', depends='missing_driver'))
            record['modules'][path.name] = b.sha(path)
            record['module_dependencies'][path.name] = ['missing_driver']
            b.write_json(root / 'kernel-build.json', record)
            with self.assertRaisesRegex(RuntimeError, 'Unresolved'): b.validate_kernel(root)

    def test_unsafe_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ('../etc/passwd', '/etc/passwd', 'x\\y', 'x:y'):
                with self.assertRaises(RuntimeError): b.checked_file(root, name)
            p = root / 'links'; p.write_text('/bin/sh\n/linuxrc\n/bin/sh\n')
            self.assertEqual(b.read_links(p), ['bin/sh', 'linuxrc'])
            for name in ('/bin/../init', '/init', 'bin/sh', '/tmp/script'):
                p.write_text(name + '\n')
                with self.assertRaises(RuntimeError): b.read_links(p)

    def test_rootless_newc_devices_and_payload(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'dev').mkdir(); (root / 'bin').mkdir()
            (root / 'bin/busybox').write_bytes(b'ELFfixture')
            (root / 'bin/sh').symlink_to('/bin/busybox')
            first, inventory = b.pack_newc(root)
            second, _ = b.pack_newc(root)
            self.assertEqual(first, second)
            entries = {}; offset = 0
            while True:
                self.assertEqual(first[offset:offset + 6], b'070701')
                fields = [int(first[offset + 6 + 8*i:offset + 14 + 8*i], 16) for i in range(13)]
                offset += 110
                name = first[offset:offset + fields[11] - 1].decode()
                offset = (offset + fields[11] + 3) & ~3
                body = first[offset:offset + fields[6]]
                offset = (offset + fields[6] + 3) & ~3
                if name == 'TRAILER!!!': break
                entries[name] = fields, body
            self.assertEqual(entries['bin/busybox'][1], b'ELFfixture')
            self.assertEqual(entries['bin/sh'][1], b'/bin/busybox')
            for name, major, minor in [('dev/console',5,1),('dev/null',1,3),('dev/tty',5,0)]:
                f, payload = entries[name]
                self.assertTrue(stat.S_ISCHR(f[1])); self.assertEqual(f[9:11], [major, minor])
                self.assertEqual(payload, b''); self.assertEqual(f[2:4], [0,0])
            self.assertEqual(set(entries), set(inventory))

    def simulate_init(self, *, monitor=True, fail_module='', integrity=0, ready=True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for directory in ('etc/valence','run','sys/firmware/devicetree/base/monitor',
                              'sys/bus/platform/devices/board','sys/devices/soc0','sys/class/net/eth0'):
                (root / directory).mkdir(parents=True, exist_ok=True)
            (root / 'etc/valence/kernel-release').write_text('test-release\n')
            (root / 'etc/valence/modules.load').write_text('\n'.join(b.PRIORITY)+'\n')
            (root / 'sys/firmware/devicetree/base/monitor/compatible').write_bytes(b'openion,valence-clock-monitor-v1\0')
            (root / 'sys/firmware/devicetree/base/monitor/status').write_bytes(b'okay\0' if monitor else b'disabled\0')
            board = root / 'sys/bus/platform/devices/board'
            (board / 'irqchip_status').write_text('ready=1 faulted=0\n' if ready else 'ready=0 faulted=1\n')
            for name in ('clock_status','dma_status','rate_status','snapshot','dvfs_policy'):
                (board / name).write_text('fixture\n')
            script = (HERE / 'init').read_text().split('# Invoke only at PID1;',1)[0]
            for prefix in ('/etc/', '/run/', '/sys/', '/lib/'):
                script = script.replace(prefix, str(root) + prefix)
            script += '\nuname() { echo test-release; }\n'
            script += 'sha256sum() { return '+str(integrity)+'; }\n'
            script += ('insmod() { name=${1##*/}; name=${name%.ko}; echo "$name" >> '+str(root / 'loaded')
                       + '; [ "$name" != "'+fail_module+'" ]; }\n')
            script += 'load_modules\necho "FINAL_FAILED=$failed"\n'
            p = subprocess.run(['/bin/sh'], input=script, text=True, capture_output=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
            loaded = (root / 'loaded').read_text().splitlines() if (root / 'loaded').exists() else []
            return loaded, p.stdout

    def test_i1_loads_all_in_real_order(self):
        loaded, output = self.simulate_init()
        self.assertEqual(loaded, list(b.PRIORITY)); self.assertIn('FINAL_FAILED=0', output)

    def test_a1_skips_disabled_dt_capability_without_mmio(self):
        loaded, output = self.simulate_init(monitor=False)
        self.assertEqual(loaded, [n for n in b.PRIORITY if n != 'valence_clockmon'])
        self.assertIn('SKIP_UNSUPPORTED', output); self.assertIn('FINAL_FAILED=0', output)

    def test_irq_fault_blocks_both_consumers(self):
        for kwargs in ({'ready':False}, {'fail_module':'valence_aia'}):
            loaded, output = self.simulate_init(**kwargs)
            self.assertNotIn('valence_dma', loaded); self.assertNotIn('valence_gmac', loaded)
            self.assertIn('FINAL_FAILED=1', output)

    def test_clock_provider_failure_blocks_cmu_and_consumers(self):
        loaded, output = self.simulate_init(fail_module='valence_clockmon')
        for name in ('valence_cmu','valence_dma','valence_gmac'): self.assertNotIn(name, loaded)
        self.assertIn('FINAL_FAILED=1', output)

    def test_hash_failure_loads_nothing(self):
        loaded, output = self.simulate_init(integrity=1)
        self.assertEqual(loaded, []); self.assertIn('FINAL_FAILED=1', output)

    def test_shell_syntax_console_and_no_automatic_dvfs(self):
        for name in ('init','diagnose','net','udhcpc','profile'):
            subprocess.run(['/bin/sh','-n',HERE / name], check=True)
        init = (HERE / 'init').read_text()
        self.assertIn('setsid cttyhack /bin/sh -l', init)
        self.assertNotIn('getty ', init); self.assertNotIn('console_mode=', init)
        self.assertNotIn('udhcpc -', init); self.assertNotIn('devmem ', init)


if __name__ == '__main__':
    unittest.main(verbosity=2)
