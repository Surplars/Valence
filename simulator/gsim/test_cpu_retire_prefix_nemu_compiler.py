"""No compiler/link/model execution: exercise the exact execution-boundary check."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cpu_retire_prefix_nemu as n

class CompilerGateTests(unittest.TestCase):
    def inputs(self, name='clang++-19'):
        return SimpleNamespace(cxx=Path('/attested')/name, root=Path('/source'),
            compiler_version='qualified clang version', compiler_sha256='f'*64, guard=Mock())

    def test_positive_and_exact_argv(self):
        i=self.inputs()
        with patch.object(n.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=i.compiler_version+'\nTarget: target')) as call:
            row=n.verify_execution_compiler(i)
            self.assertEqual(call.call_args.args[0],['/attested/clang++-19','--version'])
            self.assertEqual(row['sha256'],'f'*64)
            self.assertEqual(i.guard.call_count,2)

    def test_non_cpp_or_unrecognized_driver_rejected_before_execution(self):
        for name in ('clang','clang-19','true','compiler-wrapper','clang++-19-evil'):
            with self.subTest(name=name),patch.object(n.subprocess,'run') as call,self.assertRaises(RuntimeError):
                n.verify_execution_compiler(self.inputs(name))
            call.assert_not_called()

    def test_failed_empty_or_changed_version_rejected(self):
        for code,text in ((1,'qualified clang version'),(0,''),(0,'different compiler\n'),(0,'warning\nqualified clang version')):
            i=self.inputs()
            with self.subTest(code=code,text=text),patch.object(n.subprocess,'run',return_value=SimpleNamespace(returncode=code,stdout=text)),self.assertRaises(RuntimeError):
                n.verify_execution_compiler(i)

    def test_input_drift_prevents_execution_or_success(self):
        for calls in (1,2):
            i=self.inputs();i.guard.side_effect=[RuntimeError('drift')] if calls==1 else [None,RuntimeError('drift')]
            with self.subTest(calls=calls),patch.object(n.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=i.compiler_version)) as call,self.assertRaises(RuntimeError):
                n.verify_execution_compiler(i)
            self.assertEqual(call.call_count,calls-1)

if __name__=='__main__':unittest.main()
