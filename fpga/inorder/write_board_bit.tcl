# Generate only after reviewing a completed repaired board route. No RTL,
# implementation, clock, timing exception or DRC-severity changes are made.
if {$argc != 2} {error "usage: write_board_bit.tcl BOARD_ROOT REVIEWED_ROUTED_DCP"}
set root [file normalize [lindex $argv 0]]
set dcp [file normalize [lindex $argv 1]]
if {![string match */orbital-i1-cpu300-board-* $root] ||
    [string first "$root/" $dcp] != 0 || ![file isfile $dcp] ||
    ![file isfile [file join $root bootrom-prebuild-audit.json]] ||
    ![file isfile [file join $root reports bootrom_post_synth.txt]]} {
    error "Repaired isolated board with synthesized ROM and source proof required"
}
set out [file join $root bitstream]
if {[file exists $out]} {error "Preserve previous bitstream evidence"}
set_param general.maxThreads 8
open_checkpoint $dcp
if {[string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
    error "Wrong board part"
}
foreach {pin period} {u_soc/io_clockIn 3.3333333333 u_axi_cdc/m_axi_aclk 4.0
                     u_soc/io_alwaysOnClock 20.0 u_soc/io_uartClockIn 20.0} {
    set clock [get_clocks -of_objects [get_pins $pin]]
    if {[llength $clock] != 1 || abs([get_property PERIOD $clock]-$period) > 0.002} {
        error "Frozen clock changed: $pin"
    }
}
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
if {$setup < 0 || $hold < 0} {error "Refuse timing-failed bit: setup=$setup hold=$hold"}
if {[llength [get_cells -quiet -hier -filter {REF_NAME == BSCANE2 && JTAG_CHAIN == 2}]] != 1} {
    error "Exact USER2 BSCAN missing"
}
if {[llength [get_cells -quiet -hier -filter {REF_NAME =~ *Gmac* || REF_NAME =~ EthernetPacketDma* || NAME =~ *u_rgmii*}]]} {
    error "Unexpected MAC in no-MAC candidate"
}
file mkdir $out
# Use the release checker paired with this writer. It may improve evidence
# formatting without modifying the frozen synthesis inputs in root/scripts.
source [file join [file dirname [info script]] audit_board_bootrom.tcl]
i1_audit_bootrom [file join $root rtl bootrom.hex] [file join $out bootrom_pre_bit.txt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_route_status -file [file join $out route_status.rpt]
report_drc -file [file join $out drc.rpt]
report_cdc -details -file [file join $out cdc.rpt]
set f [open [file join $out timing_summary.rpt]]; set timing [read $f]; close $f
if {[string first "All user specified timing constraints are met." $timing] < 0} {
    error "Full timing including pulse-width checks did not pass"
}
foreach key {no_clock unconstrained_internal_endpoints multiple_clock generated_clocks loops latch_loops} {
    if {![regexp "checking $key \\(0\\)" $timing]} {error "Unqualified timing coverage: $key"}
}
set f [open [file join $out route_status.rpt]]; set route [read $f]; close $f
if {![regexp {# of routable nets\.+\s*:\s*([0-9]+)} $route -> routable] ||
    ![regexp {# of fully routed nets\.+\s*:\s*([0-9]+)} $route -> routed] ||
    ![regexp {# of nets with routing errors\.+\s*:\s*0\s*:} $route] ||
    $routable <= 0 || $routed != $routable} {error "Incomplete or invalid routing"}
set critical [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {[llength $critical]} {error "Critical DRC blocks bit generation: $critical"}
source [file join $root scripts audit_board_reset_cdc.tcl]
i1_audit_board_reset_cdc $out
set bit [file join $out orbital_i1_rv64gc_cpu300_i32k_d32k_uart460800_jtag65_nomac_bootrom.bit]
write_bitstream $bit
set f [open [file join $out result.txt] w]
puts $f "BIT_GENERATED_FROM_REVIEWED_ROUTED_DCP ROM4096_EXACT_INIT_AND_MAPPING_PASS"
puts $f "CPU300 UI250 AON50 UART50 I32KiB D32KiB RV64GC USER2_SCAN65 UART460800 MAC_ABSENT"
puts $f "WNS=$setup WHS=$hold ROUTED_NETS=$routed EXISTING_CDC_REVIEW_REQUIRED BOARD_NOT_YET_TESTED"
puts $f "SOURCE_DCP=$dcp BIT=$bit"
close $f
close_design
puts "I1_BOOTROM_REPAIRED_BIT_COMPLETE $bit"
