# Native Vivado2025.2 only. No bitstream, no substitute behavioral primitives.
if {[llength $argv]!=3} {error "usage: validate_native.tcl ROOT FRESH_OUT simulation|synthesis"}
lassign $argv root out mode
set root [file normalize $root];set out [file normalize $out]
if {[file exists $out]} {error "Fresh output directory required"}
if {$mode ni {simulation synthesis}} {error "Unsupported mode"}
if {![string match 2025.2* [version -short]]} {error "This validation command is pinned to Vivado2025.2"}
file mkdir $out;cd $out
set_param general.maxThreads 8
if {[get_param general.maxThreads]<8} {error "Requested thread limit unavailable"}
foreach cmd {write_bitstream write_device_image} {
    if {[llength [info commands $cmd]]} {rename $cmd dynamic_forbidden_$cmd}
    proc ::$cmd {args} {error "UNQUALIFIED_DYNAMIC_COMPONENT_NO_BITSTREAM"}
}
set dir [file join $root fpga common dynamic]
set rtl [list [file join $dir native_clock_drp.sv] [file join $dir native_clock_gate.sv] [file join $dir native_dynamic_clock_domain.sv]]
if {$mode eq "simulation"} {
    if {![info exists ::env(VALENCE_VIVADO_HOME)]} {error "Set VALENCE_VIVADO_HOME to native Vivado2025.2"}
    set home $::env(VALENCE_VIVADO_HOME)
    set suffix [expr {$::tcl_platform(platform) eq "windows" ? ".bat" : ""}]
    foreach tool {xvlog xelab xsim} {
        set exe($tool) [file join $home bin $tool$suffix]
        if {![file isfile $exe($tool)]} {error "Missing native tool $tool"}
    }
    set glbl [file join $home data verilog src glbl.v]
    exec $exe(xvlog) -sv --define VALENCE_USE_UNISIM {*}$rtl [file join $dir dynamic_clock_unisim_tb.sv] $glbl > xvlog.log 2>@1
    exec $exe(xelab) dynamic_clock_unisim_tb glbl -L unisims_ver -debug typical -mt 8 -s dynamic_native > xelab.log 2>@1
    set failed [catch {exec $exe(xsim) dynamic_native -runall -onerror quit > xsim.log 2>@1} why]
    set f [open xsim.log];set log [read $f];close $f
    if {$failed || [string first DYNAMIC_CLOCK_UNISIM_PASS $log]<0 ||
        [regexp -nocase {Timing[[:space:]]+Violation|Unisim MMCME4_ADV-40|Illegal cp, res, and/or lock DRP|(^|[[:space:]])(FATAL|ERROR)(:|[[:space:]])} $log]} {
        error "Native dynamic clock test failed: $why; inspect xsim.log"
    }
    set f [open RESULT.txt w];puts $f "PASS_NATIVE_DYNAMIC_COMPONENT_UNISIM; WHOLE_SOC=UNTESTED; STA=UNTESTED; BOARD=UNTESTED";close $f
} else {
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv $rtl
    synth_design -top native_dynamic_clock_domain -mode out_of_context -part xczu15eg-ffvb1156-2-i -flatten_hierarchy none
    create_clock -name ui250 -period 4.0 [get_ports source_clock250]
    create_clock -name aon50 -period 20.0 [get_ports aon_clock]
    set clk [get_clocks -quiet -of_objects [get_pins managed_buffer/O]]
    if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-20.0)>0.002} {error "Actual boot managed clock is not50MHz"}
    if {[llength [get_cells -hier -filter {REF_NAME == MMCME4_ADV}]]!=1 ||
        [llength [get_cells -hier -filter {REF_NAME == BUFGCE}]]<1} {error "Required actual clock primitives missing"}
    write_checkpoint component-synthesized-unqualified.dcp
    report_clocks -file generated-clocks.rpt
    report_utilization -file utilization.rpt
    report_timing -from [get_pins gate/ce_reg/Q] -to [get_pins managed_buffer/CE] -delay_type min_max -max_paths 2 -file ce-timing.rpt
    check_timing -verbose -file coverage.rpt
    report_cdc -details -file cdc.rpt
    report_drc -file drc.rpt
    set f [open RESULT.txt w];puts $f "SOURCE_COMPONENT_SYNTHESIZED_UNQUALIFIED; OOC_IO_NOT_BOARD; TARGET_CPU300_FABRIC250_UNCHANGED; NO_BITSTREAM";close $f
}
puts "DYNAMIC_NATIVE_COMPONENT_STAGE_FINISHED mode=$mode"
