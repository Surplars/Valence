"""Packaging-only tests with synthetic text; not RTL elaboration/synthesis evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('local_runner', HERE / 'run_local.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PackageTests(unittest.TestCase):
    def test_round_trip_and_tamper(self):
        with tempfile.TemporaryDirectory(prefix='ooc package ') as temp:
            root = Path(temp)
            emission = root / 'emission'
            emission.mkdir()
            identity = {'schema': 'valence-combined-a1-fabric-ooc-v1',
                        'top': 'CombinedA1FabricTimingTop', 'part': 'xczu15eg-ffvb1156-2-i',
                        'mode': 'candidate'}
            (emission / 'ooc-identity.json').write_text(json.dumps(identity))
            (emission / 'Top.sv').write_text('module CombinedA1FabricTimingTop(); endmodule\n')
            output = root / 'portable package'
            command = [sys.executable, str(HERE / 'package_rtl.py'), '--emission', str(emission), '--out', str(output)]
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(runner.verify(output)['mode'], 'candidate')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (output / 'rtl/Top.sv').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                runner.verify(output)

    def test_external_memory_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'ooc-identity.json').write_text(json.dumps({
                'schema': 'valence-combined-a1-fabric-ooc-v1', 'top': 'CombinedA1FabricTimingTop',
                'part': 'xczu15eg-ffvb1156-2-i', 'mode': 'candidate'}))
            (root / 'Top.sv').write_text('module CombinedA1FabricTimingTop(); initial $readmemh("/old/rom", m); endmodule')
            result = subprocess.run([sys.executable, str(HERE / 'package_rtl.py'), '--emission', str(root),
                                     '--out', str(root / 'output')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unexpected memory file dependency', result.stderr)
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
