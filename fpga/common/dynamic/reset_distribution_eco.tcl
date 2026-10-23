# R38 mapped equivalent of source 728055c: D=0, PRE=complete CPU release.
# Only call on a separately hash-bound R37/RX450 routed checkpoint copy.
# No checkpoint I/O, routing, timing exceptions or automatic action on source.
namespace eval r38_reset_eco {if {![info exists used]} {variable used 0}}
proc r38_reset_eco::require {test message} {
    if {![uplevel 1 [list expr $test]]} {error "R38_RESET_ECO $message"}
}
proc r38_reset_eco::names {objects} {
    if {![llength $objects]} {return {}}
    return [lsort [get_property NAME $objects]]
}
proc r38_reset_eco::one {objects message} {
    require {[llength $objects] == 1} $message
    return $objects
}
proc r38_reset_eco::pin {cell ref} {
    set p [one [get_pins -quiet -leaf -of_objects $cell -filter "REF_PIN_NAME == $ref"] "missing $cell/$ref"]
    set dir [expr {$ref eq "Q" ? "OUT" : "IN"}]
    require {[get_property DIRECTION $p] eq $dir &&
        [get_property IS_INVERTED $p] in {0 false FALSE}} "wrong pin/polarity $cell/$ref"
    return $p
}
proc r38_reset_eco::ends {p dir} {
    set nets [get_nets -quiet -segments -of_objects $p]
    require {[llength $nets] > 0} "floating pin $p"
    return [names [get_pins -quiet -leaf -of_objects $nets -filter "DIRECTION == $dir"]]
}
proc r38_reset_eco::net {p} {
    return [one [get_nets -quiet -of_objects $p] "ambiguous local net $p"]
}
proc r38_reset_eco::constant {p type driver primitive} {
    require {[ends $p OUT] eq [list $driver]} "wrong $type driver $p"
    foreach n [get_nets -quiet -segments -of_objects $p] {
        require {[get_property TYPE $n] eq $type} "nonconstant net at $p"
    }
    set owner [one [get_cells -quiet -of_objects [get_pins -quiet -leaf -of_objects \
        [get_nets -quiet -segments -of_objects $p] -filter {DIRECTION == OUT}]] "constant owner $p"]
    require {[get_property REF_NAME $owner] eq $primitive} "wrong constant primitive $p"
}
proc r38_reset_eco::inspect {mode} {
    require {$mode in {before after}} "unknown inspection mode"
    require {[get_property PART [current_design]] eq "xczu15eg-ffvb1156-2-i" &&
        [get_property TOP [current_design]] eq "soc_top_common_ddr"} "wrong part/top"
    foreach {clock period} {cpu_target300 3.333333333333 fabric_target250 4.0} {
        set c [one [get_clocks -quiet $clock] "missing target $clock"]
        require {abs([get_property PERIOD $c]-$period)<0.002} "changed target $clock"
    }
    set root u_soc/cpuFunctionalReset_cpuResetDistribution
    set cells [get_cells -quiet -hierarchical -filter {NAME =~ u_soc/cpuFunctionalReset_cpuResetDistribution/distributed_reg*}]
    set wanted [list $root/distributed_reg $root/distributed_reg_replica]
    for {set i 1} {$i <= 39} {incr i} {lappend wanted $root/distributed_reg_replica_$i}
    require {[names $cells] eq [lsort $wanted]} "changed 41-copy census"
    set release [get_cells -quiet -hierarchical -filter {NAME =~ u_soc/cpuRelease/release_0_reg*}]
    set wantedRelease {}
    for {set i 0} {$i < 3} {incr i} {lappend wantedRelease [format {u_soc/cpuRelease/release_0_reg[%d]} $i]}
    require {[names $release] eq [lsort $wantedRelease]} "changed three-stage release"
    set stage {}; set stable {}; set dpins {}; set prepins {}; set cpins {}; set allLoads {}
    set finalQ {u_soc/cpuRelease/release_0_reg[2]/Q}
    set rawDriver u_soc/cpuRelease_i_1/O
    set groundDriver u_soc/cpuRelease/GND/G
    foreach cell [concat $release $cells] {
        set n [get_property NAME $cell]; set isRelease [expr {[lsearch -exact $wantedRelease $n]>=0}]
        set attrs {}
        foreach key {REF_NAME INIT ASYNC_REG DONT_TOUCH LOC BEL} {dict set attrs $key [get_property $key $cell]}
        require {[dict get $attrs REF_NAME] eq "FDPE" && [string tolower [dict get $attrs INIT]] in {1 1'b1 1'h1 0x1}} "wrong FF/INIT $n"
        require {[dict get $attrs LOC] ne "" && [dict get $attrs BEL] ne ""} "unplaced FF $n"
        if {$isRelease} {
            require {[dict get $attrs ASYNC_REG] in {1 true TRUE}} "unprotected release $n"
        } else {
            require {[dict get $attrs ASYNC_REG] eq "" && [dict get $attrs DONT_TOUCH] eq ""} "protected distribution $n"
        }
        set pins {}
        foreach ref {C D CE PRE Q} {dict set pins $ref [pin $cell $ref]}
        set c [dict get $pins C]; set d [dict get $pins D]; set pre [dict get $pins PRE]; set q [dict get $pins Q]
        require {[ends $c OUT] eq {cpu_clock/managed_buffer/O} &&
            [names [get_clocks -quiet -of_objects $c]] eq {cpu_target300}} "wrong CPU clock $n"
        set powerDriver [expr {$isRelease ? "u_soc/cpuRelease/VCC/P" : "$root/VCC/P"}]
        constant [dict get $pins CE] POWER $powerDriver VCC
        dict set stable $n attrs $attrs
        dict set stable $n clock [ends $c OUT]
        dict set stable $n ce [ends [dict get $pins CE] OUT]
        if {$isRelease} {
            require {[ends $pre OUT] eq [list $rawDriver]} "changed original release PRE $n"
            dict set stable $n d [ends $d OUT]
            dict set stable $n pre [ends $pre OUT]
            dict set stage $n $pins
        } else {
            set expectedD [expr {$mode eq "before" ? $finalQ : $groundDriver}]
            set expectedPre [expr {$mode eq "before" ? $rawDriver : $finalQ}]
            require {[ends $d OUT] eq [list $expectedD] && [ends $pre OUT] eq [list $expectedPre]} "wrong distribution D/PRE $n"
            if {$mode eq "after"} {constant $d GROUND $groundDriver GND}
            set loads [ends $q IN]
            require {[llength $loads]>=3 && [llength $loads]<=250} "unreviewed Q load count $n"
            dict set stable $n loads $loads
            set allLoads [concat $allLoads $loads]
            lappend dpins $d; lappend prepins $pre; lappend cpins $c
        }
    }
    require {[llength $allLoads]==5987 && [llength [lsort -unique $allLoads]]==5987} "changed distribution total/aliased Q loads"
    set first [dict get $stage [lindex $wantedRelease 0]]
    constant [dict get $first D] GROUND $groundDriver GND
    for {set i 1} {$i < 3} {incr i} {
        set previous [dict get $stage [lindex $wantedRelease [expr {$i-1}]]]
        set next [dict get $stage [lindex $wantedRelease $i]]
        require {[ends [dict get $next D] OUT] eq [names [dict get $previous Q]] &&
            [ends [dict get $previous Q] IN] eq [names [dict get $next D]]} "early release bypass/fanout"
    }
    set last [dict get $stage [lindex $wantedRelease 2]]
    set d0 [dict get $first D]; set q2 [dict get $last Q]; set raw [dict get $first PRE]
    return [dict create stable $stable dpins $dpins prepins $prepins cpins $cpins launch [dict get $last C] \
        ground [net $d0] groundPin $d0 local [net [lindex $dpins 0]] q2 $q2 raw $raw \
        groundLoads [ends $d0 IN] localLoads [ends $q2 IN] rawLoads [ends $raw IN]]
}
proc r38_reset_eco::same_stable {a b} {
    require {[lsort [dict keys $a]] eq [lsort [dict keys $b]]} "stable cell census changed"
    dict for {name state} $a {require {$state eq [dict get $b $name]} "FF attributes/clocks/source chain/Q consumers changed $name"}
}
proc r38_reset_eco::subtract {items remove} {
    foreach x $remove {
        set i [lsearch -exact $items $x]
        require {$i>=0} "expected endpoint absent $x"
        set items [lreplace $items $i $i]
    }
    return [lsort $items]
}
proc r38_reset_eco::apply {directory} {
    variable used
    require {!$used} "one-shot guard: reopen the immutable input, never retry partial ECO"
    require {![file exists $directory]} "output directory exists"
    set before [inspect before]
    file mkdir $directory
    set f [open [file join $directory before.tcldict] w]; puts $f $before; close $f
    set d [dict get $before dpins]; set pre [dict get $before prepins]
    set oldPreNet [net [lindex $pre 0]]; set localNet [dict get $before local]
    foreach p $pre {require {[names [net $p]] eq [names $oldPreNet]} "split original PRE net"}
    foreach p $d {require {[names [net $p]] eq [names $localNet]} "split original D net"}
    set used 1
    # Mutation starts only after ALL copies and the complete source chain pass.
    # No -quiet/-prune: a native error must abort, without hiding partial edits.
    disconnect_net -net $oldPreNet -pinlist $pre
    disconnect_net -net $localNet -pinlist $d
    connect_net -hierarchical -net $localNet -objects $pre
    connect_net -hierarchical -net [dict get $before ground] -objects $d
    set after [inspect after]
    same_stable [dict get $before stable] [dict get $after stable]
    set dNames [names $d]; set preNames [names $pre]
    require {[dict get $after rawLoads] eq [subtract [dict get $before rawLoads] $preNames]} "unintended raw reset load change"
    require {[dict get $after localLoads] eq [lsort [concat [subtract [dict get $before localLoads] $dNames] $preNames]]} "unintended local release load change"
    require {[dict get $after groundLoads] eq [lsort [concat [dict get $before groundLoads] $dNames]]} "unintended ground load change"
    set f [open [file join $directory after.tcldict] w]; puts $f $after; close $f
    puts "R38_RESET_ECO_CONNECTIVITY_PASS copies=41 D_changes=41 PRE_changes=41 Q_loads=5987 NO_TIMING_EXCEPTION NOT_ROUTED_NOT_SIGNOFF"
    return $after
}
