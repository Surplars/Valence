"""Runner guards only: mocks do not qualify native DRP or measure runtime."""
import contextlib
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
    def run_case(self, corrupt=None):
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
                    RUNNER.PASS+'\n'+'BOARD_DRP_VERIFIED lane=0\n'*4,
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
                       ['run_board_profiles.py', str(root/'out'), '--vivado-bin', str(binary)]), contextlib.redirect_stdout(io.StringIO()):
                try:
                    RUNNER.main()
                except SystemExit:
                    pass
            receipt = json.loads((root/'out/receipt.json').read_text())
            return receipt, calls

    def test_full_guard_success(self):
        receipt, calls = self.run_case()
        self.assertEqual(receipt['status'], 'PASS_NATIVE_EXACT_195_155_ROUNDTRIP')
        self.assertEqual(len(calls), 5)
        self.assertNotIn('behavioral_primitives.sv', ' '.join(map(str, calls)))
        self.assertIn('VALENCE_USE_UNISIM', calls[0])
        self.assertIn('unisims_ver', calls[1])
        self.assertTrue(all('board195155' in c for c in calls[2:]))

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
