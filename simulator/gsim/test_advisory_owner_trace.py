#!/usr/bin/env python3
"""Static schema/adapter and comparator negative controls; no DUT build or run."""
import copy
from pathlib import Path
import tempfile
import unittest
import advisory_owner_trace as t


class TraceTests(unittest.TestCase):
    def test_direction_and_fail_closed(self):
        fir = '  public module CommonA1VmPipelineGsim :\n    output x : { a : UInt<4>, flip b : { flip c : UInt<1>, d : UInt<2>}}\n'
        self.assertEqual(t.fir_outputs(fir), {'x$$a':4, 'x$$b$$c':1})
        with self.assertRaises(Exception):
            t.fir_outputs(fir.replace('UInt<4>', 'UInt<4>[2]'))
        with self.assertRaises(Exception):
            t.fir_outputs(fir.replace('UInt<4>', 'UInt<65>'))

    def test_explicit_payload_and_single_ready_exception(self):
        fir = ('  public module CommonA1VmPipelineGsim :\n'
               '    output x : { valid : UInt<1>, bits : UInt<8>, ready : UInt<1>}\n'
               '    output returnFlow : { outputReady : UInt<1>, outputValid : UInt<1>, outputBits : {data : UInt<64>}}\n')
        outputs = t.fir_outputs(fir)
        header = '\n'.join('uint64_t get_' + name + '();' for name in outputs)
        fields = {x['getter']: x['when'] for x in t.schema(fir,header)}
        self.assertEqual(fields['x$$valid'], 'true')
        self.assertEqual(fields['x$$ready'], 'true')
        self.assertEqual(fields['x$$bits'], 'd.get_x$$valid()')
        self.assertEqual(fields['returnFlow$$outputReady'], 'd.get_returnFlow$$outputValid()')
        self.assertEqual(fields['returnFlow$$outputBits$$data'], 'd.get_returnFlow$$outputValid()')
        with self.assertRaises(Exception):
            t.schema(fir,header.replace('uint64_t get_x$$ready();',''))
        with self.assertRaises(Exception):
            t.schema(fir,header+'\nuint8_t get_unexpected();')
        with self.assertRaises(Exception):
            t.schema(fir.replace('valid : UInt<1>, ',''),header.replace('uint64_t get_x$$valid();',''))

    def test_exact_comparator_rejects_event_cycle_and_log_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            for name in ('a','b'):
                (p/(name+'.bin')).write_bytes(bytes(range(16)))
                (p/(name+'.log')).write_text('PASS cycles=2\n')
            def result(name):
                return {'schema_sha256':'same', 'fields_per_cycle':1, 'runs':{'vm':{
                    'functional_log':str(p/(name+'.log')), 'traces':{'guest':{
                    'path':str(p/(name+'.bin')), 'cycles':2, 'bytes':16}}}}}
            a,b=result('a'),result('b')
            self.assertTrue(t.compare_exact(a,b)['all_guest_cycles_exact'])
            # Missing valid completion or arbitrary phase/payload: any bit differs.
            (p/'b.bin').write_bytes(bytes(16))
            with self.assertRaises(Exception): t.compare_exact(a,b)
            (p/'b.bin').write_bytes(bytes(range(16)))
            c=copy.deepcopy(b);c['runs']['vm']['traces']['guest']['cycles']=1
            with self.assertRaises(Exception): t.compare_exact(a,c)
            (p/'b.log').write_text('PASS cycles=3\n')
            with self.assertRaises(Exception): t.compare_exact(a,b)
            c=copy.deepcopy(b);c['schema_sha256']='changed'
            with self.assertRaises(Exception): t.compare_exact(a,c)


if __name__ == '__main__':
    unittest.main()
