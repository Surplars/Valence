# Read-only final-checkpoint audit. Unknown mapping/format/coverage is BLOCKED.
# common_cdc.tcl contains definitions only: no mutation occurs when sourced here.
source [file join [file dirname [info script]] common_cdc.tcl]
namespace eval common_board {variable constants {}; variable critical null}
proc common_board::json {s} {return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $s]\""}
proc common_board::object {dictionary} {
    set rows {}; dict for {k v} $dictionary {lappend rows "[json $k]:[json $v]"}; return "\{[join $rows ,]\}"
}
proc common_board::net {pin} {
    variable constants
    set nets [get_nets -quiet -segments -of_objects $pin]
    if {![llength $nets]} {error "COMMON_BOARD disconnected net [get_property NAME $pin]"}
    set name [lindex [common_cdc::names $nets] 0]
    foreach n $nets {
        set type [get_property TYPE $n]
        if {$type in {GROUND POWER}} {dict set constants $name [expr {$type eq "POWER" ? 1 : 0}]}
    }
    return $name
}
proc common_board::rom_dump {root output} {
    variable constants; set constants {}; set ports {}; set rows {}
    set boundary [common_cdc::one get_cells $root]
    if {[get_property IS_BLACKBOX $boundary] in {1 TRUE true}} {error "COMMON_ROM unimplemented IP"}
    foreach p [get_pins -of_objects $boundary] {dict set ports [get_property REF_PIN_NAME $p] [net $p]}
    foreach c [get_cells -quiet -hier -filter {IS_PRIMITIVE == TRUE}] {
        set name [get_property NAME $c]
        if {[string first $root/ $name]!=0} {continue}
        set ref [get_property REF_NAME $c]; set pins {}; set outputs {}; set props {}; set inverted {}
        foreach p [get_pins -of_objects $c] {
            set pn [get_property REF_PIN_NAME $p]; dict set pins $pn [net $p]
            if {[get_property DIRECTION $p] eq "OUT"} {lappend outputs [json $pn]}
            if {$pn in {C CLKARDCLK CLKBWRCLK ENARDEN ENBWREN RSTRAMARSTRAM RSTRAMB RSTREGARSTREG RSTREGB}} {
                if {[get_property IS_INVERTED $p] ni {0 FALSE false}} {lappend inverted [json $pn]}
            }
        }
        if {$ref eq "RAMB36E2"} {
            foreach key {READ_WIDTH_A READ_WIDTH_B WRITE_WIDTH_A WRITE_WIDTH_B DOA_REG DOB_REG EN_ECC_READ EN_ECC_WRITE} {dict set props $key [get_property $key $c]}
            for {set i 0} {$i<128} {incr i} {set key [format INIT_%02X $i]; dict set props $key [get_property $key $c]}
            for {set i 0} {$i<16} {incr i} {set key [format INITP_%02X $i]; dict set props $key [get_property $key $c]}
        } elseif {[string match LUT* $ref] || [string match FD* $ref]} {dict set props INIT [get_property INIT $c]}
        lappend rows [format {{"name":%s,"ref":%s,"pins":%s,"outputs":[%s],"properties":%s,"inverted_pins":[%s]}} [json $name] [json $ref] [object $pins] [join $outputs ,] [object $props] [join $inverted ,]]
    }
    if {![llength $rows]} {error "COMMON_ROM no mapped primitives under $root"}
    set f [open $output w]
    puts $f [format {{"root":%s,"ports":%s,"constants":%s,"cells":[%s]}} [json $root] [object $ports] [object $constants] [join $rows ,]]
    close $f
}
proc common_board::rom {} {
    global valence
    foreach key {rom python} {if {![info exists valence($key)]} {error "COMMON_ROM missing frozen $key binding"}}
    set dump [file join $valence(out) rom-netlist.json]
    rom_dump u_soc/fabric/rom/memory $dump
    set result [exec $valence(python) -E [file join $valence(root) fpga common rom_audit.py] --netlist $dump --rom $valence(rom) --output [file join $valence(out) rom-mapping.json]]
    if {[string trim $result] ne "COMMON_ROM_CONTENT_MAPPING_PASS"} {error "COMMON_ROM no verified content/mapping result"}
}
proc common_board::cpu {} {
    global valence
    if {![info exists valence(cpu)] || $valence(cpu) ni {i1 a1}} {error "COMMON_CPU missing selected CPU"}
    set expected [expr {$valence(cpu) eq "i1" ? "CommonI1CpuTile" : "CommonA1CpuTile"}]
    set other [expr {$valence(cpu) eq "i1" ? "CommonA1CpuTile*" : "CommonI1CpuTile*"}]
    set cpu [common_cdc::one get_cells u_soc/cpu]
    if {![string match $expected* [get_property REF_NAME $cpu]] || [llength [get_cells -quiet -hier -filter "REF_NAME =~ $other"]]} {error "COMMON_CPU selected core hierarchy mismatch"}
    set clk [common_cdc::clock u_soc/cpuClock]; set fabric [common_cdc::clock u_soc/fabricClock]
    set profile production
    if {[info exists valence(clock_profile)]} {set profile $valence(clock_profile)}
    if {$profile ni {production boot50-static performance300-static}} {error "COMMON_CPU unreviewed clock profile"}
    if {$profile eq "performance300-static" && $valence(cpu) ne "i1"} {error "COMMON_CPU performance300 is I1-only"}
    set hz [expr {$profile eq "boot50-static" ? 50000000 : $valence(cpu) eq "i1" ? 300000000 : 100000000}]
    set fabricHz [expr {$profile eq "boot50-static" ? 50000000 : 250000000}]
    if {$clk eq $fabric || abs([get_property PERIOD [get_clocks $clk]]-1.0e9/$hz)>0.002 || abs([get_property PERIOD [get_clocks $fabric]]-1.0e9/$fabricHz)>0.002} {error "COMMON_CPU selected CPU/fabric clock mismatch"}
    if {$profile in {boot50-static performance300-static}} {
        set fixed [common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing]
        if {$fixed eq $fabric || abs([get_property PERIOD [get_clocks $fixed]]-4.0)>0.002} {error "COMMON_CPU fixed UI/time/debug250 topology mismatch"}
        common_cdc::same_net u_soc/fabricClock u_clk_wiz/clk_out3
        common_cdc::one get_cells u_soc/ddrCrossing
    } else {
        common_cdc::same_net u_soc/fabricClock u_ddr/c0_ddr4_ui_clk
    }
    foreach pin {u_soc/alwaysOnClock u_soc/rawUartClock} {
        if {abs([get_property PERIOD [get_clocks [common_cdc::clock $pin]]]-20.0)>0.002} {error "COMMON_CPU fixed AON/UART50 mismatch"}
    }
}
proc common_board::release {prefix report} {
    set cells [common_cdc::bank $prefix 3]; set clk [common_cdc::clock [lindex $cells 0]/C]
    foreach c $cells {common_cdc::ff $c $clk 1; if {[get_property REF_NAME [common_cdc::one get_cells $c]] ne "FDPE"} {error "COMMON_RESET async-set release expected $c"}}
    common_cdc::constant [lindex $cells 0]/D 0
    for {set i 1} {$i<3} {incr i} {
        set a [lindex $cells [expr {$i-1}]]; set b [lindex $cells $i]
        common_cdc::same_net $a/PRE $b/PRE
        if {[common_cdc::drivers $b/D] ne [list $a/Q] || [common_cdc::loads $a/Q] ne [list $b/D]} {error "COMMON_RESET indirect/intermediate fanout $prefix"}
        foreach kind {max min} {
            set p [get_timing_paths -quiet -from [common_cdc::one get_pins $a/C] -to [common_cdc::one get_pins $b/D] -delay_type $kind -max_paths 1]
            if {[llength $p]!=1 || ![string is double -strict [get_property SLACK $p]] || [get_property SLACK $p]<0} {error "COMMON_RESET interstage $kind not timed/met $prefix"}
        }
    }
    set q [lindex $cells 2]/Q
    puts $report [list RELEASE $prefix CLOCK=$clk FINAL=$q]
    return [list $q $clk]
}
proc common_board::reset_source {control releases} {
    # Preserve the positive-asserting reset-release meaning through mapped
    # LUT1 buffers/inverters. A name-only LUT allowance is never sufficient.
    set pin $control; set parity 0
    for {set depth 0} {$depth<5} {incr depth} {
        set drivers [common_cdc::drivers $pin]
        if {[llength $drivers]!=1} {error "COMMON_RESET ambiguous reset driver $pin"}
        set driver [lindex $drivers 0]
        if {[dict exists $releases $driver]} {
            set inverted [get_property IS_INVERTED [common_cdc::one get_pins $control]]
            if {$inverted ni {0 1 FALSE TRUE false true}} {error "COMMON_RESET unknown control polarity $control"}
            if {$parity != ($inverted in {1 TRUE true})} {error "COMMON_RESET wrong assertion polarity $control"}
            return $driver
        }
        set cell [get_cells -of_objects [common_cdc::one get_pins $driver]]
        if {[llength $cell]!=1 || [get_property REF_NAME $cell] ne "LUT1" || [get_property REF_PIN_NAME [common_cdc::one get_pins $driver]] ne "O"} {break}
        set init [string tolower [get_property INIT $cell]]
        if {$init in {2'h1 2'b01 1 0x1}} {set parity [expr {$parity ^ 1}]} elseif {$init ni {2'h2 2'b10 2 0x2}} {error "COMMON_RESET non-buffer LUT1 $driver"}
        set pin [get_property NAME $cell]/I0
    }
    error "COMMON_RESET unreviewed functional reset logic $control"
}
proc common_board::resets {} {
    global valence
    set report [open [file join $valence(out) reset-structure.tcllist] w]
    try {
        set releases [dict create]
        foreach prefix {ui_reset_pipe_reg delay_reset_pipe_reg phy_reset_pipe_reg rx_reset_pipe_reg} {
            lassign [release $prefix $report] q clk; dict set releases $q $clk
        }
        foreach c [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {
            set n [get_property NAME $c]
            if {[string first u_soc/ $n]!=0} {continue}
            lassign [release $n/release_0_reg $report] q clk; dict set releases $q $clk
        }
        if {[dict size $releases]<6} {error "COMMON_RESET missing domain release chains"}
        common_cdc::same_net {ui_reset_pipe_reg[2]/Q} u_soc/commonColdReset
        set functional 0
        foreach c [get_cells -quiet -hier -filter {REF_NAME == FDCE || REF_NAME == FDPE}] {
            set n [get_property NAME $c]; if {[string first u_soc/ $n]!=0 || [get_property ASYNC_REG $c] in {TRUE true 1}} {continue}
            set control [expr {[get_property REF_NAME $c] eq "FDPE" ? "PRE" : "CLR"}]
            set launch [reset_source $n/$control $releases]; set clk [dict get $releases $launch]
            if {[common_cdc::clock $n/C] ne $clk} {error "COMMON_RESET functional reset released in other clock $n"}
            foreach kind {max min} {
                set p [get_timing_paths -quiet -from [common_cdc::one get_pins $launch] -to [common_cdc::one get_pins $n/$control] -delay_type $kind -max_paths 1]
                if {[llength $p]!=1 || ![string is double -strict [get_property SLACK $p]] || [get_property SLACK $p]<0} {error "COMMON_RESET functional recovery/removal cut/failing $n $kind"}
            }
            incr functional
        }
        if {!$functional} {error "COMMON_RESET no functional loads proved"}
        puts $report "FUNCTIONAL_RESET_LOADS $functional"
    } finally {close $report}
}
proc common_board::payloads {} {
    global valence
    set f [open [file join $valence(out) held-payload-mapping.tcllist] w]
    try {
        foreach scope $::common_cdc::scopes {
            if {[dict exists $scope by_end]} {puts $f $scope}
        }
        foreach h $::common_cdc::inactive_scopes {puts $f [list PROVEN_INACTIVE $h]}
    } finally {close $f}
}
proc common_board::cdc {} {
    global valence
    variable critical
    set scopes [common_cdc::collect]
    common_cdc::audit_timing $scopes $valence(out)
    payloads
    report_cdc -details -file [file join $valence(out) board-cdc.rpt]
    set f [open [file join $valence(out) board-cdc.rpt]]; set text [read $f]; close $f
    # Accept only the known summary table: rule ID | severity | description | count.
    # Detail-row counting or absence of the word Critical is not a zero proof.
    set rows 0; set critical 0
    foreach line [split $text \n] {
        if {[regexp {^\s*\|\s*CDC-[0-9]+\s*\|\s*(Critical|Warning|Info)\s*\|[^|]*\|\s*([0-9]+)\s*\|\s*$} $line -> severity count]} {
            incr rows; if {$severity eq "Critical"} {incr critical $count}
        }
    }
    if {!$rows} {set critical null; error "COMMON_CDC unsupported report_cdc summary; cannot prove critical count"}
    if {$critical} {error "COMMON_CDC $critical unreviewed Critical crossings; no implicit reset/data waiver"}
    # Validate exact bus endpoints and budgets, not just total count of MET rows.
    set f [open [file join $valence(out) common-bus-skew.rpt]]; set text [read $f]; close $f
    set expected 0
    foreach scope $scopes {
        if {![dict get $scope skew]} {continue}; incr expected
        set found 0
        foreach endpoint [dict get $scope ends] {
            if {[string first $endpoint $text]>=0} {set found 1}
        }
        if {!$found} {error "COMMON_CDC skew report lacks a worst endpoint from [dict get $scope label]"}
    }
    set matches [regexp -all -inline {Slack\s+\((MET|VIOLATED)\)\s*:\s*(-?[0-9.]+)ns} $text]
    if {[llength $matches]/3 != $expected} {error "COMMON_CDC skew constraint count changed/unsupported report"}
    foreach {whole state slack} $matches {if {$state ne "MET" || ![string is double -strict $slack] || $slack<0} {error "COMMON_CDC bus skew violation"}}
}
proc common_board::io_report {text port_names} {
    set keys {no_input_delay partial_input_delay no_output_delay partial_output_delay}
    set counts {}; set bodies {}; set active {}
    foreach line [split $text \n] {
        if {[regexp {checking\s+([a-z_]+)\s+\(([0-9]+)\)} $line -> key count]} {
            set active {}
            if {$key in $keys} {
                if {[dict exists $counts $key]} {error "COMMON_IO duplicate coverage section $key"}
                dict set counts $key $count; dict set bodies $key {}; set active $key
            }
        } elseif {$active ne ""} {dict append bodies $active "$line\n"}
    }
    set result {}
    foreach key $keys {
        if {![dict exists $counts $key]} {error "COMMON_IO missing/unknown check_timing format for $key"}
        set found {}
        foreach name $port_names {
            set pattern [format {(^|[[:space:]|:])%s($|[[:space:]|,])} [common_cdc::quote $name]]
            if {[regexp -line $pattern [dict get $bodies $key]]} {lappend found $name}
        }
        if {[llength $found] != [dict get $counts $key]} {error "COMMON_IO incomplete/unknown endpoint listing for $key"}
        if {[string match partial_* $key] && [llength $found]} {error "COMMON_IO partial min/max delay coverage: $key $found"}
        dict set result $key $found
    }
    return $result
}
proc common_board::input_sync {port first second} {
    set clock [common_cdc::clock $first/C]
    common_cdc::ff $first $clock 1; common_cdc::ff $second $clock 1
    if {[common_cdc::drivers $second/D] ne [list $first/Q] || [common_cdc::loads $first/Q] ne [list $second/D]} {error "COMMON_IO non-direct two-stage input synchronizer $port"}
    set endpoints [common_cdc::names [all_fanout -flat -endpoints_only -from [get_ports $port]]]
    if {$endpoints ne [list $first/D]} {error "COMMON_IO asynchronous input has unreviewed endpoint/fanout $port: $endpoints"}
    foreach kind {max min} {
        set p [get_timing_paths -quiet -from [common_cdc::one get_pins $first/C] -to [common_cdc::one get_pins $second/D] -delay_type $kind -max_paths 1]
        if {[llength $p]!=1 || ![string is double -strict [get_property SLACK $p]] || [get_property SLACK $p]<0} {error "COMMON_IO input interstage $kind missing/failing $port"}
    }
    set budget [expr {$port eq "uart_rxd" ? 20.0 : 10.0}]
    set p [get_timing_paths -quiet -from [get_ports $port] -to [common_cdc::one get_pins $first/D] -delay_type max -max_paths 1]
    if {[llength $p]!=1} {error "COMMON_IO missing asynchronous pad-to-first-stage bound $port"}
    set req [get_property REQUIREMENT $p]; set slack [get_property SLACK $p]
    set exception [string tolower [string map {_ {} - {} { } {}} [get_property EXCEPTION $p]]]
    if {![string is double -strict $req] || ![string is double -strict $slack] || $req<=0 || $req>$budget+0.001 || $slack<0 || ![string match maxdelay* $exception]} {error "COMMON_IO missing/relaxed/failing first-stage max-delay $port"}
}
proc common_board::io {} {
    global valence
    set path [file join $valence(out) io-coverage.rpt]
    check_timing -override_defaults {no_input_delay partial_input_delay no_output_delay partial_output_delay} -verbose -file $path
    set f [open $path]; set text [read $f]; close $f
    set coverage [io_report $text [common_cdc::names [get_ports -quiet]]]
    set facts [open [file join $valence(out) io-allowances.tcllist] w]
    try {
        foreach port [dict get $coverage no_input_delay] {
            switch -- $port {
                uart_rxd {input_sync $port u_soc/peripherals/uart/sampledRx_meta_reg u_soc/peripherals/uart/sampledRx_reg}
                eth_mdio {input_sync $port {u_soc/peripherals/gmac/mdio_io_mdioIn_sync/stages_reg[0]} {u_soc/peripherals/gmac/mdio_io_mdioIn_sync/stages_reg[1]}}
                sys_rst_n - button_n {
                    set endpoints [all_fanout -flat -endpoints_only -from [get_ports $port]]
                    if {![llength $endpoints]} {error "COMMON_IO asynchronous reset has no endpoints $port"}
                    foreach endpoint $endpoints {
                        set cell [get_cells -quiet -of_objects $endpoint]
                        if {[llength $cell]!=1} {error "COMMON_IO reset reaches non-cell endpoint $endpoint"}
                        set ref [get_property REF_NAME $cell]; set pin [get_property REF_PIN_NAME $endpoint]
                        if {!(($ref in {FDCE FDPE} && $pin in {CLR PRE}) || ($ref in {MMCME3_ADV MMCME4_ADV PLLE3_ADV PLLE4_ADV} && $pin eq "RST"))} {error "COMMON_IO reset reaches unreviewed data/control $endpoint ($ref)"}
                    }
                }
                default {error "COMMON_IO unreviewed input without delay $port"}
            }
            puts $facts [list ASYNC_INPUT $port STRUCTURE_VERIFIED]
        }
        foreach port [dict get $coverage no_output_delay] {
            if {$port ni {uart_txd led eth_reset_gate eth_mdc eth_mdio}} {error "COMMON_IO unreviewed output without delay $port"}
            set budget 20.0
            set starts [all_fanin -flat -startpoints_only -to [get_ports $port]]
            if {![llength $starts]} {error "COMMON_IO output lacks registered source $port"}
            foreach start $starts {
                set cell [get_cells -quiet -of_objects $start]
                if {[llength $cell]!=1 || [get_property REF_NAME $cell] ni {FDCE FDPE FDRE FDSE} || [get_property REF_PIN_NAME $start] ne "C"} {error "COMMON_IO unknown output launch $port: $start"}
                set name [get_property NAME $cell]
                switch -- $port {
                    uart_txd {set allowed [expr {[string first u_soc/peripherals/uart/uart/ $name]==0}]; set budget [get_property PERIOD [get_clocks [common_cdc::clock $name/C]]]}
                    led {set allowed [expr {$name eq {ui_reset_pipe_reg[2]}}]}
                    eth_reset_gate {set allowed [regexp {^phy_reset_count_reg\[[0-9]+\]$} $name]}
                    eth_mdc {set allowed [expr {$name eq "u_soc/peripherals/gmac/mdio/mdc_reg"}]}
                    eth_mdio {set allowed [expr {[string first u_soc/peripherals/gmac/mdio/ $name]==0}]}
                }
                if {!$allowed} {error "COMMON_IO output source scope changed $port: $name"}
                set p [get_timing_paths -quiet -from $start -to [get_ports $port] -delay_type max -max_paths 1]
                if {[llength $p]!=1} {error "COMMON_IO missing registered output datapath bound $port: $name"}
                set req [get_property REQUIREMENT $p]; set slack [get_property SLACK $p]
                set exception [string tolower [string map {_ {} - {} { } {}} [get_property EXCEPTION $p]]]
                if {![string is double -strict $req] || ![string is double -strict $slack] || $req<=0 || $req>$budget+0.001 || $slack<0 || ![string match maxdelay* $exception]} {error "COMMON_IO missing/relaxed/failing async output bound $port: $name"}
            }
            puts $facts [list ASYNC_OUTPUT $port BOUND_NS=$budget SOURCES=[common_cdc::names $starts]]
        }
    } finally {close $facts}
}
proc common_board::run {} {
    global valence
    variable critical
    foreach key {root out profile_sha256 dcp_sha256} {if {![info exists valence($key)]} {error "COMMON_BOARD missing $key binding"}}
    set checks {}; set errors {}
    foreach {check commands} {rom_content_and_mapping {common_board::rom} cpu_selection {common_board::cpu} reset_cdc {common_board::resets; common_board::io; common_board::cdc}} {
        if {[catch {eval $commands} result]} {dict set checks $check BLOCKED; dict set errors $check $result} else {dict set checks $check PASS}
    }
    set status [expr {[dict size $errors] ? "BLOCKED" : "PASS"}]
    set scope "Exact CommonCpuClockBoundary Held capturedGray/writeGray, two-stage scalar synchronizers, time64 mailbox; functional u_soc local reset release; exact no-delay I/O endpoint allowances with bounded asynchronous outputs and zero partial min/max coverage; no waiver of any full-design report_cdc Critical. No board or all-operating-condition CDC signoff."
    set f [open [file join $valence(out) board-audit.json] w]
    puts $f [format {{"profile_sha256":%s,"dcp_sha256":%s,"status":%s,"checks":%s,"unreviewed_critical_cdc":%s,"cdc_review_scope":%s,"errors":%s}} [json $valence(profile_sha256)] [json $valence(dcp_sha256)] [json $status] [object $checks] $critical [json $scope] [object $errors]]
    close $f
    if {$status ne "PASS"} {error "COMMON_BOARD_AUDIT_BLOCKED: $errors"}
    puts "COMMON_BOARD_STRUCTURAL_AUDIT_PASS BOARD_NOT_TESTED"
}
if {![info exists ::common_board_definitions_only]} {common_board::run}
