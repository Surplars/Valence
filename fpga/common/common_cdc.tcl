# CommonCpuClockBoundary only. Source after synth_design -flatten_hierarchy none,
# then call common_cdc::constrain. This file never applies global clock groups,
# false paths, reset cuts, or asynchronous payload exceptions.
namespace eval common_cdc { variable scopes {} }
source [file join [file dirname [info script]] inactive_zero_state.tcl]
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
proc common_cdc::registered_level_source {path source_clock source_reset} {
    set first [format {%s/stages_reg[0]/D} $path]
    set direct [drivers $first]
    if {[llength $direct]!=1 || ![regexp {^(.*)/Q$} [lindex $direct 0] -> launch]} {
        error "COMMON_CDC idle announcement requires one direct source FF Q: $path"
    }
    ff $launch $source_clock
    set cell [one get_cells $launch]
    if {[get_property REF_NAME $cell] ne "FDCE" || [get_property INIT $cell] ni {0 1'b0}} {
        error "COMMON_CDC idle announcement must be a reset-low source FF: $path"
    }
    constant $launch/CE 1
    same_net $launch/CLR $source_reset
    if {[loads $launch/Q] ne [list $first]} {
        error "COMMON_CDC idle source Q must feed only its first synchronizer stage: $path"
    }
    puts "COMMON_EMPTY_SOURCE_REGISTERED $path launch=$launch clock=$source_clock NO_CDC_WAIVER"
}
proc common_cdc::exported_idle_source {root name source_clock source_reset} {
    set path $root/${name}_crossing
    set instance [get_cells -quiet $path]
    if {![llength $instance]} {
        set children [get_cells -quiet -hier -filter "NAME =~ $path/*"]
        set port [get_pins -quiet -of_objects [one get_cells $root] -filter "REF_PIN_NAME == $name"]
        if {[llength $children] || [llength $port]} {
            error "COMMON_CDC idle synchronizer absent but export/state retained: $path"
        }
        puts "COMMON_EMPTY_EXPORT_PRUNED no_port_no_state=$path"
        return 0
    }
    if {[llength $instance]!=1} {error "COMMON_CDC ambiguous idle synchronizer $path"}
    registered_level_source $path $source_clock $source_reset
    return 1
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
proc common_cdc::payload_absent {h} {
    # Valid-only specialization: pointer/handshake state remains active and its
    # Gray constraints are still mandatory. Only an entirely absent data ABI and
    # storage, with a complete local control-state census, remove payload scopes.
    set cell [one get_cells $h]
    if {![string match HeldResponseCdcDataFifo* [get_property REF_NAME $cell]]} {return 0}
    set destination_bits [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME =~ destination_bits*}]
    foreach bit $destination_bits {
        set nets [get_nets -quiet -segments -of_objects $bit]
        if {![llength $nets]} {continue}
        if {[catch {constant [get_property NAME $bit] 0}] && [catch {constant [get_property NAME $bit] 1}]} {return 0}
    }
    set source_bits [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME =~ source_bits*}]
    if {[llength $source_bits]} {
        set dynamic {}
        foreach n [get_nets -quiet -segments -of_objects $source_bits] {
            if {[get_property TYPE $n] ni {GROUND POWER}} {lappend dynamic $n}
        }
        if {[llength $dynamic] && [llength [get_pins -quiet -leaf -of_objects $dynamic -filter "DIRECTION == IN && NAME =~ $h/*"]]} {return 0}
    }
    set src [clock $h/sourceClock];set dst [clock $h/destinationClock];set count 0
    foreach c [get_cells -quiet -hier -filter "IS_PRIMITIVE == TRUE && NAME =~ $h/*"] {
        set name [get_property NAME $c];set ref [get_property REF_NAME $c]
        if {[regexp {/(sourceRelease|destinationRelease)/release_0_reg\[[0-2]\]$} $name]} {
            if {$ref ne {FDPE}} {return 0}
            continue
        }
        if {$ref eq {FDCE}} {
            set tail [string range $name [expr {[string length $h]+1}] end]
            if {![regexp {^(writeBinary|writeGray|capturedBinary|capturedGray|capturedGraySync(_stage0)?|writeGraySync(_stage0)?|issueBinary|heldAddress)_reg\[[0-4]\]$|^(pending|valid|full)_reg$} $tail]} {return 0}
            set expected $dst
            if {[regexp {^(writeBinary|writeGray|capturedGraySync(_stage0)?|full)_reg} $tail]} {set expected $src}
            ff $name $expected
            if {[get_property INIT $c] ne {1'b0}} {return 0}
            incr count
        } elseif {$ref ni {GND VCC CARRY4 CARRY8 MUXF7 MUXF8 MUXF9} && ![regexp {^LUT[1-6]$} $ref]} {return 0}
    }
    if {!$count} {return 0}
    puts "COMMON_PAYLOAD_ABSENT_PROVED fifo=$h no_live_source_data_load=1 no_observable_destination_data=1 no_payload_storage=1 control_ff=$count GRAY_SCOPES_STILL_REQUIRED"
    return 1
}
proc common_cdc::captured_constant {capture destination_clock ram_capture} {
    # A locally latched literal is not an asynchronous RAM data launch. Keep its
    # clock/CE timing ordinary; require the same capture event as proved RAM data.
    ff $capture $destination_clock
    set value -1
    foreach bit {0 1} {if {![catch {constant $capture/D $bit}]} {set value $bit;break}}
    if {$value<0} {error "COMMON_PAYLOAD unproved non-RAM data source $capture"}
    same_net $capture/CE $ram_capture/CE
    puts "COMMON_PAYLOAD_LOCAL_CONSTANT capture=$capture literal_D=$value clock=$destination_clock CE_matches=$ram_capture NO_TIMING_EXCEPTION"
    return $value
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
    set starts {}; set ends {}; set by_end {}; set ordinary_by_end {}; set constant_bits {};set unused_bits {};set local_constants {}
    foreach bit $bits {
        set bn [get_property REF_PIN_NAME $bit]
        if {$bn eq {destination_bits} && [llength $bits]==1} {set i 0
        } elseif {![regexp {^destination_bits\[([0-9]+)\]$} $bn -> i]} {error "COMMON_PAYLOAD unsupported bit name $bn"}
        set pn [get_property NAME $bit]
        if {![llength [get_nets -quiet -segments -of_objects $bit]]} {lappend unused_bits $i;continue}
        if {![catch {constant $pn 0}] || ![catch {constant $pn 1}]} {lappend constant_bits $i; continue}
        set driver [drivers $pn]
        if {[llength $driver]!=1 || ![regexp {^(.*)/Q$} [lindex $driver 0] -> capture] || [string first $h/output_0_reg $capture]!=0} {error "COMMON_PAYLOAD missing owned output FF driver $pn: $driver"}
        ff $capture $dst
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
        if {![llength $ramStarts]} {
            # This is only accepted below after literal D and matching real-data
            # capture CE are proved. A missing RAM never skips dynamic data.
            lappend local_constants [list $i $capture]
            continue
        }
        lappend ends $end; dict set by_end $end [lsort -unique $ramStarts]; dict set ordinary_by_end $end [lsort -unique $ordinary]
    }
    if {![llength $ends]} {error "COMMON_PAYLOAD active FIFO has no proved nonconstant storage $h"}
    set reference [file dirname [lindex $ends 0]]
    foreach row $local_constants {
        lassign $row i capture
        captured_constant $capture $dst $reference
    }
    puts "COMMON_PAYLOAD_ACTUAL_OUTPUTS fifo=$h asynchronous_capture_count=[llength [lsort -unique $ends]] unconnected_bits=[llength $unused_bits] constant_bits=[llength $constant_bits]"
    return [dict create label $h/payload starts [lsort -unique $starts] ends [lsort -unique $ends] second {} budget [budget $src $dst] skew 1 by_end $by_end ordinary_by_end $ordinary_by_end constant_bits $constant_bits unused_bits $unused_bits local_constants $local_constants]
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
    set failures {}
    foreach h [lsort $held] {
        if {[catch {
            if {[inactive $h] || [common_zero::prove $h]} {
                lappend ::common_cdc::inactive_scopes $h;puts "COMMON_CDC_PROVEN_INACTIVE $h"
            } else {
                foreach d {write captured} {lappend scopes [gray $h $d]}
                if {![payload_absent $h]} {lappend scopes [payload $h]}
            }
        } reason]} {lappend failures [list lane $h reason $reason];puts "COMMON_CDC_LANE_BLOCKED $h $reason"}
    }
    if {[llength $failures]} {error "COMMON_CDC incomplete lane mappings: $failures"}
    if {![llength $levels]} {error "COMMON_CDC missing scalar synchronizers"}
    foreach h [lsort $levels] {lappend scopes [level $h]}
    exported_idle_source $root cpuEmptyInFabric [clock $root/cpuClock] $root/cpuRelease/resetOut
    exported_idle_source $root fabricEmptyInCpu [clock $root/fabricClock] $root/fabricRelease/resetOut
    lappend scopes [mailbox [lindex $mailboxes 0]]
    # Every retained stage0 bank must be covered, including future new channels.
    set covered {}; foreach s $scopes {foreach p [dict get $s ends] {lappend covered $p}}
    set ::common_cdc::constant_stage0_endpoints {}
    foreach c [get_cells -quiet -hier -filter {ASYNC_REG == TRUE}] {
        set n [get_property NAME $c]
        if {[string first $root/ $n]==0 && [regexp {(Sync_stage0_reg\[[0-9]+\]|stages_reg\[0\])$} $n] && [lsearch -exact $covered $n/D]<0} {
            set constant_scope 0
            foreach h $::common_cdc::inactive_scopes {if {[string first $h/ $n]==0} {set constant_scope 1;break}}
            if {$constant_scope} {lappend ::common_cdc::constant_stage0_endpoints $n/D;continue}
            error "COMMON_CDC unreviewed first-stage endpoint $n"
        }
    }
    puts "COMMON_CDC_CONSTANT_STAGE0_PROOF_COVERAGE endpoints=[llength $::common_cdc::constant_stage0_endpoints] NO_TRANSITIONS_NO_EXCEPTION"
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
