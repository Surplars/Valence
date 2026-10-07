# HISTORICAL DDR50 ONLY. This is not the RV64GC100/native-GMAC/r6 release path.
# Firmware-only ECO: reject topology/config changes and preserve physical state.
# Current hardware changes require a fresh source-integrated full-board build.
# See bootrom-update-plan.md before selecting an update flow.
# Args: old ROM OOC DCP, new ROM OOC DCP, routed SoC DCP, fresh output directory.
if {$argc != 4 && $argc != 6} {
    error {Expected OLD_ROM_DCP NEW_ROM_DCP ROUTED_DCP OUTPUT_DIR [prepare-only SOC_DCP]}
}
lassign $argv old_ip new_ip routed out mode soc_dcp
if {$argc == 6 && $mode ne "prepare-only"} {error "Expected prepare-only mode"}
set out [file normalize $out]
if {[file exists $out]} {error "Preserve existing output; select a fresh output directory"}
foreach path [list $old_ip $new_ip $routed] {
    if {![file isfile $path] || ![file readable $path]} {error "Missing readable checkpoint: $path"}
}
if {$mode eq "prepare-only" && (![file isfile $soc_dcp] || ![file readable $soc_dcp])} {
    error "Missing readable logical SoC checkpoint"
}
if {[file normalize $old_ip] eq [file normalize $new_ip]} {error "Old and new ROM checkpoints must differ"}
set_param general.maxThreads 8

# Check the actual CPU endpoint before copying any INIT or writing any output.
# A legacy-named 50 MHz clock elsewhere in a 100 MHz board is not sufficient.
# In particular prepare-only must not bypass this guard.
proc require_legacy_ddr50 {} {
    if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong FPGA part"}
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved black boxes"}
    if {[llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] ||
        [llength [get_cells -quiet u_soc/nativeBank/gmac]]} {
        error "Legacy DDR50 ECO cannot update native RV64GC100/r6; see bootrom-update-plan.md"
    }
    set endpoint [get_pins -quiet u_soc/clock]
    if {[llength $endpoint] != 1} {error "Missing actual legacy CPU clock endpoint"}
    set actual [get_clocks -quiet -of_objects $endpoint]
    set named [get_clocks -quiet clk_out1_clk_wiz_ddr]
    if {[llength $actual] != 1 || [llength $named] != 1 ||
        [get_property NAME $actual] ne [get_property NAME $named] ||
        abs([get_property PERIOD $actual] - 20.0) > 0.0001 ||
        ![get_property IS_GENERATED $actual]} {
        error "Legacy DDR50 ECO requires the actual CPU endpoint at generated 50 MHz; native RV64GC100/r6 requires current full-board signoff"
    }
    set regions [get_pins -quiet {u_axi_cdc/s_axi_awregion* u_axi_cdc/s_axi_arregion*}]
    if {[llength $regions] != 8} {error "Missing legacy AXI REGION pins"}
    foreach pin $regions {
        set nets [get_nets -of_objects $pin]
        if {[llength $nets] != 1 || [get_property TYPE $nets] ne "GROUND"} {error "REGION not grounded"}
    }
}
open_checkpoint $routed
require_legacy_ddr50
close_design

# Whole-board physical snapshot, not merely the changed BRAM LOCs. No place,
# route, phys_opt, read_checkpoint -cell or timing-constraint commands run here.
proc snapshot_physical {} {
    set cells [dict create]
    foreach cell [lsort [get_cells -hier -filter {IS_PRIMITIVE == 1}]] {
        dict set cells [get_property NAME $cell] [list [get_property REF_NAME $cell] \
            [get_property LOC $cell] [get_property BEL $cell]]
    }
    set routes [dict create]
    foreach net [lsort [get_nets -hier]] {
        dict set routes [get_property NAME $net] [get_property ROUTE $net]
    }
    if {![dict size $cells] || ![dict size $routes]} {error "Empty physical snapshot"}
    return [list $cells $routes]
}
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
        # Compare every exposed primitive property, not a presentation-dependent
        # subset parsed from report_property. Unknown differences fail closed.
        foreach prop [lsort [list_property $cell]] {
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
dict for {cell values} $old_init {
    if {[lsort [dict keys $values]] ne [lsort [dict keys [dict get $new_init $cell]]]} {
        error "ROM INIT/INITP property set changed: $cell"
    }
}
if {[dict size $new_init] != 29} {error "Expected existing 29 BRAM ROM mapping"}
puts "BOOTROM_ECO: old/new IP topology and non-memory properties identical"
open_checkpoint $routed
require_legacy_ddr50
set physical_before [snapshot_physical]
set prefix {u_soc/platform/rom/memory/}
set targets [dict create]
foreach c [get_cells -hier -filter {REF_NAME =~ RAMB* && NAME =~ *rom*}] {
    set name [get_property NAME $c]
    if {![string equal -length [string length $prefix] $prefix $name]} {error "Unexpected ROM cell $name"}
    dict set targets [string range $name [string length $prefix] end] $c
}
if {[lsort [dict keys $targets]] ne [lsort [dict keys $old_init]]} {error "Routed ROM cell mapping differs"}
set changed 0
# Check ALL old values before changing anything: no stale/mismatched checkpoint.
dict for {name values} $old_init {
    set c [dict get $targets $name]
    dict for {prop value} $values {
        if {[get_property $prop $c] ne $value} {error "Original INIT mismatch: $c $prop"}
    }
}
file mkdir $out
set audit [open [file join $out rom_init_audit.txt] w]
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
if {[snapshot_physical] ne $physical_before} {error "Whole-board primitive placement or routing changed"}
puts $audit "INIT_AND_PHYSICAL_AUDIT_ONLY: 29 legacy ROM BRAMs; changed INIT properties=$changed; old/new OOC topology identical; whole-board REF/LOC/BEL/ROUTE unchanged"
close $audit
if {$changed == 0} {error "No memory changes; refusing stale build"}
puts "BOOTROM_ECO: patched $changed INIT properties, full readback matched"
if {$mode eq "prepare-only"} {
    write_checkpoint [file join $out bootrom_updated_routed.dcp]
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
    puts "BOOTROM_ECO: LEGACY_DDR50_PREPARED_NOT_SIGNED_OFF; full release_soc_partition signoff still required"
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
require_legacy_ddr50
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
# Save a direct-release checkpoint only after all legacy signoff gates pass.
if {[snapshot_physical] ne $physical_before} {error "Physical state changed during signoff"}
write_checkpoint [file join $out bootrom_updated_routed.dcp]
write_bitstream [file join $out valence_ddr50_bootrom_v01.bit]
write_debug_probes [file join $out valence_ddr50_bootrom_v01.ltx]
puts "BOOTROM_ECO: BITSTREAM COMPLETE [file join $out valence_ddr50_bootrom_v01.bit]"
close_design
