# Fresh standalone IP project; never opens or modifies the user's ZU15EG project.
if {$argc != 1} { error "usage: generate_ethernet_ip.tcl FRESH_PROJECT_DIR" }
set output [file normalize [lindex $argv 0]]
if {[file exists $output]} { error "Use a fresh IP project directory" }
create_project ethernet_ip $output -part xczu15eg-ffvb1156-2-i
set_param general.maxThreads 8
create_ip -name axi_ethernet -vendor xilinx.com -library ip -version 7.2 -module_name axi_ethernet_0
set ip [get_ips axi_ethernet_0]
set_property -dict [list CONFIG.PHY_TYPE RGMII CONFIG.speed_1_2p5 1G \
    CONFIG.processor_mode true CONFIG.SupportLevel 1 CONFIG.axiliteclkrate 125.0 \
    CONFIG.axisclkrate 125.0 CONFIG.TXMEM 4k CONFIG.RXMEM 4k \
    CONFIG.TXCSUM None CONFIG.RXCSUM None CONFIG.Enable_1588 false CONFIG.ENABLE_AVB false] $ip
report_property $ip -file [file join $output ethernet_properties.rpt]
report_ip_status -file [file join $output ip_status.rpt]
generate_target all $ip
export_ip_user_files -of_objects $ip -no_script -sync -force -quiet
puts "ETHERNET_IP_GENERATED [get_property IP_FILE $ip]"
close_project
