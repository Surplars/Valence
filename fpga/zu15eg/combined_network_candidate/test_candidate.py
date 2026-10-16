import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('combined', HERE / 'export_board.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class CandidateTests(unittest.TestCase):
    def test_four_modes_and_exact_single_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pad in (False, True):
                for rx in (False, True):
                    out = Path(tmp) / f'{pad}-{rx}'
                    m.export(out, pad, rx, 't1-selected' if pad else None)
                    m.audit(out)
                    data = (out / m.BOARD).read_bytes()
                    base = (m.ROOT / 'fpga/next' / m.BOARD).read_bytes()
                    self.assertEqual(m.ports(data), m.ports(base))
                    if not pad and not rx:
                        self.assertEqual(data, base)
                    if pad != rx:
                        single = Path(tmp) / f'single-{pad}'
                        adapter = m.load_adapter('pad_reset_candidate' if pad else 'rx_capture_candidate')
                        if pad: adapter.export(single, True, 't1-selected')
                        else: adapter.export(single, True)
                        self.assertEqual(data, (single / m.BOARD).read_bytes())
                    if pad and rx:
                        for marker in (b'ENABLE_PAD_DOMAIN_RESET(1)', b'ENABLE_FALLING_PAIR(1)',
                                       b'BUFG rx_capture_clock_buffer', b'posedge clk_rx_capture',
                                       b'.rx_clock(clk_rx_capture)', b'PAD candidate requires t1-selected'):
                            self.assertEqual(data.count(marker), 1, marker)
                        for parameter in (b'NATIVE_MAC_LOCAL_PAD_RESET_RELEASE', b'NATIVE_MAC_REGISTER_SELECTED_HALF'):
                            self.assertEqual(data.count(b'parameter ' + parameter + b' = 1'), 1)
                        self.assertIn(b'.io_nativeGmac_rawRxClock(clk_rx)', data)

    def test_profile_and_flag_rejection(self):
        for args in [(True, True, None), (False, True, 't1-selected'), (1, False, None)]:
            with self.assertRaises(ValueError): m.build(*args)

    def test_overlap_rejected(self):
        with self.assertRaises(ValueError): m.merge_edits(b'a\nb\n', [b'x\nb\n', b'y\nb\n'])

    def test_stale_flags_sources_and_corrupt_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            m.export(out, True, True, 't1-selected')
            receipt = out / 'source-candidate.json'
            saved = receipt.read_bytes()
            record = json.loads(saved)
            record['rxCaptureSibling'] = False
            receipt.write_text(json.dumps(record))
            with self.assertRaises(ValueError): m.audit(out)
            receipt.write_bytes(saved)
            with patch.object(m, 'sources', return_value={'changed': 'source'}):
                with self.assertRaises(ValueError): m.audit(out)
            rtl = out / m.BOARD
            original = rtl.read_bytes()
            rtl.write_bytes(original.replace(b'.rx_clock(clk_rx_capture)', b'.rx_clock(clk_rx)'))
            with self.assertRaises(ValueError): m.audit(out)
            rtl.write_bytes(original)
            extra = out / 'extra.sv'; extra.write_text('module bad; endmodule')
            with self.assertRaises(ValueError): m.audit(out)
            extra.unlink()
            (out / 'native_rx_falling_pair.sv').unlink()
            with self.assertRaises(ValueError): m.audit(out)

    def test_changed_source_during_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with patch.object(m, 'sources', side_effect=[{}, {'changed': 'source'}]):
                with self.assertRaises(ValueError): m.export(out)
            self.assertFalse(out.exists())

if __name__ == '__main__': unittest.main()
