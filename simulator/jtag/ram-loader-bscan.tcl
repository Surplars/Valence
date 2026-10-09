# Optional Valence custom BSCANE2 USER-register backend for ram-loader.tcl.
# This is NOT riscv use_bscan_tunnel. The board supplies the real FPGA TAP,
# physical IR length, expected FPGA IDCODE and USER instruction. No pin defaults.
namespace eval valence_ram {
    variable user_ir -1
    variable fpga_id -1
}
if {[info exists VALENCE_RAM_USER_IR]} {set valence_ram::user_ir $VALENCE_RAM_USER_IR}
if {[info exists VALENCE_RAM_FPGA_IDCODE]} {set valence_ram::fpga_id $VALENCE_RAM_FPGA_IDCODE}
source [file join [file dirname [info script]] ram-loader-xczu15eg.tcl]

proc valence_ram::bscan_scan {op address data} {
    validate_xczu15eg_configuration
    variable tap
    variable user_ir
    irscan $tap $user_ir
    # Fixed 64-bit custom USER DR, LSB first, split into <=32-bit fields:
    # op2, data32, address7, flags3, version4, magic16. Input flags must be zero.
    set fields [drscan $tap 2 $op 32 [hex $data] 7 [hex $address] 3 0 4 1 16 0x5642]
    if {[llength $fields] != 6} {error "Malformed Valence USER reply: $fields"}
    set result {}
    foreach value $fields bits {2 32 7 3 4 16} {lappend result [scan_value $value $bits]}
    if {[lindex $result 4] != 1 || [lindex $result 5] != 0x5642} {
        error "Valence USER signature/version mismatch; verify selected FPGA USER instruction and bitstream"
    }
    # flags bit0=DONE, bit1=BUSY, bit2=protocol_error; low op field is DMI status.
    return $result
}
proc valence_ram::bscan_collect {context {idle_only 0}} {
    validate_xczu15eg_configuration
    variable dmi_polls
    variable idle_cycles
    set delay $idle_cycles
    for {set attempt 0} {$attempt < $dmi_polls} {incr attempt} {
        runtest $delay
        set reply [bscan_scan 0 0 0]
        set flags [lindex $reply 3]
        if {!$idle_only && ($flags & 4)} {error "$context: USER protocol error; outcome uncertain; no request replay"}
        if {!($flags & 2) && ($idle_only || ($flags & 1))} {return $reply}
        if {$delay < 1024} {set delay [expr {$delay * 2}]}
    }
    error "$context: USER response timeout; outcome uncertain, no request replay; bus ownership may persist"
}
proc valence_ram::bscan_transfer {op address data} {
    set context [format "USER op=%d address=0x%02x" $op $address]
    set ready [bscan_scan 0 0 0]
    if {[lindex $ready 3] & 6} {error "$context: USER transport not ready; no request submitted"}
    # Submission returns the previous capture. Do not mistake it for a response.
    bscan_scan $op $address $data
    set reply [bscan_collect $context]
    if {[lindex $reply 0] != 0} {error "$context: DMI failed (status [lindex $reply 0]); no request replay"}
    if {[lindex $reply 2] != $address} {error "$context: response address mismatch; outcome uncertain; no request replay"}
    return [lindex $reply 1]
}
proc valence_ram::bscan_start {} {
    variable tap
    variable user_ir
    variable fpga_id
    variable fpga_id_mask
    variable idle_cycles
    if {$user_ir < 0 || $fpga_id < 0} {
        error "BSCAN requires board-supplied VALENCE_RAM_USER_IR and VALENCE_RAM_FPGA_IDCODE"
    }
    validate_xczu15eg_configuration
    set user_ir [u32 $user_ir USER_IR]
    set fpga_id [u32 $fpga_id FPGA_IDCODE]
    if {!($fpga_id & 1)} {error "FPGA_IDCODE must be a real nonzero IDCODE with bit 0 set"}
    set observed [u32 [jtag cget $tap -idcode] observed_FPGA_IDCODE]
    if {($observed & $fpga_id_mask) != ($fpga_id & $fpga_id_mask)} {
        error "Unexpected FPGA IDCODE [hex $observed], expected [hex $fpga_id] with BSDL mask [hex $fpga_id_mask]"
    }
    # The endpoint consumes its held UPDATE frame on TCK. >=8 idle clocks avoid
    # observing an old DONE; BUSY also covers an UPDATE awaiting consumption.
    set idle_cycles 8
    set reply [bscan_collect "Initial USER transport drain" 1]
    if {([lindex $reply 3] & 4) || [lindex $reply 0] != 0} {
        # Control 1 clears a retained result/protocol error only while idle.
        # It does not cancel an in-flight request and is never a hard reset.
        bscan_scan 3 1 0
        set reply [bscan_collect "USER clear-result" 1]
        if {[lindex $reply 3] & 4} {error "USER protocol error remained after idle clear-result"}
    }
    if {[bscan_transfer 3 0 0] != 0x701} {error "Valence USER capability mismatch; require protocol 1, address width 7"}
}
proc valence_ram::bscan_dmi {op address data} {
    validate_xczu15eg_configuration
    variable uncertain
    if {$uncertain} {error "Transport outcome uncertain; use explicit valence_abort to attempt a bounded drain, or inspect/reset the board safely"}
    set uncertain 1
    if {[catch {bscan_transfer $op $address $data} value]} {error $value}
    set uncertain 0
    return $value
}
