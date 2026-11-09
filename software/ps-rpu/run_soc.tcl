# Cold JTAG launch. Check the supplied bit manifest for timing qualification.
# Usage: xsdb run_soc.tcl <package-directory>
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
dow [file join $root i1-rpu-handoff.elf]
# A warm JTAG system reset can retain DDR: invalidate old completion before launch.
targets -set -filter {name == "PSU"}
mwr $i1_rpu_report_address 0 2
mwr 0x4fff0040 0
targets -set -filter {name =~ "Cortex-R5 #0"}
con
targets -set -filter {name == "PSU"}
set deadline [expr {[clock milliseconds] + 15000}]
set phase 0
while {[clock milliseconds] < $deadline} {
    # XSDB -value returns numbers, not hexadecimal text.
    set phase [expr {[lindex [mrd -value $i1_rpu_report_address 1] 0] & 0xffffffff}]
    if {$phase == 5 || ($phase & 0x80000000)} {break}
    after 100
}
after 100
set report [mrd -value $i1_rpu_report_address 2]
set phase [expr {[lindex $report 0] & 0xffffffff}]
set status [lindex $report 1]
set gpio [lindex [mrd -value 0xff0a006c 1] 0]
set mailbox [mrd -value 0x4fff0040 18]
puts [format {RPU phase=0x%08x status=%u; PL started=%u; RV state=0x%08x error=%u} $phase $status [expr {($gpio >> 2) & 1}] [lindex $mailbox 0] [lindex $mailbox 1]]
puts [format {RV misa=0x%08x%08x CRC=0x%08x checksum=0x%08x} [lindex $mailbox 7] [lindex $mailbox 6] [lindex $mailbox 2] [lindex $mailbox 3]]
if {$phase != 5 || $status != 0} {
    puts [mrd $i1_rpu_report_address 70]
    puts [mrd 0x4fff0000 35]
    error [format {RPU/RV handoff failed or timed out: phase=0x%08x status=%u} $phase $status]
}
puts PASS_RPU_LOADED_RV_REAL_DDR_SELFTEST
