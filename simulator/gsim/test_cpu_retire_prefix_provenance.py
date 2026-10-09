"""Host-only mutation tests. Subprocesses are forbidden; no receipts are edited.

The live closure tests use the actual r2 receipt when present. Mutations are
in-memory copies of that evidence; real file hashes are obtained in setUpClass.
"""
import copy
import contextlib
import io
import sys
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cpu_retire_prefix_provenance as proof
import cpu_retire_prefix_attribution as attribution
import cpu_retire_prefix_representative as representative


class CachedProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='prefix-proof-')
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.product = self.out / 'run'
        self.product.write_text('synthetic product')
        self.log = self.out / 'link.log'
        self.log.write_text('EXPECTED_PASS\n')
        self.argv = ['qualified-cxx', 'source.cpp', '-o', str(self.product)]
        self.record = dict(command=self.argv, actual_exit=0, expected_exit=0, anchor='EXPECTED_PASS',
            status='PASS', log=self.log.name, log_sha256=proof.sha(self.log),
            artifacts={self.product.name: proof.sha(self.product)})
        self.state = dict(steps={'link': self.record}, artifacts=dict(self.record['artifacts']))

    def check(self):
        with mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')):
            return proof.cached_step(self.out, self.state, 'link', self.argv, (self.product,), 0, 'EXPECTED_PASS')

    def test_valid_cached_step(self):
        self.assertIn('EXPECTED_PASS', self.check())

    def test_exit_status_anchor_command_mutations(self):
        for field, value in [('actual_exit', 1), ('status', 'FAIL'), ('expected_exit', 1),
                             ('anchor', None), ('command', ['/usr/bin/true'])]:
            with self.subTest(field=field):
                old = self.record[field]; self.record[field] = value
                with self.assertRaises(RuntimeError): self.check()
                self.record[field] = old

    def test_missing_required_product_even_if_both_maps_omit_it(self):
        self.record['artifacts'] = {}; self.state['artifacts'] = {}
        with self.assertRaises(RuntimeError): self.check()

    def test_extra_product_rejected(self):
        self.record['artifacts']['extra'] = '0' * 64
        with self.assertRaises(RuntimeError): self.check()

    def test_product_hash_and_global_map_must_agree(self):
        self.state['artifacts']['run'] = '0' * 64
        with self.assertRaises(RuntimeError): self.check()
        self.state['artifacts']['run'] = self.record['artifacts']['run']
        self.product.write_text('changed product')
        with self.assertRaises(RuntimeError): self.check()

    def test_missing_anchor_or_sanitizer_even_with_matching_hash(self):
        for text in ('no required anchor\n', 'EXPECTED_PASS\nruntime error: bad access\n',
                     'EXPECTED_PASS\nERROR: AddressSanitizer\n'):
            with self.subTest(text=text):
                self.log.write_text(text); self.record['log_sha256'] = proof.sha(self.log)
                with self.assertRaises(RuntimeError): self.check()

    def test_unhashed_log_change_and_path_escape(self):
        self.log.write_text('changed log')
        with self.assertRaises(RuntimeError): self.check()
        for path in ('../outside.log', str(self.log)):
            self.record['log'] = path
            with self.assertRaises(RuntimeError): self.check()

    def test_negative_cannot_also_report_success(self):
        with self.assertRaises(RuntimeError): proof.clean_log('rejected\nRV64GC_BOARD_PASS', 'rejected', True)

    def test_optimized_python_is_rejected_without_execution(self):
        source = Path(proof.__file__).read_text()
        code = compile(source, proof.__file__, 'exec', optimize=1)
        with self.assertRaisesRegex(RuntimeError, 'assertions enabled'):
            exec(code, {'__file__': proof.__file__})


class RepresentativeAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='prefix-resume-')
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.models = {label: dict(cxx='/qualified/clang++-19', compiler_version='qualified clang version 19',
            directory=str(self.out / ('model-' + label)), objects={}) for label in proof.LABELS}
        self.tools = {name: '/qualified/' + name for name in ('riscv64-unknown-elf-gcc',
            'riscv64-unknown-elf-objcopy', 'riscv64-unknown-elf-objdump', 'riscv64-unknown-elf-nm')}
        self.state = dict(steps={}, artifacts={}, cases={}, negative_controls={}, model_elaborations=0,
                         generated_model_compiles=0, production_changes=0, component_receipt_mutations=0)

    def add_step(self, name, text=''):
        contract = representative.execution_contracts(self.out, self.models, self.tools, self.state)[name]
        for p in contract['products']:
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text('synthetic product')
        log = self.out / (name + '.log'); log.write_text(text)
        artifacts = {str(p.relative_to(self.out)): proof.sha(p) for p in contract['products']}
        self.state['steps'][name] = dict(command=contract['argv'], actual_exit=contract['expected'],
            expected_exit=contract['expected'], anchor=contract['anchor'], status='PASS',
            artifacts=artifacts, log=log.name, log_sha256=proof.sha(log))
        self.state['artifacts'].update(artifacts)

    def check(self, terminal=False):
        with mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')), \
             mock.patch('subprocess.check_output', side_effect=AssertionError('execution forbidden')):
            return representative.audit(self.out, self.state, self.models, self.tools, terminal)

    def test_prepared_and_partial_positive_before_subprocess(self):
        self.check()
        self.add_step('steady-build'); self.check()
        self.add_step('tool-cxx', 'qualified clang version 19\n'); self.check()

    def test_missing_cached_product_global_and_step_maps_rejected(self):
        self.add_step('steady-build')
        self.state['steps']['steady-build']['artifacts'] = {}; self.state['artifacts'] = {}
        with self.assertRaises(RuntimeError): self.check()

    def test_cached_gc_anchor_and_failed_exit_rejected(self):
        self.add_step('off-rv64gc-run', 'RV64GC_BOARD_PASS\n')
        self.check()
        self.state['steps']['off-rv64gc-run']['actual_exit'] = 1
        with self.assertRaises(RuntimeError): self.check()
        self.state['steps']['off-rv64gc-run']['actual_exit'] = 0
        log = self.out / 'off-rv64gc-run.log'; log.write_text('no anchor')
        self.state['steps']['off-rv64gc-run']['log_sha256'] = proof.sha(log)
        with self.assertRaises(RuntimeError): self.check()

    def test_missing_build_dependencies_rejected(self):
        self.add_step('off-fetch-permission-run', 'FETCH_PERMISSION_BOARD_PASS\n')
        with self.assertRaises(RuntimeError): self.check()

    def test_unknown_steps_results_or_terminal_incompleteness_rejected(self):
        self.state['steps']['unexpected'] = {}
        with self.assertRaises(RuntimeError): self.check()
        self.state['steps'] = {}; self.state['cases']['unexpected'] = {}
        with self.assertRaises(RuntimeError): self.check()
        self.state['cases'] = {}
        with self.assertRaises(RuntimeError): self.check(terminal=True)

    def test_virtual_helper_rejects_prefix_and_path_overrides(self):
        with mock.patch.dict(os.environ, RISCV_PREFIX='/unqualified/riscv-'):
            with self.assertRaisesRegex(RuntimeError, 'RISCV_PREFIX'):
                representative.guest_tool_environment(self.tools)
        with mock.patch.dict(os.environ, RISCV_PREFIX='riscv64-unknown-elf-'), \
             mock.patch.object(representative.shutil, 'which', side_effect=lambda name: self.tools[name]):
            env = representative.guest_tool_environment(self.tools)
            self.assertEqual(env['RISCV_PREFIX'], 'riscv64-unknown-elf-')
        with mock.patch.dict(os.environ, RISCV_PREFIX='riscv64-unknown-elf-'), \
             mock.patch.object(representative.shutil, 'which', return_value='/unqualified/tool'):
            with self.assertRaisesRegex(RuntimeError, 'resolution drift'):
                representative.guest_tool_environment(self.tools)

    def test_cpp_quote_include_shadow_is_in_guard_inventory(self):
        self.assertIn('board_boot.cpp', proof.quote_dependencies())



class RealHotClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = proof.common.ROOT / 'build/gsim/cpu-retire-prefix-board-r2/receipt.json'
        if not cls.path.exists():
            raise unittest.SkipTest('actual r2 hot qualification not present')
        cls.before = proof.sha(cls.path)
        with mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')), \
             mock.patch('subprocess.check_output', side_effect=AssertionError('execution forbidden')):
            cls.valid = proof.HotInputs(cls.path)
        cls.original_load = staticmethod(proof.load)
        cls.original_read_text = staticmethod(Path.read_text)

    def setUp(self):
        self.state = copy.deepcopy(self.valid.state)
        self.components = {label: copy.deepcopy(m['state']) for label, m in self.valid.models.items()}
        self.text_changes = {}

    def validate(self):
        def load(path):
            return self.state if Path(path).resolve() == self.path else self.original_load(path)
        def validate_model(path, *args, **kwargs):
            label = next(label for label, m in self.valid.models.items() if m['receipt'] == Path(path))
            m = self.valid.models[label]
            return self.components[label], m['model'], m['objects']
        def read_text(path, *args, **kwargs):
            return self.text_changes.get(str(path), self.original_read_text(path, *args, **kwargs))
        # The initial positive pass hashes every real file. Memoizing only those
        # unchanged bytes makes dozens of receipt-only mutations inexpensive.
        def digest(path):
            key = str(Path(path).resolve())
            return self.valid.files[key] if key in self.valid.files else self.original_sha(path)
        self.original_sha = proof.sha
        with mock.patch.object(proof, 'load', side_effect=load), \
             mock.patch.object(proof.hot, 'validate_model', side_effect=validate_model), \
             mock.patch.object(proof, 'sha', side_effect=digest), \
             mock.patch.object(Path, 'read_text', read_text), \
             mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')), \
             mock.patch('subprocess.check_output', side_effect=AssertionError('execution forbidden')):
            return proof.HotInputs(self.path)

    def test_real_positive_and_cpp_driver_spelling(self):
        inputs = self.validate()
        self.assertIn('clang++', str(inputs.cxx))
        self.assertNotEqual(str(inputs.cxx), str(inputs.cxx.resolve()))
        for label in proof.LABELS:
            argv = attribution.link_command(inputs, label, Path('/output/observer.cpp'), Path('/output/run'))
            self.assertEqual(argv[0], str(inputs.cxx))
            self.assertEqual([x for x in argv if x.endswith('.o')], list(map(str, inputs.models[label]['objects'])))
            self.assertEqual([x for x in argv if x.startswith('-DBACKEND_OWNER_COUNT=')], ['-DBACKEND_OWNER_COUNT=4'])
            self.assertIn('-DRETIRE_PREFIX_ENABLED=' + str(int(label == 'on')), argv)
        self.assertEqual(proof.sha(self.path), self.before)

    def test_inventory_omission_rejected(self):
        for mode in ('empty', 'observer'):
            with self.subTest(mode=mode):
                self.state = copy.deepcopy(self.valid.state)
                if mode == 'empty': self.state['inputs'] = {}
                else: self.state['inputs'].pop('simulator/gsim/harness/cpu_retire_prefix_hot.cpp')
                with self.assertRaises(RuntimeError): self.validate()

    def test_hot_link_recipe_mutations(self):
        mutations = [lambda c: c.insert(1, '-I/unattested'), lambda c: c.insert(1, '/unattested.o'),
            lambda c: c.insert(1, '/unattested.cpp'), lambda c: c.insert(1, '-DUNREVIEWED=1'),
            lambda c: c.__setitem__(c.index('-DBACKEND_OWNER_COUNT=4'), '-DBACKEND_OWNER_COUNT=2'),
            lambda c: c.__setitem__(0, '/usr/bin/true')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.state = copy.deepcopy(self.valid.state)
                mutate(self.state['steps']['off-read-4096-link']['command'])
                with self.assertRaises(RuntimeError): self.validate()

    def test_hot_link_missing_evidence(self):
        for field in ('exit', 'artifacts', 'log_sha256'):
            with self.subTest(field=field):
                self.state = copy.deepcopy(self.valid.state)
                self.state['steps']['off-read-4096-link'].pop(field)
                with self.assertRaises((RuntimeError, KeyError)): self.validate()

    def test_hot_run_guest_exit_metrics_and_negative_anchor(self):
        mutations = [lambda s: s['steps']['off-read-4096-run']['command'].__setitem__(1, '/wrong-guest'),
            lambda s: s['steps']['off-read-4096-run'].__setitem__('exit', 1),
            lambda s: s['cases']['off']['read-4096']['result'].__setitem__('kernel_retired', -1),
            lambda s: s['steps'].pop('on-negative-upper-token'),
            lambda s: s['cases']['on'].pop('copy-8192')]
        for mutate in mutations:
            self.state = copy.deepcopy(self.valid.state); mutate(self.state)
            with self.assertRaises((RuntimeError, KeyError)): self.validate()
        self.state = copy.deepcopy(self.valid.state)
        for name, text in [('off-read-4096-run', 'missing success'),
                           ('off-negative-upper-token', 'no rejection anchor'),
                           ('off-read-4096-run', 'HOT_PASS\nruntime error: bad')]:
            self.text_changes = {str(self.path.parent / self.state['steps'][name]['log']): text}
            with self.assertRaises(RuntimeError): self.validate()

    def test_gc_recipe_mutations_even_when_duplicate_records_agree(self):
        mutations = [lambda c: c.insert(1, '-I/unattested'), lambda c: c.insert(1, '/unattested.cpp'),
            lambda c: c.insert(1, '/unattested.o'), lambda c: c.insert(1, '-DUNREVIEWED=1'),
            lambda c: c.__setitem__(c.index('-DBACKEND_OWNER_COUNT=4'), '-DBACKEND_OWNER_COUNT=2'),
            lambda c: c.__setitem__(0, '/usr/bin/true')]
        for mutate in mutations:
            self.components = {label: copy.deepcopy(m['state']) for label, m in self.valid.models.items()}
            c = self.components['off']; mutate(c['steps']['gc-link']['command'])
            c['commands'] = list(c['steps'].values())
            with self.assertRaises(RuntimeError): self.validate()

    def test_gc_duplicate_failure_and_missing_product_evidence(self):
        for mutation in ('duplicate', 'exit', 'product', 'test'):
            self.components = {label: copy.deepcopy(m['state']) for label, m in self.valid.models.items()}
            c = self.components['off']
            if mutation == 'duplicate': c['commands'] = []
            elif mutation == 'exit':
                c['steps']['gc-link']['actual_exit'] = 1; c['commands'] = list(c['steps'].values())
            elif mutation == 'product': c['artifacts'].pop('gc')
            else: c['tests'] = {}
            with self.assertRaises(RuntimeError): self.validate()

    def test_attribution_entrypoint_stops_at_reconstructed_link(self):
        class BoundaryReached(Exception):
            pass
        with tempfile.TemporaryDirectory(prefix='prefix-attribution-') as tmp:
            out = Path(tmp) / 'new'
            with mock.patch.object(sys, 'argv', ['attribution', '--receipt', str(self.path), '--out', str(out)]), \
                 mock.patch('subprocess.check_output', return_value=self.valid.compiler_version + '\n'), \
                 mock.patch('subprocess.run', side_effect=BoundaryReached) as boundary:
                with self.assertRaises(BoundaryReached): attribution.main()
            self.assertEqual(boundary.call_count, 1)
            self.assertEqual(boundary.call_args.args[0], attribution.link_command(self.valid, 'off', out / 'observer.cpp', out / 'off-run'))
            self.assertEqual(proof.sha(self.path), self.before)

    def test_representative_prepare_entrypoint_is_read_only_of_inputs(self):
        with tempfile.TemporaryDirectory(prefix='prefix-representative-') as tmp:
            out = Path(tmp) / 'new'
            with mock.patch.dict(os.environ, PATH=str(self.valid.cxx.parent) + os.pathsep + os.environ['PATH']), \
                 mock.patch.object(sys, 'argv', ['representative', '--prepare', '--hot-receipt', str(self.path), '--out', str(out)]), \
                 mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')), \
                 mock.patch('subprocess.check_output', side_effect=AssertionError('execution forbidden')), \
                 contextlib.redirect_stdout(io.StringIO()):
                representative.main()
            state = json.loads((out / 'receipt.json').read_text())
            self.assertEqual(state['status'], 'PREPARED_NOT_EXECUTED')
            self.assertEqual(state['steps'], {})
            self.assertEqual(proof.sha(self.path), self.before)

    def test_representative_fresh_positive_no_subprocess(self):
        bindir = Path(self.valid.cxx).parent
        with mock.patch.dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']), \
             mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')), \
             mock.patch('subprocess.check_output', side_effect=AssertionError('execution forbidden')):
            files, inventory, models, tools = representative.provenance(self.path)
        self.assertEqual(inventory, self.valid.board_inputs)
        self.assertEqual(models['off']['cxx'], str(self.valid.cxx))
        self.assertEqual(list(models['off']['objects']), list(map(str, self.valid.models['off']['objects'])))
        self.assertEqual(files[str(self.path)], self.before)
        self.assertEqual(len(tools), 4)


if __name__ == '__main__':
    unittest.main()
