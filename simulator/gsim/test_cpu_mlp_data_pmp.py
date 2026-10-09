import unittest
from pathlib import Path
from unittest.mock import patch
import cpu_mlp_data_pmp as pmp

class CapacityPmpTests(unittest.TestCase):
    def test_explicit_pair_and_fixed_dma_profile(self):
        a=pmp.arguments(['--out','test-output','--lsu2-model-tag','two','--lsu4-model-tag','four'])
        self.assertEqual((a.dma_line_transfers,a.dma_line_entries,a.dma_line_yield_cycles),(True,4,0))
        self.assertEqual(set(pmp.model_paths(a,Path('/tmp/test-models'))),{'lsu2','lsu4'})
    def test_architectural_pair_exactness(self):
        x={'cycles':10,'retired':108,'pc_trace':123}
        y={**x,'cycles':8}
        self.assertEqual(pmp.compare_results({'lsu2':x,'lsu4':y}),{'retired':108,'pc_trace':123})
        for field in ('retired','pc_trace'):
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                pmp.compare_results({'lsu2':x,'lsu4':{**y,field:y[field]+1}})
    def test_flow_pair_not_mislabeled_capacity(self):
        with self.assertRaises(RuntimeError):
            pmp.compare_results({'off':{},'on':{}})
    def test_reject_same_receipt(self):
        with self.assertRaises(RuntimeError):
            pmp.validate_models({'lsu2':Path('/tmp/same'),'lsu4':Path('/tmp/same')},{},'compiler')
    def test_both_physical_flags_and_owner_counts(self):
        paths={'lsu2':Path('/tmp/two'),'lsu4':Path('/tmp/four')}
        result=({'inputs':{},'toolchain':{}},Path('/tmp/model'),[])
        with patch.object(Path,'is_file',return_value=True),patch.object(pmp,'sha',return_value='digest'),\
             patch.object(pmp,'stable'),patch.object(pmp.flow,'validate_model',return_value=result) as validate:
            pmp.validate_models(paths,{},'compiler',dma_line_transfers=True,dma_line_entries=4,dma_line_yield_cycles=0)
        self.assertEqual([call.args[1] for call in validate.call_args_list],[1,1])
        self.assertEqual([call.kwargs['lsu_entries'] for call in validate.call_args_list],[2,4])

if __name__=='__main__':unittest.main()
