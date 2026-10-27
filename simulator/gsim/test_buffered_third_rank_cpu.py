import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import buffered_third_rank_cpu as runner


class CpuGates(unittest.TestCase):
    def fixture(self):
        def preamble(names):
            annotations = [{'class': 'firrtl.transforms.DedupGroupAnnotation', 'target': '~|' + n, 'group': n}
                           for n in names]
            return ('FIRRTL version 6.0.0\ncircuit X :%[' + json.dumps(annotations) + ']\n').encode()
        def block(name, body):
            return ('  module ' + name + ' :\n    input clock : Clock\n' + body).encode()
        def prf(count):
            text = '    output io : { flip address : UInt<6>[' + str(count) + ']}\n'
            for bank in range(2):
                text += f'    cmem banks_{bank} : UInt<64>[48]\n'
                text += f'      write mport W{bank} = banks_{bank}[a], clock\n'
                for n in range(count):
                    text += f'    read mport R{bank}_{n} = banks_{bank}[a{n}], clock\n'
            return block('OwnerBankedPhysicalRegisterFile', text)
        names = ['IntegerBackend', 'BankedIssuePayload', runner.raw.TOP, 'RenameRob']
        a = {n: block(n, '    node x = UInt<1>(0h0)\n') for n in names}
        b = {n: block(n, '    node x = UInt<1>(0h1)\n' if n != 'RenameRob' else '    node x = UInt<1>(0h0)\n') for n in names}
        a['OwnerBankedPhysicalRegisterFile'], b['OwnerBankedPhysicalRegisterFile'] = prf(14), prf(15)
        for n in runner.ALLOW_REMOVED:
            a[n] = block(n, '')
        for n in runner.ALLOW_ADDED:
            b[n] = block(n, '')
        return (preamble(sorted(runner.ALLOW_REMOVED)), a), (preamble(sorted(runner.ALLOW_ADDED)), b)

    def run_gate(self, pair):
        with patch.object(runner, 'modules', side_effect=pair):
            return runner.module_gate(Path('control'), Path('candidate'))

    def test_expected_delta(self):
        self.assertEqual(self.run_gate(self.fixture())['added_modules'], sorted(runner.ALLOW_ADDED))

    def reject(self, change):
        pair = copy.deepcopy(self.fixture())
        change(pair)
        with self.assertRaises(RuntimeError):
            self.run_gate(pair)

    def test_unrelated_body(self):
        self.reject(lambda p: p[1][1].__setitem__('RenameRob', p[1][1]['RenameRob'] + b'    node bad = UInt<1>(0h1)\n'))

    def test_unexpected_module(self):
        self.reject(lambda p: p[1][1].__setitem__('Unapproved', b'  module Unapproved :\n'))

    def test_missing_module(self):
        self.reject(lambda p: p[1][1].pop('ThirdMemoryPreparationRank'))

    def test_prf_geometry(self):
        self.reject(lambda p: p[1][1].__setitem__('OwnerBankedPhysicalRegisterFile',
            p[1][1]['OwnerBankedPhysicalRegisterFile'].replace(b'UInt<64>[48]', b'UInt<64>[64]')))

    def test_extra_read(self):
        self.reject(lambda p: p[1][1].__setitem__('OwnerBankedPhysicalRegisterFile',
            p[1][1]['OwnerBankedPhysicalRegisterFile'] + b'    read mport extra = banks_0[a], clock\n'))

    def test_annotation_not_blindly_stripped(self):
        a, b = self.fixture()
        bad = b[0].replace(b'firrtl.transforms.DedupGroupAnnotation', b'UnexpectedAnnotation', 1)
        with self.assertRaises(RuntimeError):
            self.run_gate((a, (bad, b[1])))

    def test_non_annotation_preamble(self):
        a, b = self.fixture()
        with self.assertRaises(RuntimeError):
            self.run_gate((a, (b[0].replace(b'circuit X', b'circuit Other'), b[1])))

    def test_parameters(self):
        old = {'config': {'robEntries': '16'}, 'core': {'robEntries': '16'}}
        a = {k: {**v, 'bufferedThirdRankLoadProof': 'false'} for k, v in old.items()}
        b = {k: {**v, 'bufferedThirdRankLoadProof': 'true'} for k, v in old.items()}
        runner.parameter_gate(a, b, old)
        b['core']['robEntries'] = '15'
        with self.assertRaises(RuntimeError):
            runner.parameter_gate(a, b, old)

    def test_host_adapters_restore_exact_original(self):
        with tempfile.TemporaryDirectory() as directory:
            result = runner.host_adapters(Path(directory))
            self.assertTrue(result['vm']['inverse_original_bytes_exact'])
            self.assertTrue(result['load']['inverse_original_bytes_exact'])
            self.assertEqual(result['vm']['allowed_exact_edits'], 4)
            self.assertEqual(result['load']['allowed_exact_edits'], 5)


if __name__ == '__main__':
    unittest.main()
