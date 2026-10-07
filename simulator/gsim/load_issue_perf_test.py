#!/usr/bin/env python3
"""Pure tests for performance receipt accounting and ROI isolation."""
import unittest
from load_issue_perf import board_rows

class BoardRowsTest(unittest.TestCase):
    whole = 'BOARD_IPC name=whole_run_after_reset_includes_UART cycles=5 retired=4 ipc=0.8 zero_commit=2 single_commit=2 dual_commit=1'
    roi = 'BOARD_IPC name=first_start_time_rdtime_retire_through_stop_time_rdtime_retire_inclusive cycles=2 retired=3 ipc=1.5 zero_commit=0 single_commit=1 dual_commit=1'

    def test_only_coremark_may_have_pc_roi(self):
        self.assertEqual(len(board_rows(self.whole + '\n' + self.roi, False)), 1)
        self.assertEqual(len(board_rows(self.whole + '\n' + self.roi, True)), 2)

    def test_reject_bad_retirement_accounting(self):
        with self.assertRaisesRegex(RuntimeError, 'histogram'):
            board_rows(self.whole.replace('retired=4', 'retired=5'), False)

    def test_reject_bad_cycle_accounting(self):
        with self.assertRaisesRegex(RuntimeError, 'histogram'):
            board_rows(self.whole.replace('cycles=5', 'cycles=6'), False)

if __name__ == '__main__':
    unittest.main()
