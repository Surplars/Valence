# Finite native-object model: guard/transaction tests only, not physical legality.
set helper [file join [file dirname [info script]] dynamic tx_reset_placement.tcl]
source $helper
namespace eval m {}
proc m::obj {n args} {dict set ::m::db $n [dict merge [dict create NAME $n] $args]}
proc m::link {p net dir {ref {}}} {
    m::obj $p DIRECTION $dir REF_PIN_NAME [expr {$ref eq "" ? [file tail $p] : $ref}] IS_INVERTED 0
    dict set ::m::pn $p $net; dict lappend ::m::np $net $p
}
proc m::init {} {
    set ::r38_tx_place::attempted 0
    set ::m::db {}; set ::m::pn {}; set ::m::np {}; set ::m::cells {}; set ::m::calls 0; set ::m::fault {}
    m::obj design PART xczu15eg-ffvb1156-2-i
    m::obj cpu_target300 PERIOD 3.333333333333; m::obj fabric_target250 PERIOD 4.0
    foreach {n type driver primitive} {
        raw SIGNAL network_clock/raw_div/O BUFGCE_DIV
        pad SIGNAL network_clock/quarter_div/O BUFGCE_DIV
        pwr POWER tx_release/VCC/P VCC
        gnd GROUND tx_release/GND/G GND
        inhibit SIGNAL tx_release_i_1/O LUT2
        q0 SIGNAL {tx_release/tx_reset_pipe_reg[0]/Q} FDPE
        q1 SIGNAL {tx_release/tx_reset_pipe_reg[1]/Q} FDPE
        q2 SIGNAL {tx_release/tx_reset_pipe_reg[2]/Q} FDPE
    } {
        m::obj $n TYPE $type CLOCK_ROOT X3Y3 USER_CLOCK_ROOT {} CLOCK_DELAY_GROUP {}
        m::obj [file dirname $driver] REF_NAME $primitive
        m::link $driver $n OUT
    }
    foreach {b net period wave div} {raw_div raw 8.000 {0.000 4.000} 4 quarter_div pad 4.000 {0.000 2.000} 2} {
        m::obj network_clock/$b REF_NAME BUFGCE_DIV LOC BUFGCE_DIV_X0Y12 BEL BUFGCE_DIV.BUFGCE_DIV BUFGCE_DIVIDE $div
        m::obj valence_tx_$b PERIOD $period WAVEFORM $wave MASTER_CLOCK ref_source SOURCE_PINS network_clock/$b/O
    }
    for {set i 0} {$i<3} {incr i} {
        set n [format {tx_release/tx_reset_pipe_reg[%d]} $i]; lappend ::m::cells $n
        m::obj $n REF_NAME FDPE INIT 1'b1 ASYNC_REG 1 DONT_TOUCH {} LOC SLICE_X116Y132 BEL SLICEM.[lindex {HFF2 EFF2 FFF2} $i]
        foreach {r net} [list C raw CE pwr PRE inhibit D [lindex {gnd q0 q1} $i]] {m::link $n/$r $net IN}
    }
    for {set i 0} {$i<3} {incr i} {m::link [format {rx_reset_pipe_reg[%d]/PRE} $i] inhibit IN}
    foreach p [r38_tx_place::wanted_loads] {
        set n [file dirname $p]; set r [file tail $p]
        set ref [expr {$r eq "RST" ? "OSERDESE3" : ($r eq "PRE" ? "FDPE" : "FDCE")}]
        m::obj $n REF_NAME $ref INIT 1'b0 ASYNC_REG {} DONT_TOUCH {} LOC SLICE_X106Y230 BEL SLICEL.AFF
        m::link $p q2 IN
        m::link $n/[expr {$r eq "RST" ? "CLK" : "C"}] pad IN
    }
    foreach b {EFF2 FFF2 GFF2} {m::obj SLICE_X106Y229/$b IS_OCCUPIED 0}
}
proc m::arg {xs k} {return [lindex $xs [expr {[lsearch -exact $xs $k]+1}]]}
proc current_design {} {return design}
proc get_property {k xs} {set v {}; foreach x $xs {lappend v [dict get $::m::db $x $k]}; if {[llength $v]==1} {return [lindex $v 0]}; return $v}
proc get_cells {args} {
    if {[lsearch -exact $args -of_objects]>=0} {return [file dirname [m::arg $args -of_objects]]}
    set f [m::arg $args -filter]
    if {[string match {* =~ *} $f]} {return $::m::cells}
    regexp {^NAME == "(.*)"$} $f -> n
    if {[dict exists $::m::db $n]} {return [list $n]}; return {}
}
proc get_pins {args} {
    set out {}; set filter [m::arg $args -filter]; lassign $filter key op val
    foreach x [m::arg $args -of_objects] {
        if {[dict exists $::m::np $x]} {set ps [dict get $::m::np $x]} else {
            set ps {}; dict for {p net} $::m::pn {if {[file dirname $p] eq $x} {lappend ps $p}}
        }
        foreach p $ps {if {[dict get $::m::db $p $key] eq $val} {lappend out $p}}
    }; return [lsort -unique $out]
}
proc get_nets {args} {set ns {}; foreach p [m::arg $args -of_objects] {if {[dict exists $::m::pn $p]} {lappend ns [dict get $::m::pn $p]}}; return [lsort -unique $ns]}
proc get_clocks {args} {
    if {[lsearch -exact $args -of_objects]<0} {return [lindex $args end]}
    set net [dict get $::m::pn [lindex [m::arg $args -of_objects] 0]]
    return [expr {$net eq "raw" ? "valence_tx_raw_div" : "valence_tx_quarter_div"}]
}
proc get_bels {args} {return [lindex $args end]}
proc place_cell {mapping} {
    incr ::m::calls
    foreach {n place} $mapping {
        dict set ::m::db $n LOC [file dirname $place]; dict set ::m::db $n BEL SLICEM.[file tail $place]
        if {$::m::fault eq "partial"} {error "native place legality failed"}
    }
    if {$::m::fault eq "root"} {dict set ::m::db raw CLOCK_ROOT X9Y9}
    if {$::m::fault eq "sink"} {dict set ::m::db u_rgmii/high_clock_reg LOC SLICE_X0Y0}
}
proc test {name mutation expected {during {}}} {
    m::init; uplevel #0 $mutation; set ::m::fault $during
    set dir /tmp/r38-tx-[pid]-$name
    set code [catch {r38_tx_place::apply $dir} result opts]
    if {$expected eq "PASS"} {if {$code} {return -options $opts $result}; if {$::m::calls!=1} {error "wrong call count"}} else {
        if {!$code || ![string match *$expected* $result]} {error "$name wrong result: $result"}
        if {$during eq "" && $::m::calls!=0} {error "premature mutation"}
    }
    if {$::m::calls} {
        source $::helper
        if {![catch {r38_tx_place::apply ${dir}-again} e] || ![string match *one-shot* $e]} {error "retry permitted"}
    }
    if {[file exists $dir]} {file delete -force $dir}
    puts "PASS $name"
}
set s {tx_release/tx_reset_pipe_reg[1]}
test normal {} PASS
test missing {set ::m::cells [lrange $::m::cells 1 end]} census
test init {dict set ::m::db $s INIT 1'b0} FF/INIT
test async {dict set ::m::db $s ASYNC_REG 0} FF/INIT
test protected {dict set ::m::db $s DONT_TOUCH 1} FF/INIT
test polarity {dict set ::m::db $s/PRE IS_INVERTED 1} polarity
test wrong_clock {dict set ::m::pn $s/C pad} RAW125
test early {dict set ::m::pn $s/D q1} {chain D}
test hiddenload {m::link other/CLR q2 IN} {Q fanout}
test wrong_sink {dict set ::m::db u_rgmii/high_clock_reg REF_NAME LUT1} primitive
test wrong_location {dict set ::m::db $s LOC SLICE_X0Y0} placement
test wrong_target {dict set ::m::db cpu_target300 PERIOD 20} target
test bad_constant {dict set ::m::db gnd TYPE SIGNAL} constant
test busy {dict set ::m::db SLICE_X106Y229/FFF2 IS_OCCUPIED 1} occupied
test bad_divide {dict set ::m::db network_clock/raw_div BUFGCE_DIVIDE 2} geometry
test partial {} {native place legality} partial
test moved_root {} {altered logic} root
test moved_sink {} {altered logic} sink
puts {PASS finite placement guard suite: 1 positive + 17 negative; not native legality/STA}

set f [open [file join [file dirname [info script]] dynamic route_tx_reset_placement.tcl]]; set source [read $f]; close $f
set first [string first {proc tx_oserdes_status} $source]
set last [string first {if {$argc!=3}} $source]
eval [string range $source $first [expr {$last-1}]]
proc list_property {p} {return [dict keys [dict get $::m::db $p]]}
set ::m::db {}
foreach {name slack req expected violation} {positive 0.2 4.0 1 0 negative -0.1 4.0 1 1 inf Inf 4.0 0 0 neginf -Inf 4.0 0 0 empty {} {} 0 0 unknown <absent> 4 0 0 badreq 1 Inf 0 0 nan NaN 4 0 0} {
 dict set ::m::db $name [dict create SLACK $slack REQUIREMENT $req STARTPOINT_PIN launch/C ENDPOINT_PIN oserdes/RST STARTPOINT_CLOCK raw ENDPOINT_CLOCK pad EXCEPTION {}]
 set r [lindex [dict get [tx_oserdes_status [list $name]] records] 0]
 if {[dict get $r finite]!=$expected || [dict get $r finite_violation]!=$violation || [dict get $r qualified]} {error "bad $name"}
 puts "PASS OSERDES $name"
}
dict set ::m::db missing [dict create SLACK Inf]
if {[dict get [lindex [dict get [tx_oserdes_status missing] records] 0] finite]} {error missing}
if {[dict get [tx_oserdes_status {}] count]!=0} {error empty_collection}
puts {PASS OSERDES missing-property and empty-collection; all remain unqualified}
