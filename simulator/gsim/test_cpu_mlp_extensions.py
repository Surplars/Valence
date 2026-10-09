import ast
import copy
import unittest
from pathlib import Path
import cpu_mlp_board_nemu as nemu
import cpu_mlp_representative as representative

class ExtensionTests(unittest.TestCase):
    def test_nemu_preserves_owner_and_terminal_checks(self):
        source=(nemu.HERE/'harness/cpu_flow_bandwidth.cpp').read_text()
        generated=nemu.instrument(source)
        for check in ('complete_owner_drain=1', 'terminal_live_owners=', 'reserveGuardMatch',
                      'BackendSample::ownerCount', 'verifyGuardOwner', 'terminal_start='):
            self.assertIn(check,generated)
        self.assertEqual(generated.count('nemu.sample(d);'),1)
        self.assertEqual(generated.count('observer.nemu.initialize(image,argv[2],injection);'),1)
        self.assertIn('std::array<std::string,13> modes',generated)
    def test_nemu_anchor_changes_rejected(self):
        source=(nemu.HERE/'harness/cpu_flow_bandwidth.cpp').read_text()
        for anchor in ('#include <limits>', 'struct Observer {\n    Test *test=nullptr;',
                       '    void sample(SBoardSocGsim &d) {', '    if(argc==3) {\n        injection=argv[2];',
                       'const std::array<std::string,10> modes',
                       '    observer.verify();observer.report();return 0;'):
            with self.subTest(anchor=anchor),self.assertRaises(RuntimeError):
                nemu.instrument(source.replace(anchor,'altered anchor'))
        with self.assertRaises(RuntimeError): nemu.instrument(source+source)
    def test_virtual_peak_only(self):
        source=(nemu.HERE/'harness/virtual_load_board.cpp').read_text()
        generated=representative.virtual_observer(source)
        self.assertEqual(generated.replace('backend.liveCount()', 'unsigned(backend.live[0]) + unsigned(backend.live[1])'),source)
        for bad in (source+source,source.replace('unsigned(backend.live[0]) + unsigned(backend.live[1])','altered')):
            with self.assertRaises(AssertionError):representative.virtual_observer(bad)
    def test_step_name_is_never_shadowed(self):
        tree=ast.parse(Path(nemu.__file__).read_text())
        run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        step=next(n for n in run.body if isinstance(n,ast.FunctionDef) and n.name=='step')
        for node in ast.walk(step):
            if isinstance(node,ast.For):
                self.assertNotIn('name',[x.id for x in ast.walk(node.target) if isinstance(x,ast.Name)])
    def test_capacity_definitions(self):
        for label in nemu.LABELS:
            flags=nemu.flags(label,'read-4096',Path('model'),Path('guest'))
            self.assertEqual([x for x in flags if x.startswith('-DBACKEND_OWNER_COUNT=')],['-DBACKEND_OWNER_COUNT='+label[3:]])
            self.assertIn('-DPHYSICAL_INGRESS_FLOW=1',flags)
        self.assertEqual(len(nemu.negative_modes('lsu2')),8)
        self.assertEqual(len(nemu.negative_modes('lsu4')),10)
    def test_pair_trace_mutations(self):
        cases={label+'-'+case:dict(guest_sha256='same',nemu=dict(guest_pc_checks='10',guest_pc_trace='123',final_memory_bytes='4194368'))
               for label in nemu.LABELS for case in nemu.CASES}
        nemu.compare_pairs(cases)
        for field in ('guest_pc_checks','guest_pc_trace','final_memory_bytes'):
            bad=copy.deepcopy(cases);bad['lsu4-read-4096']['nemu'][field]='11'
            with self.assertRaises(RuntimeError):nemu.compare_pairs(bad)
        bad=copy.deepcopy(cases);bad['lsu4-read-4096']['guest_sha256']='different'
        with self.assertRaises(RuntimeError):nemu.compare_pairs(bad)
        with self.assertRaises(RuntimeError):nemu.compare_pairs({})

if __name__=='__main__':unittest.main()
