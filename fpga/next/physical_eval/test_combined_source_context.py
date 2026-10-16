"""Mock Tcl source-context tests; no Vivado or actual constraints executed."""
from pathlib import Path
import tempfile
import tkinter
import unittest

HERE = Path(__file__).resolve().parent


class SourceContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-source-context-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root/'package/scripts'; self.scripts.mkdir(parents=True)
        self.board = self.root/'package/export/board'; self.board.mkdir(parents=True)
        self.out = self.root/'output'; self.out.mkdir()
        self.tcl = tkinter.Tcl()
        self.tcl.eval((HERE/'combined_runtime.tcl').read_text())
        self.old_cwd = self.tcl.call('pwd')
        self.addCleanup(self.tcl.call, 'cd', self.old_cwd)
        self.tcl.call('cd', str(self.out))
        for name in ('GMAC', 'BANK', 'ROM', 'SOC', 'RGMII'):
            self.tcl.call('set', '::V_'+name+'_ROOT', 'mock_'+name.lower())
        self.entry = self.root/'external-validator/entry.tcl'
        self.entry.parent.mkdir()
        self.bound = self.scripts/'board_controls.tcl'
        self.child = self.board/'child.tcl'

    def entry_script(self):
        # Tcl builds its own exact argument quoting, including paths with spaces.
        self.tcl.call('set', 'bound_path', str(self.bound))
        self.entry.write_text('set before [info script]\ncatch {combined_source_bound $bound_path} message options\nset after [info script]\n')
        self.tcl.call('source', str(self.entry))

    def test_nested_sources_use_sealed_script_context_and_restore_caller(self):
        original = 'set bound_context [info script]\nset mapped u_soc/board/nativeBank/gmac\nsource [file join [file dirname [info script]] .. export board child.tcl]\nset resumed [info script]\n'
        self.bound.write_text(original)
        self.child.write_text('set child_context [info script]\nsource [file join [file dirname [info script]] grandchild.tcl]\n')
        (self.board/'grandchild.tcl').write_text('set grandchild_context [info script]\n')
        self.entry_script()
        self.assertEqual(self.tcl.getvar('mapped'), 'mock_gmac')
        for key, path in [('before', self.entry), ('after', self.entry), ('bound_context', self.bound),
                          ('resumed', self.bound), ('child_context', self.child),
                          ('grandchild_context', self.board/'grandchild.tcl')]:
            self.assertEqual(Path(str(self.tcl.getvar(key))).resolve(), path.resolve(), key)
        self.assertEqual(self.bound.read_text(), original)
        self.assertIn('mock_gmac', (self.out/'bound-board_controls.tcl').read_text())

    def test_nested_error_preserves_failure_and_restores_caller(self):
        self.bound.write_text('source [file join [file dirname [info script]] .. export board child.tcl]\n')
        self.child.write_text('return -code error -errorcode MOCK_NESTED_ERROR "mock nested failure"\n')
        self.entry_script()
        self.assertEqual(self.tcl.getvar('message'), 'mock nested failure')
        self.assertEqual(self.tcl.eval('dict get $options -errorcode'), 'MOCK_NESTED_ERROR')
        self.assertEqual(self.tcl.getvar('before'), self.tcl.getvar('after'))

if __name__ == '__main__': unittest.main()
