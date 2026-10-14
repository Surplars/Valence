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
# Tcl list/dict operations can lose Vivado collection typing. Re-resolve the
# exact escaped names and verify the entire set before every collection boundary.
proc valence_fifo_payload::objects {command names} {
    set expected [lsort -unique $names]
    if {![llength $expected]} {error "Empty exact object collection"}
    set patterns [lmap name $expected {format {^%s$} [quote $name]}]
    set found [$command -quiet -hierarchical -regexp $patterns]
    if {[llength $found]!=[llength $expected] || [lsort [get_property NAME $found]] ne $expected} {
        error "Exact object collection changed: $names"
    }
    return $found
}
proc valence_fifo_payload::clock {pin} {
    set clocks [get_clocks -quiet -of_objects $pin]
    if {[llength $clocks]!=1} {error "FIFO missing/ambiguous clock: $pin"}
    return [get_property NAME $clocks]
}
# Typed pins only; the cache belongs to one collect call, never a design stage.
proc valence_fifo_payload::clock_of {pin cacheName} {
    upvar 1 $cacheName cache
    set name [get_property NAME $pin]
    if {![dict exists $cache $name]} {dict set cache $name [clock $pin]}
    return [dict get $cache $name]
}
proc valence_fifo_payload::collect {hier {width 38}} {
    if {$width!=38} {error "FIFO payload contract requires 38 bits: $hier"}
    set pattern "^[quote $hier/output_0_reg]"
    append pattern {\[[0-9]+\]$}
    set captures [get_cells -quiet -hierarchical -regexp $pattern]
    if {[llength $captures]!=$width} {error "FIFO capture bank shape changed: $hier"}
    set captureNames [get_property NAME $captures]
    set expectedCaptures {}
    for {set bit 0} {$bit<$width} {incr bit} {lappend expectedCaptures [format {%s/output_0_reg[%d]} $hier $bit]}
    if {[lsort $captureNames] ne [lsort $expectedCaptures]} {error "FIFO exact capture bank differs: $hier"}
    set clockCache {}
    set source [clock_of [one get_pins $hier/sourceClock] clockCache]
    set target [clock_of [one get_pins $hier/destinationClock] clockCache]
    set by_end [dict create]; set ordinary_by_end [dict create]
    set ends {}; set starts {}; set ordered {}
    for {set bit 0} {$bit<$width} {incr bit} {
        set name [format {%s/output_0_reg[%d]} $hier $bit]
        set cell [lindex $captures [lsearch -exact $captureNames $name]]
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
            [get_property DIRECTION $end] ne "IN" || [clock_of $cp clockCache] ne $target} {
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
                if {[clock_of $pin clockCache] ne $target} {error "FIFO foreign-domain ordinary launch: $pname"}
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
            if {[clock_of $pin clockCache] ne $source} {error "FIFO RAM write clock mismatch: $pname"}
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
proc valence_fifo_payload::checked_pair {path expected budget} {
    set sname [get_property STARTPOINT_PIN $path]
    set ename [get_property ENDPOINT_PIN $path]
    set pair [list $sname $ename]
    if {![dict exists $expected $pair]} {error "FIFO unexpected timing pair: $sname -> $ename"}
    if {$budget ne ""} {
        set requirement [get_property REQUIREMENT $path]
        set exception [get_property EXCEPTION $path]
        set numeric {^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$}
        set kind [string tolower [string map {_ {} - {} { } {}} $exception]]
        if {![regexp $numeric $requirement] || $requirement<=0 ||
            $requirement>$budget+0.001 || ![string match maxdelay* $kind]} {
            error "FIFO missing/ignored/relaxed max-delay bound: $sname -> $ename requirement=$requirement exception=$exception"
        }
    }
    return $pair
}
proc valence_fifo_payload::check_paths {scope {budget {}} {starts {}} {ends {}}} {
    set begun [::clock milliseconds]
    if {$starts eq ""} {set starts [objects get_pins [dict get $scope starts]]}
    if {$ends eq ""} {set ends [objects get_pins [dict get $scope ends]]}
    set snames [get_property NAME $starts]; set enames [get_property NAME $ends]
    if {[lsort $snames] ne [lsort -unique [dict get $scope starts]] ||
        [lsort $enames] ne [lsort -unique [dict get $scope ends]]} {error "FIFO typed scope differs"}
    set expected {}; set observed {}; set queries 1
    foreach ename [dict get $scope ends] {
        foreach sname [dict get $scope by_end $ename] {
            if {$sname ni $snames} {error "FIFO launch outside exact scope"}
            dict set expected [list $sname $ename] 1
        }
    }
    puts "FIFO_PATHS_BEGIN starts=[llength $starts] ends=[llength $ends] pairs=[dict size $expected] budget=$budget"
    flush stdout
    set paths [get_timing_paths -quiet -from $starts -to $ends -delay_type max -max_paths [llength $ends] -nworst 1]
    foreach path $paths {dict set observed [checked_pair $path $expected $budget] 1}
    puts "FIFO_BATCH_DONE covered=[dict size $observed] missing=[expr {[dict size $expected]-[dict size $observed]}] elapsed_ms=[expr {[::clock milliseconds]-$begun}]"
    flush stdout
    # Batch worst paths need not cover every legal RAM launch. Query ONLY the
    # missing exact pairs. Typed objects come from the original collections,
    # never another full-design regex lookup, and no cache crosses this call.
    dict for {pair ignored} $expected {
        if {[dict exists $observed $pair]} {continue}
        lassign $pair sname ename
        set start [lindex $starts [lsearch -exact $snames $sname]]
        set end [lindex $ends [lsearch -exact $enames $ename]]
        set paths [get_timing_paths -quiet -from $start -to $end -delay_type max -max_paths 1 -nworst 1]
        incr queries
        if {[llength $paths]!=1 || [checked_pair [lindex $paths 0] $expected $budget] ne $pair} {
            error "FIFO missing/false-pathed RAM path: $sname -> $ename"
        }
        dict set observed $pair 1
    }
    if {[lsort [dict keys $observed]] ne [lsort [dict keys $expected]]} {error "FIFO incomplete exact pair coverage"}
    puts "FIFO_PATHS_DONE pairs=[dict size $observed] queries=$queries elapsed_ms=[expr {[::clock milliseconds]-$begun}] budget=$budget"
    flush stdout
    return [dict size $observed]
}
proc valence_fifo_payload_constraints {hier budget} {
    if {![string is double -strict $budget] || $budget<=0 || $budget==Inf} {
        error "FIFO finite positive payload budget required: $hier"
    }
    set begun [clock milliseconds]
    puts "FIFO_COLLECT_BEGIN $hier"; flush stdout
    set scope [valence_fifo_payload::collect $hier]
    puts "FIFO_COLLECT_DONE $hier elapsed_ms=[expr {[clock milliseconds]-$begun}]"; flush stdout
    # Resolve collections once in this gate, then retain typed objects through
    # pre/post path checking and both unchanged constraints.
    set starts [valence_fifo_payload::objects get_pins [dict get $scope starts]]
    set ends [valence_fifo_payload::objects get_pins [dict get $scope ends]]
    valence_fifo_payload::check_paths $scope {} $starts $ends
    set_max_delay -datapath_only $budget -from $starts -to $ends
    set_bus_skew $budget -from $starts -to $ends
    set paths [valence_fifo_payload::check_paths $scope $budget $starts $ends]
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
