# Continue THIS candidate's own fully expanded optimized netlist. No synthesis,
# donor import, constraint edits or bit generation. Keep the failed run intact.
if {$argc != 1} {error "Expected CANDIDATE_ROOT"}
set root [file normalize [lindex $argv 0]]
set checkpoint [file join $root implementation optimized.dcp]
set out [file join $root implementation-resume-opt-r1]
set isa rv64gc
if {![file isfile $checkpoint] || [file exists $out]} {
    error "Missing own optimized checkpoint or non-fresh continuation output"
}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved functional netlist"}
if {[llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] != 1} {
    error "Own checkpoint must contain the complete RV64GC FPU"
}
foreach {pin hz} {
    u_soc/clock 100000000 u_soc/io_alwaysOnClock 50000000
    u_soc/nativeBank/uart/uart/clock 50000000 u_soc/io_nativeGmac_rawTxClock 125000000
    u_rgmii/delay_clock 500000000
} {
    set clk [get_clocks -quiet -of_objects [get_pins $pin]]
    if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-1.0e9/$hz)>0.001} {
        error "Saved complete-board clock contract changed: $pin"
    }
}
foreach port [get_ports] {
    if {[get_property PACKAGE_PIN $port] eq "" || [get_property IOSTANDARD $port] in {"" DEFAULT}} {
        error "Saved complete-board I/O missing constraints: $port"
    }
}
# These files declare audit procedures. Do NOT call their constraint setters:
# optimized.dcp already contains the actual audited constraints from this run.
source [file join $root scripts native_board_constraints.tcl]
report_clocks -file restored_clocks.rpt
write_xdc -type timing restored_constraints.xdc
puts "NATIVE_BOARD_RESUME_OWN_OPTIMIZED $checkpoint NO_REFERENCE_IMPORT NO_CONSTRAINT_CHANGES"
# Reuse the exact production placement/route/report tail, so every TX/RX lane,
# quarter-clock topology, CDC/skew and divider check remains mandatory.
set f [open [file join $root scripts build_native_board.tcl] r]
set original [read $f]
close $f
set marker "\nplace_design -directive Explore\n"
set start [string first $marker $original]
if {$start<0 || $start != [string last $marker $original]} {
    error "Production implementation/report tail is not uniquely identified"
}
eval [string range $original [expr {$start+1}] end]
