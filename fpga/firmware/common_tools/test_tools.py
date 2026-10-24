#!/usr/bin/env python3
"""Host protocol/negative tests: never accesses actual hardware sysfs."""
import contextlib
import errno
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

clockmon, dma, coremark = load('clockmon'), load('dma_bench'), load('coremark')

def snapshot(**replace):
    lines = []
    for domain in ('cpu', 'fabric'):
        row = dict(sequence='7', flags='0x1', valid='1', counter_bits='24',
                   reference_hz='50000000', window='50000', timestamp='900000', measured_hz='100000000')
        for i in range(8):
            row['delta'+str(i)] = str(100000 if not i else 100+i)
            row['total'+str(i)] = str(120000 if not i else 1000+i)
        row.update(replace)
        lines.append(domain + ' ' + ' '.join(k+'='+v for k,v in row.items()))
    return '\n'.join(lines) + '\n'

def profile_snapshot(lanes, scalar, **replace):
    text = snapshot(**replace)
    return text.replace('cpu ', f'cpu retirement_lanes={lanes} scalar_request_lane={scalar} ', 1)

def status(**replace):
    row = dict(bytes='4096', iterations='1', elapsed_ns='1000000', payload_bytes_per_sec='4096000',
               logical_rw_bytes_per_sec='8192000', verified='1', faulted='0',
               timing='dmaengine_submit_to_callback', run_sequence='8', last_stage='complete',
               last_reason='pass', last_errno='0', last_cookie='1', last_result='0', last_iteration='1')
    row.update(replace)
    return ' '.join(k+'='+str(v) for k,v in row.items()) + '\n'

