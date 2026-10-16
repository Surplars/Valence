proc diag_report {path command} {
    set code [catch {uplevel #0 $command} why options]
    set f [open [file join $::out report-status.tsv] a]
    puts $f [list $path [expr {$code ? {FAILED} : {EXPORTED}}] $why]
    close $f
    if {$code} {
        set e [open ${path}.error.txt w];puts $e $why;puts $e [dict get $options -errorinfo];close $e
        puts "REPORT_FAILED $path $why"
    }
    return $code
}
proc diag_reports {stage {full 1}} {
    set d [file join $::out reports $stage];file mkdir $d
    set cpu [get_clocks -of_objects [get_pins $::V_SOC_ROOT/clock]]
    foreach {name command} [list utilization [list report_utilization -hierarchical] timing_summary [list report_timing_summary -delay_type min_max -report_unconstrained] clocks [list report_clocks] check_timing [list check_timing -verbose] clock_interaction [list report_clock_interaction] exceptions [list report_exceptions -coverage] cdc [list report_cdc -details] bus_skew [list report_bus_skew] drc [list report_drc]] {
        diag_report [file join $d $name] [concat $command [list -file [file join $d ${name}.rpt]]]
    }
    foreach {delay mode} {max setup min hold} {
        set opts [list -delay_type $delay -max_paths 40 -nworst 3 -input_pins -nets -path_type full_clock_expanded]
        diag_report [file join $d $mode] [concat [list report_timing] $opts [list -file [file join $d ${mode}.rpt]]]
        diag_report [file join $d cpu_$mode] [concat [list report_timing -from $cpu -to $cpu] $opts [list -file [file join $d cpu_${mode}.rpt]]]
        foreach {dir names} {rx {eth_rxd[*] eth_rx_ctl} tx {eth_txd[*] eth_tx_ctl}} {
            set ports [get_ports -quiet $names]
            set side [expr {$dir eq {rx} ? {-from} : {-to}}]
            diag_report [file join $d ${dir}_${mode}] [concat [list report_timing $side $ports] $opts [list -file [file join $d ${dir}_${mode}.rpt]]]
        }
    }
    set async [get_pins -quiet -hier -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE}]
    foreach {delay mode} {max recovery min removal} {
        diag_report [file join $d $mode] [list report_timing -to $async -delay_type $delay -max_paths 40 -nworst 3 -input_pins -nets -path_type full_clock_expanded -file [file join $d ${mode}.rpt]]
    }
    if {$full} {diag_report [file join $d congestion] [list report_design_analysis -congestion -file [file join $d congestion.rpt]]}
    diag_report [file join $d constraints] [list write_xdc -force [file join $d actual-constraints.xdc]]
}