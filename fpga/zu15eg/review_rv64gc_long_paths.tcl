# Read-only analysis of the completed candidate. Never reruns implementation.
if {$argc != 2 && $argc != 3} {error "Expected ROUTED_DCP FRESH_REPORT_DIRECTORY OPTIONAL_CANDIDATE_ROOT"}
lassign $argv checkpoint destination
set checkpoint [file normalize $checkpoint]
set destination [file normalize $destination]
if {![file exists $checkpoint] || [file exists $destination]} {error "Missing checkpoint or report directory already exists"}
file mkdir $destination
set_param general.maxThreads 8
# Optional release-input investigation shares this one full-board DCP load.
# It records facts; it neither changes constraints nor waives any warning.
set expectedRom [dict create]
if {$argc == 3} {
    set candidate [file normalize [lindex $argv 2]]
    set rom [file join $candidate ip-build board_ip.gen sources_1 ip blk_mem_gen_0 blk_mem_gen_0.dcp]
    if {![file exists $rom]} {error "Missing this candidate's ROM IP checkpoint"}
    open_checkpoint $rom
    foreach cell [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}] {
        foreach property [list_property $cell] {
            if {[regexp {^INIT(P)?_[0-9A-F]{2}$} $property]} {
                dict set expectedRom "u_soc/platform/rom/memory/[get_property NAME $cell]/$property" [get_property $property $cell]
            }
        }
    }
    if {[dict size $expectedRom] != 4176} {error "Incomplete expected BootROM INIT/INITP mapping"}
    close_design
}
open_checkpoint $checkpoint
set cpu [get_clocks -of_objects [get_pins u_soc/clock]]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 10.0) > 0.001} {error "Expected real CPU100 clock"}
if {$argc == 3} {
    set facts [open [file join $destination release_input_facts.txt] w]
    puts $facts "CHECKPOINT=$checkpoint"
    puts $facts "PART=[get_property PART [current_design]]"
    dict for {key expected} $expectedRom {
        set split [string last / $key]
        set cell [get_cells -quiet [string range $key 0 [expr {$split-1}]]]
        set property [string range $key [expr {$split+1}] end]
        if {[llength $cell] != 1 || [get_property $property $cell] ne $expected} {
            error "Implemented BootROM differs from candidate IP: $key"
        }
    }
    puts $facts "BOOTROM_INIT_MATCH=4176 (MIF/binary identity must also pass audit_bootrom.py)"
    puts $facts "LEGACY_ETH_CLOCK_IP_CELLS=[llength [get_cells -quiet -hier -filter {REF_NAME == clk_wiz_eth}]]"
    foreach {pin period} {
        u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0
        u_soc/nativeBank/uart/uart/clock 20.0 u_soc/io_nativeGmac_rawTxClock 8.0
        u_rgmii/delay_clock 2.0
    } {
        set clock [get_clocks -of_objects [get_pins $pin]]
        if {[llength $clock] != 1 || abs([get_property PERIOD $clock] - $period)>0.001} {
            error "Actual board clock mismatch: $pin"
        }
        puts $facts "CLOCK $pin $clock PERIOD=$period"
    }
    # Vendor XDC lines 169/170 are queried as loaded on the complete hierarchy.
    # Empty sets are evidence for review, not permission to hide other paths.
    foreach leaf {RIU_ADDR RIU_WR_DATA} {
        set exact [get_pins -quiet u_ddr/inst/*/*/*/*/*/*.u_xiphy_control/xiphy_control/${leaf}*]
        set expanded [get_pins -quiet -hier -filter "NAME =~ u_ddr/* && REF_PIN_NAME =~ ${leaf}*"]
        puts $facts "MIG_VENDOR_HOLD_TARGET $leaf original=[llength $exact] expanded=[llength $expanded]"
        foreach pin $expanded {puts $facts "MIG_RIU_PIN $pin"}
    }
    close $facts
}
report_timing -from $cpu -to $cpu -delay_type max -max_paths 200 -nworst 1 -input_pins -file [file join $destination cpu_setup_200.rpt]
foreach {name filter} {
    fp {IS_SEQUENTIAL && NAME =~ *floatingPoint*}
    fp_physical_write {IS_SEQUENTIAL && NAME =~ *floatingPoint/fp/*}
    line_writer {IS_SEQUENTIAL && NAME =~ *lineTransfer/writer/*}
    fetch_window {IS_SEQUENTIAL && NAME =~ *suppliedPackets_window/*}
    store_preparation_owner {IS_SEQUENTIAL && NAME =~ *backend/capturedOwners*}
    store_preparation_payload {IS_SEQUENTIAL && NAME =~ *backend/captured_*}
    system_dispatch {IS_SEQUENTIAL && (NAME =~ *backend/head_reg* || NAME =~ *ledger/head_reg*)}
    bridge_credits {IS_SEQUENTIAL && NAME =~ *bridge/order/*_ptr*}
    store_dependency {IS_SEQUENTIAL && (NAME =~ *storeEnd*reg* || NAME =~ *storeSafeRange*reg* || NAME =~ *storeByteLanes*reg*)}
    fetch_cursor {IS_SEQUENTIAL && (NAME =~ *fetchPacket/rawCursor_reg* || NAME =~ *fetchPacket/correctionPc_reg*)}
    fabric_owner {IS_SEQUENTIAL && (NAME =~ *arbiter/occupied* || NAME =~ *crossbar*occupied*)}
} {
    set cells [get_cells -quiet -hier -filter $filter]
    puts "PATH_REVIEW $name startpoints=[llength $cells]"
    if {[llength $cells]} {
        report_timing -from $cells -to $cpu -delay_type max -max_paths 25 -nworst 1 -input_pins -file [file join $destination ${name}_setup.rpt]
    }
}
close_design
puts "PASS_READ_ONLY_RV64GC_PATH_REVIEW"
