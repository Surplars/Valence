# Native six-mailbox CDC. Every bound names mapped sequential endpoints.
# No whole-clock cuts, false paths, multicycles or internal-clock relaxation.
# AMD UG903 2025.2 Constraining Asynchronous Signals: scoped datapath_only
# retains maximum-delay coverage; clock groups would override those bounds.
namespace eval spinor_cdc {variable endpoints {}; variable rows {}}
proc spinor_cdc::quote {s} {return [regsub -all {[][{}().+*?^$|\\]} $s {\\&}]}
proc spinor_cdc::one {command name} {
    set objects [$command -quiet -hierarchical -regexp "^[quote $name]$"]
    if {[llength $objects] != 1} {error "CDC exact object missing: $name"}
    return $objects
}
proc spinor_cdc::clock {cell} {
    set clocks [get_clocks -quiet -of_objects [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}]]
    if {[llength $clocks] != 1} {error "CDC FF clock ambiguous: $cell"}
    return [get_property NAME $clocks]
}
proc spinor_cdc::drivers {pin} {
    return [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}]
}
proc spinor_cdc::bound {starts ends budget label skew} {
    variable endpoints; variable rows
    if {![llength $starts] || ![llength $ends]} {error "CDC empty mapped bound: $label"}
    set_max_delay -datapath_only $budget -from $starts -to $ends
    if {$skew && [llength $starts] > 1 && [llength $ends] > 1} {
        set_bus_skew $budget -from $starts -to $ends
    }
    foreach end $ends {dict set endpoints [get_property NAME $end] 1}
    lappend rows [list $label [llength $starts] [llength $ends] $budget $skew]
    puts "SPINOR_CDC_BOUND $label starts=[llength $starts] ends=[llength $ends] budget=$budget skew=$skew"
}
proc spinor_cdc::level {root source target budget} {
    set first [one get_cells [format {%s/stages_reg[0]} $root]]
    set second [one get_cells [format {%s/stages_reg[1]} $root]]
    foreach cell [list $first $second] {
        if {[get_property REF_NAME $cell] ne "FDCE" || [clock $cell] ne $target ||
            [get_property ASYNC_REG $cell] ni {1 TRUE true}} {error "CDC synchronizer contract changed: $cell"}
    }
    set firstD [get_pins -of_objects $first -filter {REF_PIN_NAME == D}]
    set secondD [get_pins -of_objects $second -filter {REF_PIN_NAME == D}]
    set link [drivers $secondD]
    if {[llength $link] != 1 || [get_property NAME $link] ne "[get_property NAME $first]/Q"} {
        error "CDC synchronizer stages are not directly connected: $root"
    }
    set launch [drivers $firstD]
    if {[llength $launch] != 1 || [get_property REF_PIN_NAME $launch] ne "Q"} {
        error "CDC level is not launched by one direct FF: $root"
    }
    set cell [get_cells -of_objects $launch]
    if {![string match FD* [get_property REF_NAME $cell]] || [clock $cell] ne $source} {
        error "CDC level launch clock/primitive changed: $root"
    }
    bound [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}] $firstD $budget $root 0
}
proc spinor_cdc::payload {root source target budget} {
    set captures [get_cells -quiet -hierarchical -filter "IS_PRIMITIVE == TRUE && REF_NAME =~ FD* && NAME =~ ${root}/captured_reg*"]
    set held [get_cells -quiet -hierarchical -filter "IS_PRIMITIVE == TRUE && REF_NAME =~ FD* && NAME =~ ${root}/held_reg*"]
    if {![llength $captures]} {
        if {[llength $held]} {error "CDC held data remains without named capture bank: $root"}
        # Unused preview fields are eliminated naturally. Its control is still bounded.
        puts "SPINOR_CDC_PAYLOAD_ABSENT $root held=0 captured=0 NO_EXCEPTION"
        return
    }
    set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
    set starts {}
    foreach cell $captures {
        if {[clock $cell] ne $target} {error "CDC payload capture clock changed: $cell"}
    }
    foreach pin [all_fanin -flat -startpoints_only -to $ends] {
        set cell [get_cells -quiet -of_objects $pin]
        if {[llength $cell] != 1 || ![string match FD* [get_property REF_NAME $cell]]} {
            error "CDC payload contains a non-FF launch: $root $pin"
        }
        set domain [clock $cell]
        if {$domain eq $source} {
            lappend starts [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}]
        } elseif {$domain ne $target} {error "CDC payload third clock: $root $domain"}
    }
    bound [lsort -unique $starts] $ends $budget $root/payload 1
}

