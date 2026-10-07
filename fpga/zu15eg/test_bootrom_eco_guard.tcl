# Offline preflight/physical-snapshot tests. No Vivado, DCP or bit operation.
# Tests stop at the first ROM DCP open after the complete early profile gate.
if {$argc != 1} {error "Expected UPDATE_BOOTROM_SCRIPT"}
set f [open [lindex $argv 0] r]; set script [read $f]; close $f
if {![info complete $script]} {error "Incomplete ECO Tcl"}
set fixtures {
    legacy_preflight {} TEST_PREFLIGHT_PASSED
    legacy_prepare_preflight {set argc 6; lappend argv prepare-only soc.dcp} TEST_PREFLIGHT_PASSED
    wrong_argc {set argc 0} {Expected OLD_ROM_DCP}
    wrong_mode {set argc 6; lappend argv unsafe soc.dcp} {Expected prepare-only mode}
    occupied_output {set occupied 1} {Preserve existing output}
    missing_input {set readable 0} {Missing readable checkpoint}
    same_rom {lset argv 1 old.dcp} {Old and new ROM checkpoints must differ}
    wrong_part {set part wrong} {Wrong FPGA part}
    blackbox {set blackbox bb} {Unresolved black boxes}
    native_fpu {set fpu fpu} {Legacy DDR50 ECO cannot update native}
    native_gmac {set gmac gmac} {Legacy DDR50 ECO cannot update native}
    native_prepare {set argc 6; lappend argv prepare-only soc.dcp; set fpu fpu} {Legacy DDR50 ECO cannot update native}
    cpu100 {set period 10.0} {requires the actual CPU endpoint}
    cpu100_prepare {set argc 6; lappend argv prepare-only soc.dcp; set period 10.0} {requires the actual CPU endpoint}
    stray_legacy_clock {set actual other_clock} {requires the actual CPU endpoint}
    missing_cpu_pin {set endpoint {}} {Missing actual legacy CPU clock endpoint}
    multiple_cpu_clocks {set actual {cpu_clock other_clock}} {requires the actual CPU endpoint}
    missing_named_clock {set named {}} {requires the actual CPU endpoint}
    primary_not_generated {set generated 0} {requires the actual CPU endpoint}
    missing_region {set region_count 7} {Missing legacy AXI REGION pins}
    ungrounded_region {set net_type POWER} {REGION not grounded}
    disconnected_region {set region_net {}} {REGION not grounded}
}
set mocked {
    set argc 4; set argv {old.dcp new.dcp routed.dcp fresh-output}
    set occupied 0; set readable 1; set part xczu15eg-ffvb1156-2-i
    set blackbox {}; set fpu {}; set gmac {}; set endpoint u_soc/clock
    set actual cpu_clock; set named cpu_clock; set generated 1; set period 20.0
    set region_count 8; set region_net gnd; set net_type GROUND
    set events {}; set physical_changed 0
    rename file real_file
    proc file {op args} {
        switch -- $op {
            exists {return $::occupied}
            isfile - readable {return $::readable}
            mkdir {lappend ::events mkdir; error "Unexpected output creation"}
            default {return [real_file $op {*}$args]}
        }
    }
    proc set_param args {}
    proc open_checkpoint path {
        lappend ::events "open:$path"
        if {$path ne "routed.dcp"} {error TEST_PREFLIGHT_PASSED}
    }
    proc close_design args {}
    proc current_design args {return design}
    proc get_cells args {
        set query [lindex $args end]
        if {$query eq "IS_BLACKBOX"} {return $::blackbox}
        if {$query eq "REF_NAME == FloatingPointSystem"} {return $::fpu}
        if {$query eq "u_soc/nativeBank/gmac"} {return $::gmac}
        if {$query eq "IS_PRIMITIVE == 1"} {return {rom other}}
        error "Unexpected cell query: $args"
    }
    proc get_pins args {
        if {[lindex $args end] eq "u_soc/clock"} {return $::endpoint}
        set result {}; for {set i 0} {$i < $::region_count} {incr i} {lappend result region$i}
        return $result
    }
    proc get_clocks args {
        if {[lsearch -exact $args -of_objects] >= 0} {return $::actual}
        return $::named
    }
    proc get_nets args {
        if {$args eq "-hier"} {return {net0 net1}}
        return $::region_net
    }
    proc get_property {name object} {
        switch -- $name {
            PART {return $::part}
            NAME {return $object}
            PERIOD {return $::period}
            IS_GENERATED {return $::generated}
            TYPE {return $::net_type}
            REF_NAME {return [expr {$object eq "rom" ? "RAMB36E2" : "LUT1"}]}
            LOC {return "LOC_$object"}
            BEL {return "BEL_$object"}
            ROUTE {return "ROUTE_${object}_$::physical_changed"}
            default {error "Unexpected property: $name"}
        }
    }
    foreach command {set_property write_checkpoint write_bitstream write_debug_probes} {
        proc $command args {lappend ::events forbidden_write; error "Unexpected mutation/output"}
    }
}
set cases 0
foreach {label setup expected} $fixtures {
    set child [interp create]
    $child eval $mocked
    $child eval $setup
    set failed [catch {$child eval $script} detail]
    set events [$child eval {set events}]
    if {!$failed || [string first $expected $detail] < 0} {error "$label: unexpected result: $detail"}
    if {[lsearch -exact $events forbidden_write] >= 0 || [lsearch -exact $events mkdir] >= 0} {
        error "$label: mutation/output before preflight completed"
    }
    if {$expected eq "TEST_PREFLIGHT_PASSED"} {
        # Verify full-board snapshot identity and sensitivity to a route change.
        $child eval {
            set saved [snapshot_physical]
            if {[snapshot_physical] ne $saved} {error "Unchanged snapshot differs"}
            set physical_changed 1
            if {[snapshot_physical] eq $saved} {error "Route drift not detected"}
            foreach property {INIT_00 INIT_7F INITP_00 INITP_0F} {
                if {![is_mem_init $property]} {error "Missing memory INIT match"}
            }
            foreach property {INIT INIT_AAA INIT_FILE LUT_INIT INIT_gg} {
                if {[is_mem_init $property]} {error "Unexpected mutable memory property"}
            }
        }
    } elseif {[lsearch -exact $events open:old.dcp] >= 0} {
        error "$label: stale profile reached ROM processing"
    }
    interp delete $child
    incr cases
}
puts "PASS_BOOTROM_ECO_PREFLIGHT_UNIT cases=$cases MOCKED_NO_DCP_NO_VIVADO_NO_SIGNOFF_NO_BIT"
