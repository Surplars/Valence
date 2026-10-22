# Structural control-flow mocks only; never native qualification.
set here [file dirname [file normalize [info script]]]
if {$argc!=1} {error {usage: immutable_prechange_common_cdc.tcl}}
set baseline [lindex $argv 0]
proc assert {value reason} {if {![uplevel 1 [list expr $value]]} {error $reason}}
foreach {ip source} [list old $baseline new [file join $here common_cdc.tcl]] {
    interp create $ip
    $ip eval [list set ::valence(root) [file dirname [file dirname $here]]]
    $ip eval [list source $source]
    $ip eval {
        rename puts real_puts
        set markers {};set calls {};set fail {}
        proc puts args {
            set text [lindex $args end]
            if {[lindex $text 0] eq {COMMON_CDC_PROGRESS}} {lappend ::markers $text}
        }
        proc trace_call {name args} {
            lappend ::calls [list $name {*}$args]
            if {$::fail eq $name} {error "INJECTED_$name"}
        }
        proc common_cdc::dynamic_clock_anchors {soc timer} {trace_call anchors $soc $timer;return fixed}
        proc common_cdc::clock pin {
            trace_call clock $pin
            switch $pin {
                cpu_clock/managed_buffer/O {return cpu}
                fabric_clock/managed_buffer/O {return fabric}
                network_clock/raw_div/O {return mac}
                u_soc/alwaysOnClock {return aon}
                default {error "unexpected pin $pin"}
            }
        }
        foreach name {one expect_clock same_net new_stage_coverage exact_modules} {
            proc common_cdc::$name {args} [format {trace_call %s {*}$args} $name]
        }
        # Prove wiring to each unchanged exact group; the census implementation
        # itself is independently exercised by test_dynamic_census_reuse.tcl.
        proc common_cdc::exact_module_groups {root groups} {
            foreach {ref expected} $groups {exact_modules $root $ref $expected}
        }
        foreach name {gray payload register_payload mailbox_width level} {
            proc common_cdc::$name {args} [format {trace_call %s {*}$args;return [list label %s args $args]} $name $name]
        }
    }
}
proc run_dynamic {ip fail} {
    $ip eval [list set ::fail $fail]
    $ip eval {set markers {};set calls {}}
    set code [catch {$ip eval {common_cdc::collect_dynamic u_soc u_soc/fixedTimer}} value]
    return [list $code $value [$ip eval {set calls}]]
}
proc has_marker {stage event {detail {}}} {
    foreach line [new eval {set markers}] {
        if {[lsearch -exact $line stage=$stage]>=0 && [lsearch -exact $line event=$event]>=0 &&
            ($detail eq {} || [lsearch -exact $line detail=$detail]>=0)} {return 1}
    }
    return 0
}
set a [run_dynamic old {}];set b [run_dynamic new {}]
assert {$a eq $b} {dynamic scopes or proof call sequence changed}
set calls [new eval {set calls}]
set levels 0;set censuses 0
foreach call $calls {
    if {[lindex $call 0] eq {level}} {incr levels}
    if {[lindex $call 0] eq {exact_modules}} {incr censuses}
}
assert {$levels==88 && $censuses==55} {source-known level/group coverage changed}
assert {[has_marker dynamic_mailboxes COMPLETE 32] && [has_marker dynamic_levels COMPLETE 88]} {missing phase completion marker}
assert {[has_marker census COMPLETE u_soc/debugFaultSync]} {missing final root marker}
foreach fail {level exact_modules} {
    set a [run_dynamic old $fail];set b [run_dynamic new $fail]
    assert {$a eq $b && [lindex $a 0]==1} {failure semantics changed}
    if {$fail eq {level}} {
        assert {[has_marker level BEGIN] && ![has_marker level COMPLETE] && ![has_marker dynamic_levels COMPLETE]} {false level completion marker}
    } else {
        assert {[has_marker census BEGIN] && ![has_marker census COMPLETE]} {false census completion marker}
    }
}
foreach ip {old new} {
    $ip eval {
        set expectedScopes [list [dict create label first starts src/C ends dst/D budget 3.333 skew 1] \
            [dict create label second starts a/C ends b/D budget 4.0 skew 0]]
        proc common_cdc::collect root {trace_call collect $root;return $::expectedScopes}
        proc common_cdc::objects {kind names} {trace_call objects $kind $names;return $names}
        foreach command {set_max_delay set_bus_skew} {
            proc ::$command args [format {trace_call %s {*}$args} $command]
        }
    }
}
proc run_constrain {ip fail} {
    $ip eval [list set ::fail $fail];$ip eval {set calls {};set markers {}}
    set code [catch {$ip eval {common_cdc::constrain}} value]
    return [list $code $value [$ip eval {set calls}]]
}
set a [run_constrain old {}];set b [run_constrain new {}]
assert {$a eq $b} {scope or budget application changed}
assert {[has_marker collect COMPLETE 2] && [has_marker budgets COMPLETE 2]} {missing completed stage marker}
foreach fail {collect set_max_delay} {
    set a [run_constrain old $fail];set b [run_constrain new $fail]
    assert {$a eq $b && [lindex $a 0]==1} {constraint failure behavior changed}
    assert {![has_marker budgets COMPLETE]} {failed budget marked complete}
    if {$fail eq {collect}} {
        assert {![has_marker collect COMPLETE] && ![has_marker budgets BEGIN]} {incomplete collection marked resumable}
    }
}
puts {CDC_PROGRESS_PASS scenarios=6 unchanged_dynamic_scope_and_proof_sequence=1 levels=88 exact_groups=55 no_false_completion=1 MOCK_ONLY_NOT_NATIVE_QUALIFIED}

