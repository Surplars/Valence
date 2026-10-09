#!/usr/bin/env python3
"""V4: target shell reaches Dinit despite observation failures; PTY I/O handoff.

Fixtures never claim Valence UART/IRQ execution. VALENCE_QEMU and
VALENCE_TARGET_ROOTFS select the actual shipped RV64 dash instead of host dash.
"""
import os
from pathlib import Path
import pty
import select
import shlex
import subprocess
import tempfile
import time
import unittest

FW = Path(__file__).resolve().parents[1]
HELPER = FW / 'debian_rootfs/dinit/uart-irq-init'
REAL_LINE = '0: uart:16550A MMIO:0x0000000010000000 irq:3 tx:8149 rx:0 RTS|DTR\n'


def shell(script):
    qemu, target = os.environ.get('VALENCE_QEMU'), os.environ.get('VALENCE_TARGET_ROOTFS')
    if qemu or target:
        if not qemu or not target:
            raise RuntimeError('Set both VALENCE_QEMU and VALENCE_TARGET_ROOTFS')
        return [qemu, '-L', target, str(Path(target) / 'usr/bin/dash'), str(script)]
    return ['/bin/sh', str(script)]


class BootRegressionTests(unittest.TestCase):
    def fixture(self, *, line=REAL_LINE, proc_name='serial_8250', node=True,
                module_fail=False, termios_fail=False, reopen_fail=False, diagnostics_fail=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('proc/tty/driver', 'dev', 'run/valence'):
                (root / name).mkdir(parents=True)
            if proc_name:
                (root / 'proc/tty/driver' / proc_name).write_text(line)
            if node:
                (root / 'dev/ttyS0').touch()
            if diagnostics_fail:
                (root / 'run/valence').rmdir()
                (root / 'dev/kmsg').mkdir()
            termios = root / 'termios'
            termios.write_text('#!/bin/sh\n' +
                (f'rm -f {root}/dev/ttyS0; mkdir {root}/dev/ttyS0\n' if reopen_fail else '') +
                ('exit 1\n' if termios_fail else 'exit 0\n'))
            termios.chmod(0o755)
            text = HELPER.read_text()
            for prefix in ('/proc/', '/dev/', '/run/'):
                text = text.replace(prefix, str(root) + prefix)
            text = text.replace('[ -c ', '[ -f ')
            text = text.replace('modprobe valence_aia', 'false' if module_fail else 'true')
            text = text.replace('stty -F ', str(termios) + ' ')
            # These fail loudly if a proc/status predicate or busy wait returns.
            trap = f'echo forbidden > {root}/forbidden; return 91'
            script = root / 'init-test'
            script.write_text('set -eu\nawk() { ' + trap + '; }\n'
                'sleep() { ' + trap + '; }\n' + text +
                f'\necho reached > {root}/dinit-reached\n')
            result = subprocess.run(shell(script), capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertTrue((root / 'dinit-reached').exists())
            self.assertFalse((root / 'forbidden').exists())
            self.assertFalse((root / 'run/valence/uart-recovery-required').exists())
            if not diagnostics_fail:
                log = (root / 'run/valence/uart-startup.log').read_text()
                self.assertIn('readiness self-check disabled', log)
                self.assertIn('UART IRQ traffic unverified', log)
                if not node or module_fail or termios_fail or reopen_fail:
                    self.assertTrue((root / 'run/valence/uart-warning').exists())
                else:
                    self.assertIn('ttyS0 descriptors opened', log)

    def test_actual_proc_and_old_or_missing_proc_all_continue(self):
        for name in ('serial_8250', 'serial', None):
            with self.subTest(proc=name):
                self.fixture(proc_name=name)

    def test_bad_unknown_or_zero_irq_is_not_a_boot_gate(self):
        for line in (REAL_LINE.replace('irq:3', 'irq:0'),
                     REAL_LINE.replace('16550A', 'unknown'),
                     REAL_LINE.replace('10000000', '10000100'), '', 'unrecognized-format\n'):
            with self.subTest(line=line):
                self.fixture(line=line)

    def test_missing_node_continues_for_getty_retry(self):
        self.fixture(node=False)

    def test_module_and_termios_failures_warn_and_continue(self):
        self.fixture(module_fail=True)
        self.fixture(termios_fail=True)

    def test_descriptor_reopen_failure_does_not_exit_pid1(self):
        self.fixture(reopen_fail=True)

    def test_logging_failure_does_not_exit_pid1(self):
        self.fixture(module_fail=True, diagnostics_fail=True)

    def test_no_proc_parser_or_readiness_loop(self):
        executable = '\n'.join(line for line in HELPER.read_text().splitlines() if not line.lstrip().startswith('#'))
        for forbidden in ('awk ', 'while ', 'sleep ', 'uart_controller_ready', 'uart_fail'):
            self.assertNotIn(forbidden, executable)
        self.assertIn('timeout 2 stty -F /dev/ttyS0 460800', executable)

    def test_real_character_pty_descriptors_read_and_write(self):
        master, slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'run/valence').mkdir(parents=True)
                (root / 'dev').mkdir()
                text = HELPER.read_text().replace('/dev/ttyS0', os.ttyname(slave))
                for prefix in ('/run/', '/proc/'):
                    text = text.replace(prefix, str(root) + prefix)
                text = text.replace('/dev/kmsg', str(root / 'dev/kmsg'))
                text = text.replace('modprobe valence_aia', 'true')
                script = root / 'pty-test'
                script.write_text('set -eu\n' + text + '\nprintf "DINIT_REACHED\\n"\n'
                                  'read -r input\nprintf "ECHO:%s\\n" "$input"\n')
                process = subprocess.Popen(shell(script), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                data = b''; deadline = time.monotonic() + 6; sent = False
                while time.monotonic() < deadline and b'ECHO:uart-v4-test' not in data:
                    readable, _, _ = select.select([master], [], [], 0.1)
                    if readable:
                        data += os.read(master, 4096)
                    if b'DINIT_REACHED' in data and not sent:
                        os.write(master, b'uart-v4-test\n'); sent = True
                try:
                    out, err = process.communicate(timeout=2)
                    self.assertEqual(process.returncode, 0, err.decode(errors='replace'))
                    self.assertIn(b'DINIT_REACHED', data)
                    self.assertIn(b'ECHO:uart-v4-test', data)
                    self.assertIn('ttyS0 descriptors opened', (root / 'run/valence/uart-startup.log').read_text())
                finally:
                    if process.poll() is None:
                        process.kill(); process.communicate()
        finally:
            os.close(master); os.close(slave)


if __name__ == '__main__':
    unittest.main(verbosity=2)
