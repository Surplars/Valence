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
proc spinor_cdc::apply {output} {
    variable endpoints; variable rows
    set endpoints {}; set rows {}
    set budget 3.333333333
    foreach {name source target} {
        commandBox i1_cpu300 i1_vpu300
        previewBox i1_vpu300 i1_cpu300
        grantBox i1_cpu300 i1_vpu300
        doneBox i1_vpu300 i1_cpu300
        memoryRequestBox i1_vpu300 i1_cpu300
        memoryResponseBox i1_cpu300 i1_vpu300
    } {
        set root dut/boundary/$name
        one get_cells $root
        payload $root $source $target $budget
        level $root/requestSync $source $target $budget
        level $root/ackSync $target $source $budget
    }
    level dut/error i1_vpu300 i1_cpu300 $budget
    set fd [open [file join $output cdc_scopes.tsv] w]
    puts $fd "scope\tstarts\tends\tbudget_ns\tbus_skew"
    foreach row $rows {puts $fd [join $row "\t"]}
    close $fd
}
proc spinor_cdc::coverage {cpu vpu output} {
    variable endpoints
    set fd [open [file join $output cdc_coverage.tsv] w]
    puts $fd "direction\tstart\tend\tslack_ns"
    set total 0
    foreach {source target label} [list $cpu $vpu cpu_to_vpu $vpu $cpu vpu_to_cpu] {
        set paths [get_timing_paths -from $source -to $target -delay_type max -nworst 1 -max_paths 10000]
        if {[llength $paths] >= 10000} {error "CDC endpoint enumeration limit reached"}
        foreach path $paths {
            set end [get_property ENDPOINT_PIN $path]
            if {![dict exists $endpoints $end]} {error "unbounded register-to-register CDC: $end"}
            puts $fd "$label\t[get_property STARTPOINT_PIN $path]\t$end\t[get_property SLACK $path]"
            incr total
        }
    }
    close $fd
    if {!$total} {error "CDC timing coverage is empty"}
    puts "SPINOR_CDC_COVERAGE paths=$total mapped_endpoints=[dict size $endpoints]"
}
