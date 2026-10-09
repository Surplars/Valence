#!/usr/bin/env python3
"""Small source-bound ABI checks; no kernel build or board execution."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import kernel_proc_contract as contract

HELPER = Path(__file__).resolve().parents[1] / 'debian_rootfs/dinit/uart-irq-init'


class ContractTests(unittest.TestCase):
    def test_helper_matches_independently_audited_kernel_name(self):
        self.assertEqual(contract.PROC_PATH, '/proc/tty/driver/serial_8250')
        self.assertIn('uart_proc=' + contract.PROC_PATH + '\n', HELPER.read_text())
        self.assertIn('"$uart_proc"', HELPER.read_text())

    def test_pinned_source_and_mutations(self):
        supplied = os.environ.get('VALENCE_LINUX_SOURCE')
        if not supplied:
            self.skipTest('Set VALENCE_LINUX_SOURCE for the exact pinned upstream-source check')
        source = Path(supplied)
        result = contract.validate(source, HELPER)
        self.assertEqual(result['proc_path'], '/proc/tty/driver/serial_8250')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in contract.SOURCES:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, destination)
            bad_helper = root / 'uart-irq-init'
            bad_helper.write_text(HELPER.read_text().replace('serial_8250', 'serial'))
            with self.assertRaisesRegex(RuntimeError, 'pathname differs'):
                contract.validate(root, bad_helper)
            for name in contract.SOURCES:
                original = (root / name).read_bytes()
                (root / name).write_bytes(original + b'\n/* mutation */\n')
                with self.subTest(source=name), self.assertRaisesRegex(RuntimeError, 'implementation changed'):
                    contract.validate(root, HELPER)
                (root / name).write_bytes(original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
