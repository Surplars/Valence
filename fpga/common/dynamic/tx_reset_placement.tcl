# One reviewed physical candidate. No logical ECO, exceptions, or clock changes.
namespace eval r38_tx_place {if {![info exists attempted]} {variable attempted 0}}
proc r38_tx_place::need {test why} {if {![uplevel 1 [list expr $test]]} {error "R38_TX_PLACE $why"}}
proc r38_tx_place::names {xs} {if {![llength $xs]} {return {}}; return [lsort [get_property NAME $xs]]}
proc r38_tx_place::one {xs why} {need {[llength $xs]==1} $why; return $xs}
proc r38_tx_place::cell {n} {return [one [get_cells -quiet -hierarchical -filter [format {NAME == "%s"} $n]] "missing exact cell $n"]}
proc r38_tx_place::pin {c r} {return [one [get_pins -quiet -leaf -of_objects $c -filter "REF_PIN_NAME == $r"] "missing pin $c/$r"]}
proc r38_tx_place::ends {p dir} {
    set ns [get_nets -quiet -segments -of_objects $p]; need {[llength $ns]>0} "floating $p"
    return [names [get_pins -quiet -leaf -of_objects $ns -filter "DIRECTION == $dir"]]
}
proc r38_tx_place::constant {p type primitive} {
    set ns [get_nets -quiet -segments -of_objects $p]; need {[llength $ns]>0} "constant absent"
    foreach n $ns {need {[get_property TYPE $n] eq $type} "constant net type $p"}
    set d [one [get_pins -quiet -leaf -of_objects $ns -filter {DIRECTION == OUT}] "constant driver count"]
    need {[get_property REF_NAME [one [get_cells -quiet -of_objects $d] owner]] eq $primitive} "constant primitive $p"
}
proc r38_tx_place::wanted_loads {} {
    set x {u_rgmii/high_clock_reg/CLR u_rgmii/low_clock_reg/CLR u_rgmii/previous_clock_reg/CLR u_rgmii/phase_high_reg/PRE u_rgmii/tx_clock_ddr/RST}
    for {set i 0} {$i<5} {incr i} {
        if {$i<4} {lappend x [format {u_rgmii/high_symbol_reg[%d]/CLR} $i]}
        lappend x [format {u_rgmii/low_symbol_reg[%d]/CLR} $i] [format {u_rgmii/transmit[%d].data_ddr/RST} $i]
    }
    return [lsort $x]
}
proc r38_tx_place::inspect {phase} {
    need {$phase in {before after}} "phase"
    need {[get_property PART [current_design]] eq "xczu15eg-ffvb1156-2-i"} "part"
    foreach {n period} {cpu_target300 3.333333333333 fabric_target250 4.0} {
        set c [one [get_clocks -quiet $n] "target $n"]
        need {abs([get_property PERIOD $c]-$period)<0.002} "performance target changed"
    }
    set wanted {}; for {set i 0} {$i<3} {incr i} {lappend wanted [format {tx_release/tx_reset_pipe_reg[%d]} $i]}
    need {[names [get_cells -quiet -hierarchical -filter {NAME =~ tx_release/tx_reset_pipe_reg*}]] eq [lsort $wanted]} "three-stage census"
    set stable {}; set stages {}; set places {}
    for {set i 0} {$i<3} {incr i} {
        set n [lindex $wanted $i]; set c [cell $n]; set attrs {}
        foreach k {REF_NAME INIT ASYNC_REG DONT_TOUCH} {dict set attrs $k [get_property $k $c]}
        need {[dict get $attrs REF_NAME] eq "FDPE" && [dict get $attrs INIT] in {1 1'b1 1'h1} && [dict get $attrs ASYNC_REG] in {1 TRUE true} && [dict get $attrs DONT_TOUCH] eq ""} "FF/INIT/ASYNC_REG $n"
        set loc [get_property LOC $c]; set bel [get_property BEL $c]
        set expectedLoc [expr {$phase eq "before" ? "SLICE_X116Y132" : "SLICE_X106Y229"}]
        set expectedBel [lindex [expr {$phase eq "before" ? {HFF2 EFF2 FFF2} : {EFF2 FFF2 GFF2}}] $i]
        need {$loc eq $expectedLoc && [lindex [split $bel .] end] eq $expectedBel} "placement $n"
        dict set places $n [list $loc $bel]
        dict set stable $n attrs $attrs
        set ps {}
        foreach r {C D CE PRE Q} {
            set p [pin $c $r]; dict set ps $r $p
            need {[get_property IS_INVERTED $p] in {0 FALSE false}} "pin polarity $n/$r"
            dict set stable $n $r [ends $p OUT]
        }
        need {[ends [dict get $ps C] OUT] eq {network_clock/raw_div/O}} "RAW125 source"
        need {[names [get_clocks -quiet -of_objects [dict get $ps C]]] eq {valence_tx_raw_div}} "RAW125 clock"
        constant [dict get $ps CE] POWER VCC
        need {[ends [dict get $ps PRE] OUT] eq {tx_release_i_1/O}} "shared inhibit"
        dict set stable $n preloads [ends [dict get $ps PRE] IN]
        set expectedD [expr {$i==0 ? {tx_release/GND/G} : [list [lindex $wanted [expr {$i-1}]]/Q]}]
        need {[ends [dict get $ps D] OUT] eq $expectedD} "chain D driver"
        if {$i==0} {constant [dict get $ps D] GROUND GND}
        set loads [ends [dict get $ps Q] IN]
        set expectedLoads [expr {$i<2 ? [list [lindex $wanted [expr {$i+1}]]/D] : [wanted_loads]}]
        need {$loads eq $expectedLoads} "Q fanout $n"
        dict set stable $n loads $loads; lappend stages $ps
    }
    set endpoints {}; set oserdes {}
    foreach n [wanted_loads] {
        set c [cell [file dirname $n]]; set p [pin $c [file tail $n]]
        set ref [get_property REF_NAME $c]
        set expectedRef [expr {[file tail $n] eq "RST" ? "OSERDESE3" : ([file tail $n] eq "PRE" ? "FDPE" : "FDCE")}]
        need {$ref eq $expectedRef} "consumer primitive $n"
        need {[ends $p OUT] eq [list [lindex $wanted 2]/Q]} "consumer reset driver $n"
        set attrs {}; foreach k {REF_NAME INIT ASYNC_REG DONT_TOUCH LOC BEL} {dict set attrs $k [get_property $k $c]}
        dict set stable consumers $n attrs $attrs
        # Preserve every native input's driver, including OSERDESE3 clock/reset.
        foreach ip [get_pins -quiet -leaf -of_objects $c -filter {DIRECTION == IN}] {
            set ipn [get_property NAME $ip]
            set ns [get_nets -quiet -segments -of_objects $ip]
            dict set stable consumers $n inputs $ipn [names [get_pins -quiet -leaf -of_objects $ns -filter {DIRECTION == OUT}]]
        }
        if {$ref eq "OSERDESE3"} {lappend oserdes $p} else {lappend endpoints $p}
    }
    foreach {n period wave divide} {raw_div 8.0 {0.000 4.000} 4 quarter_div 4.0 {0.000 2.000} 2} {
        set c [cell network_clock/$n]; set p [pin $c O]
        set cl [one [get_clocks -quiet -of_objects $p] "clock count $n"]
        need {[get_property REF_NAME $c] eq "BUFGCE_DIV" && [get_property BUFGCE_DIVIDE $c]==$divide && abs([get_property PERIOD $cl]-$period)<0.001 && [get_property WAVEFORM $cl] eq $wave && [get_property MASTER_CLOCK $cl] eq "ref_source"} "fixed clock geometry $n"
        foreach k {REF_NAME LOC BEL BUFGCE_DIVIDE} {dict set stable clocks $n $k [get_property $k $c]}
        foreach k {NAME PERIOD WAVEFORM MASTER_CLOCK SOURCE_PINS} {dict set stable clocks $n $k [get_property $k $cl]}
        set net [one [get_nets -quiet -of_objects $p] "clock output net $n"]
        foreach k {CLOCK_ROOT USER_CLOCK_ROOT CLOCK_DELAY_GROUP} {dict set stable clocks $n net_$k [get_property $k $net]}
    }
    return [dict create stable $stable stages $stages endpoints $endpoints oserdes $oserdes places $places]
}
proc r38_tx_place::apply {directory} {
    variable attempted; need {!$attempted} "one-shot: reopen immutable input after any attempt"
    set before [inspect before]
    set mapping {}; set i 0
    foreach bel {EFF2 FFF2 GFF2} {
        set b [one [get_bels -quiet SLICE_X106Y229/$bel] "missing target BEL"]
        need {[llength [get_cells -quiet -of_objects $b]]==0} "occupied target BEL $bel"
        lappend mapping [get_property NAME [cell [format {tx_release/tx_reset_pipe_reg[%d]} $i]]] SLICE_X106Y229/$bel
        incr i
    }
    need {![file exists $directory]} "fresh evidence directory required"
    file mkdir $directory
    set f [open [file join $directory before.tcllist] {WRONLY CREAT EXCL}]; puts $f $before; close $f
    set attempted 1
    # Explicitly release the three old placements before assigning new BELs.
    # UG835 unplace_cell accepts an exact cell list. Do not clear unrelated
    # properties, ASYNC_REG, other cells, or shared clock/constant routing.
    set moving {}; foreach {n location} $mapping {lappend moving $n}
    puts [list R38_TX_UNPLACE_EXACT $moving]
    unplace_cell $moving
    foreach n $moving {
        set c [cell $n]; set loc [get_property LOC $c]; set bel [get_property BEL $c]
        puts [list R38_TX_UNPLACED $n LOC $loc BEL $bel]
        need {$loc eq "" && $bel eq ""} "unplace retained LOC/BEL $n"
    }
    # Vendor legality is authoritative (shared clock/reset/LUT control sets).
    # No -quiet, no unprotect/force, no alternate location retry.
    place_cell $mapping
    set after [inspect after]
    need {[dict get $before stable] eq [dict get $after stable]} "placement altered logic/clock/sink attributes"
    set f [open [file join $directory placed.tcllist] {WRONLY CREAT EXCL}]; puts $f $after; close $f
    return $before
}
