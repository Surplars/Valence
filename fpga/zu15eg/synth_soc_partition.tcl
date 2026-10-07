# Build/reuse only the replaceable SoC partition; preserve all real BMG initialization.
# Arguments: RTL_DIR ROM_DCP OUT_DIR REPORT_PERIOD_NS [SYNTHESIS_PERIOD_NS [DIRECTIVE [FLATTEN]]]
# Four-argument mode retains historical post-synthesis-only clocking. The optional
# fifth argument loads an actual XDC BEFORE synth_design for timing-driven mapping.
if {$argc ni {4 5 6 7}} {error "Expected RTL_DIR ROM_DCP OUT_DIR REPORT_PERIOD_NS ?SYNTHESIS_PERIOD_NS ?DIRECTIVE ?FLATTEN???"}
lassign $argv rtl_dir rom_dcp out_dir period synthesis_period directive flatten
if {$argc < 6} {set directive Default}
if {$argc < 7} {set flatten none}
if {$directive ni {Default RuntimeOptimized}} {error "Unsupported synthesis directive"}
if {$flatten ni {none rebuilt}} {error "Unsupported hierarchy mode"}
foreach name {rtl_dir rom_dcp out_dir} {set $name [file normalize [set $name]]}
if {![string is double -strict $period] || $period <= 0} {error "Invalid period"}
if {$argc >= 5 && (![string is double -strict $synthesis_period] || $synthesis_period <= 0)} {
    error "Invalid synthesis period"
}
file mkdir $out_dir
set_param general.maxThreads 8
set blackbox_dcp [file join $out_dir soc_blackbox.dcp]
set mode_file [file join $out_dir synthesis_clock_mode.txt]
set expected_mode [expr {$argc >= 5 ? "timing-driven:$synthesis_period" : "post-synthesis-clock"}]
if {$argc >= 6} {append expected_mode ":directive:$directive"}
if {$argc == 7} {append expected_mode ":flatten:$flatten"}
if {[file exists $blackbox_dcp]} {
    if {[file exists $mode_file]} {
        set stream [open $mode_file r]
        set existing_mode [string trim [read $stream]]
        close $stream
        if {$existing_mode ne $expected_mode} {error "Cached synthesis clock mode differs; use a new candidate directory"}
    } elseif {$argc >= 5} {
        error "Historical cached checkpoint has no timing-driven proof; use a new candidate directory"
    }
}
# This checkpoint permits ROM/import/report retries without re-running SoC synthesis.
# The output directory must belong to this exact RTL candidate.
if {![file exists $blackbox_dcp]} {
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    set veo [file join [file dirname $rom_dcp] blk_mem_gen_0.veo]
    set input [open $veo r]
    set template [read $input]
    close $input
    set ports {}
    foreach line [split $template "\n"] {
        if {[regexp {^\s*\.(\w+)\([^)]*\).*//\s*(input|output|inout)\s+(?:wire\s+)?(\[[^]]+\])?\s*(\w+)} $line -> port direction width]} {
            lappend ports "$direction wire $width $port"
        }
    }
    if {[llength $ports] != 8} {error "BMG ROM port contract changed"}
    set stub_file [file join $out_dir rom_ooc_stub.v]
    set stream [open $stub_file w]
    puts $stream "(* black_box = \"yes\" *) module blk_mem_gen_0 ("
    puts $stream [join $ports ",\n"]
    puts $stream "); endmodule"
    close $stream
    read_verilog -sv [glob -directory $rtl_dir *.sv]
    read_verilog $stub_file
    if {$argc >= 5} {
        set constraint [file join $out_dir synthesis_clock.xdc]
        set stream [open $constraint w]
        puts $stream [format {create_clock -name soc_ooc_clock -period %.9f [get_ports clock]} $synthesis_period]
        close $stream
        read_xdc $constraint
        puts "SOC_SYNTHESIS: clock XDC loaded before synth_design; target_period=$synthesis_period"
    }
    set synthesis_args [list -top BoardSocTop -part xczu15eg-ffvb1156-2-i \
        -mode out_of_context -flatten_hierarchy $flatten -directive $directive]
    if {$argc >= 6} {lappend synthesis_args -debug_log}
    puts "SOC_SYNTHESIS: directive=$directive flatten=$flatten debug_log=[expr {$argc >= 6}]"
    synth_design {*}$synthesis_args
    if {$argc >= 5} {
        set synthesis_clock [get_clocks -quiet soc_ooc_clock]
        if {[llength $synthesis_clock] != 1 ||
            abs([get_property PERIOD $synthesis_clock] - $synthesis_period) > 0.001} {
            error "Timing-driven synthesis clock missing or incorrect"
        }
        puts "SOC_SYNTHESIS: synthesis_clock_period=[get_property PERIOD $synthesis_clock]"
        reset_timing
    }
    create_clock -name soc_ooc_clock -period $period [get_ports clock]
    write_checkpoint $blackbox_dcp
    set stream [open $mode_file w]
    puts $stream $expected_mode
    close $stream
    close_project
}
# Vivado 2025.1 on this host fails read_checkpoint -cell with Project 1-9.
# Its documented update_design structural-netlist interface avoids that re-link.
set rom_edif [file join $out_dir rom.edf]
if {![file exists $rom_edif]} {
    open_checkpoint $rom_dcp
    write_edif $rom_edif
    close_design
}
open_checkpoint $blackbox_dcp
set memory [get_cells -quiet platform/rom/memory]
if {[llength $memory] != 1 || ![get_property IS_BLACKBOX $memory]} {error "Expected native ROM black box"}
update_design -cells platform/rom/memory -from_file $rom_edif
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved black boxes in SoC"}
set uart_regs [get_cells -quiet -hier -filter {NAME =~ */uart/rxMeta_reg || NAME =~ */uart/rxSync_reg}]
if {[llength $uart_regs] != 2} {error "UART synchronizer mismatch"}
set_property ASYNC_REG TRUE $uart_regs
report_utilization -hierarchical -file [file join $out_dir utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out_dir timing.rpt]
report_timing -delay_type max -max_paths 30 -file [file join $out_dir paths.rpt]
# The enclosing board supplies the real MMCM clock and existing IP constraints.
reset_timing
if {[llength [get_clocks -quiet]]} {error "OOC clocks unexpectedly remain"}
write_checkpoint [file join $out_dir soc_candidate.dcp]
write_edif [file join $out_dir soc_candidate.edf]
close_design
