# Firmware-only ECO. Reject any ROM IP topology/config change, keep all placement/routing.
# Args: old ROM OOC DCP, new ROM OOC DCP, routed SoC DCP, empty output directory.
if {$argc != 4 && $argc != 6} {
    error "Expected OLD_ROM_DCP NEW_ROM_DCP ROUTED_DCP OUTPUT_DIR [prepare-only SOC_DCP]"
}
lassign $argv old_ip new_ip routed out mode soc_dcp
if {$argc == 6 && $mode ne "prepare-only"} {error "Expected prepare-only mode"}
file mkdir $out
set_param general.maxThreads 8
proc is_mem_init {p} {return [regexp {^INIT(P)?_[0-9A-F]{2}$} $p]}
proc snapshot_rom {dcp} {
    open_checkpoint $dcp
    set shape [dict create]
    set contents [dict create]
    foreach cell [lsort [get_cells -hier -filter {IS_PRIMITIVE == 1}]] {
        set name [get_property NAME $cell]
        set ref [get_property REF_NAME $cell]
        set config [dict create REF_NAME $ref]
        set init [dict create]
        foreach line [split [report_property -return_string $cell] "\n"] {
            if {![regexp {^\s*(\S+)\s+\S+\s+false\s+} $line -> prop]} {continue}
            if {[string match RAMB* $ref] && [is_mem_init $prop]} {
                dict set init $prop [get_property $prop $cell]
            } else {
                dict set config $prop [get_property $prop $cell]
            }
        }
        set wiring [dict create]
        foreach pin [lsort [get_pins -of_objects $cell]] {
            set nets [get_nets -quiet -of_objects $pin]
            set names {}
            foreach net $nets {lappend names [get_property NAME $net]}
            dict set wiring [get_property REF_PIN_NAME $pin] [lsort $names]
        }
        dict set shape $name [list $config $wiring]
        if {[dict size $init]} {dict set contents $name $init}
    }
    set ports [dict create]
    foreach p [lsort [get_ports]] {
        set names {}
        foreach net [get_nets -quiet -of_objects $p] {lappend names [get_property NAME $net]}
        dict set ports [get_property NAME $p] [list [get_property DIRECTION $p] [lsort $names]]
    }
    close_design
    return [list $shape $contents $ports]
}
lassign [snapshot_rom $old_ip] old_shape old_init old_ports
lassign [snapshot_rom $new_ip] new_shape new_init new_ports
if {[dict keys $old_shape] ne [dict keys $new_shape]} {error "ROM primitive set changed; full implementation required"}
foreach cell [dict keys $old_shape] {
    if {[dict get $old_shape $cell] ne [dict get $new_shape $cell]} {
        error "ROM configuration or wiring changed: $cell; full implementation required"
    }
}
if {$old_ports ne $new_ports} {error "ROM port connections changed"}
if {[dict keys $old_init] ne [dict keys $new_init]} {error "ROM BRAM set changed"}
if {[dict size $new_init] != 29} {error "Expected existing 29 BRAM ROM mapping"}
puts "BOOTROM_ECO: old/new IP topology and non-memory properties identical"
open_checkpoint $routed
set prefix {u_soc/platform/rom/memory/}
set targets [dict create]
foreach c [get_cells -hier -filter {REF_NAME =~ RAMB* && NAME =~ *rom*}] {
    set name [get_property NAME $c]
    if {![string equal -length [string length $prefix] $prefix $name]} {error "Unexpected ROM cell $name"}
    dict set targets [string range $name [string length $prefix] end] $c
}
if {[lsort [dict keys $targets]] ne [lsort [dict keys $old_init]]} {error "Routed ROM cell mapping differs"}
set audit [open [file join $out rom_init_audit.txt] w]
set changed 0
# Check ALL old values before changing anything: no stale/mismatched checkpoint.
dict for {name values} $old_init {
    set c [dict get $targets $name]
    dict for {prop value} $values {
        if {[get_property $prop $c] ne $value} {error "Original INIT mismatch: $c $prop"}
    }
}
dict for {name values} $new_init {
    set c [dict get $targets $name]
    set location [get_property LOC $c]
    dict for {prop value} $values {
        if {[get_property $prop $c] ne $value} {
            set_property $prop $value $c
            incr changed
        }
        if {[get_property $prop $c] ne $value} {error "INIT readback failed: $c $prop"}
    }
    if {[get_property LOC $c] ne $location} {error "Placement unexpectedly changed"}
    puts $audit "$name: all [dict size $values] INIT/INITP properties match new IP; LOC=$location"
}
puts $audit "PASS: 29 ROM BRAMs; changed INIT properties=$changed; no topology, placement or routing changes"
close $audit
if {$changed == 0} {error "No memory changes; refusing stale build"}
puts "BOOTROM_ECO: patched $changed INIT properties, full readback matched"
write_checkpoint [file join $out bootrom_updated_routed.dcp]
if {$mode eq "prepare-only"} {
    # Keep the logical reference partition in sync with the same firmware ECO.
    # The normal release flow then repeats timing, CDC/reset and all INIT checks.
    close_design
    open_checkpoint $soc_dcp
    set prefix {platform/rom/memory/}
    dict for {name values} $old_init {
        set cell [get_cells -quiet "${prefix}${name}"]
        if {[llength $cell] != 1} {error "Missing logical ROM primitive: $name"}
        dict for {prop value} $values {
            if {[get_property $prop $cell] ne $value} {error "Logical ROM baseline mismatch: $name/$prop"}
        }
    }
    dict for {name values} $new_init {
        set cell [get_cells "${prefix}${name}"]
        dict for {prop value} $values {
            set_property $prop $value $cell
            if {[get_property $prop $cell] ne $value} {error "Logical ROM readback failed: $name/$prop"}
        }
    }
    write_checkpoint [file join $out bootrom_updated_soc.dcp]
    close_design
    puts "BOOTROM_ECO: PREPARED; full release_soc_partition signoff still required"
    return
}
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $out timing_paths.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_drc -ruledeck bitstream_checks -file [file join $out bitstream_drc.rpt]
set bad_drc [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {[llength $bad_drc]} {error "Bitstream DRC errors/critical warnings: $bad_drc"}
proc read_text {path} {set f [open $path r]; set t [read $f]; close $f; return $t}
set skew [read_text [file join $out bus_skew.rpt]]
if {[string first "VIOLATED" $skew] >= 0 || [regexp -all {Slack \(MET\)} $skew] != 14} {
    error "Expected all 14 bus-skew constraints to pass"
}
set timing [read_text [file join $out timing_summary.rpt]]
set summary {}
foreach line [split $timing "\n"] {
    if {[regexp {^\s*-?[0-9]+\.[0-9]+\s+-?[0-9]+\.[0-9]+\s+[0-9]+\s+[0-9]+\s+-?[0-9]+\.[0-9]+} $line]} {
        set summary [regexp -all -inline {[-]?[0-9]+(?:\.[0-9]+)?} $line]
        break
    }
}
if {[llength $summary] != 12} {error "Cannot validate timing summary: $summary"}
foreach index {0 4 8} {
    if {[lindex $summary $index] < 0} {error "Timing failed: $summary"}
}
foreach index {1 2 5 6 9 10} {
    if {[lindex $summary $index] != 0} {error "Timing violations: $summary"}
}
foreach delay {min max} {
    set paths [get_timing_paths -delay_type $delay -max_paths 1]
    if {[llength $paths] != 1 || [get_property SLACK $paths] < 0} {error "$delay slack fails"}
}
set cpu_clock [get_clocks clk_out1_clk_wiz_ddr]
if {[llength $cpu_clock] != 1 || abs([get_property PERIOD $cpu_clock] - 20.0) > 0.0001} {error "CPU is not constrained to 50 MHz"}
foreach check {no_clock unconstrained_internal_endpoints loops latch_loops} {
    if {![regexp [format {checking %s \(0\)} $check] $timing]} {error "Timing coverage fails: $check"}
}
set route [read_text [file join $out route_status.rpt]]
foreach {label variable} {"routable nets" routable "fully routed nets" fully "nets with routing errors" errors} {
    if {![regexp [format {%s\.+\s*:\s*([0-9]+)} $label] $route -> $variable]} {error "Missing route statistic $label"}
}
if {$routable != $fully || $errors != 0} {error "Routing not clean"}
set regions [get_pins -quiet {u_axi_cdc/s_axi_awregion* u_axi_cdc/s_axi_arregion*}]
if {[llength $regions] != 8} {error "Missing REGION pins"}
foreach p $regions {
    if {[get_property TYPE [get_nets -of_objects $p]] ne "GROUND"} {error "REGION not grounded"}
}
puts "BOOTROM_ECO: timing PASS WNS=[lindex $summary 0] WHS=[lindex $summary 4] WPWS=[lindex $summary 8]; routing and DRC PASS"
write_bitstream [file join $out valence_ddr50_bootrom_v01.bit]
write_debug_probes [file join $out valence_ddr50_bootrom_v01.ltx]
puts "BOOTROM_ECO: BITSTREAM COMPLETE [file join $out valence_ddr50_bootrom_v01.bit]"
close_design
