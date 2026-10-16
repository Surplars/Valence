# EXPERIMENT ONLY. Sourcing defines a procedure; it changes no design state.
# Invoke explicitly before place_design in a fresh, already audited T1 build.
# No RTL, clock, timing exception, LOC or BEL changes. Not timing qualification.
namespace eval valence_reset_distribution {}

proc valence_reset_distribution::snapshot {hier} {
    set source [get_cells -quiet $hier/pad_release.pad_release_reset_reg]
    if {[llength $source] != 1 || [get_property REF_NAME $source] ne "FDPE" ||
        [get_property INIT $source] ne "1'b1" ||
        [get_property IS_INVERTED [get_pins $source/C]] ni {1 1'b1}} {
        error "Require original falling-edge preset-high T1 release FF"
    }
    set result {}
    foreach pin {C PRE CE D Q} {
        set net [get_nets -segments -of_objects [get_pins $source/$pin]]
        if {![llength $net]} {error "Missing release $pin net"}
        dict set result $pin [lsort $net]
    }
    if {[get_property TYPE [get_nets -of_objects [get_pins $source/D]]] ne "GROUND" ||
        [get_property TYPE [get_nets -of_objects [get_pins $source/CE]]] ne "POWER"} {
        error "Release D/CE must remain constant zero/one"
    }
    set clocks [get_clocks -of_objects [get_pins $source/C]]
    if {[llength $clocks] != 1} {error "Require one timed PAD clock"}
    lassign [get_property WAVEFORM $clocks] rise fall
    if {abs([get_property PERIOD $clocks]-4.0)>0.001 ||
        abs($rise)>0.001 || abs($fall-2.0)>0.001} {error "Require unchanged PAD250 phase"}
    dict set result clocks [list $clocks [get_property PERIOD $clocks] [get_property WAVEFORM $clocks]]
    set sinks [lsort [get_pins -leaf -of_objects [dict get $result Q] -filter {DIRECTION == IN}]]
    set expected [list $hier/phase_high_reg/PRE $hier/previous_clock_reg/CLR $hier/low_clock_reg/CLR $hier/high_clock_reg/CLR $hier/tx_clock_ddr/RST]
    for {set n 0} {$n < 5} {incr n} {
        lappend expected [format {%s/low_symbol_reg[%d]/CLR} $hier $n]
        lappend expected [format {%s/high_symbol_reg[%d]/CLR} $hier $n]
        lappend expected [format {%s/transmit[%d].data_ddr/RST} $hier $n]
    }
    if {$sinks ne [lsort $expected]} {error "Require exactly the original twenty shared-reset loads"}
    dict set result sinks $sinks
    set driver [get_pins -leaf -of_objects [dict get $result PRE] -filter {DIRECTION == OUT}]
    if {[llength $driver] != 1} {error "Require one upstream PRE driver"}
    dict set result upstream $driver
    return $result
}

proc valence_reset_distribution::apply {hier region} {
    # No default region or top-level call: selection must be explicit.
    if {![regexp {^SLICE_X([0-9]+)Y([0-9]+):SLICE_X([0-9]+)Y([0-9]+)$} $region all x0 y0 x1 y1] ||
        $x1 < $x0 || $y1 < $y0 || ($x1-$x0+1)*($y1-$y0+1)>256} {
        error "Require an explicit ordered SLICE region of at most 256 sites"
    }
    # Existing production proof remains mandatory; never weaken it for this test.
    valence_trispeed_quarter_audit $hier 1
    set before [snapshot $hier]
    set source [get_cells -quiet $hier/pad_release.pad_release_reset_reg]
    if {[get_property IS_LOC_FIXED $source] || [get_property IS_BEL_FIXED $source] ||
        [llength [get_pblocks -quiet -of_objects $source]]} {
        error "Do not override existing placement ownership"
    }
    set name valence_rgmii_reset_distribution_candidate
    if {[llength [get_pblocks -quiet $name]]} {error "Candidate pblock already exists"}
    set sites {}
    for {set x $x0} {$x <= $x1} {incr x} {
        for {set y $y0} {$y <= $y1} {incr y} {
            set site [get_sites -quiet SLICE_X${x}Y${y}]
            if {[llength $site] != 1 || [get_property SITE_TYPE $site] ni {SLICEL SLICEM}} {
                error "Region contains a missing or non-SLICE site"
            }
            lappend sites $site
        }
    }
    set regions [get_clock_regions -of_objects $sites]
    if {[llength $regions] != 1} {error "Candidate must stay within one clock region"}
    # Let place_design choose a legal FF/control set; do not force same-SLICE packing.
    create_pblock $name
    resize_pblock [get_pblocks $name] -add $region
    add_cells_to_pblock [get_pblocks $name] $source
    set_property IS_SOFT false [get_pblocks $name]
    if {[snapshot $hier] ne $before || [get_cells -of_objects [get_pblocks $name]] ne $source} {
        error "Candidate changed connectivity or included another cell; discard this experimental build"
    }
    puts "EXPERIMENT_ONLY reset_source_region=$region clock_region=$regions upstream_PRE=[dict get $before upstream] loads=20 physical_qualification=pending"
    return $before
}
