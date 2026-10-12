#!/usr/bin/env python3
"""Optional53 export/staging contracts with a mock emitter; no hardware evidence."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
BOARD = SOURCE / 'fpga/next'
spec = importlib.util.spec_from_file_location('test_optional_entry', BOARD / 'board_eager_prefix.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class OptionalEntryTests(unittest.TestCase):
    def emit_mock(self, output):
        final = entry.final_module()
        exporter = final.exporter_module()
        wrapper = (BOARD / 'soc_top_fpga_next_ddr.sv').read_text()
        calls = []
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True)

        def emit(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[:4], ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'])
            self.assertEqual(len(command[5:]), 53)
            self.assertIn(entry.FLAG, command[5:])
            rtl = Path(command[4]); rtl.mkdir()
            instance = re.search(r'FpgaNextSocTop\s+u_soc\s*\((.*?)\);', wrapper, re.S).group(1)
            ports = re.findall(r'\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(', instance)
            (rtl / 'FpgaNextSocTop.sv').write_text('// MOCK EMITTER: NOT HARDWARE EVIDENCE\nmodule FpgaNextSocTop(' + ','.join('input ' + name for name in ports) + '); endmodule\n')
            (rtl / 'MockLeaf.sv').write_text('// MOCK LEAF: NOT HARDWARE EVIDENCE\n')
            (rtl / 'filelist.f').write_text('FpgaNextSocTop.sv\nMockLeaf.sv\n')
            for name in ('ValenceJtagDebugPort.sv', 'ValenceBscanDebugPort.sv'):
                (rtl / name).write_text('// MOCK EMITTER: NOT HARDWARE EVIDENCE\n')
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(entry, 'final_module', return_value=final), \
                mock.patch.object(final, 'exporter_module', return_value=exporter), \
                mock.patch.object(exporter.subprocess, 'run', side_effect=emit), \
                mock.patch.object(exporter.subprocess, 'check_output', return_value=head), \
                contextlib.redirect_stdout(io.StringIO()):
            entry.main(['--output', str(output), '--emit'])
        self.assertEqual(len(calls), 1)
        return json.loads((output / 'receipt.json').read_text())

    def test_mock_export_real_staging_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'export'
            self.emit_mock(output)
            result = entry.verify(output)
            self.assertEqual(result['status'], 'PASS_OPTIONAL53_EXPORT_BINDING_ONLY')
            self.assertEqual(result['default_native_option_count'], 52)
            self.assertFalse(result['physical_qualification'])
            self.assertFalse(result['synthesis_consumer_executed'])

    def test_cli_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'absent'
            for options in ([entry.FLAG], ['--reference'], ['--experimental-jtag-bscan=1'],
                            ['--out', 'other'], ['--emit=true'], ['--verify-export', str(output)]):
                with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    entry.main(['--output', str(output), *options])
                self.assertFalse(output.exists())

    def test_mutated_receipt_command_state_and_real_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'export'
            original = self.emit_mock(output)
            mutations = [
                lambda b: b['command'].remove(entry.FLAG),
                lambda b: b['profile'].update(eager_fetch_prefix_select=False),
                lambda b: b['source_sha256'].update({'fpga/next/board_eager_prefix.py': '0' * 64}),
                lambda b: b['native_mac_mode']['generics'].update(NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=0),
                lambda b: b.update(physical_qualification=True),
                lambda b: b['optional_eager_prefix_profile'].update(sha256='0' * 64),
            ]
            for index, mutate in enumerate(mutations):
                bad = copy.deepcopy(original); mutate(bad)
                (output / 'receipt.json').write_text(json.dumps(bad))
                with self.subTest(index=index), self.assertRaises(RuntimeError):
                    entry.verify(output)
            (output / 'receipt.json').write_text(json.dumps(original))
            path = output / 'board/require_jtag_chain.tcl'
            raw = path.read_bytes(); path.write_bytes(raw + b'\n# drift\n')
            with self.assertRaises(RuntimeError):
                entry.verify(output)
            path.write_bytes(raw)
            self.assertEqual(entry.verify(output)['status'], 'PASS_OPTIONAL53_EXPORT_BINDING_ONLY')


if __name__ == '__main__':
    unittest.main()
