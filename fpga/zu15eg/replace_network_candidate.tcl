# Incremental ECO: two changed CPU-domain leaves plus INIT-only BootROM.
# No new clock exceptions, frequency changes, or I/O timing relaxations.
if {$argc != 3} {error "Expected PRIVATE_ROOT DONOR_ROOT prepare|route"}
lassign $argv root donor mode
foreach name {root donor} {set $name [file normalize [set $name]]}
if {$mode ni {prepare route}} {error "Unknown ECO phase"}
set out [file join $root implementation-report-recovery-r1]
set checkpoint [file join $donor implementation-report-recovery-r1 routed.dcp]
file mkdir $out
set_param general.maxThreads 8
proc is_mem_init {p} {return [regexp {^INIT(P)?_[0-9A-F]{2}$} $p]}
proc snapshot_rom {dcp} {
    open_checkpoint $dcp
    set shape [dict create]
    set contents [dict create]
    foreach cell [lsort [get_cells -hier -filter {IS_PRIMITIVE == 1}]] {
        set name [get_property NAME $cell]
        set ref [get_property REF_NAME $cell]
        set config [dict create REF_NAME $ref]
        set init [dict create]
        foreach line [split [report_property -return_string $cell] "\n"] {
            if {![regexp {^\s*(\S+)\s+\S+\s+false\s+} $line -> prop]} {continue}
            if {[string match RAMB* $ref] && [is_mem_init $prop]} {
                dict set init $prop [get_property $prop $cell]
            } else {
                dict set config $prop [get_property $prop $cell]
            }
        }
        set wiring [dict create]
        foreach pin [lsort [get_pins -of_objects $cell]] {
            set names {}
            foreach net [get_nets -quiet -of_objects $pin] {lappend names [get_property NAME $net]}
            dict set wiring [get_property REF_PIN_NAME $pin] [lsort $names]
        }
        dict set shape $name [list $config $wiring]
        if {[dict size $init]} {dict set contents $name $init}
    }
    set ports [dict create]
    foreach p [lsort [get_ports]] {
        set names {}
        foreach net [get_nets -quiet -of_objects $p] {lappend names [get_property NAME $net]}
        dict set ports [get_property NAME $p] [list [get_property DIRECTION $p] [lsort $names]]
    }
    close_design
    return [list $shape $contents $ports]
}
proc read_value {path} {set f [open $path r]; set value [read $f]; close $f; return $value}
proc write_value {path value} {set f [open $path w]; puts $f $value; close $f}
set leaves {u_soc/platform/privateCache u_soc/platform/packetDma}
set tops {CoherentLineCache EthernetPacketDma}
if {$mode eq "prepare"} {
    if {[file exists [file join $out patched_boundary_pending.dcp]]} {error "Preserve prepared checkpoint"}
    lassign [snapshot_rom [file join $donor ip-build board_ip.gen sources_1 ip blk_mem_gen_0 blk_mem_gen_0.dcp]] oldShape oldInit oldPorts
    lassign [snapshot_rom [file join $root ip-build board_ip.gen sources_1 ip blk_mem_gen_0 blk_mem_gen_0.dcp]] newShape newInit newPorts
    if {[dict keys $oldShape] ne [dict keys $newShape] || $oldPorts ne $newPorts} {error "ROM shape/ports changed"}
    dict for {name value} $oldShape {
        if {$value ne [dict get $newShape $name]} {error "ROM non-INIT config/wiring changed: $name"}
    }
    if {[dict size $newInit] != 29 || [dict keys $oldInit] ne [dict keys $newInit]} {error "ROM BRAM mapping changed"}
    open_checkpoint $checkpoint
    if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Donor part changed"}
    set frozen [dict create]
    foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
        set name [get_property NAME $cell]
        set affected 0
        foreach leaf $leaves {if {[string match "$leaf/*" $name]} {set affected 1}}
        if {!$affected} {dict set frozen $name [list [get_property LOC $cell] [get_property BEL $cell]]}
    }
    if {[dict size $frozen] < 10000} {error "Unexpected donor placement coverage"}
    write_value [file join $out frozen_placement.tcldict] $frozen
    dict for {name values} $oldInit {
        set cell [get_cells "u_soc/platform/rom/memory/$name"]
        if {[llength $cell] != 1} {error "Missing donor ROM BRAM"}
        dict for {property expected} $values {
            if {[get_property $property $cell] ne $expected} {error "Donor ROM identity mismatch"}
        }
    }
    set boundary [dict create]
    foreach leaf $leaves top $tops {
        set cell [get_cells -quiet $leaf]
        if {[llength $cell]!=1 || [get_property REF_NAME $cell] ne $top} {error "Wrong partition: $leaf"}
        foreach pin [get_pins -of_objects $cell -filter {DIRECTION == IN}] {
            set drivers {}
            foreach net [get_nets -quiet -segments -of_objects $pin] {
                foreach driver [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}] {
                    set owner [get_cells -of_objects $driver]
                    lappend drivers [list [get_property NAME $driver] [get_property REF_NAME $owner]]
                }
            }
            dict set boundary [get_property NAME $pin] [lsort -unique $drivers]
        }
        update_design -cells $cell -black_box
        update_design -cells $cell -strict -from_file [file join $root partitions $top leaf_alias.edf]
    }
    write_value [file join $out donor_boundary_drivers.tcldict] $boundary
    set count 0
    dict for {name values} $newInit {
        set cell [get_cells "u_soc/platform/rom/memory/$name"]
        dict for {property expected} $values {
            set_property $property $expected $cell
            if {[get_property $property $cell] ne $expected} {error "ROM INIT readback mismatch"}
            incr count
        }
    }
    if {$count!=4176} {error "Incomplete ROM update"}
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved partitions"}
    write_checkpoint [file join $out patched_boundary_pending.dcp]
    set report [open [file join $out imported_boundary_inputs.txt] w]
    set dangling 0
    foreach leaf $leaves {
        foreach pin [get_pins -of_objects [get_cells $leaf] -filter {DIRECTION == IN}] {
            set drivers {}
            set sinks {}
            foreach net [get_nets -quiet -segments -of_objects $pin] {
                foreach driver [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}] {
                    lappend drivers [get_property NAME $driver]
                }
                foreach sink [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == IN}] {
                    lappend sinks [get_property NAME $sink]
                }
            }
            set name [get_property NAME $pin]
            set previous [expr {[dict exists $boundary $name] ? [dict get $boundary $name] : "ABSENT"}]
            puts $report "PIN=$name DRIVERS=[lsort -unique $drivers] SINKS=[llength [lsort -unique $sinks]] OLD=$previous"
            if {![llength $drivers] && [llength $sinks]} {incr dangling; puts $report "DANGLING_USED_INPUT=$name"}
        }
    }
    puts $report "DANGLING_COUNT=$dangling"
    close $report
    puts "NETBOOT_ECO_PREPARED frozen=[dict size $frozen] INIT_MATCH=4176 DANGLING_USED_INPUTS=$dangling"
    close_design
    exit
}
if {[file exists [file join $out routed.dcp]]} {error "Preserve prior routed evidence"}
open_checkpoint [file join $out patched_boundary_pending.dcp]
# The imported partition may revive inputs pruned in the old whole-board context.
# Never tie such a pin off without independent proof of its actual RTL driver.
set text [read_value [file join $out imported_boundary_inputs.txt]]
if {![regexp {DANGLING_COUNT=0(?:\s|$)} $text]} {error "Imported boundary needs independent constant/connection review"}
set frozen [read_value [file join $out frozen_placement.tcldict]]
source [file join $root scripts native_quarter_clock_constraints.tcl]
foreach {pin period} {
    u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0 u_soc/nativeBank/uart/uart/clock 20.0
    u_soc/io_nativeGmac_rawTxClock 8.0 u_rgmii/delay_clock 2.0
    u_rgmii/tx_clock_ddr/CLK 4.0 u_ddr/c0_ddr4_ui_clk 4.0
} {
    set clock [get_clocks -quiet -of_objects [get_pins $pin]]
    if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-$period)>0.001} {error "Actual clock changed at $pin"}
}
lock_design -level placement
place_design -directive Quick
write_checkpoint [file join $out eco_placed.dcp]
route_design -directive Quick -preserve
dict for {name expected} $frozen {
    set cell [get_cells -quiet $name]
    if {[llength $cell]!=1 || [list [get_property LOC $cell] [get_property BEL $cell]] ne $expected} {
        error "Unrelated donor placement moved: $name"
    }
}
write_checkpoint [file join $out routed.dcp]
set pads [valence_quarter_tx_audit u_rgmii]
set audit [open [file join $out quarter_tx_identity.txt] w]
puts $audit "PASS_NATIVE_QUARTER_TX_TOPOLOGY SIX_COMMON_CLK250_RESET FIVE_EXACT_D0_D4_PAIRS PHASE_FEEDBACK"
puts $audit "ACTUAL_VALIDATED_DATA_PADS=$pads"
close $audit
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_timing -delay_type max -max_paths 40 -input_pins -file [file join $out setup_paths.rpt]
report_timing -delay_type min -max_paths 30 -input_pins -file [file join $out hold_paths.rpt]
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_clock_interaction -file [file join $out clock_interaction.rpt]
report_cdc -details -file [file join $out cdc.rpt]
report_bus_skew -warn_on_violation -file [file join $out bus_skew.rpt]
report_route_status -file [file join $out route_status.rpt]
report_exceptions -coverage -file [file join $out exception_coverage.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_drc -file [file join $out drc.rpt]
report_clocks -file [file join $out routed_clocks.rpt]
set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
report_timing -from $cpuClock -to $cpuClock -delay_type min_max -max_paths 20 -input_pins -file [file join $out cpu_paths.rpt]
foreach direction {tx rx} {
    set report [file join $out ${direction}_io.rpt]
    set f [open $report w]; close $f
    set endpoints [get_ports [list eth_${direction}d\[*\] eth_${direction}_ctl]]
    if {[llength $endpoints]!=5} {error "Missing physical $direction lanes"}
    foreach port $endpoints {
        foreach delay {max min} {
            if {$direction eq "tx"} {
                set path [get_timing_paths -to $port -delay_type $delay -max_paths 1]
                if {[llength $path]!=1} {error "Untimed TX"}
                set required [expr {$delay eq "max" ? 2.0 : -2.0}]
                if {abs([get_property REQUIREMENT $path]-$required)>0.001} {error "Changed TX edge"}
                report_timing -to $port -delay_type $delay -max_paths 1 -input_pins -append -file $report
            } else {
                set path [get_timing_paths -from $port -delay_type $delay -max_paths 1]
                if {[llength $path]!=1} {error "Untimed RX"}
                report_timing -from $port -delay_type $delay -max_paths 1 -input_pins -append -file $report
            }
            if {[get_property SLACK $path] in {inf -inf}} {error "Infinite I/O timing"}
        }
    }
}
set clearPins {}
foreach name {raw_div quarter_div} {lappend clearPins [get_pins centered_tx_clock.clock_dut/$name/CLR]}
report_timing -to $clearPins -delay_type min_max -max_paths 12 -input_pins -file [file join $out divider_clear.rpt]
write_xdc -type timing [file join $out routed_constraints.xdc]
puts "NETBOOT_ECO_ROUTE_COMPLETE NO_BIT_GENERATED FULL_SIGNOFF_REQUIRED"
close_design
