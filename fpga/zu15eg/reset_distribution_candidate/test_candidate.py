"""Host Tcl guard fixtures only. No hardware, placement, or timing claim."""
from pathlib import Path
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
MOCK = r'''
set mode MODE
set changes 0
set created 0
set audit 0
proc valence_trispeed_quarter_audit {hier mode} {
    if {$::mode eq "audit_fail"} {error "production proof failed"}
    if {$mode != 1} {error "wrong mode"}
    incr ::audit
}
proc get_cells {args} {
    if {[lsearch $args -of_objects]>=0 && $::mode eq "extra_cell"} {return {u/pad_release.pad_release_reset_reg other}}
    return u/pad_release.pad_release_reset_reg
}
proc get_pins {args} {
    if {[lsearch $args -leaf]>=0} {
        if {[lindex $args 2] eq "PRE"} {return upstream/Q}
        set r {u/phase_high_reg/PRE u/previous_clock_reg/CLR u/low_clock_reg/CLR u/high_clock_reg/CLR u/tx_clock_ddr/RST}
        for {set n 0} {$n<5} {incr n} {
            lappend r [format {u/low_symbol_reg[%d]/CLR} $n] [format {u/high_symbol_reg[%d]/CLR} $n] [format {u/transmit[%d].data_ddr/RST} $n]
        }
        if {$::mode eq "missing_sink"} {set r [lrange $r 1 end]}
        if {$::mode eq "extra_sink"} {lappend r clone/PRE}
        return $r
    }
    return [lindex $args end]
}
proc get_nets {args} {return [lindex [split [lindex $args end] /] end]}
proc get_clocks {args} {if {$::mode eq "no_clock"} {return {}};return PAD}
proc get_property {key obj} {
    switch -- $key {
        REF_NAME {if {$::mode eq "wrong_ff"} {return FDCE};return FDPE}
        INIT {return 1'b1}
        IS_INVERTED {if {$::mode eq "wrong_edge"} {return 0};return 1}
        TYPE {if {$obj eq "D"} {return GROUND};return POWER}
        PERIOD {if {$::mode eq "wrong_period"} {return 8};return 4}
        WAVEFORM {if {$::mode eq "wrong_phase"} {return {1 3}};return {0 2}}
        IS_LOC_FIXED {return [expr {$::mode eq "fixed_loc"}]}
        IS_BEL_FIXED {return [expr {$::mode eq "fixed_bel"}]}
        SITE_TYPE {if {$::mode eq "wrong_site"} {return RAMB36};return SLICEL}
    }
    error "unmocked property $key"
}
proc get_pblocks {args} {
    if {[lsearch $args -of_objects]>=0} {if {$::mode eq "owned"} {return old};return {}}
    if {$::created || $::mode eq "exists"} {return candidate};return {}
}
proc get_sites {args} {if {$::mode eq "missing_site"} {return {}};return [lindex $args end]}
proc get_clock_regions {args} {if {$::mode eq "cross_region"} {return {X0Y0 X0Y1}};return X0Y1}
proc create_pblock {args} {incr ::changes;set ::created 1}
proc resize_pblock {args} {incr ::changes}
proc add_cells_to_pblock {args} {incr ::changes}
proc set_property {args} {incr ::changes}
'''


def run_tcl(script):
    # tclsh reading stdin may return zero after a Tcl error: explicitly exit.
    wrapped = 'if {[catch {\n' + script + '\n} why]} {puts stderr $why; exit 1}\n'
    return subprocess.run(['tclsh'], input=wrapped, text=True, capture_output=True, check=False)


class Candidate(unittest.TestCase):
    def test_source_is_inert(self):
        result = run_tcl(f'source {{{HERE / "candidate.tcl"}}}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def fixture(self, mode, region='SLICE_X109Y120:SLICE_X116Y139'):
        script = MOCK.replace('set mode MODE', 'set mode ' + mode)
        script += f'\nsource {{{HERE / "candidate.tcl"}}}\n'
        script += f'set code [catch {{valence_reset_distribution::apply u {region}}} why]\n'
        script += 'puts [list $code $changes $audit $why]\n'
        result = run_tcl(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().splitlines()[-1]

    def test_valid_one_cell_region(self):
        self.assertTrue(self.fixture('good').startswith('0 4 1 '))

    def test_guard_rejections_before_mutation(self):
        for mode in ['audit_fail', 'wrong_ff', 'wrong_edge', 'missing_sink', 'extra_sink',
                     'no_clock', 'wrong_period', 'wrong_phase', 'fixed_loc', 'fixed_bel',
                     'owned', 'exists', 'missing_site', 'wrong_site', 'cross_region']:
            with self.subTest(mode=mode):
                self.assertTrue(self.fixture(mode).startswith('1 0 '), self.fixture(mode))

    def test_invalid_bounds_before_mutation(self):
        for region in ['SLICE_X116Y120:SLICE_X109Y139', 'SLICE_X0Y0:SLICE_X100Y100', 'nonsense']:
            with self.subTest(region=region):
                self.assertTrue(self.fixture('good', region).startswith('1 0 0 '))

    def test_extra_cell_postcondition_rejected(self):
        self.assertTrue(self.fixture('extra_cell').startswith('1 4 1 '))


if __name__ == '__main__':
    unittest.main()
