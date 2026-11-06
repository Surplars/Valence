# Cold JTAG launch. Check the supplied bit manifest for timing qualification.
# Usage: xsdb run_firmware.tcl <package-directory> [probe]
set root [file normalize [lindex $argv 0]]
source [file join $root handoff-address.tcl]
connect
targets -set -filter {name == "PSU"}
rst -system
after 1000
source [file join $root psu_init.tcl]
psu_init
# Stop the complete RPU group before exposing the newly configured PL.
targets -set -filter {name =~ "Cortex-R5 #0"}
rst -cores -stop -clear-registers
targets -set -filter {name == "PSU"}
fpga -file [file join $root i1_board.bit]
after 1000
psu_ps_pl_isolation_removal
after 1000
psu_ps_pl_reset_config
psu_post_config
targets -set -filter {name =~ "Cortex-R5 #0"}
dow [file join $root i1-rpu-firmware.elf]
# A warm JTAG system reset can retain DDR: invalidate old completion before launch.
targets -set -filter {name == "PSU"}
mwr $i1_rpu_report_address 0 2
mwr 0x4fff0040 0
mwr 0x4fff0100 0 22
targets -set -filter {name =~ "Cortex-R5 #0"}
con
targets -set -filter {name == "PSU"}
set deadline [expr {[clock milliseconds] + 15000}]
set phase 0
while {[clock milliseconds] < $deadline} {
    set phase [expr {[lindex [mrd -value $i1_rpu_report_address 1] 0] & 0xffffffff}]
    if {$phase == 7 || ($phase & 0x80000000)} {break}
    after 100
}
set status [lindex [mrd -value [expr {$i1_rpu_report_address + 4}] 1] 0]
set gpio [lindex [mrd -value 0xff0a006c 1] 0]
puts [format {RPU phase=0x%08x status=%u; PL started=%u} $phase $status [expr {($gpio >> 2) & 1}]]
if {$phase != 7 || $status != 0 || !(($gpio >> 2) & 1)} {
    puts [mrd $i1_rpu_report_address 8]
    error {RPU firmware publication/release failed}
}
puts RPU_FIRMWARE_RELEASED_NOT_OS_BOOT_ACCEPTANCE
if {[lindex $argv 1] eq "probe"} {
    proc read64 {address} {
        set words [mrd -value $address 2]
        return [expr {([lindex $words 0] & 0xffffffff) | (([lindex $words 1] & 0xffffffff) << 32)}]
    }
    set deadline [expr {[clock milliseconds] + 20000}]
    while {[clock milliseconds] < $deadline} {
        set done [read64 0x4fff0130]
        if {$done == 0x534d4f4445504153 || $done == 0xbad} {break}
        after 100
    }
    puts [mrd 0x4fff0100 22]
    if {$done != 0x534d4f4445504153 || [read64 0x4fff0100] != 0xbeef ||
        [read64 0x4fff0108] != 0x8fe00000 || [read64 0x4fff0110] != 0x03000000 ||
        [read64 0x4fff0118] != 1 || [read64 0x4fff0120] != 12 ||
        [read64 0x4fff0128] != 1 || [read64 0x4fff0138] != 0x8000000000080210} {
        error {OpenSBI S-mode/SBI/atomic/timer/Sv39 probe failed or timed out}
    }
    puts PASS_BOARD_OPENSBI_S_MODE_SBI_TIMER_SV39
}