# Independent audit fixtures below describe timing responses, not injected
# exceptions. A negative passes only when audit_timing observes the corrupt
# response and rejects it with the expected checker diagnostic. The query
# oracle is built separately from either implementation.
foreach ip {old new} {
    $ip eval {
        proc puts args {
            set text [lindex $args end]
            if {[lindex $text 0] eq {COMMON_CDC_PROGRESS}} {lappend ::markers $text}
            if {[llength $args]==2 && [lindex $args 0] ni {stdout stderr -nonewline}} {
                real_puts {*}$args
            }
        }
        proc common_cdc::one {command name} {
            lappend ::auditLog [list one $command $name]
            return pin:$name
        }
        proc common_cdc::objects {command names} {
            lappend ::auditLog [list objects $command $names]
            set prefix [expr {$command eq {get_pins} ? {pin} : {cell}}]
            return [lmap name $names {format {%s:%s} $prefix $name}]
        }
        proc common_cdc::drivers pin {
            lappend ::auditLog [list drivers $pin]
            return [dict get $::auditDrivers $pin]
        }
        proc get_cells args {
            lappend ::auditLog [list get_cells {*}$args]
            if {[lindex $args 0] eq {-of_objects}} {
                set pin [lindex [lindex $args 1] 0]
                return cell:[string range $pin 4 end-2]
            }
            return [lmap name [lindex $args 0] {format {cell:%s} $name}]
        }
        proc get_timing_paths args {
            lappend ::auditLog [list get_timing_paths {*}$args]
            lappend ::auditTiming $args
            set index [expr {[llength $::auditTiming]-1}]
            if {$index >= [llength $::auditPlan]} {error {MOCK unexpected extra timing query}}
            set row [lindex $::auditPlan $index]
            if {$args ne [dict get $row args]} {
                error "MOCK timing arguments differ at query [expr {$index+1}]: $args"
            }
            if {[dict exists $row paths]} {return [dict get $row paths]}
            return path:$index
        }
        proc get_property {property object} {
            lappend ::auditLog [list get_property $property $object]
            if {[string match cell:* $object] && $property eq {NAME}} {
                return [string range $object 5 end]
            }
            if {![string match path:* $object]} {error "MOCK unexpected property object $object"}
            set index [string range $object 5 end]
            return [dict get [lindex $::auditPlan $index] properties $property]
        }
        proc report_bus_skew args {
            lappend ::auditLog [list report_bus_skew {*}$args]
            return {}
        }
    }
}
proc audit_add_path {planVar mode starts end kind budget scopeIndex} {
    upvar 1 $planVar plan
    set from [lmap start $starts {format {pin:%s} $start}]
    set args [list -quiet -from $from -to pin:$end -delay_type $kind -max_paths 1]
    if {$mode eq {endpoint}} {lappend args -nworst 1}
    lappend plan [dict create args $args mode $mode scope $scopeIndex properties [dict create \
        STARTPOINT_PIN [lindex $starts 0] ENDPOINT_PIN $end REQUIREMENT $budget SLACK 0.125 EXCEPTION Max_Delay]]
}
set auditScopes [list \
    [dict create label payload starts {ram0/C ram1/C} ends {capture0/D capture1/D capture2/D} \
        second {sync0 sync1} budget 3.333 skew 1 \
        by_end [dict create capture0/D {ram0/C ram1/C} capture1/D ram1/C capture2/D ram0/C] \
        ordinary_by_end [dict create capture0/D local0/C capture1/D {local1/C local2/C} capture2/D {}]] \
    [dict create label level starts level/source/C ends {level/first0/D level/first1/D} \
        second level/second0 budget 4.0 skew 0] \
    [dict create label empty starts {} ends {} second {} budget 4.0 skew 0]]
