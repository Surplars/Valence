"""Source-transformation guards; actual diagnostic replay has its own receipt."""
import unittest
from pathlib import Path
import cpu_mlp_retire_attribution as attribution

class InstrumentationTests(unittest.TestCase):
    def setUp(self):
        self.source=(Path(__file__).parent/'harness/cpu_flow_bandwidth.cpp').read_text()
    def test_current_source_has_all_passive_checks(self):
        text=attribution.instrument(self.source)
        for field in ('orderCheckValid','replayPendingValid','branchRedirectValid','ledger$recoveryCycle',
                      'ledger$recovering','ledger$acceptRecovery','ledger$entries$$exception'):
            self.assertIn(attribution.PREFIX+field,text)
        self.assertIn('exact done-head commit equation mismatch',text)
        self.assertIn('load-order check history mismatch',text)
        self.assertIn('verifyTerminalDrain();terminalDrainNegatives();',text)
    def test_missing_anchor_rejected(self):
        with self.assertRaises(RuntimeError):
            attribution.instrument(self.source.replace('    PerfCounts perf;','    PerfCounts renamed;'))
    def test_ambiguous_anchor_rejected(self):
        with self.assertRaises(RuntimeError):
            attribution.instrument(self.source+'\n    PerfCounts perf;\n')
    def test_double_instrumentation_rejected(self):
        with self.assertRaises(RuntimeError):
            attribution.instrument(attribution.instrument(self.source))

if __name__=='__main__':unittest.main()
