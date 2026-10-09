#!/usr/bin/env python3
"""Source-only synthetic contract tests. Never compiles or executes a guest/model."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.dont_write_bytecode = True
import binding as b
import run_fixture as runner
# Reuse all frozen model/history tests, but direct their synthetic files ONLY here.
original = sys.modules['binding']
sys.modules['binding'] = b.history
try:
    inherited = b.load('dma_pmp_shared_contract_tests', b.GSIM / 'fixtures/fetch_context_qualification_v1/test_validation.py')
finally:
    sys.modules['binding'] = original
inherited.HERE = b.HERE


class AdditionalProfileTests(inherited.BindingTests):
    def test_unknown_profile_fields_rejected(self):
        for key, value in [('unknown', True), ('fetch_previous_packet_extra', False), ('lsu_entries', 4)]:
            old = copy.deepcopy(self.state['plan'])
            self.state['plan'][key] = value
            with self.subTest(key=key):
                self.rejected('model profile drift')
            self.state['plan'] = old

    def test_symlink_artifact_rejected(self):
        path = self.root / 'model/BoardSocGsim0.o'
        copy = self.root / 'backing'
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        self.rejected('nonregular|symlink')

    def test_running_checkpoint_rejected(self):
        self.state['status'] = 'RUNNING'
        self.rejected('completed board smoke')

    def test_on_model_cannot_be_off(self):
        self.state['plan'] = b.v.expected_plan(True)
        self.rejected('model profile drift')

    def test_absolute_artifact_rejected(self):
        self.state['artifacts'][str(self.root / 'gc')] = self.state['artifacts']['gc']
        self.rejected('noncanonical')


class LocalContractTests(unittest.TestCase):
    def test_original_negatives_complete(self):
        self.assertEqual(len(b.NEGATIVES['dma']), 4)
        self.assertEqual(b.NEGATIVES['pmp'], list(b.pmp.NEGATIVES.items()))
        models = {side: ({}, Path('/model-' + side), [Path('/model-' + side + '/BoardSocGsim0.o')]) for side in ('off','on')}
        contracts = runner.contracts(Path('/output'), Path('/guest'), '/tools/clang++-19', models, True)
        self.assertEqual(len(contracts), 23)
        self.assertEqual(sum(c['expected_exit'] == 1 for c in contracts.values()), 14)
        for case in b.CASES:
            link = contracts['off-' + case + '-link']['command']
            self.assertIn('-fsanitize=address,undefined', link)
            self.assertIn('-fno-sanitize-recover=all', link)
            self.assertIn('-DBACKEND_OWNER_COUNT=4', link)
        self.assertIn('-DPHYSICAL_INGRESS_FLOW=1', contracts['off-dma-link']['command'])

    def test_duplicate_pmp_result_rejected(self):
        row = 'DATA_PMP_BOARD_PASS cycles=999 traps=3 denied_s=1 denied_mprv=1 allowed_reads=3 forbidden_physical=0 retired=40 pc_trace=9'
        self.assertEqual(b.metrics('pmp', row)['retired'], 40)
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            b.metrics('pmp', row + '\n' + row)

    def test_sanitizer_and_false_positive_negatives(self):
        for text in ('expected\nruntime error: bad', 'expected\nEXEC_CPU_DMA_PASS', 'expected\nDATA_PMP_BOARD_PASS'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                b.clean_log(text, 'expected', True)

    def test_pmp_ab_trace_and_retirement(self):
        baseline = {'cycles': 500, 'retired': 100, 'pc_trace': 5}
        b.pmp.compare_results({'off': baseline, 'on': {**baseline, 'cycles': 900}})
        for key in ('retired', 'pc_trace'):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'trace mismatch'):
                b.pmp.compare_results({'off': baseline, 'on': {**baseline, key: baseline[key] + 1}})

    def test_dma_metrics_witnesses(self):
        fields = {'descriptors':4, 'success':3, 'injected_read_error':1, 'restart':1, 'cycles':10000, 'retired':1000,
            'cpu_ram_while_dma':20,'scratch_reads_while_dma':10,'scratch_writes_while_dma':10,
            'dirty_source_state_cycles':10,'dirty_destination_state_cycles':10,'dirty_source_checked_beats':8,
            'dirty_destination_checked_beats':8,'lsu_entries':4,'lsu_resident_peak':3,'terminal_live_owners':0,
            'complete_owner_drain':1,'dma_resident_slots_peak':3,'verified_cpu_loads':100,'physical_ingress_flow':1,
            'physical_ingress_passes':50,'packet_dma':0,'mac_cdc':0,'stop_abort':'unsupported'}
        def row(f):
            return 'EXEC_CPU_DMA_PASS ' + ' '.join(str(k)+'='+str(v) for k,v in f.items())
        b.metrics('dma', row(fields))
        for key in ('scratch_reads_while_dma','scratch_writes_while_dma','dirty_source_checked_beats','dirty_destination_checked_beats','complete_owner_drain'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                b.metrics('dma', row({**fields, key: 0}))
        for line in (row(fields)+' cycles=1', row({**fields, 'extra':1}), row(fields)+'\n'+row(fields)):
            with self.assertRaises(RuntimeError):
                b.metrics('dma', line)


class PortableGuestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=b.HERE, prefix='.source-test-')
        self.root = Path(self.tmp.name)
        self.tools = {key: Path('/pinned/' + rec['name']) for key,rec in b.LOCK['guest_toolchain'].items()}
        self.state = {'schema': b.GUEST_SCHEMA,'status':b.GUEST_PASS,'profile':b.GUEST_PROFILE,
            'toolchain': b.LOCK['guest_toolchain'],'gsim_lock':b.common.LOCK,'builder_sha256':b.sha(b.HERE/'build_guests.py'),
            'binding_sha256':b.sha(b.__file__),'cases':{}}
        for case in b.CASES:
            root = self.root/case
            (root/'sources').mkdir(parents=True)
            record = {'sources':{}, 'steps':{}, 'artifacts':{}}
            self.state['cases'][case] = record
            for name, original in b.GUEST_SOURCES[case].items():
                (root/'sources'/name).write_bytes((b.ROOT/original).read_bytes())
                record['sources'][name] = b.sha(root/'sources'/name)
            base = 0x80000000 if case=='dma' else 0x80200000
            symbols = {name:base+i*4 for i,name in enumerate(sorted(b.dma_build.SYMBOLS if case=='dma' else b.pmp.SYMBOLS))}
            symbol_text = ''.join(f'{value:016x} T {name}\n' for name,value in symbols.items())
            for name,argv in b.guest_commands(case,self.tools).items():
                log=root/(name+'.log');log.write_text(symbol_text if name=='symbols' else '')
                record['steps'][name]={'command':[Path(argv[0]).name,*argv[1:]],'exit':0,'log':log.name,'log_sha256':b.sha(log)}
            for name in ('guest.o','guest.elf','guest.bin'):
                (root/name).write_bytes(b'\x00'*256)
                record['artifacts'][name]=b.sha(root/name)
            filename,text=b.symbol_file(case,symbols)
            (root/filename).write_text(text)
            record['symbols']=symbols;record['artifacts'][filename]=b.sha(root/filename)
        self.save()

    def save(self):
        (self.root/'manifest.json').write_text(json.dumps(self.state))

    def check(self):
        self.save()
        return b.guest_audit(self.root,self.tools,b.LOCK['guest_toolchain'])

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_portable(self):
        self.check()
        relocated=self.root/'../moved-source-test'
        # Relocation is represented by tool path changes; only pinned basenames
        # are build evidence, never executed from a portable manifest.
        other={k:Path('/newlocation')/v.name for k,v in self.tools.items()}
        b.guest_audit(self.root,other,b.LOCK['guest_toolchain'])

    def test_each_guest_artifact_changed(self):
        for case,record in self.state['cases'].items():
            for name in record['artifacts']:
                path=self.root/case/name;data=path.read_bytes();path.write_bytes(data+b'mutation')
                with self.subTest(case=case,name=name), self.assertRaises(RuntimeError):self.check()
                path.write_bytes(data)

    def test_each_guest_command_changed(self):
        for case,record in self.state['cases'].items():
            for name,step in record['steps'].items():
                old=step['command'];step['command']=old+['--wrong']
                with self.subTest(case=case,name=name), self.assertRaisesRegex(RuntimeError,'command/exit'):self.check()
                step['command']=old

    def test_unknown_profile_fields_rejected(self):
        self.state['profile']={**b.GUEST_PROFILE,'unknown':False}
        with self.assertRaisesRegex(RuntimeError,'profile drift'):self.check()

    def test_command_bool_exit_rejected(self):
        self.state['cases']['dma']['steps']['link']['exit']=False
        with self.assertRaisesRegex(RuntimeError,'command/exit'):self.check()

    def test_extra_or_shadow_file_rejected(self):
        for name in ('pmp/board_boot.cpp','dma/extra','pmp/sources/extra.h'):
            path=self.root/name;path.write_text('shadow')
            with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'file inventory'):self.check()
            path.unlink()

    def test_copied_guest_change_rejected(self):
        (self.root/'dma/sources/guest.S').write_text('changed independent guest')
        with self.assertRaisesRegex(RuntimeError,'copied guest'):self.check()

    def test_log_change_and_sanitizer_rejected(self):
        record=self.state['cases']['pmp']['steps']['assemble'];path=self.root/'pmp'/record['log']
        path.write_text('runtime error: bad')
        with self.assertRaisesRegex(RuntimeError,'log drift'):self.check()
        record['log_sha256']=b.sha(path)
        with self.assertRaisesRegex(RuntimeError,'sanitizer'):self.check()


class ResultAuditTests(PortableGuestTests):
    def setUp(self):
        super().setUp()
        self.result_tmp = tempfile.TemporaryDirectory(dir=b.HERE, prefix='.source-test-')
        self.out = Path(self.result_tmp.name)
        models = {side: ({}, Path('/m-'+side), [Path('/m-'+side+'/BoardSocGsim0.o')]) for side in ('off','on')}
        self.allowed = runner.contracts(self.out, self.root, '/pinned/clang++-19', models, False)
        dma = 'EXEC_CPU_DMA_PASS descriptors=4 success=3 injected_read_error=1 restart=1 cycles=10000 retired=1000 cpu_ram_while_dma=20 scratch_reads_while_dma=10 scratch_writes_while_dma=10 dirty_source_state_cycles=10 dirty_destination_state_cycles=10 dirty_source_checked_beats=8 dirty_destination_checked_beats=8 lsu_entries=4 lsu_resident_peak=3 terminal_live_owners=0 complete_owner_drain=1 dma_resident_slots_peak=3 verified_cpu_loads=100 physical_ingress_flow=1 physical_ingress_passes=50 packet_dma=0 mac_cdc=0 stop_abort=unsupported'
        pmp = 'DATA_PMP_BOARD_PASS cycles=999 traps=3 denied_s=1 denied_mprv=1 allowed_reads=3 forbidden_physical=0 retired=40 pc_trace=9'
        self.result = {'schema':runner.SCHEMA,'limitations':runner.LIMITS,'steps':{},'artifacts':{},'cases':{},'negatives':{},
            'guest_manifest':self.state,'guest_manifest_sha256':b.sha(self.root/'manifest.json'),
            'pmp_architectural_ab':{'retired':40,'pc_trace':9}}
        for name,contract in self.allowed.items():
            text = (dma if '-dma-' in name else pmp) if name.endswith('-run') else (contract['anchor'] or '')
            log=self.out/(name+'.log');log.write_text(text+'\n')
            artifacts={}
            for product in contract['products']:
                (self.out/product).write_text('synthetic binary, never executed')
                artifacts[product]=b.sha(self.out/product)
            self.result['artifacts'].update(artifacts)
            self.result['steps'][name]={**{k:contract[k] for k in ('command','expected_exit','anchor')},
                'actual_exit':contract['expected_exit'],'status':'PASS','cwd':str(b.ROOT),'artifacts':artifacts,
                'log':log.name,'log_sha256':b.sha(log)}
            if name.endswith('-run'):
                case=name.split('-')[1];key=name.removesuffix('-run')
                self.result['cases'][key]={'status':'PASS','metrics':b.metrics(case,text),
                    'guest_sha256':b.sha(self.root/case/'guest.bin'),'binary_sha256':b.sha(self.out/key)}
            if '-negative-' in name:
                self.result['negatives'][name]={'status':'REJECTED','expected_exit':1,'anchor':contract['anchor']}
        (self.out/'receipt.json').write_text('{}')

    def tearDown(self):
        self.result_tmp.cleanup()
        super().tearDown()

    def result_audit(self):
        runner.audit(self.out,self.result,self.allowed,self.root,self.tools,b.LOCK['guest_toolchain'],True)

    def test_complete_result_audit(self):
        self.result_audit()

    def test_each_result_command_rejected(self):
        for name,step in self.result['steps'].items():
            old=step['command'];step['command']=old+['--wrong']
            with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'command/exit'):self.result_audit()
            step['command']=old

    def test_each_missing_negative_rejected(self):
        for name in list(self.result['negatives']):
            old=self.result['negatives'].pop(name)
            with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'incomplete terminal'):self.result_audit()
            self.result['negatives'][name]=old

    def test_result_cwd_and_bool_exit_rejected(self):
        step=self.result['steps']['off-dma-run']
        for key,value in [('actual_exit',False),('cwd','/wrong')]:
            old=step[key];step[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,'command/exit'):self.result_audit()
            step[key]=old

    def test_result_metric_disagreement(self):
        self.result['cases']['on-pmp']['metrics']['retired']+=1
        with self.assertRaisesRegex(RuntimeError,'case/log disagreement'):self.result_audit()

    def test_negative_log_cannot_report_success(self):
        step=self.result['steps']['off-dma-negative-route'];log=self.out/step['log']
        log.write_text(step['anchor']+'\nEXEC_CPU_DMA_PASS\n');step['log_sha256']=b.sha(log)
        with self.assertRaisesRegex(RuntimeError,'negative reported success'):self.result_audit()

    def test_result_sanitizer_cannot_be_rehashed(self):
        step=self.result['steps']['on-pmp-run'];log=self.out/step['log']
        log.write_text(log.read_text()+'runtime error: bad\n');step['log_sha256']=b.sha(log)
        with self.assertRaisesRegex(RuntimeError,'sanitizer'):self.result_audit()

    def test_result_extra_file_rejected(self):
        (self.out/'shadow.h').write_text('unrecorded')
        with self.assertRaisesRegex(RuntimeError,'result file inventory'):self.result_audit()


if __name__=='__main__':
    unittest.main()
