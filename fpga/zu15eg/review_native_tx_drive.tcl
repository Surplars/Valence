# Diagnostic only: reuses the completed routed DCP, changes drive strength
# in memory and queries all real pad setup/hold checks. No reroute/DCP/bit write.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_REPORT_DIRECTORY"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve previous drive review"}
file mkdir $out
set_param general.maxThreads 4
open_checkpoint $dcp
set outputs [lsort [get_ports {eth_txd[*] eth_tx_ctl}]]
if {[llength $outputs]!=5} {error "Expected five real TX lanes"}
set txc [get_ports eth_txc]
if {[llength $txc]!=1} {error "Expected forwarded TX clock pad"}
foreach port [concat $outputs $txc] {
    if {[get_property IOSTANDARD $port] ne "LVCMOS18" || [get_property SLEW $port] ne "FAST"} {
        error "Unexpected electrical mode: $port"
    }
}
set f [open [file join $out drive_review.csv] w]
puts $f "clock_drive,data_drive,pin,setup_ns,hold_ns"
foreach clockDrive {4 6 8 12 16} {
    set_property DRIVE $clockDrive $txc
    foreach dataDrive {4 6 8 12 16} {
        set_property DRIVE $dataDrive $outputs
        update_timing
        foreach port $outputs {
            set maximum [get_timing_paths -to $port -delay_type max -max_paths 1]
            set minimum [get_timing_paths -to $port -delay_type min -max_paths 1]
            if {[llength $maximum]!=1 || [llength $minimum]!=1} {error "Missing real TX path: $port"}
            puts $f "$clockDrive,$dataDrive,$port,[get_property SLACK $maximum],[get_property SLACK $minimum]"
        }
        flush $f
        puts "NATIVE_TX_DRIVE_REVIEW clock=$clockDrive data=$dataDrive"
    }
}
close $f
close_design
puts "REVIEW_ONLY_NO_CANDIDATE_OR_BIT_WRITTEN"
