# Read-only preflight: do not synthesize, edit an IP, or modify license attributes.
if {$argc != 2} {
    error "Usage: check_ethernet_license.tcl <ethernet-xci> <report-dir>"
}
set xci [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
if {![file isfile $xci]} { error "Missing native Ethernet XCI: $xci" }
file mkdir $output
set projectDir [file join $output query-project]
if {[file exists $projectDir]} { error "Refusing to overwrite preflight project: $projectDir" }
create_project ethernet_license_check $projectDir -part xczu15eg-ffvb1156-2-i
read_ip $xci
if {[llength [get_ips -quiet axi_ethernet_0]] != 1} {
    error "Native Ethernet IP was not imported; license check is inconclusive"
}
report_ip_status -file [file join $output ip_status.rpt]
foreach ip [get_ips] {
    puts "IP_LICENSE_PREFLIGHT name=$ip definition=[get_property IPDEF $ip]"
    foreach property [list_property $ip] {
        if {[regexp -nocase {license} $property]} {
            puts "IP_LICENSE_PROPERTY $ip $property=[get_property $property $ip]"
        }
    }
}
puts "ETHERNET_LICENSE_PREFLIGHT_COMPLETE"
close_project
