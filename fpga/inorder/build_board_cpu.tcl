# One combined implementation after affected short PASS. No old CPU DCP.
if {$argc!=1} {error "usage: build_board_cpu.tcl FRESH_STAGED_BOARD_ROOT"}
set root [file normalize [lindex $argv 0]]
if {![string match */orbital-i1-cpu300-board-* $root] ||
    ![file isfile [file join $root board-manifest.json]]} {error "Explicit isolated staged board required"}
set reports [file join $root reports]
if {[file exists $reports]} {error "Preserve previous implementation evidence"}
file mkdir $reports
set_param general.maxThreads 8
open_project [file join $root project i1_board.xpr]
if {[string tolower [get_property PART [current_project]]] ne "xczu15eg-ffvb1156-2-i"} {
    error "Wrong physical FPGA part"
}
foreach name {ddr4_0 clk_wiz_i1 axi_clock_converter_i1} {
    set ip [get_ips -quiet $name]
    if {[llength $ip]!=1 || [get_property PROGRESS [get_runs [format "%s_synth_1" $name]]] ne "100%"} {
        error "Exact completed IP required: $name"
    }
    set file [file normalize [get_property IP_FILE $ip]]
    if {[string first [string tolower [file join $root project]] [string tolower $file]]!=0} {
        error "IP must belong to the isolated copied project: $file"
    }
}
foreach file [get_files -all] {
    set path [string map {\\ /} [get_property NAME $file]]
    if {[string first "$root/rtl/" $path]==0 || [string first "$root/board/" $path]==0} {
        remove_files $file
    }
}
add_files -norecurse [glob [file join $root rtl *.sv]]
add_files -norecurse [file join $root board soc_top_i1_cpu_ddr.sv]
add_files -norecurse [file join $root rtl bootrom.hex]
set_property FILE_TYPE {Memory Initialization Files} [get_files */bootrom.hex]
add_files -fileset constrs_1 -norecurse [list [file join $root board board_ddr.xdc] \
    [file join $root board pl_ddr4_pins.xdc] [file join $root board phy_disabled.xdc]]
set_property top soc_top_i1_cpu_ddr [get_filesets sources_1]
source [file join $root scripts configure_board_mem.tcl]
i1_configure_board_mem
set synth [get_runs synth_1]
set runDir [file normalize [get_property DIRECTORY $synth]]
if {[string first [string tolower [file join $root project i1_board.runs]] \
        [string tolower $runDir]]!=0} {error "Refuse to reset a run outside this isolated candidate"}