class ClockTests(unittest.TestCase):
    def test_explicit_i1_and_legacy_identity(self):
        legacy = clockmon.parse_snapshot(snapshot())
        explicit = clockmon.parse_snapshot(profile_snapshot(1, 1))
        self.assertEqual(legacy['cpu']['profile_source'], 'legacy_i1_text')
        self.assertEqual(explicit['cpu']['profile_source'], 'explicit_driver_fields')
        self.assertEqual(explicit['cpu']['events'], legacy['cpu']['events'])
        self.assertEqual(explicit['cpu']['meter_abi'], 1)
        self.assertEqual(explicit['fabric']['meter_abi'], 1)
        self.assertIn('retire_lane0_per_cycle', explicit['cpu'])

    def test_explicit_a1_dual_retirement_labels(self):
        s = clockmon.parse_snapshot(profile_snapshot(2, 0, delta1='150000'))
        cpu = s['cpu']
        self.assertEqual(cpu['meter_abi'], 2)
        self.assertEqual(cpu['snapshot_profile'], 'a1-runtime')
        self.assertEqual(cpu['retire_total_two_lanes_per_cycle'], 1.5)
        self.assertNotIn('retire_lane0_per_cycle', cpu)
        self.assertEqual(cpu['events']['retire_total_two_lanes']['window_count'], 150000)
        self.assertEqual(cpu['events']['scalar_lane0_request_fire']['window_count'], 102)
        self.assertIn('neither_lane_retired', cpu['events'])
        self.assertNotIn('retire_lane0', cpu['events'])
        self.assertNotIn('scalar_lane1_request_fire', cpu['events'])
        self.assertIn('two independently synchronized lanes', clockmon.render(s)['ipc_semantics'])
        self.assertEqual(s['fabric']['events']['AXI_R_beats']['window_count'], 105)

    def test_lane_pairing_and_unknown_abi_rejected(self):
        for lanes, scalar in ((0,0), (1,0), (2,1), (3,0), ('-1',1), (2,'nan')):
            with self.subTest(lanes=lanes, scalar=scalar), self.assertRaises(ValueError):
                clockmon.parse_snapshot(profile_snapshot(lanes, scalar))
        text = profile_snapshot(2, 0)
        for bad in (text.replace(' retirement_lanes=2',''),
                    text.replace(' scalar_request_lane=0',''),
                    text.replace('fabric ', 'fabric retirement_lanes=2 scalar_request_lane=0 '),
                    text.replace('cpu ', 'cpu abi_version=2 '),
                    text.replace('cpu ', 'cpu retirement_lanes=2 ')):
            with self.subTest(bad=bad[:100]), self.assertRaises(ValueError):
                clockmon.parse_snapshot(bad)

    def test_dual_lane_wrap_boundary(self):
        mask = (1 << 24) - 1
        for lanes, scalar in ((1,1), (2,0)):
            boundary = mask // (6 * lanes)
            hz = str(100000 * 50000000 // boundary)
            clockmon.parse_snapshot(profile_snapshot(lanes, scalar, window=str(boundary), measured_hz=hz))
            with self.assertRaises(ValueError):
                clockmon.parse_snapshot(profile_snapshot(lanes, scalar, window=str(boundary+1),
                    measured_hz=str(100000 * 50000000 // (boundary+1))))
        # This window passes the one-lane limit but must fail the two-lane limit.
        clockmon.parse_snapshot(profile_snapshot(1, 1, window='2000000', measured_hz='2500000'))
        with self.assertRaises(ValueError):
            clockmon.parse_snapshot(profile_snapshot(2, 0, window='2000000', measured_hz='2500000'))

    def test_dual_lane_invalid_and_stopped(self):
        invalid = clockmon.parse_snapshot(profile_snapshot(2, 0, flags='5', valid='0', measured_hz='unavailable'))
        self.assertIsNone(invalid['cpu']['retire_total_two_lanes_per_cycle'])
        self.assertIsNone(invalid['cpu']['events']['retire_total_two_lanes']['average_per_second'])
        stopped = clockmon.parse_snapshot(profile_snapshot(2, 0, delta0='0', flags='3', measured_hz='0'))
        self.assertIsNone(stopped['cpu']['retire_total_two_lanes_per_cycle'])
        self.assertTrue(stopped['cpu']['valid'])

    def test_exact_frequency_and_window(self):
        s = clockmon.parse_snapshot(snapshot())
        self.assertEqual(s['cpu']['measured_hz'], 100000000)
        self.assertEqual(s['cpu']['window_seconds'], .001)
        self.assertEqual(s['fabric']['events']['AXI_R_beats']['window_count'], 105)
        self.assertAlmostEqual(s['cpu']['line_refill_mib_s'],105*64/.001/1048576)
    def test_stopped_is_valid_zero(self):
        s = clockmon.parse_snapshot(snapshot(delta0='0', flags='3', measured_hz='0'))
        self.assertTrue(s['cpu']['valid']); self.assertEqual(s['cpu']['measured_hz'],0)
        self.assertIsNone(s['cpu']['retire_lane0_per_cycle'])
    def test_invalid_and_overflow_suppress_rates(self):
        for flags in ('0','4','5'):
            with self.subTest(flags=flags):
                s = clockmon.parse_snapshot(snapshot(flags=flags, valid='0', measured_hz='unavailable'))
                self.assertIsNone(s['cpu']['measured_hz'])
                self.assertIsNone(s['cpu']['line_refill_mib_s'])
                self.assertIsNone(s['cpu']['events']['edges']['average_per_second'])
    def test_publication_repeated_reset(self):
        s=clockmon.parse_snapshot(snapshot())
        self.assertEqual(clockmon.render(s)['sequence_state'],'first')
        self.assertFalse(clockmon.render(s,7)['new_publication'])
        self.assertEqual(clockmon.render(s,6)['sequence_state'],'advanced')
        self.assertEqual(clockmon.render(s,8)['sequence_state'],'reset_or_wrap')
    def test_bad_fields(self):
        for kwargs in ({'counter_bits':'3'}, {'counter_bits':'33'}, {'reference_hz':'250000000'},
                       {'window':'0'}, {'window':'3000000'}, {'flags':'8'}, {'flags':'3'},
                       {'valid':'2'}, {'valid':'0'}, {'measured_hz':'100000001'},
                       {'delta7':'16777216'}, {'total7':'16777216'}, {'timestamp':'-1'},
                       {'sequence':str(1<<64)}, {'delta0':'nan'}, {'window':'1.0'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                clockmon.parse_snapshot(snapshot(**kwargs))
    def test_missing_unknown_duplicate_incoherent(self):
        text=snapshot()
        variants=[text.replace(' total7=1007',''),text.replace(' total7=1007',' mystery=1007'),
                  text.replace(' total7=1007',' total6=1007'),text+text.splitlines()[0]+'\n',
                  text.splitlines()[0]+'\n',text.replace('fabric sequence=7','fabric sequence=8'),
                  text.replace('fabric ','other ',1)]
        for value in variants:
            with self.subTest(value=value[-60:]),self.assertRaises(ValueError):clockmon.parse_snapshot(value)
    def test_cli_saved_and_invalid_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'snapshot';p.write_text(snapshot())
            with contextlib.redirect_stdout(io.StringIO()) as out:clockmon.main(['--file',str(p)])
            self.assertEqual(json.loads(out.getvalue())['publication_sequence'],7)
            for args in (['--interval','nan'],['--interval','inf'],['--count','0']):
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):clockmon.main(args)

class DmaTests(unittest.TestCase):
    def test_bounds(self):
        for size,iterations in ((8,1),(8388608,64),(4096,1)):dma.validate_request(size,iterations)
        for size,iterations in ((0,1),(7,1),(9,1),(8388616,1),(8,0),(8,65)):
            with self.subTest(size=size,iterations=iterations),self.assertRaises(ValueError):dma.validate_request(size,iterations)
    def test_parse_and_bad_result(self):
        self.assertEqual(dma.parse_status(status())['bytes'],4096)
        for kwargs in ({'faulted':'2'},{'verified':'2'},{'run_sequence':'-1'},{'bytes':str(1<<64)},
                       {'timing':'wire_peak'},{'logical_rw_bytes_per_sec':'8192001'},
                       {'last_errno':'nan'},{'last_cookie':str(1<<31)},{'last_result':str(-(1<<31)-1)},
                       {'last_iteration':str(1<<32)}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):dma.parse_status(status(**kwargs))
        with self.assertRaises(ValueError):dma.parse_status(status()+' bytes=1')
    def test_generation_and_exact_rate(self):
        before=dma.parse_status(status(run_sequence='7'));after=dma.parse_status(status())
        self.assertEqual(dma.evaluate(before,after,4096,1),after)
        for kwargs in ({'run_sequence':'9'}, {'bytes':'8192'}, {'iterations':'2'}, {'elapsed_ns':'0'},
                       {'verified':'0'},{'faulted':'1'},{'last_reason':'timeout'},{'last_stage':'wait'},
                       {'elapsed_ns':'999999'},{'last_errno':'-5'},{'last_result':'1'},
                       {'last_iteration':'0'},{'last_cookie':'0'},{'last_cookie':'-1'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(RuntimeError):
                dma.evaluate(before,dma.parse_status(status(**kwargs)),4096,1)
    def test_write_once_regular_private_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sink';p.touch();dma.write_once(p,b'4096 1\n')
            self.assertEqual(p.read_bytes(),b'4096 1\n')
    def run_mock(self, action, rows, root=0, fault=None):
        class Input:
            def read_text(self):return rows.pop(0)
        with patch.object(dma,'discover',return_value=Input()),patch.object(dma.os,'geteuid',return_value=root),\
             patch.object(dma,'write_once',side_effect=fault) as writer,\
             contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            try:dma.main([action])
            finally:self.last_calls=writer.call_count
    def test_status_never_triggers(self):
        self.run_mock('status',[status()]);self.assertEqual(self.last_calls,0)
    def test_success_exactly_one_write(self):
        self.run_mock('run',[status(run_sequence='7'),status()]);self.assertEqual(self.last_calls,1)
    def test_fault_nonroot_and_uncertain_no_retry(self):
        for rows,uid in (([status(faulted='1')],0),([status()],1000)):
            with self.assertRaises(RuntimeError):self.run_mock('run',rows,root=uid)
            self.assertEqual(self.last_calls,0)
        with self.assertRaises(OSError):self.run_mock('run',[status(),status()],fault=OSError(errno.EINTR,'interrupted'))
        self.assertEqual(self.last_calls,1)

class CoremarkTests(unittest.TestCase):
    GOOD = """seedcrc : 0xe9f5
[0]crclist : 0xe714
[0]crcmatrix : 0x1fd7
[0]crcstate : 0x8e3a
Total time (secs): 10.100000
Iterations/Sec : 100.000
Correct operation validated.
"""
    def test_valid(self):
        self.assertEqual(coremark.evaluate(self.GOOD)['iterations_per_second'],100)
    def test_short_no_score(self):
        text=self.GOOD.replace('10.100000','0.100000').replace('Correct operation validated.','ERROR! Must execute for at least 10 secs for a valid result!')
        self.assertIsNone(coremark.evaluate(text)['iterations_per_second'])
    def test_bad_crc_and_timing(self):
        for text in (self.GOOD.replace('e714','e715'), self.GOOD+'seedcrc : 0xe9f5\n',
                     self.GOOD.replace('10.100000','0.000000'), self.GOOD.replace('10.100000','nan'),
                     self.GOOD.replace('Correct operation validated.','Errors detected'),
                     self.GOOD+'ERROR unexpected\n'):
            with self.subTest(text=text[-40:]),self.assertRaises(ValueError):coremark.evaluate(text)

if __name__=='__main__':unittest.main()
