# Read-only reports from an already routed no-MAC I1 board. No implementation
# command, timing exception, clock definition or bit generation is permitted.
if {$argc!=1} {error "Usage: review_board_cpu.tcl <existing-board-root>"}
set root [file normalize [lindex $argv 0]]
set dcp [file join $root reports real_board_routed.dcp]
if {![file isfile $dcp]} {error "Existing routed checkpoint required"}
set out [file join $root reports review-r4]
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $dcp
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {
    error "Wrong actual FPGA part"
}
set f [open [file join $out domains.tsv] w]
puts $f "domain\tclock\tperiod_ns\tdelay\tslack_ns\tstartpoint\tendpoint"
proc domain_report {name c} {
    global f out
    if {[llength $c]!=1} {error "Exactly one actual clock required: $name"}
    foreach delay {max min} {
        set p [get_timing_paths -from $c -to $c -delay_type $delay -max_paths 1]
        if {[llength $p]!=1} {error "Missing timed paths: $name $delay"}
        puts $f "$name\t[get_property NAME $c]\t[get_property PERIOD $c]\t$delay\t[get_property SLACK $p]\t[get_property STARTPOINT_PIN $p]\t[get_property ENDPOINT_PIN $p]"
        report_timing -from $c -to $c -delay_type $delay -max_paths 10 \
            -file [file join $out [format "%s_%s.rpt" $name $delay]]
    }
}
foreach {name pin expected} {CPU300 u_soc/io_clockIn 3.333
                           DDR_UI250 u_axi_cdc/m_axi_aclk 4.000
                           AON50 u_soc/io_alwaysOnClock 20.000} {
    set c [get_clocks -of_objects [get_pins $pin]]
    if {[llength $c]!=1 || abs([get_property PERIOD $c]-$expected)>0.002} {
        error "Actual clock/period changed: $name"
    }
    domain_report $name $c
}
# The unused hierarchical ManagedUart.managedClock output is optimized away.
# Qualify the actual UART storage clock pins, not a net name or a new clock.
set uartCells [get_cells -hier -filter {IS_SEQUENTIAL && NAME =~ u_soc/bank/uart/uart/*}]
if {[llength $uartCells]<10} {error "Actual UART sequential cells missing"}
set uartClockPins [get_pins -of_objects $uartCells -filter {REF_PIN_NAME == C}]
set uartClocks [get_clocks -of_objects $uartClockPins]
if {[llength $uartClocks]!=1 || abs([get_property PERIOD $uartClocks]-20.0)>0.002} {
    error "Actual UART storage clock is not independently buffered UART50"
}
domain_report UART50 $uartClocks
foreach delay {max min} {
    report_timing -from $uartCells -to $uartCells -delay_type $delay -max_paths 10 \
        -file [file join $out [format "UART_LOCAL_%s.rpt" $delay]]
}
close $f
set f [open [file join $out families.tsv] w]
puts $f "family\tcell_count\tslack_ns\tstartpoint\tendpoint"
foreach {name pattern direction} {
    PMP_UPPER u_soc/soc/core/core/csr/effectiveUpper* from
    PMP_LOWER u_soc/soc/core/core/csr/effectiveLower* from
    IT u_soc/soc/core/it/* to
    DT u_soc/soc/core/dt/* to
    ICACHE u_soc/soc/core/icache/* to
    DCACHE u_soc/soc/core/dcache/* to
    ALU_RESULT u_soc/soc/core/core/addrPacket_result_reg* to
    FPU u_soc/soc/core/core/execute/* to
} {
    set cells [get_cells -hier -filter "IS_SEQUENTIAL && NAME =~ $pattern"]
    if {[llength $cells]==0} {error "Expected CPU path family missing: $name"}
    set p [get_timing_paths -$direction $cells -delay_type max -max_paths 1]
    if {[llength $p]!=1} {error "Expected timed CPU path family missing: $name"}
    puts $f "$name\t[llength $cells]\t[get_property SLACK $p]\t[get_property STARTPOINT_PIN $p]\t[get_property ENDPOINT_PIN $p]"
    report_timing -$direction $cells -delay_type max -max_paths 5 -input_pins \
        -file [file join $out [format "family_%s.rpt" $name]]
}
close $f
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set f [open [file join $out stage-result.txt] w]
puts $f "REAL_BOARD CPU300 UI250 AON50 UART50 I32KiB D32KiB FD Sv39 PLIC CMU USER2 MAC_ABSENT"
puts $f "WNS=$setup WHS=$hold STATUS=ROUTED_REQUIRES_REPORT_REVIEW NO_BIT_GENERATED"
puts $f "READ_ONLY_REPORT_RECOVERY original_UART_output_pin_optimized_away"
close $f
puts "I1_CPU_BOARD_REVIEW WNS=$setup WHS=$hold NO_DESIGN_CHANGES"
close_design
