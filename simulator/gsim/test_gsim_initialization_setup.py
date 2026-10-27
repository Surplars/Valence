"""Branch tests only: no network, rebuilds, or old hardware execution."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import gsim_initialization_setup as setup

class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.common = SimpleNamespace(ROOT=root, BUILD=root/'build/gsim', HERE=root/'simulator/gsim',
                                      SOURCE=root/'source', compiler=lambda: ('clang++-19','19'))
        self.env = patch.dict(os.environ, {}, clear=True); self.env.start(); self.addCleanup(self.env.stop)
        self.binding = {'gsim': {'path': '/corrected/gsim'}}
    def test_missing_without_fetch(self):
        with self.assertRaisesRegex(RuntimeError, 'make gsim-setup'):
            setup.setup(False, self.common)
    def test_explicit_wins(self):
        with patch.dict(os.environ, {'VALENCE_GSIM_INIT_RECEIPT':'/explicit/receipt.json'}), \
             patch.object(setup.epoch, 'tool_binding', return_value=self.binding) as verify, \
             patch.object(setup, 'build_fresh') as build:
            self.assertEqual(setup.setup(True,self.common)[0],Path('/corrected/gsim'))
            verify.assert_called_once_with(Path('/explicit/receipt.json')); build.assert_not_called()
    def test_canonical_reuse(self):
        out=setup.canonical_output(self.common); out.mkdir(parents=True); (out/'receipt.json').touch()
        with patch.object(setup.epoch,'tool_binding',return_value=self.binding) as verify, patch.object(setup,'build_fresh') as build:
            setup.setup(False,self.common); verify.assert_called_once_with(out/'receipt.json'); build.assert_not_called()
    def test_tampered_no_fallback(self):
        with patch.dict(os.environ,{'VALENCE_GSIM_INIT_RECEIPT':'/tampered'}), patch.object(setup.epoch,'tool_binding',side_effect=RuntimeError('changed')), patch.object(setup,'build_fresh') as build:
            with self.assertRaisesRegex(RuntimeError,'changed'): setup.setup(True,self.common)
            build.assert_not_called()
    def test_fresh_bootstrap(self):
        with patch.object(setup,'build_fresh') as build, patch.object(setup.epoch,'tool_binding',return_value=self.binding):
            setup.setup(True,self.common); build.assert_called_once_with(self.common,setup.canonical_output(self.common))
    def test_incomplete_output_not_reused(self):
        out=setup.canonical_output(self.common); out.mkdir(parents=True)
        with patch.object(setup,'prepare_pristine') as prepare:
            with self.assertRaisesRegex(RuntimeError,'incomplete repaired epoch'): setup.build_fresh(self.common,out)
            prepare.assert_not_called()
if __name__=='__main__': unittest.main()
