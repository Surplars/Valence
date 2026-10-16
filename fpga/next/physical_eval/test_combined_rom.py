"""Synthetic graph mocks, not captured Vivado evidence or hardware qualification."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter
import unittest

HERE = Path(__file__).resolve().parent


class MockRomGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-ROM-graph-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'firmware').mkdir()
        (self.root/'synthesis').mkdir()
        (self.root/'synthesis/post_synth_unconstrained.dcp').write_text('MOCK NOT A DCP')
        block = b''.join((i ^ 0x536CA914).to_bytes(4, 'little') for i in range(1024))
        raw = block*32
        (self.root/'firmware/bootrom.bin').write_bytes(raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        self.dump = self.root/'mock-init.tsv'
        props = dict(DOA_REG='0', DOB_REG='0', READ_WIDTH_A='36', READ_WIDTH_B='36')
        bits = int.from_bytes(block, 'little')
        for i in range(128): props[f'INIT_{i:02X}'] = f"256'h{(bits>>(256*i))&((1<<256)-1):064X}"
        for i in range(16): props[f'INITP_{i:02X}'] = "256'h"+'0'*64
        self.props = props
        graph = ['NET\tgnd\tGROUND', 'NET\tvcc\tPOWER']
        for i in range(1, 15): graph.append(f'NET\ta{i}\tSIGNAL')
        for side in ('a', 'b'):
            for i in range(15):
                net = ('gnd' if side == 'a' else 'vcc') if i == 0 else f'a{i}'
                graph.append(f'PORT\taddr{side}[{i}]\tIN\t{net}')
            graph += [f'PORT\ten{side}\tIN\tvcc', f'PORT\tclk{side}\tIN\tgnd']
            for i in range(32):
                graph += [f'NET\tout{side}{i}\tSIGNAL', f'PORT\tdout{side}[{i}]\tOUT\tout{side}{i}']
        graph.append('CELL\tram\tRAMB36E2')
        graph += [f'PROP\tram\t{k}\t{v}' for k,v in props.items()]
        for side in ('a', 'b'):
            bus = 'ADDRARDADDR' if side == 'a' else 'ADDRBWRADDR'
            for i in range(15):
                net = 'gnd' if i < 5 else ('gnd' if side == 'a' else 'vcc') if i == 5 else f'a{i-5}'
                graph.append(f'PIN\tram\t{bus}[{i}]\tIN\t{net}')
            enable = 'ENARDEN' if side == 'a' else 'ENBWREN'
            graph.append(f'PIN\tram\t{enable}\tIN\tvcc')
            pin = 'DOUTADOUT' if side == 'a' else 'DOUTBDOUT'
            graph += [f'PIN\tram\t{pin}[{i}]\tOUT\tout{side}{i}' for i in range(32)]
        self.graph = Path(str(self.dump)+'.graph.tsv')
        self.graph.write_text('\n'.join(graph)+'\n')
        self.dump.write_text('CELL\tram\tRAMB36E2\n'+''.join(f'{k}\t{v}\n' for k,v in props.items()))

    def run_decoder(self):
        return subprocess.run([sys.executable, '-B', str(HERE/'verify_combined_rom_graph.py'),
            str(self.root), str(self.dump), '--rom-sha256', self.digest, '--padded-sha256', self.digest],
            capture_output=True, text=True)

    def test_mock_full_word_reconstruction(self):
        result = self.run_decoder()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['bram_count'], 1)
        self.assertTrue(report['all_live_ram_accounted'])
        self.assertIn('temporal read behavior', report['unverified'])

    def test_empty_generic_ram_init_placeholder_is_normalized(self):
        with self.graph.open('a') as stream: stream.write('PROP\tram\tINIT\t\n')
        result = self.run_decoder()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonempty_generic_ram_init_rejected(self):
        for value in ("1'b0", ' ', '0'):
            original = self.graph.read_text()
            self.graph.write_text(original+'PROP\tram\tINIT\t'+value+'\n')
            result = self.run_decoder()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('nonempty_RAM_generic_INIT', result.stderr)
            self.graph.write_text(original)

    def test_missing_init_and_parity_properties_still_rejected(self):
        original = self.graph.read_text()
        for key in ('INIT_00', 'INITP_00'):
            self.graph.write_text(original.replace(f'PROP\tram\t{key}\t{self.props[key]}\n', '')+'PROP\tram\tINIT\t\n')
            self.assertNotEqual(self.run_decoder().returncode, 0)

    def test_other_property_mismatch_still_rejected(self):
        self.graph.write_text(self.graph.read_text()+'PROP\tram\tINIT\t\nPROP\tram\tUNEXPECTED\t\n')
        result = self.run_decoder()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dump_graph_RAM_properties', result.stderr)

    def test_missing_output_bit_rejected(self):
        self.graph.write_text(self.graph.read_text().replace('PORT\tdouta[0]\tOUT\touta0\n', ''))
        self.assertNotEqual(self.run_decoder().returncode, 0)

    def test_changed_init_in_both_dump_and_graph_rejected(self):
        key = self.props['INIT_00']
        replacement = key[:-1]+('0' if key[-1] != '0' else '1')
        for path in (self.graph, self.dump): path.write_text(path.read_text().replace(key, replacement))
        self.assertNotEqual(self.run_decoder().returncode, 0)

    def test_wrong_output_mapping_rejected(self):
        self.graph.write_text(self.graph.read_text().replace('PORT\tdouta[0]\tOUT\touta0', 'PORT\tdouta[0]\tOUT\touta2'))
        self.assertNotEqual(self.run_decoder().returncode, 0)

    def test_extra_unreachable_ram_rejected(self):
        with self.graph.open('a') as stream:
            stream.write('CELL\textra\tRAMB36E2\n')
            stream.write(''.join(f'PROP\textra\t{k}\t{v}\n' for k,v in self.props.items()))
        with self.dump.open('a') as stream:
            stream.write('CELL\textra\tRAMB36E2\n')
            stream.write(''.join(f'{k}\t{v}\n' for k,v in self.props.items()))
        result = self.run_decoder()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unreachable_ROM_RAM', result.stderr)

    def test_unsupported_extra_ram_rejected(self):
        with self.graph.open('a') as stream: stream.write('CELL\textra\tRAMB18E2\n')
        self.assertNotEqual(self.run_decoder().returncode, 0)


class RecoveryDecoderRoutingTests(unittest.TestCase):
    def test_only_explicit_recovery_routes_decoder_to_validator(self):
        tcl = tkinter.Tcl()
        tcl.eval((HERE/'combined_runtime.tcl').read_text())
        tcl.eval('proc combined_exec {command} {return $command}')
        tcl.eval('set ::r3_config [dict create python_mode native python_command python]')
        plain = tcl.call('combined_python', '/mock/package', 'verify_combined_rom_graph.py', ('input',))
        self.assertEqual(plain[2], '/mock/package/scripts/verify_combined_rom_graph.py')
        tcl.call('set', '::combined_recovery_validator', '/mock/validator')
        tcl.call('set', '::combined_recovery_options', ('--recovery', '/mock/recovery.json'))
        routed = tcl.call('combined_python', '/mock/package', 'verify_combined_rom_graph.py', ('input',))
        self.assertEqual(routed[2], '/mock/validator/fpga/next/physical_eval/verify_combined_rom_graph.py')
        self.assertEqual(routed[3:], ('input',))
        gate = tcl.call('combined_python', '/mock/package', 'verify_combined_package.py', ('input',))
        self.assertEqual(gate[2], '/mock/package/scripts/verify_combined_package.py')


if __name__ == '__main__':
    unittest.main()
