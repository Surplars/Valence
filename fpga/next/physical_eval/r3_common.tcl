# Shared helpers for exact R3 full-board synthesis and checkpoint-based placement.
proc r3_one {query pattern} {
    set objects [$query -quiet $pattern]
    if {[llength $objects] != 1} {error "Expected unique $query $pattern: $objects"}
    return $objects
}
proc r3_ref {ref} {
    set objects [get_cells -quiet -hier -filter "REF_NAME == $ref || ORIG_REF_NAME == $ref"]
    if {[llength $objects] != 1} {error "Expected unique module $ref: $objects"}
    return [get_property NAME $objects]
}
proc r3_discover {} {
    foreach {name ref} {V_SOC_ROOT FpgaNextSocTop V_BANK_ROOT ManagedPeripheralBank V_GMAC_ROOT TriSpeedManagedGmac V_RGMII_ROOT native_rgmii_trispeed_quarter V_ROM_ROOT InstructionRom} {
        set ::$name [r3_ref $ref]
    }
    set cells [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}]
    if {[llength $cells] != 1} {error "Require exactly one BSCANE2"}
    set ::V_BSCAN_PRIMITIVE [get_property NAME $cells]
    if {![regsub {([/.])user_scan$} $::V_BSCAN_PRIMITIVE {\1transport} ::V_BSCAN_ENGINE]} {error "Unknown BSCAN sibling layout"}
    r3_one get_cells $::V_BSCAN_ENGINE
    if {[get_property JTAG_CHAIN $cells] != 2} {error "USER2 required"}
    set f [open hierarchy-roots.txt w]
    foreach name {V_SOC_ROOT V_BANK_ROOT V_GMAC_ROOT V_RGMII_ROOT V_ROM_ROOT V_BSCAN_PRIMITIVE V_BSCAN_ENGINE} {
        puts $f "$name=[set ::$name]"
        puts "R3_DISCOVERED $name=[set ::$name]"
    }
    close $f
}
proc r3_rom_dump {path} {
    set cells [get_cells -quiet -hier -filter "NAME =~ $::V_ROM_ROOT/memory/* && (REF_NAME == RAMB36E2 || REF_NAME == RAMB18E2)"]
    if {![llength $cells]} {error "Missing actual ROM BRAM primitives"}
    set f [open $path w]
    foreach cell [lsort -dictionary $cells] {
        puts $f "CELL\t[get_property NAME $cell]\t[get_property REF_NAME $cell]"
        foreach prop [lsort [list_property $cell]] {
            if {[regexp {^(INIT|INITP)_[0-9A-Fa-f]+$|^READ_WIDTH_[AB]$|^WRITE_WIDTH_[AB]$|^RAM_MODE$|^DO[AB]_REG$|^RAM_EXTENSION_[AB]$} $prop]} {
                puts $f "$prop\t[get_property $prop $cell]"
            }
        }
    }
    close $f
}
proc r3_source_bound {path} {
    set f [open $path];set body [read $f];close $f
    set pairs [list u_soc/board/nativeBank/gmac $::V_GMAC_ROOT u_soc/board/nativeBank $::V_BANK_ROOT u_soc/board/platform/rom $::V_ROM_ROOT u_soc $::V_SOC_ROOT u_rgmii $::V_RGMII_ROOT]
    set actual [string map $pairs $body]
    set f [open [file join [pwd] bound-[file tail $path]] w];puts -nonewline $f $actual;close $f
    uplevel #0 $actual
}
proc r3_reports {directory cpuClock} {
    file mkdir $directory
    report_utilization -hierarchical -file [file join $directory utilization.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $directory timing_summary.rpt]
    foreach {delay name} {max setup min hold} {
        report_timing -delay_type $delay -max_paths 40 -nworst 3 -input_pins -path_type full_clock_expanded -file [file join $directory ${name}_paths.rpt]
        report_timing -from $cpuClock -to $cpuClock -delay_type $delay -max_paths 40 -nworst 3 -input_pins -path_type full_clock_expanded -file [file join $directory cpu_${name}.rpt]
    }
    report_clocks -file [file join $directory clocks.rpt]
    check_timing -verbose -file [file join $directory check_timing.rpt]
    report_clock_interaction -file [file join $directory clock_interaction.rpt]
    report_exceptions -coverage -file [file join $directory exceptions.rpt]
    report_drc -file [file join $directory drc.rpt]
    report_cdc -details -file [file join $directory cdc.rpt]
    set f [open [file join $directory timing_numeric.tsv] w]
    foreach {kind query} {setup {get_timing_paths -delay_type max -max_paths 1} hold {get_timing_paths -delay_type min -max_paths 1}} {
        set paths [uplevel #0 $query]
        if {[llength $paths]!=1} {error "Missing $kind timing path"}
        puts $f "$kind\t[get_property SLACK $paths]"
    }
    close $f
}
