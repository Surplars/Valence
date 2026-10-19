# CommonCpuClockBoundary only. Source after synth_design -flatten_hierarchy none,
# then call common_cdc::constrain. This file never applies global clock groups,
# false paths, reset cuts, or asynchronous payload exceptions.
namespace eval common_cdc { variable scopes {} }
proc common_cdc::quote {s} {return [regsub -all {[][{}().+*?^$|\\]} $s {\\&}]}
proc common_cdc::names {objects} {
    set out {}; foreach o $objects {lappend out [get_property NAME $o]}; return [lsort -unique $out]
}
proc common_cdc::one {command name} {
    set o [$command -quiet -hierarchical -regexp "^[quote $name]$"]
    if {[llength $o] != 1 || [get_property NAME $o] ne $name} {error "COMMON_CDC missing exact object $name"}
    return $o
}
proc common_cdc::objects {command names} {
    set expected [lsort -unique $names]
    if {![llength $expected]} {error "COMMON_CDC empty exact collection"}
    set patterns [lmap name $expected {format {^%s$} [quote $name]}]
    set found [$command -quiet -hierarchical -regexp $patterns]
    if {[names $found] ne $expected} {error "COMMON_CDC exact collection changed: $names"}
    return $found
}
proc common_cdc::bank {prefix width} {
    set pattern "^[quote $prefix]"; append pattern {\[[0-9]+\]$}
    set found [names [get_cells -quiet -hier -regexp $pattern]]
    set expected {}; for {set i 0} {$i<$width} {incr i} {lappend expected [format {%s[%d]} $prefix $i]}
    if {$found ne [lsort $expected]} {error "COMMON_CDC bank shape changed: $prefix expected=$width found=$found"}
    return $expected
}
proc common_cdc::drivers {pin} {
    return [names [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects [one get_pins $pin]] -filter {DIRECTION == OUT}]]
}
proc common_cdc::loads {pin} {
    return [names [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects [one get_pins $pin]] -filter {DIRECTION == IN}]]
}
proc common_cdc::clock {pin} {
    set c [get_clocks -quiet -of_objects [one get_pins $pin]]
    if {[llength $c] != 1} {error "COMMON_CDC missing/ambiguous clock at $pin"}
    return [get_property NAME $c]
}
proc common_cdc::constant {pin value} {
    set nets [get_nets -quiet -segments -of_objects [one get_pins $pin]]
    if {![llength $nets]} {error "COMMON_CDC floating $pin"}
    foreach n $nets {if {[get_property TYPE $n] ne [expr {$value ? "POWER" : "GROUND"}]} {error "COMMON_CDC $pin not constant $value"}}
}
proc common_cdc::same_net {a b} {
    set aa [get_nets -segments -of_objects [one get_pins $a]]
    foreach n [get_nets -segments -of_objects [one get_pins $b]] {if {[lsearch -exact $aa $n]>=0} {return}}
    error "COMMON_CDC nets differ $a $b"
}
proc common_cdc::ff {cell expected_clock {async 0}} {
    set c [one get_cells $cell]
    if {![string match FD* [get_property REF_NAME $c]] || [clock $cell/C] ne $expected_clock} {error "COMMON_CDC non-FF/wrong clock $cell"}
    if {[get_property IS_INVERTED [one get_pins $cell/C]] ni {0 false FALSE}} {error "COMMON_CDC inverted clock $cell"}
    if {$async} {
        if {[get_property ASYNC_REG $c] ni {1 TRUE true}} {error "COMMON_CDC missing ASYNC_REG $cell"}
        constant $cell/CE 1
    }
}
proc common_cdc::pair {first second target_clock} {
    ff $first $target_clock 1; ff $second $target_clock 1
    if {[drivers $second/D] ne [list $first/Q] || [loads $first/Q] ne [list $second/D]} {
        error "COMMON_CDC non-direct stage0 Q->stage1 D or stage0 functional fanout $first"
    }
    foreach c [list $first $second] {
        if {[get_property REF_NAME [one get_cells $c]] ne "FDCE"} {error "COMMON_CDC zero-reset FDCE required $c"}
    }
    same_net $first/CLR $second/CLR
}
proc common_cdc::budget {source target} {
    set a [get_property PERIOD [get_clocks $source]]; set b [get_property PERIOD [get_clocks $target]]
    if {![string is double -strict $a] || ![string is double -strict $b] || $a<=0 || $b<=0} {error "COMMON_CDC invalid clock period"}
    return [expr {min($a,$b)}]
}
proc common_cdc::gray {fifo direction} {
    # Match the actual HeldResponse ABI. Captured credit is NOT readGray.
    lassign [dict get {write {writeGray writeBinary destinationClock sourceClock} captured {capturedGray capturedBinary sourceClock destinationClock}} $direction] gray binary targetPin sourcePin
    set src [clock $fifo/$sourcePin]; set dst [clock $fifo/$targetPin]
    if {$src eq $dst} {error "COMMON_CDC CPU/fabric unexpectedly same domain $fifo"}
    set first [bank $fifo/${gray}Sync_stage0_reg 5]; set second [bank $fifo/${gray}Sync_reg 5]
    set starts {}; set ends {}
    for {set i 0} {$i<5} {incr i} {
        set a [lindex $first $i]; set b [lindex $second $i]; pair $a $b $dst
        set driver [drivers $a/D]
        set allowed [list [format {%s/%s_reg[%d]/Q} $fifo $gray $i]]
        # Vivado can merge binary/Gray MSB, but no other bit may be substituted.
        if {$i==4} {lappend allowed [format {%s/%s_reg[4]/Q} $fifo $binary]}
        if {[llength $driver]!=1 || [lsearch -exact $allowed [lindex $driver 0]]<0} {error "COMMON_CDC wrong Gray bit launch $a: $driver"}
        set launch [get_property NAME [get_cells -of_objects [one get_pins [lindex $driver 0]]]]
        ff $launch $src
        lappend starts $launch/C; lappend ends $a/D
    }
    return [dict create label $fifo/$gray starts $starts ends $ends second $second budget [budget $src $dst] skew 1]
}
proc common_cdc::level {path} {
    set stages [bank $path/stages_reg 2]; lassign $stages first second
    set dst [clock $first/C]; pair $first $second $dst
    set starts {}; set periods [list [get_property PERIOD [get_clocks $dst]]]
    foreach pin [all_fanin -flat -startpoints_only -to [one get_pins $first/D]] {
        set c [get_cells -quiet -of_objects $pin]
        if {[llength $c]!=1 || ![string match FD* [get_property REF_NAME $c]]} {error "COMMON_CDC unknown scalar launch $path: $pin"}
        set name [get_property NAME $c]; lappend starts $name/C
        lappend periods [get_property PERIOD [get_clocks [clock $name/C]]]
    }
    if {![llength $starts]} {error "COMMON_CDC empty scalar launch $path"}
    return [dict create label $path starts [lsort -unique $starts] ends [list $first/D] second [list $second] budget [lindex [lsort -real $periods] 0] skew 0]
}
proc common_cdc::mailbox {h} {
    set src [clock $h/sourceClock]; set dst [clock $h/destinationClock]
    set starts {}; set ends {}; set held [bank $h/held_reg 64]; set captured [bank $h/captured_reg 64]
    foreach a $held b $captured {
        ff $a $src; ff $b $dst
        if {[drivers $b/D] ne [list $a/Q]} {error "COMMON_CDC mailbox payload mapping changed $a $b"}
        lappend starts $a/C; lappend ends $b/D
    }
    return [dict create label $h/held_payload starts $starts ends $ends second {} budget [budget $src $dst] skew 1]
}
proc common_cdc::payload {h} {
    # The emitted SyncReadMem has destination-clock registered read address;
    # its distributed RAM write clocks are real sequential startpoints. Never
    # constrain a composite RAM32M16/WCLK or Q-segment the output path.
    set src [clock $h/sourceClock]; set dst [clock $h/destinationClock]
    set readAddress [bank $h/storage_ext/_R0_addr_d0_reg 4]
    for {set i 0} {$i<4} {incr i} {
        set c [lindex $readAddress $i]; ff $c $dst
        same_net $c/D [format {%s/storage_ext/R0_addr[%d]} $h $i]
    }
    one get_cells $h/pending_reg; bank $h/heldAddress_reg 4
    set bits [get_pins -of_objects [one get_cells $h] -filter {REF_PIN_NAME =~ destination_bits*}]
    if {![llength $bits]} {error "COMMON_PAYLOAD missing destination port $h"}
    set starts {}; set ends {}; set by_end {}; set ordinary_by_end {}; set constant_bits {}
    foreach bit $bits {
        set bn [get_property REF_PIN_NAME $bit]
        if {![regexp {^destination_bits\[([0-9]+)\]$} $bn -> i]} {error "COMMON_PAYLOAD unsupported bit name $bn"}
        set pn [get_property NAME $bit]
        if {![catch {constant $pn 0}] || ![catch {constant $pn 1}]} {lappend constant_bits $i; continue}
        set capture [format {%s/output_0_reg[%d]} $h $i]; ff $capture $dst
        if {[drivers $pn] ne [list $capture/Q]} {error "COMMON_PAYLOAD output is not held matching bit $pn"}
        set end $capture/D; set ramStarts {}; set ordinary {}
        foreach launch [all_fanin -flat -startpoints_only -to [one get_pins $end]] {
            set owner [get_cells -quiet -of_objects $launch]
            if {[llength $owner]!=1} {error "COMMON_PAYLOAD non-cell launch $launch"}
            set ln [get_property NAME $launch]; set cn [get_property NAME $owner]; set ref [get_property REF_NAME $owner]
            if {$ref in {FDRE FDSE FDCE FDPE}} {
                if {$ln ne "$cn/C" || [clock $ln] ne $dst} {error "COMMON_PAYLOAD asynchronous FF/data bypass $ln"}
                lappend ordinary $ln
            } elseif {$ref in {RAMD32 RAMS32 RAMD64E RAMS64E}} {
                if {[string first $h/storage_ext/ $ln]!=0 || [get_property REF_PIN_NAME $launch] ni {CLK WCLK} || [clock $ln] ne $src || [get_property IS_LEAF $launch] ni {1 TRUE true}} {error "COMMON_PAYLOAD unreviewed RAM launch $ln"}
                lappend ramStarts $ln; lappend starts $ln
            } else {error "COMMON_PAYLOAD unsupported mapped RAM/launch $ln ($ref)"}
        }
        if {![llength $ramStarts]} {error "COMMON_PAYLOAD no true RAM storage for $pn"}
        lappend ends $end; dict set by_end $end [lsort -unique $ramStarts]; dict set ordinary_by_end $end [lsort -unique $ordinary]
    }
    if {![llength $ends]} {error "COMMON_PAYLOAD active FIFO has no proved nonconstant storage $h"}
    return [dict create label $h/payload starts [lsort -unique $starts] ends $ends second {} budget [budget $src $dst] skew 1 by_end $by_end ordinary_by_end $ordinary_by_end constant_bits $constant_bits]
}
proc common_cdc::inactive {fifo} {
    # An omitted source port is allowed only on a specialized preserved module
    # whose destination is statically invalid, every data output is zero, and
    # there is no surviving payload/functional state. No live lane is waived.
    set cell [one get_cells $fifo]
    set valid [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == destination_valid}]
    if {[llength $valid]!=1 || [catch {constant [get_property NAME $valid] 0}]} {return 0}
    set source [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == source_valid}]
    if {[llength $source]>1 || ([llength $source] && [catch {constant [get_property NAME $source] 0}])} {return 0}
    set bits [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME =~ destination_bits*}]
    if {![llength $bits]} {return 0}
    foreach bit $bits {if {[catch {constant [get_property NAME $bit] 0}]} {return 0}}
    foreach c [get_cells -quiet -hier -filter {IS_PRIMITIVE == TRUE}] {
        set n [get_property NAME $c]; if {[string first $fifo/ $n]!=0} {continue}
        set ref [get_property REF_NAME $c]
        if {[string match RAM* $ref] || [string match URAM* $ref]} {return 0}
        if {[string match FD* $ref] && ![regexp {/(sourceRelease|destinationRelease)/release_0_reg\[[0-2]\]$} $n]} {return 0}
    }
    return 1
}
proc common_cdc::collect {{root u_soc/crossing}} {
    variable scopes; set scopes {}; one get_cells $root
    set held {}; set levels {}; set mailboxes {}; set unknown {}
    foreach c [get_cells -quiet -hier] {
        set n [get_property NAME $c]; if {[string first $root/ $n]!=0} {continue}
        set ref [get_property REF_NAME $c]
        if {[string match HeldResponseCdcDataFifo* $ref]} {lappend held $n}
        if {[string match CdcLevel* $ref]} {lappend levels $n}
        if {[string match CdcMailbox* $ref]} {lappend mailboxes $n}
        if {[string match CdcDataFifo* $ref]} {lappend unknown $n}
    }
    # Logical source has 3x5 TL + 2 LineGrant + 4 scalar + 2 MSI + 3 maintenance.
    # Missing optimized lanes need explicit tied-off proof, never silent omission.
    if {[llength $held]!=26 || [llength $mailboxes]!=1 || [lindex $mailboxes 0] ne "$root/time_0" || [llength $unknown]} {
        error "COMMON_CDC logical census changed/optimized: Held=[llength $held]/26 mailbox=$mailboxes legacy=$unknown; require reviewed constant-lane proof"
    }
    set ::common_cdc::inactive_scopes {}
    foreach h [lsort $held] {
        if {[inactive $h]} {lappend ::common_cdc::inactive_scopes $h; puts "COMMON_CDC_PROVEN_INACTIVE $h"; continue}
        foreach d {write captured} {lappend scopes [gray $h $d]}
        lappend scopes [payload $h]
    }
    if {![llength $levels]} {error "COMMON_CDC missing scalar synchronizers"}
    foreach h [lsort $levels] {lappend scopes [level $h]}
    lappend scopes [mailbox [lindex $mailboxes 0]]
    # Every retained stage0 bank must be covered, including future new channels.
    set covered {}; foreach s $scopes {foreach p [dict get $s ends] {lappend covered $p}}
    foreach c [get_cells -quiet -hier -filter {ASYNC_REG == TRUE}] {
        set n [get_property NAME $c]
        if {[string first $root/ $n]==0 && [regexp {(Sync_stage0_reg\[[0-9]+\]|stages_reg\[0\])$} $n] && [lsearch -exact $covered $n/D]<0} {
            error "COMMON_CDC unreviewed first-stage endpoint $n"
        }
    }
    return $scopes
}
proc common_cdc::constrain {{root u_soc/crossing}} {
    set scopes [collect $root]
    foreach scope $scopes {
        set starts [objects get_pins [dict get $scope starts]]; set ends [objects get_pins [dict get $scope ends]]
        set b [dict get $scope budget]
        # Clock pins are legal sequential startpoints; no Q-pin path segmentation.
        set_max_delay -datapath_only $b -from $starts -to $ends
        if {[dict get $scope skew]} {set_bus_skew $b -from $starts -to $ends}
        puts "COMMON_CDC_BOUNDED [dict get $scope label] budget=$b"
    }
    return $scopes
}
proc common_cdc::audit_timing {scopes output} {
    set f [open [file join $output common-cdc-scopes.tcllist] w]
    try {
        foreach scope $scopes {
            puts $f $scope
            if {[dict exists $scope by_end]} {
                dict for {end launches} [dict get $scope by_end] {
                    foreach start $launches {
                        set p [get_timing_paths -quiet -from [one get_pins $start] -to [one get_pins $end] -delay_type max -max_paths 1]
                        if {[llength $p]!=1 || [get_property STARTPOINT_PIN $p] ne $start || [get_property ENDPOINT_PIN $p] ne $end} {error "COMMON_PAYLOAD missing exact RAM path $start -> $end"}
                        set req [get_property REQUIREMENT $p]; set slack [get_property SLACK $p]
                        set exception [string tolower [string map {_ {} - {} { } {}} [get_property EXCEPTION $p]]]
                        if {![string is double -strict $req] || ![string is double -strict $slack] || $req<=0 || $req>[dict get $scope budget]+0.001 || $slack<0 || ![string match maxdelay* $exception]} {error "COMMON_PAYLOAD missing/relaxed/failing bound $start -> $end"}
                    }
                    foreach start [dict get $scope ordinary_by_end $end] {
                        foreach kind {max min} {
                            set p [get_timing_paths -quiet -from [one get_pins $start] -to [one get_pins $end] -delay_type $kind -max_paths 1]
                            if {[llength $p]!=1 || ![string is double -strict [get_property SLACK $p]] || [get_property SLACK $p]<0} {error "COMMON_PAYLOAD cut/failing destination $kind path $start -> $end"}
                        }
                    }
                }
            }
            foreach end [dict get $scope ends] {
                set p [get_timing_paths -quiet -from [objects get_pins [dict get $scope starts]] -to [one get_pins $end] -delay_type max -max_paths 1 -nworst 1]
                if {[llength $p]!=1 || [get_property ENDPOINT_PIN $p] ne $end} {error "COMMON_CDC cut/missing exact max-delay path $end"}
                set req [get_property REQUIREMENT $p]; set slack [get_property SLACK $p]
                set exception [string tolower [string map {_ {} - {} { } {}} [get_property EXCEPTION $p]]]
                if {![string is double -strict $req] || ![string is double -strict $slack] || $req<=0 || $req>[dict get $scope budget]+0.001 || $slack<0 || ![string match maxdelay* $exception]} {error "COMMON_CDC missing/relaxed/violating max-delay bound $end requirement=$req slack=$slack exception=$exception"}
            }
            foreach second [dict get $scope second] {
                set firstQ [drivers $second/D]; set first [get_property NAME [get_cells -of_objects [objects get_pins $firstQ]]]
                foreach kind {max min} {
                    set p [get_timing_paths -quiet -from [one get_pins $first/C] -to [one get_pins $second/D] -delay_type $kind -max_paths 1]
                    if {[llength $p]!=1 || ![string is double -strict [get_property SLACK $p]] || [get_property SLACK $p]<0} {error "COMMON_CDC interstage $kind missing/failing $second"}
                }
            }
        }
    } finally {close $f}
    report_bus_skew -delay_type min_max -cells [get_cells u_soc/crossing] -max_paths 1 -nworst 1 -input_pins -warn_on_violation -file [file join $output common-bus-skew.rpt]
}
