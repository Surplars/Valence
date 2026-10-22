# Connectivity/property mocks only, not native netlist or timing qualification.
source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
foreach command {set_max_delay set_min_delay set_bus_skew set_false_path set_clock_groups set_property} {
    proc $command args {error UNEXPECTED_CONSTRAINT_MUTATION}
}
proc reset_fixture {} {
    set ::refs [dict create m/held_reg FDRE m/captured_reg FDRE m/valid_reg FDCE \
        {m/requestSync/stages_reg[1]} FDCE m/ackToggle_reg FDCE m/captured_i_1 LUT5 \
        m/held_i_1 LUT6 {m/sourceRelease/release_0_reg[2]} FDPE \
        {m/ackSync/stages_reg[1]} FDCE m/requestToggle_reg FDCE upstream_data FDRE upstream_valid FDRE]
    set ::clocks [dict create m/sourceClock fabric m/destinationClock aon m/held_reg/C fabric]
    foreach c [dict keys $::refs] {
        if {$c ne {m/held_reg}} {dict set ::clocks $c/C aon}
    }
    foreach c {m/held_reg {m/sourceRelease/release_0_reg[2]} {m/ackSync/stages_reg[1]} m/requestToggle_reg upstream_data upstream_valid} {
        dict set ::clocks $c/C fabric
    }
    set ::drivers [dict create m/destination_bits m/captured_reg/Q m/captured_reg/D m/captured_i_1/O \
        m/captured_i_1/I0 m/held_reg/Q m/captured_i_1/I1 m/valid_reg/Q \
        m/captured_i_1/I2 {m/requestSync/stages_reg[1]/Q} m/captured_i_1/I3 m/ackToggle_reg/Q \
        m/captured_i_1/I4 m/captured_reg/Q m/source_bits upstream_data/Q m/source_valid upstream_valid/Q \
        m/held_reg/D m/held_i_1/O m/held_i_1/I0 upstream_data/Q \
        m/held_i_1/I1 {m/sourceRelease/release_0_reg[2]/Q} m/held_i_1/I2 {m/ackSync/stages_reg[1]/Q} \
        m/held_i_1/I3 m/requestToggle_reg/Q m/held_i_1/I4 upstream_valid/Q m/held_i_1/I5 m/held_reg/Q]
    set ::constants [dict create m/captured_reg/CE 1 m/captured_reg/R 0 m/held_reg/CE 1 m/held_reg/R 0]
    set ::init 32'hFEEF0220; set ::held_init 64'hEFFEFFFF20020000
    set ::inverted 0; set ::inversions {}
}
proc get_cells args {
    set result {}; foreach c [dict keys $::refs] {if {[regexp [lindex $args end] $c]} {lappend result $c}}
    return $result
}
proc get_pins args {
    set pins {m/source_bits m/source_valid m/destination_bits m/sourceClock m/destinationClock}
    foreach c [dict keys $::refs] {foreach p {C D Q CE R I0 I1 I2 I3 I4 I5 O} {lappend pins $c/$p}}
    set result {}; foreach p $pins {if {[regexp [lindex $args end] $p]} {lappend result $p}}
    return $result
}
proc get_clocks args {return [lindex $args end]}
proc get_property {key object} {
    set object [lindex $object 0]
    switch $key {
        NAME {return $object}
        REF_NAME {return [dict get $::refs $object]}
        IS_INVERTED {if {[dict exists $::inversions $object]} {return [dict get $::inversions $object]}; return $::inverted}
        INIT {if {$object eq {m/held_i_1}} {return $::held_init}; return $::init}
        PERIOD {return [dict get {fabric 4.0 aon 20.0} $object]}
        default {error "unexpected property $key $object"}
    }
}
proc common_cdc::clock pin {return [dict get $::clocks $pin]}
proc common_cdc::drivers pin {if {[dict exists $::drivers $pin]} {return [list [dict get $::drivers $pin]]};return {}}
proc common_cdc::loads pin {
    set result {};dict for {sink source} $::drivers {if {$source eq $pin} {lappend result $sink}}
    return [lsort $result]
}
proc common_cdc::constant {pin value} {
    if {![dict exists $::constants $pin] || [dict get $::constants $pin]!=$value} {error "COMMON_CDC $pin not constant $value"}
}
proc checked_scope {} {
    set s [common_cdc::mailbox_width m 1 fabric aon]
    assert {[dict get $s starts] eq {m/held_reg/C}} {source launch changed}
    assert {[dict get $s ends] eq {m/captured_reg/D}} {capture endpoint changed}
    assert {[dict get $s budget]==4.0 && [dict get $s skew]==0} {CDC budget relaxed}
}
proc reject {mutation diagnostic} {
    reset_fixture; uplevel 1 $mutation
    assert {[catch {checked_scope} why]} "mutation accepted: $mutation"
    assert {[string match $diagnostic $why]} "wrong rejection for $mutation: $why"
}
reset_fixture; checked_scope
# Original direct capture form remains supported with the same scope/budget.
reset_fixture; dict unset ::drivers m/captured_i_1/I0; dict set ::drivers m/captured_reg/D m/held_reg/Q
checked_scope
# Retain the original all-direct mapping-only contract, not a new CE/functional proof.
dict unset ::drivers m/held_i_1/I5; dict set ::drivers m/held_reg/D upstream_data/Q
checked_scope
# Equivalent pin permutation must pass based on connectivity/truth, not INIT alone.
reset_fixture; dict set ::drivers m/captured_i_1/I0 m/captured_reg/Q; dict set ::drivers m/captured_i_1/I4 m/held_reg/Q
set permuted 0
for {set row 0} {$row<32} {incr row} {
    set original [expr {($row & 14) | (($row & 1) << 4) | (($row >> 4) & 1)}]
    if {(0xFEEF0220 >> $original) & 1} {set permuted [expr {$permuted | (1 << $row)}]}
}
set ::init [format {32'h%08X} $permuted]; checked_scope
# A source-side input permutation is also proved from all 64 rows.
reset_fixture; dict set ::drivers m/held_i_1/I0 m/held_reg/Q; dict set ::drivers m/held_i_1/I5 upstream_data/Q
set permuted 0
for {set row 0} {$row<64} {incr row} {
    set original [expr {($row & 30) | (($row & 1) << 5) | (($row >> 5) & 1)}]
    if {(0xEFFEFFFF20020000 >> $original) & 1} {set permuted [expr {$permuted | (1 << $row)}]}
}
set ::held_init [format {64'h%016X} $permuted]; checked_scope
# Every single truth-table bit mutation enters the ordinary checker.
for {set row 0} {$row<64} {incr row} {
    reject {set ::held_init [format {64'h%016X} [expr {0xEFFEFFFF20020000 ^ (1 << $row)}]]} {*held truth table changed*}
}
foreach control {{m/sourceRelease/release_0_reg[2]} {m/ackSync/stages_reg[1]} m/requestToggle_reg upstream_data upstream_valid} {
    reject {dict set ::clocks $control/C aon} {*non-FF/wrong clock*}
}
reject {dict set ::drivers m/held_i_1/I1 {m/sourceRelease/release_0_reg[1]/Q}} {*held unknown input*}
reject {dict set ::drivers m/held_i_1/I2 {m/ackSync/stages_reg[0]/Q}} {*held unknown input*}
reject {dict set ::drivers m/held_i_1/I3 m/ackToggle_reg/Q} {*held unknown input*}
reject {dict set ::drivers m/held_i_1/I5 upstream_data/Q} {*held input census changed*}
reject {dict set ::drivers m/source_bits unrelated/O} {*must be one source FF Q*}
reject {dict unset ::drivers m/source_valid} {*must be one source FF Q*}
reject {dict set ::drivers m/extra/D m/held_i_1/O} {*held LUT fanout changed*}
reject {dict set ::refs m/held_i_1 LUT5} {*without exact source feedback*}
reject {dict set ::drivers m/held_reg/D unrelated/O} {*without exact source feedback*}
reject {dict unset ::drivers m/held_i_1/I5; dict set ::drivers m/held_reg/D upstream_data/Q} {*without exact source feedback*}
reject {dict set ::refs m/held_reg FDCE} {*held requires FDRE*}
reject {dict set ::constants m/held_reg/CE 0} {*not constant 1*}
reject {dict set ::constants m/held_reg/R 1} {*not constant 0*}
foreach pin {D CE R} {
    foreach value {1 {}} {
        reject {dict set ::inversions m/held_reg/$pin $value} {*folded held inverted/unknown*}
    }
}
reject {set ::held_init 64'hXXXXXXXXXXXXXXXX} {*held unknown LUT INIT*}

for {set row 0} {$row<32} {incr row} {
    reject {set ::init [format {32'h%08X} [expr {0xFEEF0220 ^ (1 << $row)}]]} {*truth table changed*}
}
foreach control {m/valid_reg {m/requestSync/stages_reg[1]} m/ackToggle_reg m/captured_reg} {
    reject {dict set ::clocks $control/C fabric} {*non-FF/wrong clock*}
}
reject {dict set ::clocks m/held_reg/C aon} {*non-FF/wrong clock*}
reject {dict set ::drivers m/captured_i_1/I2 {m/requestSync/stages_reg[0]/Q}} {*unknown input*}
reject {dict set ::drivers m/captured_i_1/I1 m/requestToggle_reg/Q} {*unknown input*}
reject {dict set ::drivers m/captured_i_1/I4 m/held_reg/Q} {*input census changed*}
reject {dict set ::drivers m/captured_i_1/I4 unrelated/Q} {*unknown input*}
reject {dict set ::drivers m/extra/D m/held_reg/Q} {*held fanout changed*}
reject {dict set ::drivers m/extra/D m/captured_i_1/O} {*LUT fanout changed*}
reject {dict set ::constants m/captured_reg/CE 0} {*not constant 1*}
reject {dict set ::constants m/captured_reg/R 1} {*not constant 0*}
reject {dict set ::refs m/captured_reg FDCE} {*requires FDRE*}
reject {dict set ::refs m/captured_i_1 LUT6} {*not direct or exact LUT5*}
reject {dict set ::drivers m/captured_reg/D unrelated/O} {*not direct or exact LUT5*}
reject {dict set ::drivers m/destination_bits m/held_reg/Q} {*not captured Q*}
reject {dict set ::drivers m/destination_bits m/captured_i_1/O} {*not captured Q*}
reject {dict unset ::refs m/held_reg} {*exact bank changed/pruned*}
reject {dict set ::refs {m/captured_reg[0]} FDRE} {*exact bank changed/pruned*}
reject {set ::inverted 1} {*inverted clock*}
foreach pin {D CE R} {
    foreach value {1 {}} {
        reject {dict set ::inversions m/captured_reg/$pin $value} {*folded capture inverted/unknown*}
    }
}
reject {set ::init 32'hXXXXXXXX} {*unknown LUT INIT*}
puts SCALAR_MAILBOX_DIRECT_AND_FOLDED_MUX_PASS_NOT_NATIVE_QUALIFIED
