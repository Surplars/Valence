source [file join [file dirname [info script]] idelay_reset_replication.tcl]
rename idelay_reset_replication::reports idelay_reset_replication::native_reports
proc idelay_reset_replication::reports {post directory} {incr ::reports}
set reports 0
set calls 0
set mode good
set replicated 0
proc get_cells {args} {
    if {[lsearch -exact $args -of_objects] >= 0} {
        return [file dirname [lindex $args end]]
    }
    regexp {NAME == "(.*)"} [lindex $args end] -> name
    if {$::mode eq "missing" && $name eq "u_rgmii/delay_control_REPLICATED_0"} {return {}}
    return $name
}
proc get_pins {args} {
    if {[lsearch -exact $args -hier] >= 0} {
        regexp {NAME == "(.*)"} [lindex $args end] -> name
        return $name
    }
    set object [lindex $args [expr {[lsearch -exact $args -of_objects]+1}]]
    set filter [lindex $args end]
    if {[string match REF_PIN_NAME* $filter]} {return "$object/[lindex $filter end]"}
    if {$filter eq "DIRECTION == OUT"} {
        if {$object eq "resetnet"} {
            if {$::replicated} {return replica/Q}
            return {delay_reset_guard_reg[63]/Q}
        }
        return [string range $object 4 end]
    }
    set out {}
    dict for {name primitive} [idelay_reset_replication::expected] {lappend out $name/RST}
    if {$::mode eq "extra-load"} {lappend out rogue/RST}
    return $out
}
proc get_nets {args} {
    set p [lindex $args end]
    switch -glob -- $p {
        */RST - */Q {return resetnet}
        */D {if {$::mode eq "wrong-D"} {return net_other/Q}; return {net_delay_reset_guard_reg[62]/Q}}
        */PRE {return {net_delay_reset_pipe_reg[2]/Q}}
        */C {return net_delay_buffer/O}
        */CE {return net_VCC/P}
        */O {return rxnet}
    }
    error "unexpected net $p"
}
proc get_clocks {args} {return ref500}
proc get_property {property object} {
    switch -- $property {
        NAME {return $object}
        REF_NAME {
            if {[dict exists [idelay_reset_replication::expected] $object]} {
                return [dict get [idelay_reset_replication::expected] $object]
            }
            return FDPE
        }
        REF_PIN_NAME {return [file tail $object]}
        IS_PLACED {return [expr {$::mode ne "unplaced"}]}
        INIT {return 1}
        IS_C_INVERTED {return 0}
        PERIOD {if {$::mode eq "wrong-clock"} {return 4.0}; return 2.0}
        LOC {if {$::mode eq "post-move" && $::replicated} {return DIFFERENT}; return SITE_$object}
        BEL {return BEL_$object}
        DELAY_VALUE {if {$::mode eq "wrong-delay"} {return 550}; return 475}
        DELAY_FORMAT {return TIME}
        DELAY_TYPE {return FIXED}
        IODELAY_GROUP {return VALENCE_RGMII}
        REFCLK_FREQUENCY {return 500.0}
        CASCADE {if {[string match *input_delay $object]} {return MASTER}; return SLAVE_END}
        CLOCK_ROOT - USER_CLOCK_ROOT {if {$::mode eq "wrong-root"} {return X2Y3}; return X3Y2}
    }
    error "unexpected property $property $object"
}
proc phys_opt_design {args} {
    if {$args ne {-force_replication_on_nets resetnet}} {error "unexpected mutation $args"}
    incr ::calls
    set ::replicated 1
    if {$::mode eq "tool-error"} {error "uncertain native failure"}
}
proc reset_case {mode} {
    set ::mode $mode; set ::calls 0; set ::replicated 0
    set ::idelay_reset_replication::attempted 0
    unset -nocomplain ::idelay_reset_replication::baseline
}
foreach mode {missing extra-load wrong-D unplaced wrong-clock wrong-delay wrong-root} {
    reset_case $mode
    if {![catch {idelay_reset_replication::apply unused-test-directory} message]} {error "accepted $mode"}
    if {$calls != 0} {error "mutated invalid baseline $mode"}
}
reset_case good
set result [idelay_reset_replication::apply unused-test-directory]
if {$calls != 1 || [dict get $result status] ne "REQUIRES_ROUTE_AND_TIMING_VALIDATION"} {error "good case failed"}
if {![catch {idelay_reset_replication::apply unused-test-directory}]} {error "repeated mutation accepted"}
if {$calls != 1} {error "second mutation"}
foreach mode {post-move tool-error} {
    reset_case $mode
    if {![catch {idelay_reset_replication::apply unused-test-directory}]} {error "accepted $mode"}
    if {$calls != 1} {error "wrong mutation count"}
    if {![catch {idelay_reset_replication::apply unused-test-directory}]} {error "retry after uncertain failure"}
    if {$calls != 1} {error "retried after uncertain failure"}
}
puts "IDELAY_RESET_REPLICATION_PASS baseline_negative=7 post_negative=2 one_shot=1"
