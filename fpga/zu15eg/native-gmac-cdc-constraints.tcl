# Only the new native frame/config/event/retention boundary. No global
# set_clock_groups or broad false paths: payloads and Gray pointers are timed.
source [file join [file dirname [info script]] cdc_constraints.tcl]
proc valence_level_cdc_constraint {hier budget} {
    set captures [get_cells -quiet "$hier/stages_reg?0?"]
    if {[llength $captures] != 1} { error "Missing level first stage: $hier" }
    set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
    set drivers [all_fanin -flat -startpoints_only -to $ends]
    set starts [get_pins -of_objects [get_cells -of_objects $drivers] -filter {REF_PIN_NAME == C}]
    if {[llength $starts] != 1} { error "Level CDC is not driven by ONE registered bit: $hier" }
    set_max_delay -datapath_only $budget -from $starts -to $ends
    puts "NATIVE_GMAC_CDC_LEVEL $hier budget=$budget"
}
proc valence_mailbox_cdc_constraints {hier budget} {
    valence_cdc_bus [get_cells -quiet "$hier/held*_reg*"] \
        [get_cells -quiet "$hier/captured*_reg*"] $budget "$hier atomic_payload"
    valence_level_cdc_constraint "$hier/requestSync" $budget
    valence_level_cdc_constraint "$hier/ackSync" $budget
}
# Shared read-only discovery/checking for the constraint recipe and MAC audit.
# Resolve timing-graph leaf startpoints from each capture D, never collect RAM
# clock names across a hierarchy. Composite RAM32M16/WCLK is not a legal launch.
namespace eval valence_fifo_payload {}
proc valence_fifo_payload::quote {text} {return [regsub -all {[][{}().+*?^$|\\]} $text {\\&}]}
proc valence_fifo_payload::one {command name} {
    set objects [$command -quiet -hierarchical -regexp "^[quote $name]$"]
    if {[llength $objects]!=1 || [get_property NAME $objects] ne $name} {
        error "FIFO exact object missing/ambiguous: $name"
    }
    return $objects
}
proc valence_fifo_payload::clock {pin} {
    set clocks [get_clocks -quiet -of_objects $pin]
    if {[llength $clocks]!=1} {error "FIFO missing/ambiguous clock: $pin"}
    return [get_property NAME $clocks]
}
proc valence_fifo_payload::collect {hier {width 38}} {
    if {$width!=38} {error "FIFO payload contract requires 38 bits: $hier"}
    set pattern "^[quote $hier/output_0_reg]"
    append pattern {\[[0-9]+\]$}
    set captures [get_cells -quiet -hierarchical -regexp $pattern]
    if {[llength $captures]!=$width} {error "FIFO capture bank shape changed: $hier"}
    set source [clock [one get_pins $hier/sourceClock]]
    set target [clock [one get_pins $hier/destinationClock]]
    set by_end [dict create]; set ordinary_by_end [dict create]
    set ends {}; set starts {}; set ordered {}
    for {set bit 0} {$bit<$width} {incr bit} {
        set name [format {%s/output_0_reg[%d]} $hier $bit]
        set cell [one get_cells $name]
        if {[get_property IS_SEQUENTIAL $cell] ni {1 TRUE true} ||
            [get_property REF_NAME $cell] ni {FDRE FDSE FDCE FDPE}} {
            error "FIFO capture is not a reviewed FF: $name"
        }
        set end [get_pins -of_objects $cell -filter {REF_PIN_NAME == D}]
        set cp [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}]
        if {[llength $end]!=1 || [llength $cp]!=1 ||
            [get_property NAME $end] ne "$name/D" ||
            [get_property NAME $cp] ne "$name/C" ||
            [get_property IS_LEAF $end] ni {1 TRUE true} ||
            [get_property DIRECTION $end] ne "IN" || [clock $cp] ne $target} {
            error "FIFO capture pin/clock shape changed: $name"
        }
        set launches {}; set ordinary {}
        foreach pin [all_fanin -flat -startpoints_only -to $end] {
            set pname [get_property NAME $pin]
            set ram [get_cells -quiet -of_objects $pin]
            if {[llength $ram]!=1} {error "FIFO unknown timing startpoint owner: $pname"}
            set ref [get_property REF_NAME $ram]
            # Read-address and output-feedback FF clocks may occur inside or
            # outside storage_ext. Only actual destination-domain leaf FF C
            # pins can be left under ordinary timing. A foreign-clock bypass,
            # Q pin, input port or unknown primitive must never be skipped.
            if {$ref in {FDRE FDSE FDCE FDPE}} {
                if {[get_property IS_SEQUENTIAL $ram] ni {1 TRUE true} ||
                    [get_property IS_PRIMITIVE $ram] ni {1 TRUE true} ||
                    [get_property IS_LEAF $pin] ni {1 TRUE true} ||
                    [get_property REF_PIN_NAME $pin] ne "C" ||
                    [get_property DIRECTION $pin] ne "IN" ||
                    "[get_property NAME $ram]/C" ne $pname} {
                    error "FIFO ordinary launch is not a reviewed leaf FF clock: $pname"
                }
                if {[clock $pin] ne $target} {error "FIFO foreign-domain ordinary launch: $pname"}
                lappend ordinary $pin
                continue
            }
            if {[string first "$hier/storage_ext/" $pname]!=0 ||
                [get_property IS_LEAF $pin] ni {1 TRUE true} ||
                [get_property DIRECTION $pin] ne "IN" ||
                [get_property REF_PIN_NAME $pin] ni {CLK WCLK} ||
                $ref ni {RAMD32 RAMS32 RAMD64E RAMS64E} ||
                [get_property IS_PRIMITIVE $ram] ni {1 TRUE true}} {
                error "FIFO RAM startpoint is not a reviewed leaf clock: $pname"
            }
            if {[clock $pin] ne $source} {error "FIFO RAM write clock mismatch: $pname"}
            if {[lsearch -exact $launches $pin]>=0} {error "FIFO duplicate RAM startpoint: $pname"}
            lappend launches $pin
            if {[lsearch -exact $starts $pin]<0} {lappend starts $pin}
        }
        if {![llength $launches]} {error "FIFO uncovered payload bit: $name/D"}
        dict set by_end [get_property NAME $end] $launches
        dict set ordinary_by_end [get_property NAME $end] $ordinary
        lappend ends {*}$end; lappend ordered {*}$cell
    }
    return [dict create starts $starts ends $ends captures $ordered by_end $by_end ordinary_by_end $ordinary_by_end]
}
proc valence_fifo_payload::check_paths {scope {budget {}}} {
    set numeric {^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$}
    set checked 0
    foreach end [dict get $scope ends] {
        set ename [get_property NAME $end]
        foreach start [dict get $scope by_end $ename] {
            set sname [get_property NAME $start]
            set paths [get_timing_paths -quiet -from $start -to $end -delay_type max -max_paths 1 -nworst 1]
            if {[llength $paths]!=1} {error "FIFO missing/false-pathed RAM path: $sname -> $ename"}
            set path [lindex $paths 0]
            if {[get_property STARTPOINT_PIN $path] ne $sname || [get_property ENDPOINT_PIN $path] ne $ename} {
                error "FIFO timing startpoint/endpoint mismatch: $sname -> $ename"
            }
            if {$budget ne ""} {
                set requirement [get_property REQUIREMENT $path]
                set exception [get_property EXCEPTION $path]
                # An ordinary 8 ns clock requirement is not proof that the
                # requested max-delay exception is active. Fail on empty or
                # unrecognized exception types, including a silently ignored
                # constraint. Exact datapath-only/skew coverage still requires
                # the Vivado exception and bus-skew reports in the audit.
                set kind [string tolower [string map {_ {} - {} { } {}} $exception]]
                if {![regexp $numeric $requirement] || $requirement<=0 ||
                    $requirement>$budget+0.001 || ![string match maxdelay* $kind]} {
                    error "FIFO missing/ignored/relaxed max-delay bound: $sname -> $ename requirement=$requirement exception=$exception"
                }
            }
            incr checked
        }
    }
    return $checked
}
proc valence_fifo_payload_constraints {hier budget} {
    if {![string is double -strict $budget] || $budget<=0 || $budget==Inf} {
        error "FIFO finite positive payload budget required: $hier"
    }
    set scope [valence_fifo_payload::collect $hier]
    # Validate every leaf-to-bit path before creating either exception.
    valence_fifo_payload::check_paths $scope
    set starts [dict get $scope starts]; set ends [dict get $scope ends]
    set_max_delay -datapath_only $budget -from $starts -to $ends
    set_bus_skew $budget -from $starts -to $ends
    set paths [valence_fifo_payload::check_paths $scope $budget]
    puts "NATIVE_GMAC_RAM_BOUNDED $hier starts=[llength $starts] ends=[llength $ends] paths=$paths budget=$budget EXCEPTION_AND_SKEW_REVIEW_REQUIRED"
}
proc valence_native_gmac_cdc_constraints {root budget} {
    set prefix [expr {$root eq "" ? "" : "$root/"}]
    foreach name {txFifo rxFifo} {
        valence_stream_cdc_constraints "${prefix}${name}/fifo" $budget
        valence_fifo_payload_constraints "${prefix}${name}/fifo" $budget
    }
    foreach name {txConfig rxConfig txEvents rxEvents} {
        valence_mailbox_cdc_constraints "${prefix}${name}/mailbox" $budget
    }
    valence_level_cdc_constraint "${prefix}policy/ack" $budget
    valence_level_cdc_constraint "${prefix}agent/request" $budget
}
