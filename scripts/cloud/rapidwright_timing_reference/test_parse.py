#!/usr/bin/env python3
"""Pure parser tests; no Java, Vivado, routing or input mutation."""
import hashlib
import unittest
from run import parse_paths

REPORT = '''Report header
Slack (VIOLATED) : -0.100ns
 Source: top/start/C
 Destination: top/end/D
 Data Path Delay: 0.226ns (logic 0.126ns (55%) route 0.100ns (45%))
 SLICE_X0Y0 FDSE r top/start/C (IS_INVERTED)
 SLICE_X0Y0 FDSE (Prop_FFF_C_Q)
 0.076 1.076 r top/start/Q
 net (fo=1, estimated) 0.050 1.126 top/net1
 SLICE_X1Y0 r top/lut/I0
 SLICE_X1Y0 LUT4 (Prop_A6LUT_I0_O)
 0.050 1.176 r top/lut/O
 net (fo=1, routed) 0.050 1.226 top/net2
 SLICE_X1Y0 FDRE r top/end/D
'''
SELECTION = dict(label='test', source='top/start/C', destination='top/end/D', logic_arcs=2)

class ParseTests(unittest.TestCase):
    def test_complete_inverted_source(self):
        logic, nets, checks, matched = parse_paths(REPORT, [SELECTION])
        self.assertEqual((len(logic), len(nets)), (2, 2))
        self.assertEqual(matched[0]['vivado_logic_ps'], 126)
        self.assertEqual(checks, [['test', 'top/end', 'D']])

    def test_exact_source(self):
        with self.assertRaises(ValueError):
            parse_paths(REPORT, [dict(SELECTION, source='top/start/Cextra')])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            parse_paths(REPORT + REPORT, [SELECTION])

    def test_block_digest_disambiguates(self):
        alternate = REPORT.replace('0.076 1.076 r', '0.076 1.076 f')
        digest = hashlib.sha256(REPORT[REPORT.index('Slack ('):].encode()).hexdigest()
        # The following block starts immediately at Slack, avoiding extra headers.
        combined = REPORT + alternate[alternate.index('Slack ('):]
        self.assertEqual(len(parse_paths(combined, [dict(SELECTION, report_block_sha256=digest)])[0]), 2)

    def test_incomplete_arc_count(self):
        with self.assertRaises(ValueError):
            parse_paths(REPORT, [dict(SELECTION, logic_arcs=3)])

    def test_wrong_subtotal(self):
        with self.assertRaises(ValueError):
            parse_paths(REPORT.replace('logic 0.126ns', 'logic 0.127ns'), [SELECTION])

if __name__ == '__main__':
    unittest.main()
