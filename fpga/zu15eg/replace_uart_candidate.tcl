# Reuse a routed baseline; only UART, MMCM parameters and ROM INIT change.
# This script targets the audited 50 MHz baseline and 45/50 MHz FIFO candidates.
# Args: OLD_SOC_DCP OLD_ROM_DCP ROUTED_DCP PARTITION_DIR OUTPUT_DIR CPU_HZ
if {$argc != 6} {error "Expected OLD_SOC_DCP OLD_ROM_DCP ROUTED_DCP PARTITION_DIR OUTPUT_DIR CPU_HZ"}
lassign $argv old_soc old_ip routed partitions out cpu_hz
if {$cpu_hz ni {45000000 50000000}} {error "Supported CPU targets are 45/50 MHz"}
set period [expr {1000000000.0/$cpu_hz}]
foreach var {old_soc old_ip routed partitions out} {set $var [file normalize [set $var]]}
file mkdir $out
set_param general.maxThreads 8
set gen [file join $partitions ip-build reclock_ip.gen sources_1 ip]
set new_ip [file join $gen blk_mem_gen_0 blk_mem_gen_0.dcp]
set new_clock [file join $gen clk_wiz_ddr clk_wiz_ddr.dcp]
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
            set nets [get_nets -quiet -of_objects $pin]
            set names {}
            foreach net $nets {lappend names [get_property NAME $net]}
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

