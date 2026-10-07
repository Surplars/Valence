# Recover only this candidate's own saved post-place implementation.
# A reporting error must never discard another completed route.
# No synthesis/opt/place, no new constraints/false paths, no bit generation.
if {$argc != 3} {error "Expected CANDIDATE_ROOT OWN_PLACED_DCP FRESH_OUTPUT_DIRECTORY"}
lassign $argv root placed out
set root [file normalize $root]
set placed [file normalize $placed]
set out [file normalize $out]
set isa rv64gc
if {$placed ne [file normalize [file join $root implementation placed.dcp]] || ![file isfile $placed]} {
    error "Only this candidate's own placed checkpoint is allowed"
}
if {$out ne [file normalize [file join $root implementation-report-recovery-r1]]} {
    error "Recovery output must stay in this candidate's named fresh directory"
}
if {[file exists $out]} {error "Preserve previous recovery evidence; output exists"}
if {![file isfile [file join $root inputs.json]]} {error "Missing frozen candidate manifest"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $placed
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong FPGA part"}
set fpSystems [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]
if {[llength $fpSystems] != 1} {error "The placed checkpoint must contain the actual full RV64GC FPU"}
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black boxes in placed design"}
foreach {pin hz} {
    u_soc/clock 100000000
    u_soc/io_alwaysOnClock 50000000
    u_soc/nativeBank/uart/uart/clock 50000000
    u_soc/io_nativeGmac_rawTxClock 125000000
    u_rgmii/delay_clock 500000000
    u_rgmii/tx_clock_ddr/CLK 250000000
} {
    set endpoint [get_pins -quiet $pin]
    if {[llength $endpoint]!=1} {error "Missing actual clock endpoint $pin"}
    set clock [get_clocks -of_objects $endpoint]
    if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-1.0e9/$hz)>0.001} {
        error "Wrong actual clock on $pin"
    }
}
# Definitions only. The checkpoint already contains the applied constraints.
# Do not reapply valence_native_board_constraints or write a new timing budget.
source [file join $root scripts native_quarter_clock_constraints.tcl]
valence_quarter_tx_audit u_rgmii
puts "RECOVERY_OWN_PLACED_RV64GC100_UART460800 NO_SOURCE_OR_CONSTRAINT_CHANGE"
route_design -directive Explore -tns_cleanup
write_checkpoint routed_before_physopt.dcp
phys_opt_design -directive Explore
write_checkpoint routed.dcp
set quarter [get_cells -quiet centered_tx_clock.clock_dut/quarter_div]
if {[llength $quarter]} {
    set txData [valence_quarter_tx_audit u_rgmii]
    set txIdentity [open quarter_tx_identity.txt w]
    puts $txIdentity "PASS_NATIVE_QUARTER_TX_TOPOLOGY SIX_COMMON_CLK250_RESET FIVE_EXACT_D0_D4_PAIRS PHASE_FEEDBACK"
    puts $txIdentity "ACTUAL_DATA_DDR_CELLS=$txData"
    close $txIdentity
}
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -delay_type max -max_paths 40 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 30 -input_pins -file hold_paths.rpt
report_utilization -hierarchical -file utilization.rpt
report_clock_interaction -file clock_interaction.rpt
report_cdc -details -file cdc.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_route_status -file route_status.rpt
report_exceptions -coverage -file exception_coverage.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
report_clocks -file routed_clocks.rpt
set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
report_timing -from $cpuClock -to $cpuClock -delay_type min_max -max_paths 20 -input_pins -file cpu_paths.rpt
# Query every physical lane independently: a report of only the globally
# worst lanes can hide an excluded endpoint or its missing hold check.
foreach direction {tx rx} {
    set report [file join $out ${direction}_io.rpt]
    set f [open $report w]; close $f
    set endpoints [get_ports [list eth_${direction}d\[*\] eth_${direction}_ctl]]
    if {[llength $endpoints]!=5} {error "Missing physical $direction lanes"}
    foreach port $endpoints {
        foreach delay {max min} {
            if {$direction eq "tx"} {
                set path [get_timing_paths -to $port -delay_type $delay -max_paths 1]
                if {[llength $path]!=1} {error "Untimed $direction/$delay endpoint: $port"}
                if {[llength $quarter]} {
                    set required [expr {$delay eq "max" ? 2.0 : -2.0}]
                    if {abs([get_property REQUIREMENT $path]-$required)>0.001} {error "Unproved actual TX edge relationship at $port"}
                }
                report_timing -to $port -delay_type $delay -max_paths 1 -input_pins -append -file $report
            } else {
                set path [get_timing_paths -from $port -delay_type $delay -max_paths 1]
                if {[llength $path]!=1} {error "Untimed $direction/$delay startpoint: $port"}
                report_timing -from $port -delay_type $delay -max_paths 1 -input_pins -append -file $report
            }
            if {[get_property SLACK $path] in {inf -inf}} {error "Invalid infinite $direction/$delay slack: $port"}
        }
    }
}
set clearNames {raw_div pad_div forward_div}
if {[llength $quarter]} {set clearNames {raw_div quarter_div}}
set clearPins {}
foreach name $clearNames {lappend clearPins [get_pins centered_tx_clock.clock_dut/$name/CLR]}
report_timing -to $clearPins -delay_type min_max -max_paths 12 -input_pins -file divider_clear.rpt
write_xdc -type timing routed_constraints.xdc
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
set wns [get_property SLACK $setup]
set whs [get_property SLACK $hold]
puts "NATIVE_BOARD_RESULT ISA=$isa WNS=$wns WHS=$whs CPU100 UART460800 GMAC125"
# Reports/checkpoint always remain. Do not issue write_bitstream just because
# synthesis finished. A separate signed review checks unconstrained endpoints,
# reset/CDC/Gray/payload coverage, pulse width, routing and DRC before release.
set status [open stage-result.txt w]
puts $status "ISA=$isa CPU_HZ=100000000 UART_BAUD=460800 WNS=$wns WHS=$whs"
puts $status "STATUS=ROUTED_REQUIRES_SIGNOFF NO_BIT_GENERATED"
close $status
close_design

