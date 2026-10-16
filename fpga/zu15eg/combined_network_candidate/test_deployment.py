"""Cloud Tcl loading and exact scope regressions; no Vivado/netlist claims."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

class DeploymentTests(unittest.TestCase):
    def test_tcl_load_in_sealed_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); board = root/'export/board'; board.mkdir(parents=True)
            scripts = root/'scripts'; scripts.mkdir()
            for path in HERE.parent.glob('*.tcl'): shutil.copy(path, board/path.name)
            for name in ('trispeed_board_constraints_v1.tcl', 'native_quarter_clock_constraints_v1.tcl'):
                shutil.copy(HERE/name, board/name)
            shutil.copy(HERE/'board_controls_v1.tcl', scripts/'board_controls.tcl')
            command = f'source {{{scripts}/board_controls.tcl}}\n'
            command += 'foreach p {v_apply_board_constraints valence_quarter_tx_clocks valence_trispeed_board_constraints} {if {[llength [info procs $p]] != 1} {error "missing $p"}}\nputs LOADED\n'
            result = subprocess.run(['tclsh'], input=command, text=True, capture_output=True)
            self.assertEqual(result.stderr, '', result.stderr)
            self.assertEqual(result.stdout.strip(), 'LOADED')

    def test_only_existing_reset_exception_scope(self):
        old = (ROOT/'fpga/next/physical_eval/board_controls.tcl').read_text()
        new = (HERE/'board_controls_v1.tcl').read_text()
        self.assertEqual([x.strip() for x in old.splitlines() if 'set_false_path' in x],
                         [x.strip() for x in new.splitlines() if 'set_false_path' in x])
        self.assertIn('foreach div {network_clock/enabled/raw_div}', new)
        self.assertNotIn('network_clock/quarter_div', new)
        self.assertNotIn('network_clock/enabled/pad_buffer/CLR', new)
        self.assertIn('network_clock/enabled/pad_buffer/O]] ne $clock', new)
        for path in HERE.glob('*_v1.tcl'):
            text = path.read_text()
            for forbidden in ('set_clock_groups', 'set_multicycle_path', 'set_clock_latency', 'set_min_delay'):
                self.assertNotIn(forbidden, text)

    def test_io_budget_unchanged(self):
        old = (HERE.parent/'trispeed_board_constraints.tcl').read_text()
        new = (HERE/'trispeed_board_constraints_v1.tcl').read_text()
        start = 'proc valence_trispeed_rx_constraints'; end = 'proc valence_trispeed_same_net'
        self.assertEqual(old[old.index(start):old.index(end)], new[new.index(start):new.index(end)])
        self.assertIn('ne "phy_rx"', new)
        self.assertIn('i < 10', new)
        self.assertIn('whole pair reset epoch', new)
        clock = (HERE/'native_quarter_clock_constraints_v1.tcl').read_text()
        original = (HERE.parent/'native_quarter_clock_constraints.tcl').read_text()
        tail = 'proc valence_quarter_data_pin'
        self.assertEqual(clock[clock.index(tail):], original[original.index(tail):])

if __name__ == '__main__': unittest.main()
