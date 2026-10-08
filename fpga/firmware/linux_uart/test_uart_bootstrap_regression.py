#!/usr/bin/env python3
"""Regression for the 2026-10-08 real-board boot failure; no board access.

Pinned Linux serial_core uart_get_ioinfos prints MMIO%s:%pa. vsprintf address_val
uses sizeof(phys_addr_t), yielding 16 hex digits on RV64. serial_base_device_init
adds ctrl and port devices below the physical UART; the tty lives below the port.
The production predicate reads /proc and must not assume a direct tty->OF parent.
"""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

FW = Path(__file__).resolve().parents[1]
HELPER = FW / 'debian_rootfs/dinit/uart-irq-init'
REAL_LINE = '0: uart:16550A MMIO:0x0000000010000000 irq:3 tx:8149 rx:0 RTS|DTR\n'


class BootRegressionTests(unittest.TestCase):
    def run_fixture(self, line, *, delayed=False, controller_fault=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('proc/tty/driver', 'dev', 'run/valence', 'sys/class/tty', 'sys/bus/platform/devices'):
                (root / name).mkdir(parents=True)
            aia = root / 'sys/bus/platform/devices/c000000.interrupt-controller'
            aia.mkdir()
            (aia / 'irqchip_status').write_text('ready=1 faulted=' + ('1' if controller_fault else '0') + '\n')
            tty = root / 'sys/devices/platform/soc/10000000.serial/10000000.serial:0/10000000.serial:0.0/tty/ttyS0'
            tty.mkdir(parents=True)
            (tty / 'irq').write_text('3\n')
            (tty / 'type').write_text('4\n')
            (tty / 'device').symlink_to('../..')
            (root / 'sys/class/tty/ttyS0').symlink_to(tty)
            if not delayed:
                (root / 'dev/ttyS0').touch()
            serial = root / 'proc/tty/driver/serial'
            serial.write_text('0: uart:unknown I/O:0x0 irq:0\n' if delayed else line)
            (root / 'ready-line').write_text(line)
            step = root / 'probe-step'
            # Each wait advances deferred-probe state; UART becomes visible only
            # after the ctrl and port stages. There is no real hardware in here.
            step.write_text('#!/bin/sh\nset -eu\n'
                f'n=$(cat {root}/step-count 2>/dev/null || echo 0)\n'
                f'n=$((n+1)); echo "$n" > {root}/step-count\n'
                f'if [ "$n" -ge 2 ]; then cp {root}/ready-line {serial}; fi\n'
                f'if [ "$n" -ge 3 ]; then touch {root}/dev/ttyS0; fi\n')
            step.chmod(0o755)
            text = HELPER.read_text()
            for prefix in ('/sys/', '/proc/', '/dev/', '/run/'):
                text = text.replace(prefix, str(root) + prefix)
            text = text.replace('[ -c ', '[ -f ')  # mock device node only
            text = text.replace('modprobe valence_aia', 'true')  # mock module loader
            text = text.replace('stty -F ', 'true ')  # mock termios system call
            if delayed:
                text = text.replace('sleep 0.1', str(step))
            else:
                text = text.replace('sleep 0.1', ':')  # bounded-negative test only
            script = root / 'init-test'
            script.write_text('set -eu\n' + text)
            process = subprocess.Popen(['/bin/sh', script], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True)
            marker = root / 'run/valence/uart-recovery-required'
            try:
                deadline = time.monotonic() + 3
                while process.poll() is None and not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                good = line == REAL_LINE or line == REAL_LINE.replace('MMIO:', 'mmio:')
                if good and not controller_fault:
                    self.assertEqual(process.wait(timeout=1), 0)
                    self.assertIn('FIFO IRQ terminal ready', (root / 'dev/ttyS0').read_text())
                    self.assertFalse(marker.exists())
                    if delayed:
                        self.assertEqual((root / 'step-count').read_text().strip(), '3')
                else:
                    self.assertTrue(marker.exists(), 'invalid binding did not reach controlled recovery')
                    time.sleep(0.03)
                    self.assertIsNone(process.poll(), 'PID 1 bootstrap must not exit on recovery')
                    self.assertIn('reset and load the SBI recovery image', (root / 'dev/kmsg').read_text())
                    self.assertEqual((root / 'dev/ttyS0').read_text(), '')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=2)

    def test_actual_rv64_line_and_lowercase(self):
        self.run_fixture(REAL_LINE)
        # Preserve the UART type spelling while varying only MMIO field case.
        self.run_fixture(REAL_LINE.replace('MMIO:', 'mmio:'))

    def test_real_nested_sysfs_and_deferred_ctrl_port_probes(self):
        self.run_fixture(REAL_LINE, delayed=True)

    def test_wrong_base_lookalike_zero_irq_unknown_port_and_controller_fault(self):
        for line in (REAL_LINE.replace('10000000', '10000100'),
                     REAL_LINE.replace('10000000', '110000000'),
                     REAL_LINE.replace('irq:3', 'irq:0'),
                     REAL_LINE.replace('16550A', 'unknown')):
            with self.subTest(line=line):
                self.run_fixture(line)
        self.run_fixture(REAL_LINE, controller_fault=True)

    def test_old_predicate_rejects_real_board_format(self):
        result = subprocess.run(['awk', '$1 == "0:" && $2 == "uart:16550A" { for (i=3;i<=NF;i++) '
            'if (tolower($i)=="mmio:0x10000000") found=1 } END { exit !found }'],
            input=REAL_LINE, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
