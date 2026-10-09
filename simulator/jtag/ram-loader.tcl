# Valence RAM loader, run by OpenOCD's Jim Tcl interpreter. No riscv target.
# Raw JTAG fields follow https://openocd.org/doc/html/JTAG-Commands.html.
# Source this file; then explicitly call valence_download_and_run FILE ENTRY.
# The CPU must already be parked in the ROM's UART 'j' download mode.
namespace eval valence_ram {
    variable backend direct
    variable tap valence.dtm
    variable expected_id 1
    variable dmi_polls 64
    variable sb_polls 1024
    variable claim_polls 4096
    variable chunk_words 256
    variable idle_cycles 8
    variable initialized 0
    variable uncertain 0
    variable committed_generation -1
    variable expected_base 0x80200000
}
if {[info exists VALENCE_RAM_BACKEND]} {set valence_ram::backend $VALENCE_RAM_BACKEND}
if {[info exists VALENCE_RAM_TAP]} {set valence_ram::tap $VALENCE_RAM_TAP}
if {[info exists VALENCE_RAM_IDCODE]} {set valence_ram::expected_id $VALENCE_RAM_IDCODE}

proc valence_ram::say {message} {
    if {[llength [info commands echo]]} {echo $message} else {puts $message}
}
proc valence_ram::u32 {value label} {
    if {![regexp {^(0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)$} $value]} {
        error "$label must be an unsigned integer (decimal or 0x hexadecimal)"
    }
    if {[catch {expr {$value + 0}} number] || $number < 0 || $number > 0xffffffff} {
        error "$label is outside the unsigned 32-bit range"
    }
    return $number
}
proc valence_ram::hex {value} {return [format 0x%08x $value]}
proc valence_ram::scan_value {value bits} {
    # OpenOCD drscan returns unprefixed hexadecimal strings, including digits only.
    if {![regexp {^[0-9a-fA-F]+$} $value]} {error "Malformed drscan reply: $value"}
    set number [expr "0x$value"]
    if {$number < 0 || $number >= (1 << $bits)} {error "Oversized drscan reply: $value"}
    return $number
}
proc valence_ram::reg_scan {instruction value} {
    variable tap
    irscan $tap $instruction
    set result [drscan $tap 32 [hex $value]]
    if {[llength $result] != 1} {error "Malformed 32-bit drscan reply: $result"}
    return [scan_value [lindex $result 0] 32]
}
proc valence_ram::dmi_scan {op address data} {
    variable tap
    irscan $tap 0x11
    # Scan order is LSB first: op[1:0], data[33:2], address[40:34].
    # Separate <=32-bit fields avoid OpenOCD's nonportable >32-bit field handling.
    set result [drscan $tap 2 $op 32 [hex $data] 7 [hex $address]]
    if {[llength $result] != 3} {error "Malformed DMI drscan reply: $result"}
    return [list [scan_value [lindex $result 0] 2] \
        [scan_value [lindex $result 1] 32] [scan_value [lindex $result 2] 7]]
}
proc valence_ram::clear_busy {} {
    # dmireset clears sticky transport status only. dtmhardreset (bit 17),
    # TAP reset, TRST and system reset must NOT occur during a download.
    reg_scan 0x10 0x10000
}
proc valence_ram::collect {context {allow_old_failure 0}} {
    variable dmi_polls
    variable idle_cycles
    set delay $idle_cycles
    for {set attempt 0} {$attempt < $dmi_polls} {incr attempt} {
        runtest $delay
        set reply [dmi_scan 0 0 0]
        set status [lindex $reply 0]
        if {$status == 0} {return $reply}
        if {$status == 3 || ($status == 2 && $allow_old_failure)} {
            clear_busy
            if {$delay < 1024} {set delay [expr {$delay * 2}]}
        } else {
            error "$context: DMI failed (status $status); request was not replayed"
        }
    }
    error "$context: DMI response timeout; outcome uncertain, request was not replayed; bus ownership may persist"
}
proc valence_ram::dmi {op address {data 0}} {
    variable backend
    if {$backend == "direct"} {return [raw_dmi $op $address $data]}
    if {$backend == "bscan" && [llength [info commands ::valence_ram::bscan_dmi]]} {
        return [bscan_dmi $op $address $data]
    }
    error "Unknown or unloaded RAM-loader transport backend: $backend"
}
proc valence_ram::raw_dmi {op address {data 0}} {
    variable uncertain
    if {$uncertain} {error "Transport outcome uncertain; use explicit valence_abort to attempt a bounded drain, or inspect/reset the board safely"}
    set context [format "DMI op=%d address=0x%02x" $op $address]
    # Mark uncertain BEFORE the potentially side-effecting scan. Any scan/I/O
    # exception must prevent a later invocation from silently replaying a write.
    set uncertain 1
    if {[catch {
        set previous [dmi_scan $op $address $data]
        if {[lindex $previous 0] != 0} {
            error "$context: transport was not idle at request scan; acceptance uncertain; no replay"
        }
        set reply [collect $context]
        if {[lindex $reply 2] != $address} {
            error "$context: response address mismatch; outcome uncertain; no replay"
        }
    } problem]} {error $problem}
    set uncertain 0
    return [lindex $reply 1]
}
proc valence_ram::rd {address} {return [dmi 1 $address]}
proc valence_ram::wr {address data} {dmi 2 $address $data}