proc spinor_cdc::source_starts {ends target allowed} {
    set starts {}
    foreach pin [all_fanin -flat -startpoints_only -to $ends] {
        set cell [get_cells -quiet -of_objects $pin]
        if {![llength $cell]} {continue}
        set clocks [get_clocks -quiet -of_objects [get_pins -quiet -of_objects $cell -filter {IS_CLOCK == TRUE}]]
        foreach clk $clocks {
            set name [get_property NAME $clk]
            if {$name eq $target} {continue}
            if {$name ni $allowed} {error "unexpected clock in CDC cone: $pin $name"}
            foreach cpin [get_pins -quiet -of_objects $cell -filter {IS_CLOCK == TRUE}] {
                if {[get_clocks -quiet -of_objects $cpin] eq $clk} {lappend starts $cpin}
            }
        }
    }
    return [lsort -unique $starts]
}
proc spinor_cdc::apply {output} {
    variable endpoints; variable rows
    set endpoints {}; set rows {}; set budget 3.333333333
    set domains {i1_cpu300 i1_vpu300 i1_system300}
    # Native bundled-data payloads; retained six-box ownership contract.
    foreach {name source target} {
        commandBox i1_cpu300 i1_vpu300
        previewBox i1_vpu300 i1_cpu300
        grantBox i1_cpu300 i1_vpu300
        doneBox i1_vpu300 i1_cpu300
        memoryRequestBox i1_vpu300 i1_cpu300
        memoryResponseBox i1_cpu300 i1_vpu300
    } {payload unit/unit/boundary/$name $source $target $budget}
    payload unit/time_0 i1_system300 i1_cpu300 $budget
    # Persistent level and mailbox-toggle synchronizers. Keep stage0->stage1
    # under its ordinary local-clock setup/hold checks.
    foreach first [get_cells -quiet -hierarchical -regexp {^.*/stages_reg\[0\]$}] {
        set root [file dirname [get_property NAME $first]]
        set second [one get_cells [format {%s/stages_reg[1]} $root]]
        if {[get_property ASYNC_REG $first] ni {1 TRUE true} ||
            [get_property ASYNC_REG $second] ni {1 TRUE true}} {error "level sync attribute missing: $root"}
        set link [drivers [get_pins -of_objects $second -filter {REF_PIN_NAME == D}]]
        if {[llength $link] != 1 || [get_property NAME $link] ne "[get_property NAME $first]/Q"} {
            error "level synchronizer topology changed: $root"
        }
        set target [clock $first]
        set ends [get_pins -of_objects $first -filter {REF_PIN_NAME == D}]
        set starts [source_starts $ends $target $domains]
        if {[llength $starts]} {bound $starts $ends $budget $root/level 0}
    }
    # Each FIFO Gray bus has one source counter and a two-stage destination
    # synchronizer. Apply both maximum delay and skew only to stage zero.
    foreach root [get_cells -quiet -hierarchical -regexp {^unit/links_[01]/empty_fifo(_[0-4])?$}] {
        foreach stem {capturedGraySync writeGraySync} {
            set first [get_cells -quiet -hierarchical -filter "NAME =~ $root/${stem}_stage0_reg* && REF_NAME =~ FD*"]
            if {![llength $first]} {continue}
            set target [clock [lindex $first 0]]
            set ends [get_pins -of_objects $first -filter {REF_PIN_NAME == D}]
            foreach cell $first {
                if {[get_property ASYNC_REG $cell] ni {1 TRUE true} || [clock $cell] ne $target} {
                    error "Gray stage0 contract changed: $cell"
                }
                set suffix [string range [get_property NAME $cell] [string length "$root/${stem}_stage0_reg"] end]
                set second [one get_cells "$root/${stem}_reg$suffix"]
                set link [drivers [get_pins -of_objects $second -filter {REF_PIN_NAME == D}]]
                if {[llength $link] != 1 || [get_property NAME $link] ne "[get_property NAME $cell]/Q"} {
                    error "Gray synchronizer topology changed: $cell"
                }
            }
            set starts [source_starts $ends $target $domains]
            if {[llength $starts]} {bound $starts $ends $budget $root/$stem 1} else {puts "SYSTEM_CDC_NO_CROSS_CLOCK_LAUNCH $root/$stem NO_EXCEPTION"}
        }
        # Dual-clock synchronous-read storage is held until the destination
        # captures it; Gray ownership prevents overwrite of the read slot.
        set captures [get_cells -quiet -hierarchical -filter "NAME =~ $root/output_0_reg* && REF_NAME =~ FD*"]
        if {[llength $captures]} {
            set target [clock [lindex $captures 0]]
            set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
            set starts [source_starts $ends $target $domains]
            if {[llength $starts]} {bound $starts $ends $budget $root/storage 1}
        }
    }
    # Real BUFGCE uses CE_TYPE=SYNC. Its always-on held CE command is bounded
    # to the primitive CE pin; no fabric clock gating or clock-group cut.
    foreach gate {cpuGate vpuGate} {
        set cell [one get_cells $gate/buffer]
        if {[get_property REF_NAME $cell] ne "BUFGCE"} {error "managed clock primitive missing"}
        set ends [get_pins -of_objects $cell -filter {REF_PIN_NAME == CE}]
        set starts [source_starts $ends [expr {$gate eq "cpuGate" ? "i1_cpu300" : "i1_vpu300"}] $domains]
        bound $starts $ends $budget $gate/heldCE 0
    }
    set fd [open [file join $output cdc_scopes.tsv] w]
    puts $fd "scope\tstarts\tends\tbudget_ns\tbus_skew"
    foreach row $rows {puts $fd [join $row "\t"]}
    close $fd
}
proc spinor_cdc::states {clockName} {
    return [all_registers -clock $clockName]
}
proc spinor_cdc::coverage {output} {
    variable endpoints
    set fd [open [file join $output cdc_coverage.tsv] w]
    puts $fd "direction\tstart\tend\tslack_ns"
    set total 0
    foreach source {i1_cpu300 i1_vpu300 i1_system300} {
        foreach target {i1_cpu300 i1_vpu300 i1_system300} {
            if {$source eq $target} {continue}
            set paths [get_timing_paths -from [states $source] -to [states $target] -delay_type max -nworst 1 -max_paths 10000]
            if {[llength $paths] >= 10000} {error "CDC endpoint enumeration limit reached"}
            foreach path $paths {
                set end [get_property ENDPOINT_PIN $path]
                if {![dict exists $endpoints $end]} {error "unbounded register-to-register CDC: $source -> $target $end"}
                puts $fd "$source->$target\t[get_property STARTPOINT_PIN $path]\t$end\t[get_property SLACK $path]"
                incr total
            }
        }
    }
    close $fd
    if {!$total} {error "empty CDC coverage"}
    puts "SYSTEM_CDC_COVERAGE paths=$total mapped_endpoints=[dict size $endpoints]"
}
