# Read-only physical clock diagnosis. Do not publish altered attributes as a
# hardware-qualified checkpoint: this compares timing models in memory only.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
file copy [info script] executed_review.tcl
foreach cell [get_cells -hier -filter {REF_NAME =~ MMCM*}] {
    puts "EXISTING_MMCM $cell [get_property LOC $cell] [get_property COMPENSATION $cell]"
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
foreach site [get_sites -of_objects $region -filter {NAME =~ MMCM_X*}] {
    puts "RX_BANK_MMCM $site OCCUPANTS [get_cells -quiet -of_objects $site]"
}
set pll [get_cells native_rx_pll]
report_property $pll
puts "PLL_FEEDBACK_DRIVERS [get_pins -leaf -of_objects [get_nets -segments -of_objects [get_pins native_rx_pll/CLKFBIN]] -filter {DIRECTION == OUT}]"
foreach mode {AUTO BUF_IN INTERNAL} {
    set_property COMPENSATION $mode $pll
    foreach delay {max min} {
        report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type $delay -max_paths 1 -input_pins -file rx_${mode}_${delay}_model_only.rpt
    }
}
set_property COMPENSATION AUTO $pll
help opt_design
puts "RX_COMPENSATION_DIAG_COMPLETE READ_ONLY_NO_DCP_OR_BIT"
close_design
