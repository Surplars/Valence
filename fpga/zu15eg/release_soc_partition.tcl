# Sign off an isolated routed SoC candidate before generating a new, non-overwriting bitstream.
# Arguments: SOC_DCP ROUTED_DCP OUT_DIR CPU_HZ UART_BAUD EXPECTED_ROM_DCP EXPECTED_ROM_BIN
# An explicitly selected firmware reference is mandatory: candidate==bit alone
# used to silently accept the old project's cached BootROM.
if {$argc != 7} {
    error "Expected SOC_DCP ROUTED_DCP OUT_DIR CPU_HZ UART_BAUD EXPECTED_ROM_DCP EXPECTED_ROM_BIN"
}
lassign $argv soc_dcp dcp out cpu_hz uart_baud expected_rom_dcp expected_rom_bin
if {$cpu_hz eq ""} {set cpu_hz 50000000}
if {![string is integer -strict $cpu_hz] || $cpu_hz < 6000000 || $cpu_hz > 200000000 || $cpu_hz % 1000000 != 0} {
    error "Expected CPU_HZ in whole MHz, 6..200 MHz"
}
set cpu_mhz [expr {$cpu_hz / 1000000}]
set cpu_period [expr {1000000000.0 / $cpu_hz}]
set bit_name "valence_ddr${cpu_mhz}_early_issue.bit"
if {$uart_baud ne ""} {
    if {$uart_baud ni {115200 460800 1500000}} {error "Expected UART_BAUD=115200, 460800 or 1500000"}
    set bit_name "valence_ddr${cpu_mhz}_uart${uart_baud}_fifo.bit"
}
set out [file normalize $out]
file mkdir $out
set_param general.maxThreads 8
proc read_text {path} {
    set stream [open $path r]
    set value [read $stream]
    close $stream
    return $value
}
# Verify firmware identity BEFORE accepting any candidate/reference checkpoint.
set mif [file join [file dirname $expected_rom_dcp] blk_mem_gen_0.mif]
set audit_script [file join [file dirname [info script]] .. firmware audit_bootrom.py]
# Vivado exports PYTHONHOME/PYTHONPATH for its bundled Python. Isolated mode
# prevents those variables from mixing its stdlib with a PATH-selected interpreter.
puts [exec python -I $audit_script --bin $expected_rom_bin --mif $mif --dcp $expected_rom_dcp \
    --manifest [file join $out bootrom_manifest.json]]
