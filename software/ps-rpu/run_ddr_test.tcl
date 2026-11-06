# Cold JTAG boot only. Performs PS/DDR initialization and runs the RPU DDR test.
# Usage: xsdb run_ddr_test.tcl <bringup-package-directory>
set root [file normalize [lindex $argv 0]]
source [file join $root ddr-test-address.tcl]
connect
targets -set -filter {name == "PSU"}
rst -system
after 1000
source [file join $root psu_init.tcl]
psu_init
targets -set -filter {name =~ "Cortex-R5 #0"}
rst -cores -stop -clear-registers
dow [file join $root i1-rpu-ddr-test.elf]
con
targets -set -filter {name == "PSU"}
set deadline [expr {[clock milliseconds] + 15000}]
set phase 0
while {[clock milliseconds] < $deadline} {
    # XSDB -value returns numbers, not hexadecimal text.
    set phase [expr {[lindex [mrd -value $i1_rpu_report_address 1] 0] & 0xffffffff}]
    if {$phase == 6 || ($phase & 0x80000000)} {break}
    after 100
}
after 100
puts [mrd $i1_rpu_report_address 5]
if {$phase != 6} {error [format {RPU DDR test failed or timed out: phase=0x%08x} $phase]}
puts PASS_RPU_DDR_HANDOFF_WINDOW_TEST
