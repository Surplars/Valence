# Current full RV64GC/native quarter-TX bit release, NOT the legacy CPU partition.
# Never changes timing exceptions, clock budgets, placement or logic.
if {$argc ni {5 6}} {error "Expected CANDIDATE_ROOT OWN_ROUTED_DCP QUALIFIED_CONTRACT PYTHON_EXE FRESH_OUTPUT_DIRECTORY ?r3|r4|r5|r6|current-candidate?"}
lassign $argv root checkpoint contract python output releaseTag
if {$argc == 5} {set releaseTag r3}
if {$releaseTag ni {r3 r4 r5 r6 current-candidate}} {error "Unknown release tag"}
foreach name {root checkpoint contract python output} {set $name [file normalize [set $name]]}
set implementation [expr {$releaseTag in {r5 r6 current-candidate} ? "implementation" : "implementation-report-recovery-r1"}]
if {$checkpoint ne [file normalize [file join $root $implementation routed.dcp]]} {
    error "Only this candidate's own source-integrated recovered route is allowed"
}
if {$output ne [file normalize [file join $root release-rv64gc100-u460800-$releaseTag]] || [file exists $output]} {
    error "Expected this candidate's fresh named release output; preserve prior artifacts"
}
set checker [file join [file dirname [info script]] verify_native_release_contract.py]
if {$releaseTag in {r5 r6}} {set checker [file join [file dirname [info script]] verify_ddr2g_release.py]}
if {$releaseTag eq "current-candidate"} {set checker [file join [file dirname [info script]] verify_current_candidate_release.py]}
# Isolated Python ignores Vivado's bundled PYTHONHOME/PYTHONPATH. -B avoids
# writing pycache into the user's repository. No subprocess writes or COM I/O.
puts [exec $python -B -I $checker --contract $contract --dcp $checkpoint]
set rom [file join $root ip-build board_ip.gen sources_1 ip blk_mem_gen_0 blk_mem_gen_0.dcp]
set_param general.maxThreads 8
open_checkpoint $rom
set expectedRom [dict create]
foreach cell [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}] {
    foreach property [list_property $cell] {
        if {[regexp {^INIT(P)?_[0-9A-F]{2}$} $property]} {
            dict set expectedRom "u_soc/platform/rom/memory/[get_property NAME $cell]/$property" [get_property $property $cell]
        }
    }
}
if {[dict size $expectedRom]!=4176} {error "Incomplete selected BootROM INIT/INITP"}
close_design
open_checkpoint $checkpoint
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong FPGA part"}
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black boxes remain"}
if {[llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]]!=1} {error "Missing actual RV64GC FPU"}
if {[llength [get_cells -quiet -hier -filter {REF_NAME == clk_wiz_eth}]]} {error "Legacy Ethernet IP must not replace native MAC"}
dict for {key expected} $expectedRom {
    set split [string last / $key]
    set cell [get_cells -quiet [string range $key 0 [expr {$split-1}]]]
    set property [string range $key [expr {$split+1}] end]
    if {[llength $cell]!=1 || [get_property $property $cell] ne $expected} {error "Implemented BootROM differs: $key"}
}
foreach {pin period} {
    u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0
    u_soc/nativeBank/uart/uart/clock 20.0 u_soc/io_nativeGmac_rawTxClock 8.0
    u_rgmii/delay_clock 2.0 u_rgmii/tx_clock_ddr/CLK 4.0 u_ddr/c0_ddr4_ui_clk 4.0
} {
    set endpoint [get_pins -quiet $pin]
    if {[llength $endpoint]!=1} {error "Missing actual clock endpoint $pin"}
    set clock [get_clocks -quiet -of_objects $endpoint]
    if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-$period)>0.001} {error "Wrong actual board clock $pin"}
}
source [file join $root scripts native_quarter_clock_constraints.tcl]
valence_quarter_tx_audit u_rgmii
foreach delay {max min} {
    set path [get_timing_paths -delay_type $delay -max_paths 1]
    if {[llength $path]!=1 || [get_property SLACK $path] in {inf -inf} || [get_property SLACK $path]<0} {
        error "Actual routed setup/hold failure"
    }
}
foreach direction {tx rx} {
    set ports [get_ports [list eth_${direction}d\[*\] eth_${direction}_ctl]]
    if {[llength $ports]!=5} {error "Missing physical $direction lanes"}
    foreach port $ports {
        foreach delay {max min} {
            if {$direction eq "tx"} {set path [get_timing_paths -to $port -delay_type $delay -max_paths 1]} \
            else {set path [get_timing_paths -from $port -delay_type $delay -max_paths 1]}
            if {[llength $path]!=1 || [get_property SLACK $path] in {inf -inf} || [get_property SLACK $path]<0} {
                error "Physical $direction lane is untimed or fails: $port"
            }
            if {$direction eq "tx"} {
                set expected [expr {$delay eq "max" ? 2.0 : -2.0}]
                if {abs([get_property REQUIREMENT $path]-$expected)>0.001} {error "TX edge relationship changed"}
            }
        }
    }
}
file mkdir $output
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_summary.rpt]
report_route_status -file [file join $output route_status.rpt]
report_bus_skew -file [file join $output bus_skew.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
report_cdc -details -file [file join $output cdc_release.rpt]
report_drc -ruledeck bitstream_checks -file [file join $output bitstream_drc.rpt]
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]} {
    error "Bitstream DRC errors/critical warnings"
}
proc native_release_read {path} {
    set f [open $path r]; set text [read $f]; close $f
    return $text
}
set timing [native_release_read [file join $output timing_summary.rpt]]
set numeric {}
foreach line [split $timing "\n"] {
    if {[regexp {^\s+-?[0-9]+\.[0-9]+\s+-?[0-9]+\.[0-9]+\s+[0-9]+\s+[0-9]+\s+-?[0-9]+\.[0-9]+} $line]} {
        set numeric [regexp -all -inline {[-]?[0-9]+(?:\.[0-9]+)?} $line]
        break
    }
}
if {[llength $numeric]!=12} {error "Cannot validate actual complete setup/hold/pulse summary"}
foreach index {0 4 8} {if {[lindex $numeric $index]<0} {error "Setup/hold/pulse failure"}}
foreach index {1 2 5 6 9 10} {if {[lindex $numeric $index]!=0} {error "Timing failing endpoint/total remains"}}
set coverage [native_release_read [file join $output check_timing.rpt]]
foreach name {no_clock unconstrained_internal_endpoints generated_clocks loops multiple_clock latch_loops} {
    if {![regexp [format {checking %s \(0\)} $name] $coverage]} {error "Timing coverage failure: $name"}
}
set skew [native_release_read [file join $output bus_skew.rpt]]
if {[regexp -all {Slack \(MET\)} $skew]<27 || [string first VIOLATED $skew]>=0} {error "Bus-skew checks missing/failing"}
set route [native_release_read [file join $output route_status.rpt]]
foreach {label variable} {"routable nets" routable "fully routed nets" fully "nets with routing errors" errors} {
    if {![regexp [format {%s\.+\s*:\s*([0-9]+)} $label] $route -> $variable]} {error "Missing route statistic $label"}
}
if {$routable!=$fully || $errors!=0} {error "Incomplete routing"}
# Recheck the CURRENT reopened-netlist CDC inventory against the reviewed
# fingerprints, not zero Critical counts or a broad CDC waiver.
puts [exec $python -B -I $checker --contract $contract --dcp $checkpoint \
    --cdc-report [file join $output cdc_release.rpt]]
