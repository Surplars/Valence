#!/usr/bin/env python3
"""Pinned Linux proc-name/format regressions; shell endpoints mocked, no board.

Unlike the v2 regression, fixture filenames are not copied or substituted from
production code. Only host filesystem prefixes and hardware commands are mocked.
Optional VALENCE_QEMU + VALENCE_TARGET_ROOTFS execute the shipped RV64 dash/mawk.
"""
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

FW = Path(__file__).resolve().parents[1]
HELPER = FW / 'debian_rootfs/dinit/uart-irq-init'
# Independently derived from serial8250_reg.driver_name -> proc_tty_register_driver.
PROC_NAME = 'serial_8250'
REAL_LINE = '0: uart:16550A MMIO:0x0000000010000000 irq:3 tx:8149 rx:0 RTS|DTR\n'
HEADER = 'serinfo:1.0 driver revision:\n'


class BootRegressionTests(unittest.TestCase):
    def run_fixture(self, line=REAL_LINE, *, success=True, delayed=False,
                    proc_name=PROC_NAME, proc_missing=False, tty_missing=False,
                    status='ready=1 faulted=0 selftest_irqs=2 claims=2 parent_calls=2 budget_yields=0\n',
                    modprobe_fail=False, stty_fail=False, reopen_fail=False,
                    late_fault=False, diagnostics_fail=False, helper=None, legacy_good=False,
                    expected_proc=PROC_NAME):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('proc/tty/driver', 'dev', 'run/valence', 'sys/class/tty', 'sys/bus/platform/devices'):
                (root / name).mkdir(parents=True)
            aia = root / 'sys/bus/platform/devices/c000000.interrupt-controller'
            aia.mkdir()
            (aia / 'irqchip_status').write_text(status)
            tty = root / 'sys/devices/platform/soc/10000000.serial/10000000.serial:0/10000000.serial:0.0/tty/ttyS0'
            tty.mkdir(parents=True)
            (tty / 'irq').write_text('3\n')
            (tty / 'type').write_text('4\n')
            (tty / 'device').symlink_to('../..')
            (root / 'sys/class/tty/ttyS0').symlink_to(tty)
            if not delayed and not tty_missing:
                (root / 'dev/ttyS0').touch()
            serial = root / 'proc/tty/driver' / proc_name
            if not proc_missing:
                serial.write_text(HEADER + ('0: uart:unknown I/O:0x0 irq:0\n' if delayed else line))
            # An unrelated legacy file must never override bad/missing canonical evidence.
            if legacy_good and proc_name != 'serial':
                (serial.parent / 'serial').write_text(HEADER + REAL_LINE)
            (root / 'ready-line').write_text(HEADER + line)
            step = root / 'probe-step'
            step.write_text('#!/bin/sh\nset -eu\n'
                f'n=$(cat {root}/step-count 2>/dev/null || echo 0)\n'
                f'n=$((n+1)); echo "$n" > {root}/step-count\n'
                f'if [ "$n" -ge 2 ]; then cp {root}/ready-line {serial}; fi\n'
                f'if [ "$n" -ge 3 ]; then touch {root}/dev/ttyS0; fi\n' +
                (f'echo "ready=1 faulted=1" > {aia}/irqchip_status\n' if late_fault else ''))
            step.chmod(0o755)
            text = HELPER.read_text() if helper is None else helper
            for prefix in ('/sys/', '/proc/', '/dev/', '/run/'):
                text = text.replace(prefix, str(root) + prefix)
            text = text.replace('[ -c ', '[ -f ')  # mock device type only
            text = text.replace('modprobe valence_aia', 'false' if modprobe_fail else 'true')
            termios = root / 'termios'
            termios.write_text('#!/bin/sh\n' +
                (f'rm -f {root}/dev/ttyS0; mkdir {root}/dev/ttyS0\n' if reopen_fail else '') +
                ('exit 1\n' if stty_fail else 'exit 0\n'))
            termios.chmod(0o755)
            text = text.replace('stty -F ', str(termios) + ' ')
            text = text.replace('sleep 0.1', str(step) if delayed else ':')
            observed = root / 'recovery-observed'
            text = text.replace('sleep 3600', f'echo recovery > {observed}; sleep 3600')
            if diagnostics_fail:
                (root / 'dev/kmsg').mkdir()  # redirection fails even when running as root
                (root / 'run/valence').rmdir()
            script = root / 'init-test'
            script.write_text('set -eu\n' + text + f'\necho reached > {root}/dinit-reached\n')
            env = os.environ.copy()
            qemu, target = env.get('VALENCE_QEMU'), env.get('VALENCE_TARGET_ROOTFS')
            command = ['/bin/sh', str(script)]
            if qemu or target:
                self.assertTrue(qemu and target, 'Set both VALENCE_QEMU and VALENCE_TARGET_ROOTFS')
                command = [qemu, '-L', target, str(Path(target) / 'usr/bin/dash'), str(script)]
                bindir = root / 'bin'
                bindir.mkdir()
                wrapper = bindir / 'awk'
                wrapper.write_text('#!/bin/sh\nexec ' + ' '.join(map(shlex.quote,
                    [qemu, '-L', target, str(Path(target) / 'usr/bin/mawk')])) + ' "$@"\n')
                wrapper.chmod(0o755)
                env['PATH'] = str(bindir) + ':' + env['PATH']
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True, env=env)
            marker = root / 'run/valence/uart-recovery-required'
            try:
                deadline = time.monotonic() + 8
                while process.poll() is None and not observed.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if success:
                    self.assertEqual(process.wait(timeout=2), 0)
                    self.assertIn('FIFO IRQ binding ready', (root / 'dev/ttyS0').read_text())
                    self.assertTrue((root / 'dinit-reached').exists())
                    self.assertFalse(marker.exists())
                    if delayed:
                        self.assertEqual((root / 'step-count').read_text().strip(), '3')
                else:
                    self.assertTrue(observed.exists(), 'did not reach controlled recovery')
                    time.sleep(0.03)
                    self.assertIsNone(process.poll(), 'PID 1 bootstrap must not exit on recovery')
                    self.assertFalse((root / 'dinit-reached').exists())
                    if not diagnostics_fail:
                        self.assertTrue(marker.exists())
                        self.assertIn('reset and load the SBI recovery image', (root / 'dev/kmsg').read_text())
                        self.assertIn('/proc/tty/driver/' + expected_proc, (root / 'run/valence/uart-failure.log').read_text())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=2)
            return stdout, stderr

    def test_exact_rv64_path_and_format(self):
        self.run_fixture()
        self.run_fixture(REAL_LINE.replace('MMIO:', 'mmio:'))
        self.run_fixture(REAL_LINE.replace('0000000010000000', '10000000'))
        self.run_fixture(REAL_LINE.replace('irq:3', 'irq:7'))  # Linux virq is not a hardware source ID

    def test_real_nested_sysfs_and_deferred_ctrl_port_probes(self):
        self.run_fixture(delayed=True)

    def test_missing_canonical_proc_or_tty_never_falls_back(self):
        self.run_fixture(proc_name='serial', success=False)
        self.run_fixture(proc_missing=True, legacy_good=True, success=False)
        self.run_fixture(tty_missing=True, success=False)

    def test_wrong_base_zero_irq_unknown_port_and_controller_fault(self):
        for line in (REAL_LINE.replace('10000000', '10000100'),
                     REAL_LINE.replace('10000000', '110000000'),
                     REAL_LINE.replace('irq:3', 'irq:0'),
                     REAL_LINE.replace('irq:3', 'irq:3junk'),
                     REAL_LINE.replace('16550A', 'unknown'),
                     REAL_LINE.replace('0:', '1:', 1),
                     REAL_LINE.replace('MMIO:', 'MMIO32:'), ''):
            with self.subTest(line=line):
                self.run_fixture(line, legacy_good=True, success=False)
        for status in ('ready=1 faulted=1\n', 'ready=0 faulted=0\n', 'ready=1 faulted=01\n', ''):
            with self.subTest(status=status):
                self.run_fixture(status=status, success=False)

    def test_module_termios_reopen_and_late_controller_failures(self):
        self.run_fixture(modprobe_fail=True, success=False)
        self.run_fixture(stty_fail=True, success=False)
        self.run_fixture(reopen_fail=True, success=False)
        self.run_fixture(delayed=True, late_fault=True, success=False)

    def test_diagnostic_write_failure_still_keeps_pid1_alive(self):
        self.run_fixture(modprobe_fail=True, diagnostics_fail=True, success=False)

    def test_old_shipped_path_mutation_cannot_pass(self):
        old = HELPER.read_text().replace('uart_proc=/proc/tty/driver/serial_8250\n',
                                       'uart_proc=/proc/tty/driver/serial\n')
        # Canonical good data exists, legacy path is absent. This reproduces v2.
        self.assertNotEqual(old, HELPER.read_text())
        self.run_fixture(helper=old, expected_proc='serial', success=False)

    def test_old_unpadded_predicate_rejects_board_format(self):
        result = subprocess.run(['awk', '$1 == "0:" && $2 == "uart:16550A" { for (i=3;i<=NF;i++) '
            'if (tolower($i)=="mmio:0x10000000") found=1 } END { exit !found }'],
            input=REAL_LINE, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
