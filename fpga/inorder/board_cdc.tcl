# Exact CDC constraints for the full board. Local synchronizer stages retain
# ordinary setup/hold checks. No clock groups, blanket cuts or multicycles.
source [file join [file dirname [info script]] system_cdc.tcl]
namespace eval board_cdc {variable clocks {}; variable root {}}
proc board_cdc::apply {output} {
    variable clocks; variable root
    set cpu [get_cells -quiet -hier -filter {REF_NAME == BUFGCE && NAME =~ */cpuGate/buffer}]
    set vpu [get_cells -quiet -hier -filter {REF_NAME == BUFGCE && NAME =~ */vpuGate/buffer}]
    if {[llength $cpu] != 1 || [llength $vpu] != 1} {error "board managed clock roots missing"}
    set root [file dirname [file dirname [get_property NAME $cpu]]]
    set psroot [file dirname $root]
    set cpuClock [get_clocks -of_objects [get_pins $cpu/O]]
    set vpuClock [get_clocks -of_objects [get_pins $vpu/O]]
    set systemClock [get_clocks -of_objects [get_pins $root/unit/systemClock]]
    set clocks [list $cpuClock $vpuClock $systemClock]
    if {[llength [lsort -unique $clocks]] != 3} {error "board clock domains were merged"}
    foreach clk $clocks {
        set_clock_uncertainty -setup 0.100 [get_clocks $clk]
        set_clock_uncertainty -hold 0.080 [get_clocks $clk]
    }
    set spinor_cdc::endpoints {}; set spinor_cdc::rows {}
    set budget 3.333333333
    foreach {box source target} [list commandBox $cpuClock $vpuClock previewBox $vpuClock $cpuClock \
        grantBox $cpuClock $vpuClock doneBox $vpuClock $cpuClock \
        memoryRequestBox $vpuClock $cpuClock memoryResponseBox $cpuClock $vpuClock] {
        spinor_cdc::payload $root/unit/unit/boundary/$box $source $target $budget
    }
    spinor_cdc::payload $root/unit/time_0 $systemClock $cpuClock $budget
    foreach first [get_cells -quiet -hier -regexp {^.*/stages_reg\[0\]$}] {
        set name [get_property NAME $first]
        if {![string match "$root/*" $name] && ![string match "$psroot/boot/*" $name]} {continue}
        set sync [file dirname $name]
        set second [spinor_cdc::one get_cells [format {%s/stages_reg[1]} $sync]]
        if {[get_property ASYNC_REG $first] ni {1 TRUE true} || [get_property ASYNC_REG $second] ni {1 TRUE true}} {
            error "board level synchronizer attributes missing: $sync"
        }
        set firstD [get_pins -of_objects $first -filter {REF_PIN_NAME == D}]
        set secondD [get_pins -of_objects $second -filter {REF_PIN_NAME == D}]
        set link [spinor_cdc::drivers $secondD]
        if {[llength $link] != 1 || [get_property NAME $link] ne "$name/Q"} {error "board level topology changed: $sync"}
        set launch [spinor_cdc::drivers $firstD]
        if {[llength $launch] == 1 && [get_property REF_NAME [get_cells -of_objects $launch]] eq "PS8"} {
            # EMIO is a persistent asynchronous PS level, captured only by stage zero.
            spinor_cdc::bound $launch $firstD $budget $sync/PS_GPIO 0
        } else {
            set starts [spinor_cdc::source_starts $firstD [spinor_cdc::clock $first] $clocks]
            if {[llength $starts]} {spinor_cdc::bound $starts $firstD $budget $sync/level 0}
        }
    }
    set roots [get_cells -quiet -hier -regexp "^[spinor_cdc::quote $root]/unit/links_\[01\]/empty_fifo(_\[0-4\])?$" ]
    foreach fifo $roots {
        foreach stem {capturedGraySync writeGraySync} {
            set first [get_cells -quiet -hier -filter "NAME =~ $fifo/${stem}_stage0_reg* && REF_NAME =~ FD*"]
            if {![llength $first]} {continue}
            set target [spinor_cdc::clock [lindex $first 0]]
            set ends [get_pins -of_objects $first -filter {REF_PIN_NAME == D}]
            foreach cell $first {
                if {[get_property ASYNC_REG $cell] ni {1 TRUE true} || [spinor_cdc::clock $cell] ne $target} {
                    error "board Gray stage0 contract changed: $cell"
                }
                set suffix [string range [get_property NAME $cell] [string length "$fifo/${stem}_stage0_reg"] end]
                set second [spinor_cdc::one get_cells "$fifo/${stem}_reg$suffix"]
                set link [spinor_cdc::drivers [get_pins -of_objects $second -filter {REF_PIN_NAME == D}]]
                if {[llength $link] != 1 || [get_property NAME $link] ne "[get_property NAME $cell]/Q"} {
                    error "board Gray topology changed: $cell"
                }
            }
            set starts [spinor_cdc::source_starts $ends $target $clocks]
            if {[llength $starts]} {spinor_cdc::bound $starts $ends $budget $fifo/$stem 1}
        }
        set captures [get_cells -quiet -hier -filter "NAME =~ $fifo/output_0_reg* && REF_NAME =~ FD*"]
        if {[llength $captures]} {
            set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
            set starts [spinor_cdc::source_starts $ends [spinor_cdc::clock [lindex $captures 0]] $clocks]
            if {[llength $starts]} {spinor_cdc::bound $starts $ends $budget $fifo/storage 1}
        }
    }
    # Boot release is an asynchronous reset epoch from the system domain.
    # Only release synchronizer PRE pins cross domains; the CPU leaf uses two.
    # Bound their physical propagation; downstream local reset recovery stays timed.
    foreach release [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {
        if {![string match "$psroot/*" [get_property NAME $release]]} {continue}
        set regs [get_cells -quiet -hier -filter "NAME =~ $release/release_0_reg* && REF_NAME == FDPE"]
        if {![llength $regs]} {continue}
        set count [expr {[get_property NAME $release] eq "$root/unit/unit/cpuRelease" ? 2 : 3}]
        if {[llength $regs] != $count} {error "reset-release stage count changed: $release"}
        set target [spinor_cdc::clock [lindex $regs 0]]
        foreach cell $regs {
            if {[get_property ASYNC_REG $cell] ni {1 TRUE true} || [spinor_cdc::clock $cell] ne $target} {
                error "reset-release topology/clock contract changed: $release"
            }
        }
        set ends [get_pins -of_objects $regs -filter {REF_PIN_NAME == PRE}]
        set starts [spinor_cdc::source_starts $ends $target $clocks]
        if {[llength $starts]} {spinor_cdc::bound $starts $ends $budget $release/resetEntry 0}
    }
    foreach gate [list $cpu $vpu] target [list $cpuClock $vpuClock] {
        set ends [get_pins -of_objects $gate -filter {REF_PIN_NAME == CE}]
        spinor_cdc::bound [spinor_cdc::source_starts $ends $target $clocks] $ends $budget $gate/heldCE 0
    }
    # The off-board UART receiver is asynchronous. Its two existing FFs are
    # physically marked as a synchronizer; only the input-to-stage0 path is bounded.
    set rx [get_cells -quiet -hier -filter {NAME =~ */rxMeta_reg && REF_NAME =~ FD*}]
    if {[llength $rx] != 1} {error "board UART first stage missing"}
    set rx2 [spinor_cdc::one get_cells [file dirname $rx]/rxSync_reg]
    set link [spinor_cdc::drivers [get_pins -of_objects $rx2 -filter {REF_PIN_NAME == D}]]
    if {[llength $link] != 1 || [get_property NAME $link] ne "$rx/Q"} {error "UART synchronizer topology changed"}
    set_property ASYNC_REG TRUE [list $rx $rx2]
    # External UART propagation uses one 16x baud tick. Its first FF has no
    # phase relationship to the transmitter; the local FF-to-FF path stays timed.
    set uartBudget [expr {1000000000.0 / (460800 * 16)}]
    spinor_cdc::bound [get_ports uartRx] [get_pins -of_objects $rx -filter {REF_PIN_NAME == D}] $uartBudget UART_RX_ASYNC_BAUD 0
    # UART has an independent asynchronous receiver, not a 300 MHz capture clock.
    # Bound TX propagation to one tick of the fastest supported 16x baud reference.
    # Internal system-clock paths retain their original period and uncertainty.
    # Same 460800-baud reference contract as UART RX above.
    set txStarts [spinor_cdc::source_starts [get_ports uartTx] {} [list $systemClock]]
    spinor_cdc::bound $txStarts [get_ports uartTx] $uartBudget UART_TX_ASYNC_BAUD 0
    set fd [open [file join $output board_clock_contract.tsv] w]
    foreach role {CPU VPU SYSTEM} clk $clocks {puts $fd "$role\t$clk\t[get_property PERIOD [get_clocks $clk]]"}
    close $fd
    set fd [open [file join $output cdc_scopes.tsv] w]
    puts $fd "scope\tstarts\tends\tbudget_ns\tbus_skew"
    foreach row $spinor_cdc::rows {puts $fd [join $row "\t"]}
    close $fd
    return $clocks
}
proc board_cdc::coverage {output} {
    variable clocks
    set fd [open [file join $output cdc_coverage.tsv] w]
    puts $fd "direction\tstart\tend\tslack_ns"
    set total 0
    foreach source $clocks {
        foreach target $clocks {
            if {$source eq $target} {continue}
            set paths [get_timing_paths -from [all_registers -clock $source] -to [all_registers -clock $target] \
                -delay_type max -nworst 1 -max_paths 10000]
            if {[llength $paths] >= 10000} {error "board CDC enumeration limit reached"}
            foreach path $paths {
                set end [get_property ENDPOINT_PIN $path]
                if {![dict exists $spinor_cdc::endpoints $end]} {error "unbounded board CDC: $source -> $target $end"}
                puts $fd "$source->$target\t[get_property STARTPOINT_PIN $path]\t$end\t[get_property SLACK $path]"
                incr total
            }
        }
    }
    close $fd
    if {!$total} {error "empty board CDC coverage"}
    puts "BOARD_CDC_COVERAGE paths=$total bounded_endpoints=[dict size $spinor_cdc::endpoints]"
}
