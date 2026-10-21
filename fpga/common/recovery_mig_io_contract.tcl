# Existing OOC MIG owns physical IO. A plain synth_stub import can infer a
# second top-level buffer; remove only a proved, otherwise unused 1:1 bridge.
# No clock routing overrides, pin invention, IP regeneration or RTL changes.
namespace eval recovery_mig_io {}
source [file join [file dirname [info script]] .. .. recovery mig-io-reference.tcl]
proc recovery_mig_io::names {objects} {
    if {![llength $objects]} {return {}}
    return [lsort -unique [get_property NAME $objects]]
}
proc recovery_mig_io::one {kind name} {
    set objects [$kind -quiet $name]
    if {[names $objects] ne [list $name]} {error "MIG_IO missing exact $kind $name"}
    return [lindex $objects 0]
}
proc recovery_mig_io::net {object} {
    set nets [get_nets -quiet -of_objects $object]
    if {[llength $nets]!=1} {error "MIG_IO expected one outer net: $object"}
    return [lindex $nets 0]
}
proc recovery_mig_io::apply {} {
    variable reference
    set mig [one get_cells u_ddr]
    if {[get_property REF_NAME $mig] ne {ddr4_0}} {error {MIG_IO wrong IP reference}}
    set plans {};set seen {}
    # Inspect every physical pin before performing any edit.
    foreach mp [get_pins -of_objects $mig] {
        set tail [get_property REF_PIN_NAME $mp]
        if {[string match c0_sys_clk_* $tail]} {
            set pn [dict get {c0_sys_clk_p clk_in1_p c0_sys_clk_n clk_in1_n} $tail]
        } elseif {[dict exists $reference $tail]} {set pn $tail} else {continue}
        lappend seen $pn
        set port [one get_ports $pn]
        lassign [dict get $reference $pn] package standard
        if {[get_property PACKAGE_PIN $port] ne $package} {error "MIG_IO board pin mismatch $pn"}
        set inner [net $mp];set outer [net $port]
        if {[names [get_ports -quiet -of_objects [get_nets -segments -of_objects $mp]]] eq [list $pn]} {
            continue
        }
        set role [get_property DIRECTION $port]
        if {$role eq {IN}} {set ref IBUF;set pad I;set core O} elseif {$role eq {OUT}} {
            set ref OBUF;set pad O;set core I
        } else {error "MIG_IO unreviewed inout bridge $pn"}
        set outer_pins [get_pins -quiet -of_objects $outer]
        if {[llength $outer_pins]!=1} {error "MIG_IO pad net not a single bridge pin $pn: [names $outer_pins]"}
        set bridge [get_cells -of_objects $outer_pins]
        set bn [get_property NAME $bridge]
        if {[llength $bridge]!=1 || [string first / $bn]>=0 || [get_property REF_NAME $bridge] ne $ref ||
            [get_property REF_PIN_NAME $outer_pins] ne $pad} {error "MIG_IO unexpected pad bridge $pn: $bn"}
        set bp [one get_pins $bn/$core]
        if {[net $bp] ne $inner || [names [get_pins -quiet -of_objects $inner]] ne [lsort [list [get_property NAME $mp] $bn/$core]]} {
            error "MIG_IO bridge core net has extra connection: $pn"
        }
        lappend plans [list $pn [get_property NAME $mp] $bn [get_property NAME $inner]]
    }
    if {[lsort $seen] ne [lsort [dict keys $reference]]} {error {MIG_IO incomplete physical port census}}
    if {[llength $plans] ni {0 29}} {error "MIG_IO unexpected bridge census [llength $plans]"}
    foreach row $plans {
        lassign $row pn mp bn inner
        disconnect_net -net [one get_nets $inner] -objects [one get_pins $mp]
        remove_cell [one get_cells $bn]
        connect_net -hierarchical -net [net [one get_ports $pn]] -objects [one get_pins $mp]
        puts "MIG_IO_REMOVED_EXACT_DUPLICATE_BUFFER $bn direct_top=$pn mig_pin=$mp"
    }
    foreach row $plans {
        lassign $row pn mp bn inner
        if {[names [get_ports -quiet -of_objects [get_nets -segments -of_objects [one get_pins $mp]]]] ne [list $pn]} {
            error "MIG_IO repaired port is not direct: $pn"
        }
    }
    puts "MIG_IO_DIRECT_CONNECTIVITY_REPAIRED bridges=[llength $plans] physical_ports=[llength $seen]"
    return $plans
}
proc recovery_mig_io::verify_electrical {} {
    variable reference
    dict for {pn expected} $reference {
        lassign $expected package standard
        set p [one get_ports $pn]
        if {[get_property PACKAGE_PIN $p] ne $package || [get_property IOSTANDARD $p] ne $standard} {
            error "MIG_IO physical contract mismatch $pn: pin=[get_property PACKAGE_PIN $p] standard=[get_property IOSTANDARD $p] expected=$expected"
        }
    }
    puts "MIG_IO_ELECTRICAL_REFERENCE_MATCH ports=[dict size $reference]"
}
