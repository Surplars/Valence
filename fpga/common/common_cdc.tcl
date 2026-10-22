# CommonCpuClockBoundary plus explicitly selected boot50-static boundaries. Source after synth_design -flatten_hierarchy none,
# then call common_cdc::constrain. This file never applies global clock groups,
# false paths, reset cuts, or asynchronous payload exceptions.
namespace eval common_cdc { variable scopes {} }
if {[info exists ::valence(root)]} {
    # Tool overlays retain the original frozen inactive-state proof dependency.
    source [file join $::valence(root) fpga common inactive_zero_state.tcl]
} else {
    source [file join [file dirname [info script]] inactive_zero_state.tcl]
}
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
proc common_cdc::gray {fifo direction {inactive_payload 0}} {
    # Match the actual HeldResponse ABI. Captured credit is NOT readGray.
    lassign [dict get {write {writeGray writeBinary destinationClock sourceClock} captured {capturedGray capturedBinary sourceClock destinationClock}} $direction] gray binary targetPin sourcePin
    set src [clock $fifo/$sourcePin]; set dst [clock $fifo/$targetPin]
    if {$src eq $dst} {error "COMMON_CDC CPU/fabric unexpectedly same domain $fifo"}
    set first [bank $fifo/${gray}Sync_stage0_reg 5]; set second [bank $fifo/${gray}Sync_reg 5]
    set starts {}; set ends {}
    for {set i 0} {$i<5} {incr i} {
        set a [lindex $first $i]; set b [lindex $second $i]; pair $a $b $dst
        if {$inactive_payload && ![catch {constant $a/D 0}]} {
            foreach c [list $a $b] {
                if {[get_property INIT [one get_cells $c]] ni {0 1'b0}} {
                    error "COMMON_CDC constant Gray stage lacks zero INIT $c"
                }
            }
            lappend ::common_cdc::constant_stage0_endpoints $a/D
            puts "COMMON_CDC_LITERAL_ZERO_GRAY $a/D INIT_ZERO_FDCE_PAIR NO_TRANSITIONS_NO_EXCEPTION"
            continue
        }
        set driver [drivers $a/D]
        set allowed [list [format {%s/%s_reg[%d]/Q} $fifo $gray $i]]
        # Vivado can merge binary/Gray MSB, but no other bit may be substituted.
        if {$i==4} {lappend allowed [format {%s/%s_reg[4]/Q} $fifo $binary]}
        if {[llength $driver]!=1 || [lsearch -exact $allowed [lindex $driver 0]]<0} {error "COMMON_CDC wrong Gray bit launch $a: $driver"}
        set launch [get_property NAME [get_cells -of_objects [one get_pins [lindex $driver 0]]]]
        ff $launch $src
        lappend starts $launch/C; lappend ends $a/D
    }
    if {![llength $starts]} {return {}}
    return [dict create label $fifo/$gray starts $starts ends $ends second $second budget [budget $src $dst] skew 1]
}
proc common_cdc::inactive_gray {fifo direction} {
    # Payload inactivity does not remove physical Gray paths from STA. Only an
    # absent receiver bank (both stages) or a proved literal-zero FDCE pair can
    # omit a path. Retained register-driven Gray bits keep the ordinary budget.
    set stem [dict get {write writeGray captured capturedGray} $direction]
    set pattern [format {^%s/%sSync(_stage0)?_reg(\[[0-9]+\])?$} [quote $fifo] $stem]
    set receivers [get_cells -quiet -hierarchical -regexp $pattern]
    if {![llength $receivers]} {
        # Absence of expected names cannot hide renamed/replicated receiver FFs.
        # The caller already proved inactive payload/state; additionally require
        # every surviving sequential cell to belong to the known control ABI.
        foreach c [get_cells -quiet -hier -filter "IS_PRIMITIVE == TRUE && NAME =~ $fifo/*"] {
            set name [get_property NAME $c];set ref [get_property REF_NAME $c]
            if {![string match FD* $ref]} {continue}
            if {[regexp {/(sourceRelease|destinationRelease)/release_0_reg\[[0-2]\]$} $name]} {continue}
            set tail [string range $name [expr {[string length $fifo]+1}] end]
            if {![regexp {^(writeBinary|writeGray|capturedBinary|capturedGray|capturedGraySync(_stage0)?|writeGraySync(_stage0)?|issueBinary|heldAddress)_reg\[[0-4]\]$|^(pending|valid|full)_reg$} $tail]} {
                error "COMMON_CDC unknown retained state prevents Gray absence proof $name"
            }
        }
        puts "COMMON_CDC_INACTIVE_GRAY_RECEIVERS_ABSENT $fifo/$stem NO_PHYSICAL_ENDPOINTS_NO_EXCEPTION"
        return {}
    }
    # gray enforces the entire exact five-bit/two-stage shape. A partial or
    # renamed physical bank is not accepted as optimized-away constant state.
    return [gray $fifo $direction 1]
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
proc common_cdc::constant_zero_level {path} {
    # A literal zero with two INIT=0, clear-to-zero destination FFs cannot
    # transition, even when reset release is arbitrary. No timing exception.
    set stages [bank $path/stages_reg 2];lassign $stages first second
    if {[catch {constant $first/D 0}]} {return 0}
    set dst [clock $first/C];pair $first $second $dst
    foreach c $stages {
        if {[get_property INIT [one get_cells $c]] ni {0 1'b0}} {
            error "COMMON_CDC constant-zero scalar has nonzero/unknown INIT: $c"
        }
    }
    puts "COMMON_CDC_CONSTANT_ZERO_LEVEL $path clock=$dst INIT=0 FDCE_clear_zero=1 NO_TRANSITIONS_NO_EXCEPTION"
    return 1
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
    if {$root eq {u_soc/crossing} && [info exists ::valence(clock_profile)] &&
        $::valence(clock_profile) eq {boot50-dynamic}} {
        # Exact dynamic source adds maintenanceResume (fifo_11) and
        # maintenanceResumed (fifo_12), both 8-bit HeldResponse lanes.
        # Missing/pruned modules still fail; inspect the saved raw DCP first.
        if {[llength $held]!=28 || [llength $mailboxes]!=1 || [lindex $mailboxes 0] ne "$root/time_0" || [llength $unknown]} {
            error "COMMON_CDC dynamic census changed/optimized: Held=[llength $held]/28 mailbox=$mailboxes legacy=$unknown; inspect same raw DCP"
        }
        foreach name {fifo_11 fifo_12} {
            if {[lsearch -exact $held $root/$name]<0} {error "COMMON_CDC missing dynamic maintenance lane $root/$name"}
        }
    } elseif {[llength $held]!=26 || [llength $mailboxes]!=1 || [lindex $mailboxes 0] ne "$root/time_0" || [llength $unknown]} {
        error "COMMON_CDC logical census changed/optimized: Held=[llength $held]/26 mailbox=$mailboxes legacy=$unknown; require reviewed constant-lane proof"
    }
    set ::common_cdc::inactive_scopes {}
    set ::common_cdc::constant_stage0_endpoints {}
    set failures {}
    foreach h [lsort $held] {
        if {[catch {
            if {$root eq {u_soc/crossing} && [info exists ::valence(clock_profile)] &&
                $::valence(clock_profile) eq {boot50-dynamic} && $h in [list $root/fifo_11 $root/fifo_12]} {
                set source [clock $root/fabricClock]; set destination [clock $root/cpuClock]
                if {$h eq "$root/fifo_12"} {set swap $source; set source $destination; set destination $swap}
                expect_clock $h/sourceClock $source; expect_clock $h/destinationClock $destination
                same_net $h/commonReset $root/commonColdReset
                foreach d {write captured} {lappend scopes [gray $h $d]}
                lappend scopes [payload $h]
            } elseif {[inactive $h] || [common_zero::prove $h]} {
                lappend ::common_cdc::inactive_scopes $h;puts "COMMON_CDC_PROVEN_INACTIVE_PAYLOAD $h"
                foreach d {write captured} {
                    set scope [inactive_gray $h $d]
                    if {$scope ne {}} {lappend scopes $scope}
                }
            } else {
                foreach d {write captured} {lappend scopes [gray $h $d]}
                if {![payload_absent $h]} {lappend scopes [payload $h]}
            }
        } reason]} {lappend failures [list lane $h reason $reason];puts "COMMON_CDC_LANE_BLOCKED $h $reason"}
    }
    if {![llength $levels]} {error "COMMON_CDC missing scalar synchronizers"}
    foreach h [lsort $levels] {
        if {[catch {level $h} result]} {
            set original $result
            if {[catch {constant_zero_level $h} inactive_result]} {
                set result "$original; constant proof: $inactive_result"
            } elseif {$inactive_result} {
                lappend ::common_cdc::inactive_scopes $h
                lappend ::common_cdc::constant_stage0_endpoints [format {%s/stages_reg[0]/D} $h]
                continue
            }
            lappend failures [list scalar $h reason $result]
            puts "COMMON_CDC_SCALAR_BLOCKED $h $result"
        } else {lappend scopes $result}
    }
    if {[llength $failures]} {error "COMMON_CDC incomplete lane/scalar mappings: $failures"}
    exported_idle_source $root cpuEmptyInFabric [clock $root/cpuClock] $root/cpuRelease/resetOut
    exported_idle_source $root fabricEmptyInCpu [clock $root/fabricClock] $root/fabricRelease/resetOut
    lappend scopes [mailbox [lindex $mailboxes 0]]
    # Every retained stage0 bank must be covered, including future new channels.
    set covered {}; foreach s $scopes {foreach p [dict get $s ends] {lappend covered $p}}
    foreach c [get_cells -quiet -hier -filter {ASYNC_REG == TRUE}] {
        set n [get_property NAME $c]
        if {[string first $root/ $n]==0 && [regexp {(Sync_stage0_reg\[[0-9]+\]|stages_reg\[0\])$} $n] && [lsearch -exact $covered $n/D]<0} {
            if {[lsearch -exact $::common_cdc::constant_stage0_endpoints $n/D]>=0} {continue}
            error "COMMON_CDC unreviewed first-stage endpoint $n"
        }
    }
    puts "COMMON_CDC_CONSTANT_STAGE0_PROOF_COVERAGE endpoints=[llength $::common_cdc::constant_stage0_endpoints] NO_TRANSITIONS_NO_EXCEPTION"
    if {$root eq {u_soc/crossing}} {
        set profile production
        if {[info exists ::valence(clock_profile)]} {set profile $::valence(clock_profile)}
        if {$profile ni {production boot50-static performance300-static boot50-dynamic}} {error "COMMON_CDC unreviewed clock profile $profile"}
        if {$profile in {boot50-static performance300-static boot50-dynamic}} {
            lappend scopes {*}[collect_static u_soc u_soc/fixedTimer u_soc/debugCrossing $profile]
        } elseif {[llength [get_pins -quiet u_soc/ddrClock]] || [llength [get_cells -quiet u_soc/ddrCrossing]]} {
            error "COMMON_CDC independent DDR boundary requires explicit static topology profile"
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
    if {[info exists ::valence(clock_profile)] && $::valence(clock_profile) eq {boot50-dynamic}} {
        variable dynamic_roots
        if {![info exists dynamic_roots] || ![llength $dynamic_roots]} {error "COMMON_CDC dynamic scopes were not collected"}
        report_bus_skew -delay_type min_max -cells [objects get_cells [concat u_soc/crossing $dynamic_roots]] -max_paths 1 -nworst 1 -input_pins -warn_on_violation -file [file join $output common-bus-skew.rpt]
    } else {
    report_bus_skew -delay_type min_max -cells [get_cells [expr {[info exists ::valence(clock_profile)] && $::valence(clock_profile) in {boot50-static performance300-static boot50-dynamic} ? {u_soc/crossing u_soc/ddrCrossing u_soc/fixedTimer u_soc/debugCrossing} : {u_soc/crossing}}]] -max_paths 1 -nworst 1 -input_pins -warn_on_violation -file [file join $output common-bus-skew.rpt]
    }
}

# Additional opt-in static boot boundary map. This is a fail-closed mapped-netlist
# contract, not a waiver and not evidence that a native implementation has passed.
proc common_cdc::expect_clock {pin expected {period {}}} {
    set actual [clock $pin]
    if {$actual ne $expected} {error "COMMON_CDC incorrect clock at $pin: $actual expected $expected"}
    if {$period ne {}} {
        set p [get_property PERIOD [get_clocks $actual]]
        if {![string is double -strict $p] || abs($p-$period)>0.002} {
            error "COMMON_CDC incorrect clock period at $pin: $p expected $period"
        }
    }
}
proc common_cdc::exact_modules {root ref expected} {
    set actual {}
    foreach c [get_cells -quiet -hier -filter "NAME =~ $root/*"] {
        if {[string match $ref [get_property REF_NAME $c]]} {lappend actual [get_property NAME $c]}
    }
    if {[lsort $actual] ne [lsort $expected]} {
        error "COMMON_CDC exact module census changed under $root ($ref): $actual expected $expected"
    }
}
proc common_cdc::mailbox_width {h width source destination} {
    if {$width==1} {
        # Emitted CdcMailbox(1) has scalar ports and scalar held/captured FFs.
        # Do not reinterpret a missing vector bank or a pruned payload as safe.
        expect_clock $h/sourceClock $source; expect_clock $h/destinationClock $destination
        one get_pins $h/source_bits; one get_pins $h/destination_bits
        set held [names [get_cells -quiet -hier -regexp [format {^%s/held_reg(\[[0-9]+\])?$} [quote $h]]]]
        set captured [names [get_cells -quiet -hier -regexp [format {^%s/captured_reg(\[[0-9]+\])?$} [quote $h]]]]
        if {$held ne [list $h/held_reg] || $captured ne [list $h/captured_reg]} {
            error "COMMON_CDC scalar mailbox exact bank changed/pruned $h; inspect same raw DCP"
        }
        ff $h/held_reg $source; ff $h/captured_reg $destination
        if {[drivers $h/captured_reg/D] ne [list $h/held_reg/Q] ||
            [drivers $h/destination_bits] ne [list $h/captured_reg/Q]} {
            error "COMMON_CDC scalar mailbox payload bypass $h"
        }
        return [dict create label $h/held_payload starts [list $h/held_reg/C] ends [list $h/captured_reg/D] second {} budget [budget $source $destination] skew 0]
    }
    expect_clock $h/sourceClock $source; expect_clock $h/destinationClock $destination
    set starts {};set ends {};set constants {};set captures {}
    for {set i 0} {$i<$width} {incr i} {
        # A constant output bit may lose both registers in optimization. Prove
        # that exact exported bit is literal, never infer it from a missing FF.
        set output [format {%s/destination_bits[%d]} $h $i]
        one get_pins $output
        if {![catch {constant $output 0}] || ![catch {constant $output 1}]} {
            lappend constants $i;continue
        }
        set a [format {%s/held_reg[%d]} $h $i]
        set b [format {%s/captured_reg[%d]} $h $i]
        ff $a $source;ff $b $destination
        if {[drivers $b/D] ne [list $a/Q] || [drivers $output] ne [list $b/Q]} {
            error "COMMON_CDC mailbox payload mapping changed $a $b"
        }
        lappend starts $a/C;lappend ends $b/D;lappend captures $b
    }
    if {![llength $ends]} {error "COMMON_CDC mailbox has no proved dynamic payload $h"}
    # Retained capture state must be accounted for as dynamic or locally literal.
    foreach c [get_cells -quiet -hier -regexp [format {^%s/captured_reg\[[0-9]+\]$} [quote $h]]] {
        set name [get_property NAME $c]
        if {[lsearch -exact $captures $name]>=0} {continue}
        ff $name $destination
        if {[catch {constant $name/D 0}] && [catch {constant $name/D 1}]} {
            error "COMMON_CDC unaccounted mailbox capture $name"
        }
    }
    puts "COMMON_CDC_MAILBOX_ACTUAL_BITS $h dynamic=[llength $ends] literal_output_bits=$constants"
    return [dict create label $h/held_payload starts $starts ends $ends second {} budget [budget $source $destination] skew 1]
}
proc common_cdc::register_payload {h from to fields source destination} {
    # The timer consumes only a subset of address/size bits. Enumerate the exact
    # retained capture ABI, not a guessed full bank; all retained dynamic capture
    # bits must have their matching held source bit, with no combinational bypass.
    set captures {};set starts {};set ends {}
    foreach c [get_cells -quiet -hier -filter "NAME =~ $h/${to}_*_reg*"] {
        set name [get_property NAME $c]
        set pattern [format {^%s_([a-zA-Z]+)_reg(\[([0-9]+)\])?$} [quote $h/$to]]
        if {![regexp $pattern $name -> field suffix index]} {
            error "COMMON_CDC unexpected register payload ABI $name"
        }
        if {![dict exists $fields $field]} {error "COMMON_CDC unexpected register payload field $name"}
        set width [dict get $fields $field]
        if {($suffix eq {} && $width!=1) || ($suffix ne {} && ($index<0 || $index>=$width))} {
            error "COMMON_CDC unexpected register payload bit $name"
        }
        ff $name $destination;lappend captures $name
        if {![catch {constant $name/D 0}] || ![catch {constant $name/D 1}]} {continue}
        set launch $h/${from}_${field}_reg$suffix
        ff $launch $source
        if {[drivers $name/D] ne [list $launch/Q]} {error "COMMON_CDC register payload bypass $name"}
        lappend starts $launch/C;lappend ends $name/D
    }
    if {![llength $captures] || ![llength $ends]} {error "COMMON_CDC missing dynamic register payload $h/$to"}
    return [dict create label $h/$to starts $starts ends $ends second {} budget [budget $source $destination] skew 1]
}
proc common_cdc::new_stage_coverage {roots scopes} {
    set covered {};foreach s $scopes {lappend covered {*}[dict get $s ends]}
    foreach root $roots {
        foreach c [get_cells -quiet -hier -filter "IS_PRIMITIVE == TRUE && NAME =~ $root/*"] {
            set n [get_property NAME $c];set ref [get_property REF_NAME $c]
            # Check every retained FF clock, including ordinary control/payload and
            # reset release state. Global check_timing additionally covers RAM/IP.
            if {[string match FD* $ref]} {clock $n/C}
            if {[regexp {(Sync_stage0_reg\[[0-9]+\]|stages_reg\[0\])$} $n]} {
                if {[get_property ASYNC_REG $c] ni {1 TRUE true} || [lsearch -exact $covered $n/D]<0} {
                    error "COMMON_CDC uncovered new first-stage endpoint $n"
                }
            }
        }
    }
}
proc common_cdc::collect_boot50 {soc timer debug} {
    return [collect_static $soc $timer $debug boot50-static]
}
proc common_cdc::collect_static {soc timer debug {profile boot50-static}} {
    if {$profile eq {boot50-dynamic}} {return [collect_dynamic $soc $timer]}
    if {$profile ni {boot50-static performance300-static boot50-dynamic}} {error "COMMON_CDC unreviewed static profile $profile"}
    set performance [expr {$profile eq {performance300-static}}]
    set cpu [clock $soc/cpuClock];set fabric [clock $soc/fabricClock]
    set fixed [static_clock_anchors $soc $timer $debug];set aon [clock $soc/alwaysOnClock]
    expect_clock $soc/cpuClock $cpu [expr {$performance ? 1000.0/300 : 20.0}]
    expect_clock $soc/fabricClock $fabric [expr {$performance ? 4.0 : 20.0}]
    expect_clock $soc/ddrClock $fixed 4.0
    expect_clock $soc/alwaysOnClock $aon 20.0
    if {$cpu eq $fabric || $fabric eq $fixed} {
        error "COMMON_CDC static profile clock identities disagree: $profile"
    }
    distinct_net $soc/cpuClock $soc/fabricClock
    distinct_net $soc/fabricClock $soc/ddrClock
    set ddr $soc/ddrCrossing
    foreach root [list $ddr $timer $debug] {one get_cells $root}
    set lanes {};foreach suffix {{} _1 _2 _3 _4} {lappend lanes $ddr/empty_fifo$suffix}
    exact_modules $ddr HeldResponseCdcDataFifo* $lanes
    exact_modules $ddr CdcLevel* [list $ddr/fabricLinkReady_sync $ddr/ddrLinkReady_sync]
    exact_modules $timer CdcMailbox* [list $timer/snapshots]
    exact_modules $timer RegisterClockDomainBridge* [list $timer/mmio]
    exact_modules $timer CdcLevel* [list $timer/interrupt $timer/mmio/requestSync $timer/mmio/responseSync $timer/snapshots/requestSync $timer/snapshots/ackSync]
    exact_modules $debug CdcMailbox* [list $debug/requests $debug/responses]
    exact_modules $debug CdcLevel* [list $debug/requests/requestSync $debug/requests/ackSync $debug/responses/requestSync $debug/responses/ackSync]
    set result {};set i 0
    foreach lane $lanes {
        set src $fabric;set dst $fixed
        if {$i in {2 4}} {set src $fixed;set dst $fabric}
        expect_clock $lane/sourceClock $src;expect_clock $lane/destinationClock $dst
        foreach direction {write captured} {lappend result [gray $lane $direction]}
        # All five AXI lanes are live. No inactive/payload-absent shortcut.
        lappend result [payload $lane]
        incr i
    }
    foreach h [list $ddr/fabricLinkReady_sync $ddr/ddrLinkReady_sync $timer/interrupt $timer/mmio/requestSync $timer/mmio/responseSync $timer/snapshots/requestSync $timer/snapshots/ackSync $debug/requests/requestSync $debug/requests/ackSync $debug/responses/requestSync $debug/responses/ackSync] {
        set target $fabric
        if {$h in [list $ddr/ddrLinkReady_sync $timer/mmio/requestSync $timer/snapshots/ackSync $debug/requests/ackSync $debug/responses/requestSync]} {set target $fixed}
        expect_clock $h/clockIn $target
        expect_clock [format {%s/stages_reg[0]/C} $h] $target
        lappend result [level $h]
    }
    lappend result [mailbox_width $timer/snapshots 64 $fixed $fabric]
    lappend result [mailbox_width $debug/requests 41 $fixed $fabric]
    lappend result [mailbox_width $debug/responses 34 $fabric $fixed]
    expect_clock $timer/mmio/sourceClock $fabric;expect_clock $timer/mmio/destinationClock $fixed
    lappend result [register_payload $timer/mmio requestHeld request {address 64 write 1 size 3 data 64 byteEnable 8} $fabric $fixed]
    lappend result [register_payload $timer/mmio responseHeld reply {data 64 error 1} $fixed $fabric]
    one get_cells $soc/fabricDdrReady_ddrReadySync
    expect_clock $soc/fabricDdrReady_ddrReadySync/clockIn $fabric
    expect_clock [format {%s/fabricDdrReady_ddrReadySync/stages_reg[0]/C} $soc] $fabric
    lappend result [level $soc/fabricDdrReady_ddrReadySync]
    new_stage_coverage [list $ddr $timer $debug $soc/fabricDdrReady_ddrReadySync] $result
    puts "COMMON_CDC_STATIC_MAPPED profile=$profile scopes=[llength $result] NATIVE_TIMING_VALIDATION_STILL_REQUIRED"
    return $result
}

proc common_cdc::distinct_net {a b} {
    set aa [get_nets -quiet -segments -of_objects [one get_pins $a]]
    set bb [get_nets -quiet -segments -of_objects [one get_pins $b]]
    if {![llength $aa] || ![llength $bb]} {error "COMMON_CDC missing physical clock net $a $b"}
    foreach n $aa {
        if {[lsearch -exact $bb $n]>=0} {error "COMMON_CDC physical clock nets collapsed $a $b"}
    }
}

# Actual live anchors from the native synthesized design. Redundant parent
# clock aliases may be specialized to GND; never use them to time active logic.
proc common_cdc::driven_clock {pin source expected period} {
    expect_clock $pin $expected $period
    same_net $pin $source
    if {[drivers $pin] ne [list $source]} {
        error "COMMON_CDC incorrect active clock driver at $pin expected $source"
    }
}
proc common_cdc::clock_alias {pin active expected} {
    set aliases {u_soc/timebaseClock u_soc/fixedTimer/timebaseClock u_soc/debugClock u_soc/debugCrossing/sourceClock}
    if {![dict exists $aliases $pin] || [dict get $aliases $pin] ne $active} {
        error "COMMON_CDC unreviewed redundant clock alias $pin -> $active"
    }
    set object [one get_pins $pin]
    if {[get_property DIRECTION $object] ne {IN}} {error "COMMON_CDC redundant alias is not an input $pin"}
    # Even a standalone call cannot approve a dead alias without its precise
    # live child clock, period, physical net and unique UI-buffer driver proof.
    driven_clock $active u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O $expected 4.0
    set clocks [get_clocks -quiet -of_objects $object]
    if {[llength $clocks]} {
        expect_clock $pin $expected 4.0
        same_net $pin $active
    } else {
        set nets [get_nets -quiet -segments -of_objects $object]
        if {[llength $nets]} {
            # Synthesized redundant aliases are literal GND, never dynamic or POWER.
            constant $pin 0
            puts "COMMON_CDC_REDUNDANT_CLOCK_ALIAS_GND $pin ACTIVE_ANCHOR=$active NO_EXCEPTION"
        } else {
            # opt_design can remove that GND connection. Only these two exact
            # input aliases may be disconnected; there must be no residual sink.
            set endpoints [all_fanout -quiet -flat -endpoints_only -from $object]
            if {[llength $endpoints]} {error "COMMON_CDC disconnected alias retains fanout $pin: $endpoints"}
            puts "COMMON_CDC_REDUNDANT_CLOCK_ALIAS_DISCONNECTED $pin NO_NET_NO_CLOCK_NO_FANOUT ACTIVE_ANCHOR=$active NO_EXCEPTION"
        }
    }
}
proc common_cdc::static_clock_anchors {soc timer debug} {
    if {[info exists ::valence(clock_profile)] && $::valence(clock_profile) eq {boot50-dynamic}} {
        return [dynamic_clock_anchors $soc $timer]
    }
    set fixedSource u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O
    set fabricSource u_clk_wiz/inst/clkout3_buf/O
    set fixed [clock $fixedSource]
    set fabric [clock $fabricSource]
    expect_clock $fixedSource $fixed 4.0
    set fabricPeriod [get_property PERIOD [get_clocks $fabric]]
    if {$fabricPeriod ni {4 4.0 4.000 20 20.0 20.000}} {
        # Profile-specific numerical check remains in collect_static; accept
        # tool precision here, never an unrelated frequency.
        if {![string is double -strict $fabricPeriod] ||
            (abs($fabricPeriod-4.0)>0.002 && abs($fabricPeriod-20.0)>0.002)} {
            error "COMMON_CDC unreviewed active fabric period $fabricPeriod"
        }
    }
    distinct_net $fixedSource $fabricSource
    foreach pin [list $soc/ddrClock $soc/ddrCrossing/ddrClock $timer/timebaseClock $timer/timer/clock $debug/sourceClock $debug/requests/sourceClock u_debug/debug_clk] {
        driven_clock $pin $fixedSource $fixed 4.0
    }
    foreach pin [list $soc/fabricClock $soc/ddrCrossing/fabricClock $timer/fabricClock $debug/destinationClock $debug/requests/destinationClock] {
        driven_clock $pin $fabricSource $fabric $fabricPeriod
    }
    clock_alias $soc/timebaseClock $timer/timebaseClock $fixed
    clock_alias $soc/debugClock $debug/sourceClock $fixed
    return $fixed
}

# Diagnostic dynamic composition only. These are source-derived exact scopes,
# not mapped evidence. Missing/pruned banks fail for inspection in the SAME raw
# checkpoint. No global clock groups, functional reset cuts or absent-bank waiver.
proc common_cdc::dynamic_clock_anchors {soc timer} {
    if {$soc ne {u_soc} || $timer ne {u_soc/fixedTimer} ||
        ![info exists ::valence(clock_profile)] || $::valence(clock_profile) ne {boot50-dynamic}} {
        error "COMMON_CDC dynamic anchors require the exact diagnostic composition"
    }
    set fixedSource u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O
    set cpuSource cpu_clock/managed_buffer/O
    set fabricSource fabric_clock/managed_buffer/O
    set macSource network_clock/raw_div/O
    set fixed [clock $fixedSource]; set cpu [clock $cpuSource]
    set fabric [clock $fabricSource]; set mac [clock $macSource]
    expect_clock $fixedSource $fixed 4.0
    expect_clock $cpuSource $cpu [expr {1000.0/300}]
    expect_clock $fabricSource $fabric 4.0
    expect_clock $macSource $mac 8.0
    if {$cpu ne {cpu_target300} || $fabric ne {fabric_target250} ||
        [llength [lsort -unique [list $fixed $cpu $fabric $mac]]]!=4} {
        error "COMMON_CDC dynamic target/fixed clock identities changed"
    }
    # Public setup must already have named both real clocks. With these exact
    # names, the existing proof only verifies /4 and /2, CE, REF500 and CLR;
    # it does not enter its create_generated_clock branch.
    if {$mac ne {valence_tx_raw_div} || [clock network_clock/quarter_div/O] ne {valence_tx_quarter_div}} {
        error "COMMON_CDC missing existing physical MAC clock names"
    }
    valence_quarter_tx_clocks network_clock
    same_net network_clock/pll/CLKIN $fixedSource
    same_net network_clock/raw_div/I network_clock/delay_buffer/O
    same_net network_clock/delay_buffer/I network_clock/pll/CLKOUT0
    foreach {attribute expected} {CLKFBOUT_MULT 4 DIVCLK_DIVIDE 1 CLKOUT0_DIVIDE 2} {
        set actual [get_property $attribute [one get_cells network_clock/pll]]
        if {![string is double -strict $actual] || abs($actual-$expected)>0.0001} {
            error "COMMON_CDC fixed MAC PLL parameter changed: $attribute=$actual"
        }
    }
    if {[get_property REF_NAME [one get_cells network_clock/pll]] ne {PLLE4_ADV}} {
        error "COMMON_CDC fixed MAC source is not the reviewed PLLE4_ADV"
    }
    foreach pair [list [list $fixedSource $fabricSource] [list $cpuSource $fabricSource] [list $macSource $fabricSource]] {
        distinct_net {*}$pair
    }
    set debug $soc/debugSequence/boundary/crossing
    foreach pin [list $soc/ddrClock $soc/ddrCrossing/ddrClock $timer/timebaseClock $timer/timer/clock \
        $soc/ddrQualification/fixedClock $soc/timerQualification/fixedClock \
        $soc/debugSequence/debugClock $soc/debugSequence/boundary/sourceClock \
        $debug/sourceClock $debug/requests/sourceClock u_debug/debug_clk] {
        driven_clock $pin $fixedSource $fixed 4.0
    }
    foreach pin [list $soc/fabricClock $soc/ddrCrossing/fabricClock $timer/fabricClock \
        $soc/peripherals/sourceClock $soc/peripherals/crossing/fabricClock \
        $soc/debugSequence/fabricClock $soc/debugSequence/boundary/destinationClock \
        $debug/destinationClock $debug/requests/destinationClock] {
        driven_clock $pin $fabricSource $fabric 4.0
    }
    driven_clock $soc/cpuClock $cpuSource $cpu [expr {1000.0/300}]
    # Live fixed MAC loads prove the source island, not a potentially dead alias
    # such as continuousClock or a top-level metadata clock name.
    foreach pin [list $soc/peripherals/gmac/encode/clock $soc/peripherals/gmac/cpuRelease/clockIn \
        $soc/peripherals/gmac/rawTxRelease/clockIn $soc/peripherals/gmac/phy/clock \
        $soc/peripherals/gmac/mdio/clock $soc/peripherals/gmac/media/clock \
        $soc/peripherals/gmac/frontend/clock $soc/peripherals/gmac/csr/clock \
        $soc/peripherals/gmac/adapter/clock $soc/peripherals/gmac/rxClockWatchdog/monitorClock \
        $soc/peripherals/crossing/csr/destinationClock $soc/peripherals/guard/fixedClock] {
        driven_clock $pin $macSource $mac 8.0
    }
    same_net $soc/peripherals/gmac/commonReset $soc/commonColdReset
    same_net $soc/peripherals/crossing/commonReset $soc/commonColdReset
    same_net $soc/peripherals/guard/commonColdReset $soc/commonColdReset
    expect_clock $soc/alwaysOnClock [clock $soc/alwaysOnClock] 20.0
    # Dynamic aliases are not granted the static dead-alias exceptions. If a
    # named anchor was pruned, query the same raw DCP before narrowing the proof.
    puts "COMMON_CDC_DYNAMIC_ANCHORS CPU300_FABRIC250_STRESS FIXED_MAC125_UI250_AON50 NO_RUNTIME_RATE_QUALIFICATION"
    return $fixed
}

proc common_cdc::collect_dynamic {soc timer} {
    variable dynamic_roots
    set fixed [dynamic_clock_anchors $soc $timer]
    set cpu [clock cpu_clock/managed_buffer/O]
    set fabric [clock fabric_clock/managed_buffer/O]
    set mac [clock network_clock/raw_div/O]
    set aon [clock $soc/alwaysOnClock]
    if {[llength [lsort -unique [list $cpu $fabric $fixed $mac $aon]]]!=5} {
        error "COMMON_CDC dynamic independent clock identities collapsed"
    }
    set ddr $soc/ddrCrossing
    set debug $soc/debugSequence/boundary/crossing
    set outer $soc/peripherals/crossing
    set guard $soc/peripherals/guard
    set rates $soc/peripherals/rateCmu
    set dynamic_roots [list $ddr $timer $soc/ddrQualification $soc/timerQualification \
        $soc/runtime $soc/debugSequence $rates $outer $guard \
        $soc/fabricDdrReady_ddrReadySync $soc/debugFaultSync]
    foreach root $dynamic_roots {one get_cells $root}
    set fifos [list [list $ddr/empty_fifo $fabric $fixed] \
        [list $ddr/empty_fifo_1 $fabric $fixed] [list $ddr/empty_fifo_2 $fixed $fabric] \
        [list $ddr/empty_fifo_3 $fabric $fixed] [list $ddr/empty_fifo_4 $fixed $fabric] \
        [list $outer/txData $fabric $mac] [list $outer/txControl $fabric $mac] \
        [list $outer/rxData $mac $fabric] [list $outer/rxStatus $mac $fabric]]
    set registers [list [list $timer/mmio $fabric $fixed] [list $rates/bridge $fabric $aon] \
        [list $outer/csr $fabric $mac]]
    set mailboxes [list [list $timer/snapshots 64 $fixed $fabric] \
        [list $debug/requests 41 $fixed $fabric] [list $debug/responses 34 $fabric $fixed] \
        [list $rates/receipt 1 $fabric $aon] \
        [list $outer/commands 35 $fabric $mac] [list $outer/receipts 35 $mac $fabric] \
        [list $outer/observations 52 $mac $fabric] \
        [list $guard/requests 17 $aon $mac] [list $guard/replies 18 $mac $aon]]
    set levels [list [list $ddr/fabricLinkReady_sync $fabric] [list $ddr/ddrLinkReady_sync $fixed] \
        [list $timer/interrupt $fabric] [list $soc/fabricDdrReady_ddrReadySync $fabric] \
        [list $soc/debugFaultSync $aon] [list $outer/fatalRxStop_sync $mac] \
        [list $outer/sync $fabric] [list $guard/faultSync $aon]]
    foreach root [list $soc/ddrQualification $soc/timerQualification] {
        lappend mailboxes [list $root/command 10 $fabric $fixed]
        foreach name {observation terminal retirement} {lappend mailboxes [list $root/$name 9 $fixed $fabric]}
        lappend levels [list $root/fixedFaultSync $fabric] [list $root/fabricFaultSync $fixed]
    }
    set r $soc/runtime
    lappend mailboxes [list $r/command 11 $aon $fabric] [list $r/cpuArm 10 $aon $cpu] \
        [list $r/cpuObservation 12 $cpu $aon] [list $r/fabricObservation 12 $fabric $aon] \
        [list $r/terminal 9 $fabric $aon] [list $r/retirement 8 $fabric $aon]
    foreach name {retirementFaultInAon_sync localCloseFault_sync localCloseFault_sync_1} {
        lappend levels [list $r/$name $aon]
    }
    set d $soc/debugSequence
    lappend mailboxes [list $d/prepare 8 $fabric $fixed] [list $d/proof 8 $fixed $fabric] \
        [list $d/decision 9 $fabric $fixed] [list $d/terminal 9 $fixed $fabric] \
        [list $d/retirement 8 $fixed $fabric] \
        [list $d/boundary/probe 8 $fixed $fabric] [list $d/boundary/proof 8 $fabric $fixed] \
        [list $d/boundary/release_0 8 $fixed $fabric] [list $d/boundary/releaseAck 8 $fabric $fixed]
    lappend levels [list $d/fatalStop_sync $fixed] [list $d/debugFaultSync $fabric] [list $d/fabricFaultSync $fixed]
    set result {}; set fifoNames {}; set mailboxNames {}; set registerNames {}; set levelNames {}
    foreach row $fifos {
        lassign $row h source destination
        lappend fifoNames $h
        expect_clock $h/sourceClock $source; expect_clock $h/destinationClock $destination
        same_net $h/commonReset $soc/commonColdReset
        foreach direction {write captured} {lappend result [gray $h $direction]}
        # No payload_absent/inactive shortcut on any new outer or DDR lane.
        lappend result [payload $h]
    }
    foreach row $registers {
        lassign $row h source destination
        lappend registerNames $h
        expect_clock $h/sourceClock $source; expect_clock $h/destinationClock $destination
        same_net $h/commonReset $soc/commonColdReset
        lappend result [register_payload $h requestHeld request {address 64 write 1 size 3 data 64 byteEnable 8} $source $destination]
        lappend result [register_payload $h responseHeld reply {data 64 error 1} $destination $source]
        lappend levels [list $h/requestSync $destination] [list $h/responseSync $source]
    }
    foreach row $mailboxes {
        lassign $row h width source destination
        lappend mailboxNames $h
        if {$h in [list $debug/requests $debug/responses]} {
            # Only DMI transport has link-loss reset. Runtime/admission owners
            # retain common cold reset, even when the transport resets.
            same_net $h/commonReset $debug/release_0/asyncReset
        } else {same_net $h/commonReset $soc/commonColdReset}
        lappend result [mailbox_width $h $width $source $destination]
        lappend levels [list $h/requestSync $destination] [list $h/ackSync $source]
    }
    foreach row $levels {
        lassign $row h target
        lappend levelNames $h
        one get_cells $h
        expect_clock $h/clockIn $target
        expect_clock [format {%s/stages_reg[0]/C} $h] $target
        lappend result [level $h]
    }
    # Exact census includes each mailbox/CSR's internal synchronizers. Never
    # accept a missing source-known module just because its rate table is empty.
    foreach root $dynamic_roots {
        foreach {ref names} [list HeldResponseCdcDataFifo* $fifoNames CdcMailbox* $mailboxNames \
            RegisterClockDomainBridge* $registerNames CdcLevel* $levelNames] {
            set expected {}
            foreach h $names {if {[string first "$root/" $h]==0} {lappend expected $h}}
            exact_modules $root $ref $expected
        }
        exact_modules $root CdcDataFifo* {}
    }
    new_stage_coverage $dynamic_roots $result
    puts "COMMON_CDC_DYNAMIC_SOURCE_SCOPES scopes=[llength $result] STRICT_MAPPED_PROOF_REQUIRED NO_RATE_OR_SIGNOFF_ADMISSION"
    return $result
}
