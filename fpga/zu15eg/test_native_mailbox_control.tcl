# Pure evaluator tests in Vivado's Tcl interpreter; no design or DCP opened.
source [file join [file dirname [info script]] native_mailbox_truth.tcl]
set roles [dict create held H captured Q valid V request R ack A]
set fixture {}
proc fixture_resolver {pin} {
    global fixture
    if {![dict exists $fixture $pin]} {error "Unmodelled fixture leaf $pin"}
    return [dict get $fixture $pin]
}
set cases 0
proc expect_reject {label pattern code} {
    global cases
    set status [catch {uplevel 1 $code} value]
    if {!$status || ![string match $pattern $value]} {error "Negative test $label did not reject correctly: $status $value"}
    incr cases
}
dict set fixture ONE [dict create type CONST value 1]
dict set fixture ZERO [dict create type CONST value 0]
# Fixed independently generated LUT for H,Q,V,R,A, I0 is the lowest index bit.
dict set fixture D [dict create type LUT width 5 init 0xcccacacc inputs {H Q V R A}]
if {[native_mbox_check_next D ONE $roles fixture_resolver] != 32} {error "Good D-mux rejected"}
incr cases
# Equivalent CE-mapped implementation, not merely the same netlist shape.
dict set fixture CE [dict create type LUT width 3 init 0x14 inputs {V R A}]
if {[native_mbox_check_next H CE $roles fixture_resolver] != 32} {error "Good CE-mux rejected"}
incr cases
set fixture_saved $fixture
dict set fixture D init 0xcccacacd
expect_reject corrupted_init {Mailbox next-state mismatch*} {native_mbox_check_next D ONE $roles fixture_resolver}
set fixture $fixture_saved
expect_reject disabled_capture {Mailbox next-state mismatch*} {native_mbox_check_next D ZERO $roles fixture_resolver}
expect_reject transparent_capture {Mailbox next-state mismatch*} {native_mbox_check_next H ONE $roles fixture_resolver}
expect_reject unknown_leaf {Unmodelled fixture leaf*} {native_mbox_check_next UNMODELED ONE $roles fixture_resolver}
dict set fixture D [dict create type INV inputs D]
expect_reject combinational_cycle {Mailbox combinational cycle*} {native_mbox_check_next D ONE $roles fixture_resolver}
set fixture $fixture_saved
dict set fixture D width 7
expect_reject excessive_width {Invalid mailbox LUT description*} {native_mbox_check_next D ONE $roles fixture_resolver}
set fixture $fixture_saved
dict set fixture D init 0x100000000
expect_reject oversized_init {Invalid mailbox LUT description*} {native_mbox_check_next D ONE $roles fixture_resolver}
set fixture $fixture_saved
expect_reject alias {Aliased mailbox roles*} {native_mbox_check_next D ONE [dict replace $roles held Q] fixture_resolver}
expect_reject input_override {Mailbox role overwritten*} {native_mbox_check_next D ONE $roles fixture_resolver [dict create H 0]}
dict set fixture INVERT [dict create type INV inputs H]
dict set fixture MUX [dict create type MUX inputs {H Q V}]
foreach h {0 1} {
    foreach q {0 1} {
        foreach v {0 1} {
            set values [dict create H $h Q $q V $v]
            set memo {}
            if {[native_mbox_eval INVERT $values memo fixture_resolver] != !$h} {error "INV primitive mismatch"}
            if {[native_mbox_eval MUX $values memo fixture_resolver] != ($v ? $q : $h)} {error "MUX primitive mismatch"}
        }
    }
}
incr cases
# Every grammar token in the actual resolver must be legal Tcl. These tests
# parse its full body without loading a checkpoint or mocking real topology.
set f [open [file join [file dirname [info script]] review_native_mailbox_control.tcl] r]
set review [read $f]
close $f
if {![info complete $review]} {error "Incomplete actual-review Tcl source"}
foreach hex {0 CCCACACC FFFFFFFFFFFFFFFF} {
    if {[expr [format {0x%s} $hex]] < 0} {error "Unsigned LUT INIT parsing"}
}
incr cases
puts "PASS_NATIVE_MAILBOX_TRUTH_UNIT cases=$cases positive_next_state_rows=64 independent_negatives=9 PRIMITIVES_ONLY_NO_DCP_NO_HARDWARE_PROOF"
exit