reset_runs synth_1
set_property AUTO_INCREMENTAL_CHECKPOINT 0 $synth
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none $synth
set_property STEPS.SYNTH_DESIGN.TCL.PRE [file join $root scripts prepare_board_mem.tcl] $synth
set_property STEPS.OPT_DESIGN.TCL.PRE [file join $root scripts board_cpu_constraints.tcl] [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.TCL.POST [file join $root scripts save_board_physopt.tcl] [get_runs impl_1]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS $synth] ne "100%"} {error "Fresh CPU/SoC synthesis failed"}
open_run synth_1
source [file join $root scripts audit_board_bootrom.tcl]
i1_audit_bootrom [file join $root rtl bootrom.hex] [file join $reports bootrom_post_synth.txt]
report_utilization -hierarchical -file [file join $reports post_synth_utilization.rpt]
write_checkpoint [file join $reports real_board_post_synth.dcp]
close_design
launch_runs impl_1 -to_step phys_opt_design -jobs 1
wait_on_run impl_1
set implStatus [get_property STATUS [get_runs impl_1]]
if {![file isfile [file join $reports real_board_post_place_physopt.dcp]] ||
        [regexp -nocase {error|fail} $implStatus]} {
    error "Fresh board physical optimization failed: $implStatus"
}
close_project
open_checkpoint [file join $reports real_board_post_place_physopt.dcp]
puts "I1_BOARD_ROUTE_STRATEGY TIMING_DRIVEN_DEFAULT_NO_PSIR ORIGINAL_CLOCKS_NO_EXCEPTIONS_CHANGED"
# Match the completed batch38 route; avoid its crashed Leaf ClockOpt stage.
# This does NOT select Quick/non-timing-driven routing or relax constraints.
route_design -no_psir -timing_summary
i1_audit_bootrom [file join $root rtl bootrom.hex] [file join $reports bootrom_post_route.txt]
write_checkpoint [file join $reports real_board_routed.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $reports timing_summary.rpt]
foreach delay {max min} {
    report_timing -delay_type $delay -max_paths 60 -input_pins -file [file join $reports [format "paths_%s.rpt" $delay]]
}
report_utilization -file [file join $reports utilization_flat.rpt]
report_utilization -hierarchical -file [file join $reports utilization.rpt]
report_clocks -file [file join $reports clocks.rpt]
report_clock_interaction -file [file join $reports clock_interaction.rpt]
report_cdc -details -file [file join $reports cdc.rpt]
report_bus_skew -warn_on_violation -file [file join $reports bus_skew.rpt]
report_drc -file [file join $reports drc.rpt]
report_route_status -file [file join $reports route_status.rpt]
report_exceptions -coverage -file [file join $reports exceptions.rpt]
check_timing -verbose -file [file join $reports check_timing.rpt]
report_io -file [file join $reports io.rpt]
set f [open [file join $reports domains.tsv] w]
puts $f "domain\tclock\tperiod_ns\tdelay\tslack_ns\tstartpoint\tendpoint"
foreach {domain pin} {CPU300 u_soc/io_clockIn DDR_UI250 u_axi_cdc/m_axi_aclk
                     AON50 u_soc/io_alwaysOnClock UART50 UART_STORAGE_CLOCK} {
    if {$domain eq "UART50"} {
        # ManagedUart.managedClock is an unused output and may be optimized
        # away. Resolve the clock on actual retained UART sequential cells.
        set uartCells [get_cells -hier -filter {IS_SEQUENTIAL && NAME =~ u_soc/bank/uart/uart/*}]
        if {[llength $uartCells]<10} {error "Actual UART storage missing"}
        set uartClockPins [get_pins -of_objects $uartCells -filter {REF_PIN_NAME == C}]
        set c [get_clocks -of_objects $uartClockPins]
        if {[llength $c]!=1 || abs([get_property PERIOD $c]-20.0)>0.002} {
            error "Actual UART storage clock is not UART50"
        }
    } else {
        set c [get_clocks -of_objects [get_pins $pin]]
    }
    if {[llength $c]!=1} {error "Actual domain clock missing: $domain"}
    foreach delay {max min} {
        set path [get_timing_paths -from $c -to $c -delay_type $delay -max_paths 1]
        if {[llength $path]!=1} {error "Actual domain has no reported path: $domain $delay"}
        puts $f "$domain\t[get_property NAME $c]\t[get_property PERIOD $c]\t$delay\t[get_property SLACK $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]"
        report_timing -from $c -to $c -delay_type $delay -max_paths 30 \
            -file [file join $reports [format "%s_%s.rpt" $domain $delay]]
    }
}
close $f
source [file join $root scripts report_board_cpu_targets.tcl]
i1_board_cpu_target_paths $reports
source [file join $root scripts audit_board_reset_cdc.tcl]
i1_audit_board_reset_cdc $reports
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set f [open [file join $reports stage-result.txt] w]
puts $f "REAL_BOARD CPU300 UI250 AON50 UART50 I32KiB D32KiB FD Sv39 PLIC CMU USER2 MAC_ABSENT"
puts $f "WNS=$setup WHS=$hold STATUS=ROUTED_REQUIRES_REPORT_REVIEW NO_BIT_GENERATED"
close $f
puts "I1_CPU_BOARD_ROUTED WNS=$setup WHS=$hold CPU300 ACTUAL_MIG_AXI_CDC_IP"
close_design
