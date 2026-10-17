# One fresh F/D I1 SoC + shared USER2 synthesis, not place/route or a board bit.
if {$argc ni {2 3}} { error "usage: synth_fd_jtag.tcl RTL_ROOT FRESH_REPORT_ROOT ?HASH_QUALIFIED_CHECKPOINT?" }
set rtl_root [file normalize [lindex $argv 0]]
set report_root [file normalize [lindex $argv 1]]
if {[file exists $report_root]} { error "refusing to overwrite previous synthesis evidence" }
file mkdir $report_root
cd $rtl_root
set_param general.maxThreads 8
set files [lsort [glob -nocomplain -directory $rtl_root *.sv]]
if {[llength $files] == 0} { error "missing exact frozen SoC RTL" }
set reused [expr {$argc == 3}]
if {$reused} {
    # export_soc.py verifies every input SV/XDC byte and provenance before
    # copying this checkpoint. collect_soc.py repeats those hash gates.
    set checkpoint [file normalize [lindex $argv 2]]
    if {$checkpoint ne [file join $rtl_root reused_synthesized.dcp]} {
        error "only the exporter's exact hash-qualified checkpoint may be resumed"
    }
    open_checkpoint $checkpoint
    if {[get_property TOP [current_design]] ne "FiveStageFpgaShell"} { error "checkpoint top mismatch" }
    if {[string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
        error "checkpoint part mismatch"
    }
    puts "ORBITAL_I1_REUSED_EXACT_SYNTHESIS NO_NEW_SYNTHESIS"
} else {
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv $files
    read_xdc [file join $rtl_root soc_ooc.xdc]
    synth_design -top FiveStageFpgaShell -part xczu15eg-ffvb1156-2-i -mode out_of_context \
        -flatten_hierarchy rebuilt -directive Default -verilog_define ENABLE_INITIAL_MEM_
}
# Preserve this single synthesis even if a later constraint/shape gate needs review.
write_checkpoint [file join $report_root synthesized.dcp]
report_utilization -file [file join $report_root utilization.rpt]
report_utilization -hierarchical -file [file join $report_root hierarchical_utilization.rpt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type max -max_paths 30 -nworst 2 -file [file join $report_root setup_cpu_raw_synth.rpt]

set primitives [get_cells -quiet -hierarchical -filter {REF_NAME == BSCANE2}]
if {[llength $primitives] != 1} { error "expected exactly one shared USER2 primitive" }
set primitive [get_property NAME [lindex $primitives 0]]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} {
    error "review synthesized BSCAN sibling hierarchy: $primitive"
}
source [file join $rtl_root bscan_timing.tcl]
valence_apply_bscan_timing $primitive $engine orbital_i1_cpu zu15eg-user2-tck50-positive-v1
write_checkpoint [file join $report_root synthesized_constrained.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $report_root timing_synth.rpt]
report_timing -delay_type max -max_paths 30 -nworst 2 -file [file join $report_root setup_synth.rpt]
report_timing -from [all_registers] -to [all_registers] -delay_type max -max_paths 30 -nworst 2 \
    -file [file join $report_root setup_internal_synth.rpt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type max -max_paths 30 -nworst 2 -file [file join $report_root setup_cpu_synth.rpt]
report_clock_interaction -file [file join $report_root clock_interaction.rpt]
report_clocks -file [file join $report_root clocks.rpt]
check_timing -verbose -file [file join $report_root check_timing.rpt]

set bram36 [get_cells -hierarchical -filter {REF_NAME == RAMB36E2}]
set bram18 [get_cells -hierarchical -filter {REF_NAME == RAMB18E2}]
set dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]
set mapfile [open [file join $report_root ram_dsp_mapping.txt] w]
set target_mhz [expr {1000.0 / [get_property PERIOD [get_clocks orbital_i1_cpu]]}]
puts $mapfile "scope=I1_FD_SOC_USER2_SYNTHESIS_ONLY_NOT_ROUTED_NOT_BOARD_NO_BIT"
puts $mapfile "target_mhz=$target_mhz RV64IMAFDC M/S/U Sv39 PMP8 I/D2KiB BTB128 BootROM4KiB DDR2GiB PLIC USER2"
puts $mapfile "RAMB36E2=[llength $bram36] RAMB18E2=[llength $bram18] DSP48E2=[llength $dsps]"
set rf_count 0
set fpr_count 0
set cache_count 0
set rom_count 0
set rom_nonzero_init 0
foreach cell [concat $bram36 $bram18 $dsps] {
    puts $mapfile "$cell [get_property REF_NAME $cell]"
    if {[string match "*rf*bank*" $cell]} { incr rf_count }
    if {[string match "*fpr*fpBank*" $cell]} { incr fpr_count }
    if {[string match "*cache*data*" $cell]} { incr cache_count }
    if {[string match "*rom*storage*" $cell]} {
        incr rom_count
        foreach prop [list_property $cell] {
            if {[regexp {^INIT_[0-9A-F]+$} $prop]} {
                set initialized [get_property $prop $cell]
                puts $mapfile "$cell $prop=$initialized"
                set hexpart [lindex [split $initialized h] end]
                if {[regexp {[1-9a-fA-F]} $hexpart]} { set rom_nonzero_init 1 }
            }
        }
    }
}
puts $mapfile "rf_bram_primitives=$rf_count fpr_bram_primitives=$fpr_count cache_bram_primitives=$cache_count rom_bram_primitives=$rom_count rom_nonzero_init=$rom_nonzero_init"
close $mapfile
if {$rf_count < 2} { error "two GPR banks did not physically map to BRAM" }
if {$fpr_count < 3} { error "three FPR banks did not physically map to BRAM" }
if {$cache_count < 2} { error "I/D data payloads did not physically map to BRAM" }
if {$rom_count == 0 || !$rom_nonzero_init} { error "BootROM missing BRAM or nonzero INIT contents" }
if {[llength $dsps] == 0} { error "DSP tiled multiplier did not infer DSPs" }
set worst [get_timing_paths -delay_type max -max_paths 1]
set internal [get_timing_paths -from [all_registers] -to [all_registers] -delay_type max -max_paths 1]
set cpu [get_timing_paths -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] -delay_type max -max_paths 1]
set wns [get_property SLACK $worst]
set internal_wns [get_property SLACK $internal]
set cpu_wns [get_property SLACK $cpu]
set result [open [file join $report_root result.json] w]
puts $result "{\"status\":\"COMPLETE_SYNTHESIS_ONLY_NOT_ROUTED\",\"target_mhz\":$target_mhz,\"setup_wns_ns\":$wns,\"internal_setup_wns_ns\":$internal_wns,\"cpu_setup_wns_ns\":$cpu_wns,\"ramb36\":[llength $bram36],\"ramb18\":[llength $bram18],\"dsp\":[llength $dsps],\"fpr_bram_primitives\":$fpr_count,\"jtag_chain\":2,\"bscan_shape_checked\":true,\"board_qualified\":false,\"bit_generated\":false}"
close $result
puts "ORBITAL_I1_COMPLETE_SOC_SYNTH_DONE target_mhz=$target_mhz wns=$wns internal_wns=$internal_wns cpu_wns=$cpu_wns USER2"
close_project