set signoff [open [file join $output static-signoff.txt] w]
puts $signoff "PROFILE=RV64GC F_D=ON ISSUE_WIDTH=2 CPU_HZ=100000000 UART_BAUD=460800"
if {$releaseTag eq "r5"} {puts $signoff "DDR_BYTES=2147483648 RAM_BASE=0x80200000 END_EXCLUSIVE=0x100200000 MONITOR_RESERVED=0xffff8000..0xffffc000"}
puts $signoff "ACTUAL_BOOTROM_INIT_MATCH=4176 ROM_WORD_IDENTITY=32768 PHY_TXDLY=OFF_BY_SOFTWARE PHY_RXDLY=ON"
puts $signoff "Setup/hold/pulse/IO/coverage/routing/bus-skew/bitstream DRC and current documented CDC review: PASS"
puts $signoff "No constraint budgets, false paths, clock frequencies or logic changed for release."
puts $signoff "Static qualification is not physical UART/DDR/GMAC/Linux floating-point-context proof."
if {$releaseTag eq "current-candidate"} {
    puts $signoff "EXPERIMENTAL_CURRENT_CANDIDATE_BIT_NOT_PRODUCTION_PLATFORM_OR_BSP_RELEASE"
    puts $signoff "CDC evidence is current structural/held-payload/Gray/reset review, not full independent CDC protocol signoff."
    puts $signoff "Common cold reset and stable ownership assumptions remain required. Board/software/runtime remain unverified."
}
close $signoff
write_checkpoint [file join $output qualified_routed.dcp]
set bit [file join $output valence_native_rv64gc_2issue_cpu100_u460800_${releaseTag}.bit]
write_bitstream $bit
puts "PASS_NATIVE_RV64GC100_BITSTREAM_GENERATED $bit"
close_design