open_checkpoint $expected_rom_dcp
set firmware_init [dict create]
foreach cell [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}] {
    foreach prop [list_property $cell] {
        if {[regexp {^INIT(P)?_[0-9A-F]{2}$} $prop]} {
            dict set firmware_init "platform/rom/memory/[get_property NAME $cell]/$prop" [get_property $prop $cell]
        }
    }
}
if {[dict size $firmware_init] != 4176} {error "Incomplete expected ROM IP initialization"}
close_design
# Independently verify the initialized CPU ROM against the selected firmware AND candidate.
open_checkpoint $soc_dcp
set rom_init [dict create]
foreach cell [get_cells -quiet -hier -filter {NAME =~ platform/rom/memory/* && REF_NAME =~ RAMB*}] {
    foreach prop [list_property $cell] {
        if {[regexp {^INIT(P)?_[0-9A-F]{2}$} $prop]} {
            dict set rom_init "[get_property NAME $cell]/$prop" [get_property $prop $cell]
        }
    }
}
if {[dict size $rom_init] != 4176} {error "Incomplete candidate ROM initialization"}
dict for {key expected} $firmware_init {
    if {![dict exists $rom_init $key] || [dict get $rom_init $key] ne $expected} {
        error "Candidate contains stale/wrong BootROM: $key"
    }
}
close_design
open_checkpoint $dcp
source [file join [file dirname [info script]] audit_reset_cdc.tcl]
set reset_presets [audit_board_reset_cdc [file join $out reset_cdc_audit.txt]]
audit_cpu_reset_gate [file join $out reset_gate_audit.txt]
dict for {key expected} $rom_init {
    set pos [string last / $key]
    set cell [get_cells "u_soc/[string range $key 0 [expr {$pos - 1}]]"]
    set prop [string range $key [expr {$pos + 1}] end]
    if {[llength $cell] != 1 || [get_property $prop $cell] ne $expected} {
        error "Implemented ROM differs from candidate: $key"
    }
}
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong FPGA part"}
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved black boxes"}
set cpu_clock [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpu_clock] != 1 || abs([get_property PERIOD $cpu_clock] - $cpu_period) > 0.001} {
    error "Expected a real $cpu_mhz MHz CPU generated clock"
}
if {![get_property IS_GENERATED $cpu_clock]} {error "CPU clock must derive from the real MMCM"}
set ui_clock [get_clocks -quiet -of_objects [get_pins u_ddr/c0_ddr4_ui_clk]]
if {[llength $ui_clock] != 1 || abs([get_property PERIOD $ui_clock] - 4.0) > 0.0001} {
    error "MIG UI clock must remain at 250 MHz"
}
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 20 -file [file join $out cpu_timing_paths.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_cdc -file [file join $out cdc.rpt]
report_cdc -details -file [file join $out cdc_details.rpt]
set cdc_summary [read_text [file join $out cdc.rpt]]
set cdc_rows 0
foreach line [split $cdc_summary "\n"] {
    if {[regexp {([0-9]+)[ ]+([0-9]+)[ ]+([0-9]+)[ ]+([0-9]+)[ ]+([0-9]+)[ ]*$} $line -> endpoints safe unsafe unknown missing_async]} {
        incr cdc_rows
        if {$unsafe != 0 || $unknown != 0 || $missing_async != 0} {error "Unsafe/unknown/unmarked CDC: $line"}
    }
}
if {$cdc_rows == 0} {error "No CDC clock-pair rows checked"}
set cdc_details [read_text [file join $out cdc_details.rpt]]
if {[regexp -line {^CDC-[0-9]+[ ]+Critical} $cdc_details]} {error "Critical CDC remains"}
report_drc -ruledeck bitstream_checks -file [file join $out bitstream_drc.rpt]
set bad_drc [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {[llength $bad_drc]} {error "Bitstream DRC errors/critical warnings: $bad_drc"}
set timing [read_text [file join $out timing_summary.rpt]]
set summary {}
foreach line [split $timing "\n"] {
    if {[regexp {^\s*-?[0-9]+\.[0-9]+\s+-?[0-9]+\.[0-9]+\s+[0-9]+\s+[0-9]+\s+-?[0-9]+\.[0-9]+} $line]} {
        set summary [regexp -all -inline {[-]?[0-9]+(?:\.[0-9]+)?} $line]
        break
    }
}
if {[llength $summary] != 12} {error "Cannot validate timing summary: $summary"}
foreach index {0 4 8} {
    if {[lindex $summary $index] < 0} {error "Setup/hold/pulse-width failure: $summary"}
}
foreach index {1 2 5 6 9 10} {
    if {[lindex $summary $index] != 0} {error "Timing violations: $summary"}
}
foreach check {no_clock unconstrained_internal_endpoints loops latch_loops} {
    if {![regexp [format {checking %s \(0\)} $check] $timing]} {error "Timing coverage fails: $check"}
}
set skew [read_text [file join $out bus_skew.rpt]]
if {[string first "VIOLATED" $skew] >= 0 || [regexp -all {Slack \(MET\)} $skew] != 14} {
    error "Expected all 14 bus-skew constraints to pass"
}
set route [read_text [file join $out route_status.rpt]]
foreach {label variable} {"routable nets" routable "fully routed nets" fully "nets with routing errors" errors} {
    if {![regexp [format {%s\.+\s*:\s*([0-9]+)} $label] $route -> $variable]} {error "Missing route statistic $label"}
}
if {$routable != $fully || $errors != 0} {error "Routing is not complete/clean"}
set regions [get_pins -quiet {u_axi_cdc/s_axi_awregion* u_axi_cdc/s_axi_arregion*}]
if {[llength $regions] != 8} {error "Missing AXI REGION pins"}
foreach pin $regions {
    if {[get_property TYPE [get_nets -of_objects $pin]] ne "GROUND"} {error "AXI REGION not grounded"}
}
set uart_regs [get_cells -quiet -hier -filter {NAME =~ */uart/rxMeta_reg || NAME =~ */uart/rxSync_reg}]
if {[llength $uart_regs] != 2} {error "UART synchronizer mismatch"}
foreach cell $uart_regs {
    if {![get_property ASYNC_REG $cell]} {error "Missing UART ASYNC_REG: $cell"}
}
set cpu_path [get_timing_paths -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 1]
if {[llength $cpu_path] != 1} {error "Missing CPU setup paths"}
set signoff [open [file join $out signoff.txt] w]
puts $signoff "CPU=${cpu_mhz}MHz WNS=[lindex $summary 0] WHS=[lindex $summary 4] WPWS=[lindex $summary 8]"
puts $signoff "CPU_WNS=[get_property SLACK $cpu_path] CPU_DATA_DELAY=[get_property DATAPATH_DELAY $cpu_path]"
puts $signoff "Setup/hold/pulse width, timing coverage, 14 bus-skew checks, routing, bitstream DRC: PASS"
puts $signoff "ROM=4176 INIT/INITP properties matched expected firmware IP, candidate and routed design; MIG_UI=250MHz"
puts $signoff "BOOTROM=expected binary matched all 32768 MIF words; hashes in bootrom_manifest.json"
puts $signoff "AXI REGION=ground; UART ASYNC_REG=TRUE (two stages)"
puts $signoff "RESET_CDC=two audited 3-stage chains; only six asynchronous PRE entries excepted"
puts $signoff "CPU_RESET_GATE=all causes qualified in UI chain; stage 3 directly drives CPU PRE, no combinational CDC"
puts $signoff "CDC=unsafe/unknown/missing ASYNC_REG and Critical violations all zero (analyzed paths)"
if {$uart_baud ne ""} {puts $signoff "UART=${uart_baud} baud; FIFO firmware and RTL validated separately by GSIM"}
puts $signoff "Static signoff does not prove board UART/DDR stability; physical stress testing remains."
close $signoff
write_checkpoint [file join $out signed_routed.dcp]
write_bitstream [file join $out $bit_name]
write_debug_probes [file join $out "[file rootname $bit_name].ltx"]
puts "SOC_CANDIDATE: BITSTREAM COMPLETE [file join $out $bit_name]"
close_design
