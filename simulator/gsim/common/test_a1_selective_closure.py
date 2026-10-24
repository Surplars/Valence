#!/usr/bin/env python3
"""Fast independent negative controls for selective-runner input closure."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

RUNNER = Path(__file__).with_name('a1_selective_lowering.py')


class ClosureTests(unittest.TestCase):
    def rejected(self, mutate, diagnostic):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'model'
            (model / 'rtl').mkdir(parents=True)
            rtl = model / 'rtl' / 'Unused.sv'
            rtl.write_text('module Unused; endmodule\n')
            guest = model / 'guest.hex'
            guest.write_text('00000000\n')
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            receipt = dict(status='PASS_A1_RUNTIME_NATIVE_EPOCH', source_sha256={},
                           emitted_rtl_sha256={str(rtl): sha(rtl)},
                           guest={'artifacts': {'guest.hex': sha(guest)}})
            (model / 'receipt.json').write_text(json.dumps(receipt))
            mutate(model)
            result = subprocess.run(['python3', str(RUNNER), '--out', str(Path(tmp)/'out'),
                                     '--model-dir', str(model), '--kind', 'epoch',
                                     '--sv2v', 'must-not-execute'], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(diagnostic, result.stderr)

    def test_missing_unreferenced_rtl(self):
        self.rejected(lambda m: (m/'rtl/Unused.sv').unlink(), 'RTL inventory differs')

    def test_added_rtl(self):
        self.rejected(lambda m: (m/'rtl/Added.sv').write_text('module Added; endmodule'),
                      'RTL inventory differs')

    def test_guest_tampering(self):
        self.rejected(lambda m: (m/'guest.hex').write_text('ffffffff\n'),
                      'guest/model artifact drift')


if __name__ == '__main__':
    unittest.main()
