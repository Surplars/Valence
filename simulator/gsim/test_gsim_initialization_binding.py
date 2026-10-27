"""Focused default tool-binding tests; optional staged source, no installation."""
import ast
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import gsim_initialization_epoch as epoch
import gsim_initialization_setup as setup

class BindingTest(unittest.TestCase):
    def setUp(self):
        source=Path(os.environ.get('VALENCE_BINDING_TEST_SOURCE',Path(__file__).with_name('a1_common_cpu_retirement.py')))
        tree=ast.parse(source.read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='tool_binding')
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.common=SimpleNamespace(ROOT=Path(self.tmp.name),compiler=lambda:('clang19','version19'))
        self.exe=Mock(return_value={'path':'/clang19','sha256':'compiler-sha'})
        ns={'common':self.common,'executable_binding':self.exe,'os':os,'Path':Path}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        self.bind=ns['tool_binding']; self.result={'gsim':{'path':'/corrected/gsim'}}
        self.env=patch.dict(os.environ,{},clear=True); self.env.start(); self.addCleanup(self.env.stop)
    def test_false_unchanged(self):
        with patch.object(epoch,'tool_binding') as verify:
            self.assertEqual(self.bind(False),{'compiler':{'path':'/clang19','sha256':'compiler-sha','version':'version19'}})
            verify.assert_not_called()
    def test_missing_fails_without_install(self):
        with patch.object(setup,'build_fresh') as build, patch.object(epoch,'tool_binding') as verify:
            with self.assertRaisesRegex(RuntimeError,'make gsim-setup'): self.bind(True)
            build.assert_not_called(); verify.assert_not_called()
    def test_explicit_receipt_wins(self):
        with patch.dict(os.environ,{'VALENCE_GSIM_INIT_RECEIPT':'/explicit/receipt'}), patch.object(epoch,'tool_binding',return_value=self.result) as verify:
            self.assertEqual(self.bind(True),self.result); verify.assert_called_once_with(Path('/explicit/receipt'))
    def test_canonical_receipt(self):
        path=setup.canonical_output(self.common)/'receipt.json';path.parent.mkdir(parents=True);path.touch()
        with patch.object(epoch,'tool_binding',return_value=self.result) as verify:
            self.assertEqual(self.bind(True),self.result);verify.assert_called_once_with(path)
    def test_tampered_explicit_no_fallback(self):
        with patch.dict(os.environ,{'VALENCE_GSIM_INIT_RECEIPT':'/tampered'}), patch.object(epoch,'tool_binding',side_effect=RuntimeError('changed')),patch.object(setup,'build_fresh') as build:
            with self.assertRaisesRegex(RuntimeError,'changed'):self.bind(True)
            build.assert_not_called()
    def test_tampered_canonical_no_fallback(self):
        path=setup.canonical_output(self.common)/'receipt.json';path.parent.mkdir(parents=True);path.touch()
        with patch.object(epoch,'tool_binding',side_effect=RuntimeError('changed')),patch.object(setup,'build_fresh') as build:
            with self.assertRaisesRegex(RuntimeError,'changed'):self.bind(True)
            build.assert_not_called()
if __name__=='__main__':unittest.main()
