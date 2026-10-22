# Independent Tcl query/session contract tests. These model query responses;
# they do not run Vivado, prove timing, or qualify native performance.
# Usage: tclsh test_collect_session.tcl
set here [file dirname [file normalize [info script]]]
source [file join $here common_cdc.tcl]
source [file join $here exact_object_cache.tcl]

set checks 0
set failures {}
proc assert {condition why} {
    if {![uplevel 1 [list expr $condition]]} {error $why}
}
proc equal {actual expected why} {
    if {$actual ne $expected} {error "$why\nexpected: $expected\nactual:   $actual"}
}
proc test {name body} {
    incr ::checks
    if {[catch {uplevel 1 $body} result options]} {
        lappend ::failures $name
        puts stderr "COLLECT_SESSION_FAIL $name: $result"
    } else {puts "COLLECT_SESSION_CASE_PASS $name"}
}

# The oracle knows only the graph and the requested native arguments, never the
# candidate's cache or expected call count. Delay is real wall-clock waiting.
namespace eval mock {
    variable props {}; variable objects {}; variable owner {}; variable netpins {}
    variable pinnets {}; variable clocks {}; variable cones {}; variable calls {}
    variable delay 0; variable fail {}; variable malformed {}; variable mutations {}
    variable aliasKind cell; variable responses {}
}
proc mock::reset {} {
    foreach name {props objects owner netpins pinnets clocks cones calls fail malformed mutations responses} {
        variable $name; set $name {}
    }
    variable delay 0; variable aliasKind cell
}
proc mock::record {command args} {
    variable calls; variable delay; variable fail
    lappend calls [list $command {*}$args]
    if {$delay} {after $delay}
    set key [list $command {*}$args]
    if {[dict exists $fail $key] && [dict get $fail $key]>0} {
        dict incr fail $key -1
        return -code error -errorcode [list MOCK_NATIVE $command] "MOCK_NATIVE transient $command"
    }
}
proc mock::count {command} {
    variable calls; set n 0
    foreach call $calls {if {[lindex $call 0] eq $command} {incr n}}
    return $n
}
proc mock::option {args name {default {}}} {
    set i [lsearch -exact $args $name]
    if {$i<0} {return $default}
    return [lindex $args [expr {$i+1}]]
}
proc mock::add {name kind values} {
    variable objects; variable props
    dict lappend objects $kind $name
    dict set props $name [dict merge [dict create NAME $name CLASS $kind] $values]
    return $name
}
proc mock::cell {name ref} {
    return [add $name cell [dict create REF_NAME $ref IS_PRIMITIVE TRUE INIT 1'b0 ASYNC_REG TRUE]]
}
proc mock::pin {name cell direction {ref {}} {leaf 1}} {
    variable owner
    if {$ref eq {}} {set ref [file tail $name]}
    dict set owner $name $cell
    return [add $name pin [dict create DIRECTION $direction REF_PIN_NAME $ref IS_LEAF $leaf IS_INVERTED FALSE]]
}
proc mock::net {name type pins} {
    variable netpins; variable pinnets
    add $name net [dict create TYPE $type]
    dict set netpins $name $pins
    foreach pin $pins {dict lappend pinnets $pin $name}
}
proc mock::ff {name clock} {
    variable clocks
    cell $name FDRE
    foreach p {C D CE Q} {pin $name/$p $name [expr {$p eq {Q} ? {OUT} : {IN}}]}
    dict set clocks $name/C [list $clock]
}
proc mock::fixture {} {
    reset
    variable clocks; variable cones
    foreach {name period} {src 7.5 dst 20.0 rogue 3.0} {add $name clock [dict create PERIOD $period]}
    set h top/fifo
    cell $h HeldResponse
    foreach {p clock} {sourceClock src destinationClock dst} {
        pin $h/$p $h IN $p 0
        dict set clocks $h/$p [list $clock]
    }
    for {set i 0} {$i<4} {incr i} {
        set address [format {%s/storage_ext/_R0_addr_d0_reg[%d]} $h $i]
        ff $address dst
        set input [format {%s/storage_ext/R0_addr[%d]} $h $i]
        pin $input $h IN {} 0
        net address:$i SIGNAL [list $address/D $input]
        ff [format {%s/heldAddress_reg[%d]} $h $i] dst
    }
    ff $h/pending_reg dst
    foreach {name ref port leaf} {ramA RAMD32 CLK TRUE ramB RAMS64E WCLK true} {
        set c $h/storage_ext/$name
        cell $c $ref; pin $c/$port $c IN $port $leaf
        dict set clocks $c/$port src
    }
    ff $h/controlA dst; ff $h/controlB dst
    set a $h/storage_ext/ramA/CLK; set b $h/storage_ext/ramB/WCLK
    for {set i 0} {$i<3} {incr i} {
        set c [format {%s/output_0_reg[%d]} $h $i]
        set bit [format {%s/destination_bits[%d]} $h $i]
        ff $c dst; pin $bit $h OUT {} 0
        net output:$i SIGNAL [list $bit $c/Q]
        net data:$i SIGNAL [list $c/D]
        switch $i {
            0 {dict set cones $c/D [list $a $h/controlA/C]}
            1 {dict set cones $c/D [list $b $h/controlB/C]}
            2 {dict set cones $c/D [list $a $b $h/controlA/C $h/controlB/C]}
        }
    }
    # Literal and unconnected output bits must remain separate scope metadata.
    set bit [format {%s/destination_bits[3]} $h]; pin $bit $h OUT {} 0
    net literal:3 GROUND [list $bit]
    pin [format {%s/destination_bits[4]} $h] $h OUT {} 0
    return $h
}
proc mock::expected_scope {} {
    set h top/fifo; set a $h/storage_ext/ramA/CLK; set b $h/storage_ext/ramB/WCLK
    set ends {}; set by {}; set ordinary {}
    for {set i 0} {$i<3} {incr i} {
        set end [format {%s/output_0_reg[%d]/D} $h $i]; lappend ends $end
        switch $i {
            0 {dict set by $end [list $a]; dict set ordinary $end [list $h/controlA/C]}
            1 {dict set by $end [list $b]; dict set ordinary $end [list $h/controlB/C]}
            2 {dict set by $end [list $a $b]; dict set ordinary $end [list $h/controlA/C $h/controlB/C]}
        }
    }
    return [dict create label $h/payload starts [list $a $b] ends $ends second {} budget 7.5 skew 1 by_end $by ordinary_by_end $ordinary constant_bits 3 unused_bits 4 local_constants {}]
}
proc mock::get_property {args} {
    record get_property {*}$args
    variable props; variable malformed; variable aliasKind
    # Model accepted options too; the cache must preserve unsupported signatures.
    if {[lindex $args 0] eq {-quiet}} {set args [lrange $args 1 end]}
    if {[llength $args]!=2} {error {MOCK_PROPERTY invalid arguments}}
    lassign $args key items
    set out {}
    foreach item $items {
        if {$item eq {shared}} {
            switch $key {
                NAME {lappend out shared}
                CLASS {lappend out $aliasKind}
                REF_NAME {lappend out [expr {$aliasKind eq {cell} ? {FDRE} : {PIN_REF}}]}
                default {lappend out $aliasKind:$key}
            }
        } elseif {![dict exists $props $item]} {
            error "MOCK_PROPERTY missing object $item"
        } elseif {[dict exists $props $item $key]} {lappend out [dict get $props $item $key]
        } else {lappend out {}}
    }
    set signature [list $key $items]
    if {[dict exists $malformed $signature]} {
        set mode [dict get $malformed $signature]; dict unset malformed $signature
        switch $mode {
            truncated {return [lrange $out 0 end-1]}
            missing {return {}}
            extra {return [concat $out EXTRA]}
        }
    }
    if {[llength $out]==1} {return [lindex $out 0]}
    return $out
}
proc mock::get_objects {kind args} {
    record get_$kind {*}$args
    variable objects; variable props; variable owner; variable netpins; variable pinnets; variable aliasKind
    set singular [string range $kind 0 end-1]
    if {[lindex $args end] eq {shared}} {set aliasKind $singular; return shared}
    set out {}
    if {[lsearch -exact $args -of_objects]>=0} {
        foreach item [option $args -of_objects] {
            switch $kind {
                cells {if {[dict exists $owner $item]} {lappend out [dict get $owner $item]}}
                nets {if {[dict exists $pinnets $item]} {lappend out {*}[dict get $pinnets $item]}}
                pins {
                    if {[dict exists $netpins $item]} {lappend out {*}[dict get $netpins $item]
                    } else {dict for {pin cell} $owner {if {$cell eq $item} {lappend out $pin}}}
                }
            }
        }
        set out [lsort -unique $out]
    } else {
        set patterns [lindex $args end]
        if {[lsearch -exact $args -regexp]>=0 && [string index $patterns 0] eq {^}} {set patterns [list $patterns]}
        if {![dict exists $objects $singular]} {return {}}
        foreach item [dict get $objects $singular] {
            foreach pattern $patterns {
                if {[lsearch -exact $args -regexp]>=0} {set match [regexp -- $pattern $item]
                } else {set match [string match $pattern $item]}
                if {$match} {lappend out $item; break}
            }
        }
    }
    set filter [option $args -filter]
    set filtered {}
    foreach item $out {
        if {[lsearch -exact $args -leaf]>=0 && [dict get $props $item IS_LEAF] ni {1 TRUE true}} {continue}
        switch $filter {
            {} {set keep 1}
            {DIRECTION == OUT} {set keep [expr {[dict get $props $item DIRECTION] eq {OUT}}]}
            {DIRECTION == IN} {set keep [expr {[dict get $props $item DIRECTION] eq {IN}}]}
            {REF_PIN_NAME =~ destination_bits*} {set keep [string match destination_bits* [dict get $props $item REF_PIN_NAME]]}
            default {error "MOCK_QUERY unsupported filter $filter"}
        }
        if {$keep} {lappend filtered $item}
    }
    return $filtered
}
proc mock::get_clocks {args} {
    record get_clocks {*}$args
    variable clocks; variable props; variable responses
    set signature [list get_clocks {*}$args]
    if {[dict exists $responses $signature]} {return [dict get $responses $signature]}
    if {[lsearch -exact $args -of_objects]>=0} {
        set out {}
        foreach pin [option $args -of_objects] {
            if {[dict exists $clocks $pin]} {lappend out {*}[dict get $clocks $pin]}
        }
        return $out
    }
    set name [lindex $args end]
    if {[dict exists $props $name] && [dict get $props $name CLASS] eq {clock}} {return [list $name]}
    return {}
}
proc mock::cone {command args} {
    record $command {*}$args
    variable cones; variable responses
    set signature [list $command {*}$args]
    if {[dict exists $responses $signature]} {return [dict get $responses $signature]}
    set endpoint [lindex [option $args -to] 0]
    if {[dict exists $cones $endpoint]} {return [dict get $cones $endpoint]}
    return {}
}
proc get_property {args} {return [mock::get_property {*}$args]}
foreach kind {cells pins nets} {
    proc ::get_$kind {args} [format {return [mock::get_objects %s {*}$args]} $kind]
}
proc get_clocks {args} {return [mock::get_clocks {*}$args]}
foreach command {all_fanin all_fanout} {
    proc ::$command {args} [format {return [mock::cone %s {*}$args]} $command]
}
foreach command {open_checkpoint close_design close_project read_checkpoint link_design synth_design opt_design place_design phys_opt_design route_design read_verilog read_edif read_xdc read_ip create_cell create_net create_port connect_net disconnect_net remove_cell remove_net remove_port set_property reset_property create_clock create_generated_clock delete_clocks set_clock_groups set_clock_uncertainty set_clock_latency set_clock_transition set_input_delay set_output_delay set_max_delay set_min_delay set_false_path set_multicycle_path set_bus_skew set_case_analysis set_disable_timing reset_timing update_timing open_run open_design update_design} {
    proc ::$command {args} [format {lappend ::mock::mutations [list %s {*}$args]; return MUTATED} $command]
}
proc metrics_count {command} {
    set key ${command}.calls
    if {![dict exists $::common_collect_session::last api $key]} {return 0}
    return [dict get $::common_collect_session::last api $key]
}
proc clean_session {} {
    equal $::common_collect_session::active 0 {session remained active}
    foreach name {properties kinds ambiguous queries guarded} {
        equal [set ::common_collect_session::$name] {} "session retained $name"
    }
    foreach command {set_property create_clock opt_design open_run update_design} {
        foreach row [trace info execution ::$command] {
            assert {[lindex $row 1] ne {::common_collect_session::forbid}} "mutation trace leaked on $command"
        }
    }
}

set nativeBodies {}
foreach command {get_property get_cells get_pins get_nets get_clocks all_fanin all_fanout} {
    dict set nativeBodies $command [info body ::$command]
}

test adapters_are_namespace_local {
    mock::fixture
    foreach ns {common_cdc common_exact_cache common_zero} {
        foreach command {get_property get_cells get_pins get_nets get_clocks all_fanin all_fanout} {
            assert {[llength [info commands ::${ns}::$command]]==1} "missing adapter $ns $command"
        }
    }
    common_collect_session::run {
        foreach ns {common_cdc common_exact_cache common_zero} {
            equal [${ns}::get_property NAME src] src {adapter returned wrong native property}
        }
        # Explicit global invocation must still go native, not be renamed.
        equal [::get_property NAME src] src {global API changed}
    }
    equal [mock::count get_property] 2 {namespace adapters did not share one property cache}
    clean_session
}

test properties_bulk_order_duplicates_and_prefetch {
    mock::fixture; set ::common_collect_session::enabled 1
    common_collect_session::run {
        equal [common_cdc::get_property NAME {dst src dst rogue}] {dst src dst rogue} {bulk order or duplicates lost}
        equal [common_zero::get_property NAME {rogue dst src src}] {rogue dst src src} {reordered lookup lost caller order}
        equal [common_exact_cache::get_property PERIOD {rogue dst src dst}] {3.0 20.0 7.5 20.0} {bulk property values misassociated}
        common_cdc::get_cells -quiet -hierarchical -regexp {^top/fifo/controlA$}
        set before [mock::count get_property]
        equal [common_exact_cache::get_property REF_NAME top/fifo/controlA] FDRE {prefetched reference missing}
        equal [common_zero::get_property CLASS top/fifo/controlA] cell {prefetched class missing}
        equal [common_cdc::get_property NAME top/fifo/controlA] top/fifo/controlA {prefetched name missing}
        equal [mock::count get_property] [expr {$before+1}] {NAME/REF_NAME were queried again or CLASS validation was omitted}
    }
    equal [mock::count get_property] 6 {bulk missing values not batched or CLASS skipped}
    clean_session
}

test singleton_empty_and_list_shaped_property_values {
    mock::fixture
    dict set ::mock::props src INIT {}
    dict set ::mock::props src NAME {name with spaces}
    dict set ::mock::props dst INIT {two scalar words}
    common_collect_session::run {
        equal [common_cdc::get_property INIT src] {} {empty native scalar was rejected}
        equal [common_cdc::get_property INIT src] {} {cached empty scalar changed}
        equal [common_cdc::get_property NAME src] {name with spaces} {list-shaped scalar was split}
        equal [common_cdc::get_property NAME src] {name with spaces} {cached list-shaped scalar changed}
        equal [common_cdc::get_property INIT {dst src dst}] {{two scalar words} {} {two scalar words}} {singleton fill corrupted a later bulk result}
    }
    equal [mock::count get_property] 3 {empty/list-shaped values were not cached as one value}
}

test names_preserve_singleton_and_bulk_scalar_boundaries {
    mock::fixture
    dict set ::mock::props src NAME {name with spaces}
    dict set ::mock::props dst NAME {another name}
    set ::common_collect_session::enabled 0
    set baseline [common_collect_session::run {
        list [common_cdc::names src] [common_cdc::names {src dst src}]
    }]
    set ::common_collect_session::enabled 1
    set cached [common_collect_session::run {
        list [common_cdc::names src] [common_cdc::names {src dst src}]
    }]
    equal $cached $baseline {bulk names path split a singleton scalar or lost distinct names}
    equal [lindex $cached 0] {{name with spaces}} {singleton name boundary not preserved}
    equal [lindex $cached 1] {{another name} {name with spaces}} {bulk name boundaries not preserved}
}

test baseline_passthrough_and_native_metrics {
    mock::fixture; set ::common_collect_session::enabled 0
    common_collect_session::run {
        foreach ns {common_cdc common_exact_cache common_zero} {
            equal [${ns}::get_property NAME {dst src dst}] {dst src dst} {baseline bulk semantics changed}
            equal [${ns}::get_clocks -quiet -of_objects top/fifo/sourceClock] src {baseline clocks changed}
        }
    }
    equal [mock::count get_property] 3 {baseline unexpectedly reused properties}
    equal [metrics_count get_property] 3 {baseline property metric wrong}
    equal [metrics_count get_clocks] 3 {baseline clock metric wrong}
    set ::common_collect_session::enabled 1
    clean_session
}

test signatures_preserve_options_modes_and_endpoint_identity {
    mock::fixture
    set p0 {top/fifo/output_0_reg[0]/D}; set p1 {top/fifo/output_0_reg[1]/D}
    set q0 [list -flat -startpoints_only -to $p0 -trace_arcs all]
    set q1 [list -flat -startpoints_only -to $p0 -trace_arcs enabled]
    set q2 [list -flat -startpoints_only -to $p1 -trace_arcs all]
    set q3 [list -flat -startpoints_only -to $p0 -trace_arcs ALL]
    foreach args [list $q0 $q1 $q2 $q3] {
        dict set ::mock::responses [list all_fanin {*}$args] [list top/fifo/controlA/C]
    }
    common_collect_session::run {
        foreach args [list $q0 $q1 $q2 $q3] {
            foreach ns {common_cdc common_zero} {
                equal [${ns}::all_fanin {*}$args] top/fifo/controlA/C {mode-specific fanin result changed}
            }
        }
        foreach args {{-quiet src} {src} {-quiet -of_objects top/fifo/sourceClock} {-of_objects top/fifo/sourceClock -quiet}} {
            common_cdc::get_clocks {*}$args; common_zero::get_clocks {*}$args
        }
    }
    equal [mock::count all_fanin] 4 {fanin key dropped endpoint, mode, case, or other options}
    equal [mock::count get_clocks] 4 {clock key dropped options or argument order}
    equal [dict get $::common_collect_session::last api all_fanin.hits] 4 {fanin hit metric wrong}
    equal [dict get $::common_collect_session::last api get_clocks.hits] 4 {clock hit metric wrong}
}

test no_cache_for_timing_or_unsupported_property_signatures {
    mock::fixture
    dict set ::mock::props src SLACK 0.2
    common_collect_session::run {
        equal [common_cdc::get_property SLACK src] 0.2 {timing property changed}
        dict set ::mock::props src SLACK -0.1
        equal [common_cdc::get_property SLACK src] -0.1 {timing property was cached}
        common_cdc::get_property -quiet NAME src; common_cdc::get_property -quiet NAME src
        common_cdc::get_property NAME {}; common_cdc::get_property NAME {}
        common_cdc::all_fanout -from top/fifo/controlA/Q
        common_cdc::all_fanout -from top/fifo/controlA/Q
    }
    equal [mock::count get_property] 6 {unsupported property signature was normalized or cached}
    equal [mock::count all_fanout] 2 {all_fanout unexpectedly cached}
}

foreach malformed {truncated missing extra} {
    test malformed_bulk_$malformed {
        mock::fixture
        dict set ::mock::malformed [list PERIOD {src dst}] $malformed
        set outerCode [catch {common_collect_session::run {
            set code [catch {common_cdc::get_property PERIOD {src dst}} message]
            assert {$code==1 && [string match {COMMON_COLLECT malformed bulk property PERIOD:*} $message]} {malformed native bulk was accepted}
            equal [common_cdc::get_property PERIOD {dst src dst}] {20.0 7.5 20.0} {partial malformed response polluted cache}
        }} outerMessage]
        assert {$outerCode==1 && [string match {*malformed bulk property*} $outerMessage]} {caught malformed response permitted completed collection}
        equal [mock::count get_property] 2 {malformed property response was cached}
        clean_session
    }
}

test errors_are_not_cached {
    mock::fixture
    dict set ::mock::fail [list get_property PERIOD {src dst}] 1
    dict set ::mock::fail [list get_clocks -quiet src] 1
    set args [list -flat -startpoints_only -to {top/fifo/output_0_reg[0]/D}]
    dict set ::mock::fail [list all_fanin {*}$args] 1
    common_collect_session::run {
        foreach script [list {common_cdc::get_property PERIOD {src dst}} {common_cdc::get_clocks -quiet src} [list common_cdc::all_fanin {*}$args]] {
            set code [catch {eval $script} message options]
            assert {$code==1 && [lindex [dict get $options -errorcode] 0] eq {MOCK_NATIVE}} {native error/options not preserved}
            eval $script; eval $script
        }
    }
    equal [mock::count get_clocks] 2 {clock failure cached or later success not cached}
    equal [mock::count all_fanin] 2 {fanin failure cached or later success not cached}
    equal [metrics_count get_property] [mock::count get_property] {failed native property call omitted from metrics}
    equal [metrics_count get_clocks] 2 {failed clock call omitted from metrics}
}

test mixed_classes_and_alias_property_safety {
    mock::fixture
    mock::add input_port port [dict create DIRECTION IN]
    dict set ::mock::responses [list all_fanin -to top/fifo/controlA/D] {input_port top/fifo/controlA/C}
    common_collect_session::run {
        equal [common_cdc::all_fanin -to top/fifo/controlA/D] {input_port top/fifo/controlA/C} {mixed cone altered}
        equal [common_cdc::get_property CLASS {top/fifo/controlA/C input_port top/fifo/controlA/C}] {pin port pin} {mixed cone classes assumed pin}
        common_cdc::get_cells shared
        equal [common_cdc::get_property CLASS shared] cell {initial alias class wrong}
        common_cdc::get_pins shared
        equal [common_cdc::get_property CLASS shared] pin {cell/pin string alias reused stale class}
        common_cdc::get_cells shared
        equal [common_cdc::get_property REF_NAME shared] FDRE {ambiguous alias failed native fallback}
    }
    clean_session
}

test alias_query_identity_safety {
    mock::fixture
    common_collect_session::run {
        common_cdc::get_pins shared
        dict set ::mock::clocks shared src
        equal [common_cdc::get_clocks -of_objects shared] src {initial pin clock wrong}
        common_cdc::get_nets shared
        # Distinct typed native objects may print the same name. No design
        # mutation: this switch models the second object's native response.
        dict set ::mock::clocks shared dst
        equal [common_cdc::get_clocks -of_objects shared] dst {cross-class alias reused a clock result}
    }
}

test alias_fanin_target_class_safety {
    mock::fixture
    common_collect_session::run {
        common_cdc::get_pins shared
        dict set ::mock::cones shared top/fifo/controlA/C
        equal [common_cdc::all_fanin -to shared] top/fifo/controlA/C {initial pin cone wrong}
        common_cdc::get_nets shared
        dict set ::mock::cones shared top/fifo/controlB/C
        equal [common_cdc::all_fanin -to shared] top/fifo/controlB/C {cross-class alias reused a fanin result}
    }
    equal [mock::count all_fanin] 2 {alias target was not independently queried}
}

test empty_queries_are_valid_cached_results {
    mock::fixture
    set target top/fifo/controlA/D
    common_collect_session::run {
        equal [common_cdc::get_clocks -of_objects $target] {} {empty clocks changed}
        equal [common_zero::get_clocks -of_objects $target] {} {cached empty clocks changed}
        equal [common_cdc::all_fanin -to $target] {} {empty fanin changed}
        equal [common_zero::all_fanin -to $target] {} {cached empty fanin changed}
    }
    equal [mock::count get_clocks] 1 {valid empty clock result was not cached}
    equal [mock::count all_fanin] 1 {valid empty cone result was not cached}
}

test cone_class_error_does_not_cache_query {
    mock::fixture
    set target top/fifo/controlA/D
    dict set ::mock::cones $target {top/fifo/controlA/C top/fifo/controlB/C}
    dict set ::mock::fail [list get_property CLASS {top/fifo/controlA/C top/fifo/controlB/C}] 1
    common_collect_session::run {
        set code [catch {common_cdc::all_fanin -to $target} message]
        assert {$code==1 && [string match {MOCK_NATIVE transient get_property} $message]} {cone class error was lost}
        equal [common_cdc::all_fanin -to $target] {top/fifo/controlA/C top/fifo/controlB/C} {retry changed cone}
        common_cdc::all_fanin -to $target
    }
    equal [mock::count all_fanin] 2 {query was cached before returned classes validated}
}

foreach location {target result} {
    test malformed_cone_class_poison_$location {
        mock::fixture
        set target top/fifo/controlA/D
        if {$location eq {target}} {set target {top/fifo/controlA/D top/fifo/controlB/D}}
        set result {top/fifo/controlA/C top/fifo/controlB/C}
        dict set ::mock::cones [lindex $target 0] $result
        set items [expr {$location eq {target} ? $target : $result}]
        dict set ::mock::malformed [list CLASS $items] missing
        set code [catch {common_collect_session::run {
            catch {common_cdc::all_fanin -to $target} inner
            set scope apparently_complete
        }} message]
        assert {$code==1 && [string match {*malformed*} $message]} {malformed cone classes permitted collection completion}
        equal [dict get $::common_collect_session::last outcome] ERROR {malformed classes marked complete}
        clean_session
    }
}

test cross_lifecycle_clock_fanin_and_property_changes {
    mock::fixture
    set endpoint {top/fifo/output_0_reg[0]/D}
    set before [common_collect_session::run {
        list [common_cdc::get_property PERIOD src] [common_cdc::get_clocks -of_objects top/fifo/sourceClock] [common_cdc::all_fanin -to $endpoint]
    }]
    dict set ::mock::props src PERIOD 6.25
    dict set ::mock::clocks top/fifo/sourceClock rogue
    dict set ::mock::cones $endpoint top/fifo/controlB/C
    set after [common_collect_session::run {
        list [common_cdc::get_property PERIOD src] [common_cdc::get_clocks -of_objects top/fifo/sourceClock] [common_cdc::all_fanin -to $endpoint]
    }]
    equal $after {6.25 rogue top/fifo/controlB/C} {cross-lifecycle state was stale}
    assert {$before ne $after} {fixture mutation was ineffective}
    equal [metrics_count get_clocks] 1 {metrics accumulated across lifecycles}
    clean_session
}

test lifecycle_cleanup_and_caller_scope {
    mock::fixture
    set local only_in_caller
    equal [common_collect_session::run {set local}] only_in_caller {run lost caller scope}
    set code [catch {common_collect_session::run {common_cdc::get_property NAME src; error TEST_FAILURE}} message]
    assert {$code==1 && $message eq {TEST_FAILURE}} {run swallowed or rewrote script error}
    equal [dict get $::common_collect_session::last outcome] ERROR {failed lifecycle marked complete}
    clean_session
    set code [catch {common_collect_session::run {common_collect_session::run {set ignored 1}}} message]
    assert {$code==1 && [string match {*nested lifecycle*} $message]} {nested lifecycle accepted}
    clean_session
    equal [common_collect_session::run {set recovered 1}] 1 {error prevented a future lifecycle}
    clean_session
}

foreach command {set_property create_clock create_generated_clock connect_net opt_design update_timing open_checkpoint read_xdc open_run open_design update_design} {
    test mutation_guard_$command {
        mock::fixture
        set code [catch {common_collect_session::run [list ::$command mock_target]} message]
        assert {$code==1 && [string match {*mutation during read-only collect*} $message]} "$command was not rejected"
        equal $::mock::mutations {} "$command executed before rejection"
        equal [dict get $::common_collect_session::last outcome] ERROR {mutation marked complete}
        clean_session
    }
}

test caught_mutation_poison_cannot_publish_scope {
    mock::fixture
    set code [catch {common_collect_session::run {
        common_cdc::get_property NAME src
        catch {set_property INIT 1 top/fifo/controlA}
        set apparently_successful_scope [mock::expected_scope]
    }} message]
    assert {$code==1 && [string match {*mutation during read-only collect*} $message]} {caught mutation allowed a completed scope}
    equal $::mock::mutations {} {caught mutation executed}
    equal [dict get $::common_collect_session::last outcome] ERROR {caught mutation marked complete}
    clean_session
    equal [set_property INIT 1 top/fifo/controlA] MUTATED {guard remained installed outside session}
}

test disabled_mode_still_read_only {
    mock::fixture; set ::common_collect_session::enabled 0
    set code [catch {common_collect_session::run {catch {create_clock -name forbidden}; set scope ok}} message]
    set ::common_collect_session::enabled 1
    assert {$code==1 && [string match {*mutation during read-only collect*} $message]} {baseline session allowed mutation}
    equal $::mock::mutations {} {baseline mutation executed}
    clean_session
}

test repeated_source_preserves_enabled_and_active_source_poison {
    mock::fixture
    set ::common_collect_session::enabled 0
    source [file join $here common_collect_session.tcl]
    equal $::common_collect_session::enabled 0 {re-source reset explicit baseline mode}
    set ::common_collect_session::enabled 1
    set code [catch {common_collect_session::run {
        common_cdc::get_property NAME src
        catch {source [file join $here common_collect_session.tcl]} ignored
        set apparent_result done
    }} message]
    assert {$code==1 && [string match {*cannot re-source helper during active collect*} $message]} {active source erased lifecycle or escaped poisoning}
    clean_session
    equal [common_collect_session::run {common_cdc::get_property NAME src}] src {active source rejection broke later sessions}
}

test completed_failed_and_incomplete_phase_records {
    mock::fixture
    common_collect_session::run {
        common_collect_session::phase payload BEGIN root
        after 3
        common_collect_session::phase payload COMPLETE 3
        common_collect_session::phase audit BEGIN inspection
        common_collect_session::phase audit FAILED reason
        common_collect_session::phase pending BEGIN root
    }
    set phases [dict get $::common_collect_session::last phases]
    equal [llength $phases] 2 {phase end records missing}
    set complete [lindex $phases 0]; set failed [lindex $phases 1]
    equal [dict get $complete detail] root {original phase detail was lost}
    equal [dict get $complete final_detail] 3 {changed completion detail was lost}
    equal [dict get $complete outcome] COMPLETE {complete phase outcome wrong}
    assert {[dict get $complete us]>=2500} {phase did not measure real elapsed time}
    equal [dict get $failed outcome] FAILED {failed phase was marked complete}
    equal [dict get $failed final_detail] reason {failed phase detail was lost}
    equal [dict get $::common_collect_session::last incomplete_phases] pending {unfinished phase record was lost}
}

test real_elapsed_and_native_call_metrics {
    mock::fixture; set ::mock::delay 7
    common_collect_session::run {
        common_collect_session::phase metric_test BEGIN delayed
        common_cdc::get_property NAME {src dst}
        common_cdc::get_property NAME {dst src}
        common_cdc::get_clocks src
        common_cdc::get_clocks src
        common_collect_session::phase metric_test COMPLETE delayed
        common_collect_session::phase incomplete_test BEGIN pending
    }
    set ::mock::delay 0
    equal [metrics_count get_property] 1 {property metrics counted wrapper hits as native calls}
    equal [metrics_count get_clocks] 1 {clock metrics counted wrapper hits as native calls}
    assert {[dict get $::common_collect_session::last api get_property.us]>=6000} {property time did not include actual native delay}
    assert {[dict get $::common_collect_session::last api get_clocks.us]>=6000} {clock time did not include actual native delay}
    assert {[dict get $::common_collect_session::last elapsed_us]>=12000} {elapsed time is not measured wall time}
    set phase [lindex [dict get $::common_collect_session::last phases] 0]
    assert {[dict get $phase us]>=12000} {phase time did not include native work}
    equal [dict get $::common_collect_session::last incomplete_phases] incomplete_test {unfinished phase was hidden}
}

# The actual structural proof runs unchanged in both modes, with independently
# specified endpoint maps. The tests never replace the payload proof procedure.
proc run_payload {enabled} {
    set ::common_collect_session::enabled $enabled
    set ::mock::calls {}
    set code [catch {common_collect_session::run {
        set first [common_cdc::payload top/fifo]
        set second [common_cdc::payload top/fifo]
        equal $first $second {repeated proof changed in one session}
        set second
    }} result options]
    return [dict create code $code result $result calls $::mock::calls metrics $::common_collect_session::last options $options]
}

test payload_scope_all_fields_and_per_endpoint_equivalence {
    mock::fixture; set expected [mock::expected_scope]
    set off [run_payload 0]
    mock::fixture; set on [run_payload 1]
    equal [dict get $off code] 0 {baseline proof failed}
    equal [dict get $on code] 0 {cached proof failed}
    equal [dict get $off result] $expected {independent expected scope differs from baseline}
    equal [dict get $on result] $expected {cache changed a scope field or endpoint map}
    foreach run [list $off $on] {
        foreach command {get_property get_cells get_pins get_nets get_clocks all_fanin} {
            set actual 0
            foreach call [dict get $run calls] {if {[lindex $call 0] eq $command} {incr actual}}
            equal [dict get $run metrics api ${command}.calls] $actual "native metric differs from independent trace for $command"
        }
    }
    set offProperties [dict get $off metrics api get_property.calls]
    set onProperties [dict get $on metrics api get_property.calls]
    assert {$onProperties<$offProperties} {property cache did not reduce actual native calls}
    equal [dict get $off metrics api all_fanin.calls] 6 {baseline endpoint query count changed}
    equal [dict get $on metrics api all_fanin.calls] 3 {fanin was not reused per endpoint}
    equal [dict get $off metrics api get_clocks.calls] 30 {baseline clock query count changed}
    equal [dict get $on metrics api get_clocks.calls] 15 {clock queries were not reused exactly once per identity}
    foreach command {get_cells get_pins get_nets} {
        set offArgs {}; set onArgs {}
        foreach call [dict get $off calls] {if {[lindex $call 0] eq $command} {lappend offArgs [lrange $call 1 end]}}
        foreach call [dict get $on calls] {if {[lindex $call 0] eq $command} {lappend onArgs [lrange $call 1 end]}}
        equal $onArgs $offArgs "uncached $command queries or their arguments changed"
    }
    set endpointQueries {}
    foreach call [dict get $on calls] {
        if {[lindex $call 0] eq {all_fanin}} {
            set args [lrange $call 1 end]
            equal [llength [mock::option $args -to]] 1 {proof queried a union of endpoints}
            lappend endpointQueries [lindex [mock::option $args -to] 0]
        }
    }
    equal [lsort $endpointQueries] [dict get $expected ends] {endpoint query set lost specificity}
    clean_session
}

foreach {scenario mutation expectedError} {
    bad_ram_reference {dict set ::mock::props top/fifo/storage_ext/ramA REF_NAME LUT6} {*unsupported mapped RAM/launch*}
    wrong_ram_clock {dict set ::mock::clocks top/fifo/storage_ext/ramA/CLK dst} {*unreviewed RAM launch*}
    nonleaf_ram_pin {dict set ::mock::props top/fifo/storage_ext/ramA/CLK IS_LEAF FALSE} {*unreviewed RAM launch*}
    port_in_cone {dict set ::mock::props top/fifo/storage_ext/ramA/CLK CLASS port} {*non-cell launch*}
    wrong_local_clock {dict set ::mock::clocks top/fifo/controlA/C rogue} {*asynchronous FF/data bypass*}
    data_pin_bypass {dict set ::mock::cones {top/fifo/output_0_reg[0]/D} {top/fifo/controlA/Q}} {*asynchronous FF/data bypass*}
    empty_clock {dict set ::mock::clocks top/fifo/sourceClock {}} {*missing/ambiguous clock*}
    ambiguous_clock {dict set ::mock::clocks top/fifo/sourceClock {src rogue}} {*missing/ambiguous clock*}
    bad_period {dict set ::mock::props src PERIOD 0} {*invalid clock period*}
    missing_bank_cell {dict set ::mock::objects cell [lsearch -all -inline -not -exact [dict get $::mock::objects cell] {top/fifo/storage_ext/_R0_addr_d0_reg[3]}]} {*bank shape changed*}
} {
    test payload_negative_equivalence_$scenario {
        mock::fixture; eval $mutation; set off [run_payload 0]
        mock::fixture; eval $mutation; set on [run_payload 1]
        assert {[dict get $off code]==1 && [dict get $on code]==1} {corrupt graph was accepted}
        equal [dict get $on result] [dict get $off result] {cache changed the checker diagnostic}
        assert {[string match $expectedError [dict get $on result]]} {failure did not come from the expected proof check}
        equal [dict get $on metrics outcome] ERROR {failed proof marked complete}
        clean_session
    }
}

test truth_value_case_is_not_normalized {
    foreach {invert leaf} {0 1 FALSE TRUE false true} {
        mock::fixture
        dict set ::mock::props {top/fifo/output_0_reg[0]/C} IS_INVERTED $invert
        dict set ::mock::props top/fifo/storage_ext/ramA/CLK IS_LEAF $leaf
        set off [run_payload 0]
        mock::fixture
        dict set ::mock::props {top/fifo/output_0_reg[0]/C} IS_INVERTED $invert
        dict set ::mock::props top/fifo/storage_ext/ramA/CLK IS_LEAF $leaf
        set on [run_payload 1]
        equal [dict get $off code] 0 {baseline rejected a documented truth spelling}
        equal [dict get $on result] [dict get $off result] {case spelling changed proof outcome}
    }
    # Mixed-case text is not silently canonicalized into a permitted truth.
    mock::fixture; dict set ::mock::props top/fifo/storage_ext/ramA/CLK IS_LEAF True
    set off [run_payload 0]
    mock::fixture; dict set ::mock::props top/fifo/storage_ext/ramA/CLK IS_LEAF True
    set on [run_payload 1]
    assert {[dict get $off code]==1 && [dict get $on code]==1} {mixed-case unsupported value was normalized}
    equal [dict get $on result] [dict get $off result] {mixed-case rejection changed}
}

test bulk_cell_name_swap_poison {
    mock::fixture
    dict set ::mock::props top/fifo/controlA NAME top/fifo/controlB
    dict set ::mock::props top/fifo/controlB NAME top/fifo/controlA
    set code [catch {common_collect_session::run {
        set innerCode [catch {common_cdc::get_cells -quiet -hierarchical -regexp {^top/fifo/control[A-B]$}} inner]
        assert {$innerCode==1 && $inner eq {COMMON_COLLECT bulk cell NAME order/identity mismatch}} {swapped native bulk names were not rejected at collection}
        set apparent_scope complete
    }} message]
    assert {$code==1 && $message eq {COMMON_COLLECT bulk cell NAME order/identity mismatch}} {caught swapped names permitted collection completion}
    equal [dict get $::common_collect_session::last outcome] ERROR {swapped names marked complete}
    equal [mock::count get_cells] 1 {swapped-name fixture did not query one native bulk collection}
    clean_session
}

test bulk_cell_noncell_class_poison {
    mock::fixture
    dict set ::mock::props top/fifo/controlB CLASS pin
    set code [catch {common_collect_session::run {
        set innerCode [catch {common_cdc::get_cells -quiet -hierarchical -regexp {^top/fifo/control[A-B]$}} inner]
        assert {$innerCode==1 && $inner eq {COMMON_COLLECT non-cell in native get_cells collection}} {mixed native bulk cell classes were not rejected}
        set apparent_scope complete
    }} message]
    assert {$code==1 && $message eq {COMMON_COLLECT non-cell in native get_cells collection}} {caught non-cell class permitted collection completion}
    equal [dict get $::common_collect_session::last outcome] ERROR {non-cell class marked complete}
    equal [mock::count get_cells] 1 {non-cell fixture did not query one native bulk collection}
    clean_session
}

test native_commands_not_renamed_or_replaced {
    dict for {command body} $nativeBodies {equal [info body ::$command] $body "global $command was replaced"}
    clean_session
}
set ::common_collect_session::enabled 1
if {[llength $failures]} {
    puts stderr [list COLLECT_SESSION_TESTS_FAILED total $checks failures $failures MOCK_ONLY_NOT_NATIVE_QUALIFIED]
    exit 1
}
puts [list COLLECT_SESSION_TESTS_PASS cases $checks per_endpoint_maps_preserved 1 scope_fields_unchanged 1 native_metrics_checked 1 MOCK_ONLY_NOT_NATIVE_QUALIFIED]
