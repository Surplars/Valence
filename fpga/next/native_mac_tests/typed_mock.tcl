# Strict object mock: only typed handles cross property/-of_objects APIs.
set db {}; set conn {}; set clocks {}; set pinCells {}; set netOverrides {}; set pinOverrides {}
proc obj {kind name} {return "@$kind:$name"}
proc typed {object kind} {
    if {![string match "@$kind:*" $object]} {error "untyped $kind object passed: $object"}
    return [string range $object [expr {[string length $kind]+2}] end]
}
proc add_cell {name ref {init {}}} {global db; dict set db cell $name [dict create NAME $name REF_NAME $ref INIT $init]}
proc add_pin {cell name net {direction IN} {inverted 0}} {
    global db conn pinCells
    set full $cell/$name
    dict set db pin $full [dict create NAME $full REF_PIN_NAME $name DIRECTION $direction IS_INVERTED $inverted IS_LEAF [expr {[dict exists $db cell $cell] ? 1 : 0}]]
    dict set conn $full $net; dict set pinCells $full $cell
    if {![dict exists $db net $net]} {dict set db net $net [dict create NAME $net TYPE SIGNAL]}
}
proc objects {kind names} {return [lmap n $names {obj $kind $n}]}
proc get_cells {args} {
    global db
    if {"-hier" in $args} {
        set names {}; dict for {name props} [dict get $db cell] {if {[dict get $props REF_NAME] in {FDCE FDPE}} {lappend names $name}}
        return [objects cell $names]
    }
    set name [lindex $args end]
    if {![dict exists $db cell $name]} {return {}}
    return [list [obj cell $name]]
}
proc get_pins {args} {
    global db conn pinCells pinOverrides
    set at [lsearch -exact $args -of_objects]
    if {$at<0} {set name [lindex $args end]; if {[dict exists $pinOverrides $name]} {return [objects pin [dict get $pinOverrides $name]]}; if {![dict exists $db pin $name]} {return {}}; return [list [obj pin $name]]}
    set handles [lindex $args [expr {$at+1}]]; set names {}
    foreach h $handles {
        if {[string match @cell:* $h]} {
            set cell [typed $h cell]
            dict for {p c} $pinCells {if {$c eq $cell} {lappend names $p}}
        } else {
            set net [typed $h net]
            dict for {p n} $conn {
                if {$n eq $net && [dict get $db pin $p DIRECTION] eq [expr {[lindex $args end] eq "DIRECTION == IN" ? "IN" : "OUT"}] && [dict get $db pin $p IS_LEAF]} {lappend names $p}
            }
        }
    }
    return [objects pin [lsort -unique $names]]
}
proc get_nets {args} {
    global conn db netOverrides
    set at [lsearch -exact $args -of_objects]
    if {$at<0} {set name [lindex $args end]; if {![dict exists $db net $name]} {return {}}; return [list [obj net $name]]}
    set names {}; foreach h [lindex $args [expr {$at+1}]] {set p [typed $h pin]; set kind [expr {"-segments" in $args ? "segments" : "direct"}]; if {[dict exists $netOverrides $kind $p]} {lappend names {*}[dict get $netOverrides $kind $p]} elseif {[dict exists $conn $p]} {lappend names [dict get $conn $p]}}
    return [objects net [lsort -unique $names]]
}
proc get_property {key handles} {
    global db clocks
    set values {}
    foreach h $handles {
        if {![regexp {^@(cell|pin|net|clock):(.*)$} $h -> kind name]} {error "untyped property object: $h"}
        if {![dict exists $db $kind $name $key]} {error "missing property $kind $name $key"}
        lappend values [dict get $db $kind $name $key]
    }
    if {[llength $values]==1} {return [lindex $values 0]}
    return $values
}
proc get_clocks {args} {
    global clocks conn
    set at [lsearch -exact $args -of_objects]; set names {}
    foreach h [lindex $args [expr {$at+1}]] {
        set p [typed $h pin]; set n [dict get $conn $p]
        if {[dict exists $clocks $n]} {lappend names [dict get $clocks $n]}
    }
    return [objects clock [lsort -unique $names]]
}
proc ff {name q d ce falling preset reset} {
    add_cell $name [expr {$preset ? "FDPE" : "FDCE"}] [expr {$preset ? "1'b1" : "1'b0"}]
    foreach {p n} [list C pad D $d CE $ce Q $q [expr {$preset ? "PRE" : "CLR"}] $reset] {
        add_pin $name $p $n [expr {$p eq "Q" ? "OUT" : "IN"}] [expr {$p eq "C" ? $falling : 0}]
    }
}
proc lut {name inputs output init} {
    add_cell $name LUT[llength $inputs] $init; set i 0
    foreach n $inputs {add_pin $name I$i $n; incr i}
    add_pin $name O $output OUT
}
proc fixture {t1 selected {merge 0} {dead connected}} {
    global db conn clocks pinCells netOverrides pinOverrides
    set db {}; set conn {}; set clocks {}; set pinCells {}; set netOverrides {}; set pinOverrides {}
    dict set db net power [dict create NAME power TYPE POWER]
    dict set db net ground [dict create NAME ground TYPE GROUND]
    dict set db net deadGround [dict create NAME deadGround TYPE GROUND]
    foreach {c ratio n period fall} {padDivider 2 pad 4 2 rawDivider 4 raw 8 4} {
        add_cell $c BUFGCE_DIV; dict set db cell $c BUFGCE_DIVIDE $ratio
        foreach {p net} [list I ref CE power CLR commonClear O $n] {add_pin $c $p $net [expr {$p eq "O" ? "OUT" : "IN"}]}
        dict set clocks $n ${n}clock
        dict set db clock ${n}clock [dict create NAME ${n}clock PERIOD $period WAVEFORM [list 0 $fall]]
    }
    dict set clocks ref refclock; dict set db clock refclock [dict create NAME refclock PERIOD 2 WAVEFORM {0 1}]
    add_pin u_rgmii tx_clock raw; add_pin u_rgmii tx_pad_clock pad; add_pin u_rgmii tx_pad_reset rawReset
    set reset rawReset
    if {$t1} {set reset localReset; ff u_rgmii/release localReset ground power 1 1 rawReset}
    ff u_rgmii/phase phaseQ phaseNot power 0 1 $reset
    lut u_rgmii/invert {phaseQ} phaseNot 2'h1
    for {set i 0} {$i<6} {incr i} {
        set rise rise$i; set fall fall$i
        if {$merge && $i==4} {
            set fall $rise
            set encoder u_soc/board/nativeBank/gmac/encode
            ff $encoder/upstream $rise ground power 0 0 encoderReset
            dict set conn $encoder/upstream/C raw
            add_pin $encoder clock raw; add_pin $encoder reset encoderReset
            add_pin $encoder {io_rise[4]} $rise
        }
        if {$i<5} {
            add_pin u_rgmii [format {tx_rise[%d]} $i] $rise
            add_pin u_rgmii [format {tx_fall[%d]} $i] [expr {$dead eq "ground" && $i==4 ? "deadGround" : $fall}]
            if {$dead eq "disconnected" && $i==4} {dict unset conn {u_rgmii/tx_fall[4]}}
            set out [expr {$i<4 ? [format {rgmii_tx_data[%d]} $i] : "rgmii_tx_control"}]
        } else {add_pin u_rgmii txc_rise $rise; add_pin u_rgmii txc_fall $fall; set out rgmii_tx_clock}
        set hi high$i
        if {$merge && $i==4} {set hi low$i} else {ff u_rgmii/high$i $hi $fall phaseNot 1 0 $reset}
        if {$selected && !($merge && $i==4)} {
            lut u_rgmii/select$i [list $rise $hi phaseQ] mux$i 8'hCA
            ff u_rgmii/low$i low$i mux$i power 1 0 $reset
        } else {ff u_rgmii/low$i low$i $rise phaseNot 1 0 $reset}
        set symbol low$i
        if {!$selected} {lut u_rgmii/output$i [list low$i $hi phaseQ] symbol$i 8'hCA; set symbol symbol$i}
        set d0 $symbol
        if {$i==5} {ff u_rgmii/previous previousQ $symbol power 0 0 $reset; set d0 previousQ}
        set c u_rgmii/oddr$i; add_cell $c OSERDESE3
        dict set db cell $c ODDR_MODE TRUE; dict set db cell $c OSERDES_D_BYPASS FALSE; dict set db cell $c IS_CLK_INVERTED 0
        foreach {p n} [list CLK pad RST $reset {D[0]} $d0 {D[4]} $symbol OQ out$i] {add_pin $c $p $n [expr {$p eq "OQ" ? "OUT" : "IN"}]}
        add_pin u_rgmii $out out$i
    }
}
