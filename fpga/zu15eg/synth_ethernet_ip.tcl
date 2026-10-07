# Synthesize the generated real IP once; license errors remain errors, never stubbed.
if {$argc != 1} { error "usage: synth_ethernet_ip.tcl IP_PROJECT_XPR" }
open_project [file normalize [lindex $argv 0]]
set_param general.maxThreads 8
create_ip_run [get_ips axi_ethernet_0]
set ipRun [get_runs axi_ethernet_0_synth_1]
if {[llength $ipRun] != 1} { error "real Ethernet IP synthesis run missing" }
launch_runs $ipRun -jobs 4
wait_on_run $ipRun
set status [get_property STATUS $ipRun]
if {$status ne "synth_design Complete!"} {
    error "real Ethernet IP synthesis failed: $status; inspect its runme.log"
}
if {![file exists [file join [get_property DIRECTORY $ipRun] axi_ethernet_0.dcp]]} {
    error "real Ethernet IP checkpoint missing after synthesis"
}
report_ip_status -file [file join [get_property DIRECTORY [current_project]] post_synth_ip_status.rpt]
puts "ETHERNET_IP_SYNTH_COMPLETE"
close_project
