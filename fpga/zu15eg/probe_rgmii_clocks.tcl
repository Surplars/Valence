# Device/primitive property query only; no netlist changes or synthesis.
if {$argc != 1} {error "Expected ETHERNET_IP_DCP"}
open_checkpoint [lindex $argv 0]
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
puts "RGMII_REGION=$region"
puts "LOCAL_MMCMS=[get_sites -of_objects $region -filter {NAME =~ MMCM*}]"
foreach site [get_sites -filter {NAME =~ MMCM*}] {
    puts "DEVICE_MMCM $site [get_clock_regions -of_objects $site]"
}
puts "BUFG_REGION_PROPERTY=[lsearch -exact [list_property [get_cells inst/clkout1_buf]] CLOCK_REGION]"
close_design
