#!/usr/bin/env python3
"""Source-only negative controls; no compilation, generated model or simulation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding as b
sys.path.insert(0, str(b.GSIM))
from virtual_load_board import parse


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=HERE, prefix='.test-')
        self.root = Path(self.tmp.name)
        self.path = self.root / 'receipt.json'
        self.inputs = {'src/main/Example.scala': 'frozen-input'}
        self.lock = {'repository': 'test-only', 'revision': '0' * 40, 'minimum_clang_major': 19}
        self.state = {'schema': 'valence-fpga-next-board-evidence-v1', 'status': 'PASS_FPGA_NEXT_BOARD_SMOKE',
            'inputs': self.inputs, 'plan': b.v.expected_plan(False), 'toolchain': {**self.lock, 'compiler': 'test-compiler'},
            'artifacts': {}, 'steps': {}, 'tests': {}}
        for relative in ('model/BoardSocGsim.h', 'model/BoardSocGsim.fir', 'model/BoardSocGsim0.cpp',
                         'model/BoardSocGsim0.o', 'gc', 'firmware/rv64gc.elf', 'firmware/rv64gc.bin'):
            path = self.root / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text('synthetic ' + relative)
            self.state['artifacts'][relative] = b.sha(path)
        model = self.root / 'model'
        obj = model / 'BoardSocGsim0.o'
        fw = self.root / 'firmware'
        cxx = '/test-toolchain/clang++-19'
        commands = {
            'gc-build': list(map(str, ['riscv64-unknown-elf-gcc', *b.FETCH_FLAGS, '-T', b.ROOT / 'fpga/firmware/sample_app.ld',
                b.ROOT / 'fpga/firmware/rv64gc_smoke.S', '-o', fw / 'rv64gc.elf'])),
            'gc-bin': list(map(str, ['riscv64-unknown-elf-objcopy', '-O', 'binary', fw / 'rv64gc.elf', fw / 'rv64gc.bin'])),
            'elaborate': list(map(str, ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextBoardGsimMain', model,
                                      *self.state['plan']['parameters']])),
            'generate': ['/test-toolchain/gsim', '--threads=1', '--dir=' + str(model), str(model / 'BoardSocGsim.fir')],
            'compile-BoardSocGsim0': list(map(str, [cxx, *b.CXX_FLAGS, '-I' + str(model), '-c', obj.with_suffix('.cpp'), '-o', obj])),
            'gc-link': b.link_command(cxx, model, [obj], self.root / 'gc', 'fetch-permission'),
            'test-gc': list(map(str, [self.root / 'gc', fw / 'rv64gc.bin'])),
            'test-gc-negative': list(map(str, [self.root / 'gc', fw / 'rv64gc.bin', '--inject-mismatch'])),
        }
        for name, command in commands.items():
            text = {'test-gc': 'RV64GC_BOARD_PASS', 'test-gc-negative': 'firmware independent anchor/context failure'}.get(name, '')
            log = self.root / (name + '.log')
            log.write_text(text + '\n')
            code = int(name == 'test-gc-negative')
            self.state['steps'][name] = {'command': command, 'log': log.name, 'log_sha256': b.sha(log),
                                        'actual_exit': code, 'expected_exit': code, 'status': 'PASS'}
        self.sync()

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self):
        self.state['commands'] = list(self.state['steps'].values())
        self.state['tests'] = {name: self.state['steps']['test-' + name] for name in ('gc', 'gc-negative')
                              if 'test-' + name in self.state['steps']}

    def validate(self):
        self.path.write_text(json.dumps(self.state))
        state, model, objects = b.v.validate_model(self.path, self.inputs, 'test-compiler', self.lock, older_prefix=False)
        return b.historical_evidence(self.path, state, objects)

    def rejected(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            self.validate()

    def test_complete_positive(self):
        self.validate()

    def test_context_profile_drift(self):
        original = copy.deepcopy(self.state['plan'])
        for option in ('--virtual-ram-load-precheck', '--prechecked-data-flow', '--shared-fetch-pmp-relations',
                       '--independent-fetch-payload-capture', '--banked-instruction-data', '--load-order-older-retire',
                       '--dma-line-yield-cycles=4', '--lsu-entries=2', '--fetch-previous-packet'):
            with self.subTest(option=option):
                self.state['plan'] = {**original, 'parameters': original['parameters'] + [option]}
                self.rejected('model profile drift')
        for option in original['parameters']:
            with self.subTest(removed=option):
                self.state['plan'] = {**original, 'parameters': [x for x in original['parameters'] if x != option]}
                self.rejected('model profile drift')
        for key, value in [('fetch_previous_packet', False), ('fetch_previous_packet', 1),
                           ('passive_probes', 1), ('smoke_only', False), ('guest_suite', ['virtual'])]:
            with self.subTest(key=key):
                self.state['plan'] = {**original, key: value}
                self.rejected('model profile drift')

    def test_each_missing_model_file(self):
        for name in list(self.state['artifacts']):
            path = self.root / name
            data = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.validate()
            path.write_bytes(data)

    def test_each_changed_model_artifact(self):
        for name in self.state['artifacts']:
            path = self.root / name
            data = path.read_bytes()
            path.write_bytes(data + b' mutation')
            with self.subTest(name=name):
                self.rejected('artifact content drift')
            path.write_bytes(data)

    def test_extra_model_file(self):
        for name in ('unrecorded.txt', 'BoardSocGsim1.cpp', 'shadow.h', 'extra.o'):
            path = self.root / 'model' / name
            path.write_text('extra')
            with self.subTest(name=name):
                self.rejected('complete model file set')
            path.unlink()

    def test_extra_declared_product(self):
        file = self.root / 'extra'
        file.write_text('extra')
        self.state['artifacts']['extra'] = b.sha(file)
        self.rejected('complete model artifact inventory')

    def test_model_inputs_drift(self):
        self.state['inputs'] = {**self.inputs, 'unqualified': 'value'}
        self.rejected('source inventory drift')

    def test_compiler_drift(self):
        self.state['toolchain']['compiler'] = 'different compiler'
        self.rejected('toolchain/profile drift')

    def test_each_step_missing(self):
        original = copy.deepcopy(self.state['steps'])
        for name in original:
            with self.subTest(name=name):
                self.state['steps'] = {k: v for k, v in original.items() if k != name}
                self.sync()
                self.rejected('missing model step|complete model step')

    def test_each_command_altered(self):
        for name in self.state['steps']:
            command = self.state['steps'][name]['command']
            self.state['steps'][name]['command'] = command + ['--unqualified']
            self.sync()
            with self.subTest(name=name):
                self.rejected('recipe drift|historical roots')
            self.state['steps'][name]['command'] = command

    def test_each_log_changed(self):
        for name in self.state['steps']:
            path = self.root / (name + '.log')
            data = path.read_bytes()
            path.write_bytes(data + b'changed')
            with self.subTest(name=name):
                self.rejected('model log drift')
            path.write_bytes(data)

    def test_exit_bool_rejected(self):
        self.state['steps']['test-gc']['actual_exit'] = False
        self.sync()
        self.rejected('exit/status drift')

    def test_negative_success_rejected(self):
        record = self.state['steps']['test-gc-negative']
        path = self.root / record['log']
        path.write_text('firmware independent anchor/context failure\nRV64GC_BOARD_PASS\n')
        record['log_sha256'] = b.sha(path)
        self.sync()
        self.rejected('negative reported success')

    def test_sanitizer_rejected(self):
        record = self.state['steps']['test-gc']
        path = self.root / record['log']
        path.write_text('RV64GC_BOARD_PASS\nruntime error: mutation\n')
        record['log_sha256'] = b.sha(path)
        self.sync()
        self.rejected('sanitizer diagnostic')

    def test_oracle_guest_source_changes(self):
        for name in ('guest.S', 'oracle.h'):
            path = self.root / name
            path.write_text('unchanged independent source')
            sources = {name: b.sha(path)}
            b.verify_sources(self.root, sources)
            path.write_text('altered expectation')
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'source/oracle/guest drift'):
                b.verify_sources(self.root, sources)

    def test_same_recipes_preserved(self):
        command = b.link_command('clang++-19', Path('/m'), [Path('/m/BoardSocGsim0.o')], Path('/out'), 'virtual', Path('/fw'))
        self.assertNotIn('-DDDR_BENCHMARK_MODEL=1', command)
        self.assertIn('-DBACKEND_OWNER_COUNT=4', command)
        self.assertIn(str(b.GSIM / 'harness/virtual_load_board.cpp'), command)
        self.assertEqual(b.NEGATIVES['virtual'], [('signature', 'independent full-core signature mismatch'),
            ('trap', 'independent full-core trap provenance mismatch'), ('marker', 'ROI boundary order/uniqueness mismatch')])


class MetricTests(unittest.TestCase):
    def test_fetch_positive(self):
        result = b.metrics('fetch-permission', 'FETCH_PERMISSION_BOARD_PASS cycles=500 context_fprs=32 s_ecall=3 compressed_advances=2 ddr_reads=5', parse)
        self.assertEqual(result['s_ecall'], 3)

    def test_fetch_missing_or_wrong_trap(self):
        for value in ('2', '0'):
            with self.assertRaisesRegex(RuntimeError, 'witness missing'):
                b.metrics('fetch-permission', 'FETCH_PERMISSION_BOARD_PASS cycles=500 context_fprs=32 s_ecall=' + value + ' compressed_advances=2 ddr_reads=5', parse)

    def test_duplicate_virtual_record(self):
        with self.assertRaisesRegex(RuntimeError, 'record inventory drift'):
            b.metrics('virtual', 'VIRTUAL_BOARD_PASS total_cycles=1\nVIRTUAL_BOARD_PASS total_cycles=1', parse)


if __name__ == '__main__':
    unittest.main()