proc valence_ram::start {{recovery 0}} {
    variable expected_id
    variable backend
    variable initialized
    variable uncertain
    variable idle_cycles
    variable dmi_polls
    variable sb_polls
    variable claim_polls
    variable chunk_words
    if {$uncertain && !$recovery} {
        error "Previous transport outcome uncertain; do not retry the download; use explicit valence_abort to attempt drain"
    }
    foreach {name value} [list dmi_polls $dmi_polls sb_polls $sb_polls claim_polls $claim_polls chunk_words $chunk_words] {
        if {![string is integer -strict $value] || $value <= 0} {error "$name must be positive"}
    }
    set initialized 0
    set uncertain 1
    if {$backend == "direct"} {
        set id [reg_scan 0x01 0]
        if {$id != $expected_id || !($id & 1)} {error "Unexpected IDCODE [hex $id], expected [hex $expected_id]"}
        set dtmcs [reg_scan 0x10 0]
        if {($dtmcs & 15) != 1 || (($dtmcs >> 4) & 63) != 7} {
            error "Unsupported DTMCS [hex $dtmcs]; require wire version 1 and abits=7"
        }
        set idle_cycles [expr {(($dtmcs >> 12) & 7) + 1}]
        # Initial synchronization collects only NOPs. It never reissues an unknown
        # old request. Explicit recovery may clear a completed old failure.
        collect "Initial transport drain" 1
    } elseif {$backend == "bscan" && [llength [info commands ::valence_ram::bscan_start]]} {
        bscan_start
    } else {
        error "Unknown or unloaded RAM-loader transport backend: $backend"
    }
    set uncertain 0
    if {[rd 0x40] != 0x564c0101} {error "RAM-loader capability/version mismatch"}
    if {[rd 0x10] != 0 || [rd 0x11] != 0} {error "Unexpected DM identity; this loader requires the transport-only endpoint"}
    set initialized 1
}
proc valence_ram::sb_wait {} {
    variable sb_polls
    for {set attempt 0} {$attempt < $sb_polls} {incr attempt} {
        set sbcs [rd 0x38]
        set ownership ""
        if {($sbcs & (1 << 21)) && ($sbcs & ((1 << 22) | (7 << 12)))} {
            set ::valence_ram::uncertain 1
            set ownership "; BUSY remains set, transfer may still own the bus; use explicit valence_abort to attempt drain"
        }
        if {$sbcs & (1 << 22)} {error "SBA sbbusyerror is set; no memory request was retried$ownership"}
        if {$sbcs & (7 << 12)} {error "SBA sberror=[expr {($sbcs >> 12) & 7}]; no memory request was retried$ownership"}
        if {!($sbcs & (1 << 21))} {return $sbcs}
    }
    set ::valence_ram::uncertain 1
    error "SBA busy timeout; transfer may still own the bus. No ABORT/reset was issued; use explicit valence_abort and check drain state"
}
proc valence_ram::session {generation} {
    set observed [rd 0x46]
    set status [rd 0x41]
    if {$observed != $generation} {error "Download generation changed ($generation -> $observed); no further writes permitted"}
    if {!($status & 0x20)} {error "Download link is down; session is invalid"}
    if {!($status & 1) || ($status & 0x56)} {error "ROM is not ARMED for this download (STATUS=[hex $status]); type j at the ROM prompt"}
    if {$status & 8} {error "Download session is BUSY; no further host access issued"}
    return $status
}
# OpenOCD commonly builds Jim with --minimal: binary is optional and absent.
# Jim strings are raw bytes even in a UTF-8-enabled build; use pack/unpack and
# byte-indexed string primitives there. Stock Tcl byte arrays use binary scan.
set valence_ram::jim_bytes [expr {![catch {string byterange "" 0 0}]}]
if {$valence_ram::jim_bytes && ![llength [info commands unpack]]} {
    error "This Jim Tcl build needs the pack/unpack extension for binary images"
}
proc valence_ram::byte_count {bytes} {
    variable jim_bytes
    if {$jim_bytes} {return [string bytelength $bytes]}
    return [string length $bytes]
}
proc valence_ram::byte_values {bytes offset count} {
    variable jim_bytes
    if {$jim_bytes} {
        set values {}
        set end [expr {$offset + $count}]
        set length [byte_count $bytes]
        if {$end > $length} {set end $length}
        for {set i $offset} {$i < $end} {incr i} {
            lappend values [unpack $bytes -uintle [expr {$i * 8}] 8]
        }
        return $values
    }
    binary scan [string range $bytes $offset [expr {$offset + $count - 1}]] c* values
    return $values
}
proc valence_ram::crc32 {bytes} {
    # CRC-32/ISO-HDLC, reflected polynomial, over the original unpadded file.
    # No zlib/package dependency in OpenOCD's Jim Tcl.
    set crc 0xffffffff
    # Bound the temporary byte list rather than expanding a large image into
    # millions of Tcl objects at once.
    set length [byte_count $bytes]
    for {set offset 0} {$offset < $length} {incr offset 4096} {
        set values [byte_values $bytes $offset 4096]
        foreach byte $values {
            set crc [expr {$crc ^ ($byte & 255)}]
            for {set bit 0} {$bit < 8} {incr bit} {
                if {$crc & 1} {set crc [expr {($crc >> 1) ^ 0xedb88320}]} else {set crc [expr {$crc >> 1}]}
            }
        }
    }
    return [expr {($crc ^ 0xffffffff) & 0xffffffff}]
}
proc valence_ram::word {bytes offset} {
    set values [byte_values $bytes $offset 4]
    set result 0
    set shift 0
    foreach byte $values {
        set result [expr {$result | (($byte & 255) << $shift)}]
        incr shift 8
    }
    # Missing bytes of the final word are deliberately zero, never file data.
    return $result
}
proc valence_ram::now {} {
    if {[catch {clock milliseconds} value]} {return -1}
    return $value
}
proc valence_ram::download {filename entry} {
    variable expected_base
    variable chunk_words
    variable committed_generation
    set committed_generation -1
    set entry [u32 $entry entry]
    set length [file size $filename]
    if {$length <= 0} {error "Image is empty"}
    if {$length > 0xffffffff} {error "Image length exceeds 32 bits"}
    if {$entry & 3} {error "Entry must be 4-byte aligned"}
    start
    set generation [rd 0x46]
    session $generation
    set base [rd 0x47]
    set end [rd 0x48]
    set padded [expr {($length + 3) & ~3}]
    if {$base != $expected_base || $end <= $base || ($end & 3)} {error "Invalid advertised RAM interval [hex $base]..[hex $end]"}
    if {$padded > $end - $base} {error "Image (including final-word padding) exceeds advertised RAM interval"}
    if {$entry < $base || $entry >= $base + $length} {error "Entry is outside the logical image"}
    set sbcs [sb_wait]
    if {(($sbcs >> 29) & 7) != 1 || (($sbcs >> 5) & 127) != 32 || ($sbcs & 31) != 4} {
        error "Unsupported SBCS [hex $sbcs]; require v1, 32-bit address, 32-bit access only"
    }
    set channel [open $filename rb]
    set rc [catch {read $channel} bytes]
    close $channel
    if {$rc} {error $bytes}
    if {[byte_count $bytes] != $length} {error "Image changed length while reading"}
    set crc [crc32 $bytes]
    set started [now]
    # Disable read side effects and autoincrement. Each accepted write launches
    # exactly one 32-bit SBA transaction and is followed by bounded busy polling.
    session $generation
    wr 0x38 [expr {2 << 17}]
    for {set offset 0} {$offset < $padded} {incr offset 4} {
        if {($offset % ($chunk_words * 4)) == 0} {session $generation}
        wr 0x39 [expr {$base + $offset}]
        wr 0x3c [word $bytes $offset]
        sb_wait
        if {(($offset + 4) % ($chunk_words * 4)) == 0 || $offset + 4 == $padded} {session $generation}
    }
    # A separate complete readback pass compares every byte including zero pad.
    # readonaddr=1, readondata=0, autoincrement=0 prevents speculative extra reads.
    session $generation
    wr 0x38 [expr {(2 << 17) | (1 << 20)}]
    for {set offset 0} {$offset < $padded} {incr offset 4} {
        if {($offset % ($chunk_words * 4)) == 0} {session $generation}
        wr 0x39 [expr {$base + $offset}]
        sb_wait
        set actual [rd 0x3c]
        set wanted [word $bytes $offset]
        if {$actual != $wanted} {error "Readback mismatch at [hex [expr {$base + $offset}]]: expected [hex $wanted], got [hex $actual]; COMMIT not sent"}
        if {(($offset + 4) % ($chunk_words * 4)) == 0 || $offset + 4 == $padded} {session $generation}
    }
    session $generation
    wr 0x38 [expr {2 << 17}]
    # Validate session again before EACH metadata write and final irreversible
    # request, so reset/re-arm between checks cannot silently commit a new epoch.
    foreach {address value} [list 0x49 $generation 0x43 $entry 0x44 $length 0x45 $crc] {
        session $generation
        wr $address $value
    }
    session $generation
    wr 0x42 2
    # Do not retry COMMIT, even if its observation is ambiguous or times out.
    set committed_generation $generation
    set observed [rd 0x46]
    set status [rd 0x41]
    if {$observed != $generation || ($status & 0x14) || !($status & 0x42)} {
        error "COMMIT was sent once, but acceptance could not be confirmed (generation=$observed STATUS=[hex $status]); inspect ROM; do not replay"
    }
    set elapsed [expr {[now] - $started}]
    if {$started >= 0 && $elapsed >= 0} {set timing ", $elapsed ms"} else {set timing ""; set elapsed -1}
    say "Verified $length bytes (CRC32 [hex $crc]$timing); COMMIT accepted. ROM performs its own CRC and launch. Guest execution is not confirmed."
    return [list state commit_accepted bytes $length padded_bytes $padded crc32 [hex $crc] generation $generation elapsed_ms $elapsed]
}
proc valence_download_and_run {filename entry} {return [valence_ram::download $filename $entry]}