set auditDrivers [dict create sync0/D first0/Q sync1/D first1/Q level/second0/D level/first0/Q]
set auditPlan {}
audit_add_path auditPlan ram ram0/C capture0/D max 3.333 0
audit_add_path auditPlan ram ram1/C capture0/D max 3.333 0
audit_add_path auditPlan ordinary local0/C capture0/D max 3.333 0
audit_add_path auditPlan ordinary local0/C capture0/D min 3.333 0
audit_add_path auditPlan ram ram1/C capture1/D max 3.333 0
audit_add_path auditPlan ordinary local1/C capture1/D max 3.333 0
audit_add_path auditPlan ordinary local1/C capture1/D min 3.333 0
audit_add_path auditPlan ordinary local2/C capture1/D max 3.333 0
audit_add_path auditPlan ordinary local2/C capture1/D min 3.333 0
audit_add_path auditPlan ram ram0/C capture2/D max 3.333 0
foreach end {capture0/D capture1/D capture2/D} {
    audit_add_path auditPlan endpoint {ram0/C ram1/C} $end max 3.333 0
}
foreach {first second} {first0 sync0 first1 sync1} {
    foreach kind {max min} {audit_add_path auditPlan interstage $first/C $second/D $kind 3.333 0}
}
foreach end {level/first0/D level/first1/D} {
    audit_add_path auditPlan endpoint level/source/C $end max 4.0 1
}
foreach kind {max min} {audit_add_path auditPlan interstage level/first0/C level/second0/D $kind 4.0 1}
assert {[llength $auditPlan]==21} {incorrect independent audit fixture}