if {[file exists [file join $out patched.dcp]]} {
    if {![file exists [file join $out soc_candidate.dcp]]} {error "Missing immutable logical reference"}
    open_checkpoint $routed
    set frozen [dict create]
    foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_* && NAME !~ u_soc/platform/uart/*}] {
        dict set frozen [get_property NAME $cell] [list [get_property LOC $cell] [get_property BEL $cell]]
    }
    close_design
    open_checkpoint [file join $out patched.dcp]
} else {
lassign [snapshot_rom $old_ip] old_shape old_init old_ports
lassign [snapshot_rom $new_ip] new_shape new_init new_ports
if {[dict keys $old_shape] ne [dict keys $new_shape] || $old_ports ne $new_ports} {error "ROM topology/ports changed"}
dict for {name value} $old_shape {
    if {$value ne [dict get $new_shape $name]} {error "ROM non-INIT configuration differs: $name"}
}
if {[dict size $new_init] != 29 || [dict keys $old_init] ne [dict keys $new_init]} {error "ROM mapping changed"}
# Clock Wizard has independently validated this exact target configuration.
open_checkpoint $new_clock
set cm [get_cells inst/mmcme4_adv_inst]
if {[llength $cm] != 1} {error "Expected MMCME4_ADV"}
set clock_config [dict create]
foreach prop [list_property $cm] {
    if {[regexp {^(BANDWIDTH|CLKFBOUT_.*|CLKIN[12]_PERIOD|CLKOUT[0-6]_.*|COMPENSATION|DIVCLK_DIVIDE|REF_JITTER[12]|SS_.*|STARTUP_WAIT)$} $prop]} {
        dict set clock_config $prop [get_property $prop $cm]
    }
}
set clock_hz [expr {250000000.0 * [dict get $clock_config CLKFBOUT_MULT_F] /
    [dict get $clock_config DIVCLK_DIVIDE] / [dict get $clock_config CLKOUT0_DIVIDE_F]}]
if {abs($clock_hz - $cpu_hz) > 1.0} {error "Clock Wizard target is not requested CPU frequency"}
close_design
# Save the exact logical reference partition used by the release ROM audit.
if {![file exists [file join $out rom_candidate.edf]]} {
    open_checkpoint $new_ip
    write_edif [file join $out rom_candidate.edf]
    close_design
}
if {![file exists [file join $out soc_candidate.dcp]]} {
open_checkpoint $old_soc
update_design -cells platform/uart -black_box
update_design -cells platform/uart -strict -from_file [file join $partitions uart.edf]
update_design -cells platform/rom/memory -black_box
update_design -cells platform/rom/memory -strict -from_file [file join $out rom_candidate.edf]
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Reference SoC has black boxes"}
set_property ASYNC_REG TRUE [get_cells {platform/uart/rxMeta_reg platform/uart/rxSync_reg}]
write_checkpoint [file join $out soc_candidate.dcp]
close_design
}
open_checkpoint $routed
set cm [get_cells u_clk_wiz/inst/mmcme4_adv_inst]
if {[llength $cm] != 1 || [get_property REF_NAME $cm] ne "MMCME4_ADV"} {error "Routed MMCM mismatch"}
set cpu_before [get_clocks -quiet clk_out1_clk_wiz_ddr]
report_clocks -file [file join $out clocks_before.rpt]
if {[llength $cpu_before] != 1 || abs([get_property PERIOD $cpu_before] - 20.0) > 0.001} {error "Baseline must be real 50 MHz"}
# Check every old ROM value before modifying the in-memory design.
dict for {name values} $old_init {
    set cell [get_cells "u_soc/platform/rom/memory/$name"]
    if {[llength $cell] != 1} {error "Missing routed ROM cell $name"}
    dict for {prop value} $values {
        if {[get_property $prop $cell] ne $value} {error "Baseline ROM mismatch: $name/$prop"}
    }
}
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_* && NAME !~ u_soc/platform/uart/*}] {
    dict set frozen [get_property NAME $cell] [list [get_property LOC $cell] [get_property BEL $cell]]
}
if {[dict size $frozen] < 100000} {error "Unexpected baseline placement coverage"}
puts "RECLOCK: PRESERVED_PRIMITIVES=[dict size $frozen]"
dict for {prop value} $clock_config {set_property $prop $value $cm}
dict for {name values} $new_init {
    set cell [get_cells "u_soc/platform/rom/memory/$name"]
    dict for {prop value} $values {set_property $prop $value $cell}
}
set uart [get_cells u_soc/platform/uart]
if {[llength [get_pins -of_objects $uart]] != 215} {error "This ECO requires the audited 215-pin UART boundary"}
update_design -cells $uart -black_box
update_design -cells $uart -strict -from_file [file join $partitions uart_routed.edf]
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved functional partitions"}
set uart_sync [get_cells {u_soc/platform/uart/rxMeta_reg u_soc/platform/uart/rxSync_reg}]
if {[llength $uart_sync] != 2} {error "UART CDC changed"}
set_property ASYNC_REG TRUE $uart_sync
report_clocks -file [file join $out clocks.rpt]
set cpu [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - $period) > 0.001 ||
    ![get_property IS_GENERATED $cpu] || [get_property IS_USER_GENERATED $cpu]} {
    error "MMCM change did not produce a requested real CPU frequency generated clock"
}
set ui [get_clocks -quiet -of_objects [get_pins u_ddr/c0_ddr4_ui_clk]]
if {[llength $ui] != 1 || abs([get_property PERIOD $ui] - 4.0) > 0.001} {error "MIG UI must remain 250 MHz"}
write_checkpoint [file join $out patched.dcp]
}
# CoreRegisterRouter zero-extends its 2-bit memory size into RegisterPort.size.
# Context optimization removed this constant's old driver; restore ONLY this
# independently verified connection when importing a generic UART partition.
set stream [open [file join [file dirname $partitions] CoreRegisterRouter_2.sv] r]
set router_rtl [read $stream]
close $stream
if {![regexp {assign io_registers_request_bits_size = \{1'h0, io_upstream_request_bits_size\};} $router_rtl]} {
    error "Cannot prove the board UART size[2] constant from exported RTL"
}
set size_pin [get_pins {u_soc/platform/uart/io_mmio_request_bits_size[2]}]
set size_net [get_nets -hier -filter {NAME == "u_soc/platform/uart/io_mmio_request_bits_size[2]"}]
if {[llength $size_pin] != 1 || [llength $size_net] != 1} {error "UART size pin/net contract changed"}
if {[llength [get_pins -leaf -of_objects $size_net -filter {DIRECTION == OUT}]] != 0} {
    error "Expected exactly the audited context-pruned, driverless size[2] net"
}
create_cell -reference GND u_soc/platform/uart/board_size2_ground
connect_net -net $size_net -objects [get_pins u_soc/platform/uart/board_size2_ground/G]
set cpu [get_clocks clk_out1_clk_wiz_ddr]
if {abs([get_property PERIOD $cpu] - $period) > 0.001 || ![get_property IS_GENERATED $cpu]} {
    error "Resume clock is not requested real CPU frequency"
}
# Only the imported UART partition needs physical placement and local routing.
# Snapshot and verify every original LOC/BEL; do not mutate the baseline I/O
# shape constraints, which Vivado cannot safely re-freeze after checkpoint import.
source [file join [file dirname [info script]] audit_reset_cdc.tcl]
set reset_presets [audit_board_reset_cdc [file join $out reset_cdc_audit.txt]]
set_false_path -to $reset_presets
lock_design -level placement
place_design -directive Quick
route_design -directive Quick -preserve
dict for {name expected} $frozen {
    set cell [get_cells $name]
    if {[llength $cell] != 1 ||
        [list [get_property LOC $cell] [get_property BEL $cell]] ne $expected} {
        error "Unrelated baseline placement changed: $name"
    }
}
# Complete INIT comparison is repeated independently by release_soc_partition.tcl.
write_checkpoint [file join $out routed.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 20 -file [file join $out cpu_timing_paths.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
report_drc -file [file join $out drc.rpt]
puts "RECLOCK: PHYSICAL CANDIDATE COMPLETE; RELEASE SIGNOFF STILL REQUIRED"
close_design