proc valence_wait_claimed {} {
    set generation $valence_ram::committed_generation
    if {$generation < 0} {error "No COMMIT was issued by this loader"}
    for {set attempt 0} {$attempt < $valence_ram::claim_polls} {incr attempt} {
        set observed [valence_ram::rd 0x46]
        set status [valence_ram::rd 0x41]
        if {$observed != $generation || ($status & 0x14)} {error "ROM launch cancelled or failed (generation=$observed STATUS=[valence_ram::hex $status])"}
        if {$status & 0x40} {
            valence_ram::say "ROM launch CLAIMED; this is the irreversible launch point, not proof of guest execution. Full reset is required before another download."
            return [list state claimed generation $generation]
        }
    }
    error "COMMIT accepted, but CLAIM was not observed within the poll bound. ROM may still be verifying; no command was replayed or aborted"
}
proc valence_abort {} {
    # Explicit user request only. Drain any transport request with NOPs before
    # sending ABORT once. A timeout must never imply an outstanding bus transfer
    # has vanished, and ABORT after ROM CLAIM cannot undo guest launch.
    valence_ram::start 1
    set status [valence_ram::rd 0x41]
    if {$status & 0x40} {error "ROM already CLAIMED launch; ABORT cannot undo it. Full reset is required for another download"}
    valence_ram::wr 0x42 1
    for {set attempt 0} {$attempt < $valence_ram::sb_polls} {incr attempt} {
        set status [valence_ram::rd 0x41]
        if {$status & 0x40} {error "ROM CLAIM raced ABORT; launch cannot be undone"}
        if {!($status & 8)} {
            if {!($status & 4)} {error "ABORT sent once but cancellation was not observed; inspect reset/drain state"}
            set valence_ram::committed_generation -1
            valence_ram::say "ABORT confirmed; no outstanding loader bus transfer reported. Type j at the ROM prompt for a new session."
            return [list state cancelled status [valence_ram::hex $status]]
        }
    }
    error "ABORT sent once, but bus drain is still BUSY. Do not assume transfer stopped; inspect board reset/drain state before re-arming"
}
