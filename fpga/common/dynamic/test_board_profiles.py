"""Runner guards only: mocks do not qualify native DRP or measure runtime."""
import contextlib
import hashlib
import re
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('board_runner', Path(__file__).with_name('run_board_profiles.py'))
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RunnerGuards(unittest.TestCase):
    def run_case(self, corrupt=None, profile='195155'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root/'vendor/bin'
            binary.mkdir(parents=True)
            for tool in ('xvlog', 'xelab', 'xsim'):
                (binary/tool).write_text('not executed')
            glbl = binary.parent/'data/verilog/src/glbl.v'
            glbl.parent.mkdir(parents=True)
            glbl.write_text('mock vendor source, never compiled')
            logs = ['', 'Vivado Simulator v2025.2\n',
                    RUNNER.PASS_MARKERS[profile]+'\n'+'BOARD_DRP_VERIFIED lane=0\n'*4,
                    'Fatal: BOARD_DRP_WRITE_IMAGE\n',
                    'Fatal: UNISIM_FREQUENCY_OR_INDEPENDENCE\n']
            if corrupt is not None:
                index, text = corrupt
                logs[index] = text
            calls = []

            class Process:
                def __init__(self, command, **kw):
                    calls.append(command)
                    kw['stdout'].write(logs[len(calls)-1])
                def wait(self, timeout):
                    assert timeout == 120
                    return 0

            with patch.object(RUNNER.subprocess, 'Popen', Process), patch('sys.argv',
                       ['run_board_profiles.py', str(root/'out'), '--vivado-bin', str(binary), '--profile', profile]), contextlib.redirect_stdout(io.StringIO()):
                try:
                    RUNNER.main()
                except SystemExit:
                    pass
            receipt = json.loads((root/'out/receipt.json').read_text())
            return receipt, calls

    def test_no_load_output_mapping_only(self):
        domain = Path(__file__).with_name('native_dynamic_clock_domain.sv').read_text()
        mappings = re.findall(r'\.(\w+)\(unused_mmcm_outputs\[(\d+)\]\)', domain)
        self.assertEqual([name for name, _ in mappings], [
            'CDDCDONE', 'CLKFBOUTB', 'CLKFBSTOPPED', 'CLKINSTOPPED', 'CLKOUT0B',
            'CLKOUT1', 'CLKOUT1B', 'CLKOUT2', 'CLKOUT2B', 'CLKOUT3', 'CLKOUT3B',
            'CLKOUT4', 'CLKOUT5', 'CLKOUT6', 'PSDONE'])
        self.assertEqual([int(index) for _, index in mappings], list(range(15)))
        self.assertEqual(domain.count('unused_mmcm_outputs'), 16)  # Declaration plus15 outputs, no load.
        original = domain.replace('    // Explicit no-load sinks for unused primitive outputs; no control/clock fanout.\n    wire [14:0] unused_mmcm_outputs;\n', '')
        original = re.sub(r",\n        \.CDDCDONE\(unused_mmcm_outputs\[0\]\).*?\.PSDONE\(unused_mmcm_outputs\[14\]\)", '', original, flags=re.S)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         'e9bc1466fdfc3cceefb5af66fb1873a88c267643b7650a74c8f81a5bba64c5c4')

    def test_full_guard_success(self):
        receipt, calls = self.run_case()
        self.assertEqual(receipt['status'], 'PASS_NATIVE_EXACT_195_155_ROUNDTRIP')
        self.assertEqual(len(calls), 5)
        self.assertNotIn('behavioral_primitives.sv', ' '.join(map(str, calls)))
        self.assertIn('VALENCE_USE_UNISIM', calls[0])
        self.assertIn('unisims_ver', calls[1])
        self.assertTrue(all('board195155' in c for c in calls[2:]))

    def test_exact125_profile(self):
        receipt, calls = self.run_case(profile='125125')
        self.assertEqual(receipt['status'], 'PASS_NATIVE_EXACT_125_125_ROUNDTRIP')
        self.assertEqual(receipt['profiles']['cpu125'], '0x08280a')
        self.assertEqual(receipt['profiles']['fabric125'], '0x08280a')
        self.assertTrue(all('board125125' in c for c in calls[2:]))

    def test_each_stage_warning_rejected(self):
        for index in range(5):
            with self.subTest(index=index):
                self.assertEqual(self.run_case((index, 'WARNING: native notice\n'))[0]['status'], 'FAIL')

    def test_partial_readback_rejected(self):
        self.assertEqual(self.run_case((2, RUNNER.PASS+'\nBOARD_DRP_VERIFIED lane=0\n'))[0]['status'], 'FAIL')

    def test_wrong_negative_oracle_rejected(self):
        self.assertEqual(self.run_case((3, 'Fatal: UNRELATED\n'))[0]['status'], 'FAIL')

    def test_native_version_required(self):
        self.assertEqual(self.run_case((1, 'Vivado Simulator v2025.1\n'))[0]['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
