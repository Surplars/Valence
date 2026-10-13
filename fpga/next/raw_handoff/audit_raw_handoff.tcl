# Fresh mapped checker. Host-mock execution is separate from Vivado qualification.
# Run only in a fresh Vivado process, against a newly reviewed contract.
# No set_property, timing exceptions, netlist edits, placement or implementation.
namespace eval raw_handoff { variable serial 0; variable directory [file dirname [info script]] }

proc raw_handoff::need {ok message} { if {!$ok} { error "RAW_HANDOFF: $message" } }
proc raw_handoff::quote {s} {
    regsub -all {[][\\.^$*+?()|{}]} $s {\\&} s
    return $s
}
# Names are plain persistent data. Every consuming boundary receives a newly
# queried typed collection. Regex quoting is necessary for bus names with [].
proc raw_handoff::objects {kind names} {
    need [expr {[llength $names] > 0}] "empty $kind query"
    need [expr {[llength [lsort -unique $names]] == [llength $names]}] "duplicate $kind names"
    set patterns [lmap n $names {quote $n}]
    set re "^([join $patterns |])\$"
    set observed [get_property NAME [query $kind $re]]
    need [expr {[llength $observed] == [llength $names] && [lsort $observed] eq [lsort $names]}] "missing/ambiguous/inexact $kind: $names"
    return [query $kind $re]
}
proc raw_handoff::query {kind re} {
    switch -- $kind {
        pin {return [get_pins -quiet -hierarchical -regexp $re]}
        cell {return [get_cells -quiet -hierarchical -regexp $re]}
        net {return [get_nets -quiet -hierarchical -regexp $re]}
        clock {return [get_clocks -quiet -regexp $re]}
        default {error "unsupported object kind $kind"}
    }
}
proc raw_handoff::prop {kind name key} {return [get_property $key [objects $kind [list $name]]]}
# Counting a Vivado collection can change its Tcl representation. Repeat the
# query before NAME consumption; only the resulting names enter Tcl lists.
proc raw_handoff::names {query_script} {
    if {![llength [uplevel 1 $query_script]]} {return {}}
    return [lsort [get_property NAME [uplevel 1 $query_script]]]
}
proc raw_handoff::segments {pin} {
    set result [names {get_nets -quiet -segments -of_objects [objects pin [list $pin]]}]
    need [expr {[llength $result] > 0}] "disconnected pin: $pin"
    return $result
}
proc raw_handoff::net {pin} {return [lindex [segments $pin] 0]}
proc raw_handoff::same {a b} {need [expr {[segments $a] eq [segments $b]}] "different nets: $a / $b"}
proc raw_handoff::driver {pin} {
    set ns [segments $pin]
    set ps [names {get_pins -quiet -leaf -of_objects [objects net $ns] -filter {DIRECTION == OUT}}]
    need [expr {[llength $ps] == 1}] "not one direct leaf driver: $pin"
    return [lindex $ps 0]
}
proc raw_handoff::owner {pin} {
    set cs [names {get_cells -quiet -of_objects [objects pin [list $pin]]}]
    need [expr {[llength $cs] == 1}] "not one owner: $pin"
    return [lindex $cs 0]
}
proc raw_handoff::bit {value expected} {
    if {$expected} {return [expr {[string tolower $value] in {1 true 1'b1 1'h1}}]}
    return [expr {[string tolower $value] in {0 false 1'b0 1'h0}}]
}
proc raw_handoff::constant {pin expected} {
    return [expr {[prop net [net $pin] TYPE] eq ($expected ? "POWER" : "GROUND")}]
}
proc raw_handoff::clock {pin} {
    set ns [names {get_clocks -quiet -of_objects [objects pin [list $pin]]}]
    need [expr {[llength $ns] == 1}] "ambiguous/unclocked pin: $pin"
    return [lindex $ns 0]
}
proc raw_handoff::qcell {pin} {
    set q [driver $pin]
    need [expr {[prop pin $q REF_PIN_NAME] eq "Q"}] "not direct FF Q: $pin"
    return [owner $q]
}
# Deliberately separate from valence_mac::ff. Existing positive CDC rule stays.
proc raw_handoff::ff {cell falling clock_pin reset_pin} {
    need [expr {[prop cell $cell REF_NAME] eq "FDCE"}] "not FDCE: $cell"
    need [bit [prop cell $cell INIT] 0] "wrong INIT on $cell"
    need [bit [prop pin $cell/C IS_INVERTED] $falling] "wrong clock inversion on $cell"
    need [bit [prop pin $cell/CLR IS_INVERTED] 0] "wrong clear inversion on $cell"
    need [expr {![bit [prop cell $cell ASYNC_REG] 1]}] "datapath mislabeled ASYNC_REG: $cell"
    need [constant $cell/CE 1] "conditional handoff CE: $cell"
    same $cell/C $clock_pin
    same $cell/CLR $reset_pin
    need [expr {[clock $cell/C] eq [clock $clock_pin]}] "propagated clock mismatch: $cell"
}
# Bounded actual LUT truth evaluator; no eval/expr of contract-provided code.
# Hidden sequential inputs, unsupported primitives, cycles and >16 levels fail.
proc raw_handoff::value {pin assignment {seen {}}} {
    set n [net $pin]
    if {[dict exists $assignment $n]} {return [dict get $assignment $n]}
    if {[constant $pin 0]} {return 0}
    if {[constant $pin 1]} {return 1}
    need [expr {[llength $seen] < 16 && $n ni $seen}] "unbounded/cyclic cone at $pin"
    lappend seen $n
    set c [owner [driver $pin]]
    set ref [prop cell $c REF_NAME]
    if {$ref eq "INV"} {return [expr {1 - [value $c/I $assignment $seen]}]}
    if {$ref in {MUXF7 MUXF8 MUXF9}} {
        set s [value $c/S $assignment $seen]
        return [value $c/I$s $assignment $seen]
    }
    need [regexp {^LUT([1-6])$} $ref -> width] "unreviewed cone primitive $c ($ref)"
    set init [prop cell $c INIT]
    need [regexp {^([0-9]+)'([hHbB])([0-9a-fA-F]+)$} $init -> bits radix digits] "unsupported INIT $c"
    need [expr {$bits == (1 << $width)}] "wrong INIT width $c"
    if {[string tolower $radix] eq "h"} {set table [expr 0x$digits]} else {
        need [regexp {^[01]+$} $digits] "invalid binary INIT $c"
        set table [expr 0b$digits]
    }
    need [expr {$table < (1 << $bits)}] "oversized INIT $c"
    set index 0
    for {set i 0} {$i < $width} {incr i} {
        set index [expr {$index | ([value $c/I$i $assignment $seen] << $i)}]
    }
    return [expr {($table >> $index) & 1}]
}
proc raw_handoff::equation {output inputs kind} {
    set ns [lmap pin $inputs {net $pin}]
    need [expr {[llength [lsort -unique $ns]] == [llength $ns]}] "merged equation variables need review"
    set width [llength $inputs]
    need [expr {($kind eq "byte_step" && $width == 11) || ($kind eq "local_idle" && $width == 8)}] "wrong equation width"
    for {set v 0} {$v < (1 << $width)} {incr v} {
        set assignment {}; set i 0
        foreach n $ns {dict set assignment $n [expr {($v >> $i) & 1}]; incr i}
        # localIdle: drain & !busy & fifoIdle & statsIdle & !configValid &
        #            ingressEmpty & !managedValid & diagnosticsIdle.
        set expected [expr {$kind eq "byte_step" ? $v == 0 : $v == 173}]
        need [expr {[value $output $assignment] == $expected}] "wrong $kind equation vector=$v"
    }
}
proc raw_handoff::fanout {pin expected} {
    set got [names {all_fanout -flat -endpoints_only -from [objects pin [list $pin]]}]
    need [expr {$got eq [lsort $expected]}] "unreviewed/missing endpoint from $pin: $got"
    foreach end $expected {
        need [expr {[prop pin $end REF_PIN_NAME] in {D CE}}] "non-D/CE functional endpoint $end"
    }
}
proc raw_handoff::fanin {pin} {
    set starts [names {all_fanin -flat -startpoints_only -to [objects pin [list $pin]]}]
    need [expr {[llength $starts] > 0}] "empty source cone $pin"
    foreach q $starts {
        need [expr {[prop pin $q REF_PIN_NAME] eq "Q"}] "unreviewed non-Q source: $q"
        need [bit [prop cell [owner $q] IS_SEQUENTIAL] 1] "nonsequential source: $q"
    }
    return $starts
}
proc raw_handoff::timed {from to budget output label} {
    variable serial; incr serial
    # All supplied data/reset launch roles are verified Q pins. Vivado reports
    # sequential startpoints at C; query that explicit pin and compare to it.
    need [expr {[prop pin $from REF_PIN_NAME] eq "Q"}] "timing launch must be Q role"
    set launch [owner $from]/C
    foreach delay {min max} {
        # Never lindex, foreach, serialize, dict-store or reconstruct path objects.
        set paths [get_timing_paths -quiet -from [objects pin [list $launch]] -to [objects pin [list $to]] -delay_type $delay -max_paths 1 -nworst 1]
        set observed_start [get_property STARTPOINT_PIN $paths]
        set observed_end [get_property ENDPOINT_PIN $paths]
        set req [get_property REQUIREMENT $paths]
        set slack [get_property SLACK $paths]
        need [expr {[llength $paths] == 1}] "missing/cut $delay path $from -> $to"
        unset paths
        need [expr {$observed_start eq $launch && $observed_end eq $to}] "wrong timing pair"
        set numeric {^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$}
        need [expr {[regexp $numeric $req] && [regexp $numeric $slack]}] "nonfinite timing $label"
        need [expr {$delay ne "max" || ($req > 0 && $req <= $budget + 0.001)}] "relaxed max requirement $label"
        report_timing -from [objects pin [list $launch]] -to [objects pin [list $to]] -delay_type $delay -max_paths 1 -nworst 1 -path_type full_clock_expanded -input_pins -file [file join $output ${serial}_${delay}.rpt]
        puts [list RAW_HANDOFF_TIMING $serial $label $delay $from $to REQUIREMENT $req SLACK $slack]
        need [expr {$slack >= 0}] "negative $delay slack $label"
    }
}
proc raw_handoff::read_dict {path} {
    set f [open $path r]; try {set data [read $f]} finally {close $f}
    dict size $data
    return $data
}
proc raw_handoff::bind {contract_file c} {
    variable directory
    need [expr {[dict get $c schema] eq "raw-handoff-mapped-v1"}] "wrong contract version"
    set mode [dict get $c enabled]
    need [expr {$mode in {0 1}}] "explicit Boolean mode required"
    need [info exists ::valence_mac_session::config] "configure reviewed native/WSL Python route first"
    set config $::valence_mac_session::config
    set base [file dirname [file normalize $contract_file]]
    set binding [file join $base [dict get $c binding_file]]
    set dcp [file join $base [dict get $c checkpoint_file]]
    set paths [list [file join $directory verify_binding.py] $contract_file $binding $dcp]
    if {[dict get $config mode] eq "wsl"} {
        set prefix [list {*}[dict get $config command] -d [dict get $config distro] --]
        set converted {}
        foreach path $paths {
            set mapped [string trimright [::valence_mac_session::run_wsl [list {*}$prefix wslpath -u [file normalize $path]]] "\r\n"]
            need [expr {$mapped ne "" && [string index $mapped 0] eq "/" && ![regexp {[\r\n\x00]} $mapped]}] "invalid WSL path conversion"
            lappend converted $mapped
        }
        set result [::valence_mac_session::run_wsl [list {*}$prefix /usr/bin/python3 {*}$converted]]
    } elseif {[dict get $config mode] eq "native" && $::tcl_platform(platform) eq "unix"} {
        set result [exec {*}[dict get $config command] {*}$paths]
    } else {error "Unsupported Python route; use reviewed explicit session configuration"}
    set result [string trim $result]
    need [regexp {^([0-9a-f]{64}) ([01])$} $result -> digest actual_mode] "malformed admission result"
    need [expr {$actual_mode eq $mode}] "actualmode differs from reviewed role contract"
    return [list $dcp $digest]
}
proc raw_handoff::check_clocks {r} {
    set raw [dict get $r raw_clock]; set pad [dict get $r pad_clock]
    set div [q_or_buffer $raw BUFGCE_DIV O]; set pdiv [q_or_buffer $pad BUFGCE_DIV O]
    foreach {cell ratio} [list $div 4 $pdiv 2] {
        need [expr {[prop cell $cell BUFGCE_DIVIDE] == $ratio}] "original divider changed"
        need [constant $cell/CE 1] "divider CE changed"
    }
    same $div/I $pdiv/I; same $div/CLR $pdiv/CLR
    foreach {pin period fall} [list $div/I 2.0 1.0 $raw 8.0 4.0 $pad 4.0 2.0] {
        set clk [clock $pin]
        need [expr {abs([prop clock $clk PERIOD] - $period) < 0.001}] "wrong clock period"
        set waveform [prop clock $clk WAVEFORM]
        need [expr {[llength $waveform] == 2 && abs([lindex $waveform 0]) < 0.001 && abs([lindex $waveform 1] - $fall) < 0.001}] "wrong clock waveform"
    }
    foreach domain {rx tx} {
        set managed [dict get $r ${domain}_clock]
        set gate [q_or_buffer $managed BUFGCE O]
        same $gate/I $raw; same $gate/CE [dict get $r ${domain}_gate_ce]
        need [expr {[prop cell $gate CE_TYPE] eq "SYNC"}] "managed BUFGCE CE_TYPE changed"
        need [expr {[clock $managed] eq [clock $raw]}] "independently redeclared managed clock"
    }
    # Reviewed properties include CE_TYPE, inversion, clock uncertainty, etc.
    need [expr {[llength [dict get $r unchanged_properties]] > 0}] "missing original clock-property review"
    foreach row [dict get $r unchanged_properties] {
        lassign $row kind name key expected
        need [expr {[prop $kind $name $key] eq $expected}] "changed original property $name $key"
    }
}
proc raw_handoff::q_or_buffer {pin expected_ref expected_pin} {
    set q [driver $pin]; set c [owner $q]
    need [expr {[prop pin $q REF_PIN_NAME] eq $expected_pin && [prop cell $c REF_NAME] eq $expected_ref}] "wrong direct clock driver: $pin"
    return $c
}
proc raw_handoff::collect {contract_file output} {
    variable serial; set serial 0
    set c [read_dict $contract_file]
    lassign [bind $contract_file $c] dcp admission
    need [expr {![file exists $output]}] "fresh report directory required"
    # The gate owns this read; do not run it in a session with a modified design.
    open_checkpoint $dcp
    set root [dict get $c mac_root]
    need [expr {[prop cell $root REF_NAME] eq [dict get $c mac_ref]}] "source-bound MAC root mismatch"
    set helpers {}
    foreach name [names {get_cells -quiet -hierarchical}] {
        if {[string first "$root/" $name] != 0} {continue}
        if {[prop cell $name REF_NAME] in {MacRawHandoff ValenceMacRawFallingSample} ||
            [string first "$root/rawHandoff/" $name] == 0 || $name eq "$root/rawHandoff"} {lappend helpers $name}
    }
    if {![dict get $c enabled]} {
        need [expr {![llength $helpers]}] "OFF contains helper roles"
        set raw [dict get $c off_raw_clock]
        foreach name [names {get_cells -quiet -hierarchical -filter {REF_NAME == FDCE}}] {
            if {[string first "$root/" $name] != 0} {continue}
            if {[bit [prop pin $name/C IS_INVERTED] 1] && [net $name/C] eq [net $raw]} {
                error "OFF contains a falling RAW FF role: $name"
            }
        }
        need [expr {[lindex [bind $contract_file $c] 1] eq $admission}] "OFF binding changed"
        return "OFF_HELPER_ABSENT_FRESH_BINDING_ONLY timing_qualified=0"
    }
    set r [dict get $c roles]
    check_clocks $r
    set rx_in [dict get $r ingress_delayed]; set rx_fall [dict get $r falling_rx_outputs]
    set rx_out [dict get $r managed_rx_outputs]
    foreach bank [list $rx_in $rx_fall $rx_out] {need [expr {[llength $bank] == 11}] "wrong RX width"}
    set tx_out [dict get $r tx_step_output]
    set falling {}; set managed {}; set sources {}
    foreach input $rx_in fpin $rx_fall output_pin $rx_out {
        set source [qcell $input]; set f [qcell $fpin]; set m [qcell $output_pin]
        ff $source 0 [dict get $r raw_clock] [dict get $r ingress_reset]
        ff $f 1 [dict get $r raw_clock] [dict get $r raw_reset]
        ff $m 0 [dict get $r rx_clock] [dict get $r rx_reset]
        same $f/D $input; same $m/D $fpin
        lappend falling $f; lappend managed $m; lappend sources $source
    }
    set tx [qcell $tx_out]; ff $tx 1 [dict get $r raw_clock] [dict get $r raw_reset]
    lappend falling $tx
    foreach {bank width} [list $falling 12 $managed 11 $sources 11] {
        need [expr {[llength [lsort -unique $bank]] == $width}] "merged/duplicated bank requires review"
    }
    need [expr {[llength [lsort -unique [concat $falling $managed]]] == 23}] "shared falling/managed role"
    # Reject any other sequential helper state, including extra pipeline epochs.
    set helper_state {}
    foreach name $helpers {if {[bit [prop cell $name IS_SEQUENTIAL] 1]} {lappend helper_state $name}}
    need [expr {[lsort $helper_state] eq [lsort [concat $falling $managed]]}] "helper state census mismatch/flattened role review required"
    set decode [dict get $r encoder_phase_and_rate_gap]
    need [expr {[llength $decode] == 11 && [fanin $tx/D] eq [lsort $decode]}] "TX decode source leaves changed"
    foreach q $decode {
        set cell [owner $q]
        need [expr {[prop cell $cell REF_NAME] eq "FDCE" && [bit [prop cell $cell INIT] 0] && [bit [prop pin $cell/C IS_INVERTED] 0] && [bit [prop pin $cell/CLR IS_INVERTED] 0]}] "unreviewed encoder phase/rateGap source"
        same $cell/C [dict get $r raw_clock]; same $cell/CLR [dict get $r raw_reset]
    }
    equation $tx/D $decode byte_step
    same [dict get $r rx_pending] [lindex $rx_out 9]
    set idle_inputs [dict get $r local_idle_inputs]
    need [expr {[llength $idle_inputs] == 8}] "wrong localIdle input roles"
    same [lindex $idle_inputs 5] [dict get $r ingress_empty]
    same [lindex $idle_inputs 6] [lindex $rx_out 9]
    equation [dict get $r local_idle_output] $idle_inputs local_idle
    same [dict get $r ingress_empty_source_d] [dict get $r ingress_empty]
    file mkdir $output
    # Every expected fanout must match the real complete endpoint set. Each
    # row has an exact reviewed source pin and all expected endpoints, not a
    # wildcard/max_paths approximation. Required row keys are enforced below.
    set ingress_fanouts [dict get $r ingress_source_fanouts]
    need [expr {[llength $ingress_fanouts] == 11}] "missing original ingress source fanout rows"
    set required {}
    for {set i 0} {$i < 11} {incr i} {
        set input [lindex $sources $i]/Q; set f [lindex $falling $i]; set m [lindex $managed $i]
        set endpoints [lindex $ingress_fanouts $i]
        need [expr {"$f/D" in $endpoints}] "ingress source omits its falling bit"
        foreach end $endpoints {
            if {$end eq "$f/D"} {continue}
            # Original activity[127] and delayed valid can legally share an FF.
            # Admit only that explicit, source-reviewed alias and its original
            # empty-family endpoints; the empty loop times every pair below.
            need [expr {$i == 9 && [dict get $r reviewed_valid_activity_merge] eq "1" &&
                $input in [dict get $r empty_launches] && $end in [dict get $r fanouts empty]}] "unreviewed original ingress fanout"
            same $input [dict get $r ingress_activity_tail]
        }
        fanout $input $endpoints; fanout $f/Q [list $m/D]
        timed $input $f/D 4.0 $output ingress_to_falling_$i
        timed $f/Q $m/D 4.0 $output falling_to_managed_$i
        lappend required rx_$i
    }
    lappend required tx empty
    need [expr {[lsort [dict keys [dict get $r fanouts]]] eq [lsort $required]}] "missing/extra fanout role"
    dict for {tag endpoints} [dict get $r fanouts] {
        if {[regexp {^rx_([0-9]+)$} $tag -> i]} {set from [lindex $managed $i]/Q; set budget 8.0} elseif {$tag eq "tx"} {
            set from $tx/Q; set budget 4.0
        } else {set from [dict get $r ingress_empty]; set budget 8.0}
        need [expr {[llength $endpoints] > 0}] "empty reviewed fanout $tag"
        fanout $from $endpoints
        foreach end $endpoints {
            set sink_clock [owner $end]/C
            if {[string match rx_* $tag]} {same $sink_clock [dict get $r rx_clock]} elseif {$tag eq "tx"} {
                same $sink_clock [dict get $r tx_clock]
            } else {
                need [expr {[net $sink_clock] in [list [net [dict get $r raw_clock]] [net [dict get $r rx_clock]]]}] "unreviewed empty consumer clock"
            }
            if {$tag eq "empty"} {
                # A combinational hierarchical empty pin is not a timing start.
                # Contract contains its exact reviewed real sequential fanin.
                set starts [dict get $r empty_launches]
                need [expr {[fanin $from] eq [lsort $starts]}] "empty launch census changed"
            } else {set starts [list $from]}
            foreach start $starts {timed $start $end $budget $output ${tag}_consumer}
        }
    }
    foreach q $decode {timed $q $tx/D 4.0 $output tx_complete_decode}
    foreach {reset_pin cells budget label} [list [dict get $r raw_reset] $falling 4.0 raw_release [dict get $r rx_reset] $managed 8.0 rx_release] {
        set q [driver $reset_pin]
        need [expr {[prop pin $q REF_PIN_NAME] eq "Q"}] "reset is not direct release FF Q"
        foreach cell $cells {timed $q $cell/CLR $budget $output ${label}_recovery_removal}
    }
    report_exceptions -coverage -file [file join $output exceptions_coverage.rpt]
    report_exceptions -ignored -file [file join $output exceptions_ignored.rpt]
    report_clock_interaction -file [file join $output clock_interaction.rpt]
    report_pulse_width -file [file join $output pulse_width.rpt]
    report_timing_summary -report_unconstrained -file [file join $output timing_summary.rpt]
    # Detect files changed during collection. Does not write/modify the DCP.
    need [expr {[lindex [bind $contract_file $c] 1] eq $admission}] "binding changed during collection"
    return "FACTS_COLLECTED_REVIEW_REQUIRED_NOT_QUALIFIED enabled=1 falling=12 managed_rx=11 timing_qualified=0 exception_permission=0"
}
