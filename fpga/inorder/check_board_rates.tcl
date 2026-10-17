# STA-only rate scenarios on ONE routed board. Never calls implementation or
# writes the checkpoint; no CPU clock, payload CDC bound or PHY budget relaxation.
if {$argc ni {1 2}} {error "usage: check_board_rates.tcl ROUTED_BOARD_ROOT ?FRESH_REPORT_NAME?"}
set root [file normalize [lindex $argv 0]]
set checkpoint [file join $root reports real_board_routed.dcp]
set report_name [expr {$argc == 2 ? [lindex $argv 1] : "media-rates"}]
if {![regexp {^media-rates(-r[0-9]+)?$} $report_name]} {error "Use an isolated media report name"}
set output [file join $root reports $report_name]
if {![file isfile $checkpoint] || [file exists $output]} {
    error "One routed board and a fresh per-rate report directory required"
}
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
source [file join $root scripts trispeed_board_constraints.tcl]
# Vivado has no delete_clocks command. Its documented create_clock and
# create_generated_clock replace the SAME named in-memory clock without -add.
# Reapply ONLY the declared supported media-rate model; the original checkpoint,
# CPU/other generated clocks, physical routing, CDC budgets and exceptions stay
# untouched. These are STA scenarios, not PLL/PHY reconfiguration.
proc i1_report_media_model {mbps} {
    if {[llength [get_clocks -quiet {phy_rx phy_rx_launch phy_tx_capture}]] != 3} {
        error "Exactly the existing three media model clocks required"
    }
    valence_trispeed_quarter_audit u_rgmii
    set period [valence_trispeed_period $mbps]
    create_clock -name phy_rx -period $period -waveform [list 0 [expr {$period/2}]] [get_ports eth_rxc]
    set_clock_uncertainty 0.100 [get_clocks phy_rx]
    create_clock -name phy_rx_launch -period $period -waveform [list 2 [expr {$period/2+2}]]
    switch -- $mbps {
        1000 {set edges {2 4 6}}
        100 {set edges {2 12 22}}
        10 {set edges {2 102 202}}
        default {error "Only supported media STA rates are allowed"}
    }
    create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] \
        -edges $edges [get_ports eth_txc]
    foreach fall {0 1} {
        set extra {}
        if {$fall} {set extra {-clock_fall -add_delay}}
        set_input_delay -clock phy_rx_launch {*}$extra -max 1.050 [get_ports {eth_rxd[*] eth_rx_ctl}]
        set_input_delay -clock phy_rx_launch {*}$extra -min -1.050 [get_ports {eth_rxd[*] eth_rx_ctl}]
        set_output_delay -clock phy_tx_capture {*}$extra -max 1.250 [get_ports {eth_txd[*] eth_tx_ctl}]
        set_output_delay -clock phy_tx_capture {*}$extra -min -1.250 [get_ports {eth_txd[*] eth_tx_ctl}]
    }
    puts "I1_REPORT_ONLY_MEDIA_MODEL $mbps PHY_RX_BUDGET_1.050 TX_BUDGET_1.250 UNCHANGED"
}
report_utilization -file [file join $output utilization_flat.rpt]
report_clock_utilization -file [file join $output clock_utilization.rpt]
set domains [open [file join $output domains.tsv] w]
puts $domains "domain\tactual_clock\tperiod_ns\tdelay\tslack_ns\tstartpoint\tendpoint"
foreach {domain pin} {
    CPU300 u_soc/io_clockIn
    DDR_UI250 u_axi_cdc/m_axi_aclk
    AON50 u_soc/io_alwaysOnClock
    UART50 u_soc/io_uartClockIn
    MAC_FIXED125 u_soc/io_macTxClock
    RGMII_RX_RECOVERED u_soc/io_macRxClock
    RGMII_PAD250 u_rgmii/tx_pad_clock
    IDELAY_REF500 u_rgmii/delay_clock
} {
    set clock [get_clocks -of_objects [get_pins $pin]]
    if {[llength $clock] != 1} {error "Missing actual peripheral clock: $domain $pin"}
    foreach delay {max min} {
        set path [get_timing_paths -from $clock -to $clock -delay_type $delay -max_paths 1]
        if {[llength $path] != 1 || [get_property SLACK $path] in {inf -inf}} {
            error "Missing actual intra-domain setup/hold path: $domain $delay"
        }
        puts $domains [join [list $domain [get_property NAME $clock] [get_property PERIOD $clock] \
            $delay [get_property SLACK $path] [get_property STARTPOINT_PIN $path] \
            [get_property ENDPOINT_PIN $path]] "\t"]
        report_timing -from $clock -to $clock -delay_type $delay -max_paths 10 \
            -input_pins -file [file join $output [format "domain_%s_%s.rpt" $domain $delay]]
    }
}
close $domains
# AON/UART and the fixed MAC gates intentionally retain their existing common
# MMCM sources. An intra-clock row covers that actual source clock's sinks;
# hierarchy reports below distinguish the peripheral logic. This reporting
# does not merge, retime, rewire or reconfigure any hardware clock domain.
set scopes [file join $output internal-scopes]
file mkdir $scopes
foreach {name pattern} {
    backend u_soc/soc/core/core/*
    instruction_translation u_soc/soc/core/it/*
    data_translation u_soc/soc/core/dt/*
    icache u_soc/soc/core/icache/*
    dcache u_soc/soc/core/dcache/*
    coherent_fabric u_soc/soc/fabric/*
    network_dma u_soc/dma/*
    managed_peripherals u_soc/bank/*
    axi_clock_converter u_axi_cdc/*
    mig u_ddr/*
} {
    set cells [get_cells -quiet -hier -filter \
        "NAME =~ $pattern && (REF_NAME =~ FD* || REF_NAME =~ RAMB* || REF_NAME =~ DSP*)"]
    if {![llength $cells]} {error "Missing actual routed report hierarchy: $name $pattern"}
    foreach delay {max min} {
        report_timing -to $cells -delay_type $delay -max_paths 10 -nworst 1 \
            -input_pins -file [file join $scopes [format "%s_%s.rpt" $name $delay]]
    }
    puts "I1_ROUTED_SCOPE_REPORTED $name actual_sequential_cells=[llength $cells]"
}
set fd [open [file join $output lanes.tsv] w]
puts $fd "rate_mbps\tdirection\tport\tdelay\tslack_ns\tstartpoint\tendpoint"
foreach mbps {1000 100 10} {
    if {$mbps != 1000} {
        i1_report_media_model $mbps
    } else {
        # Re-prove exception topology AFTER all placement/route optimization.
        valence_trispeed_quarter_audit u_rgmii
    }
    set cpu [get_clocks -of_objects [get_pins u_soc/io_clockIn]]
    if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu]-10.0/3.0)>0.002} {
        error "CPU300 clock changed during media-only STA"
    }
    set period [valence_trispeed_period $mbps]
    foreach name {phy_rx phy_rx_launch phy_tx_capture} {
        set clock [get_clocks $name]
        if {abs([get_property PERIOD $clock]-$period)>0.002} {
            error "Actual media scenario period mismatch: $mbps $name"
        }
    }
    set dir [file join $output $mbps]
    file mkdir $dir
    report_clocks -file [file join $dir clocks.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained \
        -file [file join $dir timing_summary.rpt]
    foreach {direction ports} {tx {eth_txd[*] eth_tx_ctl} rx {eth_rxd[*] eth_rx_ctl}} {
        foreach port [get_ports $ports] {
            foreach delay {max min} {
                if {$direction eq "tx"} {
                    set path [get_timing_paths -to $port -delay_type $delay -max_paths 1]
                    report_timing -to $port -delay_type $delay -max_paths 10 -nworst 10 \
                        -file [file join $dir [format "%s_%s_%s.rpt" $direction $port $delay]]
                } else {
                    set path [get_timing_paths -from $port -delay_type $delay -max_paths 1]
                    report_timing -from $port -delay_type $delay -max_paths 10 -nworst 10 \
                        -file [file join $dir [format "%s_%s_%s.rpt" $direction $port $delay]]
                }
                if {[llength $path] != 1 || [get_property SLACK $path] in {inf -inf}} {
                    error "Untimed routed PHY data/control lane: $mbps $port $delay"
                }
                puts $fd [join [list $mbps $direction $port $delay [get_property SLACK $path] \
                    [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path]] "\t"]
            }
        }
    }
    flush $fd
    puts "I1_ROUTED_MEDIA_RATE_REPORTED rate=$mbps CPU300_UNCHANGED NO_REIMPLEMENTATION NO_WAIVER"
}
close $fd
close_design
