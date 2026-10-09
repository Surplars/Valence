#!/usr/bin/env tclsh
# Independent host contract model. Does NOT load RTL constants or imply physical
# OpenOCD/adapter validation. Exercises actual loader procedures through raw
# irscan/drscan/runtest mocks, including independently scheduled bus completion.
source [file join [file dirname [info script]] ram-loader.tcl]
namespace eval model {}
proc model::reset {} {
    variable state
    catch {unset state}
    array set state {
        ir 1 id 1 dtmcs 0x7071 sticky 0 pending 0 remaining 0 delay 0
        response_status 0 response_data 0 response_address 0
        result_status 0 result_data 0 result_address 0
        cap 0x564c0101 status 0x21 epoch 9 base 0x80200000 end 0x80200100
        sb_control 0x40000 sb_error 0 sb_busyerror 0 sb_busy 0 sb_delay 0
        sb_remaining 0 sb_address 0 sb_data 0 bus_kind none bus_address 0 bus_data 0
        commit_count 0 abort_count 0 writes 0 reads 0 hard_resets 0 soft_resets 0
        gen_after_writes -1 armed_after_writes -1 corrupt_address -1
        fail_address -1 fail_op -1 fail_status 2 commit_fail 0 commit_timeout 0
        abort_hold_busy 0 force_claim 0 cap_override 0x20000404
        scan_fault 0 nop_count 0 commit_claim 0 rearm_at_commit 0 bus_error_kind none ir_scans 0 dr_scans 0 shifted_bits 0 idle_tck 0
    }
    variable memory; catch {unset memory}; array set memory {}
    variable metadata; catch {unset metadata}; array set metadata {}
    variable requests; set requests {}
    variable scans; set scans {}
    set ::valence_ram::backend direct
    set ::valence_ram::uncertain 0
    set ::valence_ram::initialized 0
    set ::valence_ram::committed_generation -1
    set ::valence_ram::dmi_polls 8
    set ::valence_ram::sb_polls 6
    set ::valence_ram::claim_polls 6
    set ::valence_ram::chunk_words 2
}
proc model::bus_start {kind value} {
    variable state
    if {$state(sb_busy)} {set state(sb_busyerror) 1; return}
    if {$state(sb_error) || $state(sb_busyerror)} {return}
    if {!($state(status) & 1) || ($state(status) & 0x56)} {set state(sb_error) 2; return}
    set address $state(sb_address)
    if {$address < $state(base) || $address > $state(end)-4 || ($address & 3)} {set state(sb_error) 2; return}
    set state(bus_kind) $kind; set state(bus_address) $address; set state(bus_data) $value
    set state(sb_busy) 1; set state(sb_remaining) $state(sb_delay)
}
proc model::bus_tick {} {
    variable state; variable memory
    if {!$state(sb_busy)} {return}
    if {$state(sb_remaining) > 0} {incr state(sb_remaining) -1; return}
    set address $state(bus_address)
    if {$state(bus_error_kind) == $state(bus_kind)} {set state(sb_error) 2; set state(sb_busy) 0; return}
    if {$state(bus_kind) == "write"} {
        set memory($address) $state(bus_data); incr state(writes)
        if {$state(gen_after_writes) == $state(writes)} {incr state(epoch)}
        if {$state(armed_after_writes) == $state(writes)} {set state(status) 0x24}
    } elseif {$state(bus_kind) == "read"} {
        incr state(reads)
        if {[info exists memory($address)]} {set state(sb_data) $memory($address)} else {set state(sb_data) 0}
        if {$address == $state(corrupt_address)} {set state(sb_data) [expr {$state(sb_data) ^ 0x100}]}
    }
    set state(bus_kind) none; set state(sb_busy) 0
}
proc model::access {op address data} {
    variable state; variable memory; variable metadata; variable requests
    lappend requests [list $op $address $data]
    if {$address == $state(fail_address) && ($state(fail_op) < 0 || $op == $state(fail_op))} {return [list $state(fail_status) 0]}
    if {$op == 1} {
        switch -- $address {
            16 - 17 {return {0 0}}
            64 {return [list 0 $state(cap)]}
            65 {
                if {$state(abort_count)} {bus_tick}
                if {$state(force_claim)} {set state(status) 0x62}
                if {$state(abort_hold_busy) && $state(abort_count)} {return {0 0x2c}}
                return [list 0 [expr {$state(status) | ($state(sb_busy) << 3)}]]
            }
            70 {return [list 0 $state(epoch)]}
            71 {return [list 0 $state(base)]}
            72 {return [list 0 $state(end)]}
            56 {
                bus_tick
                return [list 0 [expr {$state(cap_override) | $state(sb_control) | ($state(sb_busy) << 21) | ($state(sb_busyerror) << 22) | ($state(sb_error) << 12)}]]
            }
            57 {return [list 0 $state(sb_address)]}
            60 {
                set result $state(sb_data)
                if {$state(sb_control) & 0x8000} {bus_start read 0}
                return [list 0 $result]
            }
            default {
                if {[info exists metadata($address)]} {return [list 0 $metadata($address)]}
                return {2 0}
            }
        }
    }
    switch -- $address {
        16 {if {$data == 0} {return {0 0}}; return {2 0}}
        56 {
            if {$state(sb_busy)} {set state(sb_busyerror) 1; return {0 0}}
            if {$data & 0x400000} {set state(sb_busyerror) 0}
            if {$data & 0x7000} {set state(sb_error) 0}
            set state(sb_control) [expr {$data & 0x1f8000}]
        }
        57 {
            set state(sb_address) $data
            if {$state(sb_control) & 0x100000} {bus_start read 0}
        }
        60 {bus_start write $data}
        66 {
            if {$data == 1} {
                incr state(abort_count)
                if {!($state(status) & 0x40)} {set state(status) 0x24}
            } elseif {$data == 2} {
                incr state(commit_count)
                if {$state(commit_fail)} {return {2 0}}
                if {!($state(status) & 1) || $state(sb_busy)} {return {2 0}}
                if {$state(rearm_at_commit)} {incr state(epoch)}
                if {![info exists metadata(73)] || $metadata(73) != $state(epoch)} {return {2 0}}
                foreach field {67 68 69} {if {![info exists metadata($field)]} {error "Model: incomplete COMMIT metadata"}}
                set state(status) 0x22
                if {$state(commit_claim)} {set state(status) 0x62}
            } else {return {2 0}}
        }
        67 - 68 - 69 - 73 {
            if {!($state(status) & 1) || ($state(status) & 0x5e) || $state(sb_busy)} {return {2 0}}
            set metadata($address) $data
        }
        default {return {2 0}}
    }
    return {0 0}
}
proc irscan {tap instruction args} {
    if {$tap != "valence.dtm"} {error "Wrong TAP"}
    incr model::state(ir_scans)
    incr model::state(shifted_bits) 5
    set model::state(ir) [expr {$instruction + 0}]
}
proc runtest {cycles} {
    upvar #0 model::state s
    incr s(idle_tck) $cycles
    if {$cycles <= 0} {error "Nonpositive idle cycles"}
    if {$s(pending)} {
        incr s(remaining) -$cycles
        if {$s(remaining) <= 0} {
            set s(pending) 0
            set s(result_status) $s(response_status)
            set s(result_data) $s(response_data)
            set s(result_address) $s(response_address)
            # Independent result status is retained across sticky busy clearing.
        }
    }
}
proc drscan {tap args} {
    upvar #0 model::state s
    incr s(dr_scans)
    foreach {bits value} $args {incr s(shifted_bits) $bits}
    lappend model::scans [list $s(ir) $args]
    if {$s(scan_fault)} {error "Injected adapter I/O failure"}
    if {$s(ir) == 1} {
        if {[llength $args] != 2 || [lindex $args 0] != 32} {error "Wrong ID scan width"}
        return [format %08x $s(id)]
    }
    if {$s(ir) == 16} {
        if {[llength $args] != 2 || [lindex $args 0] != 32} {error "Wrong DTM scan width"}
        set value [expr {[lindex $args 1]+0}]
        set result [expr {$s(dtmcs) | ($s(sticky) << 10)}]
        if {$value & 0x20000} {incr s(hard_resets); error "Forbidden dtmhardreset"}
        if {$value & 0x10000} {incr s(soft_resets); set s(sticky) 0; if {!$s(pending)} {set s(result_status) 0}}
        return [format %08x $result]
    }
    if {$s(ir) != 17 || [llength $args] != 6 || [lindex $args 0] != 2 || [lindex $args 2] != 32 || [lindex $args 4] != 7} {error "Wrong DMI scan framing"}
    set op [expr {[lindex $args 1]+0}]; set data [expr {[lindex $args 3]+0}]; set address [expr {[lindex $args 5]+0}]
    set status $s(sticky)
    if {$status == 0} {
        if {$s(pending)} {set status 3; set s(sticky) 3} else {set status $s(result_status)}
    }
    set result [list [format %x $status] [format %08x $s(result_data)] [format %02x $s(result_address)]]
    if {$op == 0} {incr s(nop_count)}
    if {$op == 1 || $op == 2} {
        if {!$s(pending) && !$s(sticky) && !$s(result_status)} {
            lassign [model::access $op $address $data] s(response_status) s(response_data)
            set s(response_address) $address; set s(pending) 1; set s(remaining) $s(delay)
            if {$s(commit_timeout) && $op == 2 && $address == 66 && $data == 2} {set s(remaining) 1000000000}
        } else {set s(sticky) 3}
    }
    return $result
}
proc echo {message} {lappend ::messages $message}
proc assert {expression {message assertion}} {
    if {![uplevel 1 [list expr $expression]]} {error "$message: $expression"}
}
proc fails {script pattern} {
    set status [catch {uplevel 1 $script} message]
    if {!$status || ![string match $pattern $message]} {error "Expected failure '$pattern', got status=$status: $message"}
    return $message
}
proc test {name body} {
    model::reset
    set ::messages {}
    if {[catch {uplevel 1 $body} message opts]} {
        puts stderr "FAIL $name: $message"
        puts stderr [dict get $opts -errorinfo]
        incr ::failed
    } else {puts "PASS $name"; incr ::passed}
}
set passed 0; set failed 0
set work [file normalize [file join /tmp valence-ram-loader-test-[pid]]]
file mkdir $work
proc image_file {hexbytes} {
    set file [file join $::work image.bin]
    set channel [open $file wb]; puts -nonewline $channel [binary format H* $hexbytes]; close $channel
    return $file
}

proc finish {label} {
    file delete -force $::work
    puts "$label: $::passed passed, $::failed failed (independent Tcl mocks; no real OpenOCD/adapter run)"
    if {$::failed} {exit 1}
}
