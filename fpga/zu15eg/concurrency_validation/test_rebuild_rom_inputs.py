#!/usr/bin/env python3
"""Host fixtures for exact-ROM recovery and fixed-IP reuse; no vendor execution."""
import hashlib
import json
import shutil
import subprocess
from types import SimpleNamespace
from unittest import mock
import rebuild_rom_inputs as rebuild
from pathlib import Path
import tempfile
import unittest
from rebuild_rom_inputs import FIXED_FOLDERS, prepare_rom, verify_fixed

sha = lambda data: hashlib.sha256(data).hexdigest()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.expected = {'sha256': {}}
        for name in FIXED_FOLDERS:
            path = self.root / name / 'fixture'; path.parent.mkdir(parents=True); path.write_bytes(name.encode())
            self.expected['sha256'][path.relative_to(self.root).as_posix()] = sha(path.read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def test_all_fixed_files_match(self):
        self.assertEqual(len(verify_fixed(self.root, self.expected)), len(FIXED_FOLDERS))

    def test_changed_fixed_file_rejected(self):
        (self.root / 'mig/fixture').write_bytes(b'changed')
        with self.assertRaises(RuntimeError): verify_fixed(self.root, self.expected)

    def test_extra_fixed_file_rejected(self):
        (self.root / 'mig/extra').write_bytes(b'extra')
        with self.assertRaises(RuntimeError): verify_fixed(self.root, self.expected)

    def test_missing_fixed_file_rejected(self):
        (self.root / 'mig/fixture').unlink()
        with self.assertRaises(RuntimeError): verify_fixed(self.root, self.expected)

    def rom(self):
        data = b'exact test ROM\0'; source = self.root / 'source.bin'; source.write_bytes(data)
        words = [int.from_bytes(data.ljust(131072, b'\0')[n:n+4], 'little') for n in range(0, 131072, 4)]
        coe = ('memory_initialization_radix=16;\nmemory_initialization_vector=\n' +
               ',\n'.join('%08x' % w for w in words) + ';\n').encode()
        expected = {'sha256': {'firmware/bootrom.bin': sha(data), 'firmware/bootrom.coe': sha(coe)},
                    'rom_word_audit': {'binaryBytes': len(data)}}
        return source, expected, data, coe

    def test_exact_recovery_preserves_all_coe_words(self):
        source, expected, data, coe = self.rom(); output = self.root / 'fresh'
        prepare_rom(source, output, expected)
        self.assertEqual((output / 'firmware/bootrom.bin').read_bytes(), data)
        self.assertEqual((output / 'firmware/bootrom.coe').read_bytes(), coe)
        self.assertFalse((output / 'ip-build').exists())

    def test_wrong_rom_rejected_without_output(self):
        source, expected, _, _ = self.rom(); source.write_bytes(b'wrong')
        with self.assertRaises(RuntimeError): prepare_rom(source, self.root / 'fresh', expected)
        self.assertFalse((self.root / 'fresh').exists())

    def test_existing_output_preserved(self):
        source, expected, _, _ = self.rom(); output = self.root / 'fresh'; output.mkdir()
        (output / 'keep').write_text('unchanged')
        with self.assertRaises(RuntimeError): prepare_rom(source, output, expected)
        self.assertEqual((output / 'keep').read_text(), 'unchanged')

    def test_wrong_coe_contract_rejected(self):
        source, expected, _, _ = self.rom(); expected['sha256']['firmware/bootrom.coe'] = '0' * 64
        with self.assertRaises(RuntimeError): prepare_rom(source, self.root / 'fresh', expected)
        self.assertFalse((self.root / 'fresh').exists())


    def assembly_fixture(self):
        repo = self.root / 'repo'; repo.mkdir()
        def put(name, data):
            path = repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); return path
        main = put('src/main/scala/Fixture.scala', b'class Fixture\n')
        board = put('fpga/fixture.sv', b'module Fixture; endmodule\n')
        original_repo = Path(__file__).resolve().parents[3]
        put('fpga/firmware/audit_bootrom.py', (original_repo / 'fpga/firmware/audit_bootrom.py').read_bytes())
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        helpers = self.root / 'helpers'; helpers.mkdir()
        (helpers / 'integrated-source-sha256.json').write_text(json.dumps({'src/main/scala/Fixture.scala': sha(main.read_bytes())}))
        rtl = self.root / 'rtl'; rtl.mkdir(); shutil.copy2(board, rtl / 'Fixture.sv')
        contract = {'variants': {'integrated-off': {'cpu_precheck': False, 'parameters_after_output': [],
            'rtl_sha256': {'Fixture.sv': sha(board.read_bytes())}}},
            'source_map': {'board/Fixture.sv': {'repo_path': 'fpga/fixture.sv', 'sha256': sha(board.read_bytes())}}}
        data = b'Valence Bootrom V0.1\r\n\0monitor> \0locked> \0EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n\0'
        binary = self.root / 'rom.bin'; binary.write_bytes(data)
        words = [int.from_bytes(data.ljust(131072, b'\0')[n:n+4], 'little') for n in range(0, 131072, 4)]
        coe = ('memory_initialization_radix=16;\nmemory_initialization_vector=\n' +
               ',\n'.join('%08x' % w for w in words) + ';\n').encode()
        expected = {'sha256': {**self.expected['sha256'], 'firmware/bootrom.bin': sha(data),
                              'firmware/bootrom.coe': sha(coe)}, 'rom_word_audit': {'binaryBytes': len(data)}}
        output = self.root / 'candidate'; prepare_rom(binary, output, expected)
        bmg = output / 'ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0'; bmg.mkdir(parents=True)
        (bmg / 'blk_mem_gen_0.mif').write_text(''.join(format(w, '032b')+'\n' for w in words))
        (bmg / 'blk_mem_gen_0.dcp').write_bytes(b'synthetic nonempty checkpoint, not vendor evidence')
        xci = output / 'ip-build/board_ip.srcs/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.xci'
        xci.parent.mkdir(parents=True); xci.write_text('synthetic XCI')
        args = SimpleNamespace(output=output, repo=repo, fixed=self.root, rtl=rtl, commit=commit, variant='integrated-off')
        return args, expected, contract, helpers, bmg

    def test_complete_synthetic_assembly_records_fresh_provenance(self):
        args, expected, contract, helpers, _ = self.assembly_fixture()
        with mock.patch.object(rebuild, 'HERE', helpers): rebuild.assemble(args, expected, contract)
        state = json.loads((args.output / 'inputs.json').read_text())
        self.assertFalse(state['historical_rom_dcp_reused'])
        self.assertEqual(state['rom_word_audit']['mifWordsMatched'], 32768)
        self.assertEqual(state['fixed_ip_files_reused_by_exact_hash'], len(FIXED_FOLDERS))
        self.assertFalse(state['bit_generated'])

    def test_mif_mutation_rejected_before_fixed_ip_copy(self):
        args, expected, contract, helpers, bmg = self.assembly_fixture()
        mif = bmg / 'blk_mem_gen_0.mif'; data = mif.read_text()
        mif.write_text(('1' if data[0] == '0' else '0') + data[1:])
        with mock.patch.object(rebuild, 'HERE', helpers), self.assertRaises(ValueError):
            rebuild.assemble(args, expected, contract)
        self.assertFalse((args.output / 'mig').exists())
        self.assertFalse((args.output / 'inputs.json').exists())


if __name__ == '__main__':
    unittest.main()