proc run_audit {ip scopes plan drivers output profile} {
    foreach {key value} [list auditScopes $scopes auditPlan $plan auditDrivers $drivers auditOutput $output] {
        $ip eval [list set ::$key $value]
    }
    $ip eval {set auditLog {};set auditTiming {};unset -nocomplain ::valence(clock_profile)}
    if {$profile ne {}} {$ip eval [list set ::valence(clock_profile) $profile]}
    $ip eval {set ::common_cdc::dynamic_roots {u_soc/dynamicA u_soc/dynamicB}}
    set code [catch {$ip eval {common_cdc::audit_timing $::auditScopes $::auditOutput}} message]
    set f [open [file join $output common-cdc-scopes.tcllist] r]
    try {set contents [read $f]} finally {close $f}
    set log [$ip eval {set auditLog}]
    set startsCalls {};set semanticLog {};set skewCalls {}
    foreach call $log {
        set isStarts 0
        if {[lrange $call 0 1] eq {objects get_pins}} {
            foreach scope $scopes {
                if {[lindex $call 2] eq [dict get $scope starts]} {set isStarts 1;break}
            }
        }
        if {$isStarts} {lappend startsCalls $call} else {lappend semanticLog $call}
        if {[lindex $call 0] eq {report_bus_skew}} {lappend skewCalls $call}
    }
    return [dict create code $code message $message contents $contents semantic $semanticLog \
        timing [$ip eval {set auditTiming}] starts $startsCalls skew $skewCalls]
}
proc check_audit_case {name scopes plan drivers output {badQuery 0} {diagnostic {}} {profile {}}} {
    set old [run_audit old $scopes $plan $drivers $output $profile]
    set new [run_audit new $scopes $plan $drivers $output $profile]
    foreach key {code message contents semantic timing skew} {
        assert {[dict get $old $key] eq [dict get $new $key]} "$name changed audit $key"
    }
    set count [expr {$badQuery ? $badQuery : [llength $plan]}]
    set expectedArgs [lmap row [lrange $plan 0 [expr {$count-1}]] {dict get $row args}]
    assert {[dict get $old timing] eq $expectedArgs} "$name timing sequence not equal to independent oracle"
    if {$badQuery} {
        assert {[dict get $new code]==1 && [string match $diagnostic [dict get $new message]]} \
            "$name did not reject observed corruption with checker diagnostic: [dict get $new message]"
        assert {[llength [dict get $new skew]]==0} "$name continued to skew after rejection"
        set lastScope [dict get [lindex $plan [expr {$badQuery-1}]] scope]
    } else {
        assert {[dict get $new code]==0} "$name rejected valid fixture: [dict get $new message]"
        assert {[llength [dict get $new skew]]==1} "$name omitted final skew report"
        set lastScope [expr {[llength $scopes]-1}]
    }
    set expectedContents {}
    foreach scope [lrange $scopes 0 $lastScope] {append expectedContents $scope \n}
    assert {[dict get $new contents] eq $expectedContents} "$name changed exact scope-file contents"
    set expectedOld {};set expectedNew {};set seenScopes {}
    foreach row [lrange $plan 0 [expr {$count-1}]] {
        if {[dict get $row mode] ne {endpoint}} {continue}
        set scopeIndex [dict get $row scope]
        set call [list objects get_pins [dict get [lindex $scopes $scopeIndex] starts]]
        lappend expectedOld $call
        if {$scopeIndex ni $seenScopes} {lappend expectedNew $call;lappend seenScopes $scopeIndex}
    }
    assert {[dict get $old starts] eq $expectedOld} "$name baseline starts-lookup count changed"
    assert {[dict get $new starts] eq $expectedNew} "$name candidate must resolve starts once per reached nonempty scope"
    incr ::auditCases
    return [list [llength [dict get $old starts]] [llength [dict get $new starts]] [llength [dict get $new timing]]]
}
set temp [file tempfile auditOutput]
close $temp
file delete $auditOutput
file mkdir $auditOutput
set auditCases 0
try {
    set fullCounts [check_audit_case full $auditScopes $auditPlan $auditDrivers $auditOutput]
    assert {$fullCounts eq {5 2 21}} {full audit query-reuse counts changed}
    foreach profile {boot50-static boot50-dynamic} {
        check_audit_case $profile $auditScopes $auditPlan $auditDrivers $auditOutput 0 {} $profile
    }
    # Zero slack and a requirement within the existing 0.001 tolerance remain
    # accepted; normalized max-delay spelling remains accepted as well.
    set plan $auditPlan
    set row [lindex $plan 11]
    dict set row properties SLACK 0
    dict set row properties REQUIREMENT 3.3335
    dict set row properties EXCEPTION {MAX - DELAY}
    lset plan 11 $row
    check_audit_case tolerance $auditScopes $plan $auditDrivers $auditOutput

    foreach {query mutations diagnostic} {
        2 {paths {} STARTPOINT_PIN alien/C ENDPOINT_PIN alien/D} {COMMON_PAYLOAD missing exact RAM path *}
        2 {EXCEPTION {} EXCEPTION false_path REQUIREMENT 3.335 REQUIREMENT 0 REQUIREMENT not_numeric SLACK -0.1 SLACK not_numeric} {COMMON_PAYLOAD missing/relaxed/failing bound *}
        3 {paths {} SLACK -0.1 SLACK not_numeric} {COMMON_PAYLOAD cut/failing destination max path *}
        4 {paths {} SLACK -0.1 SLACK not_numeric} {COMMON_PAYLOAD cut/failing destination min path *}
        12 {paths {} ENDPOINT_PIN alien/D} {COMMON_CDC cut/missing exact max-delay path *}
        12 {EXCEPTION {} EXCEPTION false_path REQUIREMENT 3.335 REQUIREMENT 0 REQUIREMENT not_numeric SLACK -0.1 SLACK not_numeric} {COMMON_CDC missing/relaxed/violating max-delay bound *}
        14 {paths {} SLACK -0.1 SLACK not_numeric} {COMMON_CDC interstage max missing/failing *}
        15 {paths {} SLACK -0.1 SLACK not_numeric} {COMMON_CDC interstage min missing/failing *}
        19 {SLACK -0.1} {COMMON_CDC missing/relaxed/violating max-delay bound *}
    } {
        foreach {property value} $mutations {
            set plan $auditPlan
            set row [lindex $plan [expr {$query-1}]]
            if {$property eq {paths}} {dict set row paths $value} else {dict set row properties $property $value}
            lset plan [expr {$query-1}] $row
            check_audit_case "query${query}_${property}=$value" $auditScopes $plan $auditDrivers $auditOutput $query $diagnostic
        }
    }
    # Keep both interpreters alive and retain labels/endpoints while changing
    # starts between calls. A cross-call cache would use stale -from objects.
    foreach starts {{freshA/C} {freshB/C freshC/C}} {
        set scopes [list [dict create label reused starts $starts ends {reused0/D reused1/D} second {} budget 5.0 skew 0]]
        set plan {}
        foreach end {reused0/D reused1/D} {audit_add_path plan endpoint $starts $end max 5.0 0}
        check_audit_case across_call_$starts $scopes $plan {} $auditOutput
    }
    puts "CDC_AUDIT_QUERY_REUSE_PASS scenarios=$auditCases starts_lookups=5->2 timing_queries=21 exact_arguments_and_scope_files=1 observed_corruption_rejected=1 no_checks_after_failure=1 MOCK_ONLY_NOT_NATIVE_QUALIFIED"
} finally {file delete -force $auditOutput}
