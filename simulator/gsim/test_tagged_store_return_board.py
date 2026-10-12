#!/usr/bin/env python3
"""Source-only CLI, parameter, command and parser checks. No DUT/tools run."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import tagged_store_return_board as board

class TaggedBoardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=board.contract(board.ROOT)
        cls.p={n:Path('/portable')/n for n in ('source','model','output','guest')}
        cls.tools={n:Path('/tools')/n for n in ('mill','gsim','cxx')}
        cls.commands=board.recipe(cls.spec,cls.p,cls.tools)

    def test_default_off_explicit_on_complete_parameters(self):
        s=self.spec
        self.assertIs(s['generic_default'],False)
        self.assertEqual((len(s['profile']['profile']),len(s['profile']['core']),len(s['profile']['cache'])),(58,151,19))
        self.assertEqual(s['profile']['core'],s['actual_fabric']['cpu'])
        self.assertEqual((s['actual_fabric']['cpu']['memoryEntries'],s['actual_fabric']['cache']['readMshrs'],
                          s['actual_fabric']['ddr']['maxOutstanding']),(4,2,4))
        self.assertEqual(s['native_options'].count('--tagged-store-returns'),1)
        self.assertEqual(s['native_options'][-1],'--tagged-store-returns')

    def test_exact_original_run_laws_and_controls(self):
        rows={r['label']:r for r in self.commands}
        for label,mode in [('cpu-sv39','1'),('bare','0'),('fixed','1')]:
            self.assertEqual(rows[label]['argv'][-4:],[mode,'2','65536','2'])
        for stem in ('','fixed-'):
            for injection,anchor in board.NEGATIVES:
                r=rows[stem+'negative-'+injection]
                self.assertEqual(r['argv'][-5:],['1','2','4096','1','--inject-'+injection])
                self.assertEqual((r['expected_exit'],r['anchor']),(1,anchor))
        self.assertEqual(len([r for r in self.commands if r['label'].startswith('compile-')]),37)
        self.assertEqual(len([r for r in self.commands if r['stage']=='host-controls' and r['expected_exit']==1]),55)
        self.assertIn('-DTAGGED_STORE_RETURNS=1',rows['host-link']['argv'])
        self.assertIn('-DBOARD_EXPECTED_LSU_ENTRIES=4',rows['host-link']['argv'])
        self.assertIn('-DDDR_READ_LATENCY=32',rows['host-link']['argv'])
        self.assertIn('-DDDR_READ_BEAT_GAP=1',rows['host-link']['argv'])

    def test_relocation_changes_only_path_parameters(self):
        other={n:Path('/elsewhere')/n for n in self.p}
        a=board.recipe(self.spec,other,self.tools)
        for old,new in zip(self.commands,a):
            self.assertEqual(json.dumps(old).replace('/portable/','/elsewhere/'),json.dumps(new))

    def test_host_materialization_exact_original_and_one_fixed_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/'original';fixed=Path(tmp)/'fixed'
            board.host_materialize(board.ROOT,original,self.spec)
            board.host_materialize(board.ROOT,fixed,self.spec,True)
            changed=[n for n in self.spec['host_sources'] if board.sha(original/n)!=board.sha(fixed/n)]
            self.assertEqual(changed,['harness/board_ddr_benchmark.h'])
            for n,row in self.spec['host_sources'].items():self.assertEqual(board.sha(original/n),row['sha256'])

    def test_105_field_parser_and_unique_lines(self):
        row=self.spec['baseline_cases']['sv39']
        text='\n'.join(prefix+' '+' '.join(k+'='+v for k,v in row[section].items())
                       for section,prefix in board.capture_result.__globals__['PREFIXES'].items())
        result=board.capture_result.__globals__['extract'](text)
        self.assertEqual(sum(len(result[n]) for n in ('result','perf','oracle','fabric')),105)
        with self.assertRaises(AssertionError):board.capture_result.__globals__['extract'](text+'\n'+text.splitlines()[0])
        with self.assertRaises(AssertionError):board.capture_result.__globals__['extract']('\n'.join(text.splitlines()[1:]))
        with self.assertRaises(AssertionError):board.parse('TAGGED_RETURN_PASS x=1 x=2','TAGGED_RETURN_PASS')

    def test_invalid_model_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for name,value in [('profile.json',self.spec['profile']),('actual-fabric.json',self.spec['actual_fabric'])]:
                (p/name).write_text(json.dumps(value))
            changed=copy.deepcopy(self.spec['profile']);changed['core']['memoryEntries']=8
            (p/'profile.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(AssertionError,'constructor'):board.model_identity(p,self.spec)

    def test_parse_requires_explicit_execution(self):
        argv=['sv39','--output','/never-created','--model-root','/never-model','--guest-root','/never-guest']
        with mock.patch.object(board.portable,'tool_paths',return_value=self.tools), \
             mock.patch.object(board,'checked'),mock.patch.object(board,'contract',return_value=self.spec), \
             mock.patch.object(board,'current_inputs',return_value={}), \
             mock.patch.object(board,'tool_inputs',return_value={}):
            with self.assertRaises(SystemExit) as error:board.main(argv)
            self.assertEqual(error.exception.code,2)

if __name__=='__main__':unittest.main()
